"""Streaming-time "reasoning loop" detector for local reasoning models — a stdlib port of
codex-local's ``rumination_detector.rs``.

Problem: models like Qwopus 3.5 emit unbounded ``<think>`` content and can spiral into
self-interrupting loops ("Actually, wait. Let me reconsider. Hmm, on second thought…"), burning
the whole window without ever producing output or a tool call. When that happens the response
arrives with ``content=""`` + ``tool_calls=[]`` after minutes of wall time — a silent empty turn —
or it runs straight into the context wall and truncates. This is a DIFFERENT footgun from a big
file write: a write streams as tool-call ARGUMENTS, so the watcher (fed only reasoning/content)
never trips on it. Only runaway thinking does.

Design constraints (kept from the Rust original):
* Pure — no I/O. Safe to call on every chunk in a hot streaming loop.
* Case-insensitive, word-bounded matching so ``waiting`` doesn't fire ``wait``.
* Two independent triggers, both behind a budget gate: (1) repetition — enough second-guessing
  markers; and (2) raw length — reasoning that consumes the WHOLE budget even with zero markers
  (a model can ramble novel-but-useless reasoning for thousands of tokens and never repeat a
  phrase). Conservative: we'd rather miss a loop than abort a legitimate reasoning chain.
"""

from __future__ import annotations

import re

# Phrases that signal the model is second-guessing itself. Matched word-bounded + case-insensitive.
# Deliberately drift/backtracking cues; neutral reasoning words ("therefore", "because") excluded.
RUMINATION_MARKERS = (
    "actually", "wait", "but wait", "hold on", "hmm", "let me reconsider", "on second thought",
    "let me think again", "or maybe", "or perhaps", "rethinking", "reconsider", "going back",
    "scratch that", "nope", "let me re-examine", "let me reexamine", "let me revisit",
    "i'm overthinking", "am i overthinking", "let me start over", "wait no", "actually no",
)

# How many markers a reasoning stream must contain before we call it a loop.
DEFAULT_MARKER_THRESHOLD = 6
# Reasoning-token budget when the role hasn't set output_reserve. Models that can't control
# thinking blow through it; the gate ensures we only flag once they've had a fair shot at normal
# reasoning. The detector's budget is seeded from output_reserve (NOT the hard cap max_tokens).
DEFAULT_REASONING_BUDGET = 4096

# A trailing run of this many IDENTICAL characters marks a stuck/degenerate generation — the model
# emitting one token forever (observed: an exec_command call whose arguments were 44,807 '0's, only
# stopped by the context window at finish_reason=length, a dead turn). This is orthogonal to the
# reasoning-marker/length rumination check and, crucially, safe to run over tool-call ARGUMENTS: a
# legitimate large write_file has varied bytes and never produces thousands of identical consecutive
# characters, so a generous window can't false-fire on real output.
DEGENERATE_RUN_CHARS = 2048


# A tail is degenerate when it is periodic with at least this many whole repeats. Three exact
# repetitions filling 2,048 characters is not something real output does; it is a stuck stream.
#
# This used to bound the repeating UNIT at 8 characters, which missed the expensive case. Walked on
# ada-handles_mellum2_codex_poff_1785714194 call 0014: writing a README example, the model emitted a
# 40,445-character repeating run with a period of **260** — 40,138 tokens over 255 seconds, 66% of
# all model time in an eight-minute run — and the guard returned False the whole way. The rumination
# detector could not cover it either: this ran inside a write_file ARGUMENT, which that watcher
# excludes on purpose.
MIN_DEGENERATE_REPEATS = 3


def degenerate_tail(text: str, window: int = DEGENERATE_RUN_CHARS) -> bool:
    """True when the last ``window`` characters of ``text`` are a single repeated character — a stuck
    single-token stream. Cheap (inspects only the tail), so it can run per streaming stride."""
    if len(text) < window:
        return False
    tail = text[-window:]
    if len(set(tail)) == 1:
        return True
    # ...or a short repeating UNIT. The real streams were two characters wide — `y8y8y8…` for 40,759
    # tokens (five minutes of a fifteen-minute run) and `v5v5v5…` inside the compactor, both on
    # ada-handles_mellum2_codex_pon_1785628543. A single-character test cannot see either. Bounded to
    # short units: a genuinely repeating 8-character block is degenerate, a repeating paragraph is
    # rumination and belongs to the detector above, not here.
    return _smallest_period(tail) <= len(tail) // MIN_DEGENERATE_REPEATS


def _smallest_period(s: str) -> int:
    """The shortest string whose repetition builds ``s`` — allowing a PARTIAL final block. Returns
    ``len(s)`` when ``s`` is not periodic at all.

    KMP's failure function, O(n), one pass, every unit size at once. The obvious one-liner
    ``(s+s).index(s,1)`` was tried first and is wrong here: it only finds the period when the period
    DIVIDES the length. The measured stream had a 255-character period in a 2,048-character window —
    8.03 repeats — so the rotation test reported "not periodic" on the exact case this exists for.
    Real output never runs three whole repeats of any block through the whole window; a stuck stream
    always does."""
    n = len(s)
    if n < 2:
        return n
    fail = [0] * n
    k = 0
    for i in range(1, n):
        while k and s[i] != s[k]:
            k = fail[k - 1]
        if s[i] == s[k]:
            k += 1
        fail[i] = k
    return n - fail[n - 1]


# Longest-first so a multi-word marker ("but wait") is preferred over its substring ("wait") at
# the same position. `\b` behaves for these alternations because every marker starts and ends on a
# word character. re.IGNORECASE for case-insensitive matching.
_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(m) for m in sorted(RUMINATION_MARKERS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def count_markers(text: str) -> int:
    """How many rumination markers appear in ``text`` (non-overlapping, word-bounded)."""
    return len(_RE.findall(text or ""))


def estimate_reasoning_tokens(text: str) -> int:
    """Rough char→token heuristic (~4 chars/token), for when the stream hasn't reported a count."""
    return len(text or "") // 4


class Detector:
    """Stateless rumination check. Construct one per role (holds only budget + threshold); the
    ``check`` call is pure, so a single instance is safely shared across concurrent streams."""

    def __init__(self, budget: int, threshold: int = DEFAULT_MARKER_THRESHOLD) -> None:
        self.budget = budget if budget and budget > 0 else DEFAULT_REASONING_BUDGET
        self.threshold = max(threshold, 1)

    @classmethod
    def from_reasoning_budget(cls, budget: int | None) -> "Detector":
        """Build from a reasoning-token budget — the caller passes the role's ``output_reserve``
        (a sane proxy for expected output magnitude). ``None`` → the built-in default."""
        return cls(budget if budget else DEFAULT_REASONING_BUDGET, DEFAULT_MARKER_THRESHOLD)

    def budget_gate(self) -> int:
        """Below half the budget we NEVER flag, regardless of marker count."""
        return self.budget // 2

    def check(self, reasoning_so_far: str, reasoning_tokens: int) -> dict | None:
        """Return ``{"hits", "reasoning_tokens"}`` when the reasoning looks like a loop (caller
        should abort the in-flight request and re-prompt), else ``None``.

        Two arms, both behind the half-budget gate: markers ≥ threshold, OR raw length ≥ full
        budget (the length backstop catches a marker-free runaway)."""
        if reasoning_tokens < self.budget_gate():
            return None
        hits = count_markers(reasoning_so_far)
        if reasoning_tokens >= self.budget or hits >= self.threshold:
            return {"hits": hits, "reasoning_tokens": reasoning_tokens}
        return None
