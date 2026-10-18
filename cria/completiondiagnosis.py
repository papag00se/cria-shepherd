"""Negative completion guidance, never completion authority.

Selection happens before these lazy stages. Suppression means silence, not approval.
The task/session retains its existing durable fields; no second pending-state store
or process-global cache is introduced. Workspace and critic readers remain services.
"""
from dataclasses import dataclass
from enum import Enum
import os
import re
from typing import Callable, Protocol

from . import probeclassify, prompts
from .assistcontract import Policy, Reference
from .jsontext import extract_json_object, strip_think
from .shelltool import is_shell_tool_name, writes_something


class DiagnosisStatus(Enum):
    NOT_APPLICABLE = "not-applicable"
    WITHHELD = "withheld"
    GROUNDED = "grounded"


@dataclass(frozen=True)
class DiagnosisResult:
    status: DiagnosisStatus
    evidence: str = ""
    action: str = ""
    diagnosis_kind: str = ""
    subject: str = ""
    cause: str = ""

    def __post_init__(self):
        # Preserve the existing nudge carrier's rendering normalization; source
        # quote validation above still uses the original, unmodified task bytes.
        object.__setattr__(self, "evidence", (self.evidence or "").strip())
        object.__setattr__(self, "action", (self.action or "").strip())

    @property
    def text(self) -> str:
        action = prompts.render("verdict_nudge_action", action=self.action.strip()) if self.action.strip() else ""
        return "\n".join(part for part in (self.evidence.strip(), action) if part)


def _diagnosis_result(result: DiagnosisResult) -> DiagnosisResult:
    if not isinstance(result, DiagnosisResult):
        raise TypeError("diagnosis hook must return DiagnosisResult")
    if not isinstance(result.status, DiagnosisStatus):
        raise ValueError("diagnosis hook returned an invalid status")
    return result


class Log(Protocol):
    def emit(self, kind: str, **fields) -> None: ...


class Ask(Protocol):
    def __call__(self, question: str, *evidence: list[str]) -> str: ...


@dataclass(frozen=True)
class GroundingServices:
    # Existing workspace-subject resolver preserves partial/folded/ambiguous unknowns.
    subject: Callable[[str], tuple[str, bool | None, str | None]]
    evidence_blocks: Callable[[str], list[str]]
    fix_text: Callable[[dict], str]
    ask: Ask | None = None
    log: Log | None = None


@dataclass(frozen=True)
class DiagnosisInput:
    candidate: Callable[[], dict]
    task: str
    action_log: str = ""
    checks: str = ""
    participation_facts: str = ""
    original_task: str | None = None
    phase: str = "negative-diagnosis"


_KINDS = frozenset({"missing_file", "missing_content", "failed_check", "unverified_requirement", "other"})
_SOURCES = frozenset({"workspace_absence", "workspace_file", "action_log", "checks", "participation"})


def _emit(log: Log | None, event: str, **fields) -> None:
    if log is not None:
        log.emit(event, assist_id=DEFINITION.policy.id, family_id=DEFINITION.policy.family_id, **fields)


def subject_is_exact_in_quote(subject: str, quote: str) -> bool:
    if not subject or not quote:
        return False
    return re.search(rf"(?<![\w./-]){re.escape(subject)}(?![\w/-])", quote) is not None


