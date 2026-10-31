import json
import pytest

np = pytest.importorskip('numpy')
onnx = pytest.importorskip('onnx')
pytest.importorskip('onnxruntime')
from onnx import helper, numpy_helper, TensorProto
from suite.gliclass_quantize import quantize
from suite.onejev_probe import file_sha


def test_external_weight_tampering_is_rejected_before_quantization(tmp_path):
    snapshot = tmp_path / 'snapshot'
    folder = snapshot / 'onnx'
    folder.mkdir(parents=True)
    source = folder / 'model.onnx'
    graph = helper.make_graph([
        helper.make_node('MatMul', ['x', 'w'], ['y']),
        helper.make_node('Gather', ['e', 'ids'], ['z'])], 'external',
        [helper.make_tensor_value_info('x', TensorProto.FLOAT, [1, 128]),
         helper.make_tensor_value_info('ids', TensorProto.INT64, [1])],
        [helper.make_tensor_value_info('y', TensorProto.FLOAT, [1, 2]),
         helper.make_tensor_value_info('z', TensorProto.FLOAT, [1, 128])],
        [numpy_helper.from_array(np.ones((128, 2), dtype=np.float32), 'w'),
         numpy_helper.from_array(np.ones((4, 128), dtype=np.float32), 'e')])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 17)], ir_version=9)
    onnx.save_model(model, source, save_as_external_data=True, all_tensors_to_one_file=True,
                    location='weights.data', size_threshold=0)
    files = {str(p.relative_to(snapshot)): {'bytes': p.stat().st_size, 'sha256': file_sha(p)}
             for p in snapshot.rglob('*') if p.is_file()}
    (tmp_path / 'download.json').write_text(json.dumps({'snapshot': str(snapshot), 'files': files}))
    weights = folder / 'weights.data'
    weights.write_bytes(bytes(weights.stat().st_size))
    with pytest.raises(ValueError, match='frozen native artifact changed'):
        quantize(tmp_path)
    assert not (tmp_path / 'int4').exists()
