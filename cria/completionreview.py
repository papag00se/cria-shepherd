"""Authoritative whole-task evaluation; callers still own scheduling and release.

Tail-pruning and step verification are different questions, not consumers of
this state-writing policy. Evidence helpers and the response reader are shared
services; this unit owns their composition, judgment and satisfaction transition.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from .assistcontract import Policy, Reference


class ReviewTrigger(Enum):
    CLAIM = "reactive-claim"
    PLAN_EXHAUSTED = "reactive-plan-exhausted"
    SCHEDULED = "scheduled"

    @property
    def level(self) -> int:
        return 5 if self is ReviewTrigger.SCHEDULED else 4


class ReviewStatus(Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    UNKNOWN_TASK = "unknown-task"
    NOT_SELECTED = "not-selected"


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
        record_satisfaction(state, satisfied, reason)
        result = ReviewResult(ReviewStatus.APPROVED if satisfied else ReviewStatus.REJECTED,
                              reason, action)
    source.log.emit("loop.task_review", assist_id=DEFINITION.policy.id,
                    family_id=DEFINITION.policy.family_id, trigger=source.trigger.value,
                    satisfied=result.approved, status=result.status.value)
    return result


@dataclass(frozen=True)
class ReviewDefinition:
    policy: Policy
    execute: Callable[[ReviewInput, SatisfactionState], ReviewResult]


DEFINITION = ReviewDefinition(
    Policy("whole-task-review", "whole-task-evaluation", 4, family_id="F34",
           prompts=("satisfaction", "satisfaction_user", "satisfaction_user_composed"),
           state="durable session satisfaction barrier; negative clears held success; no verdict cache",
           services=("qualified-action-history", "gate-observations", "task-judge", "original-task"),
           triggers=tuple((trigger.value, trigger.level) for trigger in ReviewTrigger),
           hooks=tuple(Reference("cria/loop.py", "Loop." + name) for name in
                       ("_review_task", "_reopen_if_unsatisfied", "_periodic_satisfaction", "_done_critic_reason")),
           regressions=(Reference("tests/test_whole_task_evaluation.py",
                                  "test_full_judge_bodies_events_and_review_state_match_through_both_real_drivers"),
                        Reference("tests/test_whole_task_evaluation.py",
                                  "test_reactive_real_drivers_use_the_same_question_but_keep_their_release_and_retry_owners")),
           migrated=True),
    review_task)
