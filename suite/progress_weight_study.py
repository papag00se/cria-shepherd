"""Gradient-free diagnosis of the progress classifier; no training or deployment.

Use the existing GLiClass experiment interpreter. All model calls must be on the operator-specified RTX 3080. Artifacts default to ~/.cria/test-runs/outputs/research/progress-v1/weight-study-20261104. The fresh TEST set is not read by the diagnostic commands.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path

from suite.progress_dataset import LABELS
from suite.progress_loto import DATA, f1_report
from suite.system1_paths import TRAINING_ROOT

OUT = DATA / "weight-study-20261104"
GPU = "GPU-393d4998-707c-0ef0-a514-761015477256"
BEFORE = TRAINING_ROOT / "reference"
AFTER = DATA / "final/reference"
DEV = Path(__file__).parent / "progress_fresh/dev.jsonl"
PASS_BUDGET = 50
MAX_BATCH_SIZE = 64
BATCH_ATTENTION_CELLS = 8_000_000
LABEL_EMBEDDING_ROWS = (128001, 46888, 30621, 33117)
REFERENCES = ("after", "before", "class-before", "head-before", "last4-before", "embedding-before")


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def auc(positive, negative):
    """Pairwise rank probability, half credit for ties; no fitted readout."""
    import numpy as np
    p, n = np.asarray(positive), np.asarray(negative)
    if not len(p) or not len(n):
        return None
    difference = p[:, None] - n[None, :]
    return float(((difference > 0).sum() + 0.5 * (difference == 0).sum()) / difference.size)


def margin_report(rows):
    import numpy as np
    by_label = {label: [r["logits"][0] - r["logits"][1] for r in rows if r["label"] == label] for label in LABELS}
    report = f1_report([r["label"] for r in rows], [r["prediction"] for r in rows])
    report["done_minus_partial"] = {
        label: {"n": len(values), "mean": float(np.mean(values)),
                "quantiles_0_10_25_50_75_90_100": np.quantile(values, [0, .1, .25, .5, .75, .9, 1]).tolist(),
                "within_one_logit_of_boundary": sum(abs(x) <= 1 for x in values),
                "within_two_logits_of_boundary": sum(abs(x) <= 2 for x in values)}
        for label, values in by_label.items() if values}
    report["done_vs_partial_auc"] = auc(by_label["DONE"], by_label["PARTIAL"])
    return report


def logged(args):
    """H1: a shared offset hides a task-transferable DONE/PARTIAL ordering.

    Refutation: substantial within-task overlap/reversed ordering, or different task offsets large enough that a common offset cannot recover the distinction. This command reads old LOTO logits, never fresh TEST examples or predictions.
    """
    import numpy as np
    groups = {}
    all_rows = []
    for path in sorted((DATA / "loto").glob("fold-*/predictions.jsonl")):
        rows = jsonl(path)
        groups[rows[0]["task"]] = margin_report(rows)
        all_rows.extend(rows)
    centered = []
    for task in groups:
        rows = [r for r in all_rows if r["task"] == task]
        # Label-blind per-task centering: diagnostic only, not a proposed edit.
        center = float(np.median([r["logits"][0] - r["logits"][1] for r in rows]))
        centered.extend({**r, "logits": [r["logits"][0] - center, *r["logits"][1:]]} for r in rows)
    report = {"hypothesis": logged.__doc__, "forward_passes": 0,
              "label_order": LABELS, "folds": groups, "pooled": margin_report(all_rows),
              "pooled_auc_after_label_blind_task_centering": margin_report(centered)["done_vs_partial_auc"]}
    write_json(args.out / "logged-margins.json", report)
    print(json.dumps(report, indent=2))


def variant_prefix(args):
    return "" if args.reference == "after" else args.reference + "-"


def setup_gpu():
    import os
    if os.environ.get("CUDA_VISIBLE_DEVICES") != GPU:
        raise ValueError("Only the operator-specified RTX 3080 may be visible")
    import torch
    if torch.cuda.device_count() != 1 or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080":
        raise ValueError("Wrong GPU")
    torch.set_num_threads(4)
    torch.set_grad_enabled(False)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    return torch


def controls():
    """H3: apparent representation separation tracks amount, not correctness.

    Refutation: original DONE beats a minimally corrupted, length-matched version in at least 75% of pairs in both final margins and cross-task representation probes. Mutations below violate an explicit requirement, not a disputed label. The readout direction comes from the original dev set, excluding the task.
    """
    mutations = {
        "backup-sh/arg-check": ('[ $# -ne 2 ] || [ ! -d', '[ $# -ne 2 ] && [ ! -d'),
        "backup-sh/keep-n": ('| head -n -', '| tail -n -'),
        "interval-clj/merge-contained": ('[la (max lb b)]', '[la (min lb b)]'),
        "logparse-pl/level-upper": ('level => uc($2)', 'level => lc($2)'),
        "logparse-pl/levels-filter": ('level_rank($e->{level}) < $floor', 'level_rank($e->{level}) >= $floor'),
        "logparse-pl/malformed-count": ('$bad++;', '$bad--;'),
        "ratelimit-py/validate-args": ('if capacity < 1:', 'if capacity > 1:'),
        "ratelimit-py/retry-after": ('return (1 - tokens) / self.rate', 'return (1 + tokens) / self.rate'),
        "ratelimit-py/allow-n": ('+            self.tokens -= cost', '+            self.tokens += cost'),
        "recipes-rb/integer-division": ('target.to_f / servings', 'target.to_i / servings'),
        "recipes-rb/format-quantities": ('q.round(2)', 'q.round(1)'),
        "recipes-rb/cli-args": ('target.positive?', 'target.negative?'),
        "weather-js/kelvin": ('return k - 273.15;', 'return k + 273.15;'),
        "weather-js/rounding": ('n.toFixed(1)', 'n.toFixed(2)'),
        "wordtrim-lua/trim-both": ('^%s*(.-)%s*$', '^%s*(.+)%s*$'),
        "wordtrim-lua/starts-with": ('s:sub(1, #prefix) == prefix', 's:sub(1, #prefix) ~= prefix'),
    }
    result = []
    for row in jsonl(DEV):
        key = row["id"].rsplit("/", 1)[0]
        if row["label"] != "DONE" or key not in mutations:
            continue
        old, new = mutations[key]
        if row["evidence"].count(old) != 1:
            raise ValueError(f"Ambiguous counterfactual: {key}")
        result.append({**row, "id": "control/" + key + "/DONE", "source_id": row["id"]})
        result.append({**row, "id": "control/" + key + "/PARTIAL", "source_id": row["id"],
                       "label": "PARTIAL", "label_source": "explicit requirement violated by recorded substitution",
                       "evidence": row["evidence"].replace(old, new), "substitution": [old, new]})
    return result


def prepare_rows(pipe, rows):
    from suite.gliclass_probe import render_state
    from suite.progress_dataset import render_state as state
    from suite.progress_loto import progress_policy
    prepared = []
    for row in rows:
        text = pipe.prepare_input(render_state(state(row["requirement"], row["evidence"])),
                                  list(LABELS), prompt=progress_policy())
        ids = pipe.tokenizer(text, truncation=False)["input_ids"]
        prepared.append({**row, "rendered_input": text, "input_ids": ids, "tokens": len(ids)})
    return prepared


def batches(rows, cells=BATCH_ATTENTION_CELLS):
    """Length buckets; reduce the batch, never truncate an input."""
    batch = []
    for row in sorted(rows, key=lambda r: (r["tokens"], r["id"])):
        if batch and (len(batch) == MAX_BATCH_SIZE or (len(batch) + 1) * row["tokens"] ** 2 > cells):
            yield batch
            batch = []
        batch.append(row)
    if batch:
        yield batch


def ledger_path(out, phase):
    return out / {"discovery": "forward-ledger.jsonl", "validation": "validation-ledger.jsonl", "int4": "int4-ledger.jsonl"}[phase]


def ledger_start(out, *, phase="discovery", **details):
    import time
    from suite.onejev_probe import append
    path = ledger_path(out, phase)
    old = jsonl(path) if path.exists() else []
    number = sum(r["event"] == "start" for r in old) + 1
    if phase == "discovery" and number > PASS_BUDGET:
        raise ValueError("The operator's 50-pass budget is exhausted")
    append(path, {"event": "start", "pass": number, "phase": phase, "time": time.time(), "gpu": GPU, **details})
    return number


def recorded_forward(out, torch, run, *, phase="discovery", **details):
    """One budgeted inference batch, including failed attempts and head-only replays."""
    import time
    from suite.onejev_probe import append
    number = ledger_start(out, phase=phase, **details)
    started = time.monotonic()
    torch.cuda.reset_peak_memory_stats()
    try:
        with torch.inference_mode():
            result = run()
        append(ledger_path(out, phase), {"event": "result", "pass": number,
               "seconds": time.monotonic() - started, "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
               "predictions": result["predictions"]})
        print(f"{phase} pass {number}: {len(result['predictions'])} rows, peak {torch.cuda.max_memory_allocated() / 1024**3:.2f} GiB", flush=True)
        return result
    except Exception as exc:
        append(ledger_path(out, phase), {"event": "error", "pass": number, "error": repr(exc)})
        raise


def capture(args):
    """H2: a task-transferable DONE/PARTIAL distinction exists upstream of scoring.

    Refutation: raw logits and leave-one-dev-task-out, closed-form representation contrasts fail to separate paired near misses; calibration never reverses a correct DONE decision. No optimized classifier, autograd, or loss fitting.
    """
    import numpy as np
    from suite.gliclass_probe import load_native
    torch = setup_gpu()
    checkpoint = BEFORE if args.reference == "before" else AFTER
    model, pipe, _ = load_native(str(checkpoint), "cuda")
    model.requires_grad_(False)
    edit = None
    restores = {
        "class-before": ("model.classes_projector.",),
        "head-before": ("model.classes_projector.", "model.text_projector.", "model.scorer.", "calibrator."),
        "last4-before": tuple(f"model.encoder_model.encoder.layer.{i}." for i in range(20, 24)),
    }
    if args.reference in restores:
        from safetensors import safe_open
        changed = []
        with safe_open(BEFORE / "model.safetensors", framework="pt", device="cpu") as before:
            for name, tensor in model.state_dict().items():
                if name.startswith(restores[args.reference]):
                    source = before.get_tensor(name)
                    changed.append({"tensor": name, "indices": "all", "weights": tensor.numel(),
                                    "changed": int(torch.count_nonzero(tensor.cpu() - source))})
                    tensor.copy_(source.to(tensor.device))
        edit = {"operation": "diagnostic rewind to BEFORE; not saved or proposed for deployment",
                "source": str(BEFORE), "tensors": changed}
    if args.reference == "embedding-before":
        from safetensors import safe_open
        name = "model.encoder_model.embeddings.word_embeddings.weight"
        # Native token IDs: class marker, DONE, PART, IAL. No label spelling is changed.
        indices = list(LABEL_EMBEDDING_ROWS)
        tensor = model.state_dict()[name]
        with safe_open(BEFORE / "model.safetensors", framework="pt", device="cpu") as before:
            source = torch.cat([before.get_slice(name)[i:i + 1] for i in indices])
        changed = int(torch.count_nonzero(tensor[indices].cpu() - source))
        tensor[indices] = source.to(tensor.device)
        edit = {"operation": "diagnostic label-path embedding rewind to BEFORE; not saved",
                "source": str(BEFORE), "tensors": [{"tensor": name, "rows": indices, "columns": "all 1024",
                                                    "weights": source.numel(), "changed": changed}]}
    rows = prepare_rows(pipe, jsonl(DEV) if args.panel == "dev" else controls())
    stem = variant_prefix(args) + args.panel
    hypothesis = capture.__doc__ if args.panel == "dev" else controls.__doc__
    if args.reference == "before":
        hypothesis = ("H6: progress training erased an already usable correctness distinction. "
                      "Refuted for this probe if BEFORE also fails the matched correctness contrasts. "
                      "This is a behavior comparison, not an inference from weight differences.")
    elif args.reference == "embedding-before":
        hypothesis = ("H8: the change to the class marker and DONE/PARTIAL token embeddings imposes the suppressive prior. "
                      "Refutation: reverting these four rows fails to recover DONE or correctness sensitivity on paired controls. "
                      "No NOT_STARTED word-token row is changed; shared-marker and policy-token occurrences are affected too.")
    elif edit is not None:
        hypothesis = ("H7: the rewound downstream component contains the suppressive training change. "
                      "Refutation: it does not recover matched-correctness rankings (at least 12/16), "
                      "or its DONE recovery is only a general shift that also promotes incorrect code. "
                      "Three independent diagnostic interventions: class projector, whole head, last four encoder layers.")
    write_json(args.out / f"{stem}-inputs.json", rows)
    arrays = defaultdict(list)
    recorded = []
    for batch in batches(rows):
        inputs = pipe.tokenizer.pad({"input_ids": [r["input_ids"] for r in batch]},
                                    padding=True, return_tensors="pt").to("cuda")
        positions = torch.stack([(ids == model.config.class_token_index).nonzero().flatten()
                                 for ids in inputs["input_ids"]])
        batch_indices = torch.arange(len(batch), device="cuda").unsqueeze(1)
        found = {}
        hooks = []

        def layer_hook(name):
            def save(_module, _args, output):
                hidden = output[0] if isinstance(output, tuple) else output
                found[name] = hidden[batch_indices, positions].float().cpu().numpy()
            return save

        hooks.append(model.model.encoder_model.embeddings.register_forward_hook(layer_hook("layer00")))
        for index, layer in enumerate(model.model.encoder_model.encoder.layer, 1):
            hooks.append(layer.register_forward_hook(layer_hook(f"layer{index:02}")))
        for name, module in (("projected", model.model.classes_projector),
                             ("scorer_relu1", model.model.scorer.mlp[1]),
                             ("scorer_relu2", model.model.scorer.mlp[3])):
            def save(_module, _args, output, name=name):
                found[name] = output.float().cpu().numpy()
            hooks.append(module.register_forward_hook(save))
        def run():
            output = model(**inputs, max_num_classes=len(LABELS), output_class_embeddings=True, output_text_embeddings=True)
            for key in ("logits", "uncalibrated_logits", "inverse_temperatures", "calibration_biases", "text_embeddings"):
                found[key] = getattr(output, key).float().cpu().numpy()
            result = []
            for i, row in enumerate(batch):
                rec = {k: row[k] for k in ("id", "task", "label", "tokens")}
                rec.update(logits=found["logits"][i].tolist(), prediction=LABELS[int(found["logits"][i].argmax())],
                           uncalibrated_logits=found["uncalibrated_logits"][i].tolist(),
                           inverse_temperatures=found["inverse_temperatures"][i].tolist(),
                           calibration_biases=found["calibration_biases"][i].tolist())
                result.append(rec)
            return {"predictions": result}

        try:
            result = recorded_forward(args.out, torch, run,
                                      purpose=f"{args.reference.upper()} {args.panel}: logits, calibration and pooled class representations",
                                      hypothesis=hypothesis, examples=[r["id"] for r in batch],
                                      tokens=[r["tokens"] for r in batch], shape=list(inputs["input_ids"].shape),
                                      dtype="FP32", model=str(checkpoint), edit=edit)
            recorded.extend(result["predictions"])
            for key, value in found.items():
                arrays[key].append(value)
        finally:
            for hook in hooks:
                hook.remove()
        del inputs, found
    np.savez_compressed(args.out / f"{stem}-representations.npz", **{k: np.concatenate(v) for k, v in arrays.items()})
    write_json(args.out / f"{stem}-predictions.json", recorded)
    write_json(args.out / f"{stem}-margins.json", margin_report(recorded))


def representation_report(args):
    """H2 diagnostic: fixed nearest-centroid readouts, leaving entire dev tasks out.

    Closed-form means only: no gradients, optimizers, hyperparameter search or iterative loss fitting. The paired statistic cancels a shared task offset. Label-contrast is DONE-class minus PARTIAL-class; absolute DONE class is also inspected. All rows of the evaluated task are excluded from its direction.
    """
    import numpy as np
    prefix = variant_prefix(args)
    stem = prefix + args.panel
    rows = json.loads((args.out / f"{stem}-predictions.json").read_text())
    data = np.load(args.out / f"{stem}-representations.npz")
    reference_rows = json.loads((args.out / f"{prefix}{args.direction_source}-predictions.json").read_text())
    reference = np.load(args.out / f"{prefix}{args.direction_source}-representations.npz")
    tasks = np.array([r["task"] for r in rows])
    labels = np.array([r["label"] for r in rows])
    reference_tasks = np.array([r["task"] for r in reference_rows])
    reference_labels = np.array([r["label"] for r in reference_rows])
    pairs = defaultdict(dict)
    for i, row in enumerate(rows):
        if row["label"] in ("DONE", "PARTIAL"):
            pairs[row["id"].rsplit("/", 1)[0]][row["label"]] = i

    def scored(scores):
        margins = [float(scores[p["DONE"]] - scores[p["PARTIAL"]]) for p in pairs.values()]
        return {"auc": auc(scores[labels == "DONE"], scores[labels == "PARTIAL"]),
                "paired_correct": sum(m > 0 for m in margins), "paired_total": len(margins),
                "paired_margins": dict(zip(pairs, margins)),
                "within_task_auc": {task: auc(scores[(tasks == task) & (labels == "DONE")],
                                             scores[(tasks == task) & (labels == "PARTIAL")]) for task in sorted(set(tasks))}}

    hypothesis = representation_report.__doc__ if args.panel == "dev" else controls.__doc__
    if args.direction_source == "controls":
        hypothesis = ("H4: a correctness direction from the controlled pairs transfers to other tasks; "
                      "refuted for this probe if pooled rankings remain near chance and fewer than "
                      "75% of pairs point in the correct direction.")
    result = {"method": representation_report.__doc__, "direction_source": args.direction_source,
              "hypothesis": hypothesis,
              "logit_margin": scored(data["logits"][:, 0] - data["logits"][:, 1]),
              "raw_logit_margin": scored(data["uncalibrated_logits"][:, 0] - data["uncalibrated_logits"][:, 1]),
              "length_control": scored(np.array([r["tokens"] for r in rows])), "representations": {}}
    for key in data.files:
        if not (key.startswith("layer") or key in ("projected", "scorer_relu1", "scorer_relu2")):
            continue
        x = data[key].astype(np.float64)
        r = reference[key].astype(np.float64)
        for view, features, reference_features in (("done", x[:, 0], r[:, 0]),
                                                   ("contrast", x[:, 0] - x[:, 1], r[:, 0] - r[:, 1])):
            scores = np.zeros(len(rows))
            for task in sorted(set(tasks)):
                mean_done = reference_features[(reference_tasks != task) & (reference_labels == "DONE")].mean(axis=0)
                mean_partial = reference_features[(reference_tasks != task) & (reference_labels == "PARTIAL")].mean(axis=0)
                direction = mean_done - mean_partial
                norm = np.linalg.norm(direction)
                if norm:
                    direction /= norm
                scores[tasks == task] = (features[tasks == task] - (mean_done + mean_partial) / 2) @ direction
            result["representations"][f"{key}/{view}"] = scored(scores)
    raw = data["uncalibrated_logits"].argmax(axis=1)
    calibrated = data["logits"].argmax(axis=1)
    result["calibrator_changed_predictions"] = [rows[i]["id"] for i in range(len(rows)) if raw[i] != calibrated[i]]
    write_json(args.out / f"{stem}-from-{args.direction_source}-representation-report.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "representations"}, indent=2))
    for name, stats in result["representations"].items():
        print(name, "AUC", round(stats["auc"], 3), "paired", stats["paired_correct"], "/", stats["paired_total"])


def control_significance(args):
    """H4 multiplicity check: correctness directions exceed task-grouped chance.

    Refuted as persuasive evidence if the best result among ALL inspected representations is common under sign flips of entire tasks. Enumerates the 128 task assignments; no new model call or optimization takes place.
    """
    import itertools
    import numpy as np
    prefix = variant_prefix(args)
    rows = json.loads((args.out / f"{prefix}controls-predictions.json").read_text())
    data = np.load(args.out / f"{prefix}controls-representations.npz")
    pairs = defaultdict(dict)
    for i, row in enumerate(rows):
        pairs[row["id"].rsplit("/", 1)[0]][row["label"]] = i
    done = [p["DONE"] for p in pairs.values()]
    partial = [p["PARTIAL"] for p in pairs.values()]
    tasks = np.array([rows[i]["task"] for i in done])
    unique = sorted(set(tasks))
    flips = list(itertools.product((-1, 1), repeat=len(unique)))
    sign_arrays = [np.array([flip[unique.index(t)] for t in tasks]) for flip in flips]
    counts = {}
    for key in data.files:
        if not (key.startswith("layer") or key in ("projected", "scorer_relu1", "scorer_relu2")):
            continue
        x = data[key].astype(np.float64)
        for view, features in (("done", x[:, 0]), ("contrast", x[:, 0] - x[:, 1])):
            delta = features[done] - features[partial]
            gram = delta @ delta.T
            gram[tasks[:, None] == tasks[None, :]] = 0
            counts[f"{key}/{view}"] = [int(((gram @ s) * s > 0).sum()) for s in sign_arrays]
    best_null = np.array(list(counts.values())).max(axis=0)
    observed = {key: values[-1] for key, values in counts.items()}
    best = max(observed.values())
    report = {"hypothesis": control_significance.__doc__, "pairs": len(pairs), "tasks": unique,
              "representations_examined": len(counts), "observed_pair_correct": observed,
              "best_observed": best, "task_sign_flip_maximum_counts": best_null.tolist(),
              "familywise_tail_probability": float((best_null >= best).mean()),
              "note": "Task-wise signs preserve dependence between requirements and layers; global sign inversion is symmetric."}
    write_json(args.out / f"{prefix}controlled-direction-significance.json", report)
    print(json.dumps(report, indent=2))


def input_ambiguity(args):
    """H5: identical progress inputs carry contradictory recorded verdicts.

    Refutation: no conflicting labels for an identical rendered input. Such conflicts bound agreement with recorded targets, not correctness of code. Only the training corpus is read; no fresh TEST examples are inspected.
    """
    from collections import Counter
    from suite.gliclass_probe import render_state
    from suite.progress_dataset import render_state as state
    groups = defaultdict(list)
    rows = jsonl(DATA / "dataset.jsonl")
    for row in rows:
        groups[render_state(state(row["requirement"], row["evidence"]))].append(row)
    conflicts = []
    for text, members in groups.items():
        labels = Counter(r["label"] for r in members)
        if len(labels) > 1:
            conflicts.append({"rendered_state": text, "counts": dict(labels),
                              "rows": [{k: r[k] for k in ("id", "task", "label", "label_source")} for r in members]})
    report = {"hypothesis": input_ambiguity.__doc__, "rows": len(rows), "unique_inputs": len(groups),
              "conflicting_inputs": len(conflicts), "rows_in_conflicting_groups": sum(len(g["rows"]) for g in conflicts),
              "minimum_recorded_target_disagreements": sum(sum(g["counts"].values()) - max(g["counts"].values()) for g in conflicts),
              "conflicts": conflicts}
    write_json(args.out / "input-ambiguity.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "conflicts"}, indent=2))
    if conflicts:
        write_json(args.out / "opened-conflict.json", conflicts[0])


def weight_changes(args):
    """H7 localization only: training wrote a suppressive downstream update.

    Weight norms cannot confirm behavior. A causal probe must restore the named component and recover correctness sensitivity, not merely predict DONE more.
    """
    import torch
    from safetensors import safe_open
    torch.set_num_threads(4)
    torch.set_grad_enabled(False)
    tensors = []
    groups = defaultdict(lambda: {"weights": 0, "changed": 0, "before_squared_norm": 0.0, "delta_squared_norm": 0.0})
    with safe_open(BEFORE / "model.safetensors", framework="pt", device="cpu") as before, safe_open(AFTER / "model.safetensors", framework="pt", device="cpu") as after:
        for name in after.keys():
            a, b = after.get_tensor(name).float(), before.get_tensor(name).float()
            delta = a - b
            parts = name.split(".")
            group = ".".join(parts[:5]) if name.startswith("model.encoder_model.encoder.layer.") else ".".join(parts[:2])
            values = {"weights": a.numel(), "changed": int(torch.count_nonzero(delta)),
                      "before_squared_norm": float(b.square().sum()), "delta_squared_norm": float(delta.square().sum())}
            for key, value in values.items():
                groups[group][key] += value
            tensors.append({"name": name, "shape": list(a.shape), **values,
                            "max_absolute_delta": float(delta.abs().max())})
    for group in groups.values():
        group["relative_norm_change"] = (group["delta_squared_norm"] / max(group["before_squared_norm"], 1e-30)) ** .5
    write_json(args.out / "weight-changes.json", {"hypothesis": weight_changes.__doc__, "groups": dict(groups), "tensors": tensors})
    for name, values in sorted(groups.items(), key=lambda item: item[1]["delta_squared_norm"], reverse=True):
        print(name, json.dumps(values))


def summarize(args):
    """Collate recorded events and analysis; no inference, fitting, or TEST access."""
    ledger = jsonl(args.out / "forward-ledger.jsonl")
    starts = [r for r in ledger if r["event"] == "start"]
    results = {r["pass"]: r for r in ledger if r["event"] == "result"}
    summary = {"status": "no accepted edit; binary obstacle-versus-absence not completely resolved",
               "forward_passes": len(starts), "forward_pass_budget": PASS_BUDGET, "gpu": GPU,
               "errors": [r for r in ledger if r["event"] == "error"],
               "peak_allocated_bytes": max(r["peak_allocated_bytes"] for r in results.values()),
               "test": {"read_or_scored": False, "final_edit": None,
                        "operator_supplied_baseline": {"accuracy": .539, "macro_f1": .496,
                                                       "recall": {"DONE": 0.0, "PARTIAL": .99, "NOT_STARTED": .77}}},
               "regression": {"dictation_and_retrospective": "not run: no candidate selected; saved weights unchanged",
                              "onnx_and_int4": "not run: no candidate selected"},
               "variants": {}, "passes": []}
    for variant in REFERENCES:
        prefix = "" if variant == "after" else variant + "-"
        item = {}
        for panel in ("dev", "controls"):
            metrics = json.loads((args.out / f"{prefix}{panel}-margins.json").read_text())
            metrics["recall"] = {label: metrics["confusion"][i][i] / sum(metrics["confusion"][i])
                                 for i, label in enumerate(LABELS) if sum(metrics["confusion"][i])}
            item[panel] = metrics
            observed = json.loads((args.out / f"{prefix}{panel}-inputs.json").read_text())
            original = {r["id"]: r for r in json.loads((args.out / f"{panel}-inputs.json").read_text())}
            item[f"{panel}_same_inputs_as_after"] = all(r["input_ids"] == original[r["id"]]["input_ids"]
                                                         and r["rendered_input"] == original[r["id"]]["rendered_input"] for r in observed)
        controls_report = json.loads((args.out / f"{prefix}controls-from-controls-representation-report.json").read_text())
        item["controlled_pair_ranking"] = controls_report["logit_margin"]
        item["controlled_raw_pair_ranking"] = controls_report["raw_logit_margin"]
        item["calibrator_changed_control_predictions"] = controls_report["calibrator_changed_predictions"]
        events = [r for r in starts if r["purpose"].startswith(variant.upper() + " ")]
        edit = events[0]["edit"]
        item["diagnostic_edit"] = edit
        item["temporarily_changed_weights"] = sum(t["changed"] for t in edit["tensors"]) if edit else 0
        summary["variants"][variant] = item
    for event in starts:
        result = results.get(event["pass"])
        summary["passes"].append({"pass": event["pass"], "purpose": event["purpose"], "examples": event["examples"],
                                  "shape": event["shape"], "result": "error" if result is None else
                                  f"{len(result['predictions'])} complete predictions recorded",
                                  "seconds": None if result is None else result["seconds"]})
    summary["config_equal_before_after"] = json.loads((BEFORE / "config.json").read_text()) == json.loads((AFTER / "config.json").read_text())
    summary["logged_margins"] = json.loads((args.out / "logged-margins.json").read_text())
    summary["controlled_direction_significance"] = json.loads((args.out / "controlled-direction-significance.json").read_text())
    ambiguity = json.loads((args.out / "input-ambiguity.json").read_text())
    summary["input_ambiguity"] = {k: v for k, v in ambiguity.items() if k != "conflicts"}
    summary["direction_variants"] = {}
    for path in sorted(args.out.glob("direction-*-report.json")):
        item = json.loads(path.read_text())
        summary["direction_variants"][path.name.removeprefix("direction-").removesuffix("-report.json")] = {
            "dev": item["dev"], "controls": item["controls"], "edit": item["edit"]}
    validation_path = args.out / "validation-results.json"
    if validation_path.exists():
        validation = json.loads(validation_path.read_text())
        summary["status"] = validation["status"]
        summary["validation"] = validation
        summary["test"] = {"read_or_scored": True, "final_edit": validation["candidate"],
                           "certified": False, **validation["fresh_test"]}
        summary["regression"] = {"dictation_and_retrospective": validation["old_families"],
                                 "onnx_and_int4": validation["onnx"]}
        summary["accounting_scope"] = "forward_passes is main discovery only; separately authorized validation and excluded, unapproved reviewer CPU computations are detailed in validation.inference_accounting and validation.protocol_deviations"
    write_json(args.out / "summary.json", summary)
    print("passes", summary["forward_passes"], "peak GiB", summary["peak_allocated_bytes"] / 1024**3)
    for variant, item in summary["variants"].items():
        print(variant, "dev", item["dev"]["confusion"], "controlled pairs", item["controlled_pair_ranking"]["paired_correct"],
              "AUC", item["controlled_pair_ranking"]["auc"], "temporary weights", item["temporarily_changed_weights"],
              "same inputs", item["dev_same_inputs_as_after"] and item["controls_same_inputs_as_after"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["logged", "capture", "representations", "significance", "ambiguity", "weights", "summary"])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--panel", choices=["dev", "controls"], default="dev")
    parser.add_argument("--direction-source", choices=["dev", "controls"], default="dev")
    parser.add_argument("--reference", choices=REFERENCES, default="after")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    {"logged": logged, "capture": capture, "representations": representation_report,
     "significance": control_significance, "ambiguity": input_ambiguity,
     "weights": weight_changes, "summary": summarize}[args.command](args)


if __name__ == "__main__":
    main()
