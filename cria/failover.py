"""Failover executor — classify a request failure, then decide retry / walk-chain / hard-fail.

Faithful port of codex-local's ``routing/src/failover.rs``: ``classify_failure`` (F1–F9),
``decide_action``, and ``walk_chain``, plus a small buffered ``run`` executor that drives them.
Deterministic, no LLM. The classify/decide logic is pure; only ``run`` does I/O (the call + the
backoff sleep, both injected so it's testable).

Under the single-loaded-model posture (one local endpoint), the load-bearing behavior is
**retry-same-once-on-timeout** — the flaky shared-GPU case where a transient timeout / connection
reset would otherwise be a dead turn. Chain-walk matters once distinct endpoints exist (per-role
``base_url``) or cloud roles are enabled.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Sequence


class Failure(Enum):
    RATE_LIMIT = "rate_limit"            # F1: 429, retry-able
    QUOTA_EXHAUSTED = "quota_exhausted"  # F2: 429 + quota/insufficient — waiting won't help
    MODEL_UNAVAILABLE = "unavailable"    # F3: 502/503/504, connection refused/unreachable, unknown
    MODEL_NOT_FOUND = "not_found"        # F4: 404 — config error
    AUTH = "auth"                        # F5: 401/403 — hard-fail
    TIMEOUT = "timeout"                  # F6: 408 or a timeout message
    QUALITY = "quality"                  # F7: response failed a quality check
    CONTEXT_OVERFLOW = "overflow"        # F8: too large for the window
    ROLE_UNRESOLVABLE = "unresolvable"   # F9: a chain role didn't resolve (cloud off / undefined)


@dataclass(frozen=True)
class Behavior:
    retry_same_attempts: int = 2          # rate-limit retries before walking the chain
    rate_limit_default_wait_ms: int = 1000
    rate_limit_max_wait_ms: int = 30000
    retry_same_backoff_ms: int = 500      # the timeout retry-once backoff


# --- actions (a small tagged union) --------------------------------------------------------
@dataclass(frozen=True)
class RetrySame:
    wait_ms: int
    attempt: int


@dataclass(frozen=True)
class NextInChain:
    role: str
    reason: str


@dataclass(frozen=True)
class HardFail:
    reason: str


@dataclass(frozen=True)
class ChainExhausted:
    chain_name: str


def classify_failure(status_code: Optional[int], error_message: str,
                     is_quality_failure: bool = False, is_context_overflow: bool = False) -> Failure:
    """HTTP status + error text → a FailureType, exactly as failover.rs::classify_failure."""
    if is_quality_failure:
        return Failure.QUALITY
    if is_context_overflow:
        return Failure.CONTEXT_OVERFLOW
    low = (error_message or "").lower()
    if status_code == 429:
        if "quota" in low or "insufficient" in low or "usage limit" in low:
            return Failure.QUOTA_EXHAUSTED
        return Failure.RATE_LIMIT
    if status_code in (401, 403):
        return Failure.AUTH
    if status_code == 404:
        return Failure.MODEL_NOT_FOUND
    if status_code in (502, 503, 504):
        return Failure.MODEL_UNAVAILABLE
    if status_code == 408:
        return Failure.TIMEOUT
    if status_code is None:
        if "timeout" in low or "timed out" in low:
            return Failure.TIMEOUT
        return Failure.MODEL_UNAVAILABLE  # connection refused / unreachable / unknown → unavailable
    return Failure.MODEL_UNAVAILABLE


def decide_action(failure: Failure, current_role: str, chain_name: str, chain: Sequence[str],
                  attempt: int, retry_after_ms: Optional[int] = None,
                  behavior: Behavior = Behavior()):
    """After a failure: RetrySame / NextInChain / HardFail / ChainExhausted (port of decide_action)."""
    if failure is Failure.AUTH:
        return HardFail(f"Authentication failed for {current_role}")
    if failure is Failure.RATE_LIMIT:
        if attempt < behavior.retry_same_attempts:
            wait = min(behavior.rate_limit_default_wait_ms if retry_after_ms is None else retry_after_ms,
                       behavior.rate_limit_max_wait_ms)
            return RetrySame(wait, attempt + 1)
        return _walk(current_role, chain_name, chain, "rate limit retries exhausted")
    if failure is Failure.TIMEOUT:
        if attempt < 1:
            return RetrySame(behavior.retry_same_backoff_ms, attempt + 1)
        return _walk(current_role, chain_name, chain, "timeout after retry")
    reason = {
        Failure.QUOTA_EXHAUSTED: "quota exhausted",
        Failure.MODEL_UNAVAILABLE: "model unavailable",
        Failure.MODEL_NOT_FOUND: "model not found (config error?)",
        Failure.QUALITY: "quality check failed",
        Failure.CONTEXT_OVERFLOW: "context overflow — need larger model",
        Failure.ROLE_UNRESOLVABLE: "role not resolvable (cloud disabled or unconfigured)",
    }[failure]
    return _walk(current_role, chain_name, chain, reason)


def _walk(current_role: str, chain_name: str, chain: Sequence[str], reason: str):
    """The next role after ``current_role`` in ``chain``; a role not in the chain restarts at its
    head; past the end → ChainExhausted. Port of failover.rs::walk_chain."""
    chain = list(chain)
    try:
        pos = chain.index(current_role)
        nxt = chain[pos + 1] if pos + 1 < len(chain) else None
    except ValueError:
        nxt = chain[0] if chain else None
    return NextInChain(nxt, reason) if nxt is not None else ChainExhausted(chain_name)


@dataclass
class Attempt:
    role: str
    call: Callable[[], object]  # runs the buffered request against this route's provider, or raises


def run(chain_name: str, attempts: Sequence[Attempt], classify: Callable[[Exception], Failure],
        rlog, *, behavior: Behavior = Behavior(), sleep: Callable[[float], None] = time.sleep):
    """Drive the failover state machine over an ordered list of resolvable routes (``attempts``),
    each a buffered call. Retries the same route (with backoff) or walks to the next per
    ``decide_action``; re-raises on HardFail / ChainExhausted. ``classify`` maps a raised exception
    to a Failure (the caller knows its own error type). Buffered only — a stream can't be retried."""
    roles = [a.role for a in attempts]
    by_role = {a.role: a for a in attempts}
    i, attempt = 0, 0
    while i < len(attempts):
        cur = attempts[i]
        try:
            return cur.call()
        except Exception as e:  # noqa: BLE001 — classify decides what's retryable
            action = decide_action(classify(e), cur.role, chain_name, roles, attempt,
                                   behavior=behavior)
            if isinstance(action, RetrySame):
                attempt = action.attempt
                rlog.emit("route.retry_same", role=cur.role, attempt=attempt, wait_ms=action.wait_ms)
                sleep(action.wait_ms / 1000.0)
                continue
            if isinstance(action, NextInChain):
                nxt = by_role.get(action.role)
                if nxt is None:  # the next role didn't resolve into `attempts` — stop honestly
                    raise
                i, attempt = attempts.index(nxt), 0
                rlog.emit("route.failover", to=action.role, reason=action.reason, chain=chain_name)
                continue
            raise  # HardFail / ChainExhausted
    return None
