from types import SimpleNamespace
import pytest

onnx = pytest.importorskip('onnx')
ort = pytest.importorskip('onnxruntime')
torch = pytest.importorskip('torch')
np = pytest.importorskip('numpy')


def test_export_keeps_complete_dynamic_sequences_and_native_two_label_logits(tmp_path):
    from suite.gliclass_export import export_native_graph
    class Native(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.embedding = torch.nn.Embedding(8, 4)
        def forward(self, input_ids, attention_mask, max_num_classes):
            assert max_num_classes == 2
            hidden = self.embedding(input_ids) * attention_mask.unsqueeze(-1)
            return SimpleNamespace(logits=torch.stack((hidden.sum((1, 2)), hidden.square().sum((1, 2))), dim=-1))
    torch.manual_seed(17)
    model = Native().eval()
    inputs = {'input_ids': torch.tensor([[1, 2, 3]]), 'attention_mask': torch.ones((1, 3), dtype=torch.long)}
    path = tmp_path / 'native.onnx'
    export_native_graph(torch, model, inputs, path)
    engine = ort.InferenceSession(str(path), providers=['CPUExecutionProvider'])
    for ids, mask in [([[1, 2]], [[1, 1]]), ([[1, 2, 3, 4, 5, 6, 7]], [[1, 1, 1, 1, 1, 1, 0]])]:
        ids, mask = torch.tensor(ids), torch.tensor(mask)
        with torch.no_grad():
            expected = model(ids, mask, 2).logits.numpy()
        actual = engine.run(['logits'], {'input_ids': ids.numpy(), 'attention_mask': mask.numpy()})[0]
        np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-5)
