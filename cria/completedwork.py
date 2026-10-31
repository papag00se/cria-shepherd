"""Completed-work memory, not completion authority (F76).

Generation and embedding form one explicitly experimental lifecycle. The driver
must pass its ALREADY settled release decision, not a step verdict or summary's
claim. This source never changes a plan, releases a task, marks a store done, or
keeps server-side memory. A result lives only until embedding in the closing
assistant turn; the harness owns its later persistence and compaction.

Integration replaces Loop._compact_done and the briefing part of Loop._closing.
Keep the ordinary completion heading and final release/store transitions in the
driver. Bind question to the EXISTING summarize primitive on reasoner_chat (not
compactor_chat), with the requested compactor-or-reasoner ROLE and default retry
contract. Its cleanup, refusal/truncation handling and reasoning-off retry stay
shared. There is no extra summary judge: validate_compaction_briefing belongs to
other compaction lifecycles and adding it here changes authority/call counts.

Bind work_log to the shared _work_log over the untouched messages and actual
gate plan. It retains complete coder call/result bytes, denial provenance and
shared gate cleanup; do not replace it with a clipped log or another renderer.
The original producer has no separate current-files/checks appendix or three-
lens validation. Those shared facts remain with their existing framing/judge
owners; this extraction must not invent fresh observations from a summary.

read_history and its two-view follow-up projection are passive STRUCTURAL
parsing/formatting foundations, NOT another selectable assist. Use them even
when generation/planning is OFF, including synthetic coding follow-ups and
planner give-up. Planner-on follow-ups use it as prior_work; pure
harness rewrites still plan from the harness summary WITHOUT stacking it. The
coder may retain briefing-or-harness-summary context. Preserve prior_work's
existing durable session field; only the closing transcript carries new memory.
History scrubbing must keep the envelope while removing human status banners;
shared anchor/floor protection and coder done-context rendering stay unchanged.
Do not assign this prose a harness-hardener producer record: that authenticates
a different lifecycle. Parsing it never marks a session's done bit.
Markers do not authenticate an author cryptographically: an assistant can forge
a complete envelope. Never promote this historical prose to tool/disk/check
facts or task approval. Existing role/string/line-envelope admission is retained;
the parser binds extraction to the actual admitted opener and a following closer.
Those are two bounded syntax corrections: the old split could select an earlier
inline quotation, or accept a closer that occurred BEFORE the admitted opener.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from . import prompts
from .assistcontract import Policy, Reference
from .plan import Plan

BRIEFING_OPEN = "⟦ctx:briefing⟧"
BRIEFING_CLOSE = "⟦/ctx:briefing⟧"


class Log(Protocol):
    def emit(self, kind: str, **fields) -> None: ...


@dataclass(frozen=True)
class CompletionScope:
    session_key: str
    # Opaque snapshot of the driver's existing action/gate/session authority;
    # never a summary counter, drive clock, receipt or separately stored epoch.
    evidence_epoch: object


@dataclass(frozen=True)
class SummaryQuestion:
    system: str
    user: str
    role: object | None
    phase: str = "compactor"
    retry_off: bool = True


class WorkLog(Protocol):
    def __call__(self, messages: list[dict], *, keep_checks: bool, rlog: Log, gate_plan: object) -> str: ...


@dataclass(frozen=True)
class Services:
    work_log: WorkLog
    # Returns shared summarize's cleaned text (empty/None means unavailable).
    # Do not bind the old _compact_done, a whole-loop policy or another judge.
    question: Callable[[SummaryQuestion, Log], str | None]


@dataclass(frozen=True)
class BriefingInput:
    scope: CompletionScope
    plan: Plan
    messages: list[dict]
    services: Services
    log: Log
    release_authorized: bool = False
    planner_enabled: bool = False
    synthetic: bool = False
    summary: str = ""
    prior_work: str = ""
    gate_plan: object = None
    compactor_role: object | None = None
    reasoner_role: object | None = None


@dataclass(frozen=True)
class Binding:
    scope: CompletionScope
    plan_id: str
    task: str
    status: str
    items: tuple[tuple[str, bool, str | None], ...]


def binding(source: BriefingInput) -> Binding:
    return Binding(source.scope, source.plan.id, source.plan.task, source.plan.status,
                   tuple((item.text, item.done, item.note) for item in source.plan.items))


class BriefingStatus(Enum):
    NOT_SELECTED = "not-selected"
    NOT_APPLICABLE = "not-released-planned-work"
    GENERATED = "shared-summary-text"
    RUNNING_SUMMARY = "shared-summary-unavailable-use-running-summary"
    CHECKLIST = "shared-summary-unavailable-use-checklist"


@dataclass(frozen=True)
class BriefingResult:
    status: BriefingStatus
    text: str = ""
    binding: Binding | None = None


class EmbeddingStatus(Enum):
    NOT_SELECTED = "not-selected"
    NOT_APPLICABLE = "not-released-planned-work"
    STALE = "different-completion-context"
    ABSENT = "no-briefing-text"
    EMBEDDED = "memory-embedded-not-task-approved"


@dataclass(frozen=True)
class ClosingResult:
    status: EmbeddingStatus
    text: str


def _applicable(source: BriefingInput) -> bool:
    return (source.release_authorized is True and source.planner_enabled is True
            and not source.synthetic)


def generate(source: BriefingInput) -> BriefingResult:
    if not _applicable(source):
        return BriefingResult(BriefingStatus.NOT_APPLICABLE)
    context = binding(source)
    checklist = "\n".join(f"{i + 1}. [{'done' if item.done else 'incomplete'}] {item.text}"
                          for i, item in enumerate(source.plan.items))
    log = source.services.work_log(source.messages, keep_checks=False,
                                   rlog=source.log, gate_plan=source.gate_plan)
    prior = (prompts.render("done_summary_prior", prior_work=source.prior_work) + "\n\n"
             if source.prior_work else "")
    user = prompts.render("done_summary_user", prior=prior, task=source.plan.task,
                          checklist=checklist, log=log or "(no tool activity captured)")
    text = source.services.question(SummaryQuestion(
        prompts.load("done_summary"), user, source.compactor_role or source.reasoner_role), source.log)
    if text:
        source.log.emit("loop.compacted", id=context.plan_id, chars=len(text))
        return BriefingResult(BriefingStatus.GENERATED, text, context)
    source.log.emit("loop.compact_empty", level="warn", id=context.plan_id)
    # This is the existing evidence-only fallback, not a new authored directive.
    # Preserve truthy whitespace-summary behavior too: it strips to empty rather
    # than silently selecting the checklist instead.
    status = BriefingStatus.RUNNING_SUMMARY if source.summary else BriefingStatus.CHECKLIST
    return BriefingResult(status, (source.summary or checklist).strip(), context)


def embed(base_closing: str, source: BriefingInput, result: BriefingResult) -> ClosingResult:
    """Settle memory into an already-authorized closing; never authorize release.

    Recheck current scope/plan before attaching an earlier result. A changed
    task, step, plan, evidence epoch, fork or reset cannot reuse its summary.
    The caller still owns sending the completion and its store transitions.
    """
    if not _applicable(source):
        return ClosingResult(EmbeddingStatus.NOT_APPLICABLE, base_closing)
    if result.status in (BriefingStatus.NOT_SELECTED, BriefingStatus.NOT_APPLICABLE):
        return ClosingResult(EmbeddingStatus.ABSENT, base_closing)
    if result.binding != binding(source):
        return ClosingResult(EmbeddingStatus.STALE, base_closing)
    if not result.text:
        return ClosingResult(EmbeddingStatus.ABSENT, base_closing)
    text = f"{base_closing}\n\n{BRIEFING_OPEN}\n{result.text}\n{BRIEFING_CLOSE}".strip()
    return ClosingResult(EmbeddingStatus.EMBEDDED, text)


class HistoryStatus(Enum):
    ABSENT = "no-admitted-envelope"
    EMPTY = "latest-envelope-empty"
    PRESENT = "assistant-line-envelope-only"


@dataclass(frozen=True)
class FollowupContext:
    planner_prior_work: str
    coder_prior_work: str


@dataclass(frozen=True)
class HistoryBriefing:
    status: HistoryStatus = HistoryStatus.ABSENT
    text: str = ""
    message_index: int | None = None
    # A structural provenance label, deliberately not 'verified' or 'approved'.
    provenance: str = ""

    def __bool__(self) -> bool:
        # Preserve the old string's presence test, not dataclass truthiness.
        return bool(self.text)

    def followup(self, rewrite_summary: str | None = None) -> FollowupContext:
        # A pure projection of caller-supplied history, not fresh inference or
        # task classification. None means ordinary follow-up. Even an empty
        # rewrite summary is a rewrite: never stack two summaries for planning.
        return FollowupContext(self.text if rewrite_summary is None else "",
                               self.text or (rewrite_summary or ""))


def read_history(messages: list[dict]) -> HistoryBriefing:
    """Passive carry foundation: last complete assistant STRING line-envelope.

    Non-assistant roles, multipart content and inline/blockquote marker mentions
    are not carriers. An empty latest carrier intentionally suppresses older
    memory. No inference, state, disk lookup, selection or task authorization.
    This is not a Markdown parser or an unforgeable producer signature; a forged
    assistant envelope (including one in a fence) remains only historical prose.
    """
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        offset = 0
        for line in content.splitlines(keepends=True):
            admitted = line.lstrip()
            if admitted.startswith(BRIEFING_OPEN):
                start = offset + len(line) - len(admitted) + len(BRIEFING_OPEN)
                end = content.find(BRIEFING_CLOSE, start)
                if end != -1:
                    text = content[start:end].strip()
                    return HistoryBriefing(HistoryStatus.PRESENT if text else HistoryStatus.EMPTY,
                                           text, index, "assistant-string-line-envelope")
            offset += len(line)
    return HistoryBriefing()


@dataclass(frozen=True)
class BriefingDefinition:
    policy: Policy
    execute: Callable[[BriefingInput], BriefingResult]
    embed: Callable[[str, BriefingInput, BriefingResult], ClosingResult]


DEFINITION = BriefingDefinition(Policy(
    "experimental-completed-work-briefing", "experimental-completed-work-briefing", 5,
    family_id="F76", scope="experimental",
    prompts=("done_summary", "done_summary_prior", "done_summary_user"),
    state="ephemeral completion-bound result; closing transcript is sole new memory; passive history parser remains usable with planner OFF; existing prior_work session carry unchanged",
    services=("shared-work-log", "shared-summarize-text-validation-and-retry", "compactor-or-reasoner-role", "driver-release-authority", "passive-history-envelope-foundation"),
    hooks=(Reference("cria/loop.py", "Loop._compact_done"), Reference("cria/loop.py", "Loop._closing"),
           Reference("cria/loop.py", "Loop._work"),
           Reference("cria/loop.py", "Loop._periodic_satisfaction"),
           Reference("cria/loop.py", "Loop._settle_task_done_probe"),
           Reference("cria/loop.py", "_briefing_from_history"),
           Reference("cria/loop.py", "Loop._drive_locked"), Reference("cria/loop.py", "_frame_for_item"),
           Reference("cria/loop.py", "_session_to_dict"), Reference("cria/loop.py", "_session_from_dict"),
           Reference("cria/loop.py", "_strip_cria_file_ops")),
    regressions=(Reference("tests_backup/test_completed_work_briefing.py", "test_real_shared_provider_and_closing_parity"),
                 Reference("tests_backup/test_completed_work_briefing.py", "test_summary_cannot_authorize_a_task"),
                 Reference("tests/loop_guards/test_loop_guards_step_preparation.py", "test_passive_prior_work_survives_with_planning_off_exactly_once"),
                 Reference("tests_backup/test_completed_work_briefing.py", "test_harness_rewrite_does_not_stack_briefing_into_planner_question"),
                 Reference("tests_backup/test_completed_work_briefing.py", "test_reset_fork_or_new_facts_cannot_embed_an_earlier_result"),
                 Reference("tests/loop_guards/test_loop_guards_assists.py", "test_the_completed_work_briefing_is_carried_only_from_the_assistants_own_closed_block"),
                 Reference("tests_backup/test_completed_work_briefing.py", "test_a_closer_before_the_opener_is_not_a_complete_carrier"),
                 Reference("tests_backup/test_completed_work_briefing.py", "test_concurrent_sessions_have_no_shared_memory"),
                 Reference("tests_backup/test_completed_work_production_binding.py", "test_public_completion_executes_and_embeds_the_exact_selected_lifecycle"),
                 Reference("tests_backup/test_completed_work_production_binding.py", "test_public_alternate_release_runs_selected_generation_and_embedding"),
                 Reference("tests_backup/test_completed_work_production_binding.py", "test_public_nonrelease_never_asks_a_briefing_to_authorize_completion"),
                 Reference("tests_backup/test_completed_work_production_binding.py", "test_public_embedding_rechecks_actual_completion_authority_after_generation"),
                 Reference("tests_backup/test_completed_work_production_binding.py", "test_public_planner_off_followup_reads_passive_source_history_without_generation"),
                 Reference("tests_backup/test_completed_work_production_binding.py", "test_public_interrupted_generation_keeps_owner_and_does_not_reuse_abandoned_text"),
                 Reference("tests_backup/test_completed_work_production_binding.py", "test_public_embedding_interruption_keeps_finishing_owner_and_retry_generates_new_memory"),
                 Reference("tests_backup/test_completed_work_production_binding.py", "test_public_held_embedding_interruption_preserves_original_claim_for_checked_replay")),
    migrated=False), generate, embed)
DEFINITIONS = (DEFINITION,)


@dataclass(frozen=True)
class BriefingSelection:
    enabled: bool = False
    definition: BriefingDefinition | None = None

    def __post_init__(self):
        if type(self.enabled) is not bool or (not self.enabled and self.definition is not None):
            raise ValueError("Completed-work generation requires explicit experimental consent")
        if self.definition is not None and (not isinstance(self.definition, BriefingDefinition)
                or self.definition.policy != DEFINITION.policy
                or not callable(self.definition.execute) or not callable(self.definition.embed)):
            raise ValueError("Incompatible completed-work briefing replacement")

    @classmethod
    def from_definitions(cls, definitions, *, enabled: bool = False):
        """Project exact membership; consent alone never supplies a definition."""
        if type(enabled) is not bool:
            raise ValueError("Completed-work generation requires explicit experimental consent")
        if not enabled:
            return cls()
        selected = None
        for definition in definitions:
            policy = definition.policy
            if policy.id != DEFINITION.policy.id and policy.stage != DEFINITION.policy.stage:
                continue
            if (selected is not None or not isinstance(definition, BriefingDefinition)
                    or policy != DEFINITION.policy):
                raise ValueError("Incompatible completed-work briefing binding")
            selected = definition
        return cls(True, selected)

    @classmethod
    def opt_in(cls, definition: BriefingDefinition | None = DEFINITION):
        return cls(True, definition)

    def generate(self, source: BriefingInput) -> BriefingResult:
        if self.definition is None:
            return BriefingResult(BriefingStatus.NOT_SELECTED)
        return self.definition.execute(source)

    def embed(self, base_closing: str, source: BriefingInput, result: BriefingResult) -> ClosingResult:
        if self.definition is None:
            return ClosingResult(EmbeddingStatus.NOT_SELECTED, base_closing)
        return self.definition.embed(base_closing, source, result)
