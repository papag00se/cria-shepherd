import pytest
np = pytest.importorskip('numpy')
onnx = pytest.importorskip('onnx')
ort = pytest.importorskip('onnxruntime')
from onnx import TensorProto, helper, numpy_helper
from suite.gliclass_quantize import normalize_linear_layers


def test_int4_opset_upgrade_converts_reduce_axes_not_just_the_header():
    from onnxruntime.quantization.matmul_nbits_quantizer import DefaultWeightOnlyQuantConfig, MatMulNBitsQuantizer
    model = helper.make_model(helper.make_graph([
        helper.make_node('MatMul', ['x', 'w'], ['z']),
        helper.make_node('ReduceMax', ['z'], ['y'], axes=[1], keepdims=1)], 'opset17',
        [helper.make_tensor_value_info('x', TensorProto.FLOAT, [None, 4])],
        [helper.make_tensor_value_info('y', TensorProto.FLOAT, [None, 1])],
        [numpy_helper.from_array(np.eye(4, dtype=np.float32), 'w')]),
        opset_imports=[helper.make_opsetid('', 17)], ir_version=9)
    normalized = normalize_linear_layers(model)
    quantizer = MatMulNBitsQuantizer(normalized, algo_config=DefaultWeightOnlyQuantConfig(
        block_size=32, is_symmetric=True, accuracy_level=1, bits=4))
    quantizer.process()
    x = np.array([[1, -2, 3, 4], [8, 1, -3, 0]], dtype=np.float32)
    engine = ort.InferenceSession(quantizer.model.model.SerializeToString(), providers=['CPUExecutionProvider'])
    y = engine.run(None, {'x': x})[0]
    np.testing.assert_allclose(y, np.max(x, axis=1, keepdims=True), rtol=1e-6, atol=1e-6)
