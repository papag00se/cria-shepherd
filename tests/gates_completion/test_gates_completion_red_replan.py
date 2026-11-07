"""A discovery refresh must not hide a checker failure from the event that produced it."""
import os
import subprocess
from types import SimpleNamespace

import pytest

from cria import assistruntime, loop, probediscovery as pd, probegate, proberun
from cria.plan import Plan, PlanItem
from gates_completion_helpers import Log, gates_completion_view  # noqa: F401


def pytest_outcome(tmp_path, *, red, replan):
    (tmp_path / 'test_cart.py').write_text('def test_total():\n    assert 1 == 2\n' if red else 'def test_total():\n    assert 1 == 1\n')
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTEST_ADDOPTS='', PYTHONDONTWRITEBYTECODE='1')
    run = subprocess.run(['python3', '-m', 'pytest', '-v', '-p', 'no:cacheprovider'], cwd=tmp_path,
                         env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == (1 if red else 0)
    candidate = pd.cand(pd.ProbeKind.Test, ['python3', '-m', 'pytest', '-v'], tmp_path,
                        90, 90, pd.ProbeCost.Moderate, 'test')
    result = proberun.interpret_probe_output(candidate, 'python3 -m pytest -v', run.stdout, run.returncode, 30)
    return probegate.GateOutcome(ran=True, replan_after_survey=replan,
                                 report=proberun.ProbeReport(selected=[candidate], results=[result]))


def gate_call():
    return {'id': 'replanned', 'type': 'function', 'function': {'name': 'shell', 'arguments': '{}'}}


def test_task_shows_real_red_before_replanning_then_clean_changed_gate_can_replan(tmp_path, monkeypatch):
    red = pytest_outcome(tmp_path, red=True, replan=True)
    current = [red]
    monkeypatch.setattr(loop, 'read_gate', lambda *a: current[0])
    monkeypatch.setattr(loop, 'guard_probe_reissue', lambda *a, **k: None)
    monkeypatch.setattr(loop, 'guard_gate_transport', lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(loop, 'guard_gate_replan_after_survey', lambda *a, **k: calls.append('replan') or gate_call())
    driver = loop.Loop.__new__(loop.Loop)
    driver._ctx = SimpleNamespace(reasoner_role=None)
    state = loop.GuardState(workspace_root=str(tmp_path), probe_call_id='gate', done_probe=True)
    body = {'tools': [], 'messages': [{'role': 'tool', 'tool_call_id': 'gate', 'content': 'gate-result'}]}
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        result = driver._settle_task_done_probe(state, body, 'session', Log(), plan_off=True)
        assert result is None and calls == []
        assert state.last_gate_red and 'assert 1 == 2' in state.nudge_reason
        # A later clean gate may discover a changed plan; its survey refresh still occurs.
        current[0] = pytest_outcome(tmp_path, red=False, replan=True)
        state.done_probe = True
        result = driver._settle_task_done_probe(state, body, 'session', Log(), plan_off=True)
        assert result['choices'][0]['message']['tool_calls'][0]['id'] == 'replanned'
        assert calls == ['replan']


def test_plan_on_backstop_shows_real_red_before_replan_and_clean_still_replans(tmp_path, monkeypatch):
    red = pytest_outcome(tmp_path, red=True, replan=True)
    current = [red]
    monkeypatch.setattr(loop, 'read_gate', lambda *a: current[0])
    monkeypatch.setattr(loop, '_reissue_repository_checks', lambda *a, **k: SimpleNamespace(call=None))
    monkeypatch.setattr(loop, 'guard_gate_transport', lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(loop, 'guard_gate_replan_after_survey', lambda *a, **k: calls.append('replan') or gate_call())
    monkeypatch.setattr(loop.Loop, '_judge_search_reads', lambda self, sess, body, log: body['messages'])
    monkeypatch.setattr(loop.Loop, '_persist_plan', lambda *a, **k: None)
    monkeypatch.setattr(loop.Loop, '_renudge', lambda self, sess, key, body, text, log: {'red': text})
    driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=lambda *a: b'', reasoner_chat=None, runs_dir='',
                                       workspace_root=str(tmp_path), planner_enabled=True))
    def session():
        state = loop.PlanSession(plan=Plan(id='p', task='Build cart', created='now',
                                           items=[PlanItem('Build cart', done=True)]))
        state.workspace_root, state.completion_probe_id = str(tmp_path), 'gate'
        return state
    body = {'tools': [], 'messages': [{'role': 'tool', 'tool_call_id': 'gate', 'content': 'gate-result'}]}
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        state = session()
        result = driver._work(state, 'session', body, Log())
        assert 'assert 1 == 2' in result['red'] and calls == [] and state.last_gate_red
        assert not state.plan.items[-1].done
        current[0] = pytest_outcome(tmp_path, red=False, replan=True)
        result = driver._work(session(), 'session', body, Log())
        assert result['choices'][0]['message']['tool_calls'][0]['id'] == 'replanned'
        assert calls == ['replan']


def test_step_sends_real_red_to_critic_before_replan_and_clean_still_replans(tmp_path, monkeypatch):
    red = pytest_outcome(tmp_path, red=True, replan=True)
    current = [red]
    monkeypatch.setattr(loop, 'read_gate', lambda *a: current[0])
    monkeypatch.setattr(loop, '_reissue_repository_checks', lambda *a, **k: SimpleNamespace(call=None))
    monkeypatch.setattr(loop, 'guard_gate_transport', lambda *a, **k: None)
    monkeypatch.setattr(loop, 'guard_probe_steer', lambda *a, **k: None)
    calls, seen = [], []
    monkeypatch.setattr(loop, 'guard_gate_replan_after_survey', lambda *a, **k: calls.append('replan') or gate_call())
    monkeypatch.setattr(loop.Loop, '_grounded_evidence', lambda *a, **k: '')
    monkeypatch.setattr(loop.Loop, '_verify', lambda self, *a, **k: seen.append(k.get('red_findings')) or (False, 'not done'))
    monkeypatch.setattr(loop.Loop, '_renudge', lambda *a, **k: {'finished': False})
    monkeypatch.setattr(loop.Loop, '_renudge_or_replan', lambda *a, **k: {'finished': False})
    driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=lambda *a: b'', reasoner_chat=None, runs_dir='',
                                       workspace_root=str(tmp_path), planner_enabled=True))
    state = loop.PlanSession(plan=Plan(id='p', task='Build cart', created='now', items=[PlanItem('Build cart')]))
    state.workspace_root, state.probe_call_id, state.awaiting_probe = str(tmp_path), 'gate', True
    body = {'tools': [], 'messages': [{'role': 'tool', 'tool_call_id': 'gate', 'content': 'gate-result'}]}
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        assert driver._verify_after_probe(state, 'session', body, Log()) == {'finished': False}
        assert calls == [] and seen and 'assert 1 == 2' in seen[0] and state.last_gate_red
        current[0] = pytest_outcome(tmp_path, red=False, replan=True)
        state.awaiting_probe = True
        result = driver._verify_after_probe(state, 'session', body, Log())
        assert result['choices'][0]['message']['tool_calls'][0]['id'] == 'replanned'
        assert calls == ['replan']
