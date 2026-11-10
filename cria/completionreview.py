"""Shared task review; callers retain trigger admission, transport and release.

Completion and scheduled reviews own the satisfaction transition. Focused stuck
reviews share the same evidence and diagnosis but never write completion state.
Tail pruning and optional step advancement remain distinct questions.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from .assistcontract import Policy, Reference
from .completiondiagnosis import DiagnosisStatus


class ReviewTrigger(Enum):
    CLAIM = "reactive-claim"
    PLAN_EXHAUSTED = "reactive-plan-exhausted"
    SCHEDULED = "scheduled"
    STUCK = "stuck"

    @property
    def level(self) -> int:
        return 5 if self in (ReviewTrigger.SCHEDULED, ReviewTrigger.STUCK) else 4


class ReviewStatus(Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    UNKNOWN_TASK = "unknown-task"
    NOT_SELECTED = "not-selected"
    GUIDANCE = "guidance"
    ON_TRACK = "on-track"
    WITHHELD = "withheld"


class SatisfactionState(Protocol):
    latest_satisfaction: bool | None
    latest_satisfaction_evidence: str
    pending_done: str
    pending_done_parts: tuple


class EventLog(Protocol):
    def emit(self, kind: str, **fields) -> None: ...


@dataclass(frozen=True)
class ReviewInput:
    trigger: ReviewTrigger
    task: str
    # Separate lazy sources: the owner, not each driver, composes their order.
    history: Callable[[], str]
    checks: Callable[[], str]
    judge: Callable[[str, str], tuple[bool, str, str]]
    empty_diagnosis: Callable[[], str]
    log: EventLog

    def __post_init__(self):
        if not isinstance(self.trigger, ReviewTrigger):
            raise ValueError("Unknown whole-task review trigger")


@dataclass(frozen=True)
class ReviewResult:
    status: ReviewStatus
    reason: str = ""
    action: str = ""

    def __post_init__(self):
        if not isinstance(self.status, ReviewStatus) or not isinstance(self.reason, str) or not isinstance(self.action, str):
            raise ValueError("Invalid whole-task review outcome")

    @property
    def approved(self) -> bool:
        return self.status is ReviewStatus.APPROVED


def record_satisfaction(state: SatisfactionState, satisfied: bool, evidence: str) -> None:
    """A negative task verdict invalidates held success; only a later true releases it.

    These fields remain in the session's existing durable schema. No cached verdict
    is reused across calls, and no pending probe or task-finalization flag is owned here.
    """
    state.latest_satisfaction = bool(satisfied)
    state.latest_satisfaction_evidence = evidence
    if not satisfied:
        state.pending_done = ""
        state.pending_done_parts = ()


def review_task(source: ReviewInput, state: SatisfactionState) -> ReviewResult:
    # Preserve the claim caller's original-task-unknown contract without inventing
    # a task from compacted history or gathering evidence for an unaskable question.
    if source.trigger is ReviewTrigger.CLAIM and not source.task:
        reason = source.empty_diagnosis()
        record_satisfaction(state, False, reason)
        result = ReviewResult(ReviewStatus.UNKNOWN_TASK, reason)
    else:
        evidence = source.history() + source.checks()
        satisfied, reason, action = source.judge(source.task, evidence)
        if source.trigger is ReviewTrigger.STUCK:
            # A focused diagnosis is never authority to release or reopen a task.
            # Productive unfinished work is not evidence of a stall.
            diagnosis = getattr(reason, "diagnosis_result", None)
            grounded = diagnosis is not None and diagnosis.status is DiagnosisStatus.GROUNDED
            status = (ReviewStatus.ON_TRACK if satisfied or getattr(reason, "on_track", False)
                      else ReviewStatus.GUIDANCE if grounded and reason else ReviewStatus.WITHHELD)
            result = ReviewResult(status, reason, action)
        else:
            record_satisfaction(state, satisfied, reason)
            result = ReviewResult(ReviewStatus.APPROVED if satisfied else ReviewStatus.REJECTED,
                                  reason, action)
    source.log.emit("loop.task_review", assist_id=DEFINITION.policy.id,
                    family_id=DEFINITION.policy.family_id, trigger=source.trigger.value,
                    satisfied=None if source.trigger is ReviewTrigger.STUCK else result.approved,
                    status=result.status.value)
    return result


@dataclass(frozen=True)
class ReviewDefinition:
    policy: Policy
    execute: Callable[[ReviewInput, SatisfactionState], ReviewResult]


DEFINITION = ReviewDefinition(
    Policy("whole-task-review", "whole-task-evaluation", 4, family_id="F34",
           prompts=("satisfaction", "satisfaction_user", "satisfaction_user_composed",
                    "task_review_evidence", "task_review_scheduled", "task_review_focus"),
           state="task-local shared non-terminal attempt cadence; completion/scheduled negatives clear held success; focused results never write satisfaction; no verdict cache",
           services=("qualified-action-history", "gate-observations", "task-judge", "original-task"),
           triggers=tuple((trigger.value, trigger.level) for trigger in ReviewTrigger),
           hooks=tuple(Reference("cria/loop.py", "Loop." + name) for name in
                       ("_review_task", "_reopen_if_unsatisfied", "_periodic_satisfaction", "_done_critic_reason"))
                 + (Reference("cria/loop.py", "_run_task_review"), Reference("cria/loop.py", "_stalled_author")),
           regressions=(Reference("tests/gates_completion/test_gates_completion_cov_review.py", "test_a_negative_verdict_invalidates_held_success_and_a_later_true_releases_it_without_inventing_any"),
                        Reference("tests/gates_completion/test_gates_completion_cov_review.py", "test_a_claim_without_a_known_task_is_unaskable_gathers_nothing_and_clears_held_success"),
                        Reference("tests/gates_completion/test_gates_completion_cov_review.py", "test_every_review_event_names_its_trigger_and_scheduled_reviews_belong_to_the_higher_level"),
                        Reference("tests/loop_guards/test_loop_guards_scenario_lb_sessions.py", "test_each_done_claim_is_settled_by_the_repos_checks_then_the_task_judge"),
                        Reference("tests/loop_guards/test_loop_guards_scenario_lb_sessions.py", "test_the_scheduled_check_steers_on_a_grounded_gap_and_ends_only_after_the_repos_checks_pass"),
                        Reference("tests-before-prune-20261110:tests/loop_guards/test_loop_guards_scenario_lb_sessions.py", "test_one_task_review_finds_a_missing_deliverable_without_waiting_for_checks_or_ordinary_steering"),
                        Reference("tests-before-prune-20261110:tests/loop_guards/test_loop_guards_scenario_lb_sessions.py", "test_stuck_review_shares_task_evidence_delivery_and_cadence_without_completion_or_s1"),
                        Reference("tests-before-prune-20261110:tests/loop_guards/test_loop_guards_scenario_lb_sessions.py", "test_plan_on_focused_review_reaches_the_same_coder_turn_without_a_second_scheduled_review"),
                        ),
           migrated=True),
    review_task)
