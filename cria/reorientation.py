"""Post-history-rewrite reorientation, separate from stalled-work judgments.

The author uses the shared provider transport; F49 owns its distinct name grounding.
No driver policy is imported. The original task is never used as a summary.
"""
from dataclasses import dataclass
import json
import re
from typing import Callable, Protocol

from . import groundedaction, jsontext, prompts, shellshape
from .assistcontract import Policy, Reference

CONTINUATION_MARKER = "⟦ctx:continuation⟧"
DROPPED_PROSE_LEAD = "the handoff summary from that turn did not survive"
MAX_COMMAND_LINES = 3

# F49 gathers unmatched spellings here, not their semantic role. The focused
# question below distinguishes requirement verification from unsupported state.
# Bare word/word prose is deliberately not treated as an invented file.
_GROUNDABLE_NAME = re.compile(
    r"(?:[\w.-]*/(?:[\w.-]+/)*[\w-]+(?:\.[A-Za-z][\w-]*)?)"
    r"|(?:\b[\w-]+\.(?:py|rb|go|java|js|ts|rs|php|json|toml|ya?ml|md|txt|cfg|ini|xml|lock)\b)"
    r"|(?:\bv?\d+\.\d+(?:\.\d+)?\b)")
_PROSE_PAIRING = re.compile(r"^[A-Za-z][\w-]*(?:/[A-Za-z][\w-]*)+$")


def invented_names(text: str, source: str) -> list[str]:
    """Gather unmatched legacy name spellings; this does not judge their meaning."""
    hay = (source or "").lower()
    out: list[str] = []
    for match in _GROUNDABLE_NAME.finditer(text or ""):
        token = match.group(0)
        if not _PROSE_PAIRING.fullmatch(token) and token.lower() not in hay and token not in out:
            out.append(token)
    return out


class Log(Protocol):
    def emit(self, event: str, **fields) -> None: ...


@dataclass(frozen=True)
class ReorientationFacts:
    # Already decoded by the shared content adapter, preserving multimodal handling.
    user_texts: tuple[str, ...]
    reasoner_available: bool
    # Requirements are separate from the historical account, never evidence of work.
    original_task: str = ""
    # Supplied by the handoff owner, not inferred from marker text.
    historical_continuation: str = ""


@dataclass(frozen=True)
class AuthorRequest:
    system: str
    grounding: str
    phase: str = "reasoner"


@dataclass(frozen=True)
class SummaryAuthor:
    """F49 adapter to the shared provider transport, not F44's author policy.

    GroundedActions.vet is intentionally not substituted here: it neither
    implements F49's name check nor preserves its distinct judgment/call order.
    """
    summarize: groundedaction.Summarize
    chat: Callable
    role: object
    log: Log

    def __call__(self, request: AuthorRequest) -> str:
        return self.summarize(self.chat, self.role, request.system, request.grounding,
                              self.log, phase=request.phase)


@dataclass(frozen=True)
class ReorientationInput:
    """Preparation services; an explicit None defers acknowledgement to the caller.

    A supplied consume_rewrite callback is a standalone preparation/reporting
    effect, not evidence that a coder received the prepared message. Shared
    delivery acknowledgement belongs to the caller after successful delivery.
    """
    rewritten: bool
    facts: Callable[[], ReorientationFacts]
    inventory: Callable[[], str]
    author: Callable[[AuthorRequest], str]
    consume_rewrite: Callable[[], None] | None
    log: Log
    # Shared closed-question transport; absent means unknown, never permission.
    judge: Callable[[str, list[str]], str] | None = None


@dataclass(frozen=True)
class ReorientationResult:
    """consumed reports a completed preparation callback, never shared delivery.

    False also covers explicit deferred acknowledgement, even with a message.
    """
    message: dict | None
    reason: str
    consumed: bool


def _head(text: str) -> str:
    text = text.strip()
    return text if len(text) <= 120 else text[:120] + "…"


