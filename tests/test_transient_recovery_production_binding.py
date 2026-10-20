"""Original literal baselines followed by authorized public integration witnesses.

Original baselines alone never proved selected Source binding. The later rows
exercise Primary's announced scaffold/wiring with scripted providers, clocks and
in-memory capture files. No sockets, discovery, real waits or filesystem writes.
"""
from types import SimpleNamespace

import pytest

from cria import failover as f, transientpolicy as p, upstream as u


RAW = b'{"choices":[{"message":{"content":"  untouched\\n"}}],"usage":{"completion_tokens":2}}\n'


class Log:
    def __init__(self):
        self.events = []
    def emit(self, name, **fields):
        self.events.append((name, fields))


def chat_fixture(monkeypatch, outcomes):
    events = []
    clock = iter((10.0, 20.0, 30.0))
    monkeypatch.setattr(u, "time", SimpleNamespace(monotonic=lambda: next(clock),
                                                 sleep=lambda seconds: events.append(("wait", seconds))))
    monkeypatch.setattr(u.callcapture, "capture_response",
                        lambda path, raw, log: events.append(("capture", path, raw)))
    obj = object.__new__(u.Upstream)
    obj._engagement_level = 0
    def receive_open(*args, **kwargs):
        raise AssertionError("scripted opener must not execute transport")
    obj._receive_open = receive_open
    transport = (receive_open, u.urllib.request.urlopen)
    script = iter(outcomes)
    def open_request(body, stream, log, *, _transport):
        assert _transport == transport
        events.append(("open", body, stream))
        result = next(script)
        if isinstance(result, BaseException):
            raise result
        return SimpleNamespace(read=lambda: result,
                               close=lambda: events.append(("close",))), 73, "fake-capture"
    obj._open_with_refit = open_request
    obj._calibrate = lambda model, usage, estimate, log, body=None: events.append(("calibrate", model, usage, estimate))
    return obj, events


def test_original_chat_timeout_bytes(monkeypatch):
    obj, events = chat_fixture(monkeypatch, [OSError("timed out"), RAW])
    log = Log()
    body = {"model": "fixture", "messages": [{"role": "user", "content": "hello"}]}
    assert obj.chat(body, log) is RAW
    assert events == [
        ("open", body, False), ("wait", .5), ("open", body, False), ("close",),
        ("calibrate", "fixture", {"completion_tokens": 2}, 73),
        ("capture", "fake-capture", RAW),
    ]
    assert log.events == [
        ("upstream.retry", {"level": "warn", "attempt": 1, "wait_ms": 500, "error": "timed out"}),
        ("upstream.done", {"total_ms": 10000.0, "tokens": 2, "tok_per_s": .2, "from_usage": True}),
    ]


def test_original_chat_exhaustion_preserves_final_error_identity(monkeypatch):
    final = OSError("second timeout")
    obj, events = chat_fixture(monkeypatch, [OSError("first timeout"), final])
    with pytest.raises(OSError) as caught:
        obj.chat({}, Log())
    assert caught.value is final
    assert events == [("open", {}, False), ("wait", .5), ("open", {}, False)]


def test_original_context_no_change_is_not_transient(monkeypatch):
    source = u.UpstreamError("context window full", {"message": "context window full", "code": "context_length_exceeded"})
    source.code = 400
    error = u.ContextRefitNoChange(source, b'{"original":"wire"}')
    obj, events = chat_fixture(monkeypatch, [error])
    with pytest.raises(u.ContextRefitNoChange) as caught:
        obj.chat({}, Log())
    assert caught.value is error
    assert caught.value.final_wire == b'{"original":"wire"}'
    assert events == [("open", {}, False)]


def test_original_protocol_error_bypasses_classifier(monkeypatch):
    error = u.UpstreamProtocolError("timeout in malformed output",
                                    {"type": "invalid_model_output_error", "message": "raw protocol error"})
    obj, events = chat_fixture(monkeypatch, [error])
    def forbidden(*args, **kwargs):
        raise AssertionError("protocol error reached optional classification")
    monkeypatch.setattr(f, "classify_failure", forbidden)
    with pytest.raises(u.UpstreamProtocolError) as caught:
        obj.chat({}, Log())
    assert caught.value is error
    assert caught.value.response_error == {"type": "invalid_model_output_error", "message": "raw protocol error"}
    assert events == [("open", {}, False)]


