"""Train and evaluate the System 1 ``progress`` family (DONE / PARTIAL / NOT_STARTED), leave-one-task-out.

The model is the deployed GLiClass bundle's trained weights (``expanded-v2``: dictation + retrospective) continued
on the progress rows of :mod:`suite.progress_dataset`, with the old TRAIN rows replayed every epoch so the existing
families keep their heads. One model serves all three families; the progress family uses three native labels, the old
ones two.

    fold   --holdout TASK   train on the other five tasks (+ replay), score the held-out task natively
    final                   train on all six tasks (+ replay), save the native reference
    export                  ONNX + INT4 of the final model (three native class slots)
    eval-onnx               old-family regression + progress fidelity and CPU latency on the INT4 graph
    report                  leave-one-task-out table vs the majority baseline; ONNX regression + CPU latency

Training runs on the RTX 3090 only (``CUDA_VISIBLE_DEVICES`` must be its UUID), through the pipeline's own
:mod:`suite.gliclass_train` building blocks. Outputs live under ``~/.cria/test-runs/outputs/research/progress-v1``, never the repo.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

from cria import prompts
from suite.onejev_probe import append, file_sha, frozen_policy
from suite.progress_dataset import LABELS as PROGRESS_LABELS
from suite.progress_dataset import OUT as DATA
from suite.progress_dataset import render_state as progress_state
from suite.training_updates import LABEL_ORDER, sha

GPU_UUID = "GPU-907a7f7a-b541-8208-2bce-e1361e3110d6"
BASE = Path("~/.cria/training/gliclass-v4-edge-expanded-v2/train-001").expanduser()
OLD_V1 = Path("~/.cria/training/gliclass-v4-edge-v1/train-001").expanduser()
TASKS = ("cart-billing-go", "feed-pipeline-java", "handles-cli-node", "orders-api-py", "rust-toml-cli", "shipping-rates-rb")
#: the longest whole input trained or scored. MEASURED on the 24 GiB RTX 3090 (gradient checkpointing, bf16): a
#: 3,963-token step peaks at 18.8 GiB and takes 3.2 s; ~4,800 tokens runs out of memory (attention is quadratic).
#: Longer rows are NOT clipped: they are dropped and counted (cria.system1.token_ceiling is 6,711 at its 16 GiB arena).
MAX_TOKENS = 4096
CLASSES = len(PROGRESS_LABELS)
LABELS_OF = {**{k: tuple(v) for k, v in LABEL_ORDER.items()}, "progress": tuple(PROGRESS_LABELS)}


def labels_for(family: str) -> tuple[str, ...]:
    return LABELS_OF[family]


def progress_policy() -> str:
    return prompts.load("offline_onejev_progress") + "\n"


def f1_report(truth: list[str], pred: list[str], labels=PROGRESS_LABELS) -> dict:
    """Accuracy, macro-F1 and the confusion matrix (rows = truth, columns = prediction, in ``labels`` order)."""
    matrix = [[0] * len(labels) for _ in labels]
    for t, p in zip(truth, pred):
        matrix[labels.index(t)][labels.index(p)] += 1
    f1s = []
    for i in range(len(labels)):
        tp = matrix[i][i]
        fp = sum(matrix[r][i] for r in range(len(labels))) - tp
        fn = sum(matrix[i]) - tp
        f1s.append(0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn))
    n = len(truth)
    return {"count": n, "accuracy": sum(matrix[i][i] for i in range(len(labels))) / n if n else None,
            "macro_f1": sum(f1s) / len(labels), "per_label_f1": dict(zip(labels, f1s)), "confusion": matrix}


def majority_baseline(train_labels: list[str], test_labels: list[str]) -> dict:
    """Predict the training set's most common label for every test row."""
    majority = Counter(train_labels).most_common(1)[0][0]
    return {"label": majority, **f1_report(test_labels, [majority] * len(test_labels))}


