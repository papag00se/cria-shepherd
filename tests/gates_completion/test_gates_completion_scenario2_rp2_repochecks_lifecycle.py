"""Scenario: the repository-check lifecycle at its seams — a plan that cannot be composed, a harness whose shell vanishes mid-page,
a survey-only first gate that must be re-planned, a transport that goes unknown repeatedly (bounded, said, then silent), a compacted
history on the STEP driver, and the two judgments (runner, module) that may speak before the checker's own words."""
import json

import pytest

from cria import loop, probegate, repositorychecks as rc
from gates_completion_helpers import Log, gates_completion_view, new_plan, page, sec  # noqa: F401
from test_gates_completion_scenario_periodic_checks import TOOLS, Driver, harness, pump

GONE = lambda plan: "\n".join([probegate._transport_marker(plan.transport_id), "gone\t1", probegate._transport_marker(plan.transport_id, end=True)])  # noqa: E731


def answered(d, call, text):
    d.messages += [{"role": "assistant", "tool_calls": [call]}, {"role": "tool", "tool_call_id": call["id"], "content": text}]


def test_a_plan_that_cannot_be_composed_leaves_no_pending_check_and_a_missing_shell_ends_a_transport(tmp_path, monkeypatch):
    harness(tmp_path, monkeypatch, "print('ok')")
    d = Driver(tmp_path, coder_turns=15)
    broken = rc.ProbeServices(lambda m: str(tmp_path), lambda *a, **k: (_ for _ in ()).throw(OSError("disk gone")), lambda: "c0")
    out = rc.admit(d.source(), d.state, broken)
    assert out.status is rc.Status.UNAVAILABLE and d.state.gate_plan is None and ("loop.gate_error", {"level": "warn", "error": "disk gone"}) in d.log.events
    d.state.coder_turns = 15
    first = rc.admit(d.source(), d.state, d.probes)
    assert first.status is rc.Status.PENDING and d.state.gate_plan.transport_required
    shellless = rc.Input({"tools": [], "messages": d.messages}, d.log, 5)
    assert rc.transport(d.source(), loop.GuardState(), d.probes, d.evidence).status is rc.Status.NOT_DUE      # no plan, nothing to page
    # a plan still running when the harness stops offering a shell is terminal UNKNOWN, said once
    plan = new_plan(workspace=str(tmp_path))
    state = loop.GuardState(gate_plan=plan, probe_call_id="p")
    d.messages.append({"role": "tool", "tool_call_id": "p", "content": page(plan, "x" * 50, 0, 10)})
    assert rc.transport(shellless, state, d.probes, d.evidence).status is rc.Status.OBSERVED
    assert plan.transport_error == "the harness no longer offers a shell for the next page" and rc.poll_after_rewrite(shellless, state, d.probes) is None
    assert ("gate.transport_unknown", {"level": "warn", "reason": plan.transport_error, "received": 10, "total": 50}) in d.log.events


def test_a_survey_only_first_gate_is_replanned_once_and_a_transport_unknown_repeatedly_stops_vetoing(tmp_path, monkeypatch):
    harness(tmp_path, monkeypatch, "print('ok')")
    d = Driver(tmp_path, coder_turns=15, gate_replan_required=True)
    assert rc.replan(d.source(), d.state, d.probes).pending_kind is rc.PendingKind.SURVEY_REPLAN and not d.state.gate_replan_required
    assert rc.replan(d.source(), d.state, d.probes).status is rc.Status.NOT_DUE
    d.state.gate_replan_required = True
    noshell = rc.Input({"tools": [], "messages": []}, d.log, 5)
    assert rc.replan(noshell, d.state, d.probes).status is rc.Status.UNAVAILABLE and not d.state.gate_replan_required
    d.state.gate_replan_required = True
    again = rc.replan(d.source(), d.state, d.probes, periodic=True)
    assert again.status is rc.Status.PENDING and d.state.periodic_probe and d.state.probe_call_id == again.call["id"]
    d.state.gate_replan_required = True
    assert rc.replan(d.source(), d.state, d.probes, periodic=True).status is rc.Status.NOT_DUE              # bounded: once per periodic cycle

    texts = []
    for n in range(rc.MAX_COMPLETION_CHECKS + 2):
        call = rc.compose(d.source(), d.state, d.probes)
        answered(d, call, GONE(d.state.gate_plan))
        out = rc.completion_result(d.source(), d.state, d.evidence)
        texts.append((out.status, d.state.gate_unknown_streak))
    assert texts[0] == (rc.Status.OBSERVED, 1) and texts[rc.MAX_COMPLETION_CHECKS - 1] == (rc.Status.OBSERVED, rc.MAX_COMPLETION_CHECKS)
    assert texts[-1] == (rc.Status.SILENT, rc.MAX_COMPLETION_CHECKS + 2)
    assert "loop.done_unverified" in [n for n, _ in d.log.events] and not d.state.gate_fresh


