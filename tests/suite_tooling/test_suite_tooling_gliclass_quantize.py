"""Small deterministic export fixtures; no trained classifier, GPU or network."""
import copy
import json

import pytest

np = pytest.importorskip("numpy")
onnx = pytest.importorskip("onnx")
pytest.importorskip("onnxoptimizer")
pytest.importorskip("onnxruntime")
from onnx import TensorProto as T, helper as h, numpy_helper as nh

from suite import gliclass_quantize as quant
from suite.progress_int4_study import equalize_readout, save_shared_graphs
from suite.onejev_probe import file_sha


def captured_graph():
    embedding = np.arange(256, dtype=np.float32).reshape(2, 128) / 128
    weight = np.linspace(-1, 1, 128, dtype=np.float32).reshape(1, 128)
    branch = lambda op: h.make_graph([h.make_node(op, ["long/private/captured"], ["branch_out"])], op, [],
                                    [h.make_tensor_value_info("branch_out", T.FLOAT, [1, 1])])
    graph = h.make_graph([
        h.make_node("Gather", ["embedding", "ids"], ["long/private/embedded"]),
        h.make_node("Gemm", ["long/private/embedded", "weight", "bias"], ["long/private/captured"], transB=1),
        h.make_node("If", ["condition"], ["logits"], then_branch=branch("Identity"), else_branch=branch("Neg")),
    ], "captures", [h.make_tensor_value_info("ids", T.INT64, [1]), h.make_tensor_value_info("condition", T.BOOL, [])],
        [h.make_tensor_value_info("logits", T.FLOAT, [1, 1])],
        [nh.from_array(embedding, "embedding"), nh.from_array(weight, "weight"), nh.from_array(np.array([.3], np.float32), "bias")])
    return h.make_model(graph, opset_imports=[h.make_opsetid("", 20)], ir_version=10)


def test_normalization_owns_its_externalization_and_gemm_transpose():
    model = captured_graph()
    before = model.SerializeToString()
    expected = nh.to_array(model.graph.initializer[1]).T.copy()
    normalized = quant.normalize_linear_layers(model)
    assert model.SerializeToString() == before  # caller remains usable after temporary files disappear
    onnx.checker.check_model(normalized)
    linear = next(n for n in normalized.graph.node if n.op_type == "MatMul")
    weights = {t.name: nh.to_array(t) for t in normalized.graph.initializer}
    np.testing.assert_array_equal(weights[linear.input[1]], expected)
    assert not any(n.op_type == "Gemm" for n in normalized.graph.node)


@pytest.mark.parametrize("matrix_block,relative", [(128, False), (64, False), (64, True)])
def test_quantized_save_respects_values_captured_by_if(tmp_path, matrix_block, relative):
    """ORT's explicit-edge-only saver used to move If before its captured producer."""
    snapshot = tmp_path / "native"
    path = snapshot / "onnx/model.onnx"
    path.parent.mkdir(parents=True)
    source = captured_graph()
    if relative:
        source.graph.initializer[0].name = "encoder.rel_embeddings.weight"
        source.graph.node[0].input[0] = "encoder.rel_embeddings.weight"
    onnx.save_model(source, path)
    (tmp_path / "download.json").write_text(json.dumps({"snapshot": str(snapshot), "files": {
        "onnx/model.onnx": {"bytes": path.stat().st_size, "sha256": file_sha(path)}}}))
    quant.quantize(tmp_path, matrix_block=matrix_block, relative_int4=relative)
    output = tmp_path / "int4/model.onnx"
    onnx.checker.check_model(str(output))
    model = onnx.load(output)
    assert {"MatMulNBits", "GatherBlockQuantized", "If"} <= {n.op_type for n in model.graph.node}
    assert [v.name for v in model.graph.output] == ["logits"]
    linear = next(n for n in model.graph.node if n.op_type == "MatMulNBits")
    assert next(a.i for a in linear.attribute if a.name == "block_size") == matrix_block
    if relative:
        assert not any(t.name == "encoder.rel_embeddings.weight" for t in model.graph.initializer)