# ----------------------------------------------------------------------------- rows

def load_progress(path: Path = DATA / "dataset.jsonl") -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        r = json.loads(line)
        rows.append({**r, "family": "progress", "complete_input": progress_state(r["requirement"], r["evidence"])})
    return rows


def load_replay() -> list[dict]:
    """The old dictation + retrospective TRAIN rows (836), exactly as the deployed bundle was trained."""
    from suite.gliclass_probe import load_frozen_cohorts
    _contract, train, held = load_frozen_cohorts(BASE)
    return train


def policy_text(family: str, hashes: dict) -> str:
    return progress_policy() if family == "progress" else frozen_policy(family, hashes[family])


def encode(pipe, row: dict, hashes: dict, order: tuple[str, ...]):
    from suite.gliclass_probe import render_state
    text = render_state(row["complete_input"])
    return pipe.prepare_inputs([text], list(order), same_labels=True, prompt=policy_text(row["family"], hashes))


def token_lengths(pipe, rows: list[dict], hashes: dict, cache: Path) -> dict[str, int]:
    """Native rendered-input length of every row, cached (the lengths never change for the same rows)."""
    known = json.loads(cache.read_text()) if cache.exists() else {}
    from suite.gliclass_probe import render_state
    for r in rows:
        if r["id"] not in known:
            rendered = pipe.prepare_input(render_state(r["complete_input"]), list(labels_for(r["family"])),
                                          prompt=policy_text(r["family"], hashes))
            known[r["id"]] = len(pipe.tokenizer(rendered, truncation=False)["input_ids"])
    cache.write_text(json.dumps(known))
    return known


def group_weights(rows: list[dict]) -> dict[str, float]:
    """N / (K * n): every (task, family, label) group carries the same total weight (the pipeline's balancing)."""
    counts = Counter((r["task"], r["family"], r["label"]) for r in rows)
    return {r["id"]: len(rows) / (len(counts) * counts[r["task"], r["family"], r["label"]]) for r in rows}


# ----------------------------------------------------------------------------- DeBERTa gather backward

def monotone_gather_class(torch):
    """``torch.gather`` over the last dim whose BACKWARD avoids ``scatter_add_``.

    DeBERTa's relative-position attention gathers a [N, L, 2K] score table with an [N, L, L] index that is the same
    for every one of the N batch*head slices and monotone along each row (it is a clamped, log-bucketed ``i - j``).
    The stock backward is a ``scatter_add_`` onto L*L atomically-contended slots: MEASURED 61% of a training step
    (0.76 of 1.25 s at 2,087 tokens). Because the index is monotone, each output slot's gradient is a contiguous run
    of the incoming gradient, i.e. a difference of two entries of its cumulative sum. Same gradient, no atomics.
    Anything that is not that shape falls back to the stock gather."""
    class MonotoneGather(torch.autograd.Function):
        @staticmethod
        def forward(ctx, source, index):
            ctx.row = index[0]
            ctx.slots = source.shape[-1]
            ctx.source_dtype = source.dtype
            return torch.gather(source, -1, index)

        @staticmethod
        def backward(ctx, grad):
            row, slots = ctx.row, ctx.slots
            descending = bool((row[:, 1:] <= row[:, :-1]).all()) and not bool((row[:, 1:] == row[:, :-1]).all())
            g = grad.float()
            if descending:
                row, g = row.flip(-1), g.flip(-1)
            keys = torch.arange(slots, device=row.device).expand(row.shape[0], slots).contiguous()
            start = torch.searchsorted(row.contiguous(), keys, right=False)
            end = torch.searchsorted(row.contiguous(), keys, right=True)
            cumulative = torch.nn.functional.pad(g.cumsum(-1), (1, 0))
            out = cumulative.gather(-1, end.expand(g.shape[0], -1, -1)) - cumulative.gather(-1, start.expand(g.shape[0], -1, -1))
            return out.to(ctx.source_dtype), None

    def gather(source, dim, index, **kwargs):
        row = index[0] if index.dim() == 3 and index.stride(0) == 0 else None
        if (row is None or dim not in (-1, source.dim() - 1) or kwargs or not source.requires_grad
                or not (bool((row[:, 1:] >= row[:, :-1]).all()) or bool((row[:, 1:] <= row[:, :-1]).all()))):
            return torch.gather(source, dim, index, **kwargs)
        return MonotoneGather.apply(source, index)

    return gather


