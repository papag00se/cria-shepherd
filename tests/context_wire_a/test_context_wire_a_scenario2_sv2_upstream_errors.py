"""Upstream error mapping end to end through the real Upstream with only the transport faked: buffered failures and the one timeout retry,
the stream opener, the proxy stream's accounting, and every way chat_watched can end (which guard, which label on the saved reasoning, protocol and re-ask arms)."""
import io
import json
import pathlib
import urllib.error

import pytest

from cria import generation
from cria.upstream import Upstream, UpstreamError, UpstreamProtocolError
from test_context_wire_a_stream import MESSAGES, Rlog, Stream, sse


def http(code, body):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return urllib.error.HTTPError("http://x/v1/chat/completions", code, "Bad", {}, io.BytesIO(raw))


class Buffered(Stream):
    def __init__(self, text="ok"):
        super().__init__([])
        self.payload = json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}], "usage": {"completion_tokens": 2}}).encode()

    def read(self, *a):
        return self.payload


def upstream(script, tmp_path=None, window=8192):
    """An Upstream whose transport plays `script` in order: an exception is raised at open, anything else is the response."""
    script, opened = list(script), []

    def open_request(req, timeout=None, receipt=None):
        opened.append(json.loads(req.data))
        item = script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
    kw = {"capture_dir": str(tmp_path), "capture_rendered": False} if tmp_path else {}
    return Upstream("http://fixture.invalid", context_window=window, open_request=open_request, **kw), opened


@pytest.mark.parametrize("script, code, response_error, opens", [
    ([http(500, {"error": {"message": "boom", "code": 7}})], 500, {"message": "boom"}, 1),       # a non-string code is dropped
    ([http(400, {"message": "bare payload"})], 400, None, 1),
    ([http(400, b"<html>gateway</html>")], 400, {"message": "HTTP Error 400: Bad"}, 1),         # not JSON: the status line is the message
    ([http(400, {"error": {"message": "bad", "type": generation.PROTOCOL_ERROR}})], 400, {"message": "bad", "type": generation.PROTOCOL_ERROR}, 1),
    ([urllib.error.URLError("refused")], None, {"message": "<urlopen error refused>"}, 1),
    ([http(400, {"error": {"n_prompt_tokens": 9000, "n_ctx": 8192, "message": "too big"}}),
      http(400, {"error": {"n_prompt_tokens": 9000, "n_ctx": 8192, "message": "too big"}})], 400,
     {"message": "too big", "code": "context_length_exceeded", "n_prompt_tokens": 9000, "n_ctx": 8192}, 1),
])
def test_buffered_failures_become_one_typed_error_with_the_servers_words_and_are_not_retried(script, code, response_error, opens):
    """The server's refusal reaches the caller as UpstreamError(code, the server's own error object) after exactly the expected number of sends."""
    up, opened = upstream(script)
    rlog = Rlog()
    with pytest.raises(UpstreamError) as err:
        up.chat(dict(MESSAGES), rlog)
    assert err.value.code == code and len(opened) == opens
    if response_error is not None:
        assert err.value.response_error == response_error
    assert [k for k, _ in rlog.events].count("upstream.error") == 1


def test_a_buffered_timeout_is_retried_once_after_a_wait_then_surfaces(monkeypatch):
    """A slow prefill that times out is asked again once (logged with its wait); the second timeout is the caller's."""
    waits = []
    monkeypatch.setattr("time.sleep", waits.append)
    up, opened = upstream([TimeoutError("timed out"), Buffered("recovered")])
    rlog = Rlog()
    assert json.loads(up.chat(dict(MESSAGES), rlog))["choices"][0]["message"]["content"] == "recovered"
    assert len(opened) == 2 and len(waits) == 1 and waits[0] > 0 and rlog.first("upstream.retry")["attempt"] == 1
    up, opened = upstream([TimeoutError("timed out")] * 3)
    with pytest.raises(TimeoutError):
        up.chat(dict(MESSAGES), Rlog())
    assert len(opened) == 2


def test_the_proxy_stream_forwards_frames_verbatim_and_accounts_for_reasoning_and_usage(tmp_path):
    """stream_chat yields the server's raw lines unchanged; the first reasoning delta counts as the first token (channel=reasoning), the reasoning is saved, and done carries the usage tokens."""
    frames = [sse({"reasoning_content": "thinking it over"}), sse({"content": "answer"}),
              b'data: {"choices": [], "usage": {"completion_tokens": 9}}\n', b"data: [DONE]\n", b": comment\n"]
    up, _ = upstream([Stream(frames)], tmp_path)
    rlog = Rlog()
    assert list(up.stream_chat(dict(MESSAGES), rlog)) == frames
    assert rlog.first("upstream.first_token")["channel"] == "reasoning"
    assert rlog.first("upstream.done")["tokens"] == 9 and rlog.first("upstream.done")["from_usage"] is True
    (saved,) = pathlib.Path(tmp_path).rglob("*.reasoning.txt")
    assert saved.read_text().strip().endswith("thinking it over")


