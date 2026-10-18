"""Observed rewrite identity belongs to Store; delivery, not a policy, acknowledges it."""
from dataclasses import FrozenInstanceError, replace
import io
import json
from unittest.mock import Mock

import pytest

from cria import assistruntime, bodykeys, loop, reorientation, repositorychecks, upstream
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog


def pending(store, key='sid:task'):
    assert store.observe_shape_with_ticket(key, 'original', 10) is None
    ticket = store.observe_shape_with_ticket(key, 'rewritten', 4)
    assert ticket is not None
    return ticket


def test_bool_api_and_ticket_api_share_detection_and_one_shot_acknowledgement():
    store = loop.LoopStore()
    assert store.observe_shape('sid:task', 'original', 10) is False
    assert store.observe_shape('sid:task', 'rewritten', 4) is True
    ticket = store.observe_shape_with_ticket('sid:task', 'rewritten', 4)
    assert ticket.key == 'sid:task' and isinstance(ticket.event_id, str) and ticket.event_id
    with pytest.raises(FrozenInstanceError):
        ticket.event_id = 'changed'
    assert store.ack_rewrite(ticket) is True
    assert store.ack_rewrite(ticket) is False
    assert store.observe_shape('sid:task', 'rewritten', 5) is False


def test_append_preserves_pending_identity_and_ack_survives_restart(tmp_path):
    path = tmp_path / 'state.json'
    store = loop.LoopStore(str(path))
    ticket = pending(store)
    assert store.observe_shape_with_ticket(ticket.key, 'rewritten', 20) == ticket
    restored = loop.LoopStore(str(path))
    assert restored.observe_shape_with_ticket(ticket.key, 'rewritten', 21) == ticket
    assert restored.ack_rewrite(ticket)
    assert not loop.LoopStore(str(path)).observe_shape(ticket.key, 'rewritten', 22)


@pytest.mark.parametrize('next_fp,next_count', [('newer-summary', 4), ('rewritten', 2)])
def test_new_root_or_shrink_cannot_be_consumed_by_prior_delivery(next_fp, next_count):
    store = loop.LoopStore()
    first = pending(store)
    newer = store.observe_shape_with_ticket(first.key, next_fp, next_count)
    assert newer is not None and newer.event_id != first.event_id
    assert not store.ack_rewrite(first)
    assert store.observe_shape_with_ticket(first.key, next_fp, next_count + 1) == newer
    assert store.ack_rewrite(newer)


def test_wrong_key_and_unobserved_or_malformed_receipts_never_acknowledge():
    store = loop.LoopStore()
    first = pending(store)
    other = pending(store, 'sid:other')
    for invalid in (None, {'key': first.key, 'event_id': first.event_id},
                    replace(first, key=other.key), replace(first, event_id=''),
                    replace(first, event_id=None)):
        assert store.ack_rewrite(invalid) is False
    assert store.observe_shape_with_ticket(first.key, 'rewritten', 5) == first
    assert store.observe_shape_with_ticket(other.key, 'rewritten', 5) == other


def test_event_identity_is_not_reused_after_eviction_or_repeated_shape(monkeypatch):
    monkeypatch.setattr(loop, '_MAX_SHAPES', 1)
    store = loop.LoopStore()
    first = pending(store)
    pending(store, 'sid:evicts-old-key')
    assert store.observe_shape_with_ticket(first.key, 'original', 10) is None
    recreated = store.observe_shape_with_ticket(first.key, 'rewritten', 4)
    assert recreated.event_id != first.event_id
    assert not store.ack_rewrite(first)
    assert store.ack_rewrite(recreated)
    store.observe_shape_with_ticket(first.key, 'original', 10)
    repeated = store.observe_shape_with_ticket(first.key, 'rewritten', 4)
    assert repeated.event_id not in (first.event_id, recreated.event_id)


