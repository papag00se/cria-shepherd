"""Independent literal oracles for the source-only F58 seam. No transport/executor."""
from dataclasses import replace

import pytest

from cria import transientpolicy as f, transientpolicy as p


@pytest.mark.parametrize("failure,attempt,delay,expected", [
    (f.Failure.TIMEOUT, 0, None, f.RetrySame(500, 1)),
    (f.Failure.TIMEOUT, 1, None, f.NextInChain("backup", "timeout after retry")),
    (f.Failure.RATE_LIMIT, 0, None, f.RetrySame(1000, 1)),
    (f.Failure.RATE_LIMIT, 1, 9876, f.RetrySame(9876, 2)),
    (f.Failure.RATE_LIMIT, 0, 0, f.RetrySame(0, 1)),
    (f.Failure.RATE_LIMIT, 1, 90000, f.RetrySame(30000, 2)),
    (f.Failure.RATE_LIMIT, 2, 7, f.NextInChain("backup", "rate limit retries exhausted")),
    (f.Failure.AUTH, 0, None, f.HardFail("Authentication failed for primary")),
    (f.Failure.QUOTA_EXHAUSTED, 0, None, f.NextInChain("backup", "quota exhausted")),
    (f.Failure.MODEL_UNAVAILABLE, 0, None, f.NextInChain("backup", "model unavailable")),
    (f.Failure.MODEL_NOT_FOUND, 0, None, f.NextInChain("backup", "model not found (config error?)")),
    (f.Failure.QUALITY, 0, None, f.NextInChain("backup", "quality check failed")),
    (f.Failure.CONTEXT_OVERFLOW, 0, None, f.NextInChain("backup", "context overflow — need larger model")),
    (f.Failure.ROLE_UNRESOLVABLE, 0, None, f.NextInChain("backup", "role not resolvable (cloud disabled or unconfigured)")),
])
def test_literal_choices(failure, attempt, delay, expected):
    facts = p.FailureFacts(failure, "primary", "roles", ("primary", "backup"), attempt, delay)
    assert p.choose(facts) == p.RecoveryChoice(expected)


def test_exhaustion_and_route_reset_are_call_owned():
    facts = p.FailureFacts(f.Failure.TIMEOUT, "one", "solo", ("one",), 1)
    assert p.choose(facts) == p.RecoveryChoice(f.ChainExhausted("solo"))
    assert p.choose(replace(facts, attempt=0)) == p.RecoveryChoice(f.RetrySame(500, 1))
    assert facts.attempt == 1


def test_absence_is_lazy_and_replacement_owns_decision():
    def forbidden():
        raise AssertionError("classification must not run")
    assert p.selected_choice(None, forbidden) is None
    seen = []
    owner = p.Definition(p.TRANSIENT_RECOVERY.policy,
                         lambda facts, behavior: seen.append(facts) or p.RecoveryChoice(f.RetrySame(17, 4)))
    facts = p.FailureFacts(f.Failure.AUTH, "a", "a", ("a",))
    choice = p.selected_choice(owner, lambda: facts)
    events = []
    p.wait_for_retry(choice, p.WaitServices(lambda: events.append("cancel"),
                                           lambda seconds: events.append(seconds)))
    assert seen == [facts]
    assert events == ["cancel", .017, "cancel"]
    assert choice == p.RecoveryChoice(f.RetrySame(17, 4))


def test_cancel_before_and_after_wait_preserves_identity():
    class Cancelled(BaseException):
        pass
    error = Cancelled("cancelled by caller")
    for cancel_at in (1, 2):
        events = []
        checks = []
        def check():
            checks.append(1)
            if len(checks) == cancel_at:
                raise error
        with pytest.raises(Cancelled) as caught:
            p.wait_for_retry(p.RecoveryChoice(f.RetrySame(500, 1)),
                             p.WaitServices(check, events.append))
        assert caught.value is error
        assert events == ([] if cancel_at == 1 else [.5])


