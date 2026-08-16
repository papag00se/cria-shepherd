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

# How DENSE the markers must be before we call it a loop — hits per 1,000 reasoning tokens.
#
# THIS WAS AN ABSOLUTE COUNT (6 markers, any length) AND IT WAS A HARD CAP IN DISGUISE. Because the
# arm only opens past half the budget, a long reply had almost certainly said "actually" or "wait"
# six times by then whatever it was doing. Measured over the 713 captured reasoning traces of 2,000+
# tokens: of the 131 that reach the gate, the old rule aborted 125 — 95%. Principle 6 says runaway is
# caught by rumination, timeout and n_ctx and never by a short hard cap; at 95% this WAS the short
# hard cap.
#
# What it cost, nemotron-elastic/java 0017: "⟦RUMINATION GUARD FIRED⟧ 10 second-guessing markers ·
# ~8254 reasoning tokens · aborted mid-stream". The text it killed was `write_file … pom.xml …
# <?xml version="1.0" encoding="UTF` — cut mid-write. That trace's density is 1.21 markers per 1,000
# tokens, BELOW the 3.84 median: it was aborted for being long, not for circling. The run landed zero
# edits and its final workspace was byte-identical to the seed.
#
# 10 per 1,000 is one marker every hundred tokens, sustained. It sits above the p90 of the measured
# distribution (9.27), so ordinary long reasoning passes, and well below every real spiral in the
# corpus (the densest five run 15-27). It trips 12% of gated traces where the old rule tripped 95%.
# The raw-length backstop at full budget is unchanged and still catches a marker-free runaway.
DEFAULT_MARKER_RATE_PER_1K = 10.0
# Retained so a very short burst cannot trip on rate alone: at the gate this is already implied, and
# it keeps the arm meaningful if a caller lowers the budget.
MIN_MARKERS = 6
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


# A DEAD STREAM: chunks keep arriving and NOTHING cria can read is in them. Not a runaway of bad
# output — an absence of output, for as long as the server will keep going.
#
# Measured, cycle 3 cell 1 (shipping-rates-rb × gemma4), the whole cell in one call:
#     {"message": {"role": "assistant", "content": null}, "finish_reason": "length",
#      "usage": {"completion_tokens": 42744, "prompt_tokens": 6408, "total_tokens": 49152}}
#     "timings": {"predicted_n": 42744, "predicted_ms": 703592}
# 42,744 tokens, 11.7 minutes, and the assembled message is empty — no content, no reasoning, no
# tool-call fragment. 6,408 + 42,744 = 49,152 is n_ctx exactly, so the ONLY thing that stopped it was
# running out of window. Every other call in that run finished under 17 seconds. Cycle 2's run of the
# same cell hit the identical shape (43,616 tokens, 754.9 s) and survived only because it landed with
# clock to spare. Across every log on disk: 14 calls over 300 s in 12 distinct sessions.
#
# WHY THE OTHER TWO GUARDS CANNOT SEE IT. The rumination detector reads reasoning (or content when
# the server does not split it out) and there is none. The degenerate-tail backstop reads a tail that
# never fills, because nothing is being appended to it. Both are looking at bytes; the defect is that
# there are no bytes.
#
# WHY THIS IS NOT A CAP (#6). It never bounds how much a model may produce — a legitimate 40,000-token
# write_file accumulates into tool-call arguments from its first delta and is untouched, which is the
# whole reason the rumination watcher excludes arguments in the first place. This fires only when the
# stream has run this long having accumulated NOTHING, which is a turn that cannot produce a result
# whatever happens next.
DEAD_STREAM_CHUNKS = 400


# A generation that has consumed the whole window it was ever going to get. Not a cap and not a
# latency bound — a statement about what can still be RETURNED.
#
# Measured three times in cycle 3 alone, all identical (cell 1, its re-run, and cell 9 which had
# scored 100% in both previous cycles):
#     completion_tokens 44,058 · prompt_tokens 5,094 · total_tokens 49,152 = n_ctx EXACTLY
#     finish_reason "length" · content empty · tool_calls empty · 720 seconds
# The tokens go into `write_file` ARGUMENTS that never terminate, so nothing assembles and
# `guard_truncation` discards the turn. Twelve minutes, nothing kept.
#
# WHY THE OTHER FOUR BACKSTOPS MISS IT, each for a correct reason:
#   - the rumination watcher excludes tool-call arguments ON PURPOSE, because a real large write
#     looks the same until it ends;
#   - the degenerate-tail backstop needs a periodic tail and this text is not periodic;
#   - DEAD_STREAM_CHUNKS needs NOTHING readable to have arrived, and argument fragments did arrive;
#   - `timeout_seconds` is 7200 on this box, deliberately, because a slow CPU model can take minutes.
#
# COUNTED IN FRAMES. An SSE frame carrying a choices delta is the server saying "here is a token",
# and that is true whatever the delta contains. The first cut counted characters cria had managed to
# accumulate and missed the very call it was built for — 43,873 tokens against 43,932 of room —
# because those tokens arrived in a shape the reader does not collect. A backstop cannot depend on
# understanding what it is backing up.
#
# What is left is arithmetic cria already holds: the window, and the tokens the prompt used. Past
# `window - prompt`, the server will stop with finish_reason=length and the result is discarded
# whatever happens next — so aborting there destroys nothing that was going to survive. It buys back
# only the tail of the generation; the reason to do it is that the turn ends LABELLED, with a notice
# the coder can act on, instead of a silent discard that only shows up as a gap in the timings.
WINDOW_EXHAUSTED_FRACTION = 0.92




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

    def __init__(self, budget: int, rate_per_1k: float = DEFAULT_MARKER_RATE_PER_1K) -> None:
        self.budget = budget if budget and budget > 0 else DEFAULT_REASONING_BUDGET
        self.rate_per_1k = max(float(rate_per_1k), 0.1)

    @classmethod
    def from_reasoning_budget(cls, budget: int | None) -> "Detector":
        """Build from a reasoning-token budget — the caller passes the role's ``output_reserve``
        (a sane proxy for expected output magnitude). ``None`` → the built-in default."""
        return cls(budget if budget else DEFAULT_REASONING_BUDGET, DEFAULT_MARKER_RATE_PER_1K)

    def budget_gate(self) -> int:
        """Below half the budget we NEVER flag, regardless of marker count."""
        return self.budget // 2

    def check(self, reasoning_so_far: str, reasoning_tokens: int) -> dict | None:
        """Return ``{"hits", "reasoning_tokens"}`` when the reasoning looks like a loop (caller
        should abort the in-flight request and re-prompt), else ``None``.

        Two arms, both behind the half-budget gate: marker DENSITY >= the rate, OR raw length >= full
        budget (the length backstop catches a marker-free runaway). Density, not a count, because a
        count is a length test wearing a detector's clothes — see DEFAULT_MARKER_RATE_PER_1K."""
        if reasoning_tokens < self.budget_gate():
            return None
        hits = count_markers(reasoning_so_far)
        dense = hits >= MIN_MARKERS and (hits / max(reasoning_tokens, 1)) * 1000 >= self.rate_per_1k
        if reasoning_tokens >= self.budget or dense:
            return {"hits": hits, "reasoning_tokens": reasoning_tokens}
        return None
