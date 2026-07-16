"""Plan-off self-compaction — cria manages its OWN context, on its own side.

On a long plan-off (direct-coder) session the harness may never compact, so the coder's
history grows unbounded (observed: 331 messages / ~35K tokens). The context floor keeps it
UNDER the window by DROPPING the oldest turns — which loses the information. Self-compaction
instead SUMMARIZES the old middle into one rolling briefing (reasoner-generated), so the
coder gets a lean, information-PRESERVING view: [system] + anchors + [rollup summary] +
a small verbatim band + the recent tail.

Structure kept every turn:
  - the leading system message (cria's coder framing),
  - any ANCHOR message (a ⟦cria:briefing⟧ handoff / a ___CRIA_GATE_ ground truth) — verbatim,
  - ONE ⟦cria:rollup⟧ summary of the old middle,
  - a small VERBATIM band of old-but-not-yet-folded turns (bounded by RECOMPACT_EVERY),
  - the last KEEP_TAIL messages verbatim (the live working set).

The summary is THROTTLED: re-generated only when the unfolded band grows past RECOMPACT_EVERY,
not every turn (one reasoner call amortized over ~20 turns). Boundary splits (a tail/summary
edge landing between an assistant tool_call and its result) are cleaned by the floor's
existing _strip_orphan_tools downstream — self-compaction runs BEFORE the floor.
"""

from __future__ import annotations

from dataclasses import dataclass

# Tunables (code constants, not env — they don't vary by environment).
SELFCOMPACT_TRIGGER = 80   # only compact a plan-off coder view longer than this many messages
KEEP_TAIL = 30             # keep the most recent N messages verbatim (the live working set)
RECOMPACT_EVERY = 20       # re-summarize only after the unfolded band grows this much (throttle)
SUMMARY_MARKER = "⟦cria:rollup⟧"     # tags the injected summary — floor-protected + identifiable
# Anchor markers whose messages are ALWAYS kept verbatim (never summarized away). Mirrors
# loop.BRIEFING_OPEN / probegate.SECTION_PREFIX (selfcompact is low-level; a test asserts sync).
_ANCHOR_MARKERS = ("⟦cria:briefing⟧", "___CRIA_GATE_", SUMMARY_MARKER)


@dataclass
class CompactState:
    summary: str = ""      # the current rolling summary text
    covered: int = 0       # message-count the summary represents (throttle reference)


def _text(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c if isinstance(c, str) else ""


def _has_anchor(m: dict) -> bool:
    t = _text(m)
    return any(mk in t for mk in _ANCHOR_MARKERS)


def _summary_msg(summary: str) -> dict:
    return {"role": "user", "content": (
        f"{SUMMARY_MARKER} Summary of your EARLIER work this session (older turns were elided to keep "
        f"you focused — the recent turns follow verbatim below). Treat this as done; don't redo it:\n"
        f"{summary}")}


def compact(messages: list[dict], summarize, state: CompactState) -> tuple[list[dict], CompactState, bool]:
    """Return (messages, state, applied?). ``summarize(list[dict]) -> str`` folds the old middle into
    a briefing (injected so this is testable without a model). No-op (same list) below the trigger."""
    n = len(messages)
    if n <= SELFCOMPACT_TRIGGER:
        return messages, state, False
    head_end = 1 if messages and messages[0].get("role") == "system" else 0
    tail_start = n - KEEP_TAIL
    if tail_start <= head_end:
        return messages, state, False

    # (Re)generate the summary only when the unfolded band has grown past the throttle — or the first
    # time, or if the cached coverage is stale/ahead of this (shorter) conversation.
    if not state.summary or state.covered < head_end or (tail_start - state.covered) >= RECOMPACT_EVERY:
        summarizable = [m for m in messages[head_end:tail_start] if not _has_anchor(m)]
        if summarizable:
            state = CompactState(summary=summarize(summarizable), covered=tail_start)

    covered = max(head_end, min(state.covered, tail_start))
    anchors = [m for m in messages[head_end:covered] if _has_anchor(m)]   # kept verbatim, never elided
    band = messages[covered:tail_start]                                   # old-but-unfolded, verbatim
    out = messages[:head_end] + anchors + [_summary_msg(state.summary)] + band + messages[tail_start:]
    return out, state, True
