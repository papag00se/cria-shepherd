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
  - any ANCHOR message (a ⟦ctx:briefing⟧ handoff / a ___CRIA_GATE_ ground truth) — verbatim,
  - ONE ⟦ctx:rollup⟧ summary of the old middle,
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
BOUNDARY_KEEP_TAIL_TOKENS = 0    # at a verified STEP BOUNDARY keep NO verbatim tail — the completed step's raw
#                                  turns fold ENTIRELY into the rollup. Nothing is lost: the NEXT step rides in
#                                  the caller's authoritative system message, the original task is pinned
#                                  (⟦ctx:task⟧), the API's real endpoint/fields are anchored, and the rollup
#                                  carries the rest. A verbatim tail here would only re-introduce the finished
#                                  step's distracting signals — the exact thing folding at a boundary clears.
#                                  (Without this, force only lowered the TRIGGER; the completed step stayed
#                                  verbatim in the 6000-tok tail and the view GREW step over step — observed
#                                  live: +14KB / ~350 lines between step 1 and step 2.)
RECOMPACT_TOKENS = 4000          # re-summarize only after the unfolded band grows this much (throttle)
SUMMARY_MARKER = "⟦ctx:rollup⟧"     # tags the injected summary — floor-protected + identifiable
TASK_MARKER = "⟦ctx:task⟧"          # tags the pinned original-task header — the session's north star
FACTS_MARKER = "⟦ctx:facts⟧"        # tags the DURABLE fetch ledger (url→status→endpoints) the loop re-injects
CHECKS_MARKER = "⟦ctx:checks⟧"      # tags cria's gate/check-state report — cria's OWN voice, never coder work
SEARCH_MARKER = "⟦ctx:search⟧"      # tags a suppressed search-results read — likewise cria's own, not a tool result
                                    # from cria's own session memory, so the coder keeps the real endpoints it
                                    # already fetched even after the HARNESS compacts the raw result out of its
                                    # own history — else it re-fetches to rediscover them (370-call spec loop).
# cria-SURFACED spec-shape markers — the [API endpoints …] / [response shape …] blocks a web_fetch result
# carries (mirror webfetch.ROUTES_MARKER / SHAPE_MARKER; a test asserts sync). They hold the API's REAL
# endpoint paths + response field names — EXTERNAL ground truth the coder must code against, NOT its own
# mutable identifiers. Anchored so compaction keeps them VERBATIM and the summarizer (which deliberately
# drops identifier names) NEVER folds them — else the exact fields vanish and the coder guesses
# (resolved_addresses → a made-up "cardano_address"), which is a live failure mode.
_SPEC_ROUTES_MARKER = "[API endpoints ("
_SPEC_SHAPE_MARKER = "[response shape —"
# Anchor markers whose messages are ALWAYS kept verbatim — AND, critically, excluded from the
# summarizer input, so cria's OWN prior briefings never become a rollup-of-a-rollup (each round
# summarizing the last round's summary is how a transient hallucination hardened into authoritative
# "Treat this as done" misdirection that inverted the task). ⟦ctx:continuation⟧ (loop's harness-
# compaction reframe) is one such cria-authored summary and MUST be here for the same reason as
# ⟦ctx:briefing⟧. Mirrors loop.BRIEFING_OPEN / loop.CONTINUATION_MARKER / probegate.SECTION_PREFIX
# + webfetch.ROUTES_MARKER / SHAPE_MARKER (selfcompact is low-level; a test asserts sync).
_ANCHOR_MARKERS = ("⟦ctx:briefing⟧", "⟦ctx:continuation⟧", "___CRIA_GATE_", SUMMARY_MARKER, TASK_MARKER,
                   FACTS_MARKER, _SPEC_ROUTES_MARKER, _SPEC_SHAPE_MARKER)


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


def msg_digest(m: dict) -> str:
    """A compact one-line rendering of a message for a summarization transcript: its text plus any
    tool call as ``name(args…)``. Shared by both paths so the rollup input is built the same way."""
    parts = []
    t = _text(m)
    if t.strip():
        parts.append(t)
    for tc in m.get("tool_calls") or []:
        fn = tc.get("function") or {}
        parts.append(f"{fn.get('name', '?')}({str(fn.get('arguments', ''))})")
    return " ".join(p for p in parts if p)


def serialize(messages: list[dict]) -> str:
    """The transcript span → one string fed to the summarizer."""
    return "\n".join(f"{m.get('role')}: {msg_digest(m)}" for m in messages)


def _summary_msg(summary: str) -> dict:
    # This rolls up MID-work turns (the work is NOT necessarily finished) — unlike the loop's
    # completion compaction, which summarizes genuinely-done work. So it must NOT stamp "treat this as
    # done": that blanket done-assertion drove premature completion and suppressed re-doing needed work
    # (the model coasted to "done" over an unresolved pyproject blocker; a summary saying "I fetched the
    # spec" made it skip re-fetching). Frame it truthfully as CONTEXT, and defer to the live results:
    # anything unfinished/failing/blocked still needs doing.
    return {"role": "user", "content": (
        f"{SUMMARY_MARKER} Summary of your earlier turns this session (older turns were elided to keep "
        f"you focused — the recent turns follow verbatim below). Use it as CONTEXT so you don't re-derive "
        f"what you already worked out — but it is a summary, NOT a statement that the task is done: "
        f"anything it describes as unfinished, failing, or blocked still needs doing, and the verbatim "
        f"recent turns and tool results below are the ground truth if they disagree with it:\n{summary}")}


