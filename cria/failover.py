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
from typing import Callable, Optional, Sequence

from . import generation, transientpolicy
from .transientpolicy import (Failure, Behavior, RetrySame, NextInChain, HardFail, ChainExhausted)


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
    """Legacy explicit policy API; optional execution uses its captured selection instead."""
    facts = transientpolicy.FailureFacts(failure, current_role, chain_name, tuple(chain),
                                         attempt, retry_after_ms)
    return transientpolicy.choose(facts, behavior).action


@dataclass
class Attempt:
    role: str
    call: Callable[[], object]  # runs the buffered request against this route's provider, or raises


def run(chain_name: str, attempts: Sequence[Attempt], classify: Callable[[Exception], Failure],
        rlog, *, behavior: Behavior = Behavior(), sleep: Callable[[float], None] = time.sleep):
    """Capture one synchronous operation's policy and services before invoking any route."""
    from . import assistruntime
    runtime = assistruntime.current()
    captured = tuple(Attempt(a.role, a.call) for a in attempts)
    with assistruntime.bound(runtime):
        return _run(chain_name, captured, classify, rlog, behavior=behavior, sleep=sleep,
                    definition=runtime.transient_recovery)


def _run(chain_name, attempts, classify, rlog, *, behavior, sleep, definition):
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
            if generation.is_protocol_error(getattr(e, "response_error", None)):
                raise
            choice = transientpolicy.selected_choice(definition,
                lambda: transientpolicy.FailureFacts(classify(e), cur.role, chain_name,
                                                       tuple(roles), attempt), behavior)
            if choice is None:
                raise
            action = choice.action
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
