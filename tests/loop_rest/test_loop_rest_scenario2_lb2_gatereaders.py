"""What cria reads back from a completion-gate probe and how a judge's verdict reaches the coder: the gate's blocking text for every
shape of report, the operator-only log lines read_gate must never drop, the verdict nudge's compatibility arms, the verify dump and
the SSE re-streaming of a finished completion."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cria import loop, probegate, probeparse
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind
from cria.proberun import ProbeReport


class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def report(kind, command, exit_code, summary="", findings=()):
    cand = ProbeCandidate(kind=kind, command=command.split(), working_dir=Path("/tmp"), confidence=90, expected_value=80,
                          cost=ProbeCost.Cheap, mutates_code=False, may_hang=False, may_need_services=False, reason="t")
    res = probeparse.ProbeResult(command=command, exit_code=exit_code, summary=summary, findings=list(findings))
    return ProbeReport(project_type=["x"], selected=[cand], results=[res])


@pytest.mark.parametrize("kind,exit_code,green", [(ProbeKind.Test, 0, True), (ProbeKind.Test, 1, False), (ProbeKind.Lint, 0, False)])
def test_the_gate_test_probe_is_green_only_when_a_test_kind_probe_exited_zero(kind, exit_code, green):
    assert loop._gate_test_green(SimpleNamespace(report=report(kind, "run it", exit_code))) is green
    assert loop._gate_test_green(SimpleNamespace(report=None)) is False


def test_the_blocking_text_names_a_located_failure_an_unlocated_one_both_or_nothing():
    located = probeparse.Finding("src/a.py", 3, None, "NameError: x")
    assert loop.gate_error_text(SimpleNamespace(ran=False)) == ""
    clean = SimpleNamespace(ran=True, report=report(ProbeKind.Test, "pytest -q", 0, "no problems reported"))
    assert loop.gate_error_text(clean) == ""
    findings = loop.gate_error_text(SimpleNamespace(ran=True, report=report(ProbeKind.Lint, "ruff .", 1, "1 problem", [located])))
    assert "src/a.py:3" in findings and "NameError: x" in findings
    bare = loop.gate_error_text(SimpleNamespace(ran=True, report=report(ProbeKind.Test, "pytest -q", 1, "AssertionError boom")))
    assert "$ pytest -q — AssertionError boom" in bare and "a specific line could not be parsed" in bare
    pointing = loop.gate_error_text(SimpleNamespace(ran=True, report=report(ProbeKind.Test, "go test", 2, "app_test.go:22: wrong")))
    assert "$ go test — app_test.go:22: wrong" in pointing and "could not be parsed" not in pointing and "at the line it names" in pointing
    both = report(ProbeKind.Test, "pytest -q", 1, "tests broke")
    cand = report(ProbeKind.Lint, "ruff .", 1, "1 problem", [located])
    both.selected += cand.selected
    both.results += cand.results
    text = loop.gate_error_text(SimpleNamespace(ran=True, report=both))
    assert "src/a.py:3" in text and "$ pytest -q — tests broke" in text


def test_a_refused_swept_or_offline_gate_is_logged_for_the_operator_and_a_missing_plan_reads_as_not_run(monkeypatch):
    log = Log()
    assert loop.read_gate(None, "anything", log) == probegate.GateOutcome(ran=False) and not log.events
    outcome = probegate.GateOutcome(ran=False, refused="sandbox says no", swept=["a", "b"], offline_ran=False,
                                    report=report(ProbeKind.Test, "pytest -q", 0))
    monkeypatch.setattr(probegate, "interpret_gate", lambda plan, text, rlog: outcome)
    assert loop.read_gate(object(), "", log) is outcome
    assert log.events == [("loop.gate_refused", {"level": "warn", "reason": "sandbox says no"}),
                          ("loop.gate_swept", {"paths": 2, "sample": ["a", "b"]}),
                          ("loop.gate_offline", {"ran": False, "test_green": True})]


@pytest.mark.parametrize("checks,is_test", [
    ("", False), ("3 failed, 1 passed", True), ("FAILED tests/test_x.py::t", True), ("--- FAIL: TestCart (0.00s)", True),
    ("cart_test.go:22: wrong total", True), ("src/main.rs:4:5: error", False), ("setup.py:1: bad", False)])
def test_a_finding_is_about_a_test_only_by_a_runner_tally_or_a_test_file_path(checks, is_test):
    assert loop._is_test_finding(checks) is is_test


@pytest.mark.parametrize("obj,done,kwargs,text,action", [
    ({"reason": " fine "}, True, {}, "fine", ""),
    ({"reason": "missing x", "proposed_fix": "None"}, False, {}, "missing x", ""),               # a textual null is no fix
    ({"reason": "r", "proposed_fix": "POST /handles/resolve"}, False, {"routes": "/handles/{handle}"}, "r", ""),   # a route in no spec
    ({"reason": "r", "proposed_fix": "write the README"}, False, {}, "r", "write the README"),    # no log: nothing to vet it with
])
def test_the_compatibility_verdict_nudge_keeps_the_reason_and_delivers_only_a_fix_it_could_vet(obj, done, kwargs, text, action):
    nudge = loop._verdict_nudge(obj, done, **kwargs)
    assert nudge.evidence == text and nudge.action == action
    assert str(nudge) == (text + "\nProposed fix: " + action if action else text)


def test_the_verify_dump_names_the_verdict_keeps_the_raw_reply_and_never_breaks_the_loop(tmp_path):
    loop._dump_verify(None, "k", 1, 2, "s", "sys", "usr", True, "ok")                           # no run folder: silent
    loop._dump_verify(tmp_path / "run", "sess-1", 2, 5, "write app.py", "SYS-TEXT", "USER-TEXT", False, "not there", "garbled")
    loop._dump_verify(tmp_path / "run", "sess-1", 3, 5, "step", "S", "U", True, "ok")
    first, second = sorted((tmp_path / "run").glob("verify-step-0*.md"), key=lambda p: p.name)
    text = first.read_text()
    assert text.startswith("# Step 2/5 — verdict: NOT DONE") and "garbled" in text and "SYS-TEXT" in text and "USER-TEXT" in text
    assert "(empty / call failed)" in second.read_text() and "verdict: DONE" in second.read_text()
    (tmp_path / "file").write_text("x")
    loop._dump_verify(tmp_path / "file", "k", 1, 1, "s", "a", "b", True, "r")                   # the folder is a file: swallowed
    assert (tmp_path / "file").read_text() == "x"


def test_a_finished_completion_streams_back_as_sse_with_its_calls_and_the_evidence_it_carries():
    calls = [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]
    frames = list(loop.completion_to_sse({"id": "x", "model": "m", "choices": [{"message": {"content": "hi", "tool_calls": calls}}]}))
    payloads = [json.loads(f[len(b"data: "):]) for f in frames[:-1]]
    assert frames[-1] == b"data: [DONE]\n\n"
    assert payloads[0]["choices"][0]["delta"] == {"role": "assistant"} and payloads[1]["choices"][0]["delta"] == {"content": "hi"}
    assert payloads[2]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "read_file"
    assert payloads[-1]["choices"][0]["finish_reason"] == "tool_calls" and payloads[0]["model"] == "m"
    bare = [json.loads(f[6:]) for f in loop.completion_to_sse({"choices": [{"message": {"content": "plain"}}]}) if f != b"data: [DONE]\n\n"]
    assert bare[-1]["choices"][0]["finish_reason"] == "stop" and len(bare) == 3


def test_the_ground_truth_the_coder_gets_is_the_failure_or_a_neutral_clean_note_and_silence_when_less_was_read_than_asked():
    clean = probegate.GateOutcome(ran=True, report=report(ProbeKind.Test, "pytest -q", 0, "no problems reported"))
    unlaunched = probegate.GateOutcome(ran=True, report=report(ProbeKind.Test, "pytest -q", None, "failed to launch: not found"))
    failed = probegate.GateOutcome(ran=True, report=report(ProbeKind.Test, "pytest -q", 1, "boom"))
    assert loop.guard_ground_truth(probegate.GateOutcome(ran=False)) == ""
    assert loop.guard_ground_truth(unlaunched) == ""                                  # cria's own setup gap is never a signal to the model
    assert loop.guard_ground_truth(clean) == loop.prompts.load("ground_truth_clean") != ""
    assert "$ pytest -q — boom" in loop.guard_ground_truth(failed)


def test_the_check_note_names_what_was_written_since_the_checks_ran_newest_first_and_claims_nothing_else():
    gate = {"role": "tool", "tool_call_id": "g", "content": f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\nx"}
    write = lambda cid, path: {"role": "assistant", "tool_calls": [{"id": cid, "function": {"name": "write_file", "arguments": json.dumps({"path": path, "content": "1"})}}]}   # noqa: E731
    msgs = [write("1", "old.py"), gate, write("2", "a.py"), write("3", "b.py"), write("4", "a.py"), "junk"]
    assert loop._writes_since_last_gate(msgs) == ["b.py", "a.py"] and loop._writes_since_last_gate(msgs, 1) == ["b.py"]
    assert loop._writes_since_last_gate(msgs[:1]) == ["old.py"]                              # no gate seen: every write since the start
    assert loop._checks_ran_before([]) == "" and loop._checks_ran_before(["a.py"]) == " before your change to a.py"
    assert loop._checks_ran_before(["a.py", "b.py", "c.py"]) == " before your changes to a.py, b.py, c.py"
    assert loop._gate_commands("header\n$ pytest -q — 2 failed\n$ ruff .\nnoise $ x") == ["pytest -q", "ruff ."]
    shown = {"messages": [{"role": "user", "content": "the checks: FAILED x"}, {"role": "tool", "content": None}]}
    assert loop._checks_already_visible(shown, "FAILED x") and not loop._checks_already_visible(shown, "FAILED y") and loop._checks_already_visible(shown, "  ")
