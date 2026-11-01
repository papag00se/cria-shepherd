"""Pre-release approval keeps its authorities apart: measured bytes, the task's own words and executed-test evidence."""
import json
from dataclasses import replace

import pytest
from cria import completionapproval as ca, filefacts, loop, participation as pt
from cria import probediscovery as pd
from loop_orientation_helpers import local_workspace_view  # noqa: F401
from test_loop_orientation_participation import cand

TASK = "Write out.txt with exactly 4 bytes and a final line break."
EVIDENCE = filefacts.render([filefacts.FileFact("out.txt", b"abc", False)])     # measured: 3 bytes, no final break
S = ca.ApprovalStatus

class Questions:
    """Scripted closed questions; records the phase of every question asked."""
    def __init__(self, *answers):
        self.answers, self.phases = iter(answers), []

    def closed(self, prompt, *, phase):
        self.phases.append(phase)
        return next(self.answers)

    clean = staticmethod(lambda raw: raw)
    object = staticmethod(loop.extract_json_object)

    def inspect_tests(self, system, user):
        return self.closed(user, phase="test-e2e-participation")

def extraction(**changes):
    return json.dumps(dict(quote=TASK, file="out.txt", bytes=4, ends_with_line_break=True) | changes)

@pytest.mark.parametrize("answers,status,phases", [
    ([extraction(), '{"exact_bytes":4}'], S.CONTRADICTED, 2),             # the task says 4 bytes; disk has 3
    ([extraction(), "{}", "{}"], S.WITHHELD, 3),                          # an unreadable confirmation never approves
    ([extraction(quote="invented requirement")], S.PERMITTED, 1),         # a quote the task does not contain is no requirement
    ([extraction(bytes=3, ends_with_line_break=False)], S.PERMITTED, 1),   # the stated bytes ARE the measured bytes: nothing to confirm
    ([extraction(bytes=True, ends_with_line_break=False)], S.PERMITTED, 1),   # a JSON true is not a byte count
])
def test_exact_form_contradicts_only_a_grounded_requirement_against_measured_bytes(answers, status, phases):
    """A requirement counts only if quoted from the task and about a file cria measured; unreadable answers withhold."""
    questions = Questions(*answers)
    result = ca.exact_form(ca.ExactFormInput(TASK, lambda: EVIDENCE, lambda a, b: a == b, questions))
    assert result.status is status and len(questions.phases) == phases
    assert result.blocks is (status is not S.PERMITTED) and ("out.txt" in result.text) is (status is S.CONTRADICTED)
    nothing = Questions()                                                 # no measurement, no question
    assert ca.exact_form(ca.ExactFormInput(TASK, lambda: "not measured", lambda a, b: True, nothing)).status \
        is S.NO_CONSTRAINT and not nothing.phases

@pytest.mark.parametrize("kind,answers,status", [
    (pd.ProbeKind.SyntaxCheck, ["REQUIRED"], S.WITHHELD),                  # unknown participation + required: held
    (pd.ProbeKind.SyntaxCheck, ["NOT_REQUIRED"], S.NO_CONSTRAINT),
    (pd.ProbeKind.Test, ["E2E_REQUIRED"], S.WITHHELD),                     # required but no bound executed source: unverified
])
def test_a_required_test_is_released_only_by_proven_participation_and_a_readable_answer(kind, answers, status):
    report = pt.report([pt.observe(cand(pd.Ecosystem.JsTs, "npm test", kind), "Tests: 1 passed", 0)])
    result = ca.PARTICIPATION.execute(ca.ParticipationInput(TASK, lambda: report, Questions(*answers)))
    assert result.status is status
    assert ca.test_participation(ca.ParticipationInput(TASK, lambda: None, Questions())).status is S.NO_CONSTRAINT

def test_measured_non_participation_is_contradicted_not_merely_unknown():
    for phase in (pt.PhaseParticipation(participated=False), pt.PhaseParticipation(passed=False)):
        report = pt.ParticipationReport((pt.ProbeParticipation(None, ("test",), 0, True, test=phase),))
        assert ca.test_participation(ca.ParticipationInput(TASK, lambda: report, Questions("REQUIRED"))).status is S.CONTRADICTED

SCRIPT_TASK = "Create test_calc.py that prints OK, and run `python3 test_calc.py` to confirm it prints OK."
NO_TESTS = pt.report([pt.observe(cand(pd.Ecosystem.Python, "python3 -m pytest -q"), "no tests ran in 0.00s", 5)])

ASKED = ["test-participation-requirement", "coder-run-executes-required-test"]
RUN = ca.ShellRun("python3 test_calc.py", 0, "OK\n")

