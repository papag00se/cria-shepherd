"""Source-owned bounded transient choices; transport and capacity remain caller-owned.

Not production-bound yet. Facts must come from the existing failure parser *after*
protocol/capacity guards. This module neither catches exceptions nor sends requests.
A selection and its immutable input/result travel together across a delayed retry;
there is no session/global cache, implicit reset, or replacement-policy lookup.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable
from .assistcontract import Policy, Reference

class Failure(Enum):
    RATE_LIMIT = "rate_limit"
    QUOTA_EXHAUSTED = "quota_exhausted"
    MODEL_UNAVAILABLE = "unavailable"
    MODEL_NOT_FOUND = "not_found"
    AUTH = "auth"
    TIMEOUT = "timeout"
    QUALITY = "quality"
    CONTEXT_OVERFLOW = "overflow"
    ROLE_UNRESOLVABLE = "unresolvable"


@dataclass(frozen=True)
class Behavior:
    retry_same_attempts: int = 2
    rate_limit_default_wait_ms: int = 1000
    rate_limit_max_wait_ms: int = 30000
    retry_same_backoff_ms: int = 500


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


Action = RetrySame | NextInChain | HardFail | ChainExhausted


@dataclass(frozen=True)
class FailureFacts:
    failure: Failure
    role: str
    chain_name: str
    chain: tuple[str, ...]
    attempt: int = 0
    retry_after_ms: int | None = None


@dataclass(frozen=True)
class RecoveryChoice:
    """An optional choice, not permission to swallow/rewrite the original exception."""
    action: Action


@dataclass(frozen=True)
class WaitServices:
    # Cancellation raises its original exception. The transport owns abort/close.
    check_cancelled: Callable[[], None]
    sleep: Callable[[float], None]


def wait_for_retry(choice: RecoveryChoice, services: WaitServices) -> None:
    """Settle the chosen delay only; cancellation/failed sleep never sends a retry.

    No clock is sampled: legacy backoff is relative and has no deadline/cache.
    Caller retains the choice until delivery and starts a fresh attempt counter on
    route changes or a new call, just as failover.run does.
    """
    if not isinstance(choice.action, RetrySame):
        return
    services.check_cancelled()
    services.sleep(choice.action.wait_ms / 1000.0)
    services.check_cancelled()


def _walk(facts: FailureFacts, reason: str) -> RecoveryChoice:
    """Preserve ordered first-match walk, including an absent role restarting at head."""
    chain = list(facts.chain)
    try:
        pos = chain.index(facts.role)
        nxt = chain[pos + 1] if pos + 1 < len(chain) else None
    except ValueError:
        nxt = chain[0] if chain else None
    return RecoveryChoice(NextInChain(nxt, reason) if nxt is not None
                          else ChainExhausted(facts.chain_name))


def choose(facts: FailureFacts, behavior: Behavior = Behavior()) -> RecoveryChoice:
    """Own the existing bounded ordering, backoff and exhaustion choices, not parsing."""
    if facts.failure is Failure.AUTH:
        return RecoveryChoice(HardFail(f"Authentication failed for {facts.role}"))
    if facts.failure is Failure.RATE_LIMIT:
        if facts.attempt < behavior.retry_same_attempts:
            wait = min(behavior.rate_limit_default_wait_ms if facts.retry_after_ms is None
                       else facts.retry_after_ms, behavior.rate_limit_max_wait_ms)
            return RecoveryChoice(RetrySame(wait, facts.attempt + 1))
        return _walk(facts, "rate limit retries exhausted")
    if facts.failure is Failure.TIMEOUT:
        if facts.attempt < 1:
            return RecoveryChoice(RetrySame(behavior.retry_same_backoff_ms, facts.attempt + 1))
        return _walk(facts, "timeout after retry")
    reason = {
        Failure.QUOTA_EXHAUSTED: "quota exhausted",
        Failure.MODEL_UNAVAILABLE: "model unavailable",
        Failure.MODEL_NOT_FOUND: "model not found (config error?)",
        Failure.QUALITY: "quality check failed",
        Failure.CONTEXT_OVERFLOW: "context overflow — need larger model",
        Failure.ROLE_UNRESOLVABLE: "role not resolvable (cloud disabled or unconfigured)",
    }[facts.failure]
    return _walk(facts, reason)


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable[[FailureFacts, Behavior], RecoveryChoice]


TRANSIENT_RECOVERY = Definition(Policy(
    id="transient-recovery", stage="upstream-failure", default_level=0,
    family_id="F58", scope="runtime",
    state="Caller-owned per-call attempt; reset on route change/new call; no shared cache",
    services=("parsed failure facts", "cancellation", "relative backoff sleeper"),
    hooks=(Reference("cria/transientpolicy.py", "choose"),),
    regressions=(Reference("tests/loop_orientation/test_loop_orientation_small_owners.py", "test_a_transient_failure_is_retried_routed_or_failed_by_its_kind"),
                 Reference("tests_backup/test_transient_recovery_production_binding.py", "test_original_chat_timeout_bytes")),
), choose)
DEFINITIONS = (TRANSIENT_RECOVERY,)


def selected_choice(definition: Definition | None, facts: Callable[[], FailureFacts],
                    behavior: Behavior = Behavior()) -> RecoveryChoice | None:
    """Absence skips even fact classification; mandatory guards precede this seam."""
    if definition is None:
        return None
    return definition.execute(facts(), behavior)