def test_the_proxy_stream_opener_failure_and_a_client_that_stops_reading_are_both_accounted(tmp_path):
    """A rejected open raises on the first read with the server's error; a consumer that closes after one frame still gets the done accounting and a closed response."""
    up, _ = upstream([http(500, {"error": {"message": "down"}})])
    with pytest.raises(UpstreamError) as err:
        next(iter(up.stream_chat(dict(MESSAGES), Rlog())))
    assert err.value.code == 500
    stream = Stream([sse({"content": "a"}), sse({"content": "b"})])
    closed = []
    stream.close = lambda: closed.append(True)
    up, _ = upstream([stream])
    rlog = Rlog()
    gen = up.stream_chat(dict(MESSAGES), rlog)
    next(gen)
    gen.close()
    assert closed and rlog.first("upstream.done")["from_usage"] is False and rlog.first("upstream.done")["tokens"] == 1


def reasoning(n):
    return [sse({"reasoning_content": f" w{i} "}) for i in range(n)]


@pytest.mark.parametrize("frames, window, header, kind", [
    (reasoning(5000), 5200, "⟦WINDOW-EXHAUSTED ABORT⟧", "window_exhausted"),
    ([sse({"reasoning_content": "ab"}) for _ in range(3000)], 8192, "⟦DEGENERATE-RUN ABORT⟧ the last 2048 characters", "degenerate"),
])
def test_each_stream_backstop_names_itself_and_its_own_numbers_in_the_saved_reasoning(tmp_path, frames, window, header, kind):
    """The saved reasoning of an aborted stream is headed by THE guard that fired (never the rumination header with None counters) and the completion is a re-promptable rumination turn."""
    up, _ = upstream([Stream(frames + [sse({}, finish="stop")])], tmp_path, window)
    rlog = Rlog()
    completion = json.loads(up.chat_watched(dict(MESSAGES), rlog))
    assert completion["choices"][0]["finish_reason"] == "rumination" and rlog.first("rumination.abort")[kind]
    (saved,) = pathlib.Path(tmp_path).rglob("*.reasoning.txt")
    text = saved.read_text()
    assert text.startswith(header) and "None" not in text.splitlines()[0] and "ABORTED HERE" in text


def test_a_silent_wire_and_an_unterminated_stream_are_labelled_incomplete_and_never_assembled_into_an_answer(tmp_path):
    """TimeoutError mid-read -> dead-stream abort label; a stream that just ends (no finish) -> a typed incomplete_stream_error carrying the raw prefix, with the reasoning saved under an INCOMPLETE banner."""
    def die():
        raise TimeoutError("timed out")
    up, _ = upstream([Stream(reasoning(1), at_end=die)], tmp_path / "silent")
    out = json.loads(up.chat_watched(dict(MESSAGES), Rlog()))
    assert out["choices"][0]["finish_reason"] == "rumination"
    assert next(pathlib.Path(tmp_path / "silent").rglob("*.reasoning.txt")).read_text().startswith("⟦DEAD-STREAM ABORT⟧")
    up, _ = upstream([Stream(reasoning(2))], tmp_path / "cut")
    with pytest.raises(UpstreamError) as err:
        up.chat_watched(dict(MESSAGES), Rlog())
    error = err.value.response_error
    assert error["type"] == generation.INCOMPLETE_STREAM_ERROR and error["generation_evidence"]["stream_prefix"]["reasoning_content"] == " w0  w1 "
    assert next(pathlib.Path(tmp_path / "cut").rglob("*.reasoning.txt")).read_text().startswith("⟦INCOMPLETE REASONING⟧ the stream did not finish: Upstream stream ended")


