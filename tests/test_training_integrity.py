import pytest

from suite.training_integrity import weighted_support


def test_weight_support_uses_production_weighting_not_label_balancing():
    rows = {'a': {'family': 'retrospective', 'label': 'RETROSPECTIVE'},
            'b': {'family': 'retrospective', 'label': 'PLAN'},
            'c': {'family': 'retrospective', 'label': 'PLAN'}}
    metadata = {'a': {'task': 'large', 'family': 'retrospective'},
                'b': {'task': 'large', 'family': 'retrospective'},
                'c': {'task': 'small', 'family': 'retrospective'}}
    result = weighted_support(list(rows), rows, metadata)
    by_key = {(r['task'], r['label']): r for r in result}
    assert by_key[('large', 'PLAN')]['loss_weight_mass'] == .75
    assert by_key[('small', 'PLAN')]['loss_weight_mass'] == 1.5
    assert sum(r['loss_weight_mass'] for r in result) == 3


def test_optimizer_membership_rejects_missing_and_duplicate_parameters():
    torch = pytest.importorskip('torch')
    from suite.training_integrity import optimizer_membership
    model = torch.nn.Linear(2, 2)
    optimizer = torch.optim.SGD(model.parameters(), lr=.1)
    assert len(optimizer_membership(model, optimizer)) == 2
    removed = optimizer.param_groups[0]['params'].pop()
    with pytest.raises(ValueError, match='exactly once'):
        optimizer_membership(model, optimizer)
    optimizer.param_groups[0]['params'].extend([removed, removed])
    with pytest.raises(ValueError, match='exactly once'):
        optimizer_membership(model, optimizer)


def test_parameter_change_probe_distinguishes_noop_from_real_update():
    torch = pytest.importorskip('torch')
    from suite.training_integrity import parameter_changes, gradient_summary
    model = torch.nn.Linear(2, 2)
    before = {name: p.detach().clone() for name, p in model.named_parameters()}
    assert parameter_changes(model, before)['encoder']['changed_tensors'] == 0
    model(torch.tensor([[1., 2.]])).sum().backward()
    assert gradient_summary(model)['encoder']['norm'] > 0
    torch.optim.SGD(model.parameters(), lr=.1).step()
    assert parameter_changes(model, before)['encoder']['changed_tensors'] == 2