@pytest.mark.parametrize("program,status,spoken", [
    ("import sys; print('a.py:3: error: boom'); sys.exit(1)", rc.Status.OBSERVED, "a.py:3: error: boom"),
    ("print('fine')", rc.Status.SILENT, None),
], ids=["red", "green"])
def test_completion_checks_veto_only_with_the_checkers_words_and_never_approve(tmp_path, monkeypatch, program, status, spoken):
    harness(tmp_path, monkeypatch, program)
    d = Driver(tmp_path)
    call = rc.compose(d.source(), d.state, d.probes)
    d.state.probe_call_id = call["id"]
    d.run(call)
    for _ in range(20):
        out = rc.transport(d.source(), d.state, d.probes, d.evidence)
        if out.pending_kind is not rc.PendingKind.PAGE:
            break
        d.run(out.call)
    done = rc.completion_result(d.source(), d.state, d.evidence)
    assert done.status is status and (spoken in done.text if spoken else done.text is None)
    assert d.state.last_gate_red is bool(spoken) and d.state.gate_fresh is (not spoken)


def test_a_gate_that_never_ran_is_logged_and_a_compacted_step_history_neither_reissues_nor_recovers_a_periodic_check(tmp_path, monkeypatch):
    harness(tmp_path, monkeypatch, "print('ok')")
    d = Driver(tmp_path, coder_turns=15)
    first = rc.admit(d.source(), d.state, d.probes)
    step = lambda **kw: d.source(driver=rc.Driver.STEP, rewritten=True, step=3, **kw)         # noqa: E731
    assert rc.reissue(step(), d.state, d.probes, d.evidence).status is rc.Status.NOT_DUE         # a periodic step check never reissues
    d.state.periodic_probe = False
    assert rc.reissue(step(), d.state, d.probes, d.evidence).pending_kind is rc.PendingKind.REWRITE_POLL      # nonperiodic step: re-poll the spool
    d.state.awaiting_probe = False
    assert rc.reissue(step(), d.state, d.probes, d.evidence).status is rc.Status.NOT_DUE
    d.state.awaiting_probe, d.state.probe_call_id = True, first.call["id"]
    d.run(first.call)
    assert rc.reissue(step(), d.state, d.probes, d.evidence).status is rc.Status.OBSERVED          # the answer is there: nothing to redo
    blind = Driver(tmp_path)
    blind.state.awaiting_probe, blind.state.probe_call_id = True, "never-answered"
    noshell = rc.Input({"tools": [], "messages": []}, blind.log, 5, rewritten=True)
    assert rc.reissue(noshell, blind.state, blind.probes, blind.evidence).status is rc.Status.UNAVAILABLE
    assert rc.reissue(blind.source(), blind.state, blind.probes, blind.evidence).status is rc.Status.NOT_DUE          # not rewritten: just wait
    assert rc.reissue(blind.source(driver=rc.Driver.STEP, rewritten=True, step=2), blind.state, blind.probes, blind.evidence).pending_kind is rc.PendingKind.REISSUE
    assert blind.state.awaiting_probe and ("loop.probe_reissued", {"attempt": 1, "step": 2}) in [(n, {k: v for k, v in f.items() if k in ("attempt", "step")}) for n, f in blind.log.events]


def test_the_runner_and_module_judgments_speak_before_the_checker_and_a_survey_only_result_waits(tmp_path, monkeypatch):
    harness(tmp_path, monkeypatch, "import sys; print('b.py:2: error: bad'); sys.exit(1)")
    for judgments, expect in ((rc.JudgmentServices(runner=lambda o: "RUNNER SAYS"), "RUNNER SAYS"),
                              (rc.JudgmentServices(module=lambda o: "MODULE SAYS"), "MODULE SAYS"),
                              (rc.JudgmentServices(), "b.py:2: error: bad")):
        d = Driver(tmp_path, coder_turns=15)
        out = pump(d, rc.admit(d.source(), d.state, d.probes))
        # pump already ran the default judgments; rerun periodic_result for the judged variants over the same evidence
        d.state.periodic_probe = True
        again = rc.periodic_result(d.source(), d.state, d.evidence, judgments)
        assert expect in again.text and out.status is rc.Status.OBSERVED
    not_due = rc.periodic_result(d.source(), loop.GuardState(), d.evidence, rc.JudgmentServices())
    assert not_due.status is rc.Status.NOT_DUE
    survey = new_plan(workspace=str(tmp_path))
    survey.transport_required = False
    state = loop.GuardState(gate_plan=survey, gate_unknown_streak=2)
    rc.record(d.source(), state, probegate.GateOutcome(replan_after_survey=True), "", d.evidence)
    assert state.gate_replan_required and not state.gate_fresh and state.gate_unknown_streak == 0
    assert ("loop.gate_survey_only", {"level": "info"}) in d.log.events
    rc.record(d.source(), state, probegate.GateOutcome(), "", d.evidence)
    assert state.gate_fresh and not state.gate_replan_required and state.last_gate_ran is False
