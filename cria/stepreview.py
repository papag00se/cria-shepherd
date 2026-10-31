"""Experimental optional-step review, distinct from whole-task release.

This source owns the step prompt, careful/retry authority, applicability of the
step confirmation brake, and the concrete step/probe settlement effects. Shared
critic parsing/cleanup/recovery, disk confirmation, evidence and diagnosis are
injected services, not copied here. The driver owns probe transport/scheduling,
consumes effects once, and never treats this result as whole-task approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from . import evidencesummary, callsyntax, groundtruth, prompts, research
from .assistcontract import Policy, Reference
from .planningcontracts import EventLog
from .jsontext import strip_think


# Existing optional-step cadence. The shared periodic_check_due scheduler stays
# driver-owned; integration imports this constant rather than another copy.
STEP_CHECK_EVERY = 12


class StepTrigger(Enum):
    CLAIM = "coder-completion-claim"
    SCHEDULED = "scheduled-step-check"


class StepStatus(Enum):
    NOT_SELECTED = "not-selected"
    PENDING_PROBE = "pending-probe"
    PERIODIC = "periodic-keep-working"
    UNKNOWN = "unknown"
    REJECTED = "rejected"
    APPROVED = "step-approved-only"
    UNOBSERVED = "scheduled-positive-without-observed-confirmation"


class StepAction(Enum):
    NONE = "none"
    CONTINUE_UNREVIEWED = "continue-current-step-without-review"
    KEEP_WORKING = "keep-working"
    RENUDGE = "renudge"
    ADVANCE = "advance-one-step"
    OBSERVE_WORKSPACE = "observe-workspace-then-rejudge"


@dataclass(frozen=True)
class ProbeEvidence:
    """Already settled by the shared gate reader, never inferred from prose.

    pending includes incomplete paged transport. periodic is a mid-step check,
    never a step-completion claim. A red repository gate is evidence for the
    step critic, not an automatic attribution to this step.
    """
    digest: str = ""
    red_findings: str = ""
    standing_red: bool = False
    ran: bool = False
    transport_unknown: bool = False
    blocked: bool = False
    repair_text: str = ""
    pending: bool = False
    periodic: bool = False


@dataclass(frozen=True)
class StepRead:
    system: str
    user: str
    reasoning_off: bool
    workspace_root: str = ""
    # Empty wire declaration preserves the established optional-step body;
    # the shared reader's recovery/normalization key MUST still be 'done'.
    verdict_key: str = ""
    recovery_key: str = "done"
    evidence_blocks: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepAnswer:
    verdict: dict | None
    raw: str = ""


class Confirmation(Protocol):
    @property
    def confirmed(self) -> bool: ...
    @property
    def observed(self) -> bool: ...
    @property
    def reason(self) -> str: ...


@dataclass(frozen=True)
class ConfirmStep:
    step: str
    reason: str
    workspace_root: str
    original_task: str
    participation_facts: str
    phase: str = "critic-confirm"


@dataclass(frozen=True)
class StepDiagnosis:
    verdict: dict
    done: bool
    routes: str
    user: str
    step: str
    original_task: str
    action_log: str
    checks: str
    participation_facts: str
    workspace_root: str
    phase: str


@dataclass(frozen=True)
class StepRecord:
    step: str
    system: str
    user: str
    done: bool
    reason: str
    raw: str
    key: str
    index: int
    total: int


class Reader(Protocol):
    def __call__(self, request: StepRead) -> StepAnswer: ...


class FlagReader(Protocol):
    def __call__(self, verdict: dict, flag: str, phase: str) -> dict | None: ...


@dataclass(frozen=True)
class StepServices:
    # Driver binds the existing shared critic reader, NOT the old _verify.
    read: Reader
    normalize_flag: FlagReader
    confirm: Callable[[ConfirmStep], Confirmation | None]
    diagnosis: Callable[[StepDiagnosis], str]
    persist: Callable[[StepRecord], None]
    # Required shared adapters, so omission cannot silently lose typed nudge
    # provenance or known unresolved checker facts.
    confirmation_nudge: Callable[[str], str]
    named_gap: Callable[[str], str]
    # Existing reasoning-OFF closed question with phase='confirm-applies',
    # temperature=0.0 and _ASK_USER_TURN. None keeps the brake applicable.
    confirm_applies_ask: Callable[[str], str | None] | None = None


@dataclass(frozen=True)
class StepInput:
    step: str
    coder_text: str
    evidence: str
    probe: ProbeEvidence
    services: StepServices
    log: EventLog
    workspace_root: str = ""
    coder_tools: str = ""
    routes: str = ""
    sources_read: tuple[tuple[str, str, str], ...] = ()
    participation_facts: str = ""
    original_task: str = ""
    key: str = ""
    index: int = 0
    total: int = 0
    trigger: StepTrigger = StepTrigger.CLAIM


@dataclass(frozen=True)
class StepEffect:
    action: StepAction = StepAction.NONE
    nudge: str = ""
    verify_failures: int = 0
    critic_failures: int = 0
    # A red/unknown repository reading remains standing evidence, even if one
    # step advanced. This policy cannot clear it or approve the whole task.
    preserve_gate_state: bool = True
    red_gate_advance: bool = False
    consider_critic_rescue: bool = False


@dataclass(frozen=True)
class StepResult:
    status: StepStatus
    reason: str = ""
    confirmation: Confirmation | None = None
    effect: StepEffect = StepEffect()
    readable: bool = False
    # The verifier's result, retained for the existing periodic event/artifact.
    # A scheduled positive can be readable/review_done without authority to
    # ADVANCE: its own confirmation must have observed the surveyed workspace.
    review_done: bool = False

    @property
    def done(self) -> bool:
        return self.status is StepStatus.APPROVED


def _prompt_packet(source: StepInput) -> tuple[str, str, str, tuple[str, ...]]:
    labels = prompts.load_map("verify_user")
    parts = [prompts.fill(labels["step"], step=source.step)]
    if source.evidence:
        parts.append(prompts.fill(labels["evidence"], evidence=source.evidence))
    if source.probe.digest:
        parts.append(prompts.fill(labels["probe"], probe=source.probe.digest))
    if source.participation_facts:
        parts.append(source.participation_facts)
    if source.probe.red_findings:
        parts.append(prompts.fill(labels["probe_red"], findings=source.probe.red_findings))
    claim = (prompts.load("periodic_step_claim") if source.trigger is StepTrigger.SCHEDULED
             else source.coder_text)
    coder_text = labels["summary_leak"] if callsyntax.has_tool_call_leak(claim) else claim
    parts.append(prompts.fill(labels["summary"], coder_summary=coder_text))
    if source.coder_tools:
        parts.append(prompts.render("reasoner_coder_tools", tools=source.coder_tools))
    # These are existing evidence adapters, not new file readers or policies.
    for artifact, missing in groundtruth.absent_step_literals(source.step, source.workspace_root):
        parts.append(prompts.fill(labels["absent_literals"], artifact=artifact,
                                  literals=", ".join(repr(m) for m in missing),
                                  them="it" if len(missing) == 1 else "them"))
    if source.sources_read:
        parts.append(prompts.fill(labels["sources_read"], sources=research._sources_block(source.sources_read)))
    parts.append(prompts.fill(labels["step_again"], step=source.step))
    full = "\n\n".join(parts)
    evidence = tuple(evidencesummary.blocks(parts.pop(1))) if source.evidence else ()
    return prompts.load("verify"), full, "\n\n".join(parts), evidence


def _prompt(source: StepInput) -> tuple[str, str]:
    system, full, _, _ = _prompt_packet(source)
    return system, full


def _confirm_applies(source: StepInput) -> bool:
    if source.probe.red_findings.strip() or source.probe.standing_red:
        return True
    ask = source.services.confirm_applies_ask
    if ask is None:
        return True
    answer = strip_think(ask(prompts.render("confirm_applies", step=source.step)) or "")
    head = answer.upper().split()[0].strip(".,:;`*\"'") if answer.split() else ""
    if head == "NO":
        source.log.emit("loop.confirm_skipped_no_artifact", level="info", phase="critic-confirm")
        return False
    return True


def _effect(source: StepInput, done: bool, reason: str) -> StepEffect:
    if done:
        return StepEffect(StepAction.ADVANCE, red_gate_advance=(source.trigger is StepTrigger.CLAIM
                          and source.probe.ran and source.probe.blocked))
    if source.trigger is StepTrigger.SCHEDULED:
        return StepEffect(StepAction.KEEP_WORKING)
    # Only a real red gate goes to plain checker-grounded re-nudge. A declined
    # probe/unknown transport still goes through the step critic; rejection
    # counts as a critic failure, exactly as in the original not-ran branch.
    red_gate = source.probe.ran and source.probe.blocked
    return StepEffect(StepAction.RENUDGE, source.probe.repair_text if red_gate else reason,
                      verify_failures=1, critic_failures=0 if red_gate else 1,
                      consider_critic_rescue=not red_gate)


def _record(source: StepInput, system: str, user: str, done: bool, reason: str, raw: str) -> None:
    # Same owned-directory verifier writer as the driver; no local disk I/O.
    try:
        source.services.persist(StepRecord(source.step, system, user, done, reason, raw,
                                          source.key, source.index, source.total))
    except OSError:
        pass  # existing best-effort verifier artifact contract, never a verdict input


def _diagnose(source: StepInput, obj: dict, done: bool, user: str, phase: str) -> str:
    return source.services.diagnosis(StepDiagnosis(
        obj, done, source.routes, user, source.step, source.original_task, source.evidence,
        source.probe.red_findings, source.participation_facts, source.workspace_root, phase))


def review_step(source: StepInput) -> StepResult:
    """One careful read, with exactly one negative-only reasoning-OFF retry.

    Readability, approval and workspace confirmation are distinct. Shared reader
    failures stay unknown; no step/tail guidance means keep working, never task
    release. Probe transport stays with the driver and must settle first.
    """
    if not isinstance(source.trigger, StepTrigger):
        raise ValueError("Unknown optional-step review trigger")
    if source.probe.pending:
        return StepResult(StepStatus.PENDING_PROBE)
    if source.probe.periodic:
        return StepResult(StepStatus.PERIODIC,
                          effect=StepEffect(StepAction.RENUDGE if source.probe.repair_text else StepAction.KEEP_WORKING,
                                            source.probe.repair_text))
    system, user, question, blocks = _prompt_packet(source)
    answer = source.services.read(StepRead(system, question, False, source.workspace_root, evidence_blocks=blocks))
    obj = (source.services.normalize_flag(answer.verdict, "done", "critic")
           if answer.verdict is not None else None)
    if obj is not None:
        done = bool(obj.get("done"))
        confirmation = None
        if done and source.workspace_root and _confirm_applies(source):
            confirmation = source.services.confirm(ConfirmStep(
                source.step, str(obj.get("reason") or ""), source.workspace_root,
                source.original_task, source.participation_facts))
            if confirmation is not None:
                source.log.emit("loop.done_confirm", step=source.index, confirmed=confirmation.confirmed)
            if confirmation is not None and not confirmation.confirmed:
                reason = source.services.confirmation_nudge(confirmation.reason or prompts.load("unverified_step"))
                _record(source, system, user, False, reason, answer.raw)
                return StepResult(StepStatus.REJECTED, reason, confirmation,
                                  _effect(source, False, reason), readable=True)
        reason = _diagnose(source, obj, done, user, "critic-diagnosis")
        _record(source, system, user, done, reason, answer.raw)
        if done and source.trigger is StepTrigger.SCHEDULED and not (
                confirmation is not None and confirmation.confirmed and confirmation.observed):
            # No cached approval travels with the observation request. The driver
            # schedules at most one survey/gate, discards this positive, and runs
            # this SAME review again on fresh facts after transport settles.
            observe = confirmation is not None and confirmation.confirmed and not confirmation.observed
            return StepResult(StepStatus.UNOBSERVED, reason, confirmation,
                              StepEffect(StepAction.OBSERVE_WORKSPACE if observe else StepAction.KEEP_WORKING),
                              readable=True, review_done=True)
        return StepResult(StepStatus.APPROVED if done else StepStatus.REJECTED, reason,
                          confirmation, _effect(source, done, reason), readable=True, review_done=done)
    source.log.emit("loop.verify_retry", level="info", reason="no parseable verdict; retry reasoning-off")
    # Preserve the original retry's empty workspace declaration, not a new
    # inspection loop or another role-dependent confirmation attempt.
    retry_answer = source.services.read(StepRead(system, question, True, evidence_blocks=blocks))
    retry = (source.services.normalize_flag(retry_answer.verdict, "done", "critic-retry")
             if retry_answer.verdict is not None else None)
    if retry is not None and retry.get("done"):
        source.log.emit("loop.verify_failclosed", level="info")
        retry = None
    if retry is None:
        reason = prompts.load("unverified_step") + source.services.named_gap(source.probe.red_findings)
        _record(source, system, user, False, reason, retry_answer.raw)
        return StepResult(StepStatus.UNKNOWN, reason, effect=_effect(source, False, reason))
    reason = _diagnose(source, retry, False, user, "critic-retry-diagnosis")
    _record(source, system, user, False, reason, retry_answer.raw)
    return StepResult(StepStatus.REJECTED, reason, effect=_effect(source, False, reason), readable=True)


@dataclass(frozen=True)
class StepDefinition:
    policy: Policy
    execute: Callable[[StepInput], StepResult]


DEFINITION = StepDefinition(Policy(
    "experimental-step-review", "experimental-step-review", 5, family_id="F50", scope="experimental",
    prompts=("verify", "verify_user", "reasoner_coder_tools", "confirm_applies", "unverified_step", "periodic_step_claim"),
    state="stateless step verdict/effect; driver owns correlated probe transport, counters and exactly-once effect consumption",
    services=("shared-critic-reader", "shared-verdict-flag-reader", "workspace-view-literal-facts", "research-source-facts", "step-confirmation", "shared-negative-diagnosis", "owned-verifier-persistence"),
    hooks=(Reference("cria/loop.py", "Loop._verify"), Reference("cria/loop.py", "Loop._verify_after_probe"),
           Reference("cria/loop.py", "_confirm_applies"), Reference("cria/loop.py", "Loop._work"),
           Reference("cria/loop.py", "Loop._periodic_step_check"),
           Reference("cria/loop.py", "Loop._periodic_observation_after_probe")),
    regressions=(Reference("tests/loop_planner/test_loop_planner_plan_on.py", "test_an_unreadable_verdict_gets_one_reasoning_off_retry_and_a_positive_retry_fails_closed"),
                 Reference("tests_backup/test_optional_step_policy.py", "test_probe_settlement_preserves_step_not_task_authority"),
                 Reference("tests/loop_planner/test_loop_planner_plan_on.py", "test_a_pending_or_periodic_probe_never_reaches_the_critic"),
                 Reference("tests_backup/test_optional_step_policy.py", "test_shared_reader_rejects_truncation_and_uses_step_key"),
                 Reference("tests/loop_planner/test_loop_planner_plan_on.py", "test_a_scheduled_positive_never_advances_without_its_own_observed_confirmation"),
                 Reference("tests_backup/test_optional_step_policy.py", "test_observation_discards_positive_and_rejudges_fresh_facts")),
    migrated=False), review_step)
DEFINITIONS = (DEFINITION,)


@dataclass(frozen=True)
class StepSelection:
    enabled: bool = False
    definition: StepDefinition | None = None

    def __post_init__(self):
        if type(self.enabled) is not bool or (not self.enabled and self.definition is not None):
            raise ValueError("Optional step review requires explicit experimental consent")
        if self.definition is not None and (not isinstance(self.definition, StepDefinition)
                or self.definition.policy != DEFINITION.policy
                or not callable(self.definition.execute)):
            raise ValueError("Incompatible optional step replacement")

    @classmethod
    def from_definitions(cls, definitions: tuple, *, enabled: bool = False):
        if type(enabled) is not bool or not isinstance(definitions, tuple):
            raise ValueError("Optional step selection requires immutable definitions and explicit consent")
        if not enabled:
            return cls()
        selected = tuple(definition for definition in definitions
                         if definition.policy.id == DEFINITION.policy.id)
        if len(selected) > 1:
            raise ValueError("Duplicate optional step review selection")
        return cls(True, selected[0] if selected else None)

    @classmethod
    def opt_in(cls, definition: StepDefinition | None = DEFINITION):
        return cls(True, definition)

    def run(self, source: StepInput | Callable[[], StepInput]) -> StepResult:
        if self.definition is None:
            return StepResult(StepStatus.NOT_SELECTED,
                              effect=StepEffect(StepAction.CONTINUE_UNREVIEWED))
        value = source() if callable(source) else source
        result = self.definition.execute(value)
        if (not isinstance(result, StepResult) or not isinstance(result.status, StepStatus)
                or not isinstance(result.effect, StepEffect)
                or not isinstance(result.effect.action, StepAction)
                or not isinstance(result.reason, str) or not isinstance(result.effect.nudge, str)
                or any(type(value) is not int or value < 0 for value in (
                    result.effect.verify_failures, result.effect.critic_failures))
                or any(type(value) is not bool for value in (
                    result.effect.preserve_gate_state, result.effect.red_gate_advance,
                    result.effect.consider_critic_rescue))
                or type(result.readable) is not bool or type(result.review_done) is not bool):
            raise TypeError("Optional step replacement must return a typed StepResult and StepEffect")
        return result