@pytest.mark.parametrize("block", [None, 32, 64, 128])
def test_relu_equalization_preserves_float_function_and_exact_q4_row(block):
    rng = np.random.default_rng(19)
    a = rng.normal(size=(8, 128)).astype(np.float32)
    b = rng.normal(size=128).astype(np.float32)
    w = np.resize(np.array([-3.1, 0, 1e-7, .123, 2.7], np.float32), 128).reshape(128, 1)
    source = h.make_model(h.make_graph([
        h.make_node("MatMul", ["x", "a"], ["z"], name="/scorer/mlp/mlp.2/MatMul"),
        h.make_node("Add", ["b", "z"], ["pre"], name="/scorer/mlp/mlp.2/Add"),
        h.make_node("Relu", ["pre"], ["hidden"]),
        h.make_node("MatMul", ["hidden", "w"], ["y"], name="/scorer/mlp/mlp.4/MatMul"),
    ], "readout", [], [], [nh.from_array(v, n) for n, v in (("a", a), ("b", b), ("w", w))]))
    target = copy.deepcopy(source)
    if block:
        for node in target.graph.node:
            if node.op_type != "MatMul":
                continue
            k, n = a.shape if node.input[1] == "a" else w.shape
            packed, scales = node.input[1] + "_q4", node.input[1] + "_scales"
            target.graph.initializer.extend([nh.from_array(np.zeros(1, np.uint8), packed), nh.from_array(np.zeros(1, np.float32), scales)])
            node.CopyFrom(h.make_node("MatMulNBits", [node.input[0], packed, scales], list(node.output), name=node.name,
                                     domain="com.microsoft", K=k, N=n, bits=4, block_size=block, accuracy_level=1))
    equalize_readout(target, source)
    values = {t.name: nh.to_array(t) for t in target.graph.initializer}
    if block:
        # Independent bit expansion, not the implementation's nibble unpacking.
        bits = np.unpackbits(values["w_q4"], bitorder="little").reshape(-1, 4)
        integers = bits @ np.array([1, 2, 4, 8])
        restored = ((integers.reshape(1, -1, block) - 8) * values["w_scales"].reshape(1, -1, 1)).reshape(-1)[:128]
        np.testing.assert_array_equal(restored, np.where(w.ravel() < 0, -8, np.where(w.ravel() > 0, 7, 0)))
    else:
        x = np.vstack([rng.normal(size=(5, 8)), np.zeros((1, 8))]).astype(np.float32)
        expected = np.maximum(x @ a + b, 0) @ w
        observed = np.maximum(x @ values["a"] + values["b"], 0) @ values["w"]
        np.testing.assert_allclose(observed, expected, atol=2e-5, rtol=2e-6)


@pytest.mark.parametrize("different", [False, True])
def test_shared_storage_preserves_scopes_and_deduplicates_only_equal_payloads(tmp_path, different):
    first, second = captured_graph(), captured_graph()
    if different:
        tensor = second.graph.initializer[0]
        tensor.CopyFrom(nh.from_array(nh.to_array(tensor) + 1, tensor.name))
    expected = [nh.to_array(m.graph.initializer[0]).copy() for m in (first, second)]
    save_shared_graphs([("model.onnx", first), ("progress.onnx", second)], tmp_path)
    for name, value in zip(("model.onnx", "progress.onnx"), expected):
        loaded = onnx.load(tmp_path / name)
        onnx.checker.check_model(loaded)
        np.testing.assert_array_equal(nh.to_array(loaded.graph.initializer[0]), value)
        assert [v.name for v in loaded.graph.input] == ["ids", "condition"]
        assert [v.name for v in loaded.graph.output] == ["logits"]
    assert (tmp_path / "weights.data").stat().st_size == 1024 * (2 if different else 1)
