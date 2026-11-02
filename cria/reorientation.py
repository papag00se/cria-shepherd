"""Post-history-rewrite reorientation, separate from stalled-work judgments.

After a history rewrite the coder is told only typed facts the harness already holds (the files this
session's own landed writes produced); no model writes it an instruction (principles 1 and 2).
The coder's request already carries the typed workspace survey every turn.
"""
from dataclasses import dataclass
from typing import Callable, Protocol

from . import prompts
from .assistcontract import Policy, Reference


class Log(Protocol):
    def emit(self, event: str, **fields) -> None: ...


@dataclass(frozen=True)
class ReorientationInput:
    """Preparation services; an explicit None defers acknowledgement to the caller.

    A supplied consume_rewrite callback is a standalone preparation/reporting
    effect, not evidence that a coder received the prepared message. Shared
    delivery acknowledgement belongs to the caller after successful delivery.
    """
    rewritten: bool
    consume_rewrite: Callable[[], None] | None
    log: Log
    # Typed record of the files this session's own landed writes produced, as
    # (path, survey note) pairs. Absent means no orientation exists.
    written: Callable[[], tuple[tuple[str, str], ...]] | None = None


@dataclass(frozen=True)
class ReorientationResult:
    """consumed reports a completed preparation callback, never shared delivery.

    False also covers explicit deferred acknowledgement, even with a message.
    """
    message: dict | None
    reason: str
    consumed: bool


def _reason(source: ReorientationInput) -> tuple[str | None, str]:
    """What the coder is told after a history rewrite, owned handoff or not: only typed records the
    harness already holds, in no model's words. Omitted when there is no such record, and never an
    instruction, a completion claim or an inspection order (a task may forbid one).

    No author is asked: an authored "confirm the starting state by reading ..." sent a 16K coder to
    `list_dir` first on 8 of 8 and 4 of 8 real replays where the typed survey alone sent it to
    `read_file` on 8 of 8, and an author cannot honour a task that forbids inspection except by guessing."""
    try:
        rows = source.written() if source.written is not None else ()
    except Exception:
        rows = ()
    if not rows:
        return None, "survey-only"
    source.log.emit("loop.reanchor_facts_only", level="info", files=len(rows))
    return prompts.render("reanchor_facts",
                          files="\n".join(f"- {path} ({note})" for path, note in rows)), "facts-only"


def reorient(source: ReorientationInput, *, enabled: bool = True) -> ReorientationResult:
    if not enabled or not source.rewritten:
        return ReorientationResult(None, "not-selected" if not enabled else "no-rewrite", False)
    text, reason = _reason(source)
    if text is None:
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
    prompts=("reanchor_facts", "nudge"),
    state="optional preparation callback after framing; shared delivery acknowledgement caller-owned; no persistent judge cache",
    services=("landed-write-record",),
    hooks=(Reference("cria/loop.py", "Loop._prepare_coder_context"),
           Reference("cria/loop.py", "Loop._drive_single_item")),
    regressions=(Reference("tests/loop_orientation/test_loop_orientation_reorientation.py",
                           "test_a_history_rewrite_tells_the_coder_only_the_landed_write_record"),
                 Reference("tests/loop_orientation/test_loop_orientation_driver_handoff.py",
                           "test_no_continuation_is_followed_by_an_authored_or_canned_inspection"),
                 ),
    migrated=False), reorient)
