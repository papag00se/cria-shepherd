"""Original public fake-service baselines, NOT integrated Source acceptance.

Primary must bind the new definition before selected/absent replacement can be
proved through production. These literal originals preserve the existing route
without running any shared test file, sockets, real sleeps or filesystem writes.
"""
import io
import json
from dataclasses import replace
from types import SimpleNamespace
import urllib.error

import pytest

from cria import tokenratio, upstream
from cria.upstream import Upstream, UpstreamError, ContextRefitNoChange


BODY = {"model": "capacity-fixture", "messages": [{"role": "user", "content": "hello"}]}
WIRE = b'{"model": "capacity-fixture", "messages": [{"role": "user", "content": "hello"}], "stream": false}'
RAW_ERROR = b'{"error":{"message":"context exhausted","n_prompt_tokens":2000,"n_ctx":1000}}\n'
RAW_SUCCESS = b'{"choices":[{"message":{"role":"assistant","content":" answer "}}],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n'


class Log:
    def __init__(self):
        self.events = []

    def emit(self, name, **values):
        self.events.append((name, values))


class Response:
    def __init__(self, raw):
        self.raw = raw
        self.closed = False

    def read(self):
        return self.raw

    def close(self):
        self.closed = True

    def __iter__(self):
        return iter(self.raw.splitlines(keepends=True))


class Provider:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.requests = []

    def __call__(self, request, *, timeout, receipt):
        assert receipt is None
        self.requests.append((request.data, timeout))
        outcome = next(self.outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def client(monkeypatch, outcomes, *, window=1000, level=0):
    # Process-local scripted services; no env, discovery or real clock calls.
    ticks = iter(range(100))
    def forbidden_sleep(_):
        raise AssertionError("unexpected transient wait")
    monkeypatch.setattr(upstream, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=forbidden_sleep))
    monkeypatch.setattr(tokenratio, "_ratios", {})
    provider = Provider(outcomes)
    api = Upstream("https://invalid.example", api_key="fake-service-only", context_window=window,
                   engagement_level=level, open_request=provider)
    return api, provider, Log()


def http_error(raw=RAW_ERROR, code=400):
    return urllib.error.HTTPError("https://invalid.example/v1/chat/completions", code,
                                  "context exhausted", {}, io.BytesIO(raw))


def test_original_public_no_change(monkeypatch):
    original = http_error()
    api, provider, log = client(monkeypatch, [original])
    with pytest.raises(ContextRefitNoChange) as caught:
        api.chat(dict(BODY), log)
    assert caught.value.final_wire == WIRE
    assert caught.value.__cause__ is original
    assert caught.value.code == 400
    assert caught.value.response_error == {"message": "context exhausted", "n_prompt_tokens": 2000,
                                           "n_ctx": 1000, "code": "context_length_exceeded"}
    assert original.response_body == RAW_ERROR
    assert provider.requests == [(WIRE, 600)]
    assert api._window == 1000 and api._window_final
    assert [name for name, _ in log.events].count("context.refit") == 1


def test_original_public_success_keeps_raw_bytes_and_closes_response(monkeypatch):
    response = Response(RAW_SUCCESS)
    api, provider, _log = client(monkeypatch, [response])
    assert api.chat(dict(BODY), _log) is RAW_SUCCESS
    assert provider.requests == [(WIRE, 600)]
    assert response.closed
    # hello's estimate is one token; 10 real tokens clamp to 4.0, then
    # rise-fast EWMA is 1.8 * .3 + 4 * .7 = 3.34.
    assert tokenratio.observed("capacity-fixture") == pytest.approx(3.34)


def test_original_public_noncontext_error_is_not_a_capacity_retry(monkeypatch):
    raw = b'{"error":{"message":"invalid field","code":"invalid_request_error"}}\n'
    original = http_error(raw)
    api, provider, log = client(monkeypatch, [original])
    with pytest.raises(UpstreamError) as caught:
        api.chat(dict(BODY), log)
    assert type(caught.value) is UpstreamError
    assert caught.value.__cause__ is original
    assert caught.value.response_error == {"message": "invalid field", "code": "invalid_request_error"}
    assert provider.requests == [(WIRE, 600)]
    assert original.response_body == raw
    assert not any(name == "context.refit" for name, _ in log.events)


