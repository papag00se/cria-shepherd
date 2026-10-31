"""Actual final POST/capture boundary with selected historical argument policies."""
import copy
from dataclasses import replace
import io
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest

from cria import assistruntime, bodykeys, callcapture, historyarguments as history, upstream
from test_assist_capture_metadata import Log


RAW = 'wrapper {"cmd":"echo literal"} trailing prose'
VALID = '{"literal":"<think>private</think>"}'


def messages():
    return [{'role': 'user', 'content': 'Continue'},
        {'role': 'assistant', 'content': None, bodykeys.CALLER_INSTRUCTIONS: 'private hint',
         'tool_calls': [{'id': 'old', 'type': 'function', 'function': {
             'name': 'native_opaque_name', 'arguments': RAW}},
            {'id': 'valid', 'type': 'function', 'function': {
             'name': 'another', 'arguments': VALID}}]},
        {'role': 'tool', 'tool_call_id': 'old', 'content': 'exact previous result'},
        {'role': 'tool', 'tool_call_id': 'valid', 'content': 'other result'}]


def selected(mode, calls):
    runtime = assistruntime.AssistRuntime.select(level=0 if mode == 'proxy' else 5,
        disabled=(history.DEFINITION.policy.id,) if mode == 'disabled' else ())
    if mode == 'replaced':
        def execute(source):
            calls.append(source.values)
            return history.RecoveredArguments(tuple({'chosen': raw} for raw in source.values))
        definition = replace(history.DEFINITION, execute=execute)
        runtime = replace(runtime, ordered_stages=tuple(
            definition if d.policy.id == definition.policy.id else d for d in runtime.ordered_stages))
    return runtime


@pytest.mark.parametrize('phase', ['coder-s1', 'proxy', 'satisfaction'])
@pytest.mark.parametrize('mode', ['enabled', 'disabled', 'proxy', 'replaced'])
def test_selected_history_at_actual_post_and_capture(tmp_path, monkeypatch, phase, mode):
    calls, posts, captures = [], [], []
    runtime = selected(mode, calls)
    capture = callcapture.capture
    def observe(body, log, **options):
        captures.append((copy.deepcopy(body), options['assist_selection']))
        return capture(body, log, **options)
    monkeypatch.setattr(callcapture, 'capture', observe)
    def transport(request, *, timeout, receipt):
        posts.append(request.data)
        return io.BytesIO(b'{"choices":[{"message":{"content":"offline"}}]}')
    # Eligible transport still obeys root disabled/replacement selection.
    up = upstream.Upstream('http://offline.invalid', api_key='fake', context_window=8192,
        engagement_level=0 if mode == 'proxy' else 5,
        capture_dir=tmp_path, capture_rendered=False, open_request=transport)
    log = Log()
    log.phase = phase
    original = {'model': 'offline', 'messages': messages(), bodykeys.PINNED_TASK: 'Continue'}
    before = copy.deepcopy(original)
    # Poison the actual literal service, not a name already captured by the
    # definition: disabled/replaced means the original parser cannot run.
    if mode in ('disabled', 'proxy', 'replaced'):
        monkeypatch.setattr(history.jsontext, 'extract_json_object',
                            Mock(side_effect=AssertionError('original parser')))
    with assistruntime.bound(runtime):
        up.chat(original, log)
    assert original == before
    wire = json.loads(posts[0])
    old = next(tc for m in wire['messages'] for tc in m.get('tool_calls', []) if tc['id'] == 'old')
    valid = next(tc for m in wire['messages'] for tc in m.get('tool_calls', []) if tc['id'] == 'valid')
    expected = ({'cmd': 'echo literal'} if mode == 'enabled' else
                {'chosen': RAW} if mode == 'replaced' else {'_unparsed': RAW})
    assert json.loads(old['function']['arguments']) == expected
    assert old['function']['name'] == 'native_opaque_name'
    assert valid['function']['arguments'] == VALID
    assert calls == ([(RAW,)] if mode == 'replaced' else [])
    assert captures == [(wire, {'selected': list(runtime.selected), 'engagement_level': runtime.engagement_level})]
    assert posts == [json.dumps(wire).encode('utf-8')]
    assert all(bodykeys.CALLER_INSTRUCTIONS not in m for m in wire['messages'])
    assert 'assist_selection' not in wire and bodykeys.PINNED_TASK not in wire


@pytest.mark.parametrize('strict', [False, True])
def test_history_executes_once_after_last_role_transform(monkeypatch, strict):
    calls = []
    runtime = selected('replaced', calls)
    transform = 'merge_for_alternation' if strict else '_merge_consecutive_assistant'
    module = upstream.massage if strict else upstream
    original = getattr(module, transform)
    def append_last(msgs):
        return original(msgs) + messages()[1:]
    monkeypatch.setattr(module, transform, append_last)
    body = {'messages': [{'role': 'user', 'content': 'Continue'}]}
    if strict:
        body[upstream.massage.MERGE_TURNS_KEY] = True
    with assistruntime.bound(runtime):
        raw, _, _ = upstream.Upstream('http://unused')._prep(body, False, Log())
    wire = json.loads(raw)
    assert calls == [(RAW,)]
    assert json.loads(wire['messages'][1]['tool_calls'][0]['function']['arguments']) == {'chosen': RAW}
    assert all(bodykeys.CALLER_INSTRUCTIONS not in m for m in wire['messages'])
    assert upstream.massage.MERGE_TURNS_KEY not in wire


def test_root_high_cannot_enable_optional_recovery_on_pure_proxy_transport():
    calls = []
    runtime = selected('replaced', calls)
    with assistruntime.bound(runtime):
        data, _, _ = upstream.Upstream('http://unused', engagement_level=0)._prep(
            {'messages': messages()}, False, Log())
    wire = json.loads(data)['messages']
    assert calls == []
    assert json.loads(wire[1]['tool_calls'][0]['function']['arguments']) == {'_unparsed': RAW}
    assert wire[1]['tool_calls'][1]['function']['arguments'] == VALID


def test_history_root_nesting_error_and_concurrent_replacements():
    barrier = Barrier(2)
    def run(index):
        calls = []
        runtime = selected('replaced', calls)
        with assistruntime.bound(runtime):
            assert assistruntime.is_bound()
            barrier.wait(timeout=5)
            with pytest.raises(RuntimeError):
                with assistruntime.bound(assistruntime.AssistRuntime.select(level=0)):
                    assert not assistruntime.current().bindings('historical-arguments')
                    raise RuntimeError('nested task failed')
            assert assistruntime.current() is runtime
            up = upstream.Upstream('http://unused', engagement_level=5)
            data, _, _ = up._prep({'messages': messages()}, False, Log())
        assert not assistruntime.is_bound()
        assert calls == [(RAW,)]
        return json.loads(data)['messages'][1]['tool_calls'][0]['function']['arguments']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, [0, 1])) == [json.dumps({'chosen': RAW})] * 2
