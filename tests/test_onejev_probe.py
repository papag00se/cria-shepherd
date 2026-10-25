import pytest

from suite.onejev_probe import checked_probabilities, checked_decision, native_server_ready, frozen_policy
from suite.training_prepare import sha


def test_scoring_uses_native_choice_not_recounted_rounded_probabilities():
    # qev chooses from unrounded probabilities, then publishes six decimals.
    answer = {'choice': 'PLAN', 'probabilities': {'RETROSPECTIVE': .5, 'PLAN': .5}}
    prediction, probabilities = checked_decision(answer, 'retrospective')
    assert prediction == 'PLAN'
    assert probabilities == answer['probabilities']


@pytest.mark.parametrize('choice', ['UNKNOWN', 'RETROSPECTIVE'])
def test_inconsistent_native_choice_is_not_scored(choice):
    with pytest.raises(ValueError, match='native choice conflicts'):
        checked_decision({'choice': choice, 'probabilities': {'RETROSPECTIVE': .2, 'PLAN': .8}}, 'retrospective')


def test_canonical_prompt_loader_preserves_frozen_transport_and_rejects_drift(monkeypatch):
    from cria import prompts
    monkeypatch.setattr(prompts, 'load', lambda name: 'frozen question')
    assert frozen_policy('retrospective', sha(b'frozen question\n')) == 'frozen question\n'
    with pytest.raises(ValueError, match='frozen policy'):
        frozen_policy('retrospective', sha(b'different question\n'))


def test_ready_event_matches_current_native_listener_and_only_our_port():
    line = '0.01.000 I srv llama_server: listening on http://127.0.0.1:19123\n'
    assert native_server_ready(line, 19123)
    assert not native_server_ready(line, 19124)
    assert not native_server_ready('load_model: failed to load model', 19123)


def test_native_probabilities_keep_source_class_names_and_values():
    answer = {'probabilities': {'PLAN': .8, 'RETROSPECTIVE': .2}}
    result = checked_probabilities(answer, 'retrospective')
    assert list(result) == ['RETROSPECTIVE', 'PLAN']
    assert result == {'RETROSPECTIVE': .2, 'PLAN': .8}


@pytest.mark.parametrize('probabilities', [
    {'RETROSPECTIVE': .5, 'PLAN': float('nan')},
    {'RETROSPECTIVE': .5, 'PLAN': .7},
    {'RETROSPECTIVE': -.1, 'PLAN': 1.1},
    {'DESCRIBES': .5, 'DICTATES': .5},
])
def test_invalid_or_wrong_head_probabilities_are_not_scored(probabilities):
    with pytest.raises(ValueError):
        checked_probabilities({'probabilities': probabilities}, 'retrospective')