def test_original_route_rate_limit_then_walk_and_reset():
    events = []
    log = Log()
    first = iter([RuntimeError("429"), RuntimeError("429"), RuntimeError("429")])
    second = iter([RuntimeError("timeout"), RAW])
    def call(role, script):
        events.append(("call", role))
        value = next(script)
        if isinstance(value, Exception):
            raise value
        return value
    result = f.run("roles", [f.Attempt("a", lambda: call("a", first)),
                             f.Attempt("b", lambda: call("b", second))],
                   lambda error: f.Failure.RATE_LIMIT if str(error) == "429" else f.Failure.TIMEOUT,
                   log, sleep=lambda delay: events.append(("wait", delay)))
    assert result is RAW
    assert events == [("call", "a"), ("wait", 1.0), ("call", "a"), ("wait", 1.0),
                      ("call", "a"), ("call", "b"), ("wait", .5), ("call", "b")]
    assert log.events == [
        ("route.retry_same", {"role": "a", "attempt": 1, "wait_ms": 1000}),
        ("route.retry_same", {"role": "a", "attempt": 2, "wait_ms": 1000}),
        ("route.failover", {"to": "b", "reason": "rate limit retries exhausted", "chain": "roles"}),
        ("route.retry_same", {"role": "b", "attempt": 1, "wait_ms": 500}),
    ]


def test_source_still_explicitly_unmigrated():
    assert p.TRANSIENT_RECOVERY.policy.family_id == "F58"
    assert p.TRANSIENT_RECOVERY.policy.migrated is False


# Public integration witnesses: executed only after Primary's actual scaffold
# announcement and explicit before/after GO. Missing integration prerequisites
# are never hidden behind optional imports, unknown-ID skips or expected failures.
def transient_selection(*, definition=None, absent=False):
    from cria import assistruntime
    canonical = p.TRANSIENT_RECOVERY
    replacement = canonical if definition is None else definition
    registrations = tuple(replacement if item.policy.id == canonical.policy.id else item
                          for item in assistruntime.DEFINITIONS)
    return assistruntime.AssistRuntime.select(
        level=0, registrations=registrations,
        disabled=(canonical.policy.id,) if absent else ())


def test_public_compatibility_reexports_exact_source_types():
    for name in ("Failure", "Behavior", "RetrySame", "NextInChain", "HardFail", "ChainExhausted"):
        assert getattr(f, name) is getattr(p, name)
    assert f.decide_action(p.Failure.TIMEOUT, "a", "solo", ("a",), 0) == p.RetrySame(500, 1)
    assert f.decide_action(p.Failure.TIMEOUT, "a", "solo", ("a",), 1) == p.ChainExhausted("solo")
    assert f.decide_action(p.Failure.RATE_LIMIT, "a", "solo", ("a",), 0, 0) == p.RetrySame(0, 1)
    assert f.decide_action(p.Failure.RATE_LIMIT, "a", "solo", ("a",), 1, 90000) == p.RetrySame(30000, 2)
    assert f.decide_action(p.Failure.RATE_LIMIT, "a", "solo", ("a",), 2) == p.ChainExhausted("solo")


def test_public_absence_does_not_classify_timeout(monkeypatch):
    from cria import assistruntime
    error = OSError("provider timeout")
    obj, events = chat_fixture(monkeypatch, [error])
    def forbidden(*args, **kwargs):
        raise AssertionError("absent transient policy classified a failure")
    monkeypatch.setattr(f, "classify_failure", forbidden)
    runtime = transient_selection(absent=True)
    assert runtime.transient_recovery is None
    with assistruntime.bound(runtime), pytest.raises(OSError) as caught:
        obj.chat({}, Log())
    assert caught.value is error
    assert events == [("open", {}, False)]


def test_public_replacement_not_legacy_dispatch(monkeypatch):
    from dataclasses import replace
    from cria import assistruntime
    first, final = OSError("first timeout"), OSError("final timeout")
    obj, events = chat_fixture(monkeypatch, [first, final])
    seen = []
    def execute(facts, behavior):
        seen.append(facts)
        return p.RecoveryChoice(p.RetrySame(17, 4) if len(seen) == 1
                                else p.ChainExhausted("upstream"))
    definition = replace(p.TRANSIENT_RECOVERY, execute=execute)
    runtime = transient_selection(definition=definition)
    assert runtime.transient_recovery is definition
    def forbidden(*args, **kwargs):
        raise AssertionError("optional dispatch fell back to legacy public decision")
    monkeypatch.setattr(f, "decide_action", forbidden)
    with assistruntime.bound(runtime), pytest.raises(OSError) as caught:
        obj.chat({}, Log())
    assert caught.value is final
    assert seen == [p.FailureFacts(p.Failure.TIMEOUT, "upstream", "upstream", ("upstream",), 0),
                    p.FailureFacts(p.Failure.TIMEOUT, "upstream", "upstream", ("upstream",), 4)]
    assert events == [("open", {}, False), ("wait", .017), ("open", {}, False)]


