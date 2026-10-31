"""Optional learned-capacity adaptation at the final prepared-wire boundary.

Source-only F55 contract. Upstream still owns parsing, estimator observations,
window facts, fitting, capture custody, HTTP translation and response lifetimes.
Transient recovery wraps this operation; it must not duplicate its refit retry.
No sockets, sleeps, error-text classification or ambient selection live here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import tokenratio
from .assistcontract import Policy, Reference

@dataclass(frozen=True)
class Prepared:
    wire: bytes
    estimate: int
    capture_path: str | None = None


@dataclass(frozen=True)
class Rejection:
    """Already parsed facts, not a new classifier or a copy of response bytes.

    ``real`` and ``window`` retain the shared parser's values and legacy numeric
    semantics. The transport owns the original exception and its single-read raw
    response. Non-HTTP failures have http=False; failed custody prohibits refit.
    """
    source: BaseException
    http: bool = False
    real: object = None
    window: object = None
    custody_intact: bool = True


@dataclass(frozen=True)
class Accepted:
    response: object


@dataclass(frozen=True)
class CapacityInput:
    rejection: Rejection
    prepared: Prepared


@dataclass(frozen=True)
class Refit:
    safety: float


def choose_refit(source: CapacityInput) -> Refit | None:
    """Preserve the existing parsed-count decision, without status/text guesses.

    The original route does not require HTTP 400 or real > window. Those are
    parser/translation facts, not permission to add a stricter policy here.
    """
    rejected, sent = source.rejection, source.prepared
    if not rejected.http or not rejected.custody_intact or not rejected.real or not sent.estimate:
        return None
    return Refit(float(rejected.real) / float(sent.estimate))


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable[[CapacityInput], Refit | None]
    density: Callable[[object], float] = tokenratio.observed


def fit_density(model: object, definition: Definition | None) -> float:
    """Optional learned choice; absence never consults the learned store.

    Mandatory fitting still receives the pre-observation default, at its existing
    level/window applicability. Observations continue independently of selection.
    """
    return tokenratio.DEFAULT_RATIO if definition is None else definition.density(model)


@dataclass(frozen=True)
class NoChangeProvenance:
    """Root-recognized existing exception and its authoritative rejected bytes.

    This is a fact packet, never a replacement exception or inferred marker.
    The adapter recognizes the existing concrete type and retains its identity.
    """
    source: BaseException
    final_wire: bytes


@dataclass(frozen=True)
class Services:
    # prepare MUST perform the normal final-wire floor/integrity/capture path on
    # the original input each time. The closure retains body, stream and logger.
    prepare: Callable[[float | None], Prepared]
    # send owns transport, evidence custody and parsing; it does not retry.
    send: Callable[[Prepared], Accepted | Rejection]
    # Required observations: existing ratio recorder and authoritative limit
    # adoption, including their logs. Called before the optional decision.
    observe: Callable[[CapacityInput], None]
    emit: Callable[..., None]
    # Root supplies concrete existing-type recognition and constructors. Keeping
    # that authority injected permits upstream -> capacitypolicy without any
    # reverse runtime, deferred or type-only import edge.
    recognize_no_change: Callable[[object], NoChangeProvenance | None]
    refit_no_change: Callable[[BaseException, bytes], BaseException]
    caller_no_change: Callable[[BaseException, bytes], BaseException]


@dataclass(frozen=True)
class DispatchResult:
    outcome: Accepted | Rejection
    prepared: Prepared
    attempts: int


def dispatch(services: Services, definition: Definition | None, *,
             caller_refit: object = None,
             model: str | None | Callable[[], str | None] = None) -> DispatchResult:
    """One initial send and at most one CHANGED-wire refit, for either wire mode.

    The exact selected object and callback set are retained for the entire call.
    No pending effect survives return, cancellation or exception; a later outer
    transient retry gets a fresh operation. Typed inner no-change provenance is
    still owned by Upstream and can cross the immediate reasoning-off retry.
    ``model`` may be a factual reader of the caller's prepared body: warning
    metadata reads it only after preparation, never to choose or prepare a call.
    """
    safety = None
    previous: Prepared | None = None
    rejected: Rejection | None = None
    for attempt in range(2):
        prepared = services.prepare(safety)
        provenance = services.recognize_no_change(caller_refit) if attempt == 0 else None
        if provenance is not None and prepared.wire == provenance.final_wire:
            services.emit("upstream.caller_retry_no_change", level="warn", bytes=len(prepared.wire),
                          model=model() if callable(model) else model, est=prepared.estimate)
            raise services.caller_no_change(provenance.source, prepared.wire) from provenance.source
        if previous is not None and prepared.wire == previous.wire:
            assert rejected is not None
            services.emit("upstream.refit_no_change", level="warn", bytes=len(prepared.wire),
                          model=model() if callable(model) else model, est=prepared.estimate)
            # Shared translation retains URL/error logging and the original raw
            # rejection. Never replace this exception with a new text classifier.
            raise services.refit_no_change(rejected.source, prepared.wire) from rejected.source
        outcome = services.send(prepared)
        if isinstance(outcome, Accepted):
            return DispatchResult(outcome, prepared, attempt + 1)
        # Evidence custody is mandatory, not a selected policy's permission.
        # A replacement may choose a different refit, but cannot resend after
        # the shared transport reports loss of the rejection evidence.
        if not outcome.custody_intact:
            return DispatchResult(outcome, prepared, attempt + 1)
        facts = CapacityInput(outcome, prepared)
        # Same observation eligibility as the original parsed-count path. On a
        # second rejection the legacy path performs no second refit observation.
        if attempt == 0 and outcome.http and outcome.custody_intact and outcome.real and prepared.estimate:
            services.observe(facts)
        choice = definition.execute(facts) if attempt == 0 and definition is not None else None
        if choice is None:
            return DispatchResult(outcome, prepared, attempt + 1)
        previous, rejected, safety = prepared, outcome, choice.safety
    # Exhaustion returns the second rejection, not a third request or fallback.
    return DispatchResult(outcome, prepared, 2)


DEFINITION = Definition(Policy(
    "learned-capacity-refit", "capacity-refit", 0, family_id="F55",
    triggers=(("overflow-refit", 0), ("learned-floor-density", 3)),
    state="request-local two-attempt refit; existing model-keyed ratio observations remain shared; no pending delivery state",
    services=("final-wire-preparer", "single-send-parsed-transport", "capacity-observations", "events",
              "existing-no-change-recognition-and-exception-constructors"),
    hooks=(Reference("cria/capacitypolicy.py", "dispatch"),
           Reference("cria/capacitypolicy.py", "fit_density")),
    regressions=(Reference("tests/context_wire_a/test_context_wire_a_capacity.py", "test_a_rejection_is_re_fitted_at_the_measured_density_and_re_sent_once_when_the_bytes_changed"),
                 Reference("tests/context_wire_a/test_context_wire_a_capacity.py", "test_identical_re_fit_bytes_are_never_re_sent_and_a_second_rejection_is_final")),
    migrated=False), choose_refit)
