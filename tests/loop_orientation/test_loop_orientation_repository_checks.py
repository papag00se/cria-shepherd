"""The periodic repository check-in: when it is due, and that a refused, cut or unreadable run is never read as green."""
import copy
from pathlib import Path

import pytest
from cria import loop, probegate, proberun, prompts, repositorychecks as rcheck
from gate_fixtures import FakeGateSeam
from cria import probediscovery as pd
from cria.probeparse import parse_output
from loop_orientation_helpers import Log, local_workspace_view  # noqa: F401

SHELL = [{"type": "function", "function": {"name": "exec_command", "parameters": {
    "type": "object", "properties": {"cmd": {"type": "string"}, "yield_time_ms": {"type": "integer"}}}}}]

def body(shell=True):
    return {"tools": SHELL if shell else [], "messages": [
        {"role": "user", "content": "Implement the complete task"},
        {"role": "tool", "tool_call_id": "unrelated", "content": "unrelated output"}]}

def probes(plan=None):
    plan = plan or probegate.GatePlan("/workspace", surveyed_before=True, script="FAKE CHECK ONLY")
    return rcheck.ProbeServices(lambda messages: "/workspace", lambda *a, **kw: copy.deepcopy(plan), lambda: FAKE.seam)

FAKE = FakeGateSeam()

def evidence(state, result=None):
    return rcheck.EvidenceServices(lambda st: result, loop.read_gate, loop.gate_error_text,
                                   lambda findings, messages, **kw: loop.track_gate_progress(state, findings, messages, **kw))

def resume(result, plan, **state_kw):
    state = loop.GuardState(periodic_probe=True, awaiting_probe=True, probe_call_id="probe", gate_plan=plan, **state_kw)
    hooks = rcheck.ResumeHooks(reissue=rcheck.DEFINITION.reissue, replan=rcheck.DEFINITION.replan)
    src = rcheck.Input(body(), Log(), 5)
    return rcheck.resume(src, state, probes(), evidence(state, result), rcheck.JudgmentServices(), hooks), state, src

@pytest.mark.parametrize("turns,shell,status", [(14, True, rcheck.Status.NOT_DUE), (15, True, rcheck.Status.PENDING),
                                                (15, False, rcheck.Status.UNAVAILABLE)])
def test_the_check_in_is_due_on_the_fifteenth_coder_turn_and_only_with_a_shell(turns, shell, status):
    state = loop.GuardState(coder_turns=turns, periodic_replan_done=True)
    result = rcheck.admit(rcheck.Input(body(shell=shell), Log(), 5), state, probes())
    assert result.status is status
    assert state.coder_turns == (turns if status is rcheck.Status.NOT_DUE else 0)   # a due check-in restarts the clock, even unavailable
    assert (state.awaiting_probe, state.periodic_probe) == ((True, True) if status is rcheck.Status.PENDING else (False, False))

def test_a_passing_tally_regression_is_per_command_and_a_runner_without_a_tally_is_not_zero_tests():
    state = loop.GuardState()
    state.tests_passed_high = {"pytest": 9}
    cand = lambda cmd, eco: pd.ProbeCandidate(pd.ProbeKind.Test, cmd, Path("."), 90, 90, pd.ProbeCost.Moderate, False,
                                              False, False, "fixture", ecosystem=eco)
    report = proberun.ProbeReport([], [cand(["pytest"], pd.Ecosystem.Python)],
                                  [parse_output("pytest", "pytest", 0, "7 passed in 0.1s", "")])
    assert rcheck.passing_test_regression(state, report) == prompts.render("tests_regressed", was="9", now="7")
    level = proberun.ProbeReport([], report.selected, [parse_output("pytest", "pytest", 0, "9 passed in 0.1s", "")])
    assert rcheck.passing_test_regression(state, level) == ""                  # holding the high-water mark is no regression
    untallied = proberun.ProbeReport([], [cand(["go", "test", "./..."], pd.Ecosystem.Go)],
                                     [parse_output("go", "go test ./...", 0, "ok example/project 0.1s", "")])
    assert rcheck.passing_test_regression(state, untallied) == ""
    assert rcheck.passing_test_regression(state, proberun.ProbeReport([], [], [])) == ""