def test_original_accepted_window_fact_is_not_level_three_gated(monkeypatch):
    response = Response(RAW_SUCCESS)
    api, provider, log = client(monkeypatch, [response])
    # Simulate a discovery miss already observed by shared support. The public
    # route remains L0: mandatory accepted usage repairs the guessed lower bound.
    api._window = 8
    api._window_final = False
    api._window_guessed = True
    api._resolve_window = lambda _: 8
    assert api.chat(dict(BODY), log) == RAW_SUCCESS
    assert provider.requests == [(WIRE, 600)]
    assert api._window == 12 and not api._window_guessed and not api._window_final
    assert ("context.window", {"level": "warn", "source": "accepted-prompt", "n_ctx": 12, "was": 8}) in log.events


def test_original_public_nested_immediate_retry_preserves_no_change(monkeypatch):
    original = http_error()
    api, provider, log = client(monkeypatch, [original])
    with pytest.raises(ContextRefitNoChange) as inner:
        api.chat(dict(BODY), log)
    retry_body = {**BODY, upstream.bodykeys.CONTEXT_REFIT_NO_CHANGE: inner.value}
    with pytest.raises(upstream.CallerContextRetryNoChange) as outer:
        api.chat(retry_body, log)
    assert outer.value.__cause__ is inner.value
    assert outer.value.final_wire == WIRE
    assert provider.requests == [(WIRE, 600)]


def test_source_final_wire_service_can_use_real_preparer_without_production_binding(monkeypatch):
    from cria import capacitypolicy as policy
    api, provider, log = client(monkeypatch, [])
    sent = []
    def prepare(safety):
        wire, estimate, capture = api._prep(dict(BODY), False, log, safety_override=safety)
        return policy.Prepared(wire, estimate, capture)
    def send(prepared):
        sent.append(prepared.wire)
        return policy.Accepted(RAW_SUCCESS)
    services = policy.Services(prepare, send, lambda _: None, log.emit,
        lambda source: policy.NoChangeProvenance(source, source.final_wire)
            if isinstance(source, ContextRefitNoChange) else None,
        ContextRefitNoChange, upstream.CallerContextRetryNoChange)
    result = policy.dispatch(services, policy.DEFINITION)
    assert sent == [WIRE]
    assert result.outcome.response is RAW_SUCCESS
    assert result.prepared.wire == WIRE
    assert provider.requests == []  # Only injected source transport ran.


# The scenarios below require the announced actual registry/runtime scaffold.
# Old public baselines above stay literal and unchanged.
from cria import assistruntime, capacitypolicy, receivecapture

STREAM_WIRE = b'{"model": "capacity-fixture", "messages": [{"role": "user", "content": "hello"}], "stream": true}'
SSE = b'data: {"choices":[{"delta":{"content":" answer "}}]}\n\ndata: [DONE]\n\n'


def selection(*, level=0, definition=None, absent=False):
    canonical = capacitypolicy.DEFINITION
    registry = tuple(definition if d is canonical and definition is not None else d
                     for d in assistruntime.DEFINITIONS)
    assert sum(d.policy.id == canonical.policy.id for d in registry) == 1
    runtime = assistruntime.AssistRuntime.select(level=level, registrations=registry,
        disabled=(canonical.policy.id,) if absent else ())
    assert runtime.capacity is (None if absent else definition or canonical)
    return runtime


