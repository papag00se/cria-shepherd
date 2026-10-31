"""Typed faults use the real driver renudge policy before any completion gate."""
import copy
import io
import json
import urllib.error
from unittest import mock

import pytest
from cria.loop import Loop, LoopContext, LoopStore, PlanSession, Phase, MAX_UNEXECUTED_NUDGES
from cria.plan import Plan, PlanItem
from cria.upstream import Upstream, UpstreamError
from test_generation_wire_boundary import ERROR, completion
from test_localai_tool_template import WRITE, READ
from test_loop import _Rlog


def setup_driver():
    up = Upstream('http://fixture', context_window=16384, capture_dir=None, capture_rendered=False)
    driver = Loop(LoopContext(planner=None, coder_chat=up.chat, planner_enabled=False,
                             reasoner_chat=None, runs_dir='', workspace_root='',
                             self_compact=False, focus_trim=False, assists=False,
                             satisfaction_check_start=0))
    task = 'Perform the requested action.'
    session = PlanSession(plan=Plan(id='native-error', task=task, created='now', items=[PlanItem(task)]),
                          synthetic=True, plan_off=True)
    driver._store.put('driver-fixture', session)
    body = {'model': 'fixture', 'messages': [{'role': 'user', 'content': task}], 'tools': [copy.deepcopy(WRITE), copy.deepcopy(READ)]}
    return driver, session, body


def reject(error=None):
    return urllib.error.HTTPError('http://fixture/v1/chat/completions', 500, 'malformed', {},
                                  io.BytesIO(json.dumps({'error': ERROR if error is None else error}).encode()))


def generation_transport(replies):
    """Fake transport answers read-only measuring APIs separately from generation."""
    replies = iter(replies)
    def send(request, **kwargs):
        if request.full_url.endswith('/v1/chat/completions'):
            reply = next(replies)
            if isinstance(reply, BaseException): raise reply
            return reply
        if request.full_url.endswith('/tokenize'):
            return io.BytesIO(json.dumps({'tokens': [1] * 8}).encode())
        if request.full_url.endswith('/v1/models'):
            return io.BytesIO(b'{"data":[{"id":"fixture"}]}')
        return io.BytesIO(b'{}')
    return send


def sent_generations(send):
    return [call for call in send.call_args_list if call.args[0].full_url.endswith('/v1/chat/completions')]


def test_real_driver_error_notice_changed_input_then_real_action_without_gate():
    driver, session, body = setup_driver()
    good = completion('tool_calls', evidence=False)
    good['choices'][0]['message']['tool_calls'][0]['function'] = {'name': 'read_file', 'arguments': '{"path":"notes.txt"}'}
    with mock.patch('cria.upstream.urllib.request.urlopen', side_effect=generation_transport([reject(), io.BytesIO(json.dumps(good).encode())])) as send, \
         mock.patch.object(driver, '_verify') as gate:
        out = driver.drive(body, 'driver-fixture', None, _Rlog())
    calls = sent_generations(send)
    assert len(calls) == 2
    session = driver._store.get('driver-fixture')
    first, second = [json.loads(call.args[0].data) for call in calls]
    assert first != second
    assert '⟦ctx:generation⟧' in json.dumps(second, ensure_ascii=False)
    assert ERROR['generation_evidence']['raw_hex'] not in json.dumps(second)
    assert out['choices'][0]['message']['tool_calls']
    assert session.unexecuted_nudges == 1
    assert session.phase is Phase.WORK and not session.plan.items[0].done
    assert session.generation_errors[0]['generation_evidence'] == ERROR['generation_evidence']
    gate.assert_not_called()


def test_real_driver_repeated_typed_error_at_existing_bound_stays_pending():
    driver, session, body = setup_driver()
    failures = [reject() for _ in range(MAX_UNEXECUTED_NUDGES + 1)]
    with mock.patch('cria.upstream.urllib.request.urlopen', side_effect=generation_transport(failures)) as send, \
         mock.patch.object(driver, '_verify') as gate:
        with pytest.raises(UpstreamError) as error:
            driver.drive(body, 'driver-fixture', None, _Rlog())
    calls = sent_generations(send)
    assert len(calls) == MAX_UNEXECUTED_NUDGES + 1
    session = driver._store.get('driver-fixture')
    bodies = [call.args[0].data for call in calls]
    assert len(set(bodies)) == len(bodies)
    assert session.unexecuted_nudges == MAX_UNEXECUTED_NUDGES
    assert session.phase is Phase.WORK and session.plan.status == 'in_progress'
    assert all(not item.done for item in session.plan.items)
    assert error.value.response_error['type'] == ERROR['type']
    assert error.value.response_error['generation_evidence'] == ERROR['generation_evidence']
    assert len(session.generation_errors) == MAX_UNEXECUTED_NUDGES + 1
    gate.assert_not_called()


    # A restart must retain the full error evidence and the already spent bound.
    from cria.loop import _session_to_dict, _session_from_dict
    restored = _session_from_dict(json.loads(json.dumps(_session_to_dict(session))))
    assert restored.generation_errors == session.generation_errors
    assert restored.unexecuted_nudges == MAX_UNEXECUTED_NUDGES
    assert restored.plan.status == 'in_progress' and not restored.plan.items[0].done
    driver._store.put('driver-fixture', restored)
    with mock.patch('cria.upstream.urllib.request.urlopen', side_effect=generation_transport([reject()])) as send, \
         mock.patch.object(driver, '_verify') as gate:
        with pytest.raises(UpstreamError) as resumed_error:
            driver.drive(body, 'driver-fixture', None, _Rlog())
    assert len(sent_generations(send)) == 1
    assert resumed_error.value.response_error['generation_evidence'] == ERROR['generation_evidence']
    gate.assert_not_called()