@pytest.mark.parametrize("absent", [False, True])
def test_public_failover_selected_dispatch_and_absence(monkeypatch, absent):
    from dataclasses import replace
    from cria import assistruntime
    error = OSError("provider timeout")
    events, seen = [], []
    script = iter((error, RAW))
    def call():
        events.append(("call", "a"))
        result = next(script)
        if isinstance(result, BaseException):
            raise result
        return result
    def classify(exc):
        assert exc is error
        if absent:
            raise AssertionError("absent route policy invoked classifier")
        events.append(("classify", exc))
        return p.Failure.TIMEOUT
    def execute(facts, behavior):
        seen.append(facts)
        return p.RecoveryChoice(p.RetrySame(17, 4))
    runtime = transient_selection(definition=replace(p.TRANSIENT_RECOVERY, execute=execute),
                                  absent=absent)
    def forbidden(*args, **kwargs):
        raise AssertionError("optional run dispatch called public compatibility policy")
    monkeypatch.setattr(f, "decide_action", forbidden)
    log = Log()
    with assistruntime.bound(runtime):
        if absent:
            with pytest.raises(OSError) as caught:
                f.run("roles", [f.Attempt("a", call)], classify, log,
                      sleep=lambda delay: events.append(("wait", delay)))
            assert caught.value is error
        else:
            assert f.run("roles", [f.Attempt("a", call)], classify, log,
                         sleep=lambda delay: events.append(("wait", delay))) is RAW
    assert seen == ([] if absent else [p.FailureFacts(p.Failure.TIMEOUT, "a", "roles", ("a",), 0)])
    assert events == ([("call", "a")] if absent else
                      [("call", "a"), ("classify", error), ("wait", .017), ("call", "a")])
    assert log.events == ([] if absent else
                          [("route.retry_same", {"role": "a", "attempt": 4, "wait_ms": 17})])


def test_public_chat_pins_opener_and_sleeper_before_first_attempt(monkeypatch):
    from dataclasses import replace
    from cria import assistruntime
    first, final = OSError("first timeout"), OSError("final timeout")
    obj, events = chat_fixture(monkeypatch, [first, final])
    original_open = obj._open_with_refit
    seen = []
    def execute(facts, behavior):
        seen.append(facts.attempt)
        return p.RecoveryChoice(p.RetrySame(17, 4) if len(seen) == 1
                                else p.ChainExhausted("upstream"))
    runtime = transient_selection(definition=replace(p.TRANSIENT_RECOVERY, execute=execute))
    def forbidden(*args, **kwargs):
        raise AssertionError("retry re-read replaced operation service")
    def initial_open(*args, **kwargs):
        obj._open_with_refit = forbidden
        u.time.sleep = forbidden
        return original_open(*args, **kwargs)
    obj._open_with_refit = initial_open
    with assistruntime.bound(runtime), pytest.raises(OSError) as caught:
        obj.chat({}, Log())
    assert caught.value is final
    assert seen == [0, 4]
    assert events == [("open", {}, False), ("wait", .017), ("open", {}, False)]


