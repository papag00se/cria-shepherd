"""HTTP edge arms of the real CriaServer: unknown paths, malformed/empty/non-object bodies on both endpoints, /v1/models
with and without a loaded model or a window, upstream failures buffered and streamed on the Responses path, and a client that vanishes mid-stream."""
import json
import socket
import time
import urllib.error
import urllib.request

import pytest

import test_server_config_http as H
from test_server_config_http import Wire, no_installed_opener, request, sse_events  # noqa: F401


def raw_request(w, method, path, body=b"", headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{w.cria.server_address[1]}{path}", data=body or None, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with H.OPEN(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


@pytest.fixture
def w(tmp_path):
    wire = Wire(tmp_path)
    yield wire
    wire.close()


@pytest.mark.parametrize("method, path, body, code, message", [
    ("GET", "/nope", b"", 404, "not found"),
    ("POST", "/v1/nope", b"{}", 404, "not found"),
    ("POST", "/v1/chat/completions", b"{nope", 400, "invalid JSON body"),
    ("POST", "/v1/chat/completions", b"", 400, "empty body"),
    ("POST", "/v1/chat/completions", b"[1, 2]", 400, "body must be a JSON object"),
    ("POST", "/v1/responses", b"{nope", 400, "invalid JSON body"),
    ("POST", "/v1/responses", b"", 400, "empty body"),
    ("POST", "/v1/responses", b'"text"', 400, "body must be a JSON object"),
    ("POST", "/v1/responses", b'{"input": "hi", "tool_choice": {"type": "mcp"}}', 400, "unsupported Responses tool_choice"),
    ("POST", "/v1/responses", b'{"input": "hi", "tools": [{"type": "web_search_preview"}]}', 400, "unsupported Responses tool type"),
])
def test_bad_requests_get_a_json_error_and_never_reach_the_model(w, method, path, body, code, message):
    """Unknown routes are 404; a malformed, empty or non-object body is a 400 JSON error on both endpoints, with nothing sent upstream."""
    status, raw = raw_request(w, method, path, body)
    assert status == code and message in json.loads(raw)["error"]
    assert w.fake.chats == []


def test_trailing_slash_and_health_and_the_models_card_carry_the_runtime_window(w):
    """/health/ routes like /health; /v1/models/ advertises the loaded model under every window key the ecosystem reads."""
    assert raw_request(w, "GET", "/health/") == (200, '{"status": "ok"}')
    card = json.loads(raw_request(w, "GET", "/v1/models/?x=1")[1])["data"][0]
    assert card["id"] == "loaded" and {card[k] for k in ("context_window", "max_context_window", "context_length", "max_model_len")} == {H.WINDOW}
    assert card["meta"] == {"n_ctx": H.WINDOW}


def test_models_card_is_empty_without_a_loaded_model_and_omits_the_window_without_props(tmp_path, monkeypatch):
    """No model loaded -> an empty list (never an invented name); a model with no /props -> the card without any window field."""
    class Bare(H.FakeUpstream):
        def do_GET(self):
            self._reply({"data": []} if self.path.endswith("/v1/models") else {}, code=200 if self.path.endswith("/v1/models") else 404)
    monkeypatch.setattr(H, "FakeUpstream", Bare)
    wire = Wire(tmp_path)
    try:
        assert json.loads(raw_request(wire, "GET", "/v1/models")[1]) == {"object": "list", "data": [], "models": []}
    finally:
        wire.close()

    class NoProps(H.FakeUpstream):
        def do_GET(self):
            self._reply({"data": [{"id": "m1"}]}, code=200) if self.path.endswith("/v1/models") else self._reply({}, code=404)
    monkeypatch.setattr(H, "FakeUpstream", NoProps)
    wire = Wire(tmp_path / "b")
    try:
        entry = json.loads(raw_request(wire, "GET", "/v1/models")[1])["data"][0]
    finally:
        wire.close()
    assert entry == {"id": "m1", "slug": "m1", "object": "model", "owned_by": "cria"}


def test_responses_buffered_maps_upstream_failures_to_json_errors_with_the_upstreams_words(w):
    """A 500 on the buffered Responses path is a 5xx JSON error carrying the model server's message; a 200 HTML page is a 502, never a fake completion."""
    path, body = request("responses-buffered", "__500__")
    status, raw = raw_request(w, "POST", path, json.dumps(body).encode())
    assert status >= 500 and "template rejected" in raw
    path, body = request("responses-buffered", "__NONJSON__")
    status, raw = raw_request(w, "POST", path, json.dumps(body).encode())
    assert status == 502 and "output" not in raw


def test_a_client_that_vanishes_mid_stream_is_logged_and_the_stream_unregistered(tmp_path):
    """The harness hangs up while a Responses stream is open: the handler records response.client_gone and releases the stream registration instead of dying silently."""
    wire = Wire(tmp_path, heartbeat=0.05)
    try:
        path, body = request("responses-stream", "__SLOW__")
        s = socket.create_connection(("127.0.0.1", wire.cria.server_address[1]), timeout=10)
        data = json.dumps(body).encode()
        s.sendall(b"POST " + path.encode() + b" HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: "
                  + str(len(data)).encode() + b"\r\n\r\n" + data)
        seen = b""
        while b"response.in_progress" not in seen:
            seen += s.recv(4096)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")  # RST, not FIN
        s.close()
        wire.fake.release.set()  # the model answers into the dead socket
        for _ in range(200):
            if any(e["kind"] == "response.client_gone" for e in wire.events()):
                break
            time.sleep(0.05)
        gone = [e for e in wire.events() if e["kind"] == "response.client_gone"]
    finally:
        wire.fake.release.set()
        wire.close()
    assert gone and gone[0]["level"] == "warn" and wire.cria.active_streams == {}