def install_fast_gather(torch) -> None:
    """Route the DeBERTa-v2 attention module's ``torch.gather`` calls through :func:`monotone_gather_class`."""
    import types
    from transformers.models.deberta_v2 import modeling_deberta_v2 as module
    fast = monotone_gather_class(torch)

    class Shim(types.ModuleType):
        def __getattr__(self, name):
            return fast if name == "gather" else getattr(torch, name)

    module.torch = Shim("torch")


# ----------------------------------------------------------------------------- GPU work

def _setup_torch(deterministic: bool):
    if os.environ.get("CUDA_VISIBLE_DEVICES") != GPU_UUID:
        raise ValueError("only the approved RTX 3090 may be visible (CUDA_VISIBLE_DEVICES)")
    import torch
    if torch.cuda.device_count() != 1 or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3090":
        raise ValueError("wrong GPU")
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(deterministic)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    install_fast_gather(torch)
    return torch


def _logits(torch, model, inputs, classes, *, precision='bf16'):
    with torch.autocast("cuda", dtype=torch.bfloat16, enabled=precision=='bf16'):
        return model(**inputs, max_num_classes=classes).logits[0, :classes].float()


def score_rows(torch, model, pipe, rows, hashes, path: Path) -> list[dict]:
    """Native FP32 decisions in the canonical label order (what the runtime asks)."""
    model.eval()
    out = []
    with torch.no_grad():
        for r in rows:
            labels = labels_for(r["family"])
            inputs = encode(pipe, r, hashes, labels)
            logits = model(**inputs, max_num_classes=len(labels)).logits[0, :len(labels)].float().cpu()
            rec = {"id": r["id"], "task": r["task"], "family": r["family"], "label": r["label"],
                   "prediction": labels[int(logits.argmax())], "logits": logits.tolist(),
                   "tokens": int(inputs["input_ids"].shape[1])}
            append(path, rec)
            out.append(rec)
    model.train()
    return out


def train_model(torch, rows, hashes, *, epochs, lr, progress_per_epoch, replay_per_epoch=0, accumulation, log: Path, seed=17):
    from suite.gliclass_train import load_for_training, trainable_membership
    from suite.onejev_train import loss_at_slots, lr_at
    from suite.training_updates import accumulated_update
    snapshot = str(BASE / "reference")
    model, pipe, optimizer, loading, _inactive = load_for_training(torch, snapshot)
    weights = group_weights(rows)
    old = [r for r in rows if r["family"] != "progress"]
    new = [r for r in rows if r["family"] == "progress"]
    per_epoch = min(progress_per_epoch, len(new)) if progress_per_epoch else len(new)
    replayed = min(replay_per_epoch, len(old)) if replay_per_epoch else len(old)
    total = epochs * math.ceil((replayed + per_epoch) / accumulation)
    rng = random.Random(seed)
    started = time.monotonic()
    step = tokens_seen = 0
    for epoch in range(epochs):
        order = (rng.sample(old, min(replay_per_epoch, len(old))) if replay_per_epoch else list(old)) + rng.sample(new, per_epoch)
        rng.shuffle(order)
        append(log, {"event": "epoch_start", "epoch": epoch, "rows": len(order), "progress_rows": per_epoch})
        for offset in range(0, len(order), accumulation):
            batch = []
            for i, r in enumerate(order[offset:offset + accumulation]):
                labels = labels_for(r["family"])
                perms = list(itertools.permutations(labels))
                perm = perms[(epoch * 7 + offset + i) % len(perms)]
                inputs = encode(pipe, r, hashes, perm)
                tokens_seen += int(inputs["input_ids"].shape[1])
                batch.append({"id": r["id"], "inputs": inputs, "target": perm.index(r["label"]), "classes": len(labels)})
            event = accumulated_update(torch, model, optimizer, batch, weights,
                                       lambda row: _logits(torch, model, row["inputs"], row["classes"]),
                                       loss_at_slots, lr_at(step, total, lr))
            step += 1
            if step % 10 == 0 or step == total:
                append(log, {"event": "update", "step": step, "of": total, "tokens": tokens_seen,
                             "seconds": time.monotonic() - started,
                             "gpu_peak_gib": torch.cuda.max_memory_reserved() / 1024**3, **event})
                print(json.dumps({"step": step, "of": total, **event}), flush=True)
    del optimizer
    return model, pipe, {"updates": step, "seconds": time.monotonic() - started, "tokens": tokens_seen, "loading": loading}