@pytest.mark.parametrize("iteration_error", [False, True])
def test_public_stream_keeps_construction_selection_without_transient_retry(monkeypatch, iteration_error):
    from dataclasses import replace
    from cria import assistruntime
    events = []
    line = b': raw keepalive  \\n'
    error = OSError("provider timeout after raw stream data")
    def forbidden_policy(facts, behavior):
        raise AssertionError("legacy-inapplicable stream executed transient policy")
    a = transient_selection(definition=replace(p.TRANSIENT_RECOVERY, execute=forbidden_policy))
    b = transient_selection(absent=True)
    clock = SimpleNamespace(monotonic=lambda: 10.0,
                            sleep=lambda seconds: (_ for _ in ()).throw(AssertionError("stream retried")))
    monkeypatch.setattr(u, "time", clock)
    obj = object.__new__(u.Upstream)
    def transport_a(*args, **kwargs):
        raise AssertionError("fake opener must not execute a real transport")
    def transport_b(*args, **kwargs):
        raise AssertionError("consumer transport replaced constructor transport")
    obj._receive_open = transport_a
    class Response:
        def __iter__(self):
            yield line
            if iteration_error:
                raise error
            yield b'data: [DONE]\\n'
        def close(self):
            events.append(("close", assistruntime.current() is a))
    def open_request(body, stream, log, *, _transport):
        events.append(("open", stream, assistruntime.current() is a,
                       _transport[0] is transport_a))
        return Response(), 73, "fake-stream-capture"
    obj._open_with_refit = open_request
    obj._save_reasoning = lambda *args, **kwargs: events.append(("reasoning", assistruntime.current() is a))
    obj._calibrate = lambda *args: events.append(("calibrate", assistruntime.current() is a))
    log = Log()
    with assistruntime.bound(a):
        stream = obj.stream_chat({}, log)
    obj._receive_open = transport_b
    with assistruntime.bound(b):
        assert next(stream) is line
        assert assistruntime.current() is b
        if iteration_error:
            with pytest.raises(OSError) as caught:
                next(stream)
            assert caught.value is error
        else:
            assert next(stream) == b'data: [DONE]\\n'
            with pytest.raises(StopIteration):
                next(stream)
        assert assistruntime.current() is b
        stream.close()
        assert assistruntime.current() is b
    assert events == [("open", True, True, True), ("close", True),
                      ("reasoning", True), ("calibrate", True)]
    assert log.events == [("upstream.done", {"total_ms": 0.0, "gen_ms": 0.0,
                                            "tokens": 0, "tok_per_s": None, "from_usage": False})]


@pytest.mark.parametrize("caller", [False, True])
@pytest.mark.parametrize("absent", [False, True])
def test_public_typed_timeout_guards_precede_lazy_classifier(monkeypatch, caller, absent):
    from cria import assistruntime
    source = u.UpstreamError("provider timeout", {"code": "context_length_exceeded",
                                                  "message": "provider timeout"})
    source.code = 400
    inner = u.ContextRefitNoChange(source, b'original-wire')
    error = u.CallerContextRetryNoChange(inner, b'original-wire') if caller else inner
    obj, events = chat_fixture(monkeypatch, [error])
    def forbidden(*args, **kwargs):
        raise AssertionError("typed no-change reached transient classification")
    monkeypatch.setattr(f, "classify_failure", forbidden)
    with assistruntime.bound(transient_selection(absent=absent)), pytest.raises(type(error)) as caught:
        obj.chat({}, Log())
    assert caught.value is error
    assert error.final_wire == b'original-wire'
    assert events == [("open", {}, False)]


@pytest.mark.parametrize("failure_type", [OSError, KeyboardInterrupt])
def test_public_wait_failure_or_cancellation_stops_before_retry(monkeypatch, failure_type):
    from cria import assistruntime
    obj, events = chat_fixture(monkeypatch, [OSError("provider timeout"), RAW])
    stopped = failure_type("scripted wait interruption")
    def sleep(delay):
        events.append(("wait", delay))
        raise stopped
    monkeypatch.setattr(u.time, "sleep", sleep)
    with assistruntime.bound(transient_selection()), pytest.raises(failure_type) as caught:
        obj.chat({}, Log())
    assert caught.value is stopped
    assert events == [("open", {}, False), ("wait", .5)]


def test_public_independent_calls_reset_attempt(monkeypatch):
    from dataclasses import replace
    from cria import assistruntime
    seen = []
    def execute(facts, behavior):
        seen.append(facts.attempt)
        return p.RecoveryChoice(p.RetrySame(17, 4) if facts.attempt == 0
                                else p.ChainExhausted("upstream"))
    runtime = transient_selection(definition=replace(p.TRANSIENT_RECOVERY, execute=execute))
    errors = []
    for index in range(2):
        final = OSError("final timeout " + str(index))
        obj, events = chat_fixture(monkeypatch, [OSError("first timeout"), final])
        with assistruntime.bound(runtime), pytest.raises(OSError) as caught:
            obj.chat({}, Log())
        errors.append(caught.value)
        assert caught.value is final
        assert events == [("open", {}, False), ("wait", .017), ("open", {}, False)]
    assert seen == [0, 4, 0, 4]
    assert errors[0] is not errors[1]