def test_legacy_pending_shape_gains_persisted_identity_without_losing_done(tmp_path):
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({'shapes': {'sid:task': {
        'fp': 'rewritten', 'n': 4, 'pending': True, 'done': True}}, 'sessions': {}}))
    store = loop.LoopStore(str(path))
    ticket = store.observe_shape_with_ticket('sid:task', 'rewritten', 5)
    assert ticket is not None
    saved = json.loads(path.read_text())['shapes']['sid:task']
    assert saved['done'] is True and saved['pending'] is True
    assert saved['rewrite_id'] == ticket.event_id
    assert loop.LoopStore(str(path)).observe_shape_with_ticket('sid:task', 'rewritten', 6) == ticket


def test_unknown_root_does_not_consume_an_existing_pending_event():
    store = loop.LoopStore()
    ticket = pending(store)
    assert store.observe_shape_with_ticket(ticket.key, '', 0) is None
    assert store.observe_shape_with_ticket(ticket.key, 'rewritten', 5) == ticket


def delivery_driver(monkeypatch, selection, *, real_cadences=False):
    driver, sess, body = setup_driver()
    key = 'sid:rewrite-delivery'
    driver._store.put(key, sess)
    driver._store.observe_shape(key, 'prior-root', 20)
    executed = []
    def reorient(source):
        executed.append(source)
        assert source.consume_rewrite is None
        return reorientation.DEFINITION.execute(source)
    definition = replace(reorientation.DEFINITION, execute=reorient)
    runtime = assistruntime.AssistRuntime.select(level=5,
        disabled=(definition.policy.id,) if selection == 'disabled' else ())
    if selection != 'enabled':
        runtime = replace(runtime, ordered_stages=tuple(
            definition if d.policy.id == definition.policy.id else d for d in runtime.ordered_stages))
    driver._ctx.pilot_runtime = runtime
    driver._ctx.assists = True
    satisfaction = (Mock(wraps=driver._periodic_satisfaction) if real_cadences
                    else Mock(return_value=None))
    gate = Mock(wraps=loop.guard_periodic_gate) if real_cadences else Mock(return_value=None)
    monkeypatch.setattr(driver, '_periodic_satisfaction', satisfaction)
    monkeypatch.setattr(loop, 'guard_periodic_gate', gate)
    return driver, sess, body, key, executed, satisfaction, gate


def reply(number=1):
    return loop._completion_toolcalls([{'id': f'next-{number}', 'type': 'function', 'function': {
        'name': 'read_file', 'arguments': json.dumps({'path': f'next-{number}.txt'})}}])


