"""Targeted, gradient-free direction experiments following the progress weight study.

No fresh TEST access. Discovery uses the original 50-pass ledger; final certification is separately authorized by the operator. Statistical analysis of cached activations is CPU-only; every model computation, including a replayed head, runs on the specified RTX 3080 and is recorded.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from suite.progress_weight_study import AFTER, OUT, LABELS, batches, margin_report, recorded_forward, setup_gpu, write_json

READOUT = "model.scorer.mlp.4.weight"
PROJECTOR = "model.classes_projector.linear_1.weight"
EDITS = ("baseline", "readout-identity", "readout-protected", "readout-semantic", "readout-negative", "projector-identity", "scorer-identity", "projector-shift")


def geometry(args):
    """H9: a common class-identity direction contributes a removable PARTIAL preference.

    Localization uses cached representations and weights, not fitted losses. Refutation requires a GPU forward test: removing the direction must improve development discrimination rather than simply relabeling every changed example DONE. Component rewinds did not test this operation.
    """
    import numpy as np
    from safetensors import safe_open
    data = np.load(args.out / "dev-representations.npz")
    before = np.load(args.out / "before-dev-representations.npz")
    rows = json.loads((args.out / "dev-predictions.json").read_text())
    old_rows = json.loads((args.out / "before-dev-predictions.json").read_text())
    old_index = {r["id"]: i for i, r in enumerate(old_rows)}
    order = [old_index[r["id"]] for r in rows]
    tasks = np.array([r["task"] for r in rows])
    directions = {}
    report = {"hypothesis": geometry.__doc__, "representations": {}}
    for key in ("layer24", "projected", "scorer_relu1", "scorer_relu2"):
        x = data[key].astype(np.float64)
        old = before[key][order].astype(np.float64)
        contrasts = x[:, 0] - x[:, 1]
        center = contrasts.mean(axis=0)
        norm = np.linalg.norm(center)
        u = center / norm
        delta = (contrasts - (old[:, 0] - old[:, 1])).mean(axis=0)
        d = delta / np.linalg.norm(delta)
        # The SVD describes existing coordinates, not an optimized prediction rule.
        singular = np.linalg.svd(contrasts, compute_uv=False)
        directions[key + "_identity"] = u
        directions[key + "_training_shift"] = d
        item = {"mean_contrast_norm": float(norm), "training_shift_norm": float(np.linalg.norm(delta)),
                "identity_vs_training_shift_cosine": float(u @ d),
                "uncentered_first_component_energy_fraction": float(singular[0] ** 2 / np.square(singular).sum()),
                "mean_direction_energy_fraction": float(np.square(contrasts @ u).sum() / np.square(contrasts).sum()),
                "mean_contrast_cosine_by_task": {task: float(contrasts[tasks == task].mean(axis=0) @ u /
                                                           np.linalg.norm(contrasts[tasks == task].mean(axis=0)))
                                                 for task in sorted(set(tasks))}}
        report["representations"][key] = item
    name = READOUT
    with safe_open(AFTER / "model.safetensors", framework="numpy", device="cpu") as weights:
        w = weights.get_tensor(name).astype(np.float64).reshape(-1)
    report["readout"] = {"tensor": name, "weights": len(w), "norm": float(np.linalg.norm(w))}
    for label in ("identity", "training_shift"):
        u = directions["scorer_relu2_" + label]
        report["readout"][label] = {"cosine": float(w @ u / np.linalg.norm(w)),
                                    "removed_weight_norm": float(abs(w @ u))}
    np.savez(args.out / "directions.npz", **directions)
    write_json(args.out / "direction-geometry.json", report)
    print(json.dumps(report, indent=2))


def direction_edit(model, directions, edit):
    """Fold one orthogonal projection into an existing weight tensor; no new module."""
    import numpy as np
    import torch
    if edit == "baseline":
        return None
    location, kind = edit.split("-")
    key = {"readout": "scorer_relu2", "projector": "layer24", "scorer": "projected"}[location]
    key += "_training_shift" if kind == "shift" else "_identity"
    name = {"readout": READOUT, "projector": PROJECTOR, "scorer": "model.scorer.mlp.0.weight"}[location]
    u = directions[key]
    tensor = model.state_dict()[name]
    columns = slice(tensor.shape[1] // 2, None) if location == "scorer" else slice(None)
    old = tensor[:, columns].cpu().numpy().astype(np.float64)
    right = directions["readout_protected_dual"] if kind == "protected" else u
    new = old - np.outer(old @ u, right)
    if kind in ("semantic", "negative"):
        sign = 1 if kind == "semantic" else -1
        new += sign * 0.5 * np.linalg.norm(old) * directions["semantic_source_tasks"]
    new = new.astype(np.float32)
    tensor[:, columns].copy_(torch.from_numpy(new).to(tensor.device))
    return {"tensor": name, "rows": "all", "columns": "label half" if location == "scorer" else "all",
            "direction": key, "operation": "W_new = W_after - outer(W_after @ u, v); unit u; v=u unless old-training protected; biases unchanged",
            "changed_values": int(np.count_nonzero(new != old)), "direction_values": u.tolist(), "right_values": right.tolist(),
            "semantic_operation": ("plus" if kind == "semantic" else "minus") + " 0.5*norm(W_after)*v; v from four source tasks, orthogonal to u" if kind in ("semantic", "negative") else None,
            "semantic_values": directions["semantic_source_tasks"].tolist() if kind in ("semantic", "negative") else None,
            "frobenius_delta": float(np.linalg.norm(new - old))}


def cached_panels(out):
    """Only 16 controls are new inputs; correct halves already occur in the 51 DEV rows."""
    import numpy as np
    dev = json.loads((out / "dev-predictions.json").read_text())
    control = json.loads((out / "controls-predictions.json").read_text())
    dev_arrays = np.load(out / "dev-representations.npz")
    control_arrays = np.load(out / "controls-representations.npz")
    wrong = [i for i, row in enumerate(control) if row["label"] == "PARTIAL"]
    rows = dev + [control[i] for i in wrong]
    arrays = {key: np.concatenate([dev_arrays[key], control_arrays[key][wrong]])
              for key in ("layer24", "text_embeddings", "logits")}
    return rows, arrays, control


def panel_report(rows):
    from collections import defaultdict
    pairs = defaultdict(dict)
    for row in rows:
        if row["label"] in ("DONE", "PARTIAL"):
            pairs[row["id"].rsplit("/", 1)[0]][row["label"]] = row["logits"][0] - row["logits"][1]
    margins = {key: pair["DONE"] - pair["PARTIAL"] for key, pair in pairs.items() if len(pair) == 2}
    return {**margin_report(rows), "paired_correct": sum(m > 0 for m in margins.values()),
            "paired_total": len(margins), "paired_margins": margins}


def prediction_records(output, batch):
    arrays = {key: getattr(output, key).float().cpu().numpy()
              for key in ("logits", "uncalibrated_logits", "inverse_temperatures", "calibration_biases")}
    return [{**{key: row[key] for key in ("id", "label", "tokens")},
             **{key: row[key] for key in ("task", "family", "labels") if key in row},
             **{key: values[i].tolist() for key, values in arrays.items()},
             "prediction": row.get("labels", LABELS)[int(arrays["logits"][i].argmax())]}
            for i, row in enumerate(batch)]


def head_predictions(model, torch, text, classes, batch, *, raw_logits=None):
    from gliclass.model import GLiClassOutput
    projected = model.model.classes_projector(classes)
    raw = model.model.scorer(text, projected) if raw_logits is None else raw_logits
    output = GLiClassOutput(logits=raw, text_embeddings=text, class_embeddings=projected,
                            class_mask=torch.ones_like(raw, dtype=torch.bool))
    return prediction_records(model._calibrate(output, True, True), batch)


def replay(args):
    """H9: erasing one shared class-identity direction recovers suppressed discrimination.

    Readout erasure changes the shared linear score, while projector/scorer erasure also changes nonlinear activation gates. These are independent interventions, not combined edits. Refutation: no DONE recovery, loss of NOT_STARTED, or merely promoting incorrect code; matched correctness should improve from 8/16 toward at least 12/16. No coefficient search: one full orthogonal projection per tensor. Both calibrated and raw logits are retained; the real calibrator is rerun, never frozen. Any apparent recovery remains exploratory until cross-task and old-family checks.
    """
    import numpy as np
    from suite.gliclass_probe import load_native
    torch = setup_gpu()
    model, _pipe, _ = load_native(str(AFTER), "cuda")
    model.requires_grad_(False)
    rows, cached, controls = cached_panels(args.out)
    directions = np.load(args.out / "directions.npz")
    weights = {name: model.state_dict()[name].clone() for name in (READOUT, PROJECTOR, "model.scorer.mlp.0.weight")}
    for edit in args.edit:
        for name, original in weights.items():
            model.state_dict()[name].copy_(original)
        operation = direction_edit(model, directions, edit)
        records = []
        for start in range(0, len(rows), 64):
            batch = rows[start:start + 64]
            text = torch.from_numpy(cached["text_embeddings"][start:start + 64]).to("cuda")
            classes = torch.from_numpy(cached["layer24"][start:start + 64]).to("cuda")

            def run():
                return {"predictions": head_predictions(model, torch, text, classes, batch)}

            result = recorded_forward(args.out, torch, run, purpose=f"DIRECTION {edit}: exact AFTER head replay",
                                      hypothesis=semantic_direction.__doc__ if edit in ("readout-semantic", "readout-negative") else replay.__doc__,
                                      examples=[r["id"] for r in batch],
                                      tokens=[r["tokens"] for r in batch], shape=list(classes.shape), dtype="FP32",
                                      model=str(AFTER), edit=operation, execution="cached encoder; class projector, scorer and actual calibrator on RTX 3080")
            records.extend(result["predictions"])
        by_id = {row["id"]: row for row in records}
        # The correct control input is byte-identical to its original DEV input.
        control_predictions = [{**by_id[row["id"] if row["label"] == "PARTIAL" else row["id"].removeprefix("control/")],
                                "id": row["id"]} for row in controls]
        stats = {"edit": operation, "dev": panel_report(records[:51]), "controls": panel_report(control_predictions),
                 "by_task": {task: margin_report([r for r in records[:51] if r["task"] == task])
                             for task in sorted({r["task"] for r in records[:51]})}}
        if edit == "baseline":
            actual = np.array([r["logits"] for r in records])
            stats["max_logit_error_vs_native"] = float(np.max(np.abs(actual - cached["logits"])))
            stats["changed_predictions_vs_native"] = sum(a["prediction"] != b["prediction"] for a, b in zip(records, rows))
        write_json(args.out / f"direction-{edit}-predictions.json", {"dev": records[:51], "controls": control_predictions})
        write_json(args.out / f"direction-{edit}-report.json", stats)
        print(edit, "dev", stats["dev"]["confusion"], "F1", stats["dev"]["macro_f1"],
              "controls", stats["controls"]["paired_correct"], "/16", "AUC", stats["controls"]["done_vs_partial_auc"],
              "replay error", stats.get("max_logit_error_vs_native"), flush=True)


def semantic_direction(args):
    """H11: a paired correctness contrast transfers, beyond class-identity removal.

    Source tasks are the first four alphabetically, not selected by performance. Hold the final three tasks out of this direction's construction; previous development experiments already exposed them, so this is an exploratory source-excluded probe, not a blind generalization estimate. One fixed 0.5*readout-norm addition and its negative control; no search or fitting to loss. Refutation: positive direction does not improve the source-excluded matched margins/ranks over the identity-only edit and its negative control.
    """
    from collections import defaultdict
    import numpy as np
    rows = json.loads((args.out / "controls-predictions.json").read_text())
    data = np.load(args.out / "controls-representations.npz")["scorer_relu2"].astype(np.float64)
    contrast = data[:, 0] - data[:, 1]
    pairs = defaultdict(dict)
    tasks = sorted({row["task"] for row in rows})
    source = tasks[:4]
    for i, row in enumerate(rows):
        pairs[row["id"].rsplit("/", 1)[0]][row["label"]] = i
    deltas = defaultdict(list)
    for pair in pairs.values():
        task = rows[pair["DONE"]]["task"]
        if task in source:
            deltas[task].append(contrast[pair["DONE"]] - contrast[pair["PARTIAL"]])
    raw = np.mean([np.mean(deltas[task], axis=0) for task in source], axis=0)
    directions = dict(np.load(args.out / "directions.npz"))
    u = directions["scorer_relu2_identity"]
    perpendicular = raw - (raw @ u) * u
    directions["semantic_source_tasks"] = perpendicular / np.linalg.norm(perpendicular)
    np.savez(args.out / "directions.npz", **directions)
    write_json(args.out / "semantic-direction.json", {"hypothesis": semantic_direction.__doc__,
               "source_tasks": source, "excluded_tasks": tasks[4:], "source_pairs": {task: len(deltas[task]) for task in source},
               "raw_norm": float(np.linalg.norm(raw)), "perpendicular_norm": float(np.linalg.norm(perpendicular)),
               "identity_cosine": float(raw @ u / np.linalg.norm(raw))})


def old_anchors(args):
    """H10: the 128-weight intervention can spare existing families on a TRAIN-only screen.

    Refutation: changed predictions on these anchors. An exact null-space projection can protect their raw logits, but cannot guarantee unseen inputs. Use eight examples per family/label, uniformly over lengths <=700 tokens; full inputs, not truncated. Neither old held-out cases nor fresh TEST are read. This is a cheap diagnostic screen, not regression certification. With --anchor-panel transfer, exclude every original anchor and test the SAME protected edit without reconstructing its protection subspace; changes refute transfer of protection.
    """
    import numpy as np
    from collections import defaultdict
    from suite.gliclass_probe import load_native, prepare_case
    from suite.progress_loto import BASE
    torch = setup_gpu()
    model, pipe, _ = load_native(str(AFTER), "cuda")
    model.requires_grad_(False)
    contract = json.loads((BASE / "contract.json").read_text())
    train = json.loads((BASE / "train-cases.json").read_text())
    stem = "old-" + args.anchor_panel
    excluded = {r["id"] for r in json.loads((args.out / "old-anchors-predictions.json").read_text())} if args.anchor_panel == "transfer" else set()
    groups = defaultdict(list)
    for case in train:
        if case["id"] in excluded:
            continue
        inputs, rendered = prepare_case(pipe, case, contract["policy_sha256"])
        if rendered["tokens"] <= 700:
            groups[case["family"], case["label"]].append({**case, **rendered, "input_ids": inputs["input_ids"][0].tolist()})
    selected = []
    for group in groups.values():
        group.sort(key=lambda row: (row["tokens"], row["id"]))
        selected.extend(group[i] for i in np.linspace(0, len(group) - 1, 8, dtype=int))
    write_json(args.out / f"{stem}-inputs.json", selected)
    saved = defaultdict(list)
    records = []
    for batch in batches(selected):
        inputs = pipe.tokenizer.pad({"input_ids": [r["input_ids"] for r in batch]}, padding=True, return_tensors="pt").to("cuda")
        found = {}

        def save_class(_module, arguments):
            found["layer24"] = arguments[0].float().cpu().numpy()

        def save_relu(_module, _arguments, output):
            found["scorer_relu2"] = output.float().cpu().numpy()

        hooks = [model.model.classes_projector.register_forward_pre_hook(save_class),
                 model.model.scorer.mlp[3].register_forward_hook(save_relu)]

        def run():
            output = model(**inputs, max_num_classes=2, output_text_embeddings=True)
            for key in ("logits", "text_embeddings"):
                found[key] = getattr(output, key).float().cpu().numpy()
            return {"predictions": prediction_records(output, batch)}

        try:
            result = recorded_forward(args.out, torch, run, purpose=f"AFTER {stem} TRAIN: full native baseline and ReLU2 capture",
                                      hypothesis=old_anchors.__doc__, examples=[r["id"] for r in batch],
                                      tokens=[r["tokens"] for r in batch], shape=list(inputs["input_ids"].shape),
                                      dtype="FP32", model=str(AFTER), edit=None)
            records.extend(result["predictions"])
            for key, value in found.items():
                saved[key].append(value)
        finally:
            for hook in hooks:
                hook.remove()
    arrays = {key: np.concatenate(values) for key, values in saved.items()}
    np.savez_compressed(args.out / f"{stem}-representations.npz", **arrays)
    write_json(args.out / f"{stem}-predictions.json", records)
    directions = dict(np.load(args.out / "directions.npz"))
    if args.anchor_panel == "anchors":
        # Minimum-norm update: delta dot old_activation = 0, w_new dot u = 0.
        activation = arrays["scorer_relu2"].reshape(-1, arrays["scorer_relu2"].shape[-1]).astype(np.float64)
        _left, singular, right = np.linalg.svd(activation, full_matrices=False)
        rank = int((singular > np.finfo(np.float64).eps * max(activation.shape) * singular[0]).sum())
        u = directions["scorer_relu2_identity"]
        projected = u - right[:rank].T @ (right[:rank] @ u)
        directions["readout_protected_dual"] = projected / (u @ projected)
        np.savez(args.out / "directions.npz", **directions)
        write_json(args.out / "old-anchor-geometry.json", {"rows": len(records), "activation_rank": rank,
                   "null_projection_norm": float(np.linalg.norm(projected)),
                   "update_amplification": float(np.linalg.norm(directions["readout_protected_dual"])),
                   "maximum_raw_invariance_residual": float(np.max(np.abs(activation @ directions["readout_protected_dual"]))),
                   "singular_values": singular.tolist()})
    initial = model.state_dict()[READOUT].clone()
    for edit in ("readout-identity", "readout-protected") if args.anchor_panel == "anchors" else ("readout-protected",):
        model.state_dict()[READOUT].copy_(initial)
        operation = direction_edit(model, directions, edit)
        text = torch.from_numpy(arrays["text_embeddings"]).to("cuda")
        classes = torch.from_numpy(arrays["layer24"]).to("cuda")
        result = recorded_forward(args.out, torch, lambda: {"predictions": head_predictions(model, torch, text, classes, records)},
                                  purpose=f"DIRECTION {edit}: {stem} TRAIN replay", hypothesis=old_anchors.__doc__,
                                  examples=[r["id"] for r in records], tokens=[r["tokens"] for r in records],
                                  shape=list(classes.shape), dtype="FP32", model=str(AFTER), edit=operation)
        stats = {"edit": operation, "changed_predictions": [a["id"] for a, b in zip(result["predictions"], records)
                                                             if a["prediction"] != b["prediction"]],
                 "max_logit_shift": float(np.max(np.abs(np.array([r["logits"] for r in result["predictions"]]) - arrays["logits"]))),
                 "predictions": result["predictions"]}
        write_json(args.out / f"{stem}-{edit}-report.json", stats)
        print(edit, "old anchor changes", len(stats["changed_predictions"]), "/", len(records), "logit shift", stats["max_logit_shift"], flush=True)


def native(args):
    """H12: a real weight-only edit reproduces cached-head recovery through the complete model.

    Refutation: label discrepancies between full native and cached-head predictions. All 67 distinct DEV/control inputs are length-bucketed without truncation. This checks equivalence, not generalization; no checkpoint is saved or deployed.
    """
    import numpy as np
    from suite.gliclass_probe import load_native
    torch = setup_gpu()
    model, pipe, _ = load_native(str(AFTER), "cuda")
    model.requires_grad_(False)
    edit = args.edit[0]
    operation = direction_edit(model, np.load(args.out / "directions.npz"), edit)
    source = json.loads((args.out / "dev-inputs.json").read_text())
    source += [r for r in json.loads((args.out / "controls-inputs.json").read_text()) if r["label"] == "PARTIAL"]
    predictions = []
    for batch in batches(source):
        inputs = pipe.tokenizer.pad({"input_ids": [r["input_ids"] for r in batch]}, padding=True, return_tensors="pt").to("cuda")
        result = recorded_forward(args.out, torch,
                                  lambda: {"predictions": prediction_records(model(**inputs, max_num_classes=len(LABELS)), batch)},
                                  purpose=f"DIRECTION {edit}: complete native forward", hypothesis=native.__doc__,
                                  examples=[r["id"] for r in batch], tokens=[r["tokens"] for r in batch],
                                  shape=list(inputs["input_ids"].shape), dtype="FP32", model=str(AFTER), edit=operation)
        predictions.extend(result["predictions"])
    cached = json.loads((args.out / f"direction-{edit}-predictions.json").read_text())
    expected = {row["id"]: row for panel in cached.values() for row in panel}
    stats = {"edit": operation, "predictions": predictions,
             "changed_predictions_vs_replay": [r["id"] for r in predictions if r["prediction"] != expected[r["id"]]["prediction"]],
             "max_logit_difference_vs_replay": max(abs(a - b) for r in predictions for a, b in zip(r["logits"], expected[r["id"]]["logits"])),
             "dev": panel_report([r for r in predictions if not r["id"].startswith("control/")])}
    write_json(args.out / f"direction-{edit}-native.json", stats)
    print(edit, "full-native", stats["dev"]["confusion"], "changed vs replay", len(stats["changed_predictions_vs_replay"]),
          "max logit error", stats["max_logit_difference_vs_replay"], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["geometry", "replay", "old-anchors", "semantic", "native"])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--edit", choices=EDITS, nargs="+", default=["baseline"])
    parser.add_argument("--anchor-panel", choices=["anchors", "transfer"], default="anchors")
    args = parser.parse_args()
    {"geometry": geometry, "replay": replay, "old-anchors": old_anchors,
     "semantic": semantic_direction, "native": native}[args.command](args)


if __name__ == "__main__":
    main()
