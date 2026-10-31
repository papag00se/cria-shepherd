"""Approval constraints preserve independent authorities and current refusal behavior."""
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from cria import completionapproval as policy, completionmeasure as measure, filefacts, loop, participation, prompts, shelltool
from tests.test_a_required_test_unknown_cannot_complete import _candidate, _capture_view
from cria import probediscovery


class Questions:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.phases = []
        self.requests = []

    def closed(self, prompt, *, phase):
        self.phases.append(phase)
        self.requests.append((phase, prompt))
        return next(self.answers)

    def clean(self, raw):
        return raw

    def object(self, raw):
        return loop.extract_json_object(raw)

    def inspect_tests(self, system, user):
        self.phases.append("test-e2e-participation")
        self.requests.append(("test-e2e-participation", system, user))
        return next(self.answers)


TASK = "Write out.txt with exactly 4 bytes and a final line break."
EVIDENCE = filefacts.render([filefacts.FileFact("out.txt", b"abc", False)])


def extraction(**changes):
    value = dict(quote=TASK, file="out.txt", bytes=4, ends_with_line_break=True)
    value.update(changes)
    return json.dumps(value)


@pytest.mark.parametrize("answers,status,phases,text", [
    ([extraction(), '{"exact_bytes":4}'], policy.ApprovalStatus.CONTRADICTED,
     ["exact-form-requirement", "exact-form-bytes-confirm"], prompts.render("exact_form_unmet", facts=EVIDENCE)),
    ([extraction(), '{}', '{}'], policy.ApprovalStatus.WITHHELD,
     ["exact-form-requirement", "exact-form-bytes-confirm", "exact-form-bytes-confirm"], prompts.load("unverified_step")),
    (['{}', '{}'], policy.ApprovalStatus.WITHHELD,
     ["exact-form-requirement", "exact-form-requirement"], prompts.load("unverified_step")),
    ([extraction(quote="invented requirement")], policy.ApprovalStatus.PERMITTED,
     ["exact-form-requirement"], ""),
    ([extraction(file="other.txt")], policy.ApprovalStatus.PERMITTED,
     ["exact-form-requirement"], ""),
    ([extraction(bytes=True), '{"states":"ends_with_break"}'], policy.ApprovalStatus.CONTRADICTED,
     ["exact-form-requirement", "exact-form-ending-confirm"], prompts.render("exact_form_unmet", facts=EVIDENCE)),
    ([extraction(), '{"exact_bytes":null}', '{"states":"ends_with_break"}'], policy.ApprovalStatus.CONTRADICTED,
     ["exact-form-requirement", "exact-form-bytes-confirm", "exact-form-ending-confirm"], prompts.render("exact_form_unmet", facts=EVIDENCE)),
    ([extraction(), '{"exact_bytes":null}', '{"states":"none"}'], policy.ApprovalStatus.PERMITTED,
     ["exact-form-requirement", "exact-form-bytes-confirm", "exact-form-ending-confirm"], ""),
])
def test_exact_form_matches_original_text_and_retry_count(answers, status, phases, text):
    questions = Questions(answers)
    result = policy.EXACT_FORM.execute(policy.ExactFormInput(TASK, lambda: EVIDENCE,
                                                           lambda a, b: a == b, questions))
    assert result.status is status
    # Accepted legacy cases survive removal of the old Loop policy body. The
    # oracle is the declared outcome/request sequence, never another execution.
    assert result.text == text
    assert questions.phases == phases
    expected_prompts = {
        "exact-form-requirement": prompts.render("exact_form_requirement", task=TASK, facts=EVIDENCE),
        "exact-form-bytes-confirm": prompts.render("exact_form_bytes_confirm", quote=TASK),
        "exact-form-ending-confirm": prompts.render("exact_form_ending_confirm", quote=TASK),
    }
    assert questions.requests == [(phase, expected_prompts[phase]) for phase in phases]
    assert result.blocks is (status in (policy.ApprovalStatus.WITHHELD, policy.ApprovalStatus.CONTRADICTED))


@pytest.mark.parametrize("support", [participation.Support.ABSENT, participation.Support.FAILED])
def test_measured_nonparticipation_is_not_unknown(support):
    phase = participation.PhaseParticipation(participated=False) if support is participation.Support.ABSENT else participation.PhaseParticipation(passed=False)
    event = participation.ProbeParticipation(None, ("test",), 0, True, test=phase)
    report = participation.ParticipationReport((event,))
    result = policy.test_participation(policy.ParticipationInput(TASK, lambda: report, Questions(["REQUIRED"])))
    assert result.status is policy.ApprovalStatus.CONTRADICTED


def test_no_report_is_not_an_unknown_judgment():
    questions = Questions([])
    result = policy.test_participation(policy.ParticipationInput(TASK, lambda: None, questions))
    assert result.status is policy.ApprovalStatus.NO_CONSTRAINT
    assert not questions.phases


def test_no_counts_never_asks():
    questions = Questions([])
    result = policy.exact_form(policy.ExactFormInput(TASK, lambda: "no measurements", lambda a,b: True, questions))
    assert result.status is policy.ApprovalStatus.NO_CONSTRAINT
    assert not questions.phases


