"""Literal source contract oracles; no production migration claim."""
from dataclasses import replace

import pytest

from cria import capacitypolicy as policy
from cria.upstream import ContextRefitNoChange, CallerContextRetryNoChange, UpstreamError


FIRST = b'{"messages":[{"role":"user","content":"original evidence"}],"stream":false}'
SECOND = b'{"messages":[{"role":"user","content":"original evidence"}],"stream":false,"max_tokens":64}'
RAW = b'{"error":{"message":"timeout while rejecting context"}}\n'


def rejection(*, real=2000, window=1000, http=True, intact=True):
    error = UpstreamError("timeout while rejecting context", {"message": "timeout while rejecting context"})
    error.code = 400
    error.response_body = RAW
    return policy.Rejection(error, http, real, window, intact)


class Script:
    def __init__(self, wires=(FIRST, SECOND), outcomes=None):
        self.wires = iter(wires)
        self.outcomes = iter(outcomes or (rejection(), policy.Accepted(b"answer\x00\n")))
        self.calls = []
        self.observations = []
        self.events = []
        self.sent = []

    def prepare(self, safety):
        self.calls.append(("prepare", safety))
        return policy.Prepared(next(self.wires), 500, "capture-owned-by-shared")

    def send(self, prepared):
        self.calls.append(("send", prepared.wire))
        self.sent.append(prepared)
        return next(self.outcomes)

    def observe(self, facts):
        self.calls.append(("observe", facts.rejection.real))
        self.observations.append(facts)

    def emit(self, event, **fields):
        self.events.append((event, fields))

    @property
    def services(self):
        return policy.Services(self.prepare, self.send, self.observe, self.emit,
            lambda source: policy.NoChangeProvenance(source, source.final_wire)
                if isinstance(source, ContextRefitNoChange) else None,
            ContextRefitNoChange, CallerContextRetryNoChange)


def test_literal_changed_wire():
    script = Script()
    result = policy.dispatch(script.services, policy.DEFINITION, model="fixture")
    assert script.calls == [("prepare", None), ("send", FIRST), ("observe", 2000),
                            ("prepare", 4.0), ("send", SECOND)]
    assert result == policy.DispatchResult(policy.Accepted(b"answer\x00\n"),
        policy.Prepared(SECOND, 500, "capture-owned-by-shared"), 2)
    assert result.prepared is script.sent[1]
    assert script.events == []


def test_absence_skips_optional_choice_but_keeps_observations_and_preparation():
    script = Script()
    result = policy.dispatch(script.services, None)
    assert script.calls == [("prepare", None), ("send", FIRST), ("observe", 2000)]
    assert result.outcome is script.observations[0].rejection
    assert result.outcome.source.response_body == RAW
    assert result.attempts == 1


def test_exact_selected_replacement_pinned_through_reentrant_preparation():
    script = Script()
    facts_seen = []
    definition = replace(policy.DEFINITION, execute=lambda facts: (facts_seen.append(facts) or policy.Refit(2.75)))
    result = policy.dispatch(script.services, definition)
    assert facts_seen == script.observations
    assert facts_seen[0].prepared is script.sent[0]
    assert script.calls[3] == ("prepare", 2.75)
    assert result.attempts == 2


def test_noop_replacement_is_not_builtin_policy():
    script = Script()
    result = policy.dispatch(script.services, replace(policy.DEFINITION, execute=lambda _: None))
    assert result.attempts == 1
    assert [x.wire for x in script.sent] == [FIRST]


def test_identical_refit_preserves_existing_authority_and_original_bytes():
    rejected = rejection()
    script = Script((FIRST, FIRST), (rejected,))
    with pytest.raises(ContextRefitNoChange) as caught:
        policy.dispatch(script.services, policy.DEFINITION, model="fixture")
    error = caught.value
    assert error.final_wire == FIRST
    assert error.__cause__ is rejected.source
    assert error.response_error is rejected.source.response_error
    assert error.code == 400
    assert rejected.source.response_body == RAW
    assert [x.wire for x in script.sent] == [FIRST]
    assert script.events == [("upstream.refit_no_change", {
        "level": "warn", "bytes": len(FIRST), "model": "fixture", "est": 500})]


