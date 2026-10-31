"""The periodic repository check-in: when it is due, and that a refused, cut or unreadable run is never read as green."""
import copy
from dataclasses import replace
from pathlib import Path

import pytest
from cria import loop, probegate, proberun, prompts, repositorychecks as rcheck
from cria import probediscovery as pd
from cria.probeparse import parse_output
from loop_orientation_helpers import Log, local_workspace_view  # noqa: F401

SHELL = [{"type": "function", "function": {"name": "exec_command", "parameters": {
    "type": "object", "properties": {"cmd": {"type": "string"}, "yield_time_ms": {"type": "integer"}}}}}]

def body(raw="", shell=True):
    return {"tools": SHELL if shell else [], "messages": [
        {"role": "user", "content": "Implement the complete task"},
        {"role": "tool", "tool_call_id": "unrelated", "content": "unrelated output"},
        {"role": "tool", "tool_call_id": "probe", "content": raw}]}

def probes(plan=None):
    plan = plan or probegate.GatePlan("/workspace", surveyed_before=True, script="FAKE CHECK ONLY")
    return rcheck.ProbeServices(lambda messages: "/workspace", lambda *a, **kw: copy.deepcopy(plan), lambda: "call_fixed")

def evidence(state):
    return rcheck.EvidenceServices(loop._read_tool_result, loop.read_gate, loop.gate_error_text,
                                   lambda findings, messages: loop.track_gate_progress(state, findings, messages))

def resume(raw, plan, **state_kw):
    state = loop.GuardState(periodic_probe=True, awaiting_probe=True, probe_call_id="probe", gate_plan=plan, **state_kw)
    hooks = rcheck.ResumeHooks(reissue=rcheck.DEFINITION.reissue, replan=rcheck.DEFINITION.replan)
    src = rcheck.Input(body(raw), Log(), 5)
    return rcheck.resume(src, state, probes(), evidence(state), rcheck.JudgmentServices(), hooks), state, src

@pytest.mark.parametrize("turns,shell,status", [(14, True, rcheck.Status.NOT_DUE), (15, True, rcheck.Status.PENDING),
                                                (15, False, rcheck.Status.UNAVAILABLE)])
def test_the_check_in_is_due_on_the_fifteenth_coder_turn_and_only_with_a_shell(turns, shell, status):
    state = loop.GuardState(coder_turns=turns, periodic_replan_done=True)
    result = rcheck.admit(rcheck.Input(body(shell=shell), Log(), 5), state, probes())
    assert result.status is status
    assert state.coder_turns == (turns if status is rcheck.Status.NOT_DUE else 0)   # a due check-in restarts the clock, even unavailable
    assert (state.awaiting_probe, state.periodic_probe) == ((True, True) if status is rcheck.Status.PENDING else (False, False))

@pytest.mark.parametrize("raw", ["permission denied", "cut"])
def test_a_refused_or_cut_transport_is_unknown_never_a_green_run(raw):
    """A red board stays red: neither a refusal nor a half-delivered page may be read as the repo's checks passing."""
    plan = probegate.GatePlan("/workspace", surveyed_before=True, transport_required=True)
    if raw == "cut":
        raw = probegate._transport_marker(plan.transport_id) + "\ncut"
    out, state, src = resume(raw, plan, last_gate_red=True)
    assert out.outcome.transport_unknown and out.text == prompts.render("periodic_gate",
                                                                         truth=prompts.load("probe_transport_unknown"))
    assert state.last_gate_red and not state.gate_fresh and "gate.transport_unknown" in [k for k, _ in src.log.events]
    out, state, src = resume("Permission denied: sandbox policy refused this command", probegate.GatePlan("/workspace", surveyed_before=True))
    assert out.text is None and not state.last_gate_ran            # a sandbox refusal: harness words in the log, silence to the coder
    assert any(k == "loop.gate_refused" and "Permission denied" in f["reason"] for k, f in src.log.events)

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

def test_an_unselected_check_lifecycle_calls_no_service_and_leaves_state_alone_and_a_selected_replacement_owns_the_stage():
    def forbidden(*args):
        raise AssertionError("an unselected stage called a service")
    state = loop.GuardState(coder_turns=20, periodic_probe=True)
    before = copy.deepcopy(vars(state))
    off = rcheck.Selected(None)
    for result in (off.admit(forbidden, state, forbidden), off.resume(forbidden, state, forbidden, forbidden, forbidden),
                   off.completion(forbidden, state, forbidden), off.replan(forbidden, state, forbidden),
                   off.reissue(forbidden, state, forbidden, forbidden)):
        assert result.status is rcheck.Status.NOT_SELECTED
    off.observe(state, acting=True)
    assert vars(state) == before
    calls = []
    owned = replace(rcheck.DEFINITION, execute=lambda src, st, svc: calls.append((src, st, svc)) or rcheck.Result(rcheck.Status.SILENT, text="replacement-owned"))
    src = rcheck.Input(body(), Log(), 5)
    out = rcheck.Selected(owned).admit(lambda: src, state, probes)
    assert out.text == "replacement-owned" and len(calls) == 1 and calls[0][:2] == (src, state) and vars(state) == before   # the stock due-clock never ran
