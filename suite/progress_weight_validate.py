"""Certification of the fixed readout-protected progress edit; no search or deployment.

The user authorized validation separately from the exhausted 50-pass discovery ledger. Every inference call (including ONNX export tracing) is logged separately and restricted to the RTX 3080. The fresh TEST command evaluates the frozen native candidate once; no validation result changes its weights.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path

from suite.progress_weight_directions import READOUT, prediction_records, panel_report
from suite.progress_weight_study import AFTER, DEV, OUT, batches, jsonl, prepare_rows, recorded_forward, setup_gpu, write_json

CANDIDATE = "readout-protected"
FRESH_TEST_PURPOSE = "ONE final fresh TEST evaluation: frozen native candidate"
OLD_RESULTS = Path("~/.cria/training/gliclass-v4-edge-expanded-v2/assessment/v2/results.jsonl").expanduser()
SELFTEST = Path("~/.cria/models/system1/expanded-v2-live/selftest.json").expanduser()


def freeze(args):
    """Save the exact 128-value row already tested in discovery; no checkpoint rewrite."""
    import numpy as np
    from safetensors import safe_open
    source = json.loads((args.out / f"direction-{CANDIDATE}-report.json").read_text())
    operation = source["edit"]
    with safe_open(AFTER / "model.safetensors", framework="numpy", device="cpu") as weights:
        old = weights.get_tensor(READOUT).astype(np.float64)
    u = np.array(operation["direction_values"])
    v = np.array(operation["right_values"])
    new = (old - np.outer(old @ u, v)).astype(np.float32)
    write_json(args.out / "candidate-weight.json", {
        "candidate": CANDIDATE, "source": str(AFTER), "tensor": READOUT,
        "selection": "Development evidence only: 15/21 DONE, 9/21 false-DONE on PARTIAL, 7/9 NOT_STARTED; macro-F1 0.6524. Unchanged predictions on 32 protection TRAIN anchors and 32 disjoint TRAIN probes. Full-native replay matched all 67 dev/control labels. Semantic recovery is not established; large update is a quantization risk.",
        "operation": operation, "old": old.tolist(), "new": new.tolist(),
        "changed_columns": np.flatnonzero(new.reshape(-1) != old.reshape(-1)).tolist(),
        "changed_values": int(np.count_nonzero(new != old)),
        "no_further_tuning": True, "deployed": False})
    print("Frozen", CANDIDATE, "changed values", np.count_nonzero(new != old), flush=True)


def candidate_model(args):
    from suite.gliclass_probe import load_native
    torch = setup_gpu()
    model, pipe, _ = load_native(str(AFTER), "cuda")
    model.requires_grad_(False)
    weight = json.loads((args.out / "candidate-weight.json").read_text())
    model.state_dict()[READOUT].copy_(torch.tensor(weight["new"], dtype=torch.float32, device="cuda"))
    return torch, model, pipe, weight


def old_rows():
    source = jsonl(OLD_RESULTS)
    selftest = {r["id"]: r for r in json.loads(SELFTEST.read_text())}
    rows = []
    for row in source:
        native = row["native_input"]
        rows.append({"id": row["id"], "task": row["evaluation_scope"], "family": row["family"],
                     "label": row["reviewed_target"], "labels": native["labels"],
                     "tokens": native["tokens"], "input_ids": native["native_inputs"]["input_ids"][0],
                     "rendered_input": native["rendered_input"], "before_prediction": row["native_prediction"],
                     "before_int4_prediction": row["int4_prediction"], "selftest": row["id"] in selftest})
    return rows, selftest


def native_predictions(args, torch, model, pipe, rows, *, purpose, hypothesis, classes, edit):
    records = []
    for batch in batches(rows):
        inputs = pipe.tokenizer.pad({"input_ids": [r["input_ids"] for r in batch]}, padding=True, return_tensors="pt").to("cuda")
        result = recorded_forward(args.out, torch,
                                  lambda: {"predictions": prediction_records(model(**inputs, max_num_classes=classes), batch)},
                                  phase="validation", purpose=purpose, hypothesis=hypothesis,
                                  examples=[r["id"] for r in batch], tokens=[r["tokens"] for r in batch],
                                  shape=list(inputs["input_ids"].shape), dtype="FP32", model=str(AFTER), edit=edit)
        records.extend(result["predictions"])
    return records


def old_native(args):
    """V1: the fixed edit preserves old held-out/replay and self-test-case decisions.

    Refutation is any changed prediction vs unedited AFTER. Also report comparison to the original BEFORE native and INT4 predictions; they are not assumed identical to AFTER. No adaptation to these results is allowed. This GPU check covers self-test case labels, not the CPU-only production runtime startup/logit check.
    """
    torch, model, pipe, weight = candidate_model(args)
    rows, selftest = old_rows()
    write_json(args.out / "validation-old-inputs.json", rows)
    candidates = native_predictions(args, torch, model, pipe, rows, purpose="Frozen candidate: old held-out/replay and selftest cases",
                                    hypothesis=old_native.__doc__, classes=2, edit=weight["operation"])
    model.state_dict()[READOUT].copy_(torch.tensor(weight["old"], dtype=torch.float32, device="cuda"))
    baseline = native_predictions(args, torch, model, pipe, rows, purpose="Unedited AFTER baseline: same old-family cases",
                                  hypothesis=old_native.__doc__, classes=2, edit=None)
    a = {r["id"]: r for r in candidates}
    b = {r["id"]: r for r in baseline}
    groups = defaultdict(list)
    for row in rows:
        groups[row["task"] + "/" + row["family"]].append(row)
    results = {}
    for group, cases in groups.items():
        results[group] = {
            "count": len(cases),
            "changed_vs_after": [r["id"] for r in cases if a[r["id"]]["prediction"] != b[r["id"]]["prediction"]],
            "candidate_correct": sum(a[r["id"]]["prediction"] == r["label"] for r in cases),
            "after_correct": sum(b[r["id"]]["prediction"] == r["label"] for r in cases),
            "candidate_changed_vs_before_native": [r["id"] for r in cases if a[r["id"]]["prediction"] != r["before_prediction"]],
            "after_changed_vs_before_native": [r["id"] for r in cases if b[r["id"]]["prediction"] != r["before_prediction"]]}
    self_results = [{"id": identity, "recorded_before_int4": case["label"],
                     "after": b[identity]["prediction"], "candidate": a[identity]["prediction"]}
                    for identity, case in selftest.items()]
    write_json(args.out / "validation-old-native.json", {"candidate": candidates, "after": baseline,
               "groups": results, "selftest_case_predictions": self_results,
               "production_selftest_executed": False, "fresh_test_accessed": False})
    print(json.dumps({"groups": results, "selftest": self_results}, indent=2), flush=True)


def export(args):
    """V2: exact native edit exports without changing arithmetic or the two/three-slot contract.

    Export one two-slot old-family graph and one three-slot progress graph, as required by the existing exporter. Both use the same frozen weights; this does not install a new runtime or bundle. Every actual exporter-triggered native forward is logged on CUDA.
    """
    from suite.gliclass_export import export_native_graph
    from suite.onejev_probe import file_sha
    torch, model, pipe, weight = candidate_model(args)
    old, _selftest = old_rows()
    dev = json.loads((args.out / "dev-inputs.json").read_text())
    for classes, row in ((2, min(old, key=lambda r: r["tokens"])), (3, min(dev, key=lambda r: r["tokens"]))):
        root = args.out / f"validation-export-{classes}"
        folder = root / "native/onnx"
        folder.mkdir(parents=True, exist_ok=True)
        inputs = pipe.tokenizer.pad({"input_ids": [row["input_ids"]]}, padding=True, return_tensors="pt").to("cuda")

        class RecordedNative(torch.nn.Module):
            def __init__(self, native):
                super().__init__()
                self.native = native

            def forward(self, **kwargs):
                def run():
                    output = self.native(**kwargs)
                    return {"output": output, "predictions": prediction_records(output, [row])}
                result = recorded_forward(args.out, torch, run, phase="validation",
                                          purpose=f"ONNX export trace: {classes} native class slots", hypothesis=export.__doc__,
                                          examples=[row["id"]], tokens=[row["tokens"]],
                                          shape=[1, row["tokens"]], dtype="FP32", model=str(AFTER), edit=weight["operation"])
                return result["output"]

        source = folder / "model.onnx"
        export_native_graph(torch, RecordedNative(model), inputs, source, classes=classes)
        # This is the quantizer's existing source-file contract, not a new approval mechanism.
        write_json(root / "download.json", {"snapshot": str(root / "native"), "candidate": CANDIDATE,
                   "files": {"onnx/model.onnx": {"bytes": source.stat().st_size, "sha256": file_sha(source)}}})
        print("Exported", source, flush=True)


def quantize(args):
    """Convert one graph per process with the standard INT4 recipe; no input inference."""
    from suite.gliclass_quantize import quantize as convert
    convert(args.out / f"validation-export-{args.classes}")


def onnx_session(path, profile_prefix, *, cpu=False):
    """One bounded ORT configuration for certification and quantization studies."""
    import onnxruntime as ort
    if not cpu:
        ort.preload_dlls()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.enable_profiling = True
    options.add_session_config_entry("session.disable_prepacking", "1")
    options.profile_file_prefix = str(profile_prefix)
    providers = ["CPUExecutionProvider"] if cpu else [
        ("CUDAExecutionProvider", {"device_id": 0, "use_tf32": 0, "gpu_mem_limit": 9 * 1024**3}),
        "CPUExecutionProvider"]
    engine = ort.InferenceSession(str(path), sess_options=options, providers=providers)
    if not cpu and "CUDAExecutionProvider" not in engine.get_providers():
        raise RuntimeError("CUDA execution provider did not initialize; do not silently run the full model on CPU")
    return engine


def onnx_rows(out, torch, engine, rows, classes, *, phase, purpose, hypothesis, model, edit, dtype, capture=None):
    """Whole inputs, common batching, authoritative call logging and optional feature capture."""
    import numpy as np
    from suite.progress_dataset import LABELS
    capture = capture or {}
    records, features = [], defaultdict(list)
    for batch in batches(rows):
        length = max(r["tokens"] for r in batch)
        ids = np.zeros((len(batch), length), dtype=np.int64)
        mask = np.zeros_like(ids)
        for i, row in enumerate(batch):
            ids[i, :row["tokens"]] = row["input_ids"]
            mask[i, :row["tokens"]] = 1

        def run():
            values = engine.run(["logits", *capture.values()], {"input_ids": ids, "attention_mask": mask})
            logits = values[0]
            if logits.shape != (len(batch), classes) or not np.isfinite(logits).all():
                raise ValueError(f"Invalid ONNX output: {logits.shape}")
            predictions = [{**{k: r[k] for k in ("id", "label", "tokens", "task")},
                            **{k: r[k] for k in ("family", "labels") if k in r},
                            "logits": logits[i].tolist(), "prediction": r.get("labels", LABELS)[int(logits[i].argmax())]}
                           for i, r in enumerate(batch)]
            return {"predictions": predictions, "features": dict(zip(capture, values[1:]))}

        result = recorded_forward(out, torch, run, phase=phase, purpose=purpose, hypothesis=hypothesis,
                                  examples=[r["id"] for r in batch], tokens=[r["tokens"] for r in batch],
                                  shape=list(ids.shape), dtype=dtype, model=str(model), edit=edit,
                                  providers=engine.get_providers(),
                                  memory_note=("Torch allocator peak excludes the separate ORT CUDA arena; CUDA arena limit is 9 GiB"
                                               if "CUDAExecutionProvider" in engine.get_providers() else "CPU ORT; Torch CUDA allocator does not measure CPU memory"))
        records.extend(result["predictions"])
        for key, value in result["features"].items():
            features[key].append(value)
    return records, {key: np.concatenate(value) for key, value in features.items()}


def onnx_placements(profile):
    from collections import Counter
    events = json.loads(Path(profile).read_text())
    counts = Counter((e.get("args", {}).get("provider"), e.get("args", {}).get("op_name"))
                     for e in events if e.get("cat") == "Node" and e.get("args", {}).get("provider"))
    return [{"provider": p, "op": op, "events": n} for (p, op), n in sorted(counts.items())]


def onnx_predictions(args):
    """V4: exported FP32 and standard INT4 preserve the frozen native decisions.

    No retuning, reweighting or altered quantization recipe after this comparison. The CUDA provider performs heavy inference on device 0 (the explicitly isolated RTX 3080); CPU shape/index bookkeeping is permitted by the operator's clarification. Profile actual operator placement. Refutation: any changed prediction, including false-DONE additions or old-family changes. Never read fresh TEST here.
    """
    import gc
    torch = setup_gpu()
    if args.classes == 2:
        rows, selftest = old_rows()
        reference = json.loads((args.out / "validation-old-native.json").read_text())["candidate"]
    else:
        rows = json.loads((args.out / "dev-inputs.json").read_text())
        rows += [r for r in json.loads((args.out / "controls-inputs.json").read_text()) if r["label"] == "PARTIAL"]
        reference = json.loads((args.out / f"direction-{CANDIDATE}-native.json").read_text())["predictions"]
        selftest = {}
    expected = {r["id"]: r for r in reference}
    root = args.out / f"validation-export-{args.classes}"
    path = root / ("normalized-fp32.onnx" if args.backend == "fp32" else "int4/model.onnx")
    name = f"validation-onnx-{args.backend}-{args.classes}"
    engine = onnx_session(path, args.out / (name + "-profile"))
    records, _ = onnx_rows(args.out, torch, engine, rows, args.classes, phase="validation",
                          purpose=f"Frozen {args.backend} ONNX: {args.classes} slots", hypothesis=onnx_predictions.__doc__,
                          model=path, edit=CANDIDATE, dtype="FP32 activations; " + ("INT4 matrices/embeddings" if args.backend == "int4" else "FP32 weights"))
    profile = engine.end_profiling()
    del engine
    gc.collect()
    placements = onnx_placements(profile)
    stats = {"backend": args.backend, "classes": args.classes, "predictions": records,
             "changed_vs_native": [r["id"] for r in records if r["prediction"] != expected[r["id"]]["prediction"]],
             "max_logit_difference_vs_native": max(abs(a - b) for r in records for a, b in zip(r["logits"], expected[r["id"]]["logits"])),
             "profile": profile, "operator_placements": placements}
    if args.classes == 2:
        stats["groups"] = {}
        for family in sorted({r["family"] for r in records}):
            for scope in sorted({r["task"] for r in records}):
                subset = [r for r in records if r["family"] == family and r["task"] == scope]
                stats["groups"][scope + "/" + family] = {"count": len(subset),
                    "changed_vs_native": [r["id"] for r in subset if r["id"] in stats["changed_vs_native"]],
                    "correct": sum(r["label"] == r["prediction"] for r in subset)}
        stats["selftest_case_predictions"] = [{"id": r["id"], "native": expected[r["id"]]["prediction"], "onnx": r["prediction"]}
                                              for r in records if r["id"] in selftest]
    else:
        stats["dev"] = panel_report([r for r in records if not r["id"].startswith("control/")])
        by_id = {r["id"]: r for r in records}
        controls = json.loads((args.out / "controls-predictions.json").read_text())
        controlled = [{**by_id[r["id"] if r["label"] == "PARTIAL" else r["id"].removeprefix("control/")], "id": r["id"]} for r in controls]
        stats["controls"] = panel_report(controlled)
    write_json(args.out / (name + ".json"), stats)
    print(name, "rows", len(records), "changed", len(stats["changed_vs_native"]),
          "max logit difference", stats["max_logit_difference_vs_native"], flush=True)
    if "dev" in stats:
        print("dev", stats["dev"]["confusion"], "controls", stats["controls"]["confusion"], flush=True)
    print("heavy operator placement", [p for p in placements if p["op"] in ("MatMul", "MatMulNBits", "Gemm", "GatherBlockQuantized")], flush=True)


def fresh_test(args):
    """V3: one final fresh TEST score of the fixed native candidate, with no tuning afterward."""
    torch, model, pipe, weight = candidate_model(args)
    rows = prepare_rows(pipe, jsonl(DEV.with_name("test.jsonl")))
    write_json(args.out / "validation-fresh-test-inputs.json", rows)
    predictions = native_predictions(args, torch, model, pipe, rows, purpose=FRESH_TEST_PURPOSE,
                                     hypothesis=fresh_test.__doc__, classes=3, edit=weight["operation"])
    report = panel_report(predictions)
    report["false_done"] = {"partial": sum(r["label"] == "PARTIAL" and r["prediction"] == "DONE" for r in predictions),
                            "not_started": sum(r["label"] == "NOT_STARTED" and r["prediction"] == "DONE" for r in predictions)}
    write_json(args.out / "validation-fresh-test-predictions.json", predictions)
    write_json(args.out / "validation-fresh-test-report.json", report)
    print(json.dumps(report, indent=2), flush=True)


def report(args):
    """Collate completed authoritative results; no inference or candidate modification."""
    from collections import Counter
    from suite.progress_dataset import LABELS
    weight = json.loads((args.out / "candidate-weight.json").read_text())
    baseline = json.loads(DEV.with_name("baseline-final-test.json").read_text())["report"]
    test = json.loads((args.out / "validation-fresh-test-report.json").read_text())
    old = json.loads((args.out / "validation-old-native.json").read_text())
    onnx = {f"{backend}-{classes}": json.loads((args.out / f"validation-onnx-{backend}-{classes}.json").read_text())
            for backend in ("fp32", "int4") for classes in (2, 3)}
    discovery = jsonl(args.out / "forward-ledger.jsonl")
    validation = jsonl(args.out / "validation-ledger.jsonl")
    starts = {r["pass"]: r for r in validation if r["event"] == "start"}
    completed = [r for r in validation if r["event"] == "result"]
    test_events = [r for r in completed if starts[r["pass"]]["purpose"] == FRESH_TEST_PURPOSE]
    test_ids = Counter(p["id"] for r in test_events for p in r["predictions"])
    recall = {label: test["confusion"][i][i] / sum(test["confusion"][i]) for i, label in enumerate(LABELS)}
    false_done = sum(test["confusion"][i][0] for i in (1, 2))
    old_changes = sum(len(r["changed_vs_after"]) for r in old["groups"].values())
    output = {
        "candidate": CANDIDATE, "tensor": weight["tensor"], "changed_values": weight["changed_values"],
        "deployed": False,
        "selection": weight["selection"], "edit_file": str(args.out / "candidate-weight.json"),
        "fresh_test": {"candidate": test, "baseline": baseline, "baseline_source": str(DEV.with_name("baseline-final-test.json")),
                       "baseline_was_rerun": False, "candidate_recall": recall,
                       "false_done": false_done, "done_precision": test["confusion"][0][0] / (test["confusion"][0][0] + false_done),
                       "not_started_recall_change": recall["NOT_STARTED"] - baseline["recall"]["NOT_STARTED"],
                       "forward_batches": [r["pass"] for r in test_events], "unique_inputs_scored": len(test_ids),
                       "evaluations_per_input": sorted(set(test_ids.values())), "retuned_after_test": False},
        "old_families": {"changed_vs_after_native": old_changes, "groups": old["groups"],
                         "selftest_case_predictions": old["selftest_case_predictions"],
                         "production_cpu_startup_selftest_executed": False},
        "onnx": {key: {"inputs": len(r["predictions"]), "changed_vs_native": len(r["changed_vs_native"]),
                       "changed_ids": r["changed_vs_native"], "max_logit_difference_vs_native": r["max_logit_difference_vs_native"],
                       "dev_confusion": r.get("dev", {}).get("confusion"), "controls_confusion": r.get("controls", {}).get("confusion"),
                       "operator_placements": r["operator_placements"]} for key, r in onnx.items()},
        "inference_accounting": {"main_discovery_forward_batches": sum(r["event"] == "start" for r in discovery),
                                 "authorized_validation_forward_batches": len(starts), "completed_validation_batches": len(completed),
                                 "discovery_errors": [r for r in discovery if r["event"] == "error"],
                                 "validation_errors": [r for r in validation if r["event"] == "error"],
                                 "maximum_successful_evaluations_per_fresh_input": max(test_ids.values(), default=0),
                                 "note": "Includes two GPU export traces. ORT Torch allocator peaks are not its GPU memory use; see CUDA profiles. Separate excluded CPU reviewer work is disclosed below."},
        "protocol_deviations": json.loads((args.out / "protocol-deviations.json").read_text()),
        "acceptance": {"fresh_done_recall_improves": recall["DONE"] > baseline["recall"]["DONE"],
                       "fresh_macro_f1_improves": test["macro_f1"] > baseline["macro_f1"],
                       "fresh_not_started_drop_within_five_points": recall["NOT_STARTED"] >= baseline["recall"]["NOT_STARTED"] - .05,
                       "no_additional_old_family_prediction_changes": old_changes == 0,
                       "fp32_export_same_predictions": all(not onnx[f"fp32-{c}"]["changed_vs_native"] for c in (2, 3)),
                       "int4_same_predictions": all(not onnx[f"int4-{c}"]["changed_vs_native"] for c in (2, 3))}}
    failed = [name for name, passed in output["acceptance"].items() if not passed]
    output["status"] = "not certified; failed checks: " + ", ".join(failed) if failed else "recorded weight checks passed; no serving bundle certified or deployed"
    write_json(args.out / "validation-results.json", output)
    print(json.dumps({"status": output["status"], "acceptance": output["acceptance"],
                      "recall": recall, "false_done": false_done, "done_precision": output["fresh_test"]["done_precision"],
                      "accounting": output["inference_accounting"]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["freeze", "old", "export", "quantize", "onnx", "test", "report"])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--classes", choices=[2, 3], type=int, default=3)
    parser.add_argument("--backend", choices=["fp32", "int4"], default="int4")
    args = parser.parse_args()
    {"freeze": freeze, "old": old_native, "export": export, "quantize": quantize,
     "onnx": onnx_predictions, "test": fresh_test, "report": report}[args.command](args)


if __name__ == "__main__":
    main()