def required_output_span_names_subject(task: str, quote: str, subject: str) -> bool:
    """Validate source-delimited literal identity, not output intent or Markdown meaning."""
    if not task or not quote or not subject:
        return False
    literals = tuple(re.finditer(r"(?P<mark>[`\"'])(?P<value>.*?)(?P=mark)", task, re.DOTALL))

    def source_end(pos: int, enclosed: bool = False) -> bool:
        if pos == len(task) or task[pos].isspace():
            return True
        punctuation = ".,;:!?" if enclosed else "."
        return task[pos] in punctuation and (pos + 1 == len(task) or task[pos + 1].isspace())

    at = task.find(quote)
    while at >= 0:
        if at and not task[at - 1].isspace():
            at = task.find(quote, at + 1)
            continue
        for match in re.finditer(re.escape(subject), quote):
            start, end = at + match.start(), at + match.end()
            enclosing = next((unit for unit in literals
                              if unit.start("value") <= start and end <= unit.end("value")), None)
            if enclosing is not None:
                if enclosing.group("value") != subject:
                    continue
                start, end = enclosing.span()
                if start < at or end > at + len(quote):
                    continue
            elif ((start and task[start - 1] in ("`", '"', "'"))
                  or (end < len(task) and task[end] in ("`", '"', "'"))):
                continue
            if ((start == 0 or task[start - 1].isspace()) and source_end(end, enclosed=enclosing is not None)
                    and source_end(at + len(quote), enclosed=enclosing is not None and end == at + len(quote))):
                return True
        at = task.find(quote, at + 1)
    return False


def ground_diagnosis(source: DiagnosisInput, services: GroundingServices) -> DiagnosisResult:
    obj = source.candidate()
    kind = str(obj.get("diagnosis_kind") or "").strip()
    subject = str(obj.get("subject") or "").strip()
    task_quote = str(obj.get("task_quote") or "").strip()
    origin = str(obj.get("evidence_source") or "").strip()
    evidence_quote = str(obj.get("evidence_quote") or "").strip()

    def suppress(cause: str) -> DiagnosisResult:
        _emit(services.log, "loop.negative_diagnosis_suppressed", level="info", phase=source.phase,
              cause=cause, diagnosis_kind=kind or "missing")
        return DiagnosisResult(DiagnosisStatus.WITHHELD if obj else DiagnosisStatus.NOT_APPLICABLE, cause=cause)

    def supported(evidence: str, action: str = "", *, result_kind: str = "", target: str = "") -> DiagnosisResult:
        _emit(services.log, "loop.negative_diagnosis_supported", level="info", phase=source.phase,
              diagnosis_kind=kind, evidence_source=origin)
        return DiagnosisResult(DiagnosisStatus.GROUNDED,
                               prompts.render("negative_diagnosis", task_quote=task_quote, source=origin, evidence=evidence),
                               action, result_kind, target)

    if kind not in _KINDS:
        return suppress("unknown diagnosis kind")
    if origin not in _SOURCES:
        return suppress("unknown evidence source")
    if kind == "missing_file" and origin == "workspace_absence":
        authority = source.task if source.original_task is None else source.original_task
        rel, present, _ = services.subject(subject)
        if present is not False or not rel:
            return suppress("file exists or workspace state is unknown")
        if not authority or services.ask is None:
            return suppress("required-output grounding unavailable")
        try:
            answer = services.ask(prompts.render("missing_output_requirement", task=authority, subject=subject))
            grounded = extract_json_object(strip_think(answer or ""))
        except Exception:
            return suppress("required-output grounding unavailable")
        if (not isinstance(grounded, dict) or grounded.get("required_output") is not True
                or grounded.get("subject") != subject or not isinstance(grounded.get("task_quote"), str)
                or not required_output_span_names_subject(authority, grounded["task_quote"], subject)):
            return suppress("required-output grounding unsupported")
        current_rel, current_present, _ = services.subject(subject)
        if current_present is not False or current_rel != rel:
            return suppress("file exists or workspace state is unknown")
        task_quote = grounded["task_quote"]
        return supported(prompts.render("negative_diagnosis_missing_file", subject=rel), task_quote,
                         result_kind=kind, target=rel)
    if not task_quote or task_quote not in (source.task or ""):
        return suppress("task quote is not exact")
    retyped = False
    if (origin == "workspace_absence" and kind != "missing_file" and subject
            and subject_is_exact_in_quote(subject, task_quote) and services.subject(subject)[1] is False):
        _emit(services.log, "loop.negative_diagnosis_canonicalised", level="info", phase=source.phase,
              was=kind, now="missing_file", subject=subject)
        kind, evidence_quote, retyped = "missing_file", "", True
    if kind == "missing_file":
        named = subject_is_exact_in_quote(subject, task_quote) or subject_is_exact_in_quote(os.path.basename(subject), task_quote)
        if not subject or not named:
            return suppress("workspace subject is not task-named")
    elif kind == "missing_content" and not subject:
        return suppress("missing-content has no workspace subject")
    if kind == "missing_file":
        if origin != "workspace_absence":
            return suppress("missing-file source contract")
        rel, present, _ = services.subject(subject)
        if present is not False:
            return suppress("file exists or workspace state is unknown")
        return supported(prompts.render("negative_diagnosis_missing_file", subject=rel or subject), task_quote,
                         result_kind="absent_named_file" if retyped else kind, target=rel or subject)
    if kind == "missing_content" and origin != "workspace_file":
        return suppress("missing-content source contract")
    if kind == "failed_check" and origin != "checks":
        return suppress("failed-check source contract")
    if origin == "workspace_absence":
        return suppress("absence source is only valid for a missing file")
    workspace_fact = source_text = ""
    if origin == "workspace_file":
        if not subject:
            return suppress("workspace-file source has no subject")
        rel, present, body = services.subject(subject)
        if present is not True or body is None:
            return suppress("workspace file or complete content is unknown")
        source_text = body
        workspace_fact = prompts.render("negative_diagnosis_existing_file", subject=rel or subject)
    elif origin == "action_log":
        source_text = source.action_log or ""
    elif origin == "checks":
        source_text = source.checks or ""
    elif origin == "participation":
        source_text = source.participation_facts or ""
    if not evidence_quote or evidence_quote not in source_text:
        return suppress("evidence quote is not exact")
    if services.ask is None:
        return suppress("semantic support unavailable")
    composed = bool(source.action_log.strip()) and getattr(services.ask, "composes_evidence", False)
    question = prompts.render(
        "negative_diagnosis_support", diagnosis_kind=kind, subject=subject or "(none)", task_quote=task_quote,
        evidence_source=origin, evidence_quote=evidence_quote,
        diagnosis=str(obj.get("reason") or obj.get("why") or "").strip() or "(none)",
        proposed_fix=services.fix_text(obj) or "(none)", workspace_facts=workspace_fact or "(none available)",
        checks=source.checks or "(none available)", participation=source.participation_facts or "(none available)",
        action_log=prompts.load("negative_diagnosis_log_above") if composed else source.action_log or "(none available)")
    answer = strip_think((services.ask(question, services.evidence_blocks(source.action_log)) if composed
                          else services.ask(question)) or "")
    head = answer.upper().split()[0].strip(".,:;`*\"'") if answer.split() else ""
    if head != "SUPPORTED":
        return suppress("semantic support absent or undecidable")
    return supported(evidence_quote, task_quote)


