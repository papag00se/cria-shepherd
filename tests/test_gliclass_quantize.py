"""Numerical graph semantics and complete static-weight lowering."""
import pytest

np = pytest.importorskip('numpy')
onnx = pytest.importorskip('onnx')
ort = pytest.importorskip('onnxruntime')
from onnx import TensorProto, helper, numpy_helper
from suite.gliclass_quantize import normalize_linear_layers


def test_transposed_gemm_and_bias_survive_native_normalization():
    weights = np.arange(12, dtype=np.float32).reshape(4, 3) / 9
    bias = np.array([1, -2, 3, -4], dtype=np.float32)
    model = helper.make_model(helper.make_graph(
        [helper.make_node('Gemm', ['x', 'w', 'b'], ['y'], transB=1)], 'test',
        [helper.make_tensor_value_info('x', TensorProto.FLOAT, [None, 3])],
        [helper.make_tensor_value_info('y', TensorProto.FLOAT, [None, 4])],
        [numpy_helper.from_array(weights, 'w'), numpy_helper.from_array(bias, 'b')]),
        opset_imports=[helper.make_opsetid('', 17)], ir_version=9)
    x = np.array([[1, 2, -1], [-4, 1, 0]], dtype=np.float32)
    normalized = normalize_linear_layers(model)
    actual = ort.InferenceSession(normalized.SerializeToString(), providers=['CPUExecutionProvider']).run(None, {'x': x})[0]
    np.testing.assert_allclose(actual, x @ weights.T + bias, rtol=1e-6, atol=1e-6)
    assert not any(n.op_type == 'Gemm' for n in normalized.graph.node)


def test_shared_weight_alias_cannot_leave_a_full_precision_projection():
    from onnxruntime.quantization.matmul_nbits_quantizer import DefaultWeightOnlyQuantConfig, MatMulNBitsQuantizer
    weights = np.eye(4, dtype=np.float32)
    model = helper.make_model(helper.make_graph([
        helper.make_node('MatMul', ['x', 'w'], ['a']),
        helper.make_node('Identity', ['w'], ['alias']),
        helper.make_node('MatMul', ['x', 'alias'], ['b']),
        helper.make_node('Add', ['a', 'b'], ['y'])], 'shared',
        [helper.make_tensor_value_info('x', TensorProto.FLOAT, [None, 4])],
        [helper.make_tensor_value_info('y', TensorProto.FLOAT, [None, 4])],
        [numpy_helper.from_array(weights, 'w')]),
        opset_imports=[helper.make_opsetid('', 17)], ir_version=9)
    model = normalize_linear_layers(model)
    quantizer = MatMulNBitsQuantizer(model, algo_config=DefaultWeightOnlyQuantConfig(
        block_size=32, is_symmetric=True, accuracy_level=1, bits=4))
    quantizer.process()
    result = quantizer.model.model
    assert sum(n.op_type == 'MatMulNBits' for n in result.graph.node) == 2
    x = np.array([[1, -2, 3, 4]], dtype=np.float32)
    y = ort.InferenceSession(result.SerializeToString(), providers=['CPUExecutionProvider']).run(None, {'x': x})[0]
    np.testing.assert_allclose(y, 2*x, rtol=1e-6, atol=1e-6)