def invoke(api, log, body, streaming):
    return b"".join(api.stream_chat(body, log)) if streaming else api.chat(body, log)


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("mode", ["absent", "replacement"])
def test_public_optional_choice_uses_exact_selected_owner(monkeypatch, streaming, mode):
    choices = []
    original = http_error()
    def decline(facts):
        choices.append(facts)
        assert facts.rejection.source is original
        assert facts.prepared.wire == (STREAM_WIRE if streaming else WIRE)
        assert facts.prepared.estimate == 1
        # Mandatory observations precede the optional choice.
        assert tokenratio.observed("capacity-fixture") == pytest.approx(3.34)
        return None
    definition = replace(capacitypolicy.DEFINITION, execute=decline)
    runtime = selection(definition=definition, absent=mode == "absent")
    api, provider, log = client(monkeypatch, [original])
    with assistruntime.bound(runtime):
        with pytest.raises(UpstreamError) as caught:
            invoke(api, log, dict(BODY), streaming)
    assert type(caught.value) is UpstreamError
    assert caught.value.__cause__ is original
    assert caught.value.response_error == {"message": "context exhausted", "n_prompt_tokens": 2000,
        "n_ctx": 1000, "code": "context_length_exceeded"}
    assert original.response_body == RAW_ERROR
    assert len(choices) == (mode == "replacement")
    assert provider.requests == [((STREAM_WIRE if streaming else WIRE),
                                 upstream.rumination.WIRE_SILENCE_SECONDS if streaming else 600)]
    assert tokenratio.observed("capacity-fixture") == pytest.approx(3.34)


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("level", [0, 3])
def test_public_floor_applicability_and_optional_density(monkeypatch, streaming, level):
    original_fit = upstream.contextfloor.fit
    fits, densities = [], []
    def fit(*args, **kwargs):
        fits.append(kwargs["safety"])
        return original_fit(*args, **kwargs)
    def density(model):
        densities.append(model)
        return 2.25
    monkeypatch.setattr(upstream.contextfloor, "fit", fit)
    definition = replace(capacitypolicy.DEFINITION, density=density)
    runtime = selection(level=level, definition=definition)
    response = Response(SSE if streaming else RAW_SUCCESS)
    api, provider, log = client(monkeypatch, [response], level=level)
    body = {**BODY, "max_tokens": 32}
    with assistruntime.bound(runtime):
        assert invoke(api, log, body, streaming) == (SSE if streaming else RAW_SUCCESS)
    expected = (b'{"model": "capacity-fixture", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 32, "stream": '
                + (b'true}' if streaming else b'false}'))
    assert provider.requests[0][0] == expected
    assert fits == ([2.25] if level == 3 else [])
    assert densities == (["capacity-fixture"] if level == 3 else [])
    assert response.closed


def test_public_absence_keeps_required_floor_without_learned_lookup(monkeypatch):
    original_fit = upstream.contextfloor.fit
    fits = []
    def fit(*args, **kwargs):
        fits.append(kwargs["safety"])
        return original_fit(*args, **kwargs)
    def forbidden(_):
        raise AssertionError("absent adaptation consulted learned ratio")
    monkeypatch.setattr(upstream.contextfloor, "fit", fit)
    monkeypatch.setattr(tokenratio, "observed", forbidden)
    api, provider, log = client(monkeypatch, [Response(RAW_SUCCESS)], level=3)
    with assistruntime.bound(selection(level=3, absent=True)):
        assert api.chat({**BODY, "max_tokens": 32}, log) == RAW_SUCCESS
    assert fits == [1.8]
    assert provider.requests[0][0] == b'{"model": "capacity-fixture", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 32, "stream": false}'


@pytest.mark.parametrize("level", [0, 3])
def test_public_stream_constructor_pins_owner_before_first_yield(monkeypatch, level):
    seen, densities = [], []
    def owner_a(facts):
        seen.append(("A", facts))
        return None
    def owner_b(_):
        raise AssertionError("consuming runtime stole capacity choice")
    def density_a(model):
        densities.append(("A", model))
        return 2.125
    def density_b(_):
        raise AssertionError("consuming runtime stole capacity density")
    a = selection(level=level, definition=replace(capacitypolicy.DEFINITION,
                  execute=owner_a, density=density_a))
    b = selection(level=level, definition=replace(capacitypolicy.DEFINITION,
                  execute=owner_b, density=density_b))
    original = http_error()
    api, provider, log = client(monkeypatch, [original], level=level)
    with assistruntime.bound(a):
        iterator = api.stream_chat({**BODY, "max_tokens": 32}, log)
    with assistruntime.bound(b):
        with pytest.raises(UpstreamError) as caught:
            b"".join(iterator)
        assert assistruntime.current() is b
    assert type(caught.value) is UpstreamError
    assert len(seen) == 1 and seen[0][0] == "A"
    assert seen[0][1].rejection.source is original
    assert densities == ([("A", "capacity-fixture")] if level == 3 else [])
    assert len(provider.requests) == 1


class MemoryCapture:
    def __init__(self, monkeypatch):
        self.requests, self.responses, self.files = [], [], {}
        def capture(body, log, **kwargs):
            self.requests.append((body, kwargs))
            return f"/fake-capture/{len(self.requests)}"
        def store(path, response, log=None):
            self.responses.append((path, response))
        def file(path):
            sink = io.BytesIO()
            self.files[str(path)] = sink
            return sink
        monkeypatch.setattr(upstream.callcapture, "capture", capture)
        monkeypatch.setattr(upstream.callcapture, "capture_response", store)
        monkeypatch.setattr(receivecapture.Receipt, "_file", staticmethod(file))