@dataclass(frozen=True)
class ObservationInput:
    task: str
    available: bool


@dataclass(frozen=True)
class ObservationServices:
    inventory: Callable[[], str]
    # Existing inspecting critic: deliverable-observation phase, missing_file key,
    # observation schema and seed_files=True. It retains reader/role ownership.
    judge: Callable[[str, str], object]
    truncated: Callable[[object], bool]
    text: Callable[[object], str]
    clean: Callable[[str], str]
    grounding: GroundingServices
    # Required policy composition: the same selected definition's execute hook.
    execute: Callable[[DiagnosisInput, GroundingServices], DiagnosisResult]


def observe_missing_file(source: ObservationInput, services: ObservationServices) -> DiagnosisResult:
    if not (source.task.strip() and source.available):
        return DiagnosisResult(DiagnosisStatus.NOT_APPLICABLE)
    inventory = services.inventory()
    try:
        completion = services.judge(
            prompts.load("deliverable_observation"),
            prompts.render("deliverable_observation_user", task=source.task,
                           inventory=f"{inventory}\n\n" if inventory else ""))
    except Exception as error:
        _emit(services.grounding.log, "loop.deliverable_observation_error", level="warn", error=str(error))
        return DiagnosisResult(DiagnosisStatus.WITHHELD, cause="observer unavailable")
    if services.truncated(completion):
        _emit(services.grounding.log, "loop.deliverable_observation_truncated", level="warn")
        return DiagnosisResult(DiagnosisStatus.WITHHELD, cause="observer truncated")
    obj = extract_json_object(services.clean(services.text(completion)))
    if not isinstance(obj, dict):
        return DiagnosisResult(DiagnosisStatus.WITHHELD, cause="observer unreadable")
    if obj.get("missing_file") is not True:
        return DiagnosisResult(DiagnosisStatus.NOT_APPLICABLE)
    return _diagnosis_result(services.execute(
        DiagnosisInput(lambda: obj, source.task, original_task=source.task, phase="deliverable-observation"),
        services.grounding))


