"""Explicitly experimental remaining-tail policy and its pending settlement.

The driver supplies current shared evidence and runs whole-task confirmation.
This source owns tail questions, refusal/replacement, rescue admission, and plan
mutation/persistence. It never declares a task finished. No loop imports, disk
readers, or duplicate verdict/evidence providers live here. Production hookup
must replace reassess_remaining/_replan_tail and their rescue decisions, not run
this alongside them. Selection/consent remain task-stable and caller-owned.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol

from . import planner, prompts, urlgrounding
from .assistcontract import Policy, Reference
from .planner import CoverageDefinition
from .planningcontracts import EventLog
from .jsontext import strip_think
from .plan import Plan, PlanItem

# Existing thresholds, now owned by the intervention that consumes them. The
# integration must import these instead of leaving a second threshold owner.
STUCK_STEP_REPLAN = 4
STEP_THRASH_REPLAN = 12


class Trigger(Enum):
    ADVANCE = "advance"
    CRITIC_STALLED = "critic-stalled"
    TOOL_THRASH = "tool-thrash"


class TailStatus(Enum):
    NOT_SELECTED = "not-selected"
    NOT_APPLICABLE = "not-applicable"
    ABSENT = "absent"                    # not []: keep the prior tail
    ALL_NOISE = "all-noise"              # keep the prior tail
    TOOL_LEAK = "tool-leak"              # keep the prior tail
    UNCHANGED = "unchanged"
    REPLACED = "replaced"
    RAW_TASK = "raw-task"                # typed coverage refusal, not a miss
    EMPTY_PENDING = "empty-pending-whole-task-confirmation"
    EMPTY_DECLINED = "empty-declined"
    EMPTY_CONFIRMED = "empty-confirmed"  # prune tail ONLY; not task release
    STALE = "stale"


@dataclass(frozen=True)
class TailFacts:
    evidence: str
    research: str = ""
    routes: str = ""


class Question(Protocol):
    def __call__(self, system: str, user: str, *, coder_tools: str = "") -> str | None: ...


@dataclass(frozen=True)
class TailServices:
    question: Question | None
    facts: Callable[[], TailFacts]
    persist: Callable[[Plan], None]
    coverage: CoverageDefinition | None


@dataclass(frozen=True)
class TailInput:
    plan: Plan
    # Stable task/step-POSITION identity, never mutable step text/tail shape.
    step_key: str
    # Opaque authoritative action/gate snapshot supplied by the driver, not a
    # source-maintained turn counter. Existing integer standalone tokens work.
    evidence_epoch: object
    trigger: Trigger
    services: TailServices
    log: EventLog
    synthetic: bool = False
    plan_off: bool = False
    critic_fails: int = 0
    acting_calls: int = 0
    coder_tools: str = ""
    # Supplied by the existing tool-menu summary adapter, not reparsed here.
    tool_names: tuple[str, ...] = ()
    step_index: int = 0


@dataclass(frozen=True)
class PendingToken:
    generation: int
    identity: object = field(default_factory=object, repr=False)


@dataclass(frozen=True)
class EmptyTailQuestion:
    token: PendingToken
    task: str
    evidence: str
    # The whole-task question must get the parameter-free judge menu. The
    # re-derivation gets coder_tools; do NOT reuse that parameter-bearing menu.
    plan_id: str


@dataclass(frozen=True)
class TailResult:
    status: TailStatus
    steps: tuple[str, ...] | None = None
    missing: tuple[str, ...] = ()
    confirmation: EmptyTailQuestion | None = None
    # Concrete driver effects for the raw-task transition. This is not a task
    # approval, nor an instruction authored by this module.
    reset_to_raw_task: bool = False
    reset_failure_counts: bool = False
    clear_nudge: bool = False
    reset_acting_calls: bool = False


PlanSnapshot = tuple[str, str, str, tuple[tuple[str, bool, str | None], ...]]


def _snapshot(plan: Plan) -> PlanSnapshot:
    return (plan.id, plan.task, plan.status,
            tuple((it.text, it.done, it.note) for it in plan.items))


@dataclass(frozen=True)
class PendingEmpty:
    request: EmptyTailQuestion
    snapshot: PlanSnapshot
    step_key: str
    evidence_epoch: object
    trigger: Trigger


@dataclass
class TailState:
    """One session/task's one-shot rescue and empty-tail question.

    The driver resets at task/fork/advance, never copies this to a fork, and
    binds evidence_epoch to its authoritative current action/gate generation.
    Like the existing driver's transient rescue flags, this state is rebuilt
    fresh on service resume; pending tokens/approvals MUST NOT be serialized.
    The plan and raw-task/uncovered-delivery fields keep their existing durable
    driver schema. No harness transport or whole-task approval is stored here.
    """
    step_key: str = ""
    plan_id: str = ""
    task: str = ""
    critic_rescue_used: bool = False
    thrash_rescue_used: bool = False
    sequence: int = 0
    pending: PendingEmpty | None = None

    def reset(self, step_key: str = "", *, plan_id: str = "", task: str = "") -> None:
        self.step_key = step_key
        self.plan_id, self.task = plan_id, task
        self.critic_rescue_used = self.thrash_rescue_used = False
        self.sequence += 1
        self.pending = None

    def fork(self) -> TailState:
        return TailState()


def _persist(source: TailInput) -> None:
    # Same best-effort mirror contract as the original driver. The service
    # writes only in the application's owned directory, never the workspace.
    try:
        source.services.persist(source.plan)
    except OSError as error:
        source.log.emit("loop.plan_persist_error", level="info", error=str(error))


def _matches(source: TailInput, pending: PendingEmpty) -> bool:
    return (pending.snapshot == _snapshot(source.plan) and pending.step_key == source.step_key
            and pending.evidence_epoch == source.evidence_epoch and pending.trigger is source.trigger)


def _rescue_effects(source: TailInput, before: int, after: int, *, changed: bool = True,
                    raw_task: bool = False) -> dict[str, bool]:
    rescue = source.trigger is not Trigger.ADVANCE and changed
    if rescue:
        source.log.emit("loop.stuck_replan", step=source.step_index, before=before, after=after,
                        trigger="verify" if source.trigger is Trigger.CRITIC_STALLED else "thrash")
    return {"reset_failure_counts": rescue, "clear_nudge": rescue and not raw_task,
            "reset_acting_calls": rescue and source.trigger is Trigger.TOOL_THRASH}


@dataclass(frozen=True)
class Proposal:
    """Stateless proposal only: never confirms completion or mutates a plan."""
    status: TailStatus
    steps: tuple[str, ...] | None = None
    missing: tuple[str, ...] = ()


def propose_tail(*, question: Question, task: str, completed: str,
                 completed_steps: tuple[str, ...], remaining: str, evidence: str,
                 trigger: str, research: str, coder_tools: str,
                 tool_names: tuple[str, ...], coverage: Callable, log: EventLog) -> Proposal:
    """One authority for re-derivation, parsing, noise, coverage and tool leaks.

    Display strings are passed unchanged. Coverage receives separately supplied
    authoritative completed steps; only the legacy adapter projects display text.
    """
    text = question(prompts.render("replan", TRIGGER=trigger),
                    prompts.render("replan_user", task=task, completed=completed or "(none)",
                                   remaining=remaining, evidence=evidence or "(no actions recorded yet)"),
                    coder_tools=coder_tools) or ""
    cleaned = planner.json_steps(strip_think(text))
    if cleaned is None:
        return Proposal(TailStatus.ABSENT)
    if not cleaned:
        return Proposal(TailStatus.EMPTY_PENDING, ())
    ask = lambda system, user: question(system, user) or ""
    drop = planner.reasoned_noise_indices(ask, task, cleaned, facts=research)
    if drop:
        drop, refused = planner.surviving_noise_drops(ask, task, cleaned, drop)
        for i, lost in refused.items():
            log.emit("loop.replan_noise_refused", level="warn", lost=lost, step=cleaned[i][:160])
    kept = [s for i, s in enumerate(cleaned) if i not in drop]
    log.emit("loop.replan_noise", dropped=len(drop), kept=len(kept),
             dropped_steps=" | ".join(cleaned[i][:160] for i in sorted(drop)),
             level="warn" if not kept else "info")
    if not kept:
        return Proposal(TailStatus.ALL_NOISE)
    missing = coverage(ask, task, list(completed_steps) + kept)
    if missing:
        log.emit("loop.replan_uncovered", level="warn", missing=", ".join(missing))
        return Proposal(TailStatus.RAW_TASK, missing=tuple(missing))
    leaked = urlgrounding.harness_tool_leaks("\n".join(kept), list(tool_names))
    if leaked:
        log.emit("loop.replan_tool_leak", level="warn", tools=",".join(leaked))
        return Proposal(TailStatus.TOOL_LEAK)
    return Proposal(TailStatus.REPLACED, tuple(kept))


def reassess_compatibility(*, question: Question | None, task: str, completed: str,
                          remaining: str, evidence: str, log: EventLog,
                          coder_tools: str, trigger: str, research: str,
                          tool_names: tuple[str, ...], coverage: Callable,
                          uncovered: list[str] | None = None) -> list[str] | None:
    """Legacy string-only contract, without manufacturing plan or session state."""
    if question is None or not remaining.strip():
        return None
    proposal = propose_tail(
        question=question, task=task, completed=completed,
        completed_steps=tuple(line[2:].strip() for line in (completed or "").splitlines()
                              if line.startswith("- ")),
        remaining=remaining, evidence=evidence, trigger=trigger, research=research,
        coder_tools=coder_tools, tool_names=tool_names, coverage=coverage, log=log)
    if proposal.missing and uncovered is not None:
        uncovered.extend(proposal.missing)
    return list(proposal.steps) if proposal.steps is not None else None


def rederive_tail(source: TailInput, state: TailState) -> TailResult:
    """Detect, judge and settle a nonempty tail; [] remains a pending question.

    No added retries: one re-derivation, the existing noise/loss questions, then
    one completed+remaining coverage question. Bad shape keeps the old tail.
    Rescue one-shots are spent BEFORE asking, including a declined/unchanged
    answer. Ground-truth probe failures do not count as critic stalls.
    """
    if not isinstance(source.trigger, Trigger):
        raise ValueError("Unknown living-plan trigger")
    question = source.services.question
    if question is None or source.synthetic or source.plan_off:
        return TailResult(TailStatus.NOT_APPLICABLE)
    coverage = source.services.coverage
    if (coverage is None or coverage.policy != planner.COVERAGE.policy or not callable(coverage.execute)):
        raise ValueError("Living-plan requires its selected plan-coverage dependency")
    done = [it for it in source.plan.items if it.done]
    remaining = [it for it in source.plan.items if not it.done]
    if not remaining:
        return TailResult(TailStatus.NOT_APPLICABLE)
    if state.pending is not None:
        if _matches(source, state.pending):
            return TailResult(TailStatus.EMPTY_PENDING, (), confirmation=state.pending.request)
        state.pending = None
        return TailResult(TailStatus.STALE)
    same_step = (state.step_key == source.step_key and state.plan_id == source.plan.id
                 and state.task == source.plan.task)
    if source.trigger is Trigger.CRITIC_STALLED:
        if source.critic_fails < STUCK_STEP_REPLAN or (same_step and state.critic_rescue_used):
            return TailResult(TailStatus.NOT_APPLICABLE)
    elif source.trigger is Trigger.TOOL_THRASH:
        if source.acting_calls < STEP_THRASH_REPLAN or (same_step and state.thrash_rescue_used):
            return TailResult(TailStatus.NOT_APPLICABLE)
    if not same_step:
        state.reset(source.step_key, plan_id=source.plan.id, task=source.plan.task)
    if source.trigger is Trigger.CRITIC_STALLED:
        state.critic_rescue_used = True
    elif source.trigger is Trigger.TOOL_THRASH:
        state.thrash_rescue_used = True
    facts = source.services.facts()
    evidence = facts.evidence
    if not facts.routes:
        evidence = (evidence + "\n\n" + prompts.load_map("planner_steers")["fetch_no_structure"]).strip()
    completed = "\n".join(f"- {it.text}" for it in done)
    old_steps = tuple(it.text for it in remaining)
    trigger = ("A step just finished and was verified." if source.trigger is Trigger.ADVANCE else
               "Progress has STALLED on the current step — the plan may be stale or "
               "mis-scoped. No step was just verified.")
    proposal = propose_tail(
        question=question, task=source.plan.task, completed=completed,
        completed_steps=tuple(it.text for it in done),
        remaining="\n".join(f"- {s}" for s in old_steps), evidence=evidence,
        trigger=trigger, research=facts.research, coder_tools=source.coder_tools,
        tool_names=source.tool_names, coverage=coverage.execute, log=source.log)
    if proposal.status in (TailStatus.ABSENT, TailStatus.ALL_NOISE, TailStatus.TOOL_LEAK):
        source.log.emit("loop.replan_noop", step=source.step_index, result="declined", remaining=len(remaining))
        return TailResult(proposal.status)
    if proposal.status is TailStatus.EMPTY_PENDING:
        state.sequence += 1
        request = EmptyTailQuestion(PendingToken(state.sequence), source.plan.task, evidence, source.plan.id)
        state.pending = PendingEmpty(request, _snapshot(source.plan), source.step_key,
                                     source.evidence_epoch, source.trigger)
        return TailResult(TailStatus.EMPTY_PENDING, (), confirmation=request)
    missing = proposal.missing
    if proposal.status is TailStatus.RAW_TASK:
        # Precisely the existing raw-task transition, with no authored replacement
        # step. Driver applies synthetic/plan_off and the one-use uncovered notice.
        source.plan.items = [PlanItem(text=source.plan.task)]
        source.log.emit("loop.replan_reset", level="warn", step=source.step_index,
                        state="raw_task", missing=", ".join(missing))
        _persist(source)
        return TailResult(TailStatus.RAW_TASK, (source.plan.task,), tuple(missing),
                          reset_to_raw_task=True, **_rescue_effects(source, len(old_steps), 1,
                              changed=old_steps != (source.plan.task,), raw_task=True))
    kept = proposal.steps
    if tuple(kept) == old_steps:
        source.log.emit("loop.replan_noop", step=source.step_index, result="unchanged", remaining=len(remaining))
        return TailResult(TailStatus.UNCHANGED, old_steps)
    source.plan.items = done + [PlanItem(text=s) for s in kept]
    source.log.emit("loop.replan", step=source.step_index, before=len(remaining), after=len(kept))
    _persist(source)
    return TailResult(TailStatus.REPLACED, tuple(kept), **_rescue_effects(source, len(old_steps), len(kept)))


def settle_empty(source: TailInput, state: TailState, token: PendingToken,
                 whole_task_approved: bool | None) -> TailResult:
    """Consume only the correlated separate whole-task confirmation.

    Unknown/negative retains all remaining items. A positive prunes the tail,
    persists the plan, and NEVER changes plan.status or releases the task.
    Stale work/plan/task/fork/reset invalidates the pending question.
    """
    pending = state.pending
    if pending is None or pending.request.token != token:
        return TailResult(TailStatus.STALE)
    if not _matches(source, pending):
        state.pending = None
        return TailResult(TailStatus.STALE)
    state.pending = None
    if whole_task_approved is not True:
        source.log.emit("loop.replan_empty_declined", step=source.step_index)
        return TailResult(TailStatus.EMPTY_DECLINED)
    before = sum(not it.done for it in source.plan.items)
    source.plan.items = [it for it in source.plan.items if it.done]
    source.log.emit("loop.replan", step=source.step_index, before=before, after=0)
    _persist(source)
    return TailResult(TailStatus.EMPTY_CONFIRMED, (), **_rescue_effects(source, before, 0))


@dataclass(frozen=True)
class LivingDefinition:
    policy: Policy
    execute: Callable[[TailInput, TailState], TailResult]
    settle: Callable[[TailInput, TailState, PendingToken, bool | None], TailResult]


DEFINITION = LivingDefinition(Policy(
    "experimental-living-plan", "experimental-living-plan", 5, family_id="F50", scope="experimental",
    prompts=("replan", "replan_user", "plan_noise_steps", "plan_drop_check", "plan_drop_check_user", "planner_steers"),
    state="session/task/step-position one-shot critic/thrash rescues; correlated empty-tail pending confirmation; transient on resume; reset on advance/task/fork",
    services=("shared-grounded-evidence", "reasoner-question", "selected-plan-coverage", "tool-menu-adapter", "whole-task-confirmation", "owned-plan-persistence"),
    dependencies=(planner.COVERAGE.policy.id,),
    hooks=(Reference("cria/loop.py", "reassess_remaining"), Reference("cria/loop.py", "Loop._replan_tail"),
           Reference("cria/loop.py", "Loop._renudge_or_replan"), Reference("cria/loop.py", "Loop._replan_if_thrashing"),
           Reference("cria/loop.py", "Loop._advance"), Reference("cria/loop.py", "_session_to_dict"),
           Reference("cria/loop.py", "_session_from_dict")),
    regressions=(Reference("tests/test_living_plan_policy.py", "test_absent_empty_and_replaced_are_distinct"),
                 Reference("tests/test_living_plan_policy.py", "test_rescue_thresholds_one_shots_reset_and_fork"),
                 Reference("tests/test_living_plan_policy.py", "test_coverage_includes_completed_and_raw_task_is_persisted"),
                 Reference("tests/test_living_plan_policy.py", "test_coverage_preserves_the_complete_authoritative_completed_item"),
                 Reference("tests/test_living_plan_policy.py", "test_empty_settlement_rejects_stale_or_unknown_confirmation"),
                 Reference("tests/test_living_plan_policy.py", "test_resume_discards_transient_questions_and_rescue_flags_without_releasing_tail"),
                 Reference("tests/test_living_plan_policy.py", "test_source_reuses_legacy_questions_parsers_and_exact_reask_counts")),
    migrated=False), rederive_tail, settle_empty)
DEFINITIONS = (DEFINITION,)


@dataclass(frozen=True)
class LivingSelection:
    enabled: bool = False
    definition: LivingDefinition | None = None
    # Production binds the caller's actual dependency object once. None keeps
    # explicit standalone opt_in callers, which supply their own services.
    coverage: CoverageDefinition | None = None

    def __post_init__(self):
        if type(self.enabled) is not bool or (not self.enabled and (
                self.definition is not None or self.coverage is not None)):
            raise ValueError("Living-plan stages require explicit experimental consent")
        if self.definition is not None and (not isinstance(self.definition, LivingDefinition)
                or self.definition.policy != DEFINITION.policy
                or not callable(self.definition.execute) or not callable(self.definition.settle)):
            raise ValueError("Incompatible living-plan replacement")
        if self.coverage is not None and (
                self.definition is None or not isinstance(self.coverage, CoverageDefinition)
                or self.coverage.policy != planner.COVERAGE.policy
                or not callable(self.coverage.execute)):
            raise ValueError("Incompatible living-plan coverage dependency")

    @classmethod
    def from_definitions(cls, definitions, *, enabled: bool = False):
        """Bind actual selected objects, without implicitly adding dependencies."""
        if type(enabled) is not bool:
            raise ValueError("Living-plan stages require explicit experimental consent")
        if not enabled:
            return cls()
        wanted = {DEFINITION.policy.id, planner.COVERAGE.policy.id}
        selected = {}
        for definition in definitions:
            policy_id = getattr(getattr(definition, "policy", None), "id", None)
            if policy_id not in wanted:
                continue
            if policy_id in selected:
                raise ValueError("Duplicate living-plan selection: " + policy_id)
            selected[policy_id] = definition
        definition = selected.get(DEFINITION.policy.id)
        if definition is None:
            return cls(True)
        coverage = selected.get(planner.COVERAGE.policy.id)
        if coverage is None:
            raise ValueError("Living-plan requires its selected plan-coverage dependency")
        if next(iter(selected)) != planner.COVERAGE.policy.id:
            raise ValueError("Living-plan coverage dependency must precede living-plan")
        return cls(True, definition, coverage)

    def _check_dependency(self, source: TailInput) -> None:
        if self.coverage is not None and source.services.coverage is not self.coverage:
            raise ValueError("Living-plan must use the same selected coverage object")

    @classmethod
    def opt_in(cls, definition: LivingDefinition | None = DEFINITION):
        return cls(True, definition)

    def run(self, source: TailInput, state: TailState) -> TailResult:
        if self.definition is None:
            return TailResult(TailStatus.NOT_SELECTED)
        self._check_dependency(source)
        return self.definition.execute(source, state)

    def settle(self, source: TailInput, state: TailState, token: PendingToken,
               whole_task_approved: bool | None) -> TailResult:
        if self.definition is None:
            return TailResult(TailStatus.NOT_SELECTED)
        self._check_dependency(source)
        return self.definition.settle(source, state, token, whole_task_approved)