@pytest.mark.parametrize("streaming", [False, True])
def test_public_capture_custody_precedes_adversarial_selected_refit(monkeypatch, streaming):
    capture = MemoryCapture(monkeypatch)
    choices, sent, receipts = [], [], []
    original = http_error()
    def choice(facts):
        choices.append(facts)
        return capacitypolicy.Refit(2.0)
    runtime = selection(definition=replace(capacitypolicy.DEFINITION, execute=choice))
    api, _, log = client(monkeypatch, [])
    api._capture_dir = "/fake-capture"
    def send(req, *, timeout, receipt):
        sent.append(req.data)
        receipts.append(receipt)
        receipt.failure("scripted-store", OSError("fake filesystem failure"))
        raise original
    api._receive_open = send
    with assistruntime.bound(runtime):
        with pytest.raises(UpstreamError) as caught:
            invoke(api, log, dict(BODY), streaming)
    assert type(caught.value) is UpstreamError
    assert caught.value.__cause__ is original
    assert original.response_body == RAW_ERROR
    assert choices == []
    assert sent == [STREAM_WIRE if streaming else WIRE]
    assert capture.responses == [("/fake-capture/1", RAW_ERROR)]
    assert len(receipts) == 1 and receipts[0].finished and receipts[0].failed
    assert len(capture.requests) == 1
    assert capture.requests[0][1]["assist_selection"]["selected"] == list(runtime.selected)


def test_public_stream_capture_selection_pinned_across_runtime_swap(monkeypatch):
    capture = MemoryCapture(monkeypatch)
    a, b = selection(), selection(absent=True)
    api, _, log = client(monkeypatch, [])
    api._capture_dir = "/fake-capture"
    sent = []
    def send(req, *, timeout, receipt):
        sent.append(req.data)
        receipt.finish()
        return Response(SSE)
    api._receive_open = send
    with assistruntime.bound(a):
        iterator = api.stream_chat(dict(BODY), log)
    with assistruntime.bound(b):
        assert b"".join(iterator) == SSE
        assert assistruntime.current() is b
    assert sent == [STREAM_WIRE]
    assert capture.requests[0][1]["assist_selection"]["selected"] == list(a.selected)


@pytest.mark.parametrize("absent", [False, True])
def test_public_nested_typed_suppression_and_lookalike(monkeypatch, absent):
    original = http_error()
    inner = ContextRefitNoChange(original, WIRE)
    api, provider, log = client(monkeypatch, [Response(RAW_SUCCESS)])
    with assistruntime.bound(selection(absent=absent)):
        with pytest.raises(upstream.CallerContextRetryNoChange) as caught:
            api.chat({**BODY, upstream.bodykeys.CONTEXT_REFIT_NO_CHANGE: inner}, log)
        assert type(caught.value) is upstream.CallerContextRetryNoChange
        assert caught.value.__cause__ is inner
        assert caught.value.final_wire == WIRE
        assert provider.requests == []
        lookalike = SimpleNamespace(final_wire=WIRE)
        assert api.chat({**BODY, upstream.bodykeys.CONTEXT_REFIT_NO_CHANGE: lookalike}, log) == RAW_SUCCESS
    assert provider.requests == [(WIRE, 600)]


