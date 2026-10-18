"""Select labelled model-made evidence summaries; retain raw evidence separately.

Lossless action folding and summary transport/rendering remain shared. There is
NO semantic cache or session-owned memory in the original policy. Every execute
owns its input/result; repeated text in another question/task is asked again.
Settlement records only what a consumer actually selected, not judge approval.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from . import dedup, prompts
from .assistcontract import Policy, Reference

SUMMARY_TRIGGER_CHARS = 48000


class Log(Protocol):
    def emit(self, kind: str, **fields) -> None: ...


class SummaryProvider(Protocol):
    # Ordinary shared summarize, including its existing retries/error handling.
    def __call__(self, chat_fn: Callable, role: object, system: str, user: str,
                 rlog: Log, *, phase: str) -> str: ...


class Selection(Enum):
    DISABLED = "disabled"
    RAW = "raw"
    FOLDED = "folded"
    SUMMARY = "summary"


@dataclass(frozen=True)
class Input:
    raw: str
    provider: SummaryProvider
    chat_fn: Callable | None = None
    role: object | None = None
    log: Log | None = None
    compactor_role: object | None = None


@dataclass(frozen=True)
class Result:
    raw: str
    folded: str
    selected: str
    selection: Selection
    folded_actions: int = 0
    # Preserve the provider's full reply, independently of its stripped rendering.
    summary: str | None = None


@dataclass(frozen=True)
class Settlement:
    result: Result
    delivered: str
    # Equality to this invocation's selected evidence, not a completion verdict.
    selected_delivered: bool


def select(source: Input, *, enabled: bool = True) -> Result:
    if not enabled:
        return Result(source.raw, source.raw, source.raw, Selection.DISABLED)
    folded, count = dedup.fold_repeated_actions(source.raw, prompts.load(dedup.REPEAT_NOTE_KEY).strip())
    if count and source.log is not None:
        source.log.emit("evidence.repeats_folded", level="info", folded=count,
                        chars_before=len(source.raw), chars_after=len(folded))
    choice = Selection.FOLDED if count else Selection.RAW
    if len(folded) <= SUMMARY_TRIGGER_CHARS:
        return Result(source.raw, folded, folded, choice, count)
    role = source.compactor_role or source.role
    ready = source.chat_fn is not None and role is not None and source.log is not None
    text = (source.provider(source.chat_fn, role, prompts.load("evidence_summary"),
                            folded, source.log, phase="compactor") if ready else "")
    # Transport returns the ordinary unavailable value; do not add another retry,
    # exception fallback, cache, character clip or latency/output cap here.
    if not text.strip():
        return Result(source.raw, folded, folded, choice, count)
    source.log.emit("evidence.summarised", level="info", chars_before=len(folded), chars_after=len(text))
    selected = prompts.render("evidence_summary_note", summary=text.strip())
    return Result(source.raw, folded, selected, Selection.SUMMARY, count, text)


def settle(result: Result, delivered: str, *, enabled: bool = True) -> Settlement | None:
    if not enabled or result.selection is Selection.DISABLED:
        return None
    return Settlement(result, delivered, delivered == result.selected)


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable[..., Result]
    settle: Callable[..., Settlement | None]


DEFINITION = Definition(Policy(
    "evidence-summary", "judge-evidence-selection", 2, family_id="F71",
    prompts=(dedup.REPEAT_NOTE_KEY, "evidence_summary", "evidence_summary_note"),
    state="stateless per invocation; no cache; raw/folded/selected evidence retained in immutable result",
    services=("dedup.fold_repeated_actions", "shared-summarize-provider", "shared-labelled-summary-renderer"),
    hooks=(Reference("cria/loop.py", "Loop._grounded_evidence"),
           Reference("cria/loop.py", "_satisfaction_evidence"),
           Reference("cria/loop.py", "_dedup_evidence"),
           Reference("cria/loop.py", "_summarised_evidence")),
    regressions=(Reference("tests/test_evidence_summary_policy.py", "test_exact_post_fold_threshold_question_options_and_label"),
                 Reference("tests/test_evidence_summary_policy.py", "test_threshold_uses_real_folded_output_not_raw_size_or_count_reconstruction"),
                 Reference("tests/test_evidence_summary_policy.py", "test_real_lossless_folding_preserves_tool_voice_and_avoids_unnecessary_summary"),
                 Reference("tests/test_evidence_summary_policy.py", "test_compactor_role_choice_and_explicit_role_fallback_preserve_actual_objects"),
                 Reference("tests/test_evidence_summary_policy.py", "test_no_cache_or_cross_task_reuse_and_settlement_retains_its_own_raw_source"),
                 Reference("tests/test_evidence_summary_policy.py", "test_disabled_entire_lifecycle_never_folds_reads_prompts_calls_or_logs"),
                 Reference("tests/test_evidence_summary_policy.py", "test_provider_errors_are_not_silently_reclassified_or_retried"),
                 Reference("tests/test_evidence_summary_policy.py", "test_original_selection_question_events_and_unbounded_reply_parity"),
                 Reference("tests/test_evidence_summary_policy.py", "test_definition_replacement_is_real_selection_without_old_loop_execution"),
                 Reference("tests/test_evidence_summary_policy.py", "test_old_and_source_send_identical_requests_through_actual_shared_transport")),
    migrated=False), select, settle)
