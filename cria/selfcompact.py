"""Plan-off self-compaction — cria manages its OWN context, on its own side.

On a long plan-off (direct-coder) session the harness may never compact, so the coder's
history grows unbounded (observed: 331 messages / ~35K tokens). The context floor keeps it
UNDER the window by DROPPING the oldest turns — which loses the information. Self-compaction
instead SUMMARIZES the old middle into one rolling briefing (reasoner-generated), so the
coder gets a lean, information-PRESERVING view: [system] + anchors + [rollup summary] +
a small verbatim band + the recent tail.

Everything is measured in TOKENS, not message count — the real constraint is the context
window, and a few huge file reads matter more than many tiny turns (the same currency the
floor uses). Structure kept every turn:
  - the leading system message (cria's coder framing),
  - any ANCHOR message (a ⟦cria:briefing⟧ handoff / a ___CRIA_GATE_ ground truth) — verbatim,
  - ONE ⟦cria:rollup⟧ summary of the old middle,
  - a small VERBATIM band of old-but-not-yet-folded turns (bounded by RECOMPACT_TOKENS),
  - the recent tail up to KEEP_TAIL_TOKENS verbatim (the live working set).

The summary is THROTTLED: re-generated only when the unfolded band grows past RECOMPACT_TOKENS,
not every turn (one reasoner call amortized over many turns). Boundary splits (an edge landing
between an assistant tool_call and its result) are cleaned by the floor's existing
_strip_orphan_tools downstream — self-compaction runs BEFORE the floor.
"""

from __future__ import annotations

from dataclasses import dataclass

from .content_reduce import est_tokens

# Tunables in TOKENS. TRIGGER is operator-tunable via [context] trigger_compaction; the rest are
# code constants (they don't vary by environment).
TRIGGER_TOKENS_DEFAULT = 16384   # start compacting a plan-off view once it exceeds this many tokens
KEEP_TAIL_TOKENS = 6000          # keep the most recent turns verbatim, up to this many tokens
RECOMPACT_TOKENS = 4000          # re-summarize only after the unfolded band grows this much (throttle)
SUMMARY_MARKER = "⟦cria:rollup⟧"     # tags the injected summary — floor-protected + identifiable
# Anchor markers whose messages are ALWAYS kept verbatim. Mirrors loop.BRIEFING_OPEN /
# probegate.SECTION_PREFIX (selfcompact is low-level; a test asserts sync).
_ANCHOR_MARKERS = ("⟦cria:briefing⟧", "___CRIA_GATE_", SUMMARY_MARKER)


@dataclass
class CompactState:
    summary: str = ""      # the current rolling summary text
    covered: int = 0       # message INDEX the summary represents up to (throttle reference)


def _text(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c if isinstance(c, str) else ""


def _msg_tokens(m: dict) -> int:
    t = _text(m)
    for tc in m.get("tool_calls") or []:
        t += " " + str((tc.get("function") or {}).get("arguments") or "")
    return est_tokens(t)


def _has_anchor(m: dict) -> bool:
    t = _text(m)
    return any(mk in t for mk in _ANCHOR_MARKERS)


def _tail_start(messages: list[dict], head_end: int, budget_tokens: int) -> int:
    """The lowest index i (> head_end) such that messages[i:] fits in ``budget_tokens`` — i.e. the
    recent verbatim working set. Keeps at least one message."""
    acc = 0
    i = len(messages)
    while i > head_end + 1:
        t = _msg_tokens(messages[i - 1])
        if acc + t > budget_tokens:
            break
        acc += t
        i -= 1
    return i


def _summary_msg(summary: str) -> dict:
    return {"role": "user", "content": (
        f"{SUMMARY_MARKER} Summary of your EARLIER work this session (older turns were elided to keep "
        f"you focused — the recent turns follow verbatim below). Treat this as done; don't redo it:\n"
        f"{summary}")}


def compact(messages: list[dict], summarize, state: CompactState, *,
            trigger_tokens: int = TRIGGER_TOKENS_DEFAULT, keep_tail_tokens: int = KEEP_TAIL_TOKENS,
            recompact_tokens: int = RECOMPACT_TOKENS) -> tuple[list[dict], CompactState, bool]:
    """Return (messages, state, applied?). ``summarize(list[dict]) -> str`` folds the old middle into
    a briefing (injected so this is testable without a model). No-op (same list) at/below the token
    trigger, or when there is no middle to compact (the recent tail already spans everything)."""
    if sum(_msg_tokens(m) for m in messages) <= trigger_tokens:
        return messages, state, False
    head_end = 1 if messages and messages[0].get("role") == "system" else 0
    tail_start = _tail_start(messages, head_end, keep_tail_tokens)
    if tail_start <= head_end:
        return messages, state, False

    band_tokens = (sum(_msg_tokens(m) for m in messages[state.covered:tail_start])
                   if head_end <= state.covered <= tail_start else None)
    if not state.summary or band_tokens is None or band_tokens >= recompact_tokens:
        summarizable = [m for m in messages[head_end:tail_start] if not _has_anchor(m)]
        if summarizable:
            state = CompactState(summary=summarize(summarizable), covered=tail_start)

    covered = max(head_end, min(state.covered, tail_start))
    anchors = [m for m in messages[head_end:covered] if _has_anchor(m)]   # kept verbatim, never elided
    band = messages[covered:tail_start]                                   # old-but-unfolded, verbatim
    out = messages[:head_end] + anchors + [_summary_msg(state.summary)] + band + messages[tail_start:]
    return out, state, True