@pytest.mark.parametrize("caller_retry", [False, True])
def test_public_typed_capacity_timeout_never_reaches_transient_classifier(monkeypatch, caller_retry):
    original = http_error()
    original.msg = "timeout during context rejection"
    api, provider, log = client(monkeypatch, [original])
    classified = []
    def forbidden(*args):
        classified.append(args)
        raise AssertionError("typed capacity provenance reached transient classifier")
    monkeypatch.setattr(upstream.failover, "classify_failure", forbidden)
    inner = ContextRefitNoChange(original, WIRE)
    body = {**BODY, upstream.bodykeys.CONTEXT_REFIT_NO_CHANGE: inner} if caller_retry else dict(BODY)
    with assistruntime.bound(selection()):
        expected = upstream.CallerContextRetryNoChange if caller_retry else ContextRefitNoChange
        with pytest.raises(expected) as caught:
            api.chat(body, log)
    assert type(caught.value) is expected
    assert caught.value.final_wire == WIRE
    assert caught.value.__cause__ is (inner if caller_retry else original)
    assert classified == []
    assert provider.requests == ([] if caller_retry else [(WIRE, 600)])


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("second_rejects", [False, True])
def test_public_real_floor_changed_wire_retry_is_bounded(monkeypatch, streaming, second_rejects):
    body = {"model": "capacity-fixture", "messages": [
        {"role": "user", "content": "root"},
        {"role": "assistant", "content": "x" * 3000},
        {"role": "user", "content": "hello"}], "max_tokens": 32}
    raw = b'{"error":{"message":"hot density","n_prompt_tokens":6000,"n_ctx":2000}}'
    first = http_error(raw)
    second = http_error(raw)
    response = Response(SSE if streaming else RAW_SUCCESS)
    api, provider, log = client(monkeypatch, [first, second if second_rejects else response], window=2000, level=3)
    choices = []
    def choose(facts):
        choices.append(facts)
        return capacitypolicy.choose_refit(facts)
    runtime = selection(level=3, definition=replace(capacitypolicy.DEFINITION, execute=choose))
    with assistruntime.bound(runtime):
        if second_rejects:
            with pytest.raises(UpstreamError) as caught:
                invoke(api, log, body, streaming)
            assert type(caught.value) is UpstreamError
            assert caught.value.__cause__ is second
        else:
            assert invoke(api, log, body, streaming) == (SSE if streaming else RAW_SUCCESS)
            assert response.closed
    expected_initial = json.dumps({**body, "stream": streaming}).encode()
    note = {"role": "user", "content": (
        "⟦ctx:compacted⟧ 1 earlier turn(s) were compacted to fit the context window.\n"
        "Summary of what those turns contained:\n• › [assistant] 3,000 bytes of text\n"
        "Lines beginning › name a turn whose own content did not fit this note. The line says what the turn was; its text is not in the window any more, and nothing here is a quote of it.\n"
        "Everything above describes turns that have already happened. Where it quotes a file, that is what the file said THEN — the workspace has moved on since, so its current text is what read_file returns now, or a later copy of it in this conversation if there is one.")}
    expected_refit = json.dumps({"model": "capacity-fixture", "messages": [note,
        {"role": "user", "content": "root"}, {"role": "user", "content": "hello"}],
        "max_tokens": 32, "stream": streaming}).encode()
    assert [wire for wire, _ in provider.requests] == [expected_initial, expected_refit]
    assert len(choices) == 1
    assert choices[0].rejection.source is first
    assert choices[0].prepared.wire is provider.requests[0][0]
    assert first.response_body == raw
    assert sum(name == "context.refit" for name, _ in log.events) == 1


@pytest.mark.parametrize("failure", ["none", "iteration"])
def test_public_stream_each_yield_and_close_restore_consumer_runtime(monkeypatch, failure):
    a, b = selection(), selection(absent=True)
    api, _, log = client(monkeypatch, [])
    response = Response(SSE)
    closed_under = []
    def close():
        closed_under.append(assistruntime.current())
        response.closed = True
    response.close = close
    class BrokenResponse(Response):
        def __iter__(self):
            yield b"data: first\n"
            raise RuntimeError("scripted iteration error")
    if failure == "iteration":
        response = BrokenResponse(b"")
        response.close = close
    api._receive_open = Provider([response])
    with assistruntime.bound(a):
        iterator = api.stream_chat(dict(BODY), log)
    with assistruntime.bound(b):
        assert next(iterator) == (b"data: first\n" if failure == "iteration" else SSE.splitlines(keepends=True)[0])
        assert assistruntime.current() is b  # Suspended, not merely exhausted.
        other, other_provider, other_log = client(monkeypatch, [Response(RAW_SUCCESS)])
        assert other.chat(dict(BODY), other_log) == RAW_SUCCESS
        assert assistruntime.current() is b
        assert other_provider.requests == [(WIRE, 600)]
        if failure == "iteration":
            with pytest.raises(RuntimeError, match="scripted iteration error"):
                next(iterator)
        else:
            iterator.close()
        assert assistruntime.current() is b
    assert response.closed
    assert closed_under == [a]


@pytest.mark.parametrize("custody_failure", ["close", "store"])
def test_public_failed_http_evidence_custody_never_consults_replacement(monkeypatch, custody_failure):
    capture = MemoryCapture(monkeypatch)
    original = http_error()
    choices = []
    def adversarial(facts):
        choices.append(facts)
        return capacitypolicy.Refit(2.0)
    if custody_failure == "close":
        def bad_close():
            raise OSError("scripted close failure")
        original.close = bad_close
    else:
        def bad_store(*args, **kwargs):
            raise OSError("scripted evidence write failure")
        monkeypatch.setattr(upstream.callcapture, "capture_response", bad_store)
    api, _, log = client(monkeypatch, [])
    api._capture_dir = "/fake-capture"
    sent, receipts = [], []
    def send(req, *, timeout, receipt):
        sent.append(req.data)
        receipts.append(receipt)
        raise original
    api._receive_open = send
    with assistruntime.bound(selection(definition=replace(capacitypolicy.DEFINITION, execute=adversarial))):
        with pytest.raises(UpstreamError) as caught:
            api.chat(dict(BODY), log)
    assert type(caught.value) is UpstreamError
    assert caught.value.__cause__ is original
    assert original.response_body == RAW_ERROR
    assert sent == [WIRE]
    assert choices == []
    assert len(capture.requests) == 1 and receipts[0].finished
    assert any("secondary" in note for note in original.__notes__)


