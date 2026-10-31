import pytest
from suite.gliclass_probe import prepare_case, render_state
from suite.onejev_probe import sha
from cria import prompts


@pytest.mark.parametrize('state,expected', [
    ({'directive': 'Read f(x); do not lose \nanything.'}, 'directive: Read f(x); do not lose \nanything.'),
    ({'facts': ['α', 'β'], 'nested': {'value': 3}}, 'facts:\n- α\n- β\nnested: {"value": 3}'),
    (['a', {'b': 1}], '- a\n- {"b": 1}'), ('literal', 'literal'), (None, '')])
def test_native_state_renderer_preserves_full_values(state, expected):
    assert render_state(state) == expected


class FakePipe:
    def __init__(self, crop=False):
        self.crop = crop

    def prepare_input(self, text, labels, prompt=None):
        return '|'.join(labels) + prompt + text

    def tokenizer(self, text, truncation=False):
        assert truncation is False
        return {'input_ids': list(map(ord, text))}

    def prepare_inputs(self, texts, labels, same_labels, prompt):
        torch = pytest.importorskip('torch')
        ids = list(map(ord, self.prepare_input(texts[0], labels, prompt)))
        if self.crop:
            ids = ids[:-1]
        return {'input_ids': torch.tensor([ids])}


def test_native_pipeline_cannot_silently_clip_the_state():
    case = {'id': 'test', 'family': 'dictation', 'complete_input': {'directive': 'Complete final sentence.'}}
    hashes = {'dictation': sha((prompts.load('offline_onejev_dictation')+'\n').encode())}
    with pytest.raises(ValueError, match='truncated'):
        prepare_case(FakePipe(crop=True), case, hashes)
    inputs, receipt = prepare_case(FakePipe(), case, hashes, reverse=True)
    assert receipt['labels'] == ['DICTATES', 'DESCRIBES']
    assert receipt['rendered_input'].endswith('Complete final sentence.')
    assert receipt['tokens'] == inputs['input_ids'].shape[-1]


def test_oversized_native_input_is_rejected_without_a_shorter_substitute(monkeypatch):
    import suite.gliclass_probe as subject
    monkeypatch.setattr(subject, 'MAX_TOKENS', 1)
    case = {'id': 'test', 'family': 'dictation', 'complete_input': {'directive': 'whole'}}
    hashes = {'dictation': sha((prompts.load('offline_onejev_dictation')+'\n').encode())}
    with pytest.raises(ValueError, match='ceiling'):
        prepare_case(FakePipe(), case, hashes)
