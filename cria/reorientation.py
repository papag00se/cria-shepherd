"""Post-history-rewrite reorientation, separate from stalled-work judgments.

The author uses the shared provider transport; F49 owns its distinct name check.
No driver policy is imported. The original task is never used as a summary.
"""
from dataclasses import dataclass
import re
from typing import Callable, Protocol

from . import groundedaction, prompts, shellshape
from .assistcontract import Policy, Reference

CONTINUATION_MARKER = "⟦ctx:continuation⟧"
DROPPED_PROSE_LEAD = "the handoff summary from that turn did not survive"
MAX_COMMAND_LINES = 3

# This is F49's narrower, deterministic name contract, not the grounded-action
# pipeline. Bare word/word prose is deliberately not treated as an invented file.
_GROUNDABLE_NAME = re.compile(
    r"(?:[\w.-]*/(?:[\w.-]+/)*[\w-]+(?:\.[A-Za-z][\w-]*)?)"
    r"|(?:\b[\w-]+\.(?:py|rb|go|java|js|ts|rs|php|json|toml|ya?ml|md|txt|cfg|ini|xml|lock)\b)"
    r"|(?:\bv?\d+\.\d+(?:\.\d+)?\b)")
_PROSE_PAIRING = re.compile(r"^[A-Za-z][\w-]*(?:/[A-Za-z][\w-]*)+$")


def invented_names(text: str, source: str) -> list[str]:
    """Exact legacy name check; no workspace gathers or reasoner questions."""
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


def _reason(source: ReorientationInput) -> tuple[str, str]:
    canned = prompts.load("reanchor")
    facts = source.facts()
    summary = next((s for s in reversed(facts.user_texts) if CONTINUATION_MARKER in s), "")
    if not facts.reasoner_available or not summary.strip():
        return canned, "no-summary-or-reasoner"
    if DROPPED_PROSE_LEAD in summary:
        source.log.emit("loop.reanchor_skipped_no_prose", level="info")
        return canned, "no-prose"
    inventory = source.inventory()
    grounding = summary if not inventory else summary + "\n\n" + inventory
    text = source.author(AuthorRequest(prompts.load("reanchor_reasoned"), grounding))
    if not text:
        return canned, "empty"
    lines = len(shellshape.command_lines(text))
    if "```" in text or lines >= MAX_COMMAND_LINES:
        source.log.emit("loop.reanchor_refused", level="warn", lines=lines, head=_head(text))
        return canned, "script"
    invented = invented_names(text, grounding)
    if invented:
        source.log.emit("loop.reanchor_ungrounded", level="warn",
                        names=prompts.named_list(invented), head=_head(text))
        return canned, "ungrounded"
    return text, "authored"


def reorient(source: ReorientationInput, *, enabled: bool = True) -> ReorientationResult:
    if not enabled or not source.rewritten:
        return ReorientationResult(None, "not-selected" if not enabled else "no-rewrite", False)
    text, reason = _reason(source)
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
    prompts=("reanchor", "reanchor_reasoned", "nudge"),
    state="optional preparation callback after framing; shared delivery acknowledgement caller-owned; no persistent judge cache",
    services=("continuation-facts", "workspace-inventory", "shared-summary-provider"),
    hooks=(Reference("cria/loop.py", "Loop._prepare_coder_context"),
           Reference("cria/loop.py", "Loop._reasoned_reanchor"),
           Reference("cria/loop.py", "Loop._drive_single_item")),
    regressions=(Reference("tests/test_context_reorientation_policy.py", "test_reasoned_source_parity"),
                 Reference("tests/test_common_context_preparation.py", "test_absent_context_selection_never_runs_optional_leaf_detection")),
    migrated=False), reorient)