@pytest.mark.parametrize("streaming", [False, True])
def test_public_mid_refit_runtime_and_transport_swap_retains_original_services(monkeypatch, streaming):
    capture = MemoryCapture(monkeypatch)
    original = http_error()
    chosen = []
    def choose(facts):
        chosen.append(facts)
        return capacitypolicy.Refit(2.0)
    a = selection(definition=replace(capacitypolicy.DEFINITION, execute=choose))
    b = selection(absent=True)
    api, _, log = client(monkeypatch, [])
    api._capture_dir = "/fake-capture"
    body = dict(BODY)
    sent = []
    response = Response(SSE if streaming else RAW_SUCCESS)
    def stolen(*args, **kwargs):
        raise AssertionError("retry used replacement transport rather than captured service")
    def send(req, *, timeout, receipt):
        sent.append(req.data)
        if len(sent) == 1:
            # A caller-owned input update is observable at the real final _prep.
            # No fake serialized bytes/preparer/fitter is substituted here.
            body["max_tokens"] = 64
            api._receive_open = stolen
            with assistruntime.bound(b):
                raise original
        receipt.finish()
        return response
    api._receive_open = send
    with assistruntime.bound(a):
        if streaming:
            iterator = api.stream_chat(body, log)
        else:
            assert api.chat(body, log) == RAW_SUCCESS
    if streaming:
        with assistruntime.bound(b):
            assert b"".join(iterator) == SSE
            assert assistruntime.current() is b
    expected_second = b'{"model": "capacity-fixture", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 64, "stream": ' + (b'true}' if streaming else b'false}')
    assert sent == [STREAM_WIRE if streaming else WIRE, expected_second]
    assert len(chosen) == 1
    assert chosen[0].prepared.wire is sent[0]
    assert chosen[0].rejection.source is original
    assert original.response_body == RAW_ERROR
    assert [metadata["assist_selection"]["selected"] for _, metadata in capture.requests] == [list(a.selected), list(a.selected)]
    assert response.closed


@pytest.mark.parametrize("absent", [False, True])
def test_public_untyped_timeout_lookalike_keeps_ordinary_transient_recovery(monkeypatch, absent):
    first = urllib.error.URLError("timeout")
    response = Response(RAW_SUCCESS)
    api, provider, log = client(monkeypatch, [first, response])
    classified, waits = [], []
    original_classifier = upstream.failover.classify_failure
    def classify(*args):
        classified.append(args)
        return original_classifier(*args)
    monkeypatch.setattr(upstream.failover, "classify_failure", classify)
    monkeypatch.setattr(upstream.time, "sleep", lambda seconds: waits.append(seconds))
    with assistruntime.bound(selection(absent=absent)):
        assert api.chat({**BODY, upstream.bodykeys.CONTEXT_REFIT_NO_CHANGE:
            SimpleNamespace(final_wire=WIRE)}, log) == RAW_SUCCESS
    assert classified == [(None, "<urlopen error timeout>")]
    assert len(waits) == 1 and waits[0] > 0
    assert provider.requests == [(WIRE, 600), (WIRE, 600)]
    assert response.closed


@pytest.mark.parametrize("absent", [False, True])
def test_public_parsed_window_fact_is_mandatory_even_without_adaptation(monkeypatch, absent):
    original = http_error()
    api, provider, log = client(monkeypatch, [original])
    api._window = 8
    api._window_final = False
    api._window_guessed = True
    api._resolve_window = lambda _: 8
    with assistruntime.bound(selection(absent=absent)):
        with pytest.raises(UpstreamError) as caught:
            api.chat(dict(BODY), log)
    assert type(caught.value) is (UpstreamError if absent else ContextRefitNoChange)
    assert caught.value.__cause__ is original
    assert original.response_body == RAW_ERROR
    assert provider.requests == [(WIRE, 600)]
    assert api._window == 1000 and api._window_final and not api._window_guessed
    assert tokenratio.observed("capacity-fixture") == pytest.approx(3.34)


