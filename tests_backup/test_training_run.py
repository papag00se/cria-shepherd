import math

import pytest

from suite.training_run import fit_specs, loss_weights, accumulated_batches, learning_rate_factor, validate_authorization


def test_every_seed_and_arm_excludes_the_same_whole_task_across_both_heads():
    folds = {'folds': [{'calibration_task': 'held-' + id,
                        'real_training_ids': sorted(set('abc') - {id}),
                        'real_calibration_ids': [id], 'mixed_arm_synthetic_training_ids': ['s']}
                       for id in 'abc']}
    jobs = fit_specs([17, 29, 43], folds, ['a', 'b', 'c'], ['s'])
    assert len(jobs) == 24
    for job in jobs:
        if job['calibration_task']:
            assert set(job['train_ids']).isdisjoint(job['predict_ids'])
            assert job['predict_ids'] == [job['calibration_task'].removeprefix('held-')]
        assert ('s' in job['train_ids']) == (job['arm'] == 'real_plus_11_reviewed_standalone_synthetic')


def test_no_training_id_can_appear_in_its_own_calibration_fold():
    folds = {'folds': [{'calibration_task': 'held', 'real_training_ids': ['a'],
                        'real_calibration_ids': ['a'], 'mixed_arm_synthetic_training_ids': []}]}
    with pytest.raises(ValueError, match='fold'):
        fit_specs([17], folds, ['a'], [])


def test_task_family_weights_do_not_turn_tiny_synthetic_groups_into_real_tasks():
    rows = {'a': {'task': 'large', 'family': 'retrospective'},
            'b': {'task': 'large', 'family': 'retrospective'},
            'c': {'task': 'small', 'family': 'dictation'}}
    weights = loss_weights(['a', 'b', 'c', 's'], rows)
    assert weights == {'a': 0.75, 'b': 0.75, 'c': 1.5, 's': 1.0}
    assert sum(weights[k] for k in rows) == len(rows)


def test_last_accumulation_uses_actual_examples_without_dropping_or_repeating():
    batches = accumulated_batches(list(range(34)), 16)
    assert list(map(len, batches)) == [16, 16, 2]
    assert [item for batch in batches for item in batch] == list(range(34))
    assert sum(1 / len(batches[-1]) for _ in batches[-1]) == 1


def test_schedule_is_optimizer_step_based_and_reaches_zero():
    total = 5 * math.ceil(514 / 16)
    assert total == 165
    assert learning_rate_factor(0, total) == 0
    assert learning_rate_factor(17, total) == 1
    assert learning_rate_factor(total, total) == 0


def test_native_pooling_gradients_and_optimizer_ownership():
    torch = pytest.importorskip('torch')
    from types import SimpleNamespace
    from suite.training_run import make_model, optimizer_groups

    class Encoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.config = SimpleNamespace(hidden_size=2)
            self.embedding = torch.nn.Embedding.from_pretrained(torch.tensor([[100., 100.], [1., 0.], [0., 1.]]), freeze=False)
            self.norm = torch.nn.LayerNorm(2)

        def forward(self, input_ids, attention_mask):
            return SimpleNamespace(last_hidden_state=self.embedding(input_ids))

    model = make_model(torch, Encoder())
    with torch.no_grad():
        model.heads['retrospective'].weight.copy_(torch.eye(2))
        model.heads['retrospective'].bias.zero_()
    logits = model(torch.tensor([[1, 2, 0]]), torch.tensor([[1, 1, 0]]), 'retrospective')
    assert torch.allclose(logits, torch.tensor([[.5, .5]]))
    torch.nn.functional.cross_entropy(logits, torch.tensor([1])).backward()
    assert model.heads['retrospective'].weight.grad.abs().sum() > 0
    assert model.heads['dictation'].weight.grad is None
    assert model.encoder.embedding.weight.grad[0].abs().sum() == 0
    groups = optimizer_groups(torch, model, {'heads_lr': .1, 'encoder_lr': .01, 'weight_decay': .02})
    by_identity = {id(parameter): group for group in groups for parameter in group['params']}
    assert by_identity[id(model.encoder.norm.weight)]['weight_decay'] == 0
    assert by_identity[id(model.encoder.norm.bias)]['weight_decay'] == 0
    assert by_identity[id(model.heads['retrospective'].bias)]['weight_decay'] == 0
    assert by_identity[id(model.heads['retrospective'].weight)]['lr'] == .1
    assert by_identity[id(model.encoder.embedding.weight)]['lr'] == .01