def test_public_run_protocol_error_never_reaches_classifier(monkeypatch):
    from cria import assistruntime
    error = u.UpstreamProtocolError("timeout", {"type": "invalid_model_output_error", "message": "bad"})
    events = []
    def call():
        events.append("call")
        raise error
    def forbidden(*args, **kwargs):
        raise AssertionError("protocol exclusion invoked optional service")
    with assistruntime.bound(transient_selection()), pytest.raises(u.UpstreamProtocolError) as caught:
        f.run("roles", [f.Attempt("a", call)], forbidden, Log(), sleep=forbidden)
    assert caught.value is error
    assert events == ["call"]


def test_public_run_snapshots_route_receivers_and_chain_attempt_reset():
    from dataclasses import replace
    from cria import assistruntime
    events, seen = [], []
    def forbidden():
        raise AssertionError("run re-read mutated route receiver")
    b_script = iter((OSError("b timeout"), RAW))
    def b_call():
        events.append("b")
        result = next(b_script)
        if isinstance(result, BaseException):
            raise result
        return result
    b = f.Attempt("b", b_call)
    def a_call():
        events.append("a")
        b.call = forbidden
        b.role = "mutated"
        raise OSError("a unavailable")
    def execute(facts, behavior):
        seen.append(facts)
        if facts.role == "a":
            return p.RecoveryChoice(p.NextInChain("b", "model unavailable"))
        return p.RecoveryChoice(p.RetrySame(17, 4))
    runtime = transient_selection(definition=replace(p.TRANSIENT_RECOVERY, execute=execute))
    log = Log()
    with assistruntime.bound(runtime):
        assert f.run("roles", [f.Attempt("a", a_call), b],
                     lambda exc: p.Failure.TIMEOUT if str(exc) == "b timeout" else p.Failure.MODEL_UNAVAILABLE,
                     log, sleep=lambda delay: events.append(delay)) is RAW
    assert seen == [p.FailureFacts(p.Failure.MODEL_UNAVAILABLE, "a", "roles", ("a", "b"), 0),
                    p.FailureFacts(p.Failure.TIMEOUT, "b", "roles", ("a", "b"), 0)]
    assert events == ["a", "b", .017, "b"]
    assert log.events == [("route.failover", {"to": "b", "reason": "model unavailable", "chain": "roles"}),
                          ("route.retry_same", {"role": "b", "attempt": 4, "wait_ms": 17})]


def test_public_actual_transport_swap_and_capture_metadata(monkeypatch):
    import io
    from cria import assistruntime, receivecapture, tokenratio
    requests, captures, responses, waits = [], [], [], []
    ticks = iter(range(100))
    monkeypatch.setattr(u, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=waits.append))
    monkeypatch.setattr(tokenratio, "_ratios", {})
    def capture(body, log, **kwargs):
        captures.append((body, kwargs))
        return "/fake-transient/" + str(len(captures))
    monkeypatch.setattr(u.callcapture, "capture", capture)
    monkeypatch.setattr(u.callcapture, "capture_response", lambda path, raw, log=None: responses.append((path, raw)))
    monkeypatch.setattr(receivecapture.Receipt, "_file", staticmethod(lambda path: io.BytesIO()))
    runtime = transient_selection()
    def forbidden(*args, **kwargs):
        raise AssertionError("operation re-read replaced transport or sleeper")
    class Response:
        def read(self):
            return RAW
        def close(self):
            requests.append("close")
    def provider(request, *, timeout, receipt):
        requests.append((request.data, timeout, assistruntime.current() is runtime))
        assert receipt is not None
        if len(requests) == 1:
            api._receive_open = forbidden
            monkeypatch.setattr(u.urllib.request, "urlopen", forbidden)
            u.time.sleep = forbidden
            raise OSError("provider timeout")
        receipt.finish()
        return Response()
    api = u.Upstream("https://invalid.example", api_key="fake-only", context_window=1000,
                     engagement_level=0, open_request=provider)
    api._capture_dir = "/fake-transient"
    body = {"model": "transient-fixture", "messages": [{"role": "user", "content": "hello"}]}
    wire = b'{"model": "transient-fixture", "messages": [{"role": "user", "content": "hello"}], "stream": false}'
    with assistruntime.bound(runtime):
        assert api.chat(body, Log()) is RAW
    assert requests == [(wire, 600, True), (wire, 600, True), "close"]
    assert waits == [.5]
    assert responses == [("/fake-transient/2", RAW)]
    assert len(captures) == 2
    for captured_body, metadata in captures:
        assert captured_body == {"model": "transient-fixture", "messages": [{"role": "user", "content": "hello"}], "stream": False}
        assert metadata["assist_selection"]["selected"] == list(runtime.selected)
        assert "transient-recovery" in metadata["assist_selection"]["selected"]


