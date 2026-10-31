"""Periodic repository-check lifecycle over a real workspace: admit -> the harness runs the composed script (sh) ->
paged transport -> periodic_result; then a compacted history re-issues the check, and a clean gate settles green.

Story: every 15th acting turn cria runs the repo's own checks via the harness's shell tool. A red check is surfaced
once with the checker's own words; the same check later passing leaves no veto; a history rewrite that dropped the
result re-polls/re-issues (bounded) instead of reading silence as green."""
import subprocess
import sys

import pytest

from cria import loop, probegate, proberun, repositorychecks as rc
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind
from gates_completion_helpers import Log, gates_completion_view, run_in_harness  # noqa: F401

TOOLS = [{"type": "function", "function": {"name": "exec_command", "parameters": {
    "type": "object", "properties": {"cmd": {"type": "string"}, "yield_time_ms": {"type": "integer"}}}}}]


def harness(tmp_path, monkeypatch, program, kind=ProbeKind.BuildCheck, argv=None):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "source.txt").write_text("source\n")
    cand = ProbeCandidate(kind, argv or [sys.executable, "-c", program], tmp_path, 100, 100,
                          ProbeCost.Cheap, False, False, False, "fixture", composed_by_cria=True)
    monkeypatch.setattr(proberun, "select_completion_probes", lambda root: [cand])


class Driver:
    def __init__(self, tmp_path, **state):
        self.tmp, self.log, self.messages = tmp_path, Log(), [{"role": "user", "content": "build it"}]
        self.state = loop.GuardState(**state)
        self.probes = rc.ProbeServices(lambda m: str(tmp_path), probegate.plan_gate, iter(f"call_{i}" for i in range(99)).__next__)
        self.evidence = rc.EvidenceServices(loop._read_tool_result, loop.read_gate, loop.gate_error_text,
                                            lambda f, m: loop.track_gate_progress(self.state, f, m))

    def source(self, **kw):
        return rc.Input({"tools": TOOLS, "messages": self.messages}, self.log, 5, workspace_root=str(self.tmp), **kw)

    def run(self, call, *, answer=True):
        import json
        cmd = json.loads(call["function"]["arguments"])["cmd"]
        self.messages.append({"role": "assistant", "tool_calls": [call]})
        if answer:
            self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": run_in_harness(cmd, self.tmp, "sh")})

    def resume(self):
        return rc.resume(self.source(), self.state, self.probes, self.evidence, rc.JudgmentServices(),
                         rc.ResumeHooks(rc.reissue, rc.replan))


def pump(d, first):
    """Deliver the check, then every continuation page the transport asks for, to the final periodic result."""
    d.run(first.call)
    for _ in range(20):
        out = d.resume()
        if out.pending_kind is not rc.PendingKind.PAGE:
            return out
        d.run(out.call)
    raise AssertionError("transport never settled")


def test_a_red_check_is_surfaced_in_the_checkers_words_then_a_green_one_clears_the_veto(tmp_path, monkeypatch):
    harness(tmp_path, monkeypatch, "import sys; print('FAILED test_cart.py::test_total - assert 2 == 3'); sys.exit(1)")
    d = Driver(tmp_path, coder_turns=rc.GATE_EVERY_CODER_TURNS - 1)
    assert d.state.coder_turns == 14
    assert rc.admit(d.source(), d.state, d.probes).status is rc.Status.NOT_DUE
    assert rc.admit(rc.Input({"tools": TOOLS, "messages": []}, d.log, 4), loop.GuardState(coder_turns=99), d.probes).status is rc.Status.NOT_SELECTED
    rc.observe_acting_turn(d.state, acting=False)
    rc.observe_acting_turn(d.state, acting=True)
    first = rc.admit(d.source(), d.state, d.probes)
    assert (first.status, first.pending_kind, d.state.periodic_probe, d.state.coder_turns) == (
        rc.Status.PENDING, rc.PendingKind.CHECK, True, 0)
    out = pump(d, first)
    assert "test_total" in out.text and "assert 2 == 3" in out.text
    assert d.state.last_gate_red and not d.state.periodic_probe and not d.state.awaiting_probe
    assert [n for n, _ in d.log.events if n.startswith("loop.periodic_gate")] == ["loop.periodic_gate", "loop.periodic_gate_result"]

    harness(tmp_path, monkeypatch, "print('all fine')")
    d.state.coder_turns = 15
    d.log.events.clear()
    second = rc.admit(d.source(), d.state, d.probes)
    out = pump(d, second)
    assert out.status is rc.Status.SILENT and out.text is None and not d.state.last_gate_red


def test_a_compacted_history_reissues_the_check_twice_then_gives_up_rather_than_reading_silence_as_green(tmp_path, monkeypatch):
    harness(tmp_path, monkeypatch, "print('ok')")
    d = Driver(tmp_path, coder_turns=15)
    first = rc.admit(d.source(), d.state, d.probes)
    d.run(first.call, answer=False)                                            # the result vanished with the history rewrite
    kinds = []
    for _ in range(6):
        out = rc.reissue(d.source(rewritten=True), d.state, d.probes, d.evidence)
        kinds.append((out.status, out.pending_kind))
        if out.call:
            d.run(out.call, answer=False)
    P, R = rc.PendingKind.REWRITE_POLL, rc.PendingKind.REISSUE
    assert kinds == [(rc.Status.PENDING, P)] * 2 + [(rc.Status.PENDING, R)] * 2 + [(rc.Status.UNAVAILABLE, None)] * 2
    assert d.state.probe_reissues == 2
    no_shell = Driver(tmp_path, coder_turns=15)
    no_shell.messages = d.messages
    src = rc.Input({"tools": [], "messages": []}, no_shell.log, 5)
    assert rc.admit(src, no_shell.state, no_shell.probes).status is rc.Status.UNAVAILABLE and no_shell.state.coder_turns == 0


def test_a_passing_suite_that_shrinks_is_called_out_on_the_next_check_in(tmp_path, monkeypatch):
    """A green run that lost tests is not green: the per-command passing high-water mark turns 3 -> 2 into a veto."""
    (tmp_path / "test_cart.py").write_text("def test_a(): pass\ndef test_b(): pass\ndef test_c(): pass\n")
    harness(tmp_path, monkeypatch, "", ProbeKind.Test, [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"])
    d = Driver(tmp_path, coder_turns=15)
    assert pump(d, rc.admit(d.source(), d.state, d.probes)).status is rc.Status.SILENT
    assert list(d.state.tests_passed_high.values()) == [3] and not d.state.last_gate_testless
    (tmp_path / "test_cart.py").write_text("def test_a(): pass\ndef test_b(): pass\n")
    d.state.coder_turns = 15
    out = pump(d, rc.admit(d.source(), d.state, d.probes))
    assert out.status is rc.Status.OBSERVED and "3" in out.text and "2" in out.text
    assert d.state.last_regression[1:] == (3, 2) and [n for n, _ in d.log.events].count("loop.tests_regressed") == 1
