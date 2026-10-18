"""Both actual drivers settle read credit from the retained coder's final POST."""
import copy
from dataclasses import replace
import io
import json

import pytest

from cria import assistruntime, bodykeys, generationguards as guards, loop
from unittest.mock import Mock
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog


@pytest.mark.parametrize('synthetic', [False, True])
def test_both_drivers_use_task_disabled_selection_not_outer_enabled_defaults(synthetic, monkeypatch):
    driver, session, body = setup_driver()
    session.synthetic = synthetic
    session.plan_off = synthetic
    driver._ctx.pilot_runtime = assistruntime.AssistRuntime.select(level=5,
        disabled=tuple(d.policy.id for d in guards.DEFINITIONS))
    poison = replace(guards.RUNAWAY, execute=Mock(side_effect=AssertionError('outer recovery')))
    outer = assistruntime.AssistRuntime.select(level=5)
    outer = replace(outer, ordered_stages=tuple(poison if d.policy.id == poison.policy.id else d
                                              for d in outer.ordered_stages))
    monkeypatch.setattr(loop, '_generation_cut_services', Mock(side_effect=AssertionError('disabled cuts')))
    monkeypatch.setattr(loop, '_generation_grounding_services', Mock(side_effect=AssertionError('disabled grounding')))
    up = driver._ctx.coder_chat.__self__
    def send(request, **options):
        return io.BytesIO(b'{"choices":[{"finish_reason":"tool_calls","message":{"role":"assistant",'
                         b'"tool_calls":[{"id":"read","type":"function","function":{"name":"read_file",'
                         b'"arguments":"{\\"path\\":\\"notes.txt\\"}"}}]}}]}')
    monkeypatch.setattr(up, '_receive_open', send)
    with assistruntime.bound(outer):
        result = driver.drive(body, 'driver-fixture', None, _Rlog())
        assert assistruntime.current() is outer
    assert result['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'read_file'
    poison.execute.assert_not_called()
    assert session.restored_current == {}


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('retry', [False, True])
def test_final_coder_reply_receipt_not_initial_or_auxiliary(synthetic, retry, monkeypatch):
    driver, session, body = setup_driver()
    session.synthetic = synthetic
    session.plan_off = synthetic
    offered = {'kept.txt': 'original-sha'}
    body['messages'].append({'role': 'user', 'content': 'restored original whole text',
                            bodykeys.RESTORED_FILES: {'offered': offered}})
    posts = []
    up = driver._ctx.coder_chat.__self__
    def send(request, **options):
        if request.full_url.endswith('/tokenize'):
            return io.BytesIO(b'{"tokens":[1,2,3]}')
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{}')
        posts.append(json.loads(request.data))
        return io.BytesIO(json.dumps({'choices': [{'finish_reason': 'tool_calls', 'message': {
            'role': 'assistant', 'tool_calls': [{'id': str(len(posts)), 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"notes.txt"}'}}]}}]}).encode())
    monkeypatch.setattr(up, '_receive_open', send)
    # The auxiliary call uses a real final-wire receipt, but is not a coder reply.
    def execute(source, services, grounding):
        completion = source.completion
        if retry:
            changed = copy.deepcopy(source.body)
            changed['messages'] = [m for m in changed['messages'] if not m.get(bodykeys.RESTORED_FILES)]
            completion = services.retry(changed, changed.get('tools'))
        up.chat({'messages': [{'role': 'user', 'content': 'auxiliary restored text',
                              bodykeys.RESTORED_FILES: {'offered': {'aux.txt': 'wrong'}}}]}, services.log)
        return guards.RecoveryResult(completion, guards.RecoveryStatus.RECOVERED if retry else guards.RecoveryStatus.UNCHANGED)
    definition = replace(guards.RUNAWAY, execute=execute)
    runtime = assistruntime.AssistRuntime.select(level=5)
    runtime = replace(runtime, ordered_stages=tuple(definition if d.policy.id == definition.policy.id else d
                                                 for d in runtime.ordered_stages))
    driver._ctx.pilot_runtime = runtime
    result = driver.drive(body, 'driver-fixture', None, _Rlog())
    assert result['choices'][0]['message']['tool_calls']
    assert session.restored_current == ({} if retry else offered)
    assert 'restored original whole text' in json.dumps(posts[0])
    if retry:
        assert 'restored original whole text' not in json.dumps(posts[1])
    assert 'auxiliary restored text' in json.dumps(posts[-1])
