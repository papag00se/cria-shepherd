"""Separate pre-release constraints; evidence providers never own approval.

The caller selects definitions before invoking these lazy inputs. No judgment is
cached, and no task/session state is changed here. Closed questions and inspecting
critic calls are supplied by the existing shared reader, not reimplemented here.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from . import filefacts, participation, prompts
from .assistcontract import Policy, Reference
from .completionmeasure import MeasurementServices, written_file_facts


class ApprovalStatus(Enum):
    NO_CONSTRAINT = "no-constraint"
    WITHHELD = "withheld"
    CONTRADICTED = "contradicted"
    PERMITTED = "permitted"


@dataclass(frozen=True)
class ApprovalResult:
    status: ApprovalStatus
    text: str = ""

    @property
    def blocks(self) -> bool:
        return self.status in (ApprovalStatus.WITHHELD, ApprovalStatus.CONTRADICTED)


class Questions(Protocol):
    def closed(self, prompt: str, *, phase: str) -> str:
        """Existing ask_closed with retry_off=False and original role cleanup."""
        ...

    def clean(self, raw: str) -> str: ...
    def object(self, raw: str) -> dict | None: ...
    def inspect_tests(self, system: str, user: str) -> str:
        """Existing completion critic/text reader, test-e2e-participation phase,
        original workspace, JUDGE_MAX_TOKENS and force_think_off=True."""
        ...


class EventLog(Protocol):
    def emit(self, kind: str, **fields) -> None: ...


@dataclass(frozen=True)
class ExactFormInput:
    task: str
    evidence: Callable[[], str]
    same_path: Callable[[str, str], bool]
    questions: Questions
    log: EventLog | None = None


@dataclass(frozen=True)
class ParticipationInput:
    task: str
    report: Callable[[], participation.ParticipationReport | None]
    questions: Questions
    log: EventLog | None = None


def exact_form(source: ExactFormInput) -> ApprovalResult:
    evidence = source.evidence()
    facts = filefacts.extract(evidence)
    if not facts:
        return ApprovalResult(ApprovalStatus.NO_CONSTRAINT)

    def ask(name: str, need: tuple = (), **tokens) -> dict | None:
        for _ in range(2):
            raw = source.questions.closed(prompts.render(name, **tokens), phase=name.replace("_", "-"))
            got = source.questions.object(source.questions.clean(raw))
            if isinstance(got, dict) and set(need) <= got.keys():
                return got
        return None

    obj = ask("exact_form_requirement", need=("bytes", "ends_with_line_break"), task=source.task, facts=facts)
    if obj is None:
        if source.log is not None:
            source.log.emit("loop.exact_form_requirement", contradicted="unknown")
        return ApprovalResult(ApprovalStatus.WITHHELD, prompts.load("unverified_step"))
    quote = " ".join(str(obj.get("quote") or "").split())
    grounded = bool(quote) and quote in " ".join(source.task.split())
    want_file = str(obj.get("file") or "").strip()
    measured = next(((n, e) for p, n, e in filefacts.parse(evidence)
                     if want_file and source.same_path(p, want_file)), None)
    contradicted = unreadable = False
    if grounded and measured is not None:
        n, ends = measured
        want_bytes, want_end = obj.get("bytes"), obj.get("ends_with_line_break")
        if isinstance(want_bytes, int) and not isinstance(want_bytes, bool) and want_bytes != n:
            said = ask("exact_form_bytes_confirm", need=("exact_bytes",), quote=quote)
            if said is None:
                unreadable = True
            else:
                fixed = said["exact_bytes"]
                contradicted = (isinstance(fixed, int) and not isinstance(fixed, bool)
                                and fixed == want_bytes)
        if isinstance(want_end, bool) and want_end != ends and not contradicted and not unreadable:
            said = ask("exact_form_ending_confirm", need=("states",), quote=quote)
            if said is None:
                unreadable = True
            else:
                contradicted = said.get("states") == ("ends_with_break" if want_end else "ends_without_break")
    if source.log is not None:
        source.log.emit("loop.exact_form_requirement", contradicted=contradicted, grounded=grounded,
                        counted=measured is not None, unreadable=unreadable)
    if unreadable:
        return ApprovalResult(ApprovalStatus.WITHHELD, prompts.load("unverified_step"))
    return ApprovalResult(ApprovalStatus.CONTRADICTED, prompts.render("exact_form_unmet", facts=facts)) if contradicted else ApprovalResult(ApprovalStatus.PERMITTED)


def test_participation(source: ParticipationInput) -> ApprovalResult:
    report = source.report()
    if report is None:
        return ApprovalResult(ApprovalStatus.NO_CONSTRAINT)
    support = report.support("test")
    facts = participation.render_for_judge(report)
    if support is not participation.Support.PROVEN:
        answer = source.questions.closed(
            prompts.render("test_participation_requirement", task=source.task, participation=facts),
            phase="test-participation-requirement").strip().upper()
        if source.log is not None:
            source.log.emit("loop.test_participation_requirement", support=support.value,
                            required=(answer == "REQUIRED") if answer else "unknown")
        return ApprovalResult(ApprovalStatus.NO_CONSTRAINT if answer == "NOT_REQUIRED" else
                              ApprovalStatus.CONTRADICTED if answer == "REQUIRED" and support in
                              (participation.Support.ABSENT, participation.Support.FAILED) else ApprovalStatus.WITHHELD)
    requirement = source.questions.closed(prompts.render("test_e2e_requirement", task=source.task),
                                          phase="test-e2e-requirement").strip().upper()
    if source.log is not None:
        source.log.emit("loop.test_e2e_requirement", required=(requirement == "E2E_REQUIRED") if requirement else "unknown")
    if requirement == "NOT_REQUIRED":
        return ApprovalResult(ApprovalStatus.PERMITTED)
    if requirement != "E2E_REQUIRED":
        return ApprovalResult(ApprovalStatus.WITHHELD)
    sources = report.executed_test_sources()
    if not sources or any(item.body is None for item in sources):
        if source.log is not None:
            source.log.emit("loop.test_e2e_participation", verdict="unverified-source")
        return ApprovalResult(ApprovalStatus.WITHHELD)
    verdict = source.questions.inspect_tests(
        prompts.load("test_e2e_participation"),
        prompts.render("test_e2e_participation", task=source.task, participation=facts)).strip().upper()
    if source.log is not None:
        source.log.emit("loop.test_e2e_participation", verdict=verdict or "unknown")
    return ApprovalResult(ApprovalStatus.PERMITTED if verdict == "PROVEN" else
                          ApprovalStatus.CONTRADICTED if verdict == "UNVERIFIED" else ApprovalStatus.WITHHELD)


@dataclass(frozen=True)
class ExactFormDefinition:
    policy: Policy
    execute: Callable[[ExactFormInput], ApprovalResult]
    measure: Callable[[list[dict], MeasurementServices], list[filefacts.FileFact]]


@dataclass(frozen=True)
class ParticipationDefinition:
    policy: Policy
    execute: Callable[[ParticipationInput], ApprovalResult]


PARTICIPATION = ParticipationDefinition(
    Policy("task-required-test-participation", "completion-approval", 4, family_id="F43",
           prompts=("test_participation_requirement", "test_e2e_requirement", "test_e2e_participation"),
           services=("lazy-gate-participation", "closed-question", "inspecting-critic"),
           hooks=(Reference("cria/loop.py", "judge_satisfaction"),),
           regressions=(
               Reference("tests/loop_orientation/test_loop_orientation_completion_approval.py", "test_a_required_test_is_released_only_by_proven_participation_and_a_readable_answer"),
               Reference("tests/loop_orientation/test_loop_orientation_completion_approval.py", "test_an_end_to_end_requirement_is_judged_on_the_executed_test_source"),
               Reference("tests/loop_orientation/test_loop_orientation_completion_approval.py", "test_measured_non_participation_is_contradicted_not_merely_unknown")),
           migrated=False), test_participation)
EXACT_FORM = ExactFormDefinition(
    Policy("exact-file-form-approval", "completion-approval", 4, family_id="F35",
           prompts=("exact_form_requirement", "exact_form_bytes_confirm", "exact_form_ending_confirm", "exact_form_unmet", "unverified_step"),
           services=("lazy-file-facts", "workspace-path-equality", "closed-question", "critic-json-reader"),
           hooks=(Reference("cria/loop.py", "_satisfaction_evidence"),
                  Reference("cria/loop.py", "judge_satisfaction")),
           regressions=(
               Reference("tests/loop_orientation/test_loop_orientation_completion_approval.py", "test_exact_form_contradicts_only_a_grounded_requirement_against_measured_bytes"),
               Reference("tests_backup/test_completion_approval_policies.py", "test_measurement_lifecycle_matches_current_mutation_invalidation"),
               Reference("tests_backup/test_completion_approval_policies.py", "test_current_workspace_bytes_win_but_later_native_edit_silences_them")),
           migrated=False), exact_form, written_file_facts)
# Preserve current short-circuit order: participation first, exact form second.
PRE_RELEASE = (PARTICIPATION, EXACT_FORM)