@pytest.mark.parametrize("proven,answers,status", [
    (False, ["REQUIRED"], policy.ApprovalStatus.WITHHELD),
    (False, ["NOT_REQUIRED"], policy.ApprovalStatus.NO_CONSTRAINT),
    (False, ["nonsense"], policy.ApprovalStatus.WITHHELD),
    (True, ["NOT_REQUIRED"], policy.ApprovalStatus.PERMITTED),
    (True, ["E2E_REQUIRED"], policy.ApprovalStatus.WITHHELD),
    (True, [""], policy.ApprovalStatus.WITHHELD),
])
def test_participation_matches_original_barrier(proven, answers, status):
    kind = probediscovery.ProbeKind.Test if proven else probediscovery.ProbeKind.SyntaxCheck
    report = participation.report([participation.observe(_candidate(kind, "npm test"), "Tests: 1 passed", 0)])
    questions = Questions(answers)
    result = policy.PARTICIPATION.execute(policy.ParticipationInput(TASK, lambda: report, questions))
    assert result.status is status
    assert result.text == ""
    assert result.blocks is (status is policy.ApprovalStatus.WITHHELD)
    phase = "test-e2e-requirement" if proven else "test-participation-requirement"
    expected_prompt = (prompts.render("test_e2e_requirement", task=TASK) if proven else
                       prompts.render("test_participation_requirement", task=TASK,
                                      participation=participation.render_for_judge(report)))
    assert questions.phases == [phase]
    assert questions.requests == [(phase, expected_prompt)]


def services(root=""):
    return measure.MeasurementServices(
        frozenset(loop._WRITE_TOOLS), frozenset(loop.writeproxy_names), frozenset(loop.writeproxy._EDIT_NAMES),
        loop.denial.unlanded_call_ids, shelltool.writes_something, loop.writeproxy._command_of,
        loop._args_of, loop._path_of_args, lambda a,b: loop._same_workspace_path(a,b,root),
        lambda: loop.wsview.current(root) if root else None)


def action(name, args, tid):
    return [{"role":"assistant", "tool_calls":[{"id":tid,"function":{"name":name,"arguments":json.dumps(args)}}]},
            {"role":"tool", "tool_call_id":tid,"content":"ok","cria_result_outcome":"landed"}]    # the write program's typed fact


@pytest.mark.parametrize("tail", [[], action("edit_file", {"path":"out.txt", "old_string":"a", "new_string":"b"}, "e"),
                                   action("shell", {"command":"echo changed > out.txt"}, "s")])
def test_measurement_lifecycle_matches_current_mutation_invalidation(tail):
    messages = action("write_file", {"path":"out.txt", "content":"雪\r\n"}, "w") + tail
    before = deepcopy(messages)
    facts = measure.written_file_facts(messages, services())
    expected = [] if tail else [filefacts.FileFact("out.txt", b"\xe9\x9b\xaa\r\n", False)]
    assert facts == expected
    assert measure.written_file_facts(messages, services()) == expected
    assert messages == before
    if not tail:
        assert facts[0].raw == b"\xe9\x9b\xaa\r\n"
    else:
        assert not facts


@pytest.mark.parametrize("verdict,status", [("PROVEN", policy.ApprovalStatus.PERMITTED),
                                            ("UNVERIFIED", policy.ApprovalStatus.CONTRADICTED),
                                            ("UNDECIDABLE", policy.ApprovalStatus.WITHHELD)])
def test_inspected_executable_reach_has_separate_authority(verdict, status):
    event = participation.observe(_candidate(probediscovery.ProbeKind.Test, "npm test"), "Tests: 1 passed", 0)
    event = replace(event, test_sources=(participation.TestSourceEvidence("test/cli.js", "spawn CLI and assert exit"),))
    report = participation.report([event])
    questions = Questions(["E2E_REQUIRED", verdict])
    result = policy.test_participation(policy.ParticipationInput(TASK, lambda: report, questions))
    assert result.status is status
    assert questions.phases == ["test-e2e-requirement", "test-e2e-participation"]
    assert result.blocks is (status in (policy.ApprovalStatus.CONTRADICTED, policy.ApprovalStatus.WITHHELD))
    assert result.text == ""
    assert questions.requests == [
        ("test-e2e-requirement", prompts.render("test_e2e_requirement", task=TASK)),
        ("test-e2e-participation", prompts.load("test_e2e_participation"),
         prompts.render("test_e2e_participation", task=TASK, participation=participation.render_for_judge(report))),
    ]


def test_current_workspace_bytes_win_but_later_native_edit_silences_them():
    root = "/workspace"
    view = _capture_view(root, {"out.txt": "雪\r\n"}, session="approval-measure")
    adapters = replace(services(root), view=lambda: view)
    messages = action("write_file", {"path":"out.txt", "content":"old"}, "w")
    facts = policy.EXACT_FORM.measure(messages, adapters)
    assert facts == [filefacts.FileFact("out.txt", "雪\r\n".encode(), True)]
    assert filefacts.parse(filefacts.render(facts)) == [("out.txt", 5, True)]
    messages += action("edit_file", {"path":"out.txt", "old_string":"雪", "new_string":"ice"}, "e")
    assert not policy.EXACT_FORM.measure(messages, adapters)


def test_unusable_workspace_does_not_mislabel_written_bytes_as_disk():
    root = "/workspace"
    view = _capture_view(root, {"out.txt": "old"}, session="approval-stale")
    view.note_a_mutator_ran()
    messages = action("write_file", {"path":"out.txt", "content":"new"}, "w")
    assert policy.EXACT_FORM.measure(messages, replace(services(root), view=lambda: view)) == [
        filefacts.FileFact("out.txt", b"new", False)]


def test_pending_call_is_not_measured():
    messages = action("write_file", {"path":"out.txt", "content":"abc"}, "w")[:1]
    assert measure.written_file_facts(messages, services()) == []