def common_setup(args):
    from suite.gliclass_probe import load_frozen_cohorts
    contract, _train, _held = load_frozen_cohorts(BASE)
    hashes = dict(contract["policy_sha256"])
    return contract, hashes


def fit_filter(rows, lengths):
    kept = [r for r in rows if lengths[r["id"]] <= MAX_TOKENS]
    return kept, [r["id"] for r in rows if lengths[r["id"]] > MAX_TOKENS]


def prepare(args):
    """(hashes, progress rows that fit, ids that do not, replay rows) with lengths cached beside the dataset."""
    torch = _setup_torch(args.deterministic)
    from suite.gliclass_probe import load_native
    _contract, hashes = common_setup(args)
    _model, pipe, _ = load_native(str(BASE / "reference"), "cpu")
    del _model
    rows = load_progress()
    lengths = token_lengths(pipe, rows, hashes, DATA / "token-lengths.json")
    kept, dropped = fit_filter(rows, lengths)
    return torch, hashes, kept, dropped, load_replay()


def cmd_fold(args):
    out = DATA / "loto" / f"fold-{args.holdout}{args.tag}"
    if (out / "done.json").exists():
        print("fold already complete", out)
        return
    out.mkdir(parents=True, exist_ok=True)
    torch, hashes, kept, dropped, replay = prepare(args)
    train = [r for r in kept if r["task"] != args.holdout] + replay
    test = [r for r in kept if r["task"] == args.holdout]
    (out / "predictions.jsonl").unlink(missing_ok=True)
    model, pipe, info = train_model(torch, train, hashes, epochs=args.epochs, lr=args.lr,
                                    progress_per_epoch=args.progress_per_epoch, replay_per_epoch=args.replay_per_epoch,
                                    accumulation=args.accumulation, log=out / "events.jsonl")
    scored = score_rows(torch, model, pipe, test, hashes, out / "predictions.jsonl")
    (out / "done.json").write_text(json.dumps({
        "holdout": args.holdout, "train_progress_rows": sum(r["family"] == "progress" for r in train),
        "replay_rows": len(replay), "test_rows": len(test), "no_fit_dropped_ids": dropped,
        "epochs": args.epochs, "lr": args.lr, "progress_per_epoch": args.progress_per_epoch,
        "replay_per_epoch": args.replay_per_epoch, "accumulation": args.accumulation,
        "report": f1_report([s["label"] for s in scored], [s["prediction"] for s in scored]),
        **{k: v for k, v in info.items() if k != "loading"}}, indent=2) + "\n")