@pytest.mark.parametrize("selected", [None, policy.DEFINITION])
def test_nested_immediate_retry_no_change_is_mandatory_even_absent(selected):
    inner = ContextRefitNoChange(rejection().source, FIRST)
    script = Script((FIRST,))
    with pytest.raises(CallerContextRetryNoChange) as caught:
        policy.dispatch(script.services, selected, caller_refit=inner)
    assert caught.value.__cause__ is inner
    assert caught.value.final_wire == FIRST
    assert script.sent == script.observations == []


def test_nested_retry_changed_wire_is_sent_without_reclassifying_provenance():
    inner = ContextRefitNoChange(rejection().source, FIRST)
    script = Script((SECOND,), (policy.Accepted(b""),))
    result = policy.dispatch(script.services, policy.DEFINITION, caller_refit=inner)
    assert result.outcome == policy.Accepted(b"")
    assert [x.wire for x in script.sent] == [SECOND]


@pytest.mark.parametrize("rejected", [rejection(real=None), rejection(real=0),
    rejection(http=False), rejection(intact=False)])
def test_nonrefittable_outcomes_preserve_original_rejection(rejected):
    script = Script(outcomes=(rejected,))
    result = policy.dispatch(script.services, policy.DEFINITION)
    assert result.outcome is rejected
    assert result.attempts == 1
    assert script.observations == []


def test_failed_custody_blocks_adversarial_selected_refit_before_choice():
    rejected = rejection(intact=False)
    script = Script(outcomes=(rejected, policy.Accepted(b"must not arrive")))
    choices = []
    def adversarial(facts):
        choices.append(facts)
        return policy.Refit(2.0)
    selected = replace(policy.DEFINITION, execute=adversarial)
    result = policy.dispatch(script.services, selected)
    assert result.outcome is rejected
    assert result.outcome.source is rejected.source
    assert result.outcome.source.response_body == RAW
    assert result.attempts == 1
    assert script.calls == [("prepare", None), ("send", FIRST)]
    assert choices == []
    assert script.observations == []
    assert script.events == []


def test_second_rejection_never_reobserved_or_retried():
    second = rejection(real=4000)
    script = Script(outcomes=(rejection(), second))
    result = policy.dispatch(script.services, policy.DEFINITION)
    assert result.outcome is second
    assert result.attempts == 2
    assert len(script.observations) == 1


@pytest.mark.parametrize("error", [KeyboardInterrupt(), RuntimeError("cancel"), TimeoutError("transport")])
def test_cancel_and_transport_exceptions_are_not_capacity_retry_types(error):
    script = Script()
    def fail(_):
        raise error
    with pytest.raises(type(error)) as caught:
        policy.dispatch(replace(script.services, send=fail), policy.DEFINITION)
    assert caught.value is error
    # A new operation cannot inherit the cancelled operation's attempt/safety.
    fresh = Script(outcomes=(policy.Accepted(b"fresh"),))
    assert policy.dispatch(fresh.services, policy.DEFINITION).attempts == 1
    assert fresh.calls[0] == ("prepare", None)


def test_density_absence_is_lazy_and_exact_replacement_used(monkeypatch):
    seen = []
    def forbidden(_):
        raise AssertionError("learned lookup while absent")
    monkeypatch.setattr(policy.tokenratio, "observed", forbidden)
    assert policy.fit_density("fixture", None) == 1.8
    definition = replace(policy.DEFINITION, density=lambda model: (seen.append(model) or 3.125))
    assert policy.fit_density("fixture", definition) == 3.125
    assert seen == ["fixture"]


def test_legacy_numeric_and_status_applicability_not_redesigned():
    # Legacy parsed real strings are float-converted; status and density bounds
    # are not reclassified by this policy (only the shared learner clamps).
    assert policy.choose_refit(policy.CapacityInput(rejection(real="2500"), policy.Prepared(FIRST, 500))) == policy.Refit(5.0)
    assert policy.choose_refit(policy.CapacityInput(rejection(real=-10), policy.Prepared(FIRST, 500))) == policy.Refit(-0.02)


