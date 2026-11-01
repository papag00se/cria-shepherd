"""Hostile input at cria's HTTP edge: every request is answered or refused with a JSON error, never a silent connection drop,
a hung handler thread or an unbounded allocation; an unexpected pipeline exception is logged and answered, not swallowed."""
import json
import socket
import threading
import time

import pytest

import test_server_config_http as H
from test_server_config_http import Wire, no_installed_opener, request  # noqa: F401
from cria import server


@pytest.fixture
def w(tmp_path):
    wire = Wire(tmp_path)
    yield wire
    wire.close()


def exchange(w, data: bytes, *, wait=5.0, then=b""):
    """Send raw bytes, read one HTTP response (status line, headers, Content-Length body); a closed connection reads as b''."""
    s = socket.create_connection(("127.0.0.1", w.cria.server_address[1]), timeout=wait)
    try:
        s.sendall(data)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                return b"", b""
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        want = next((int(l.split(b":")[1]) for l in head.split(b"\r\n") if l.lower().startswith(b"content-length")), 0)
        while len(rest) < want:
            rest += s.recv(65536)
        if then:  # the SAME connection must still be a clean HTTP stream (no leftover body parsed as a request)
            s.sendall(then)
            more = s.recv(65536)
            return head, rest + b"|" + more
        return head, rest
    finally:
        s.close()


def post(w, body: bytes, path="/v1/chat/completions", headers=b""):
    return exchange(w, b"POST " + path.encode() + b" HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n" + headers
                    + b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)


def threads_settle(before, seconds=5.0):
    end = time.time() + seconds
    while threading.active_count() > before and time.time() < end:
        time.sleep(0.05)
    return threading.active_count()


CHAT_USER = {"role": "user", "content": "hi"}


@pytest.mark.parametrize("path, body", [
    ("/v1/chat/completions", b"[" * 200000),                                                     # nesting deeper than the parser's stack
    ("/v1/chat/completions", b'{"messages": "x"}'),                                              # messages not a list
    ("/v1/chat/completions", json.dumps({"messages": [1, 2]}).encode()),                         # messages not objects
    ("/v1/chat/completions", json.dumps({"messages": [{"role": "user", "content": 5}]}).encode()),
    ("/v1/chat/completions", json.dumps({"messages": [CHAT_USER], "tools": "x"}).encode()),
    ("/v1/chat/completions", b'{"messages": [{"role": "user", "content": "hi"}], "messages": "dup"}'),  # last duplicate wins
    ("/v1/chat/completions", b'{"messages": [{"role": "user", "content": "\xff\xfe"}]}'),        # invalid UTF-8
    ("/v1/responses", b'{"input": 5}'),
    ("/v1/responses", b'{"input": {"a": 1}}'),
])
def test_valid_or_invalid_json_of_the_wrong_shape_is_a_json_400_never_a_dropped_connection(w, path, body):
    """A body the pipeline cannot use is refused with a 400 JSON error that reaches the client; nothing is sent upstream."""
    head, raw = post(w, body, path)
    assert head.startswith(b"HTTP/1.1 400"), (head, raw)
    assert json.loads(raw)["error"]
    assert w.fake.chats == []


def test_a_string_input_is_the_user_message_not_silently_dropped(w):
    """Responses `input` may be a bare string (one user message); it reaches the model instead of vanishing."""
    head, raw = post(w, json.dumps({"input": "say pineapple", "stream": False}).encode(), "/v1/responses")
    assert head.startswith(b"HTTP/1.1 200"), (head, raw)
    assert "say pineapple" in json.dumps(w.fake.chats[-1][1]["messages"])


def test_an_unexpected_pipeline_exception_is_logged_and_answered_with_a_500(w, monkeypatch):
    """A bug past the edge must not leave the client with a reset: the handler logs request.error with the exception and answers 500 JSON; the next request on the server works."""
    def boom(*a, **k):
        raise RuntimeError("synthetic pipeline bug")
    monkeypatch.setattr(server, "carry_chat_system", boom)
    head, raw = post(w, json.dumps({"messages": [CHAT_USER]}).encode())
    assert head.startswith(b"HTTP/1.1 500") and "synthetic pipeline bug" in json.loads(raw)["error"]
    errs = [e for e in w.events() if e["kind"] == "request.error"]
    assert errs and errs[0]["level"] == "error" and "RuntimeError" in errs[0]["error"]
    monkeypatch.undo()
    assert post(w, json.dumps({"messages": [CHAT_USER]}).encode())[0].startswith(b"HTTP/1.1 200")


def test_an_oversized_declared_body_is_refused_with_413_before_any_of_it_is_read(w, monkeypatch):
    """Content-Length beyond the cap is a 413 and the connection closes (the unread body must not be parsed as the next request)."""
    monkeypatch.setattr(server, "MAX_BODY_BYTES", 1000)
    head, raw = exchange(w, b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nContent-Length: 99999999999\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 413") and b"Connection: close" in head and "too large" in json.loads(raw)["error"]


def test_a_chunked_body_is_refused_with_411_and_the_connection_closes(w):
    """cria reads Content-Length bodies only; a chunked one must be named, not mistaken for an empty body with its chunks left to parse as the next request."""
    head, raw = exchange(w, b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 411") and b"Connection: close" in head and "Content-Length" in json.loads(raw)["error"]


@pytest.mark.parametrize("length", [b"-5", b"abc", b"1e3", b"+7"])
def test_a_malformed_content_length_is_a_400(w, length):
    head, raw = exchange(w, b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nContent-Length: " + length + b"\r\n\r\n{}")
    assert head.startswith(b"HTTP/1.1 400") and "Content-Length" in json.loads(raw)["error"]


def test_a_body_that_stalls_is_timed_out_and_its_thread_is_released(w, monkeypatch):
    """A client that declares a body and then goes quiet gets a 408 after the deadline instead of holding a handler thread forever."""
    monkeypatch.setattr(server, "BODY_DEADLINE_SECONDS", 0.5)
    before = threading.active_count()
    s = socket.create_connection(("127.0.0.1", w.cria.server_address[1]), timeout=10)
    s.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nContent-Length: 500\r\n\r\n{\"mess")
    t0 = time.time()
    reply = s.recv(65536)
    s.close()
    assert reply.startswith(b"HTTP/1.1 408") and time.time() - t0 < 5
    assert threads_settle(before) <= before


def test_a_connection_that_never_sends_a_request_is_closed_and_its_thread_released(w, monkeypatch):
    """A connect-and-idle (or header-dribbling) client cannot pin a handler thread: the request line + headers have a deadline."""
    monkeypatch.setattr(server.CriaHandler, "REQUEST_HEAD_TIMEOUT_SECONDS", 0.5)
    before = threading.active_count()
    s = socket.create_connection(("127.0.0.1", w.cria.server_address[1]), timeout=10)
    s.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\n")  # headers never finish
    assert s.recv(65536) == b""                                      # closed by the server, not by our timeout
    s.close()
    assert threads_settle(before) <= before


def test_a_slow_model_turn_is_not_cut_by_the_head_deadline(w, monkeypatch):
    """The head deadline ends when the head is read: a stream whose first byte takes longer than it still completes."""
    monkeypatch.setattr(server.CriaHandler, "REQUEST_HEAD_TIMEOUT_SECONDS", 0.3)
    path, body = request("chat-buffered", "__SLOW__")
    threading.Timer(1.0, w.fake.release.set).start()
    head, raw = post(w, json.dumps(body).encode(), path, headers=b"")
    assert head.startswith(b"HTTP/1.1 200"), (head, raw)