class RemediationState(Protocol):
    completion_remediation_subject: str
    completion_remediation_reason: str
    completion_remediation_nonwrite_ids: tuple[str, ...]
    completion_remediation_nonwrite_seen: bool
    nudge_reason: str
    steer_source: str


class RemediationStatus(Enum):
    NOT_APPLICABLE = "not-applicable"
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    FOLLOW_UP = "follow-up"
    SETTLED = "settled"
    DELIVERED = "delivered"


@dataclass(frozen=True)
class RemediationResult:
    status: RemediationStatus
    subject: str = ""
    reason: str = ""


def _remediation_result(result: RemediationResult, allowed: tuple[RemediationStatus, ...]) -> RemediationResult:
    if not isinstance(result, RemediationResult):
        raise TypeError("remediation hook must return RemediationResult")
    if not isinstance(result.status, RemediationStatus) or result.status not in allowed:
        raise ValueError("remediation hook returned an invalid status")
    return result


@dataclass(frozen=True)
class RemediationServices:
    write_path: Callable[[dict], str | None]
    same_path: Callable[[str, str], bool]
    command_text: Callable[[object], str | None]
    log: Log | None = None


def arm_remediation(state: RemediationState, subject: str, reason: str) -> RemediationResult:
    """Caller must supply only the provenance owner's typed missing-file target."""
    state.completion_remediation_subject = subject
    state.completion_remediation_reason = reason
    state.completion_remediation_nonwrite_ids = ()
    state.completion_remediation_nonwrite_seen = False
    return RemediationResult(RemediationStatus.PENDING, subject, reason)


_NATIVE_INSPECTIONS = frozenset({"read_file", "cat_file", "view_file", "list_dir", "grep_files"})
_SHELL_READERS = frozenset({"ls", "dir", "pwd", "cat", "head", "tail", "wc", "stat", "grep", "rg", "ag"})
_SHELL_INERT = frozenset({"cd", "echo", "printf", "test", "[", "[["})


def supported_inspection(function: dict, services: RemediationServices) -> bool:
    name = function.get("name")
    if name in _NATIVE_INSPECTIONS:
        return True
    if not is_shell_tool_name(name):
        return False
    command = services.command_text(function.get("arguments") or "")
    if not command or writes_something(name, command):
        return False
    inspected = False
    for segment in probeclassify.split_chain(command):
        argv = probeclassify.tokenize(segment)
        if not argv:
            continue
        base = probeclassify.basename(argv[0])
        if base in _SHELL_READERS:
            inspected = True
        elif base not in _SHELL_INERT:
            return False
    return inspected


def acknowledge_delivery(state: RemediationState, coder: dict, services: RemediationServices) -> RemediationResult:
    subject = getattr(state, "completion_remediation_subject", "")
    if not subject:
        return RemediationResult(RemediationStatus.NOT_APPLICABLE)
    ids = []
    for choice in coder.get("choices", []) if isinstance(coder, dict) else []:
        for call in ((choice.get("message") or {}).get("tool_calls") or []):
            if call.get("id") and supported_inspection(call.get("function") or {}, services):
                ids.append(str(call["id"]))
    state.completion_remediation_nonwrite_ids = tuple(ids)
    return RemediationResult(RemediationStatus.ACKNOWLEDGED, subject, state.completion_remediation_reason)