def test_injected_constructors_preserve_exact_existing_exception_identity():
    rejected = rejection()
    script = Script((FIRST, FIRST), (rejected,))
    constructed = []
    def inner_factory(source, wire):
        error = ContextRefitNoChange(source, wire)
        constructed.append((source, wire, error))
        return error
    with pytest.raises(ContextRefitNoChange) as inner:
        policy.dispatch(replace(script.services, refit_no_change=inner_factory), policy.DEFINITION)
    assert constructed == [(rejected.source, FIRST, inner.value)]
    assert type(inner.value) is ContextRefitNoChange
    assert inner.value.__cause__ is rejected.source
    assert inner.value.final_wire == FIRST
    assert rejected.source.response_body == RAW

    retry = Script((FIRST,))
    caller_constructed = []
    def caller_factory(source, wire):
        error = CallerContextRetryNoChange(source, wire)
        caller_constructed.append((source, wire, error))
        return error
    with pytest.raises(CallerContextRetryNoChange) as outer:
        policy.dispatch(replace(retry.services, caller_no_change=caller_factory),
                        None, caller_refit=inner.value)
    assert caller_constructed == [(inner.value, FIRST, outer.value)]
    assert type(outer.value) is CallerContextRetryNoChange
    assert outer.value.__cause__ is inner.value
    assert outer.value.response_error is rejected.source.response_error
    assert outer.value.final_wire == FIRST
    assert retry.sent == []


def test_only_root_recognition_authorizes_caller_suppression():
    from types import SimpleNamespace
    # Merely carrying rejected-looking bytes never establishes typed provenance.
    lookalike = SimpleNamespace(final_wire=FIRST)
    script = Script((FIRST,), (policy.Accepted(b"answer"),))
    result = policy.dispatch(script.services, policy.DEFINITION, caller_refit=lookalike)
    assert result.outcome == policy.Accepted(b"answer")
    assert [prepared.wire for prepared in script.sent] == [FIRST]


@pytest.mark.parametrize("path", ["accepted", "rejected", "inner", "caller"])
def test_model_fact_supplier_is_lazy_and_reads_after_preparation_only(path):
    rejected = rejection()
    script = Script((FIRST, FIRST), (rejected,)) if path == "inner" else Script(
        (FIRST,), (policy.Accepted(b"answer"),) if path == "accepted" else (rejected,))
    state, reads = {"model": None}, []
    def prepare(safety):
        result = script.prepare(safety)
        state["model"] = "prepared-model"
        return result
    def model():
        reads.append((state["model"], script.calls[-1]))
        return state["model"]
    services = replace(script.services, prepare=prepare)
    if path in ("inner", "caller"):
        caller = ContextRefitNoChange(rejected.source, FIRST) if path == "caller" else None
        expected = CallerContextRetryNoChange if path == "caller" else ContextRefitNoChange
        with pytest.raises(expected) as caught:
            policy.dispatch(services, policy.DEFINITION, caller_refit=caller, model=model)
        assert caught.value.final_wire == FIRST
        assert reads == [("prepared-model", ("prepare", None if path == "caller" else 4.0))]
        assert script.events[0][1]["model"] == "prepared-model"
    else:
        policy.dispatch(services, None, model=model)
        assert reads == []
        assert script.events == []


def test_semantic_fault_controls_are_detected_and_restored(monkeypatch):
    # Process-local fault: suppress the genuine changed-wire retry. The same
    # literal oracle must reject it, then pass after restoration.
    original = policy.DEFINITION
    with monkeypatch.context() as local:
        local.setattr(policy, "DEFINITION", replace(original, execute=lambda _: None))
        with pytest.raises(AssertionError):
            test_literal_changed_wire()
    test_literal_changed_wire()
    # Independent fault: send stale original bytes despite a changed final fit.
    original_dispatch = policy.dispatch
    def stale(services, definition, **kwargs):
        first = []
        def send(prepared):
            first.append(prepared)
            return services.send(first[0])
        return original_dispatch(replace(services, send=send), definition, **kwargs)
    with monkeypatch.context() as local:
        local.setattr(policy, "dispatch", stale)
        with pytest.raises(AssertionError):
            test_literal_changed_wire()
    test_literal_changed_wire()