def test_public_stream_transport_is_captured_at_construction(monkeypatch):
    api, provider, log = client(monkeypatch, [Response(SSE)])
    a, b = selection(), selection(absent=True)
    with assistruntime.bound(a):
        iterator = api.stream_chat(dict(BODY), log)
    def forbidden(*args, **kwargs):
        raise AssertionError("consumer stole constructing transport")
    api._receive_open = forbidden
    with assistruntime.bound(b):
        assert next(iterator) == SSE.splitlines(keepends=True)[0]
        assert assistruntime.current() is b
        iterator.close()
        assert assistruntime.current() is b
    assert provider.requests == [(STREAM_WIRE, upstream.rumination.WIRE_SILENCE_SECONDS)]


@pytest.mark.parametrize("streaming", [False, True])
def test_public_missing_request_capture_stops_before_any_send_or_choice(monkeypatch, streaming):
    capture = MemoryCapture(monkeypatch)
    monkeypatch.setattr(upstream.callcapture, "capture", lambda *args, **kwargs: None)
    choices = []
    def choose(facts):
        choices.append(facts)
        return capacitypolicy.Refit(2.0)
    api, provider, log = client(monkeypatch, [])
    api._capture_dir = "/fake-capture"
    with assistruntime.bound(selection(definition=replace(capacitypolicy.DEFINITION, execute=choose))):
        with pytest.raises(receivecapture.CaptureFailure):
            invoke(api, log, dict(BODY), streaming)
    assert provider.requests == choices == []
    assert capture.files == {}


@pytest.mark.parametrize("streaming", [False, True])
def test_public_source_choice_receives_original_prepared_object(monkeypatch, streaming):
    actual_dispatch = capacitypolicy.dispatch
    prepared, choices = [], []
    def traced(services, definition, **kwargs):
        def send(source):
            prepared.append(source)
            return services.send(source)
        return actual_dispatch(replace(services, send=send), definition, **kwargs)
    monkeypatch.setattr(capacitypolicy, "dispatch", traced)
    original = http_error()
    def decline(facts):
        choices.append(facts)
        return None
    api, provider, log = client(monkeypatch, [original])
    with assistruntime.bound(selection(definition=replace(capacitypolicy.DEFINITION, execute=decline))):
        with pytest.raises(UpstreamError) as caught:
            invoke(api, log, dict(BODY), streaming)
    assert type(caught.value) is UpstreamError
    assert caught.value.__cause__ is original
    assert len(prepared) == len(choices) == 1
    assert choices[0].prepared is prepared[0]
    assert prepared[0].wire is provider.requests[0][0]
    assert prepared[0].wire == (STREAM_WIRE if streaming else WIRE)
    assert original.response_body == RAW_ERROR


@pytest.mark.parametrize("absent", [False, True])
def test_public_nested_changed_wire_empty_result_is_not_suppressed(monkeypatch, absent):
    original = http_error()
    inner = ContextRefitNoChange(original, WIRE)
    response = Response(b"")
    api, provider, log = client(monkeypatch, [response])
    with assistruntime.bound(selection(absent=absent)):
        assert api.chat({**BODY, "max_tokens": 64,
            upstream.bodykeys.CONTEXT_REFIT_NO_CHANGE: inner}, log) == b""
    assert response.closed
    assert provider.requests == [(b'{"model": "capacity-fixture", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 64, "stream": false}', 600)]


def test_public_stream_cancel_before_start_has_no_effects(monkeypatch):
    api, provider, log = client(monkeypatch, [])
    a, b = selection(), selection(absent=True)
    with assistruntime.bound(a):
        iterator = api.stream_chat(dict(BODY), log)
    with assistruntime.bound(b):
        iterator.close()
        assert assistruntime.current() is b
    assert provider.requests == []
    assert log.events == []