def follow_up_nonwrite(state: RemediationState, messages: list[dict], services: RemediationServices) -> RemediationResult:
    subject = getattr(state, "completion_remediation_subject", "")
    ids = set(getattr(state, "completion_remediation_nonwrite_ids", ()) or ())
    if not subject:
        return RemediationResult(RemediationStatus.NOT_APPLICABLE)
    if (not ids or getattr(state, "completion_remediation_nonwrite_seen", False) or getattr(state, "nudge_reason", "")
            or not any((m.get("tool_call_id") or m.get("call_id")) in ids for m in messages or [] if isinstance(m, dict))):
        return RemediationResult(RemediationStatus.PENDING, subject, state.completion_remediation_reason)
    state.completion_remediation_nonwrite_seen = True
    state.nudge_reason = prompts.load("completion_remediation_nonwrite")
    state.steer_source = "completion remediation non-write follow-up"
    _emit(services.log, "loop.completion_remediation_nonwrite", subject=subject)
    return RemediationResult(RemediationStatus.FOLLOW_UP, subject, state.nudge_reason)


def observed_successful_write(messages: list[dict], subject: str, services: RemediationServices) -> bool:
    calls = {}
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        for call in message.get("tool_calls") or []:
            path = services.write_path(call.get("function") or {})
            if call.get("id") and path and services.same_path(path, subject):
                calls[call["id"]] = path
        path = calls.get(message.get("tool_call_id") or message.get("call_id"))
        if path:
            content = message.get("content") if message.get("content") is not None else message.get("output")
            if isinstance(content, str) and content.strip().splitlines()[:1] == [prompts.render("write_confirm", path=path).strip()]:
                return True
    return False


def settle_remediation(state: RemediationState, messages: list[dict], services: RemediationServices) -> RemediationResult:
    subject = getattr(state, "completion_remediation_subject", "")
    if not subject:
        return RemediationResult(RemediationStatus.NOT_APPLICABLE)
    if not observed_successful_write(messages, subject, services):
        return RemediationResult(RemediationStatus.PENDING, subject, state.completion_remediation_reason)
    state.completion_remediation_subject = ""
    state.completion_remediation_reason = ""
    state.completion_remediation_nonwrite_ids = ()
    state.completion_remediation_nonwrite_seen = False
    _emit(services.log, "loop.completion_remediation_written", subject=subject)
    return RemediationResult(RemediationStatus.SETTLED, subject)


class GapState(RemediationState, Protocol):
    last_gap_named: str
    last_gap_subject: str
    last_gap_observation: str | None


class DeliveryTrigger(Enum):
    SCHEDULED_REVIEW = "scheduled-review"
    DELIVERABLE_OBSERVATION = "deliverable-observation"


@dataclass(frozen=True)
class DeliveryInput:
    diagnosis: DiagnosisResult
    trigger: DeliveryTrigger
    plan_off: bool = False


@dataclass(frozen=True)
class DeliveryServices:
    observation: Callable[[], str | None]
    event_head: Callable[[str, int], str]
    # Policy composition, not a fact reader. PENDING accepts; NOT_APPLICABLE
    # declines without mutation by the callback. Other statuses are invalid.
    arm: Callable[[RemediationState, str, str], RemediationResult]
    log: Log | None = None