def _task_msg(task: str) -> dict:
    return {"role": "user", "content": (
        f"{TASK_MARKER} Your ORIGINAL task for this session — keep it as your north star and do NOT "
        f"drift onto tangential work; everything below serves THIS:\n{task}")}


def compact(messages: list[dict], summarize, state: CompactState, *,
            trigger_tokens: int = TRIGGER_TOKENS_DEFAULT, keep_tail_tokens: int = KEEP_TAIL_TOKENS,
            recompact_tokens: int = RECOMPACT_TOKENS, pinned_task: str = "", force: bool = False,
            boundary_keep_tail_tokens: int = BOUNDARY_KEEP_TAIL_TOKENS) -> tuple[list[dict], CompactState, bool]:
    """Return (messages, state, applied?). ``summarize(list[dict]) -> str`` folds the old middle into
    a briefing (injected so this is testable without a model). No-op (same list) at/below the token
    trigger, or when there is no middle to compact (the recent tail already spans everything).

    ``force`` (the plan loop passes it at a STEP BOUNDARY) both lowers the trigger AND shrinks the kept tail
    to ``boundary_keep_tail_tokens`` (0 by default → NO verbatim tail) — so the just-verified step's work
    folds ENTIRELY into the ⟦ctx:rollup⟧ (it IS the working-set tail, which a mere trigger drop left verbatim,
    so the view grew step over step). Nothing is lost at a boundary: the next step rides in the caller's
    system message, ``pinned_task`` re-anchors the original task, and anchored messages — a surfaced spec's
    real endpoint/fields (_SPEC_*_MARKER) and cria's own briefings — survive folding VERBATIM. (A boundary
    therefore REQUIRES the caller to pass ``pinned_task``, or the task would fold with the rest.)

    ``pinned_task`` (the conversation's ROOT task, supplied by the caller — it alone can detect the
    task past the harness env-context/reframe) is re-emitted verbatim as a ⟦ctx:task⟧ header on every
    compacted view. Without it the task — a plain user message with no anchor marker — falls into the
    summarizable middle and ERODES across rounds (round 2's rollup summarizes round 1's rollup), which
    is how a plan-off session lost its goal and drifted onto tangential build/deploy work. Pinning it
    keeps the north star authoritative and immune to summary degradation."""
    # At a STEP BOUNDARY keep only a SMALL verbatim tail (boundary_keep_tail_tokens) so the just-finished
    # step's work FOLDS into the rollup; otherwise keep the full working-set tail. force also lowers the
    # trigger so a boundary compacts even below the size trigger (but never a trivial view that fits the tail).
    eff_keep_tail = boundary_keep_tail_tokens if force else keep_tail_tokens
    threshold = eff_keep_tail if force else trigger_tokens
    if sum(_msg_tokens(m) for m in messages) <= threshold:
        return messages, state, False
    head_end = 1 if messages and messages[0].get("role") == "system" else 0
    tail_start = _tail_start(messages, head_end, eff_keep_tail)
    if tail_start <= head_end:
        return messages, state, False

    band_tokens = (sum(_msg_tokens(m) for m in messages[state.covered:tail_start])
                   if head_end <= state.covered <= tail_start else None)
    if not state.summary or band_tokens is None or band_tokens >= recompact_tokens:
        summarizable = [m for m in messages[head_end:tail_start] if not _has_anchor(m)]
        if summarizable:
            fresh = summarize(summarizable)
            # An EMPTY summary must NEVER be adopted. ``summarize`` returns "" on a failed/empty compactor
            # call (it happens — a reasoning model can burn its budget thinking and emit no content), and
            # taking it would advance ``covered`` to tail_start: every folded turn replaced by a rollup
            # header with nothing under it. At a step BOUNDARY (keep NO tail) that is the whole session's
            # work history destroyed by one bad model call — the exact undetectable lie never-truncate
            # exists to prevent. Fail SAFE: fold nothing, keep every turn verbatim, and let the context
            # floor (the one lossless window-fit point) size the request.
            if not fresh.strip():
                return messages, state, False
            state = CompactState(summary=fresh, covered=tail_start)

    covered = max(head_end, min(state.covered, tail_start))
    anchors = [m for m in messages[head_end:covered] if _has_anchor(m)]   # kept verbatim, never elided
    band = messages[covered:tail_start]                                   # old-but-unfolded, verbatim
    # The pinned task leads the compacted view (right after cria's system prompt) so the north star is
    # the first thing the coder reads — never summarized, re-emitted fresh from the caller each turn.
    task = [_task_msg(pinned_task)] if pinned_task.strip() else []
    out = messages[:head_end] + task + anchors + [_summary_msg(state.summary)] + band + messages[tail_start:]
    return out, state, True