def test_public_root_dispatch_fault_is_detected_and_restored(monkeypatch):
    from cria import assistruntime
    def oracle():
        error = OSError("provider timeout")
        obj, events = chat_fixture(monkeypatch, [error, RAW])
        with assistruntime.bound(transient_selection(absent=True)):
            try:
                obj.chat({}, Log())
            except OSError as caught:
                assert caught is error
            else:
                raise AssertionError("absent policy retried and returned a response")
        assert events == [("open", {}, False)]
    oracle()
    original_chat = u.Upstream._chat
    with monkeypatch.context() as fault:
        def ignore_absence(self, body, log, runtime, opening, sleeper, transport):
            return original_chat(self, body, log, transient_selection(), opening, sleeper, transport)
        fault.setattr(u.Upstream, "_chat", ignore_absence)
        with pytest.raises(AssertionError, match="absent policy retried"):
            oracle()
    oracle()


def test_public_run_duplicate_role_preserves_legacy_receiver_resolution():
    from cria import assistruntime
    events = []
    def first():
        events.append("first")
        raise OSError("unavailable")
    def middle():
        raise AssertionError("legacy by-role resolution chooses last duplicate")
    def last():
        events.append("last")
        return RAW
    log = Log()
    with assistruntime.bound(transient_selection()):
        assert f.run("roles", [f.Attempt("same", first), f.Attempt("same", middle),
                               f.Attempt("same", last)], lambda exc: p.Failure.MODEL_UNAVAILABLE,
                     log, sleep=lambda delay: events.append(delay)) is RAW
    assert events == ["first", "last"]
    assert log.events == [("route.failover", {"to": "same", "reason": "model unavailable", "chain": "roles"})]


@pytest.mark.parametrize("action", [p.HardFail("blocked"), p.ChainExhausted("roles"),
                                    p.NextInChain("not-resolved", "model unavailable")])
def test_public_run_terminal_choices_preserve_error_identity(action):
    from dataclasses import replace
    from cria import assistruntime
    error = OSError("original timeout")
    events = []
    def call():
        events.append("call")
        raise error
    runtime = transient_selection(definition=replace(p.TRANSIENT_RECOVERY,
        execute=lambda facts, behavior: p.RecoveryChoice(action)))
    log = Log()
    with assistruntime.bound(runtime), pytest.raises(OSError) as caught:
        f.run("roles", [f.Attempt("a", call)], lambda exc: p.Failure.TIMEOUT,
              log, sleep=lambda delay: events.append(delay))
    assert caught.value is error
    assert events == ["call"]
    assert log.events == []


def test_public_real_http_failure_status_headers_and_raw_body_are_retained(monkeypatch):
    import io
    import urllib.error
    from cria import assistruntime, tokenratio
    waits, sent, facts = [], [], []
    ticks = iter(range(100))
    monkeypatch.setattr(u, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=waits.append))
    monkeypatch.setattr(tokenratio, "_ratios", {})
    raw = b'{"error":{"message":"provider rate limited","code":"rate_limit"}}\n'
    originals = [urllib.error.HTTPError("https://invalid.example/v1/chat/completions", 429,
                 "provider rate limited", {"Retry-After": "9", "X-Provenance": "original"},
                 io.BytesIO(raw)) for _ in range(3)]
    script = iter(originals)
    def provider(request, *, timeout, receipt):
        sent.append((request.data, timeout, request.get_header("Authorization")))
        assert receipt is None
        raise next(script)
    from dataclasses import replace
    def execute(source, behavior):
        facts.append(source)
        return p.choose(source, behavior)
    runtime = transient_selection(definition=replace(p.TRANSIENT_RECOVERY, execute=execute))
    api = u.Upstream("https://invalid.example", api_key="fake-only", context_window=1000,
                     engagement_level=0, open_request=provider)
    body = {"model": "transient-fixture", "messages": [{"role": "user", "content": "hello"}]}
    with assistruntime.bound(runtime), pytest.raises(u.UpstreamError) as caught:
        api.chat(body, Log())
    assert caught.value.__cause__ is originals[-1]
    assert caught.value.code == 429
    assert caught.value.response_error == {"message": "provider rate limited", "code": "rate_limit"}
    assert [item.response_body for item in originals] == [raw, raw, raw]
    assert [item.headers["Retry-After"] for item in originals] == ["9", "9", "9"]
    assert [item.headers["X-Provenance"] for item in originals] == ["original"] * 3
    assert facts == [p.FailureFacts(p.Failure.RATE_LIMIT, "upstream", "upstream", ("upstream",), attempt)
                     for attempt in (0, 1, 2)]
    # Preserve existing behavior: Root has never forwarded Retry-After to this
    # policy; the explicit-delay Source contract is separately tested, not a
    # license to silently change this migration's public retry timing.
    assert waits == [1.0, 1.0]
    wire = b'{"model": "transient-fixture", "messages": [{"role": "user", "content": "hello"}], "stream": false}'
    assert sent == [(wire, 600, "Bearer fake-only")] * 3