@pytest.mark.parametrize('selection', ['disabled', 'enabled', 'replaced'])
def test_successful_raw_delivery_releases_both_next_turn_cadences(monkeypatch, selection):
    driver, sess, body, key, executed, satisfaction, gate = delivery_driver(
        monkeypatch, selection, real_cadences=True)
    # Both clocks must already be due on the rewrite turn: silence must come from
    # rewrite admission, not a zero clock or the old fixture's missing shell tool.
    sess.coder_turns = repositorychecks.GATE_EVERY_CODER_TURNS
    driver._ctx.satisfaction_check_start = 1
    driver._ctx.satisfaction_check_every = 1
    body['tools'].append({'type': 'function', 'function': {
        'name': 'exec_command', 'parameters': {'type': 'object', 'properties': {
            'cmd': {'type': 'string'}}, 'required': ['cmd']}}})
    review = Mock(return_value=loop.ReviewResult(loop.ReviewStatus.REJECTED))
    monkeypatch.setattr(driver, '_review_task', review)
    plan = loop.probegate.GatePlan(workspace='', script="printf 'offline checker\\n'")
    build = Mock(return_value=plan)
    monkeypatch.setattr(loop.probegate, 'plan_gate', build)
    runtime = driver._ctx.pilot_runtime
    selected = runtime.repository_checks
    admissions = []
    def admit(source, state, services):
        before = state.coder_turns
        result = selected.execute(source, state, services)
        admissions.append((source, state, services, result, before, state.coder_turns))
        return result
    wrapped = replace(selected, execute=admit)
    driver._ctx.pilot_runtime = replace(runtime, ordered_stages=tuple(
        wrapped if d is selected else d for d in runtime.ordered_stages))
    up = driver._ctx.coder_chat.__self__
    sent = []
    def transport(request, **kwargs):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        # Preparation must not consume even an enabled policy's pending rewrite.
        fp = loop._history_root(body['messages'])[1]
        if not sent:
            assert driver._store.observe_shape_with_ticket(key, fp, len(body['messages'])) is not None
        sent.append(json.loads(request.data))
        return io.BytesIO(json.dumps(reply(len(sent))).encode())
    monkeypatch.setattr(up, '_receive_open', transport)
    first_log = _Rlog()
    first = driver.drive(body, key, None, first_log)
    assert len(sent) == 1
    assert satisfaction.call_args == ((sess, body, first_log), {
        'plan_off': True, 'blocked': 'history-rewritten'})
    review.assert_not_called()
    assert sess.satisfaction_last_drive == -1
    assert 'loop.satisfaction_blocked' in first_log.kinds()
    assert len(admissions) == 1
    source, state, services, result, before, after = admissions[0]
    assert source == repositorychecks.Input(body, first_log, 5, '',
        repositorychecks.Driver.TASK, repositorychecks.Trigger.PERIODIC, None, True)
    assert state is sess and isinstance(services, repositorychecks.ProbeServices)
    assert result == repositorychecks.Result(repositorychecks.Status.NOT_DUE)
    assert before == after == repositorychecks.GATE_EVERY_CODER_TURNS
    build.assert_not_called()
    assert not sess.awaiting_probe and not sess.periodic_probe and not sess.probe_call_id
    assert 'loop.periodic_gate' not in first_log.kinds()
    assert first['choices'][0]['message']['tool_calls'] == reply()['choices'][0]['message']['tool_calls']
    assert sess.coder_turns == repositorychecks.GATE_EVERY_CODER_TURNS + 1
    fp = loop._history_root(body['messages'])[1]
    assert driver._store.observe_shape_with_ticket(key, fp, len(body['messages'])) is None
    assert ('re-anchored after a harness compaction' in first.get(bodykeys.NOTES, [])) is (selection != 'disabled')
    body['messages'] += [first['choices'][0]['message'],
                         {'role': 'tool', 'tool_call_id': 'next-1', 'content': 'Current file bytes.'}]
    next_log = _Rlog()
    second = driver.drive(body, key, None, next_log)
    assert satisfaction.call_args == ((sess, body, next_log), {'plan_off': True, 'blocked': ''})
    review.assert_called_once_with(sess, body, next_log, trigger=loop.ReviewTrigger.SCHEDULED)
    assert sess.satisfaction_last_drive == sess.drive_count == 2
    assert 'loop.satisfaction_check' in next_log.kinds()
    assert len(admissions) == 2
    source, state, services, result, before, after = admissions[1]
    assert source == repositorychecks.Input(body, next_log, 5, '',
        repositorychecks.Driver.TASK, repositorychecks.Trigger.PERIODIC, None, False)
    assert state is sess and isinstance(services, repositorychecks.ProbeServices)
    assert isinstance(result, repositorychecks.Result)
    assert result.status is repositorychecks.Status.PENDING
    assert result.pending_kind is repositorychecks.PendingKind.CHECK
    assert before == repositorychecks.GATE_EVERY_CODER_TURNS + 1 and after == 0
    build.assert_called_once_with('', key, next_log,
        poll_wait_s=loop.probegate.GATE_POLL_WAIT_S, helpers_ready=False)
    assert sess.gate_plan is plan and sess.awaiting_probe and sess.periodic_probe
    assert result.call['id'] == sess.probe_call_id
    assert second['choices'][0]['message']['tool_calls'] == [result.call]
    assert result.call['function']['name'] == 'exec_command'
    assert json.loads(result.call['function']['arguments']) == {'cmd': plan.script}
    assert 'loop.periodic_gate' in next_log.kinds()
    # A real due probe takes this turn instead of a second coder generation.
    assert len(sent) == 1 and sess.coder_turns == 0
    assert len(executed) == int(selection == 'replaced')
    assert not sess.plan.items[0].done