def test_a_stream_error_frame_discards_the_fragment_and_reasks_buffered_but_a_protocol_error_frame_propagates_whole(tmp_path):
    """llama.cpp 'Invalid diff' mid-tool-call: the fragment is dropped (logged with what was dropped) and the SAME request is asked buffered; a typed generation-protocol error frame instead raises UpstreamProtocolError with the raw wire hex and prefix, not a retry."""
    partial = [sse({"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "shell", "arguments": '{"cmd": "ls'}}]}),
               b'data: {"error": {"message": "Invalid diff"}}\n']
    up, opened = upstream([Stream(partial), Buffered("whole answer")], tmp_path / "a")
    rlog = Rlog()
    out = json.loads(up.chat_watched(dict(MESSAGES), rlog))
    assert out["choices"][0]["message"]["content"] == "whole answer" and len(opened) == 2
    assert opened[0]["stream"] is True and opened[1].get("stream") is not True and "stream_options" not in opened[1]
    assert rlog.first("upstream.stream_error")["dropped_tool_arg_chars"] == len('{"cmd": "ls')
    proto = {"message": "tool call was malformed", "type": generation.PROTOCOL_ERROR}
    up, opened = upstream([Stream(reasoning(1) + [b"data: " + json.dumps({"error": proto}).encode() + b"\n"])], tmp_path / "b")
    with pytest.raises(UpstreamProtocolError) as err:
        up.chat_watched(dict(MESSAGES), Rlog())
    evidence = err.value.response_error[generation.EVIDENCE]
    assert len(opened) == 1 and evidence["stream_prefix"]["reasoning_content"] == " w0 " and bytes.fromhex(evidence["wire_raw_hex"]).startswith(b"data:")


def test_a_length_finish_stays_length_so_the_caller_can_see_the_cut():
    """A generation the server cut at its token limit is returned as finish_reason=length with its text, never relabelled stop."""
    up, _ = upstream([Stream([sse({"content": "x"}), sse({}, finish="length")])])
    out = json.loads(up.chat_watched(dict(MESSAGES), Rlog()))
    assert out["choices"][0]["finish_reason"] == "length" and out["choices"][0]["message"]["content"] == "x"


def refused(code, headers, body=b"slow down"):
    return urllib.error.HTTPError("http://fixture.invalid/v1/chat/completions", code, "Too Many Requests", headers, io.BytesIO(body))


@pytest.fixture
def clocked(monkeypatch):
    """One fake clock for the retry sleeper AND the process's rate-limit wait state: every sleep advances it and is recorded."""
    from cria import ratelimit

    class Clock:
        t, slept = 0.0, []

        def sleep(self, seconds):
            self.slept.append(seconds)
            self.t += seconds
    clock = Clock()
    clock.slept = []
    monkeypatch.setattr("time.sleep", clock.sleep)
    monkeypatch.setattr(ratelimit, "STATE", ratelimit.WaitState(lambda: clock.t, clock.sleep))
    return clock


@pytest.mark.parametrize("headers, body, waits", [
    ({"Retry-After": "7"}, b"slow down", [7.0]),
    ({"RateLimit-Reset": "3"}, b"slow down", [3.0]),
    ({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "2"}, b"slow down", [2.0]),
    ({}, b'{"error": {"message": "Rate limit reached. Please try again in 1.5s."}}', [1.5]),     # a delay only the body states
    ({}, b'{"error": {"message": "busy"}}', [1.0]),                                                # none stated: the one default pause
])
def test_a_buffered_429_is_retried_once_after_exactly_the_servers_stated_wait(clocked, headers, body, waits):
    """Retry-After / RateLimit-Reset / X-RateLimit-Reset / a body delay each set the sleep; the retry is never sent before it elapsed."""
    up, opened = upstream([refused(429, headers, body), Buffered("after the wait")])
    assert json.loads(up.chat(dict(MESSAGES), Rlog()))["choices"][0]["message"]["content"] == "after the wait"
    assert clocked.slept == waits and len(opened) == 2


def test_a_429_cooldown_is_shared_by_every_request_to_that_endpoint_and_a_long_one_is_not_sent_through(clocked):
    """A second turn (another caller) to a rate-limited endpoint inside the window waits the remainder; over a turn's hold it is refused unsent with the delay."""
    up, opened = upstream([refused(429, {"Retry-After": "120"}), Buffered("never reached")])
    with pytest.raises(UpstreamError) as err:
        up.chat(dict(MESSAGES), Rlog())                       # 120 s is over what a turn can hold: no retry
    assert err.value.code == 429 and err.value.retry_after_ms == 120_000 and clocked.slept == [] and len(opened) == 1
    with pytest.raises(UpstreamError) as again:
        list(up.stream_chat(dict(MESSAGES), Rlog()))          # the other wire mode, same endpoint: not sent
    assert again.value.code == 429 and again.value.retry_after_ms > 0 and len(opened) == 1
    clocked.t += 100.0                                        # 20 s of the window remain: held, then sent
    other, other_opened = upstream([Buffered("ok")])
    assert json.loads(other.chat(dict(MESSAGES), Rlog()))["choices"][0]["message"]["content"] == "ok"
    assert clocked.slept == [20.0] and len(other_opened) == 1


def test_one_credentials_429_does_not_close_another_credentials_door_to_the_same_host(clocked):
    """A quota is per API key: the second key's request to the same host goes through unwaited while the first key stays refused."""
    def keyed(key, script):
        opened = []

        def open_request(req, timeout=None, receipt=None):
            opened.append(req)
            item = script.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        return Upstream("http://fixture.invalid", api_key=key, context_window=8192, open_request=open_request), opened
    first, _ = keyed("key-a", [refused(429, {"Retry-After": "120"})])
    with pytest.raises(UpstreamError):
        first.chat(dict(MESSAGES), Rlog())
    second, opened = keyed("key-b", [Buffered("b ok")])
    assert json.loads(second.chat(dict(MESSAGES), Rlog()))["choices"][0]["message"]["content"] == "b ok" and clocked.slept == [] and len(opened) == 1
    again, refused_opened = keyed("key-a", [Buffered("must not be sent")])
    with pytest.raises(UpstreamError) as held:
        again.chat(dict(MESSAGES), Rlog())
    assert held.value.code == 429 and refused_opened == []
