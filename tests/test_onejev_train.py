import math

import pytest

from suite.onejev_train import balanced_weights, lr_at


def case(id, label):
    return {'id': id, 'task': 'one', 'family': 'retrospective', 'label': label,
            'label_id': ['RETROSPECTIVE', 'PLAN'].index(label)}


def test_balancing_gives_each_observed_task_head_label_equal_mass():
    rows = [case('r', 'RETROSPECTIVE'), *[case(str(i), 'PLAN') for i in range(3)]]
    weights = balanced_weights(rows)
    assert math.isclose(weights['r'], 2)
    assert math.isclose(sum(weights[str(i)] for i in range(3)), 2)
    with pytest.raises(ValueError, match='duplicate'):
        balanced_weights([rows[0], rows[0]])
    rows[0]['label_id'] = 1
    with pytest.raises(ValueError, match='label order'):
        balanced_weights(rows)


def test_schedule_has_declared_warmup_without_hidden_update_or_negative_lr():
    assert lr_at(0, 100, 5e-6) == 0
    assert lr_at(5, 100, 5e-6) == 5e-6
    assert lr_at(100, 100, 5e-6) == 0
    assert all(0 <= lr_at(i, 100, 5e-6) <= 5e-6 for i in range(101))


def test_native_slot_loss_gradient_matches_independent_ce_plus_brier_derivative():
    torch = pytest.importorskip('torch')
    from suite.onejev_train import loss_at_slots
    logits = torch.tensor([.1, -.2], requires_grad=True)
    loss = loss_at_slots(torch, logits, 1, 3.5)
    loss.backward()
    p = torch.softmax(logits.detach(), -1)
    error = p - torch.tensor([0., 1.])
    expected = 3.5 * (error + 2 * p * (error - (p * error).sum()))
    assert torch.allclose(logits.grad, expected, atol=1e-6)


@pytest.mark.parametrize('count', [1, 3, 16])
def test_actual_step_matches_full_weighted_mean_for_short_and_full_batches(monkeypatch, count):
    torch = pytest.importorskip('torch')
    import suite.onejev_train as training
    actual = torch.nn.Linear(2, 2, bias=False)
    reference = torch.nn.Linear(2, 2, bias=False)
    reference.load_state_dict(actual.state_dict())
    rows = [{'id': str(i), 'tokens': [1., float(i % 2)], 'target': i % 2} for i in range(count)]
    weights = {str(i): 1 + i / 10 for i in range(count)}
    monkeypatch.setattr(training, 'slot_logits', lambda t, m, tokens, slots: m(t.tensor(tokens)))
    optimizer = torch.optim.SGD(actual.parameters(), lr=.01)
    training.training_step(torch, actual, optimizer, rows, weights, None, .03)
    optimizer_ref = torch.optim.SGD(reference.parameters(), lr=.03)
    loss = sum(training.loss_at_slots(torch, reference(torch.tensor(r['tokens'])), r['target'], weights[r['id']]) for r in rows) / count
    loss.backward()
    torch.nn.utils.clip_grad_norm_(reference.parameters(), 1, error_if_nonfinite=True)
    optimizer_ref.step()
    assert torch.allclose(actual.weight, reference.weight, atol=1e-7)


def test_native_loading_facts_are_json_safe_even_when_transformers_returns_sets(monkeypatch):
    import json
    import sys
    from types import SimpleNamespace
    from suite.onejev_train import load_model
    class Model:
        config = SimpleNamespace(use_cache=True)
        def parameters(self):
            return [SimpleNamespace(dtype='f32', requires_grad=True)]
        def gradient_checkpointing_enable(self, **kwargs):
            pass
        def to(self, device):
            return self
        def train(self):
            return self
    fake = SimpleNamespace(AutoConfig=SimpleNamespace(from_pretrained=lambda *a, **k: SimpleNamespace(get_text_config=lambda: 'text')),
        Qwen3_5ForCausalLM=SimpleNamespace(from_pretrained=lambda *a, **k: (Model(),
            {'missing_keys': set(), 'unexpected_keys': set(), 'mismatched_keys': set(), 'error_msgs': []})))
    monkeypatch.setitem(sys.modules, 'transformers', fake)
    _, info = load_model(SimpleNamespace(manual_seed=lambda seed: None, float32='f32'), 'snapshot')
    assert json.loads(json.dumps(info))['missing_keys'] == []


def test_native_order_permutation_moves_target_and_keeps_whole_state():
    pytest.importorskip('qev')
    from suite.onejev_train import render_case
    from suite.training_prepare import sha
    from cria import prompts
    row = {**case('r', 'RETROSPECTIVE'), 'complete_input': {'candidate_briefing': 'entire\noriginal input'}}
    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs):
            return 'rendered'
        def encode(self, text, **kwargs):
            return [1, 2]
    hashes = {'retrospective': sha((prompts.load('offline_onejev_retrospective') + '\n').encode())}
    forward = render_case(Tokenizer(), row, hashes)
    reverse = render_case(Tokenizer(), row, hashes, True)
    assert forward['target'] == 0 and reverse['target'] == 1
    assert reverse['labels'] == ['PLAN', 'RETROSPECTIVE']
    assert reverse['request']['state'] == row['complete_input']