def _reason(source: ReorientationInput) -> tuple[str | None, str]:
    facts = source.facts()
    owned_summary = (facts.historical_continuation if facts.historical_continuation
                     and facts.historical_continuation in facts.user_texts else "")
    # An owned handoff has a governing task. If guidance cannot be authored
    # and grounded, omit this optional steer instead of imposing inspection.
    # Unowned callers retain their existing compatibility notice.
    canned = None if owned_summary else prompts.load("reanchor")
    summary = owned_summary or next((s for s in reversed(facts.user_texts) if CONTINUATION_MARKER in s), "")
    if not facts.reasoner_available or not summary.strip():
        return canned, "no-summary-or-reasoner"
    if DROPPED_PROSE_LEAD in summary:
        source.log.emit("loop.reanchor_skipped_no_prose", level="info")
        return canned, "no-prose"
    inventory = source.inventory()
    grounding = summary if not inventory else summary + "\n\n" + inventory
    task = facts.original_task.strip()
    independent_task = bool(task and not task.startswith(CONTINUATION_MARKER))
    if not independent_task:
        task = prompts.load("reanchor_missing_task")
    author_context = prompts.render("reanchor_context", task=task, summary=summary,
                                    inventory=inventory)
    system = prompts.load("reanchor_reasoned")
    if owned_summary:
        system = prompts.load("reanchor_task_authority")
        author_context = prompts.render("reanchor_author_context", task=task, summary=summary,
            inventory=inventory, user_context=json.dumps(tuple((text, text == owned_summary)
                for text in facts.user_texts), ensure_ascii=False))
    text = source.author(AuthorRequest(system, author_context))
    if owned_summary and (not text or text.strip() == "KEEP_TASK"):
        return "", "task-preserved"
    if not text:
        return canned, "empty"
    lines = len(shellshape.command_lines(text))
    if "```" in text or lines >= MAX_COMMAND_LINES:
        source.log.emit("loop.reanchor_refused", level="warn", lines=lines, head=_head(text))
        return canned, "script"
    invented = invented_names(text, grounding)
    if invented and independent_task and source.judge is not None:
        # Spelling gathers the candidates, never decides their semantic role.
        # A required verification target need not already exist; an assertion
        # that it exists still needs historical/inventory support.
        accepted = False
        try:
            answer = source.judge(prompts.render("reanchor_name_grounding",
                names=prompts.named_list(invented)), [author_context,
                prompts.render("reanchor_candidate", directive=text)])
            verdict = jsontext.loads(jsontext.strip_think(answer).strip())
            accepted = isinstance(verdict, dict) and set(verdict) == {"grounded"} and verdict["grounded"] is True
        except Exception:
            # The existing canned notice remains available; no authored guidance
            # is released on a provider, parsing, or undecidable judgment error.
            pass
        source.log.emit("loop.reanchor_name_grounding", accepted=accepted,
                        names=prompts.named_list(invented))
        if accepted:
            return text, "authored"
    if invented:
        source.log.emit("loop.reanchor_ungrounded", level="warn",
                        names=prompts.named_list(invented), head=_head(text))
        return canned, "ungrounded"
    return text, "authored"


def reorient(source: ReorientationInput, *, enabled: bool = True) -> ReorientationResult:
    if not enabled or not source.rewritten:
        return ReorientationResult(None, "not-selected" if not enabled else "no-rewrite", False)
    text, reason = _reason(source)
    if text is None or reason == "task-preserved":
        return ReorientationResult(None, reason, False)
    message = {"role": "user", "content": prompts.render("nudge", reason=text)}
    # Optional standalone reporting happens only after successful framing.
    # None leaves shared delivery acknowledgement entirely with the caller.
    if source.consume_rewrite is not None:
        source.consume_rewrite()
    return ReorientationResult(message, reason, source.consume_rewrite is not None)


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable[..., ReorientationResult]


DEFINITION = Definition(Policy(
    "history-rewrite-reorientation", "post-history-rewrite", 4, family_id="F49",
    prompts=("reanchor", "reanchor_reasoned", "reanchor_context", "reanchor_missing_task", "nudge",
             "reanchor_name_grounding", "reanchor_candidate", "reanchor_task_authority", "reanchor_author_context"),
    state="optional preparation callback after framing; shared delivery acknowledgement caller-owned; no persistent judge cache",
    services=("original-task", "continuation-facts", "workspace-inventory", "shared-summary-provider", "shared-closed-question"),
    hooks=(Reference("cria/loop.py", "Loop._prepare_coder_context"),
           Reference("cria/loop.py", "Loop._reasoned_reanchor"),
           Reference("cria/loop.py", "Loop._drive_single_item")),
    regressions=(Reference("tests/test_reorientation_task_authority_current.py", "test_current_task_authority_driver_and_wire"),
                 Reference("tests/test_reorientation_keeps_requirements_separate_from_history.py",
                           "test_preparation_author_receives_task_separately_and_coder_keeps_it"),
                 Reference("tests/test_context_reorientation_policy.py", "test_reasoned_source_parity"),
                 Reference("tests/test_common_context_preparation.py", "test_absent_context_selection_never_runs_optional_leaf_detection"),
                 Reference("tests/test_owned_reorientation_fallbacks.py", "test_owned_unusable_guidance_never_becomes_canned_inspection")),
    migrated=False), reorient)
