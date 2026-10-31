from types import SimpleNamespace
import pytest


def toy():
    torch = pytest.importorskip('torch')
    model = torch.nn.Module()
    model.model = torch.nn.Module()
    model.model.logit_scale = torch.nn.Parameter(torch.tensor(1.0))
    model.model.encoder = torch.nn.Linear(2, 2)
    model.calibrator = torch.nn.Linear(2, 2)
    model.config = SimpleNamespace(architecture_type='uni-encoder', normalize_features=False)
    return torch, model


def test_only_structurally_inactive_native_scale_is_frozen():
    from suite.gliclass_train import freeze_architecturally_inactive
    torch, model = toy()
    active_before = {name for name, p in model.named_parameters() if p.requires_grad}
    inactive = freeze_architecturally_inactive(model)
    assert set(inactive) == {'model.logit_scale'}
    assert {name for name, p in model.named_parameters() if p.requires_grad} == active_before - set(inactive)
    model.config.normalize_features = True
    with pytest.raises(ValueError, match='unqualified'):
        freeze_architecturally_inactive(model)


def test_reset_completion_is_recorded_only_after_successful_native_reload(monkeypatch, tmp_path):
    import suite.gliclass_train as subject
    def failed(*args):
        raise RuntimeError('native checkpoint could not reload')
    monkeypatch.setattr(subject, 'load_for_training', failed)
    with pytest.raises(RuntimeError, match='could not reload'):
        subject.reload_full_fit(None, 'snapshot', tmp_path)
    assert not (tmp_path / 'events.jsonl').exists()
    loaded = (object(), object(), object(), {'missing_keys': []}, {})
    monkeypatch.setattr(subject, 'load_for_training', lambda *args: loaded)
    assert subject.reload_full_fit(None, 'snapshot', tmp_path) is loaded
    import json
    event = json.loads((tmp_path / 'events.jsonl').read_text())
    assert event['full_fit_reset_to_pretrained'] is True
    assert event['loading'] == loaded[3]


def test_active_calibrator_is_part_of_exact_optimizer_membership():
    from suite.gliclass_train import freeze_architecturally_inactive, trainable_membership
    torch, model = toy()
    freeze_architecturally_inactive(model)
    active = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.SGD(active, lr=.1)
    trainable_membership(model, optimizer)
    optimizer.param_groups[0]['params'] = [p for p in active if p is not model.calibrator.bias]
    with pytest.raises(ValueError, match='not exact'):
        trainable_membership(model, optimizer)