def deliver_gap(source: DeliveryInput, state: GapState, services: DeliveryServices) -> RemediationResult:
    """Consume already-grounded provenance, never re-judge or alter review state.

    The scheduled-review path suppresses repeats unless a complete/current survey
    renewed the same missing-file observation. The independent deliverable observer
    deliberately replaces ordinary steering, and only for a typed output absence.
    """
    gap = _diagnosis_result(source.diagnosis)
    if gap.status is not DiagnosisStatus.GROUNDED:
        return RemediationResult(RemediationStatus.NOT_APPLICABLE)
    named = gap.text.strip()
    observed = services.observation()
    target = gap.subject if gap.diagnosis_kind == "missing_file" else ""
    renewed = bool(target and target == getattr(state, "last_gap_subject", "") and observed
                   and observed != getattr(state, "last_gap_observation", ""))
    if source.trigger is DeliveryTrigger.DELIVERABLE_OBSERVATION:
        if not target:
            return RemediationResult(RemediationStatus.NOT_APPLICABLE)
        rearmed = False
    else:
        if not named or state.nudge_reason or (named == (getattr(state, "last_gap_named", "") or "").strip() and not renewed):
            return RemediationResult(RemediationStatus.NOT_APPLICABLE)
        rearmed = renewed
    nudge = prompts.render("periodic_missing_file_gap" if target else "periodic_gap",
                           reason=gap.text, subject=gap.subject)
    head = services.event_head(named, 120)
    if target and (source.trigger is DeliveryTrigger.DELIVERABLE_OBSERVATION or not source.plan_off):
        armed = _remediation_result(services.arm(state, target, nudge),
                                    (RemediationStatus.PENDING, RemediationStatus.NOT_APPLICABLE))
        if armed.status is RemediationStatus.NOT_APPLICABLE:
            return armed
    state.last_gap_named = named
    state.last_gap_subject = target
    state.last_gap_observation = observed if target else ""
    state.nudge_reason = nudge
    state.steer_source = ("deliverable observation" if source.trigger is DeliveryTrigger.DELIVERABLE_OBSERVATION
                          else "completion check (deliverable not found)")
    _emit(services.log, "loop.satisfaction_gap_named", level="info", head=head,
          subject=target, rearmed=rearmed)
    return RemediationResult(RemediationStatus.DELIVERED, target, state.nudge_reason)


class ObservationState(GapState, Protocol):
    deliverable_observation_last_drive: int


@dataclass(frozen=True)
class ScheduledObservationInput:
    task: str
    drive: int
    start: int
    every: int
    available: bool


@dataclass(frozen=True)
class ObservationRun:
    diagnosis: DiagnosisResult
    delivery: RemediationResult


@dataclass(frozen=True)
class ObservationLifecycleServices:
    observer: ObservationServices
    delivery: DeliveryServices
    due: Callable[[int, int, int, int], bool]
    # Both policy hooks belong to the same selected definition as nested services.
    observe: Callable[[ObservationInput, ObservationServices], DiagnosisResult]
    deliver: Callable[[DeliveryInput, GapState, DeliveryServices], RemediationResult]


def observe_scheduled(source: ScheduledObservationInput, state: ObservationState,
                      services: ObservationLifecycleServices) -> ObservationRun:
    """Independent plan-on observation cadence; does not clear or reinterpret a red gate.

    The pre-inspection stamp records an attempt, including a subsequent arm decline.
    """
    silent = ObservationRun(DiagnosisResult(DiagnosisStatus.NOT_APPLICABLE),
                            RemediationResult(RemediationStatus.NOT_APPLICABLE))
    if (state.completion_remediation_subject
            or not services.due(source.drive, source.start, source.every, state.deliverable_observation_last_drive)):
        return silent
    if services.delivery.observation() is None:
        return silent
    state.deliverable_observation_last_drive = source.drive
    if not (source.available and source.task.strip()):
        return silent
    gap = _diagnosis_result(services.observe(ObservationInput(source.task, source.available), services.observer))
    if gap.status is not DiagnosisStatus.GROUNDED:
        return ObservationRun(gap, silent.delivery)
    delivery = _remediation_result(
        services.deliver(DeliveryInput(gap, DeliveryTrigger.DELIVERABLE_OBSERVATION), state, services.delivery),
        (RemediationStatus.DELIVERED, RemediationStatus.NOT_APPLICABLE))
    return ObservationRun(gap, delivery)


