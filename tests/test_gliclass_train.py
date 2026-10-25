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