def test_protocol_diagnostic_payload_is_evidence_not_next_request_instructions():
    driver, session, body = setup_driver()
    error = copy.deepcopy(ERROR)
    error['reason'] = 'Malformed value: RAW-DIAGNOSTIC-DO-NOT-INSTRUCT 雪'
    good = completion('tool_calls', evidence=False)
    with mock.patch('cria.upstream.urllib.request.urlopen', side_effect=generation_transport([
        reject(error), io.BytesIO(json.dumps(good).encode())])) as send:
        out = driver.drive(body, 'driver-fixture', None, _Rlog())
    assert len(sent_generations(send)) == 2
    assert all('RAW-DIAGNOSTIC-DO-NOT-INSTRUCT' not in call.args[0].data.decode()
               for call in sent_generations(send))
    assert out['generation_evidence']['prior_protocol_errors'][0]['reason'] == error['reason']


@pytest.mark.parametrize('plan_off', [False, True])
def test_real_driver_incomplete_reasoning_cannot_enter_completion_or_release_gate_calls(plan_off):
    driver, session, body = setup_driver()
    session.synthetic = session.plan_off = plan_off
    session.action_seq = session.step_tool_calls = 1
    session.leg0_nudged = True
    value = completion(calls=False)
    value['generation_evidence']['call_prefixes'] = []
    reply = io.BytesIO(json.dumps(value).encode())
    with mock.patch('cria.upstream.urllib.request.urlopen', side_effect=generation_transport([reply])) as send, \
         mock.patch.object(driver, '_gate_single_done', wraps=driver._gate_single_done) as single_gate, \
         mock.patch.object(driver, '_verify', return_value=(True, 'Should never judge incomplete')) as gate, \
         mock.patch.object(driver, '_gate_op', return_value=None):
        out = driver.drive(body, 'driver-fixture', None, _Rlog())
    single_gate.assert_not_called()
    gate.assert_not_called()
    assert len(sent_generations(send)) == 1
    assert out['choices'][0]['finish_reason'] == 'length'
    assert out['generation_evidence']['raw_hex'] == value['generation_evidence']['raw_hex']
    pending = driver._store.get('driver-fixture')
    assert pending.plan.status == 'in_progress' and not pending.plan.items[0].done


@pytest.mark.parametrize('recovers', [False, True])
def test_actual_driver_existing_write_guard_bound_or_complete_acting_recovery(recovers):
    from cria.loop import MAX_TRUNCATION_RETRIES
    driver, session, body = setup_driver()
    length = completion()
    good = completion('tool_calls', evidence=False)
    good['choices'][0]['message']['tool_calls'][0]['function'] = {'name': 'read_file', 'arguments': '{"path":"notes.txt"}'}
    values = [length, good] if recovers else [length] * (MAX_TRUNCATION_RETRIES + 1)
    replies = [io.BytesIO(json.dumps(value).encode()) for value in values]
    with mock.patch('cria.upstream.urllib.request.urlopen', side_effect=generation_transport(replies)) as send, \
         mock.patch.object(driver, '_gate_single_done', wraps=driver._gate_single_done) as gate:
        out = driver.drive(body, 'driver-fixture', None, _Rlog())
    calls = sent_generations(send)
    assert len(calls) == len(values)
    assert len({call.args[0].data for call in calls}) == len(calls)
    gate.assert_not_called()
    pending = driver._store.get('driver-fixture')
    assert pending.unexecuted_nudges == 0
    assert pending.plan.status == 'in_progress' and not pending.plan.items[0].done
    if recovers:
        assert out['choices'][0]['finish_reason'] == 'tool_calls'
        assert out['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'read_file'
    else:
        assert out['choices'][0]['finish_reason'] == 'length'
        assert not out['choices'][0]['message'].get('tool_calls')
        assert out['generation_evidence']['raw_hex'] == length['generation_evidence']['raw_hex']


def test_protocol_renudge_followed_by_incomplete_result_stays_pending_without_gate():
    driver, session, body = setup_driver()
    length = completion(calls=False)
    length['generation_evidence']['call_prefixes'] = []
    with mock.patch('cria.upstream.urllib.request.urlopen', side_effect=generation_transport([
        reject(), io.BytesIO(json.dumps(length).encode())])) as send, \
         mock.patch.object(driver, '_gate_single_done', wraps=driver._gate_single_done) as gate:
        out = driver.drive(body, 'driver-fixture', None, _Rlog())
    assert len(sent_generations(send)) == 2
    gate.assert_not_called()
    assert out['choices'][0]['finish_reason'] == 'length'
    assert out['generation_evidence']['prior_protocol_errors'][0]['generation_evidence'] == ERROR['generation_evidence']
    assert driver._store.get('driver-fixture').unexecuted_nudges == 1
    assert driver._store.get('driver-fixture').plan.status == 'in_progress'