@pytest.mark.parametrize("support,answers,runs,status,asked", [
    # The gate's runner collected nothing (support absent) but the coder's own run is the one the task named.
    ("absent", ["REQUIRED", "1"], [RUN], S.PERMITTED, ASKED),
    ("absent", ["REQUIRED", "`2`"], [ca.ShellRun("ls", 0, ""), RUN], S.PERMITTED, ASKED),           # the number is what is read
    ("absent", ["REQUIRED", "1"], [ca.ShellRun("python3 test_calc.py", None, "OK\n")], S.PERMITTED, ASKED),   # a harness that reports no status: the judge saw the output
    ("absent", ["REQUIRED", "NONE"], [RUN], S.CONTRADICTED, ASKED),
    ("absent", ["REQUIRED", "1"], [ca.ShellRun("python3 test_calc.py", 1, "AssertionError\n")], S.CONTRADICTED, ASKED),   # the named run exited non-zero: measured, not judged
    ("absent", ["REQUIRED", "2"], [RUN], S.CONTRADICTED, ASKED),                                   # a number that is no run
    ("absent", ["REQUIRED", "0"], [RUN], S.CONTRADICTED, ASKED),
    ("absent", ["REQUIRED", ""], [RUN], S.CONTRADICTED, ASKED),                                    # unreadable: the block stands
    ("absent", ["REQUIRED", "YES"], [RUN], S.CONTRADICTED, ASKED),
    ("absent", ["REQUIRED"], [], S.CONTRADICTED, ASKED[:1]),                                       # nothing was run: no second question
    ("absent", ["NOT_REQUIRED"], [RUN], S.NO_CONSTRAINT, ASKED[:1]),
    ("failed", ["REQUIRED", "1"], [RUN], S.CONTRADICTED, ASKED[:1]),                               # a runner that reported failures is never released by a claim
    ("unknown", ["REQUIRED", "1"], [RUN], S.WITHHELD, ASKED[:1]),
])
def test_a_run_the_coder_made_releases_an_empty_runner_only_when_the_judge_names_it_and_it_did_not_fail(support, answers, runs, status, asked):
    """Item 29: the gate's own `pytest -q` collected nothing (exit 5) although the task named `python3 test_calc.py` and the
    coder ran exactly that. Only the empty-runner case (ABSENT) asks WHICH coder run is the required test; a named run that did
    not exit non-zero releases; any other answer, a failed run or no run keeps the block; FAILED/UNKNOWN support never consults the runs."""
    report = NO_TESTS if support == "absent" else pt.ParticipationReport((pt.ProbeParticipation(
        None, ("pytest",), 1, True, test=pt.PhaseParticipation(passed=False) if support == "failed" else pt.PhaseParticipation()),))
    assert report.support("test").value == support
    log, questions = Log(), Questions(*answers)
    seen = []
    questions.closed = lambda prompt, *, phase, _inner=questions.closed: (seen.append((phase, prompt)), _inner(prompt, phase=phase))[1]
    result = ca.test_participation(ca.ParticipationInput(SCRIPT_TASK, lambda: report, questions, log, lambda: tuple(runs)))
    assert result.status is status and [p for p, _ in seen] == asked
    if len(asked) == 2:
        prompt = seen[-1][1]
        assert SCRIPT_TASK in prompt and "[1] command:" in prompt and f"[{len(runs)}] command:" in prompt
        kind, fields = log.events[-1]
        assert kind == "loop.coder_run_executes_required_test" and fields["released"] is (status is S.PERMITTED) and fields["runs"] == len(runs)

def test_the_runs_put_to_the_question_are_bounded_and_every_cut_is_labelled():
    runs = tuple(ca.ShellRun(f"cmd{i}", None if i == 0 else i, "y" * 1000 if i == 19 else "") for i in range(20))
    text = ca.render_runs(runs)
    assert text.startswith("(5 earlier runs are not shown)") and "cmd4" not in text and "[6] command: cmd5" in text and "[20] command: cmd19" in text
    assert "output (first 600 of 1,000 characters; the rest is not shown)" in text and text.count("y") == 600
    assert "exit status: not reported" in ca.render_runs(runs[:1]) and "(nothing printed)" in ca.render_runs(runs[:1])

def test_an_end_to_end_requirement_is_judged_on_the_executed_test_source():
    event = pt.observe(cand(pd.Ecosystem.JsTs, "npm test"), "Tests: 1 passed", 0)
    event = replace(event, test_sources=(pt.TestSourceEvidence("test/cli.js", "spawn CLI and assert exit"),))
    for verdict, status in (("PROVEN", S.PERMITTED), ("UNVERIFIED", S.CONTRADICTED), ("UNDECIDABLE", S.WITHHELD)):
        questions = Questions("E2E_REQUIRED", verdict)
        result = ca.test_participation(ca.ParticipationInput(TASK, lambda: pt.report([event]), questions))
        assert result.status is status and questions.phases == ["test-e2e-requirement", "test-e2e-participation"], verdict