@pytest.mark.parametrize('size', [1, 3])
def test_training_step_matches_full_batch_weighted_loss_and_updates(size):
    torch = pytest.importorskip('torch')
    import copy
    from types import SimpleNamespace
    from suite.training_run import make_model, training_step

    class Encoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.config = SimpleNamespace(hidden_size=2)
            self.embedding = torch.nn.Embedding(5, 2)

        def forward(self, input_ids, attention_mask):
            return SimpleNamespace(last_hidden_state=self.embedding(input_ids))

    torch.manual_seed(17)
    actual = make_model(torch, Encoder())
    expected = copy.deepcopy(actual)
    ids = list(range(size))
    rows = {i: {'family': 'dictation' if i % 2 else 'retrospective', 'label_id': i % 2} for i in ids}
    encoded = {i: [i, i + 1] for i in ids}
    weights = {i: 1 + .25 * i for i in ids}
    optimizer = torch.optim.SGD(actual.parameters(), lr=.1)
    reference_optimizer = torch.optim.SGD(expected.parameters(), lr=.1)
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda step: 1)
    losses = []
    for i in ids:
        x = torch.tensor([encoded[i]])
        logits = expected(x, torch.ones_like(x), rows[i]['family'])
        losses.append(torch.nn.functional.cross_entropy(logits, torch.tensor([rows[i]['label_id']])) * weights[i])
    loss = torch.stack(losses).mean()
    loss.backward()
    reference_optimizer.step()
    result = training_step(torch, actual, optimizer, scheduler, ids, rows, encoded, weights, 1e9, device='cpu')
    assert result['weighted_mean_loss'] == pytest.approx(float(loss.detach()))
    assert result['learning_rates_used'] == [.1]
    for name, parameter in actual.named_parameters():
        assert torch.allclose(parameter, dict(expected.named_parameters())[name], atol=1e-7)


def test_export_preserves_full_precision_reference_and_integer_buffers():
    torch = pytest.importorskip('torch')
    from suite.training_run import export_states
    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = torch.nn.Linear(2, 2)
            self.heads = torch.nn.Linear(2, 2)
            self.encoder.register_buffer('positions', torch.tensor([0, 1], dtype=torch.int64))
    model = Model()
    reference, serving = export_states(torch, model)
    assert reference['encoder.weight'].dtype == torch.float32
    assert serving['encoder.weight'].dtype == torch.float16
    assert serving['heads.weight'].dtype == torch.float32
    assert serving['encoder.positions'].dtype == torch.int64
    assert torch.equal(reference['encoder.weight'], model.encoder.weight)
    assert model.encoder.weight.dtype == torch.float32


def test_rng_receipts_observe_without_consuming_the_sampler_or_torch_rng():
    torch = pytest.importorskip('torch')
    import random
    from suite.training_run import rng_receipt
    sampler = random.Random(17)
    cpu, sampling = torch.get_rng_state().clone(), sampler.getstate()
    receipt = rng_receipt(torch, sampler)
    assert receipt['torch_cpu'] == cpu.tolist()
    assert receipt['sampler'] == sampling
    assert sampler.getstate() == sampling
    assert torch.equal(torch.get_rng_state(), cpu)


def test_native_loader_sets_are_preserved_as_structured_receipts():
    from suite.training_run import loading_receipt
    native = {'missing_keys': set(), 'unexpected_keys': {'decoder.weight', 'head.norm.weight'},
              'mismatched_keys': [], 'error_msgs': []}
    result = loading_receipt(native)
    assert result == {'missing_keys': [], 'unexpected_keys': ['decoder.weight', 'head.norm.weight'],
                      'mismatched_keys': [], 'error_msgs': []}
    assert isinstance(native['missing_keys'], set)


def test_active_question_changes_require_new_label_policy_review(tmp_path):
    from suite.training_run import verify_question_policies
    from suite.training_prepare import sha
    path = tmp_path / 'question.txt'
    path.write_text('frozen question')
    policies = {'question.txt': sha(path.read_bytes())}
    verify_question_policies(tmp_path, policies)
    path.write_text('different question')
    with pytest.raises(ValueError, match='question policy'):
        verify_question_policies(tmp_path, policies)


def test_recipe_loader_binds_actual_public_policy_schema(tmp_path):
    import json
    from pathlib import Path
    from suite.training_run import load_recipe
    recipe_path = Path(__file__).resolve().parents[1] / 'docs/training/training-recipe.json'
    recipe = load_recipe(recipe_path)
    changed = json.loads(recipe_path.read_text())
    first = next(iter(changed['question_policy_sha256']))
    changed['question_policy_sha256'][first] = '0' * 64
    new_path = tmp_path / 'recipe.json'
    new_path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match='question policy'):
        load_recipe(new_path)
    assert recipe['question_policy_sha256'][first] != '0' * 64


def test_gpu_authority_must_be_explicit_and_bound_to_recipe_and_device():
    auth = {'training_authorized': True, 'gpu_uuid': 'gpu', 'recipe_sha256': 'recipe'}
    validate_authorization(auth, 'recipe', 'gpu')
    for field, value in [('training_authorized', False), ('gpu_uuid', 'other'), ('recipe_sha256', 'changed')]:
        bad = {**auth, field: value}
        with pytest.raises(ValueError, match='authorization'):
            validate_authorization(bad, 'recipe', 'gpu')
