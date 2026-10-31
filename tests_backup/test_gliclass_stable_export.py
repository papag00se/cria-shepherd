from types import SimpleNamespace
import pytest
np = pytest.importorskip('numpy')
onnx = pytest.importorskip('onnx')
ort = pytest.importorskip('onnxruntime')
torch = pytest.importorskip('torch')


def test_native_calibration_entropy_remains_finite_at_saturated_logits(tmp_path):
    from suite.gliclass_export import export_native_graph
    class NativeEntropy(torch.nn.Module):
        def forward(self, input_ids, attention_mask, max_num_classes):
            logits = (input_ids.float()/1000) * attention_mask
            p = torch.sigmoid(logits)
            entropy = -(p*torch.nn.functional.logsigmoid(logits)
                        + (1-p)*torch.nn.functional.logsigmoid(-logits))
            return SimpleNamespace(logits=entropy)
    model = NativeEntropy().eval()
    inputs = {'input_ids': torch.tensor([[2000, -2000]]), 'attention_mask': torch.ones((1, 2), dtype=torch.long)}
    path = tmp_path / 'calibration.onnx'
    export_native_graph(torch, model, inputs, path)
    engine = ort.InferenceSession(str(path), providers=['CPUExecutionProvider'])
    cases = [[1000*size, -1000*size] for size in [0, 1, 2, 8, 15, 17, 20, 100, 1000]]
    cases += [[17261, -15532]]  # actual failing trained calibration range
    for values in cases:
        ids = torch.tensor([values])
        expected = model(ids, inputs['attention_mask'], 2).logits.numpy()
        actual = engine.run(None, {'input_ids': ids.numpy(), 'attention_mask': inputs['attention_mask'].numpy()})[0]
        assert np.isfinite(actual).all()
        # The existing whole-model export gate allows 2e-4: ORT's FP32
        # Sigmoid approximation differs near saturation. This is not a new
        # quality threshold; finite/non-saturated values reject zero filling.
        np.testing.assert_allclose(actual, expected, rtol=2e-4, atol=2e-4)
