"""Gradient-free INT4 recovery, separately authorized after the initial study.

DEV/controlled examples and old-family diagnostics only. No fresh TEST access,
no change to the earlier frozen candidate, and no deployment. Each classifier
forward is recorded in this study's int4-ledger.jsonl, including head replays.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import json
from pathlib import Path

from suite.gliclass_quantize import equalize_readout, quantize_relative_table, set_matrix
from suite.progress_weight_directions import panel_report
from suite.progress_weight_study import OUT, setup_gpu, write_json
from suite.progress_weight_validate import CANDIDATE, old_rows, onnx_placements, onnx_rows, onnx_session

COMPONENTS = {
    "readout": "/scorer/mlp/mlp.4/", "scorer": "/scorer/",
    "class-projector": "/classes_projector/", "text-projector": "/text_projector/",
    "calibrator": "/calibrator/", "encoder": "/encoder_model/", "embedding": "/embeddings/word_embeddings/",
}
HYPOTHESIS = "The specified precision intervention removes the INT4 discrepancy of the frozen native candidate. Refuted if recovered DONE decisions still disappear or new discrepancies remain. DEV/control inputs diagnose fidelity, not fresh generalization; old-family changes are reported separately."


def selected(node, components):
    return any(("/encoder_model/" not in node.name if component == "head" else COMPONENTS[component] in node.name)
               for component in components)


def add_features(model):
    import onnx
    nodes = list(model.graph.node)

    def output(suffix):
        found = [n.output[0] for n in nodes if n.name.endswith(suffix)]
        if len(found) != 1:
            raise ValueError((suffix, found))
        return found[0]

    first = next(n for n in nodes if "/classes_projector/linear_1/MatMul" in n.name)
    capture = {
        "layer24": (first.input[0], [None, None, 1024]),
        "projected": (output("/classes_projector/linear_2/Add"), [None, None, 1024]),
        "text_embeddings": (output("/text_projector/linear_2/Gemm_Add"), [None, 1024]),
        "scorer_relu2": (output("/scorer/mlp/mlp.3/Relu"), [None, None, 128]),
        "raw_logits": (output("/scorer/Squeeze"), [None, None]),
    }
    for name, shape in capture.values():
        model.graph.output.append(onnx.helper.make_tensor_value_info(name, onnx.TensorProto.FLOAT, shape))
    return {key: name for key, (name, _shape) in capture.items()}


def noise_aware_readout(args):
    """Preserve only old-family directions distinguishable above quantization noise.

    The spectral norm of measured INT4 feature error bounds singular-value
    uncertainty. Protect the anchor singular directions above that bound, then
    perform the same single class-identity removal. Rank is determined by noise,
    not a score sweep. No held-out labels or TEST predictions enter construction.
    """
    import numpy as np
    folder = args.out / "equalized-int4-2"
    records = json.loads((folder / "anchors.json").read_text())["predictions"]
    quantized = np.load(folder / "anchors-features.npz")["scorer_relu2"].astype(np.float64)
    scale = np.array(json.loads((folder / "build.json").read_text())["readout_equalization"]["channel_scale"])
    original_rows = json.loads((args.source / "old-anchors-predictions.json").read_text())
    original = np.load(args.source / "old-anchors-representations.npz")["scorer_relu2"].astype(np.float64)
    lookup = {r["id"]: i for i, r in enumerate(records)}
    quantized = quantized[[lookup[r["id"]] for r in original_rows]] / scale
    noise = float(np.linalg.norm((quantized - original).reshape(-1, 128), 2))
    _left, singular, right = np.linalg.svd(original.reshape(-1, 128), full_matrices=False)
    rank = int((singular > noise).sum())
    u = np.load(args.source / "directions.npz")["scorer_relu2_identity"]
    projected = u - right[:rank].T @ (right[:rank] @ u)
    v = projected / (u @ projected)
    old = np.array(json.loads((args.source / "candidate-weight.json").read_text())["old"], dtype=np.float64)
    new = (old - np.outer(old @ u, v)).astype(np.float32)
    result = {"operation": noise_aware_readout.__doc__, "rank": rank, "noise_spectral_norm": noise,
              "direction": u.tolist(), "protected_dual": v.tolist(), "amplification": float(np.linalg.norm(v)),
              "old": old.tolist(), "new": new.tolist(), "changed_values": int(np.count_nonzero(new != old)),
              "source_anchor_ids": [r["id"] for r in original_rows], "fresh_test_accessed": False}
    write_json(args.out / f"{args.variant}-weight.json", result)
    print("noise-aware rank", rank, "amplification", result["amplification"], flush=True)


def compensate_quantization(args):
    """One closed-form correction of quantization error, not correctness labels.

    Fit the original frozen teacher's RAW score residual using four DEV tasks
    and the original 32 old TRAIN anchors. Center features/residuals, retain
    singular directions above the measured feature-error spectral norm, then
    solve that truncated system once. The last three DEV tasks, corruption
    controls and 32 transfer anchors are excluded from coefficient construction.
    No hyperparameter sweep, gradients, optimization loop or TEST access.
    """
    import numpy as np
    from safetensors import safe_open
    from suite.progress_weight_study import AFTER
    teacher_dev = json.loads((args.source / "dev-predictions.json").read_text())
    teacher_old = json.loads((args.source / "old-anchors-predictions.json").read_text())
    raw_dev = {r["id"]: r for r in json.loads((args.source / f"direction-{CANDIDATE}-native.json").read_text())["predictions"]}
    raw_old = {r["id"]: r for r in json.loads((args.source / "old-anchors-readout-protected-report.json").read_text())["predictions"]}
    source_tasks = sorted({r["task"] for r in teacher_dev})[:4]
    x, fp, residual, identities = [], [], [], []
    for classes, stem, rows, raw in ((3, "dev", teacher_dev, raw_dev), (2, "old-anchors", teacher_old, raw_old)):
        folder = args.out / f"equalized-block64-{classes}"
        result_stem = "results" if classes == 3 else "anchors"
        quant_rows = json.loads((folder / f"{result_stem}.json").read_text())["predictions"]
        quant = np.load(folder / f"{result_stem}-features.npz")
        scale = np.array(json.loads((folder / "build.json").read_text())["readout_equalization"]["channel_scale"])
        floating = np.load(args.source / f"{stem}-representations.npz")["scorer_relu2"]
        lookup = {r["id"]: i for i, r in enumerate(quant_rows)}
        for i, row in enumerate(rows):
            if classes == 3 and row["task"] not in source_tasks:
                continue
            j = lookup[row["id"]]
            x.extend(quant["scorer_relu2"][j].astype(np.float64) / scale)
            fp.extend(floating[i].astype(np.float64))
            residual.extend(np.array(raw[row["id"]]["uncalibrated_logits"]) - quant["raw_logits"][j])
            identities.append(row["id"])
    x, fp, residual = np.array(x), np.array(fp), np.array(residual)
    xc, fc = x - x.mean(0), fp - fp.mean(0)
    noise = float(np.linalg.norm(xc - fc, 2))
    left, singular, right = np.linalg.svd(xc, full_matrices=False)
    rank = int((singular > noise).sum())
    delta = right[:rank].T @ ((left[:, :rank].T @ (residual - residual.mean())) / singular[:rank])
    bias_delta = float(residual.mean() - x.mean(0) @ delta)
    old = np.array(json.loads((args.source / "candidate-weight.json").read_text())["new"], dtype=np.float64)
    with safe_open(AFTER / "model.safetensors", framework="numpy", device="cpu") as tensors:
        bias_old = float(tensors.get_tensor("model.scorer.mlp.4.bias")[0])
    result = {"operation": compensate_quantization.__doc__, "rank": rank, "noise_spectral_norm": noise,
              "source_tasks": source_tasks, "source_ids": identities, "old": old.tolist(),
              "new": (old + delta).astype(np.float32).tolist(), "delta_norm": float(np.linalg.norm(delta)),
              "bias_old": bias_old, "bias_new": float(np.float32(bias_old + bias_delta)),
              "fresh_test_accessed": False, "frozen_teacher_changed": False}
    write_json(args.out / f"{args.variant}-weight.json", result)
    print("quantization correction rank", rank, "delta norm", result["delta_norm"], "bias delta", bias_delta, flush=True)


def requantize_matrices(model, source, block_size, components=()):
    """Data-free RTN with smaller matrix blocks; embeddings retain their recipe."""
    from onnx import numpy_helper
    original = {t.name: t for t in source.graph.initializer}
    nodes = {tuple(n.output): n for n in source.graph.node}
    changed = []
    for node in model.graph.node:
        if node.op_type != "MatMulNBits" or (components and not selected(node, components)):
            continue
        counterpart = nodes[tuple(node.output)]
        set_matrix(model, node, numpy_helper.to_array(original[counterpart.input[1]]), block_size=block_size)
        changed.append(node.name)
    return changed


def build(args):
    """Swap selected original FP32/INT4 operators, not new fitted weights."""
    import onnx
    from onnxruntime.quantization.onnx_model import ONNXModel
    root = args.source / f"validation-export-{args.classes}"
    sources = {"fp32": root / "normalized-fp32.onnx", "int4": root / "int4/model.onnx"}
    model = onnx.load(sources[args.base])
    donor = onnx.load(sources["int4" if args.base == "fp32" else "fp32"])
    if args.base == "int4":
        # Older ORT saves sorted only explicit edges, ignoring If captures.
        # The one-for-one QOperator graph inherits its valid FP32 producer order.
        order = {tuple(n.output): i for i, n in enumerate(donor.graph.node)}
        nodes = sorted(model.graph.node, key=lambda n: order[tuple(n.output)])
        model.graph.ClearField("node")
        model.graph.node.extend(nodes)
    replaced = []
    if args.swap:
        donor_nodes = {tuple(n.output): n for n in donor.graph.node}
        donor_weights = {t.name: t for t in donor.graph.initializer}
        weights = {t.name: t for t in model.graph.initializer}
        for node in model.graph.node:
            if node.op_type not in ("MatMul", "MatMulNBits", "Gather", "GatherBlockQuantized") or not selected(node, args.swap):
                continue
            other = donor_nodes.get(tuple(node.output))
            if other is None or other.op_type == node.op_type:
                continue
            replaced.append({"node": node.name, "from": node.op_type, "to": other.op_type})
            node.CopyFrom(other)
            for name in node.input:
                if name in donor_weights and name not in weights:
                    model.graph.initializer.append(donor_weights[name])
                    weights[name] = donor_weights[name]
        domains = {v.domain for v in model.opset_import}
        for version in donor.opset_import:
            if version.domain not in domains:
                model.opset_import.append(version)
        del donor_nodes, donor_weights, weights
    reblocked = requantize_matrices(model, donor, args.matrix_block) if args.matrix_block else []
    head_reblocked = requantize_matrices(model, donor, args.head_block, ("class-projector", "scorer", "calibrator")) if args.head_block else []
    override = json.loads(args.readout.read_text()) if args.readout else None
    if override:
        import numpy as np
        floating = donor if args.base == "int4" else model
        node = next(n for n in floating.graph.node if n.name.endswith("/scorer/mlp/mlp.4/MatMul"))
        value = np.array(override["new"], dtype=np.float32).T
        set_matrix(floating, node, value)
        if args.base == "int4":
            target = next(n for n in model.graph.node if tuple(n.output) == tuple(node.output))
            set_matrix(model, target, value)
        if "bias_new" in override:
            from onnx import numpy_helper
            bias_name = next(n for n in floating.graph.node if n.name.endswith("/scorer/mlp/mlp.4/Add")).input[0]
            for graph in (floating, model) if args.base == "int4" else (model,):
                tensor = next(t for t in graph.graph.initializer if t.name == bias_name)
                tensor.CopyFrom(numpy_helper.from_array(np.array([override["bias_new"]], dtype=np.float32), bias_name))
    normalization = equalize_readout(model, donor if args.base == "int4" else model) if args.equalize_readout else None
    del donor
    relative = quantize_relative_table(model) if args.relative_int4 else None
    ONNXModel(model).clean_initializers()
    capture = add_features(model)
    folder = args.out / f"{args.variant}-{args.classes}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "model.onnx"
    operators = dict(Counter(n.op_type for n in model.graph.node))
    # Save a standalone research graph; never mutate a previously validated bundle.
    data = folder / "weights.data"
    if data.exists():
        data.unlink()  # ONNX external-data writing otherwise appends to the old file.
    onnx.save_model(model, path, save_as_external_data=True, all_tensors_to_one_file=True,
                    location=data.name, size_threshold=1024)
    del model
    gc.collect()
    onnx.checker.check_model(str(path))
    info = {"variant": args.variant, "classes": args.classes, "base": args.base,
            "swapped_components": args.swap, "replaced_operators": replaced, "source": str(sources[args.base]),
            "capture": capture, "operators": operators, "graph_and_weights_bytes": path.stat().st_size + data.stat().st_size,
            "hypothesis": (override["operation"] + " Refuted by old-family regressions, lost DONE recovery or a failure to improve source-excluded precision agreement." if override else HYPOTHESIS), "readout_equalization": normalization,
            "matrix_block_size": args.matrix_block, "reblocked_nodes": reblocked,
            "head_block_size": args.head_block, "head_reblocked_nodes": head_reblocked,
            "relative_position_quantization": relative,
            "readout_override": override, "original_candidate_file_changed": False, "fresh_test_accessed": False}
    write_json(folder / "build.json", info)
    print(json.dumps(info, indent=2), flush=True)


def panel(source, classes, *, anchors=False):
    if classes == 2:
        if anchors:
            rows = json.loads((source / "old-anchors-inputs.json").read_text())
            rows += json.loads((source / "old-transfer-inputs.json").read_text())
            for row in rows:
                row.setdefault("task", "TRAIN/" + row["family"])
            references = []
            for stem in ("old-anchors", "old-transfer"):
                references += json.loads((source / f"{stem}-readout-protected-report.json").read_text())["predictions"]
        else:
            rows, _ = old_rows()
            references = json.loads((source / "validation-old-native.json").read_text())["candidate"]
    else:
        rows = json.loads((source / "dev-inputs.json").read_text())
        rows += [r for r in json.loads((source / "controls-inputs.json").read_text()) if r["label"] == "PARTIAL"]
        references = json.loads((source / f"direction-{CANDIDATE}-native.json").read_text())["predictions"]
    return rows, {r["id"]: r for r in references}


def fidelity(records, references):
    """Decision agreement and continuous errors from the actual calibrated outputs."""
    import numpy as np
    from suite.progress_dataset import LABELS
    details = []
    for row in records:
        ref = references[row["id"]]
        labels = ref.get("labels", LABELS)
        winner = labels.index(ref["prediction"])
        errors = [abs(a-b) for a,b in zip(row["logits"], ref["logits"])]
        margins = [{"rival": labels[i], "reference_margin": ref["logits"][winner] - b,
                    "observed_margin": row["logits"][winner] - row["logits"][i]}
                   for i,b in enumerate(ref["logits"]) if i != winner]
        for margin in margins:
            margin["absolute_error"] = abs(margin["observed_margin"] - margin["reference_margin"])
        details.append({"id": row["id"], "max_absolute_logit_error": max(errors),
                        "winner_margins": margins, "sufficient_margin_bound": all(m["reference_margin"] > m["absolute_error"] for m in margins)})
    absolute = [d["max_absolute_logit_error"] for d in details]
    return {"changed_vs_reference": [r["id"] for r in records if r["prediction"] != references[r["id"]]["prediction"]],
            "max_logit_difference": max(absolute), "mean_per_input_max_logit_error": float(np.mean(absolute)),
            "p95_per_input_max_logit_error": float(np.percentile(absolute, 95)), "per_input": details}


def result_report(source, records, references, classes):
    result = fidelity(records, references)
    if classes == 3:
        dev = [r for r in records if not r["id"].startswith("control/")]
        by_id = {r["id"]: r for r in records}
        controls = json.loads((source / "controls-predictions.json").read_text())
        matched = [{**by_id[r["id"] if r["label"] == "PARTIAL" else r["id"].removeprefix("control/")], "id": r["id"]}
                   for r in controls]
        result.update(dev=panel_report(dev), controls=panel_report(matched))
    else:
        result["groups"] = {family: {"count": sum(r["family"] == family for r in records),
            "changed": [r["id"] for r in records if r["family"] == family and r["id"] in result["changed_vs_reference"]],
            "correct": sum(r["family"] == family and r["prediction"] == r["label"] for r in records)}
            for family in sorted({r["family"] for r in records})}
    return result


def evaluate(args):
    import numpy as np
    torch = setup_gpu()
    folder = args.out / f"{args.variant}-{args.classes}"
    info = json.loads((folder / "build.json").read_text())
    rows, references = panel(args.source, args.classes, anchors=args.anchors)
    path = (args.out / f"{args.variant}-packed" / ("model.onnx" if args.classes == 2 else "progress.onnx")) if args.packed else folder / "model.onnx"
    stem = "anchors" if args.anchors else "results"
    if args.packed:
        stem = "packed-" + stem
    if args.reference_variant:
        previous = json.loads((args.out / f"{args.reference_variant}-{args.classes}" / f"{stem}.json").read_text())
        references = {r["id"]: r for r in previous["predictions"]}
    engine = onnx_session(path, folder / f"{stem}-profile")
    records, features = onnx_rows(args.out, torch, engine, rows, args.classes, phase="int4",
        purpose=f"INT4 recovery {args.variant}: {args.classes} slots; {stem}", hypothesis=info["hypothesis"], model=path,
        edit=info, dtype="FP32 activations; precision interventions recorded in build.json", capture={} if args.packed else info["capture"])
    profile = engine.end_profiling()
    del engine
    gc.collect()
    np.savez_compressed(folder / f"{stem}-features.npz", **features)
    result = {"variant": args.variant, "classes": args.classes, "predictions": records,
              "reference": args.reference_variant or "original-frozen-native",
              "profile": profile, "operator_placements": onnx_placements(profile),
              **result_report(args.source, records, references, args.classes)}
    if args.packed:
        unpacked = json.loads((folder / f"{stem.removeprefix('packed-')}.json").read_text())["predictions"]
        result["vs_unpacked"] = result_report(args.source, records, {r["id"]: r for r in unpacked}, args.classes)
    write_json(folder / f"{stem}.json", result)
    print(args.variant, "changed", len(result["changed_vs_reference"]), "max difference", result["max_logit_difference"], flush=True)
    if args.classes == 3:
        print("DEV", result["dev"]["confusion"], "control", result["controls"]["confusion"], flush=True)
    else:
        print(result["groups"], flush=True)


def compact_names(model):
    """Lossless private-symbol renaming, including lexical subgraph captures.

    Keep public input/output and initializer names. One injective mapping across
    all scopes preserves both captured values and any locally shadowed symbols.
    No graph optimization, weight rounding or arithmetic rewrite is performed.
    """
    import onnx

    def graphs(graph):
        yield graph
        for node in graph.node:
            for attr in node.attribute:
                if attr.type == onnx.AttributeProto.GRAPH:
                    yield from graphs(attr.g)
                elif attr.type == onnx.AttributeProto.GRAPHS:
                    for child in attr.graphs:
                        yield from graphs(child)

    scopes = list(graphs(model.graph))
    keep = {v.name for v in (*model.graph.input, *model.graph.output)}
    keep.update(t.name for g in scopes for t in g.initializer)
    names = {v.name for g in scopes for v in (*g.input, *g.output, *g.value_info)}
    names.update(s for g in scopes for n in g.node for s in (*n.input, *n.output) if s)
    mapping = {}
    i = 0
    for name in sorted(names - keep):
        while f"v{i}" in keep:
            i += 1
        mapping[name] = f"v{i}"
        i += 1
    node_index = 0
    for graph in scopes:
        for value in (*graph.input, *graph.output, *graph.value_info):
            value.name = mapping.get(value.name, value.name)
        for node in graph.node:
            node.name = f"n{node_index}"
            node_index += 1
            for slots in (node.input, node.output):
                for j, name in enumerate(slots):
                    slots[j] = mapping.get(name, name)


def save_shared_graphs(models, folder):
    """Store identical initializer payloads once; graphs retain their own shapes.

    Models may be a lazy iterable so only one full graph need be resident.
    Byte comparison is storage deduplication, not a candidate approval gate.
    """
    import onnx
    from onnx.external_data_helper import set_external_data
    folder.mkdir(parents=True, exist_ok=True)
    bank = {}
    with (folder / "weights.data").open("wb") as stream:
        for filename, model in models:
            compact_names(model)
            for tensor in model.graph.initializer:
                data = tensor.raw_data
                if len(data) < 1024:
                    continue
                key = (tensor.name, tensor.data_type, tuple(tensor.dims))
                entries = bank.setdefault(key, [])
                offset = next((offset for old, offset in entries if old == data), None)
                if offset is None:
                    offset = stream.tell()
                    stream.write(data)
                    entries.append((data, offset))
                set_external_data(tensor, location="weights.data", offset=offset, length=len(data))
                tensor.ClearField("raw_data")
            onnx.save_model(model, folder / filename)
    for filename in ("model.onnx", "progress.onnx"):
        onnx.checker.check_model(str(folder / filename))


def pack(args):
    """Standalone research package, never installed or substituted for the live one."""
    import shutil
    import onnx
    from suite.progress_weight_study import AFTER
    folder = args.out / f"{args.variant}-packed"

    def models():
        for i, (classes, name) in enumerate(((2, "model.onnx"), (3, "progress.onnx"))):
            source = args.graphs[i] if args.graphs else args.out / f"{args.variant}-{classes}" / "model.onnx"
            model = onnx.load(source)
            output = next(v for v in model.graph.output if v.name == "logits")
            model.graph.ClearField("output")
            model.graph.output.append(output)
            yield name, model

    save_shared_graphs(models(), folder)
    for name in ("tokenizer.json", "tokenizer_config.json", "config.json"):
        shutil.copyfile((args.checkpoint_path or AFTER) / name, folder / name)
    from suite.progress_weight_validate import SELFTEST
    shutil.copytree(SELFTEST.parent / "policy", folder / "policy", dirs_exist_ok=True)
    # The historical producer records are retained separately. CPU verification
    # writes this candidate's own self-test record, never edits the live record.
    shutil.copyfile(SELFTEST, folder / "historical-selftest.json")
    graph_weights = sum((folder / name).stat().st_size for name in ("model.onnx", "progress.onnx", "weights.data"))
    write_json(folder / "package.json", {"variant": args.variant, "graph_and_weights_bytes": graph_weights,
        "graphs": {"old_families": "model.onnx", "progress": "progress.onnx"},
        "transformation": "shared identical weight payloads; bijective private-symbol renaming; diagnostic outputs removed; arithmetic unchanged",
        "production_progress_routing_implemented": False, "deployed": False})
    print("shared graphs and weights", graph_weights, flush=True)


def cpu_verify(args):
    """CPU compatibility and the real old-family production startup, not deployment.

    Six existing self-test inputs generate this candidate's producer records;
    the inherited production startup then independently replays all six through
    its real tokenizer, renderer, decoder, CPU session and logit tolerance.
    Three deterministic DEV examples (first per label) check the progress graph.
    Every forward, including startup replay, is recorded. Fresh TEST is absent.
    """
    import resource
    from cria.system1 import System1Runtime, System1Error, SELFTEST_ATOL, SELFTEST_RTOL
    from suite.progress_dataset import LABELS
    from suite.progress_weight_study import recorded_forward
    torch = setup_gpu()
    folder = args.out / f"{args.variant}-packed"
    historical = json.loads((folder / "historical-selftest.json").read_text())
    cases = []
    result = {"variant": args.variant, "deployed": False, "production_progress_routing_implemented": False}
    for classes in (2, 3):
        rows, _ = panel(args.source, classes)
        if classes == 2:
            by_id = {r["id"]: r for r in rows}
            rows = [by_id[r["id"]] for r in historical]
        else:
            rows = [next(r for r in rows if r["label"] == label) for label in LABELS]
        path = folder / ("model.onnx" if classes == 2 else "progress.onnx")
        engine = onnx_session(path, folder / f"cpu-{classes}-profile", cpu=True)
        records = []
        for row in rows:
            observed, _ = onnx_rows(args.out, torch, engine, [row], classes, phase="int4",
                purpose=f"Packed CPU compatibility: {classes} slots", hypothesis=cpu_verify.__doc__,
                model=path, edit=args.variant, dtype="INT4 weights; FP32 activations")
            records.extend(observed)
        profile = engine.end_profiling()
        del engine
        gc.collect()
        cuda = json.loads((args.out / f"{args.variant}-{classes}" / "results.json").read_text())["predictions"]
        reference = {r["id"]: r for r in cuda}
        result[str(classes)] = {"predictions": records, "profile": profile, "operator_placements": onnx_placements(profile),
            "changed_vs_cuda": [r["id"] for r in records if r["prediction"] != reference[r["id"]]["prediction"]],
            "max_logit_difference_vs_cuda": max(abs(a-b) for r in records for a,b in zip(r["logits"], reference[r["id"]]["logits"]))}
        if classes == 2:
            for old, record in zip(historical, records):
                cases.append({**old, "label": record["prediction"], "logits": record["logits"]})
            result["historical_startup_records_matching"] = [old["id"] for old, record in zip(historical, records)
                if old["label"] == record["prediction"] and all(abs(a-b) <= SELFTEST_ATOL + SELFTEST_RTOL * abs(b)
                for a,b in zip(record["logits"], old["logits"]))]
    write_json(folder / "selftest.json", cases)
    rows, _ = panel(args.source, 2)
    by_id = {r["id"]: r for r in rows}

    class RecordedRuntime(System1Runtime):
        def infer(self, family, state):
            case = next(c for c in cases if c["family"] == family and c["state"] == state)
            row = by_id[case["id"]]

            def run():
                judgment = super(RecordedRuntime, self).infer(family, state)
                return {"judgment": judgment, "predictions": [{"id": case["id"], "family": family,
                    "prediction": judgment.label, "logits": list(judgment.logits), "tokens": judgment.token_count}]}

            return recorded_forward(args.out, torch, run, phase="int4", purpose="Real CPU production startup self-test",
                hypothesis=cpu_verify.__doc__, examples=[case["id"]], tokens=[row["tokens"]], shape=[1, row["tokens"]],
                dtype="INT4 weights; FP32 activations", model=str(folder / "model.onnx"), edit=args.variant,
                providers=self._session.get_providers(), memory_note="CPU ORT; Torch CUDA allocator does not measure CPU memory")["judgment"]

    try:
        runtime = RecordedRuntime(folder, threads=2, memory_budget_bytes=2 * 1024**3)
        result["production_old_family_startup"] = {"passed": True, "cases": len(cases), "providers": runtime._session.get_providers()}
        del runtime
    except System1Error as exc:
        result["production_old_family_startup"] = {"passed": False, "error": str(exc)}
    result["process_peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    result["graph_and_weights_bytes"] = sum((folder / n).stat().st_size for n in ("model.onnx", "progress.onnx", "weights.data"))
    payload = [folder / n for n in ("model.onnx", "progress.onnx", "weights.data", "tokenizer.json", "tokenizer_config.json", "config.json", "selftest.json")]
    payload.extend((folder / "policy").glob("*.txt"))
    result["payload_files"] = {str(p.relative_to(folder)): p.stat().st_size for p in payload}
    result["research_package_payload_bytes"] = sum(result["payload_files"].values())
    write_json(folder / "cpu-compatibility.json", result)
    print(json.dumps({k: v for k,v in result.items() if k not in ("2", "3")}, indent=2), flush=True)


def checkpoint(args):
    """Save the frozen repaired native weights as a standalone reloadable checkpoint.

    This applies this study's specific readout repair, not a generic correction
    for future training. Quantization's data-free equalization is kept separate.
    """
    import numpy as np
    import shutil
    from safetensors.numpy import load_file, save_file
    from suite.progress_weight_study import AFTER
    from suite.progress_weight_directions import READOUT
    folder = args.out / "checkpoint"
    folder.mkdir(parents=True, exist_ok=True)
    repair = json.loads((args.source / "candidate-weight.json").read_text())
    weights = load_file(AFTER / "model.safetensors")
    weights[READOUT] = np.array(repair["new"], dtype=np.float32)
    save_file(weights, folder / "model.safetensors", metadata={"format": "pt"})
    for name in ("config.json", "tokenizer.json", "tokenizer_config.json"):
        shutil.copyfile(AFTER / name, folder / name)
    shutil.copyfile(args.source / "candidate-weight.json", folder / "readout-repair.json")
    write_json(folder / "checkpoint-notes.json", {"source": str(AFTER), "changed_tensor": READOUT,
        "repair_specific_to_this_checkpoint": True, "quantization_equalization_applied": False,
        "deployed": False, "fresh_test_used_for_followup": False,
        "quantization_command": "python -m suite.gliclass_quantize --root EXPORT_ROOT --matrix-block 64 --equalize-readout",
        "relative_position_note": "The command retains the standard FP32 positional table; --relative-int4 is a separate measured variant, not an interchangeable recipe."})
    print("Saved standalone native checkpoint", folder, flush=True)


def verify_reproduction(args):
    """Compare fresh checkpoint exports against the selected research outputs, without TEST."""
    torch = setup_gpu()
    for classes in (2, 3):
        folder = args.out / f"reproduced-{classes}"
        path = folder / "int4/model.onnx"
        rows, _ = panel(args.source, classes)
        reference = json.loads((args.out / f"{args.variant}-{classes}" / "results.json").read_text())["predictions"]
        engine = onnx_session(path, folder / "comparison-profile")
        records, _ = onnx_rows(args.out, torch, engine, rows, classes, phase="int4",
            purpose=f"Saved native checkpoint and reusable quantizer reproduction: {classes} slots",
            hypothesis=verify_reproduction.__doc__, model=path, edit=json.loads((folder / "int4/recipe.json").read_text()),
            dtype="INT4 dense/token weights; FP32 positional table/activations")
        profile = engine.end_profiling()
        del engine
        gc.collect()
        result = {"predictions": records, "operator_placements": onnx_placements(profile),
                  **result_report(args.source, records, {r["id"]: r for r in reference}, classes)}
        write_json(folder / "comparison.json", result)
        print("reproduced", classes, "changed", len(result["changed_vs_reference"]), "max logit error", result["max_logit_difference"], flush=True)


def report(args):
    """Collate follow-up evidence only; no inference or spent TEST access."""
    from suite.progress_weight_study import jsonl
    variants = []
    for folder in sorted(args.out.glob("*-[23]")):
        if not (folder / "build.json").exists():
            continue
        build_info = json.loads((folder / "build.json").read_text())
        classes = build_info["classes"]
        for stem in ("results", "anchors", "packed-results"):
            if not (folder / f"{stem}.json").exists():
                continue
            stored = json.loads((folder / f"{stem}.json").read_text())
            _, reference = panel(args.source, classes, anchors=stem == "anchors")
            source = stored.get("reference", "original-frozen-native")
            if source != "original-frozen-native":
                rows = json.loads((args.out / f"{source}-{classes}" / f"{stem}.json").read_text())["predictions"]
                reference = {r["id"]: r for r in rows}
            comparison = fidelity(stored["predictions"], reference)
            variants.append({"variant": build_info["variant"], "classes": classes, "panel": stem,
                "inputs": len(stored["predictions"]), "reference": source,
                "graph_and_weights_bytes": build_info.get("graph_and_weights_bytes", build_info.get("bundle_bytes")),
                "dev": stored.get("dev"), "controls": stored.get("controls"), "groups": stored.get("groups"),
                "operator_placements": stored["operator_placements"], **comparison})
    ledgers = {}
    for path in [args.out / "int4-ledger.jsonl", *sorted(args.out.glob("reproduced-*/int4-ledger.jsonl"))]:
        rows = jsonl(path)
        starts = [r for r in rows if r["event"] == "start"]
        ledgers[str(path.relative_to(args.out))] = {"started": len(starts),
            "completed": sum(r["event"] == "result" for r in rows), "errors": [r for r in rows if r["event"] == "error"],
            "cpu_only_batches": sum(r.get("providers") == ["CPUExecutionProvider"] for r in starts)}
    result = {"status": "DONE recovery survives INT4; strict original-native decision fidelity still fails; not deployed",
        "selected_research_variant": args.variant, "variants": variants, "ledgers": ledgers,
        "total_followup_completed_batches": sum(r["completed"] for r in ledgers.values()),
        "original_study_counts_unchanged": {"discovery": 50, "validation": 51},
        "fresh_test_accessed": False,
        "checkpoint": str(args.out / "checkpoint"),
        "checkpoint_verification": json.loads((args.out / "checkpoint/save-verification.json").read_text()),
        "cpu_compatibility": json.loads((args.out / f"{args.variant}-packed/cpu-compatibility.json").read_text()),
        "reproduction": {str(c): json.loads((args.out / f"reproduced-{c}/comparison.json").read_text()) for c in (2, 3)}}
    write_json(args.out / "followup-results.json", result)
    print("follow-up completed batches", result["total_followup_completed_batches"], flush=True)
    for row in variants:
        if row["variant"] in (args.variant, "equalized-head32", "equalized-allq4"):
            print(row["variant"], row["classes"], row["panel"], "changes", len(row["changed_vs_reference"]),
                  "mean max logit error", row["mean_per_input_max_logit_error"], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "evaluate", "design", "compensate", "pack", "cpu", "checkpoint", "verify-reproduction", "report"])
    parser.add_argument("--source", type=Path, default=OUT)
    parser.add_argument("--out", type=Path, default=OUT / "int4-repair")
    parser.add_argument("--variant", required=True)
    parser.add_argument("--classes", choices=[2, 3], type=int, default=3)
    parser.add_argument("--base", choices=["fp32", "int4"], default="int4")
    parser.add_argument("--swap", choices=[*COMPONENTS, "head"], nargs="*", default=[])
    parser.add_argument("--anchors", action="store_true")
    parser.add_argument("--packed", action="store_true")
    parser.add_argument("--equalize-readout", action="store_true")
    parser.add_argument("--relative-int4", action="store_true")
    parser.add_argument("--matrix-block", type=int, choices=[16, 32, 64, 128])
    parser.add_argument("--head-block", type=int, choices=[16, 32, 64, 128])
    parser.add_argument("--readout", type=Path)
    parser.add_argument("--reference-variant")
    parser.add_argument("--graphs", type=Path, nargs=2, metavar=("TWO_SLOT", "THREE_SLOT"))
    parser.add_argument("--checkpoint-path", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    {"build": build, "evaluate": evaluate, "design": noise_aware_readout, "compensate": compensate_quantization, "pack": pack, "cpu": cpu_verify, "checkpoint": checkpoint, "verify-reproduction": verify_reproduction, "report": report}[args.command](args)


if __name__ == "__main__":
    main()
