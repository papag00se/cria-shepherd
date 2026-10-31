"""Production-boundary regression: fake model HTTP and probe construction only.

No tool, shell, network, GPU, service, repository write or model inference.
Run with PYTHONDONTWRITEBYTECODE=1 and pytest cache disabled. This file imports
existing production-driver fixtures; no implementation copy or eligibility oracle.
"""
import pytest
from cria import assistruntime, bodykeys, denial, loop, stalledwork as sw
from test_stalled_work_production_binding import acting, rig, runtime, SESSION
from test_loop import _Rlog


def window(refused_positions=(0, 3, 11)):
    history = []
    for i in range(sw.REFUSAL_WINDOW):
        cid = f'old-{i}'
        history += [acting(cid)['choices'][0]['message'],
                    {'role': 'tool', 'tool_call_id': cid, 'content': f'observation {i}',
                     bodykeys.RESULT_OUTCOME: denial.REFUSED if i in refused_positions else denial.RAN}]
    assert loop._refusals_in_window(history)[0] == sw.REFUSAL_THRESHOLD
    return history


def prepare(monkeypatch, synthetic, positions=(0, 3, 11)):
    driver, state, body, posted = rig(monkeypatch, runtime(), synthetic=synthetic,
                                    replies=[acting('recovery'), acting('keep-working')])
    body['messages'] += window(positions)
    log = _Rlog()
    first = driver.drive(body, SESSION, None, log)
    assert state.redirect_due and state.repeat_count == 3
    assert state.blocked_fired_seq == state.action_seq == 1
    return driver, state, body, posted, first, log


def returned(body, completion, outcome=denial.RAN):
    body['messages'] += [completion['choices'][0]['message'],
                         {'role': 'tool', 'tool_call_id': 'recovery', 'content': 'a recorded result',
                          bodykeys.RESULT_OUTCOME: outcome}]


def probe_spy(monkeypatch, call=None):
    nominations = []
    def probe(*args, **kwargs):
        nominations.append((args, kwargs))
        return call
    monkeypatch.setattr(loop, '_requested_repository_probe', probe)
    return nominations


@pytest.mark.parametrize('synthetic', [False, True])
def test_run07_aged_out_refusal_does_not_nominate_at_next_inbound(monkeypatch, synthetic):
    driver, state, body, posted, first, log = prepare(monkeypatch, synthetic)
    returned(body, first)
    assert loop._refusals_in_window(body['messages'])[0] == 2
    nominations = probe_spy(monkeypatch, {'id': 'must-not-be-requested', 'type': 'function',
                                        'function': {'name': 'exec_command', 'arguments': '{"cmd":"probe"}'}})
    out = driver.drive(body, SESSION, None, log)
    assert nominations == [], 'stale numeric eligibility must not reach probe construction'
    assert len(posted) == 2 and out['choices'][0]['message']['tool_calls'][0]['id'] == 'keep-working'
    assert not state.redirect_due and state.stalled_probe is None and state.stalled_steer is None
    assert not any(kind == 'loop.redirect_probe' for kind, _ in log.events)


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('positions,outcome', [((1, 3, 11), denial.RAN), ((0, 3, 11), denial.REFUSED)])
def test_still_eligible_latch_survives_until_probe_dispatch(monkeypatch, synthetic, positions, outcome):
    driver, state, body, posted, first, log = prepare(monkeypatch, synthetic, positions)
    returned(body, first, outcome)
    assert loop._refusals_in_window(body['messages'])[0] == 3
    call = {'id': 'real-owned-probe', 'type': 'function',
            'function': {'name': 'exec_command', 'arguments': '{"cmd":"probe"}'}}
    nominations = probe_spy(monkeypatch, call)
    out = driver.drive(body, SESSION, None, log)
    assert len(nominations) == 1 and len(posted) == 1
    assert out['choices'][0]['message']['tool_calls'][0]['id'] == call['id']
    assert state.stalled_probe.call is call and not state.redirect_due
    # The arm site already consumed the cooldown. Admission MUST NOT reapply it.
    assert state.blocked_fired_seq == 1


@pytest.mark.parametrize('synthetic', [False, True])
def test_still_eligible_composition_failure_is_not_swallowed(monkeypatch, synthetic):
    driver, state, body, posted, first, log = prepare(monkeypatch, synthetic, (1, 3, 11))
    returned(body, first)
    nominations = probe_spy(monkeypatch, None)
    driver.drive(body, SESSION, None, log)
    assert len(nominations) == 1 and len(posted) == 2
    assert '3 of your recent calls were refused' in str(posted[-1]['messages'])
    assert any(kind == 'loop.redirect' and fields.get('canned') for kind, fields in log.events)


def test_wheel_spin_latch_unchanged_even_with_zero_refusals(monkeypatch):
    state, log = loop.GuardState(), _Rlog()
    with assistruntime.bound(runtime()):
        for i in range(sw.WRITE_THRESHOLD):
            loop.guard_track_write_streak(state, acting(f'write-{i}', 'write_file',
                {'path': 'a.py', 'content': f'line {i}\n'}), log, messages=[])
        assert state.spin_probe_due and not state.redirect_due
        assert state.recent_writes == [], 'the spin fire consumes its window; never re-test this empty list'
        nominations = probe_spy(monkeypatch, {'id': 'spin', 'type': 'function',
                                            'function': {'name': 'exec_command', 'arguments': '{"cmd":"probe"}'}})
        out = loop.guard_intervene(state, {'messages': [], 'tools': []}, log)
    assert len(nominations) == 1 and out['choices'][0]['message']['tool_calls'][0]['id'] == 'spin'
    assert state.stalled_probe.trigger is sw.Trigger.WHEEL_SPIN


def test_eligible_pending_probe_is_not_revoked_by_later_empty_history(monkeypatch):
    state, log = loop.GuardState(), _Rlog()
    history = window((1, 3, 11))
    with assistruntime.bound(runtime()):
        loop.guard_track_refusals(state, acting('recovery'), log, messages=history)
        nominations = probe_spy(monkeypatch, {'id': 'owned', 'type': 'function',
                                            'function': {'name': 'exec_command', 'arguments': '{"cmd":"probe"}'}})
        loop.guard_intervene(state, {'messages': history, 'tools': []}, log)
        ticket = state.stalled_probe
        loop.guard_intervene(state, {'messages': [], 'tools': []}, log)
    assert len(nominations) == 1 and state.stalled_probe is ticket


def test_step_reset_and_fresh_session_do_not_inherit_refusal_latch(monkeypatch):
    state, other, log = loop.GuardState(), loop.GuardState(), _Rlog()
    history = window()
    with assistruntime.bound(runtime()):
        loop.guard_track_refusals(state, acting('recovery'), log, messages=history)
        assert state.redirect_due
        sw.reset_step(loop._StalledWorkView(state))
        nominations = probe_spy(monkeypatch, {'id': 'must-not-run'})
        assert loop.guard_intervene(state, {'messages': history}, log) is None
        assert loop.guard_intervene(other, {'messages': history}, log) is None
    assert nominations == [] and not state.redirect_due and not other.redirect_due
    assert state.stalled_probe is other.stalled_probe is None