def test_sleep_failure_is_not_reclassified_and_no_post_check():
    error = OSError("sleeper stopped")
    events = []
    def sleep(seconds):
        events.append(seconds)
        raise error
    with pytest.raises(OSError) as caught:
        p.wait_for_retry(p.RecoveryChoice(f.RetrySame(1000, 1)),
                         p.WaitServices(lambda: events.append("check"), sleep))
    assert caught.value is error
    assert events == ["check", 1.0]


def test_independent_interleaved_choices_and_nonretry_silence():
    a = p.choose(p.FailureFacts(f.Failure.RATE_LIMIT, "a", "x", ("a",), 0, 3210))
    b = p.choose(p.FailureFacts(f.Failure.TIMEOUT, "b", "x", ("b",), 0))
    events = []
    services = p.WaitServices(lambda: None, events.append)
    p.wait_for_retry(b, services)
    p.wait_for_retry(a, services)
    p.wait_for_retry(p.RecoveryChoice(f.HardFail("stop")), services)
    assert events == [.5, 3.21]


def test_explicit_behavior_and_sleeper_fault_control(monkeypatch):
    facts = p.FailureFacts(f.Failure.RATE_LIMIT, "a", "solo", ("a",), 0, 5000)
    behavior = f.Behavior(retry_same_attempts=1, rate_limit_default_wait_ms=19,
                          rate_limit_max_wait_ms=2345, retry_same_backoff_ms=91)
    assert p.choose(facts, behavior) == p.RecoveryChoice(f.RetrySame(2345, 1))
    assert p.choose(replace(facts, attempt=1), behavior) == p.RecoveryChoice(f.ChainExhausted("solo"))
    assert p.choose(replace(facts, failure=f.Failure.TIMEOUT), behavior) == p.RecoveryChoice(f.RetrySame(91, 1))
    def oracle():
        events = []
        p.wait_for_retry(p.RecoveryChoice(f.RetrySame(2345, 1)),
                         p.WaitServices(lambda: events.append("check"), events.append))
        assert events == ["check", 2.345, "check"]
    oracle()
    with monkeypatch.context() as patch:
        patch.setattr(p, "wait_for_retry", lambda choice, services: services.sleep(0))
        with pytest.raises(AssertionError):
            oracle()
    oracle()


def test_downward_ownership_ignores_poisoned_legacy_decision(monkeypatch):
    # Before correction, the 27-test candidate forwarded into this function:
    # its injected illegal second timeout retry changed Source's output. The
    # same semantic poison must now leave the Source decision unchanged.
    from cria import failover as legacy
    facts = p.FailureFacts(p.Failure.TIMEOUT, "a", "solo", ("a",), 1)
    expected = p.RecoveryChoice(p.ChainExhausted("solo"))
    assert p.choose(facts) == expected
    calls = []
    with monkeypatch.context() as patch:
        def poison(*args, **kwargs):
            calls.append(args)
            return p.RetrySame(500, 2)
        patch.setattr(legacy, "decide_action", poison)
        assert p.choose(facts) == expected
        assert calls == []
    assert p.choose(facts) == expected


@pytest.mark.parametrize("role,chain,expected", [
    ("absent", ("first", "last"), p.NextInChain("first", "model unavailable")),
    ("absent", (), p.ChainExhausted("roles")),
    ("last", ("first", "last"), p.ChainExhausted("roles")),
    ("same", ("same", "same", "tail"), p.NextInChain("same", "model unavailable")),
])
def test_literal_walk_order(role, chain, expected):
    assert p.choose(p.FailureFacts(p.Failure.MODEL_UNAVAILABLE, role, "roles", chain)) == p.RecoveryChoice(expected)


def test_semantic_fault_wrong_bound_is_detected_then_restored(monkeypatch):
    facts = p.FailureFacts(f.Failure.TIMEOUT, "a", "solo", ("a",), 1)
    def oracle():
        assert p.choose(facts) == p.RecoveryChoice(f.ChainExhausted("solo"))
    oracle()
    with monkeypatch.context() as patch:
        patch.setattr(p, "_walk", lambda *args: p.RecoveryChoice(p.RetrySame(500, 2)))
        with pytest.raises(AssertionError):
            oracle()
    oracle()
