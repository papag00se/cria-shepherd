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
class ShellRun:
    """One command the coder ran and got a result for: ground truth gathered from the transcript."""
    command: str
    exit_code: int | None
    output: str


@dataclass(frozen=True)
class ParticipationInput:
    task: str
    report: Callable[[], participation.ParticipationReport | None]
    questions: Questions
    log: EventLog | None = None
    runs: Callable[[], tuple[ShellRun, ...]] = lambda: ()


RUNS_SHOWN = 15           # newest runs put to the question; the omission is labelled
OUTPUT_HEAD = 600         # characters of each run's output; the cut is labelled


def render_runs(runs: tuple[ShellRun, ...]) -> str:
    """The coder's runs as the question reads them, every reduction labelled."""
    shown = runs[-RUNS_SHOWN:]
    lines = [f"({len(runs) - len(shown)} earlier runs are not shown)"] if len(shown) < len(runs) else []
    for number, run in enumerate(shown, len(runs) - len(shown) + 1):
        status = "not reported" if run.exit_code is None else str(run.exit_code)
        head = run.output[:OUTPUT_HEAD].rstrip()
        cut = f" (first {OUTPUT_HEAD:,} of {len(run.output):,} characters; the rest is not shown)" \
            if len(run.output) > OUTPUT_HEAD else ""
        lines += [f"[{number}] command: {run.command}", f"    exit status: {status}", f"    output{cut}:",
                  *("      " + line for line in (head.splitlines() or ["(nothing printed)"]))]
    return "\n".join(lines)


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


def _coder_ran_required_test(source: ParticipationInput) -> bool:
    """The gate's own runner collected nothing, so the only evidence of the task's named run is the coder's
    own: ask ONE question of its recorded runs, WHICH of them executes the test the task requires (the
    reasoner judges what the task requires; code reads the exit status the harness measured). Released only
    when the named run exists and did not exit non-zero. An unreadable answer, a number that is no run, a
    failed run or no recorded run all keep the block (bounded by the caller's completion-check limit)."""
    runs = source.runs()
    if not runs:
        return False
    shown_from = max(0, len(runs) - RUNS_SHOWN)
    answer = source.questions.closed(
        prompts.render("coder_run_executes_required_test", task=source.task, runs=render_runs(runs)),
        phase="coder-run-executes-required-test").strip().strip("`[]. ").upper()
    named = int(answer) if answer.isdigit() and shown_from < int(answer) <= len(runs) else None
    run = runs[named - 1] if named is not None else None
    released = run is not None and run.exit_code in (0, None)
    if source.log is not None:
        source.log.emit("loop.coder_run_executes_required_test", runs=len(runs),
                        named=named if named is not None else (answer or "unknown"),
                        exit_code=run.exit_code if run is not None else None, released=released)
    return released


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
        if answer == "REQUIRED" and support is participation.Support.ABSENT and _coder_ran_required_test(source):
            return ApprovalResult(ApprovalStatus.PERMITTED)
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
           prompts=("test_participation_requirement", "coder_run_executes_required_test", "test_e2e_requirement", "test_e2e_participation"),
           services=("lazy-gate-participation", "closed-question", "inspecting-critic"),
           hooks=(Reference("cria/loop.py", "judge_satisfaction"),),
           regressions=(
               Reference("tests/loop_orientation/test_loop_orientation_completion_approval.py", "test_a_required_test_is_released_only_by_proven_participation_and_a_readable_answer"),
               Reference("tests/loop_orientation/test_loop_orientation_completion_approval.py", "test_an_end_to_end_requirement_is_judged_on_the_executed_test_source"),
               Reference("tests/loop_orientation/test_loop_orientation_completion_approval.py", "test_measured_non_participation_is_contradicted_not_merely_unknown"),
               ),
           migrated=False), test_participation)
EXACT_FORM = ExactFormDefinition(
    Policy("exact-file-form-approval", "completion-approval", 4, family_id="F35",
           prompts=("exact_form_requirement", "exact_form_bytes_confirm", "exact_form_ending_confirm", "exact_form_unmet", "unverified_step"),
           services=("lazy-file-facts", "workspace-path-equality", "closed-question", "critic-json-reader"),
           hooks=(Reference("cria/loop.py", "_satisfaction_evidence"),
                  Reference("cria/loop.py", "judge_satisfaction")),
           regressions=(
               Reference("tests/loop_orientation/test_loop_orientation_completion_approval.py", "test_exact_form_contradicts_only_a_grounded_requirement_against_measured_bytes"),
               Reference("tests/loop_rest/test_loop_rest_exact_form.py", "test_facts_describe_the_current_content_or_stay_silent"),
               Reference("tests-before-reset-20261031:tests/test_completion_approval_policies.py", "test_measurement_lifecycle_matches_current_mutation_invalidation")),
           migrated=False), exact_form, written_file_facts)
# Preserve current short-circuit order: participation first, exact form second.
PRE_RELEASE = (PARTICIPATION, EXACT_FORM)
