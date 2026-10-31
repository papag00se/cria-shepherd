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

def test_an_end_to_end_requirement_is_judged_on_the_executed_test_source():
    event = pt.observe(cand(pd.Ecosystem.JsTs, "npm test"), "Tests: 1 passed", 0)
    event = replace(event, test_sources=(pt.TestSourceEvidence("test/cli.js", "spawn CLI and assert exit"),))
    for verdict, status in (("PROVEN", S.PERMITTED), ("UNVERIFIED", S.CONTRADICTED), ("UNDECIDABLE", S.WITHHELD)):
        questions = Questions("E2E_REQUIRED", verdict)
        result = ca.test_participation(ca.ParticipationInput(TASK, lambda: pt.report([event]), questions))
        assert result.status is status and questions.phases == ["test-e2e-requirement", "test-e2e-participation"], verdict