@pytest.mark.parametrize("ending", ["success", "close", "cancel", "open-error"])
def test_public_stream_actual_capture_snapshot_and_terminal_lifecycles(monkeypatch, ending):
    import io
    from dataclasses import replace
    from cria import assistruntime, receivecapture, tokenratio
    captures, sent, closed = [], [], []
    monkeypatch.setattr(tokenratio, "_ratios", {})
    def forbidden(*args, **kwargs):
        raise AssertionError("stream invoked retry policy or consumer transport")
    monkeypatch.setattr(u, "time", SimpleNamespace(monotonic=lambda: 10.0, sleep=forbidden))
    def capture(body, log, **kwargs):
        captures.append((body, kwargs))
        return "/fake-stream/1"
    monkeypatch.setattr(u.callcapture, "capture", capture)
    monkeypatch.setattr(u.callcapture, "capture_response", lambda *args: None)
    monkeypatch.setattr(receivecapture.Receipt, "_file", staticmethod(lambda path: io.BytesIO()))
    a = transient_selection(definition=replace(p.TRANSIENT_RECOVERY, execute=forbidden))
    b = transient_selection(absent=True)
    cancel = KeyboardInterrupt("stream cancelled")
    open_error = OSError("provider timeout before streaming")
    line = b': actual keepalive  \n'
    class Response:
        def __iter__(self):
            yield line
            if ending == "cancel":
                raise cancel
            yield b'data: [DONE]\n'
        def close(self):
            closed.append(assistruntime.current() is a)
    def provider(request, *, timeout, receipt):
        sent.append((request.data, timeout, assistruntime.current() is a))
        assert receipt is not None
        if ending == "open-error":
            raise open_error
        receipt.finish()
        return Response()
    api = u.Upstream("https://invalid.example", api_key="fake-only", context_window=1000,
                     engagement_level=0, open_request=provider)
    api._capture_dir = "/fake-stream"
    api._save_reasoning = lambda *args, **kwargs: None
    body = {"model": "stream-fixture", "messages": [{"role": "user", "content": "hello"}]}
    with assistruntime.bound(a):
        stream = api.stream_chat(body, Log())
    api._receive_open = forbidden
    monkeypatch.setattr(u.urllib.request, "urlopen", forbidden)
    with assistruntime.bound(b):
        if ending == "open-error":
            with pytest.raises(OSError) as caught:
                next(stream)
            assert caught.value is open_error
        else:
            assert next(stream) is line
            assert assistruntime.current() is b
            if ending == "cancel":
                with pytest.raises(KeyboardInterrupt) as caught:
                    next(stream)
                assert caught.value is cancel
            elif ending == "success":
                assert list(stream) == [b'data: [DONE]\n']
            else:
                stream.close()
        assert assistruntime.current() is b
        stream.close()
        assert assistruntime.current() is b
    wire = b'{"model": "stream-fixture", "messages": [{"role": "user", "content": "hello"}], "stream": true}'
    assert sent == [(wire, u.rumination.WIRE_SILENCE_SECONDS, True)]
    assert closed == ([] if ending == "open-error" else [True])
    assert len(captures) == 1
    assert captures[0][0] == {"model": "stream-fixture", "messages": [{"role": "user", "content": "hello"}], "stream": True}
    assert captures[0][1]["assist_selection"]["selected"] == list(a.selected)
    assert "transient-recovery" in captures[0][1]["assist_selection"]["selected"]
