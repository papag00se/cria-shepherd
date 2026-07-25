"""Learned real÷estimate token-density ratio, per model — ported from codex-local's
`local_routing.rs` (`observed_token_ratio` / `record_token_ratio`).

cria's chars/4 estimate UNDERESTIMATES dense content: base64 file-writes and code tokenize at
~1.7 chars/token, so a request the estimate calls 34K can be 82K real — past the window, HTTP 400
("failed after compaction"). Rather than a fixed factor or a `/tokenize` round-trip per request,
LEARN the density from the REAL prompt-token count the server already reports (`usage.prompt_tokens`
on success, `n_prompt_tokens` on an overflow 400) and feed it to the context floor as its safety
factor. The session's early coder calls — same dense content — teach the ratio before a big
compaction request ever fires, so that request budgets correctly on the first try.

Asymmetric EWMA — **rise fast, fall slow** — because the costs are asymmetric: under-estimating the
ratio overflows the window (a hard failure / wasted retry), while over-estimating only spends a
little less context. So a denser-than-seen turn pulls the ratio up hard; a lighter turn barely
lowers our guard. Clamped to ``[DEFAULT_RATIO, MAX_RATIO]``.
"""
from __future__ import annotations

import threading

DEFAULT_RATIO = 1.8   # real÷(chars/4) before any measurement (codex-local's DEFAULT_SAFETY_FACTOR)
MAX_RATIO = 4.0       # cap so one outlier can't starve the budget — but 4.0 = the true 1-token/char
                      # ceiling (dense CJK/base64), so real ~4x density budgets right on the FIRST try
                      # instead of overflowing and paying a wasted _overflow_refit round-trip every turn
_NOTABLE = 0.15       # only report a shift at least this large (so "learned X" logs once)

_ratios: dict[str, float] = {}
_lock = threading.Lock()


def observed(model) -> float:
    """The learned ratio for ``model``, or the default until measured."""
    with _lock:
        return _ratios.get(model or "", DEFAULT_RATIO)


def record(model, real_tokens, estimate) -> float | None:
    """Feed the server's REAL prompt-token count back. ``estimate`` is the chars/4 estimate of the
    SAME (sent) prompt — messages + tool schema — so the value is pure tokenizer density. Returns
    the new ratio only when it shifted notably (for one-time 'learned X' logging), else None."""
    try:
        real = float(real_tokens)
    except (TypeError, ValueError):
        return None
    if real <= 0 or not estimate or estimate <= 0:
        return None
    observed_ratio = min(max(real / estimate, DEFAULT_RATIO), MAX_RATIO)
    key = model or ""
    with _lock:
        cur = _ratios.get(key, DEFAULT_RATIO)
        # rise fast toward a denser turn; fall slow so one light turn doesn't drop our guard.
        new = cur * 0.3 + observed_ratio * 0.7 if observed_ratio > cur else cur * 0.8 + observed_ratio * 0.2
        _ratios[key] = new
    return new if abs(new - cur) > _NOTABLE else None


def reset() -> None:
    """Clear all learned ratios (tests)."""
    with _lock:
        _ratios.clear()