class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

def test_every_requirement_judgement_is_logged_with_what_it_actually_decided():
    """The events are the metrics: required / unknown / verdict must carry the real answer (mutation survivors: log-only branches)."""
    def run(kind, answers, sources=()):
        log = Log()
        event = replace(pt.observe(cand(pd.Ecosystem.JsTs, "npm test", kind), "Tests: 1 passed", 0), test_sources=sources)
        ca.test_participation(ca.ParticipationInput(TASK, lambda: pt.report([event]), Questions(*answers), log))
        return log.events
    assert run(pd.ProbeKind.SyntaxCheck, ["REQUIRED"])[0][1]["required"] is True
    assert run(pd.ProbeKind.SyntaxCheck, ["NOT_REQUIRED"])[0][1]["required"] is False
    assert run(pd.ProbeKind.SyntaxCheck, [""])[0][1]["required"] == "unknown"
    assert run(pd.ProbeKind.Test, ["E2E_REQUIRED"]) == [("loop.test_e2e_requirement", dict(required=True)),
                                                         ("loop.test_e2e_participation", dict(verdict="unverified-source"))]
    assert run(pd.ProbeKind.Test, ["NOT_REQUIRED"]) == [("loop.test_e2e_requirement", dict(required=False))]
    assert run(pd.ProbeKind.Test, [""]) == [("loop.test_e2e_requirement", dict(required="unknown"))]
    source = (pt.TestSourceEvidence("test/cli.js", "spawn CLI and assert exit"),)
    assert run(pd.ProbeKind.Test, ["E2E_REQUIRED", "PROVEN"], source)[-1] == ("loop.test_e2e_participation", dict(verdict="PROVEN"))
    assert run(pd.ProbeKind.Test, ["E2E_REQUIRED", ""], source)[-1] == ("loop.test_e2e_participation", dict(verdict="unknown"))

def measuring(root, view):
    """The exact-form source's measurement services over the real loop adapters and one workspace view."""
    from cria import completionmeasure as cm, shelltool
    return cm.MeasurementServices(
        frozenset(loop._WRITE_TOOLS), frozenset(loop.writeproxy_names), frozenset(loop.writeproxy._EDIT_NAMES),
        loop.denial.unlanded_call_ids, shelltool.writes_something, loop.writeproxy._command_of, loop._args_of,
        loop._path_of_args, lambda a, b: loop._same_workspace_path(a, b, root), lambda: view)

def landed(name, args, tid):
    return [{"role": "assistant", "tool_calls": [{"id": tid, "function": {"name": name, "arguments": json.dumps(args)}}]},
            {"role": "tool", "tool_call_id": tid, "content": "ok", "cria_result_outcome": "landed"}]

def test_the_current_disk_bytes_outrank_what_was_written_until_a_later_edit_or_stale_view_silences_them(tmp_path):
    """The measured counts a refusal quotes are the CURRENT file's: the surveyed disk wins over the written payload, a later
    native edit makes the survey stale for that file (silence, never the old bytes), and a view known to be stale never lends
    its 'on disk' label to bytes that were only written."""
    import subprocess
    from cria import wsview
    (tmp_path / "out.txt").write_bytes("雪\r\n".encode())
    view = wsview.View(str(tmp_path), "approval")

    def survey():                                     # the harness runs cria's own survey block; the view ingests its reply
        shown = subprocess.run(["bash", "-lc", wsview.survey_command("approval", cd=str(tmp_path))], capture_output=True, text=True).stdout
        assert wsview.apply_survey(view, wsview.strip_survey(shown)[1])
    survey()
    adapters, write = measuring(str(tmp_path), view), landed("write_file", {"path": "out.txt", "content": "old"}, "w")
    assert ca.EXACT_FORM.measure(write, adapters) == [filefacts.FileFact("out.txt", b"old", False)]   # bytes not yet delivered: as written
    survey()                                          # ...the first measurement asked for them; the next survey brings them
    facts = ca.EXACT_FORM.measure(write, adapters)
    assert facts == [filefacts.FileFact("out.txt", "雪\r\n".encode(), True)]                  # disk bytes, not "old"
    assert filefacts.parse(filefacts.render(facts)) == [("out.txt", 5, True)]
    edit = landed("edit_file", {"path": "out.txt", "old_string": "雪", "new_string": "ice"}, "e")
    assert ca.EXACT_FORM.measure(write + edit, adapters) == []                                # the survey predates this edit
    view.note_a_mutator_ran()
    assert ca.EXACT_FORM.measure(write, adapters) == [filefacts.FileFact("out.txt", b"old", False)]   # stale view: written, not "on disk"