@pytest.mark.parametrize('selection', ['disabled', 'enabled'])
@pytest.mark.parametrize('failure', ['transport', 'protocol', 'incomplete'])
def test_failed_delivery_retains_event_and_durable_reset_until_success(monkeypatch, tmp_path, selection, failure):
    driver, sess, body, key, executed, satisfaction, gate = delivery_driver(monkeypatch, selection)
    state = tmp_path / 'state.json'
    driver._store._state_path = state
    sess.replan_uncovered = ('required-output.txt',)
    sess.replan_uncovered_pending = True
    sess.unexecuted_nudges = loop.MAX_UNEXECUTED_NUDGES
    up = driver._ctx.coder_chat.__self__
    observed = []
    def transport(request, **kwargs):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        fp = loop._history_root(body['messages'])[1]
        ticket = driver._store.observe_shape_with_ticket(key, fp, len(body['messages']))
        assert ticket is not None  # enabled preparation has not acknowledged delivery
        observed.append(ticket)
        if failure == 'transport':
            raise upstream.UpstreamError('test transport failed')
        if failure == 'protocol':
            raise upstream.UpstreamProtocolError('test malformed protocol')
        return io.BytesIO(b'{"choices":[{"finish_reason":"length","message":{"role":"assistant","content":""}}]}')
    monkeypatch.setattr(up, '_receive_open', transport)
    if failure == 'incomplete':
        result = driver.drive(body, key, None, _Rlog())
        assert result['choices'][0]['finish_reason'] == 'length'
        assert not result['choices'][0]['message'].get('tool_calls')
    else:
        with pytest.raises(upstream.UpstreamError):
            driver.drive(body, key, None, _Rlog())
    assert observed and all(ticket == observed[0] for ticket in observed)
    assert sess.replan_uncovered_pending and not sess.plan.items[0].done
    restored = loop.LoopStore(str(state))
    assert restored.observe_shape_with_ticket(key, loop._history_root(body['messages'])[1], len(body['messages'])) == observed[0]
    assert restored.get(key).replan_uncovered_pending is True
    assert restored.get(key).replan_uncovered == ('required-output.txt',)
    def success(request, **kwargs):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        return io.BytesIO(json.dumps(reply(99)).encode())
    monkeypatch.setattr(up, '_receive_open', success)
    result = driver.drive(body, key, None, _Rlog())
    assert result['choices'][0]['message']['tool_calls']
    assert not sess.replan_uncovered_pending and not sess.plan.items[0].done
    assert driver._store.observe_shape_with_ticket(key, loop._history_root(body['messages'])[1], len(body['messages'])) is None
    assert not loop.LoopStore(str(state)).get(key).replan_uncovered_pending


@pytest.mark.parametrize('selection', ['disabled', 'enabled'])
def test_successful_old_delivery_does_not_ack_newer_event(monkeypatch, selection):
    driver, sess, body, key, executed, satisfaction, gate = delivery_driver(monkeypatch, selection)
    newer = []
    def transport(request, **kwargs):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        newer.append(driver._store.observe_shape_with_ticket(key, 'newer-in-flight-summary', 1))
        return io.BytesIO(json.dumps(reply()).encode())
    monkeypatch.setattr(driver._ctx.coder_chat.__self__, '_receive_open', transport)
    result = driver.drive(body, key, None, _Rlog())
    assert result['choices'][0]['message']['tool_calls']
    assert len(newer) == 1 and newer[0] is not None
    assert driver._store.observe_shape_with_ticket(key, 'newer-in-flight-summary', 2) == newer[0]
    assert not sess.plan.items[0].done