def cmd_final(args):
    out = DATA / f"final{args.tag}"
    if (out / "done.json").exists():
        print("final already complete")
        return
    out.mkdir(parents=True, exist_ok=True)
    torch, hashes, kept, dropped, replay = prepare(args)
    model, pipe, info = train_model(torch, kept + replay, hashes, epochs=args.epochs, lr=args.lr,
                                    progress_per_epoch=args.progress_per_epoch, replay_per_epoch=args.replay_per_epoch,
                                    accumulation=args.accumulation, log=out / "events.jsonl")
    reference = out / "reference"
    reference.mkdir(exist_ok=True)
    model.save_pretrained(reference, safe_serialization=True, max_shard_size="4GB")
    pipe.tokenizer.save_pretrained(reference)
    (out / "done.json").write_text(json.dumps({
        "train_progress_rows": len(kept), "replay_rows": len(replay), "no_fit_dropped_ids": dropped,
        "epochs": args.epochs, "lr": args.lr, "progress_per_epoch": args.progress_per_epoch,
        "replay_per_epoch": args.replay_per_epoch, "accumulation": args.accumulation,
        "reference_files_sha256": {p.name: file_sha(p) for p in reference.iterdir() if p.is_file()},
        "deployed": False, **{k: v for k, v in info.items() if k != "loading"}}, indent=2) + "\n")


# ----------------------------------------------------------------------------- export + CPU eval

def ort_logits_n(engine, inputs, n: int):
    """The first ``n`` finite class logits of an ONNX graph exported with ``CLASSES`` slots."""
    import numpy as np
    feed = {i.name: inputs[i.name].detach().cpu().numpy() for i in engine.get_inputs()}
    out = engine.run(['logits'], feed)[0]
    if out.ndim != 2 or out.shape[0] != 1 or out.shape[1] < n or not np.isfinite(out[0, :n]).all():
        raise ValueError(f'expected {n} finite native label logits, got {out.shape}')
    return out[0, :n]


def cmd_export(args):
    """ONNX + INT4 of the final model with three native class slots; fidelity-checked against the native model."""
    import numpy as np
    import torch
    from suite import gliclass_export
    from suite.gliclass_probe import load_native, session
    from suite.gliclass_quantize import quantize
    torch.set_num_threads(6)
    final = args.final
    out = final / "export"
    out.mkdir()
    snap = out / "native-reference"
    snap.mkdir()
    reference = final / "reference"
    for p in reference.iterdir():
        (snap / p.name).symlink_to(p.absolute())
    _contract, hashes = common_setup(args)
    model, pipe, loading = load_native(str(reference))
    rows = load_progress()
    sample = next(r for r in rows if r["label"] == "PARTIAL")
    inputs = encode(pipe, sample, hashes, PROGRESS_LABELS)
    onnx_dir = snap / "onnx"
    onnx_dir.mkdir()
    gliclass_export.export_native_graph(torch, model, inputs, onnx_dir / "model.onnx", classes=CLASSES)
    manifest = {"repo": "offline-finetuned/knowledgator-gliclass-v4-edge", "source_kind": "trained_native_export",
                "snapshot": str(snap), "native_loading": loading, "classes": CLASSES,
                "files": {str(p.relative_to(snap)): {"bytes": p.stat().st_size, "sha256": file_sha(p)}
                          for p in snap.rglob("*") if p.is_file()}}
    (out / "download.json").write_text(json.dumps(manifest, indent=2) + "\n")
    quantize(out)
    fp32 = session(out / "normalized-fp32.onnx")
    # fidelity: native vs exported FP32 on one example per family
    replay = load_replay()
    checks = [sample, next(r for r in replay if r["family"] == "dictation"), next(r for r in replay if r["family"] == "retrospective")]
    for r in checks:
        labels = labels_for(r["family"])
        x = encode(pipe, r, hashes, labels)
        with torch.no_grad():
            native = model(**x, max_num_classes=CLASSES).logits[0, :len(labels)].float().numpy()
        exported = ort_logits_n(fp32, x, len(labels))
        np.testing.assert_allclose(exported, native, rtol=2e-4, atol=2e-4)
    (out / "fidelity.json").write_text(json.dumps({"checked": [r["id"] for r in checks], "rtol": 2e-4, "atol": 2e-4}) + "\n")


