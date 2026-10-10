"""The final prompt, not a learned average, settles dense briefing fit."""
import json
from unittest.mock import patch
from io import BytesIO

import pytest

from cria.upstream import Upstream, UpstreamError


class Log:
    def emit(self, *args, **kwargs):
        return self


def dense_body():
    return {'model': 'small', 'messages': [
        {'role': 'system', 'content': 'Write a factual briefing, not a plan.'},
        {'role': 'user', 'content': 'Earlier transcript follows.'},
        *[{'role': 'user', 'content': 'tool: ' + ('00001: 4326.28\n' * 500)}
          for _ in range(6)],
        {'role': 'user', 'content': 'A check exited 1: blank quantity.'},
        {'role': 'user', 'content': 'Write the briefing now.'}]}


def render(body):
    return json.dumps(body['messages'])


def count(text, log):
    # Numeric outputs are much denser than the surrounding prose. A fake server
    # answers this exact prompt, independently of the floor's chars/4 estimator.
    return 100 + text.count('4326.28') * 8


def test_dense_briefing_is_measured_and_refitted_before_wire_capture():
    upstream = Upstream('http://unused', context_window=16000)
    upstream._props = {'chat_template': 'server-provided template'}
    body = dense_body()
    original = json.dumps(body)
    with patch.object(upstream, '_render_prompt', side_effect=render), \
         patch.object(upstream, '_tokenize_prompt', side_effect=count, create=True):
        data, _, _ = upstream._prep(body, False, Log(), safety_override=1)
    wire = json.loads(data)
    assert count(render(body), Log()) > 16000
    assert count(render(wire), Log()) <= 16000
    assert wire['messages'][-1]['content'] == 'Write the briefing now.'
    assert 'blank quantity' in render(wire)
    assert 'ctx:compacted' in render(wire)
    assert 'max_tokens' not in wire
    assert json.dumps(body) == original


def test_irreducible_prompt_is_not_sent_or_captured_as_a_model_call():
    upstream = Upstream('http://unused', context_window=8000)
    upstream._props = {'chat_template': 'server-provided template'}
    body = {'model': 'small', 'messages': [{'role': 'user', 'content': 'Essential request'}]}
    with patch.object(upstream, '_render_prompt', return_value='Essential request'), \
         patch.object(upstream, '_tokenize_prompt', return_value=9000, create=True), \
         patch('cria.upstream.callcapture.capture') as capture:
        with pytest.raises(UpstreamError, match='context'):
            upstream._prep(body, False, Log())
    capture.assert_not_called()


def test_l0_remains_byte_identical_without_tokenizer_probes():
    upstream = Upstream('http://unused', context_window=8000, engagement_level=0)
    upstream._props = {'chat_template': 'server-provided template'}
    body = dense_body()
    with patch.object(upstream, '_tokenize_prompt', create=True) as counter:
        data, _, _ = upstream._prep(body, False, Log())
    assert json.loads(data) == {**body, 'stream': False}
    counter.assert_not_called()


def test_real_measurement_transport_prevents_an_oversized_completion_post():
    upstream = Upstream('http://unused', context_window=16000)
    upstream._props = {'chat_template': 'server-provided template'}
    upstream._props_seen = True
    posts = []

    def server(request, **kwargs):
        payload = json.loads(request.data)
        if request.full_url.endswith('/apply-template'):
            return BytesIO(json.dumps({'prompt': render(payload)}).encode())
        if request.full_url.endswith('/tokenize'):
            assert payload['add_special'] is False
            return BytesIO(json.dumps({'tokens': [1] * count(payload['content'], Log())}).encode())
        assert request.full_url.endswith('/v1/chat/completions')
        assert count(render(payload), Log()) <= 16000
        posts.append(payload)
        return BytesIO(b'{}')

    with patch('cria.upstream.urllib.request.urlopen', side_effect=server):
        response, _, _ = upstream._open_with_refit(dense_body(), False, Log())
        response.close()
    assert len(posts) == 1
    assert 'max_tokens' not in posts[0]


def test_malformed_tokenizer_reply_is_unknown_not_a_fake_zero_count():
    upstream = Upstream('http://unused', context_window=16000)
    with patch('cria.upstream.urllib.request.urlopen', return_value=BytesIO(b'{"tokens": null}')):
        assert upstream._tokenize_prompt('Request', Log()) is None