@pytest.mark.parametrize('before_call', ['defer', 'prepare-failed'])
def test_no_delivery_does_not_ack_or_invoke_disabled_reorientation(monkeypatch, before_call):
    driver, sess, body, key, executed, satisfaction, gate = delivery_driver(monkeypatch, 'disabled')
    chat = Mock(side_effect=AssertionError('coder must not be called'))
    monkeypatch.setattr(driver._ctx.coder_chat.__self__, '_receive_open', chat)
    if before_call == 'defer':
        body['tools'] = []
        assert driver.drive(body, key, None, _Rlog()) is None
    else:
        monkeypatch.setattr(driver, '_prepare_coder_context', Mock(side_effect=RuntimeError('preparation failed')))
        with pytest.raises(RuntimeError, match='preparation failed'):
            driver.drive(body, key, None, _Rlog())
    assert driver._store.observe_shape_with_ticket(key, loop._history_root(body['messages'])[1], len(body['messages'])) is not None
    assert not executed
    chat.assert_not_called()


@pytest.mark.parametrize('rewritten,receipt', [(False, 'own'), (True, 'other'), (True, 'absent')])
def test_unobserved_or_wrong_session_delivery_does_not_clear_event(monkeypatch, rewritten, receipt):
    driver, sess, body, key, executed, satisfaction, gate = delivery_driver(monkeypatch, 'disabled')
    other = pending(driver._store, 'sid:other')
    own = driver._store.observe_shape_with_ticket(key, loop._history_root(body['messages'])[1], len(body['messages']))
    observation = {'own': own, 'other': other, 'absent': None}[receipt]
    def transport(request, **kwargs):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        return io.BytesIO(json.dumps(reply()).encode())
    monkeypatch.setattr(driver._ctx.coder_chat.__self__, '_receive_open', transport)
    with assistruntime.bound(driver._ctx.pilot_runtime):
        driver._drive_single_item(sess, body, key, _Rlog(), rewritten=rewritten,
                                  rewrite_observation=observation)
    assert driver._store.observe_shape_with_ticket(other.key, 'rewritten', 5) == other
    assert driver._store.observe_shape_with_ticket(key, loop._history_root(body['messages'])[1], len(body['messages'])) == own


def test_text_delivery_acknowledges_before_task_gate_without_approving_task(monkeypatch):
    driver, sess, body, key, executed, satisfaction, gate = delivery_driver(monkeypatch, 'disabled')
    def transport(request, **kwargs):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        return io.BytesIO(b'{"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"Context received; work remains."}}]}')
    monkeypatch.setattr(driver._ctx.coder_chat.__self__, '_receive_open', transport)
    def task_gate(session, completion, framed, raw, session_key, log):
        assert not completion['choices'][0]['message'].get('tool_calls')
        assert driver._store.observe_shape_with_ticket(key, loop._history_root(body['messages'])[1], len(body['messages'])) is None
        assert not session.plan.items[0].done
        return completion
    approval = Mock(side_effect=task_gate)
    monkeypatch.setattr(driver, '_gate_single_done', approval)
    result = driver.drive(body, key, None, _Rlog())
    assert result['choices'][0]['message']['content'] == 'Context received; work remains.'
    approval.assert_called_once()
    assert not sess.plan.items[0].done and not sess.done_probe


def test_enabled_author_failure_preserves_observation_before_any_coder_call(monkeypatch):
    from cria.config import Role
    driver, sess, body, key, executed, satisfaction, gate = delivery_driver(monkeypatch, 'enabled')
    body['messages'][0]['content'] = reorientation.CONTINUATION_MARKER + ' Existing work and remaining requirements.'
    driver._ctx.reasoner_role = Role(name='reasoner', backend='local')
    author = Mock(side_effect=RuntimeError('author failed'))
    coder = Mock(side_effect=AssertionError('no delivery before authoring'))
    monkeypatch.setattr(loop, 'summarize', author)
    monkeypatch.setattr(driver._ctx.coder_chat.__self__, '_receive_open', coder)
    with pytest.raises(RuntimeError, match='author failed'):
        driver.drive(body, key, None, _Rlog())
    assert driver._store.observe_shape_with_ticket(key, loop._history_root(body['messages'])[1], len(body['messages'])) is not None
    author.assert_called_once()
    coder.assert_not_called()