def cmd_eval_onnx(args):
    """INT4 graph: regression on the old families' held-out cases and progress fidelity on the GPU; latency on the CPU
    (the deployment shape), the only measurement that must run there."""
    import statistics
    import numpy as np
    import torch
    from suite.gliclass_probe import load_frozen_cohorts, load_native, session
    torch.set_num_threads(6)
    export = args.final / "export"
    _contract, hashes = common_setup(args)
    manifest = json.loads((export / "download.json").read_text())
    model, pipe, _ = load_native(manifest["snapshot"])
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    engine = session(export / "int4" / "model.onnx", gpu=True)          # regression + fidelity
    timed = session(export / "int4" / "model.onnx")                     # CPU: latency only
    fp32 = session(export / "normalized-fp32.onnx", gpu=True)
    old = {(r["evaluation_scope"], r["id"]): r
           for r in map(json.loads, (BASE.parent / "assessment/v2/results.jsonl").read_text().splitlines())}
    _c, _t, test = load_frozen_cohorts(BASE)
    _c1, _t1, replay_held = load_frozen_cohorts(OLD_V1)
    regression = {}
    for scope, cases in (("SYNTHETIC_TEST", test), ("REAL_TRAIN_REPLAY", replay_held)):
        for family in LABEL_ORDER:
            sub = [c for c in cases if c["family"] == family]
            new_hit = old_hit = agree = 0
            worst = 0.0
            for c in sub:
                labels = labels_for(family)
                x = encode(pipe, c, hashes, labels)
                new = ort_logits_n(engine, x, len(labels))
                ref = old[scope, c["id"]]
                new_pred = labels[int(np.argmax(new))]
                new_hit += new_pred == c["label"]
                old_hit += ref["int4_prediction"] == c["label"]
                agree += new_pred == ref["int4_prediction"]
                worst = max(worst, float(np.max(np.abs(new - np.array(ref["int4_logits"])))))
            regression[f"{scope}/{family}"] = {"count": len(sub), "new_correct": new_hit, "old_correct": old_hit,
                                               "same_prediction_as_old": agree, "max_abs_logit_shift_vs_old": worst}
    rows = [r for r in load_progress() if r["task"] == args.latency_task]
    lengths = json.loads((DATA / "token-lengths.json").read_text())
    rows = [r for r in rows if lengths[r["id"]] <= MAX_TOKENS][:args.latency_rows]
    timings = []
    for r in rows:
        started = time.monotonic()
        x = encode(pipe, r, hashes, PROGRESS_LABELS)
        prepared = time.monotonic()
        ort_logits_n(timed, x, CLASSES)
        ended = time.monotonic()
        logits = ort_logits_n(engine, x, CLASSES)
        with torch.no_grad():
            native = model(**{k: v.to(device) for k, v in x.items()},
                           max_num_classes=CLASSES).logits[0, :CLASSES].float().cpu().numpy()
        reference = ort_logits_n(fp32, x, CLASSES)
        timings.append({"tokens": int(x["input_ids"].shape[1]), "prepare_s": prepared - started, "ort_s": ended - prepared,
                        "label": r["label"], "int4": PROGRESS_LABELS[int(np.argmax(logits))],
                        "native": PROGRESS_LABELS[int(np.argmax(native))], "fp32_onnx": PROGRESS_LABELS[int(np.argmax(reference))],
                        "fp32_max_abs_vs_native": float(np.max(np.abs(reference - native)))})
    secs = sorted(t["ort_s"] for t in timings)
    buckets = defaultdict(list)
    for t in timings:
        buckets[min(t["tokens"] // 500 * 500, 3500)].append(t["ort_s"])
    report = {"regression_old_families_int4": regression, "progress_rows_timed": len(timings),
              "latency_threads": 6, "ort_seconds": {"mean": statistics.mean(secs), "median": statistics.median(secs),
                                                   "p95": secs[int(len(secs) * .95) - 1], "max": secs[-1]},
              "mean_tokens": statistics.mean(t["tokens"] for t in timings),
              "ort_seconds_by_token_bucket": {f"{k}-{k + 499}": {"n": len(v), "mean": statistics.mean(v)} for k, v in sorted(buckets.items())},
              "prepare_seconds_mean": statistics.mean(t["prepare_s"] for t in timings),
              "int4_same_as_native": sum(t["int4"] == t["native"] for t in timings),
              "fp32_onnx_same_as_native": sum(t["fp32_onnx"] == t["native"] for t in timings),
              "fp32_onnx_max_abs_vs_native": max(t["fp32_max_abs_vs_native"] for t in timings),
              "note": "progress rows are TRAIN of the final model: fidelity/latency only, not accuracy"}
    (args.final / "onnx-eval.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def cmd_report(args):
    """LOTO table; ONNX INT4 regression on the old held-out cases; CPU latency of the INT4 graph."""
    root = DATA / "loto"
    rows = load_progress()
    labels_by_task: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        labels_by_task[r["task"]].append(r["label"])
    folds = {}
    for t in TASKS:
        p = root / f"fold-{t}" / "predictions.jsonl"
        if not p.exists():
            continue
        recs = [json.loads(l) for l in p.read_text().splitlines()]
        train_labels = [l for u in TASKS if u != t for l in labels_by_task[u]]
        folds[t] = {"model": f1_report([x["label"] for x in recs], [x["prediction"] for x in recs]),
                    "majority_baseline": majority_baseline(train_labels, [x["label"] for x in recs])}
    pooled_t = [x["label"] for t in folds for x in map(json.loads, (root / f"fold-{t}" / "predictions.jsonl").read_text().splitlines())]
    pooled_p = [x["prediction"] for t in folds for x in map(json.loads, (root / f"fold-{t}" / "predictions.jsonl").read_text().splitlines())]
    report = {"folds": folds, "pooled": f1_report(pooled_t, pooled_p) if pooled_t else None,
              "mean_fold_accuracy": sum(f["model"]["accuracy"] for f in folds.values()) / len(folds) if folds else None,
              "mean_fold_macro_f1": sum(f["model"]["macro_f1"] for f in folds.values()) / len(folds) if folds else None,
              "mean_baseline_accuracy": sum(f["majority_baseline"]["accuracy"] for f in folds.values()) / len(folds) if folds else None}
    (DATA / "loto-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("fold", "final"):
        p = sub.add_parser(name)
        if name == "fold":
            p.add_argument("--holdout", choices=TASKS, required=True)
        p.add_argument("--epochs", type=int, default=2)
        p.add_argument("--lr", type=float, default=1.5e-5)
        p.add_argument("--accumulation", type=int, default=8)
        p.add_argument("--replay-per-epoch", type=int, default=300, help="old-family TRAIN rows replayed per epoch (0 = all)")
        p.add_argument("--progress-per-epoch", type=int, default=1000, help="progress rows drawn per epoch (0 = all)")
        p.add_argument("--deterministic", action="store_true")
        p.add_argument("--tag", default="", help="suffix of the output directory (smoke runs)")
    for name in ("export", "eval-onnx"):
        p = sub.add_parser(name)
        p.add_argument("--final", type=Path, default=DATA / "final")
        if name == "eval-onnx":
            p.add_argument("--latency-task", choices=TASKS, default="orders-api-py")
            p.add_argument("--latency-rows", type=int, default=60)
    sub.add_parser("report")
    args = parser.parse_args()
    os.umask(0o077)
    {"fold": cmd_fold, "final": cmd_final, "export": cmd_export, "eval-onnx": cmd_eval_onnx, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