def observe_terminal(root_task: Callable[[], str], available: bool,
                     services: ObservationLifecycleServices) -> DiagnosisResult:
    """Read only retained root authority, never a continuation/generated-step argument.

    The caller has already held completion and found no usable diagnosis. This
    fallback cannot update that verdict, its cadence, or any pending remediation.
    """
    task = root_task()
    observed = services.delivery.observation()
    if observed is None or not task or not available or not task.strip():
        return DiagnosisResult(DiagnosisStatus.NOT_APPLICABLE)
    gap = _diagnosis_result(services.observe(ObservationInput(task, available), services.observer))
    if gap.status is DiagnosisStatus.GROUNDED and gap.diagnosis_kind == "missing_file" and gap.subject:
        _emit(services.observer.grounding.log, "loop.done_gap_observed", level="info", subject=gap.subject, plan_off=True)
        return gap
    return DiagnosisResult(gap.status if gap.status is DiagnosisStatus.WITHHELD else DiagnosisStatus.NOT_APPLICABLE,
                           cause=gap.cause)


@dataclass(frozen=True)
class DiagnosisDefinition:
    policy: Policy
    execute: Callable[[DiagnosisInput, GroundingServices], DiagnosisResult]
    arm: Callable[[RemediationState, str, str], RemediationResult]
    acknowledge: Callable[[RemediationState, dict, RemediationServices], RemediationResult]
    follow_up: Callable[[RemediationState, list[dict], RemediationServices], RemediationResult]
    settle: Callable[[RemediationState, list[dict], RemediationServices], RemediationResult]
    observe: Callable[[ObservationInput, ObservationServices], DiagnosisResult]
    deliver: Callable[[DeliveryInput, GapState, DeliveryServices], RemediationResult]
    observe_scheduled: Callable[[ScheduledObservationInput, ObservationState, ObservationLifecycleServices], ObservationRun]
    observe_terminal: Callable[[Callable[[], str], bool, ObservationLifecycleServices], DiagnosisResult]


DEFINITION = DiagnosisDefinition(
    Policy("negative-completion-diagnosis", "completion-diagnosis", 4, family_id="F36",
           prompts=("negative_diagnosis", "negative_diagnosis_missing_file", "negative_diagnosis_existing_file",
                    "negative_diagnosis_support", "negative_diagnosis_log_above", "missing_output_requirement",
                    "verdict_nudge_action", "completion_remediation_nonwrite", "deliverable_observation",
                    "deliverable_observation_user", "periodic_missing_file_gap", "periodic_gap"),
           state="task-local last_gap_* repeat memory, transient observer cadence, durable completion_remediation_* delivery correlation; only matching write settles",
           services=("workspace-subject", "closed-question", "reducible-evidence-blocks", "verdict-fix-reader",
                     "tool-write-path", "workspace-path-equality", "shell-command-reader", "inspecting-critic",
                     "workspace-inventory", "workspace-observation-fingerprint", "periodic-check-due", "retained-root-task"),
           hooks=(Reference("cria/loop.py", "_verdict_nudge"), Reference("cria/loop.py", "_confirm_completion"),
                  Reference("cria/loop.py", "observe_task_missing_file"), Reference("cria/loop.py", "Loop._work_item"),
                  Reference("cria/loop.py", "Loop._periodic_satisfaction"),
                  Reference("cria/loop.py", "Loop._observe_missing_file_on_done")),
           regressions=(Reference("tests/test_completion_diagnosis_policy.py", "test_grounding_matches_current_owner"),
                        Reference("tests/test_completion_diagnosis_policy.py", "test_remediation_lifecycle_matches_current_owner"),
                        Reference("tests/test_completion_diagnosis_policy.py", "test_observer_composes_real_inventory_and_reuses_grounding"),
                        Reference("tests/test_completion_diagnosis_policy.py", "test_scheduled_delivery_repeats_only_on_renewed_complete_observation"),
                        Reference("tests/test_completion_diagnosis_policy.py", "test_scheduled_observer_owns_stamp_before_question_and_target_delivery"),
                        Reference("tests/test_completion_diagnosis_policy.py", "test_terminal_observer_uses_only_retained_root_and_does_not_arm_or_stamp")),
           migrated=False), ground_diagnosis, arm_remediation, acknowledge_delivery, follow_up_nonwrite, settle_remediation,
    observe_missing_file, deliver_gap, observe_scheduled, observe_terminal)
DEFINITIONS = (DEFINITION,)
