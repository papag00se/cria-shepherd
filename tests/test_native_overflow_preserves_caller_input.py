"""Final-wire native sizing must measure preserved caller input, not its deletion."""
from copy import deepcopy
import io
import json

import pytest

from cria import bodykeys, selfcompact
from cria.upstream import Upstream, UpstreamError


class Log:
    def emit(self, *args, **kwargs):
        pass


def request():
    return {'model': 'native-fit-regression', bodykeys.PINNED_TASK: 'Perform the original task.',
            bodykeys.OUTPUT_RESERVE: 64, 'messages': [
                {'role': 'user', 'content': 'Keep this preceding constraint. '+('documentation '*1600)+' FINAL_CONSTRAINT_BYTE'},
                {'role': 'user', 'content': 'Perform the original task.'},
                {'role': 'assistant', 'content': '⟦ctx:briefing⟧ Original evidence\r\nwith its role and β bytes intact.'},
                {'role': 'user', 'content': 'A later amendment: preserve preceding instructions.'}]}


def transport(monkeypatch, *, rendered=True, tokens=2000, cached=None):
    up = Upstream('http://inprocess.invalid', context_window=4096,
                  capture_dir=None, capture_rendered=False)
    up._props = cached
    up._props_seen = cached is not None
    operations, posts = [], []

    def metadata(packet, **kwargs):
        data = json.loads(packet.data)
        if packet.full_url.endswith('/apply-template'):
            operations.append(('render', deepcopy(data)))
            return io.BytesIO(json.dumps({'prompt': json.dumps(data, ensure_ascii=False) if rendered else None}).encode())
        assert packet.full_url.endswith('/tokenize')
        operations.append(('count', deepcopy(data)))
        value = {'tokens': [42]*tokens} if type(tokens) is int else tokens
        return io.BytesIO(json.dumps(value).encode())

    def generation(packet, **kwargs):
        posts.append(json.loads(packet.data))
        return io.BytesIO(b'{"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"An unexecuted test reply."}}]}')

    monkeypatch.setattr(up, '_ordinary_open', metadata)
    monkeypatch.setattr(up, '_receive_open', generation)
    return up, operations, posts


@pytest.mark.parametrize('cached', [None, {}, {'chat_template': 'known'}])
def test_exact_native_fit_keeps_preceding_constraints_and_later_amendment(monkeypatch, cached):
    up, operations, posts = transport(monkeypatch, cached=cached)
    body = request()
    original = deepcopy(body)
    up.chat(body, Log())
    assert len(posts) == 1
    assert all(message in posts[0]['messages'] for message in original['messages'])
    assert [op for op, _ in operations] == ['render', 'count']
    rendered = operations[0][1]
    assert rendered['messages'] == posts[0]['messages']
    assert operations[1][1] == {'content': json.dumps(rendered, ensure_ascii=False), 'add_special': False}
    assert body == original and up._window == 4096
    assert bodykeys.PINNED_TASK not in posts[0]


@pytest.mark.parametrize('rendered,tokens', [(False, 2000), (True, {'tokens': []}),
    (True, {'tokens': [True]}), (True, {'tokens': [-1]}), (True, {'tokens': ['42']})])
def test_missing_or_invalid_measurement_cannot_authorize_deleting_caller_input(monkeypatch, rendered, tokens):
    up, operations, posts = transport(monkeypatch, rendered=rendered, tokens=tokens)
    body = request()
    original = deepcopy(body)
    with pytest.raises(UpstreamError, match='without losing protected input'):
        up.chat(body, Log())
    assert posts == [] and body == original


def test_true_native_overflow_refuses_without_generation_or_losing_input(monkeypatch):
    up, operations, posts = transport(monkeypatch, tokens=5000)
    body = request()
    original = deepcopy(body)
    with pytest.raises(UpstreamError, match='without losing protected input'):
        up.chat(body, Log())
    assert not posts and body == original and up._window == 4096
    assert 1 <= sum(kind == 'count' for kind, _ in operations) <= 2


def test_typed_history_can_reduce_without_reclassifying_it_as_caller_input(monkeypatch):
    up, operations, posts = transport(monkeypatch, rendered=False)
    body = {'model': 'typed-evidence', bodykeys.PINNED_TASK: 'Original task',
            bodykeys.OUTPUT_RESERVE: 64, 'messages': [
                {'role': 'user', 'content': 'Original constraint'},
                {'role': 'user', 'content': 'Original task'},
                selfcompact.internal_evidence_message('Old observation '*4000),
                {'role': 'user', 'content': 'Current amendment'}]}
    up.chat(body, Log())
    assert len(posts) == 1
    assert all(m in posts[0]['messages'] for m in body['messages'] if m.get('role') == 'user' and bodykeys.ANNOTATION_SOURCE not in m)
    assert body['messages'][2]['content'] not in json.dumps(posts[0])
    assert '⟦ctx:compacted⟧' in json.dumps(posts[0], ensure_ascii=False)
