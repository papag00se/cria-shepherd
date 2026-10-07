"""Ornith L0 incident: measured usage was replaced by chars/4; overflow lost its code."""
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from test_engagement_levels import _Harness
from test_server import _FakeUpstream


@pytest.fixture(autouse=True)
def restore_process_tool_policy(monkeypatch):
    from cria import massage
    monkeypatch.setattr(massage, '_TOOL_CALL_FIXES', massage._TOOL_CALL_FIXES)


@pytest.mark.parametrize('stream', [False, True])
def test_l0_responses_preserves_measured_usage_and_cached_input(monkeypatch, stream):
    usage = {'prompt_tokens': 48614, 'completion_tokens': 379, 'total_tokens': 48993,
             'prompt_tokens_details': {'cached_tokens': 48451}}
    def post(handler):
        handler.rfile.read(int(handler.headers['Content-Length']))
        handler._json(json.dumps({'choices': [{'message': {'role': 'assistant', 'content': '73'},
            'finish_reason': 'stop'}], 'usage': usage}).encode())
    monkeypatch.setattr(_FakeUpstream, 'do_POST', post)
    h = _Harness(0, False)
    try:
        body = {'model': 'm', 'input': [{'role': 'user', 'content': '73'}], 'stream': stream}
        req = urllib.request.Request(h.base + '/v1/responses', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
        if stream:
            events = [json.loads(line[6:]) for line in raw.decode().splitlines() if line.startswith('data: ')]
            result = next(e['response'] for e in events if e['type'] == 'response.completed')
        else:
            result = json.loads(raw)
        assert result['usage']['input_tokens'] == usage['prompt_tokens']
        assert result['usage']['total_tokens'] == usage['total_tokens']
        assert result['usage']['input_tokens_details']['cached_tokens'] == 48451
        assert 'usage.context_reported' not in h.kinds()
    finally:
        h.close()


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('overflow', [False, True])
def test_responses_retains_typed_error_and_captures_rejection(monkeypatch, stream, overflow):
    error = {'message': 'request exceeds context' if overflow else 'invalid request',
             'type': 'exceed_context_size_error' if overflow else 'invalid_request_error', 'code': 400}
    if overflow:
        error.update(n_prompt_tokens=49348, n_ctx=49152)
    raw_error = json.dumps({'error': error}).encode()
    posts = []
    def post(handler):
        posts.append(json.loads(handler.rfile.read(int(handler.headers['Content-Length']))))
        handler.send_response(400)
        handler.send_header('Content-Type', 'application/json')
        handler.send_header('Content-Length', str(len(raw_error)))
        handler.end_headers()
        handler.wfile.write(raw_error)
    monkeypatch.setattr(_FakeUpstream, 'do_POST', post)
    h = _Harness(0, False)
    h.cria.upstream._capture_dir = h.tmp.name
    h.cria.upstream._capture_rendered = False
    try:
        body = {'model': 'm', 'input': [{'role': 'user', 'content': 'keep the entire request'}], 'stream': stream}
        req = urllib.request.Request(h.base + '/v1/responses', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            assert not stream and exc.code == 400
            raw = exc.read()
        if stream:
            events = [json.loads(line[6:]) for line in raw.decode().splitlines() if line.startswith('data: ')]
            result = next(e['response']['error'] for e in events if e['type'] == 'response.failed')
        else:
            result = json.loads(raw)['error']
        assert result['message'] == error['message']
        assert result.get('code') == ('context_length_exceeded' if overflow else None)
        assert len(posts) == 1  # No L0 surgery or byte-identical rejected-body retry.
        assert posts[0]['messages'] == body['input']
        rejected = list(Path(h.tmp.name).rglob('*.response.json'))
        assert len(rejected) == 1
        assert json.loads(rejected[0].read_text()) == {'error': error}
    finally:
        h.close()