@pytest.mark.parametrize("model_input", [None, "", "capacity-fixture"])
@pytest.mark.parametrize("caller_retry", [False, True])
def test_public_no_change_events_use_model_resolved_by_actual_prepare(monkeypatch, model_input, caller_retry):
    original = http_error()
    api, provider, log = client(monkeypatch, [original])
    discoveries = []
    def loaded(rlog):
        discoveries.append(rlog)
        return "discovered-fixture"
    api.loaded_model = loaded
    body = {"messages": [{"role": "user", "content": "hello"}]}
    if model_input is not None:
        body = {"model": model_input, **body}
    resolved = model_input or "discovered-fixture"
    if model_input is None:
        expected = b'{"messages": [{"role": "user", "content": "hello"}], "model": "discovered-fixture", "stream": false}'
    elif model_input == "":
        expected = b'{"model": "discovered-fixture", "messages": [{"role": "user", "content": "hello"}], "stream": false}'
    else:
        expected = WIRE
    if caller_retry:
        upstream._http_error_body(original)
        inner = ContextRefitNoChange(original, expected)
        body[upstream.bodykeys.CONTEXT_REFIT_NO_CHANGE] = inner
    with assistruntime.bound(selection()):
        error_type = upstream.CallerContextRetryNoChange if caller_retry else ContextRefitNoChange
        with pytest.raises(error_type) as caught:
            api.chat(body, log)
    assert type(caught.value) is error_type
    assert caught.value.__cause__ is (inner if caller_retry else original)
    assert caught.value.final_wire == expected
    assert provider.requests == ([] if caller_retry else [(expected, 600)])
    assert original.response_body == RAW_ERROR
    event_name = "upstream.caller_retry_no_change" if caller_retry else "upstream.refit_no_change"
    warnings = [fields for name, fields in log.events if name == event_name]
    assert warnings == [{"level": "warn", "bytes": len(expected), "model": resolved, "est": 1}]
    assert discoveries == ([log] if not model_input else [])
    if not caller_retry:
        assert [fields["model"] for name, fields in log.events if name == "context.refit"] == [resolved]


@pytest.mark.parametrize("fault", ["source-bypass", "canonical-fallback", "learned-absence",
                                   "stale-wire", "late-owner", "late-capture", "yield-leak"])
def test_public_semantic_binding_faults_are_rejected_then_restored(monkeypatch, fault):
    original_dispatch = capacitypolicy.dispatch
    original_stream = Upstream.stream_chat
    fault_iterators = []
    if fault == "source-bypass":
        oracle = lambda patch: test_public_optional_choice_uses_exact_selected_owner(patch, False, "replacement")
        def mutate(patch):
            patch.setattr(capacitypolicy, "dispatch", lambda services, definition, **kw:
                          original_dispatch(services, None, **kw))
    elif fault == "canonical-fallback":
        oracle = lambda patch: test_public_optional_choice_uses_exact_selected_owner(patch, False, "absent")
        def mutate(patch):
            patch.setattr(capacitypolicy, "dispatch", lambda services, definition, **kw:
                          original_dispatch(services, capacitypolicy.DEFINITION, **kw))
    elif fault == "learned-absence":
        oracle = test_public_absence_keeps_required_floor_without_learned_lookup
        def mutate(patch):
            patch.setattr(capacitypolicy, "fit_density", lambda model, definition: tokenratio.observed(model))
    elif fault == "stale-wire":
        oracle = lambda patch: test_public_real_floor_changed_wire_retry_is_bounded(patch, False, False)
        def mutate(patch):
            def stale(services, definition, **kwargs):
                first = []
                def send(prepared):
                    first.append(prepared)
                    return services.send(first[0])
                return original_dispatch(replace(services, send=send), definition, **kwargs)
            patch.setattr(capacitypolicy, "dispatch", stale)
    elif fault in ("late-owner", "late-capture"):
        oracle = (lambda patch: test_public_stream_constructor_pins_owner_before_first_yield(patch, 3)) if fault == "late-owner" else test_public_stream_capture_selection_pinned_across_runtime_swap
        def mutate(patch):
            def late(self, body, log):
                yield from original_stream(self, body, log)
            patch.setattr(Upstream, "stream_chat", late)
    else:
        oracle = lambda patch: test_public_stream_each_yield_and_close_restore_consumer_runtime(patch, "none")
        def mutate(patch):
            def leaking(self, body, log):
                selected = assistruntime.current()
                iterator = original_stream(self, body, log)
                def run():
                    with assistruntime.bound(selected):
                        try:
                            yield from iterator
                        finally:
                            iterator.close()
                result = run()
                fault_iterators.append(result)
                return result
            patch.setattr(Upstream, "stream_chat", leaking)
    # Failure and restored control use the SAME full literal public oracle.
    with assistruntime.bound(assistruntime.current()):
        with monkeypatch.context() as patch:
            mutate(patch)
            try:
                with pytest.raises(AssertionError):
                    oracle(patch)
            finally:
                for iterator in fault_iterators:
                    iterator.close()
    with monkeypatch.context() as patch:
        oracle(patch)
