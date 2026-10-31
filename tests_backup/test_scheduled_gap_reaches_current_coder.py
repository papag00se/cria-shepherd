"""A scheduled negative review must reach the coder it is about to drive."""
from types import SimpleNamespace

import pytest

from cria import assistruntime, completiondiagnosis as policy, loop
from test_completion_diagnosis_production_binding import driver_state, runtime
from test_loop import _Rlog


@pytest.mark.parametrize('plan_off', [True, False])
def test_new_scheduled_content_gap_reaches_same_coder_and_is_consumed(monkeypatch, plan_off):
    driver, session, body = driver_state(assists=True)
    session.synthetic = session.plan_off = plan_off
    gap = policy.DiagnosisResult(policy.DiagnosisStatus.GROUNDED,
        'Required content is absent from the measured source.', '', 'missing_content', '')
    monkeypatch.setattr(driver, '_review_task', lambda *args, **kwargs:
        SimpleNamespace(approved=False, reason=loop._diagnosis_nudge(gap)))
    monkeypatch.setattr(loop, 'guard_intervene', lambda *args, **kwargs: None)
    monkeypatch.setattr(loop, 'guard_probe_reissue', lambda *args, **kwargs: None)
    monkeypatch.setattr(loop, 'guard_periodic_gate', lambda *args, **kwargs: None)
    monkeypatch.setattr(driver, '_periodic_step_check', lambda *args, **kwargs: None)
    monkeypatch.setattr(driver, '_replan_if_thrashing', lambda *args, **kwargs: None)
    offered = []
    reply = loop._completion_toolcalls([{'id': 'inspect', 'type': 'function',
        'function': {'name': 'read_file', 'arguments': '{"path":"source.txt"}'}}])
    def coder(sess, framed, raw, **kwargs):
        offered.append(framed)
        return reply
    monkeypatch.setattr(driver, '_coder_turn', coder)
    log = _Rlog()
    with assistruntime.bound(runtime()):
        if plan_off:
            result = driver._drive_single_item(session, body, 'key', log)
        else:
            result = driver._work_item(session, 'key', body, log, session.plan.items[0], 1)
    assert result is reply
    assert len(offered) == 1
    visible = '\n'.join(str(m.get('content', '')) for m in offered[0]['messages'])
    assert gap.text in visible
    assert not session.nudge_reason
    assert not session.completion_remediation_subject


@pytest.mark.parametrize('owner', ['pending', 'guard'])
def test_existing_steer_blocks_review_and_is_not_replaced(monkeypatch, owner):
    driver, session, body = driver_state(assists=True)
    session.synthetic = session.plan_off = True
    existing = 'Inspect the current source before proceeding.'
    if owner == 'pending':
        session.nudge_reason = existing
    def unexpected_review(*args, **kwargs):
        raise AssertionError('scheduled review bypassed the existing steering owner')
    monkeypatch.setattr(driver, '_review_task', unexpected_review)
    monkeypatch.setattr(loop, 'guard_probe_reissue', lambda *args, **kwargs: None)
    monkeypatch.setattr(loop, 'guard_intervene', lambda *args, **kwargs: None)
    monkeypatch.setattr(loop, 'guard_periodic_gate', lambda *args, **kwargs: None)
    if owner == 'guard':
        session.awaiting_probe = True
        monkeypatch.setattr(loop, 'guard_probe_steer', lambda *args, **kwargs: existing)
    offered = []
    reply = loop._completion_toolcalls([{'id': 'inspect', 'type': 'function',
        'function': {'name': 'read_file', 'arguments': '{"path":"source.txt"}'}}])
    def coder(sess, framed, raw, **kwargs):
        offered.append(framed)
        return reply
    monkeypatch.setattr(driver, '_coder_turn', coder)
    with assistruntime.bound(runtime()):
        assert driver._drive_single_item(session, body, 'key', _Rlog()) is reply
    visible = '\n'.join(str(m.get('content', '')) for m in offered[0]['messages'])
    assert visible.count(existing) == 1
    assert not session.nudge_reason


@pytest.mark.parametrize('status', [policy.DiagnosisStatus.WITHHELD, policy.DiagnosisStatus.NOT_APPLICABLE])
def test_ungrounded_scheduled_gap_stays_silent_and_does_not_finish(monkeypatch, status):
    driver, session, body = driver_state(assists=True)
    session.synthetic = session.plan_off = True
    gap = policy.DiagnosisResult(status, 'Unverified gap must not reach the coder.', '', 'missing_content', '')
    monkeypatch.setattr(driver, '_review_task', lambda *args, **kwargs:
        SimpleNamespace(approved=False, reason=loop._diagnosis_nudge(gap)))
    monkeypatch.setattr(loop, 'guard_intervene', lambda *args, **kwargs: None)
    monkeypatch.setattr(loop, 'guard_probe_reissue', lambda *args, **kwargs: None)
    monkeypatch.setattr(loop, 'guard_periodic_gate', lambda *args, **kwargs: None)
    offered = []
    reply = loop._completion_toolcalls([{'id': 'inspect', 'type': 'function',
        'function': {'name': 'read_file', 'arguments': '{"path":"source.txt"}'}}])
    def coder(sess, framed, raw, **kwargs):
        offered.append(framed)
        return reply
    monkeypatch.setattr(driver, '_coder_turn', coder)
    with assistruntime.bound(runtime()):
        assert driver._drive_single_item(session, body, 'key', _Rlog()) is reply
    assert 'Unverified gap' not in str(offered)
    assert not session.nudge_reason and not session.last_gap_named
