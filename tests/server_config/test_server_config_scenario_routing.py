"""Provider failover and upstream recovery over real HTTP: the coder chain skips what cannot run and lands on a working endpoint; a rate-limited (429) first try is retried
once; a server-reported context overflow is re-fitted once and the shrunken body is what the model finally answers."""
import json
import threading
import urllib.error
from http.server import ThreadingHTTPServer

import pytest

from cria.config import Backend, Role, RoutingConfig
from test_server_config_http import FakeUpstream, Wire, chat_body, no_installed_opener, request  # noqa: F401


def test_the_coder_chain_skips_a_keyless_remote_and_a_missing_cli_then_serves_from_the_next_endpoint_retrying_a_429(tmp_path, monkeypatch):
    """chain = [remote (key unset), cli (binary absent), local-b on its OWN endpoint]: the first two are skipped with their reasons logged, the turn is answered by b
    (the classifier still rides the shared endpoint), b's first 429 is retried once after a backoff, and the model name shown is the one b reports."""
    monkeypatch.delenv("SC_ROUTE_KEY", raising=False)
    slept = []
    monkeypatch.setattr("cria.upstream.time.sleep", slept.append)
    other = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
    other.chats, other.release, other.flaky = [], threading.Event(), [429]
    threading.Thread(target=other.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    w = Wire(tmp_path, lambda url: RoutingConfig(
        backends={"local": Backend("local"), "remote": Backend("remote", base_url=url, api_key_env="SC_ROUTE_KEY", model="gpt-x"),
                  "cli": Backend("cli", transport="cli", binary="/nonexistent/claude-cli"),
                  "b": Backend("b", base_url=f"http://127.0.0.1:{other.server_address[1]}")},
        roles={"classifier": Role("classifier", "local"), "r": Role("r", "remote"), "c": Role("c", "cli"), "b": Role("b", "b")},
        failover={"coding": ("r", "c", "b")}, engagement_bias="task", engagement_level=3))
    try:
        _, raw = w.post("/v1/chat/completions", chat_body("write a function and tests"))
        events = w.events()
    finally:
        w.close()
        other.shutdown()
    assert json.loads(raw)["choices"][0]["message"]["content"] == "Hi"
    assert [len(w.fake.chats), len(other.chats)] == [1, 2]  # shared endpoint: the classifier only; b: the 429'd try and the retry
    assert slept and [e["kind"] for e in events if e["kind"] in ("routing.backend_skipped", "route.skip", "upstream.retry")] == [
        "routing.backend_skipped", "route.skip", "route.skip", "upstream.retry"]


def test_a_server_reported_context_overflow_is_re_fitted_once_and_the_smaller_body_is_answered_and_captured(tmp_path):
    """The server says 60,000 tokens > its 49,152 window: cria re-prepares ONCE with the measured density (older whole turns folded into a labelled note, the latest user turn kept),
    the smaller body is answered, and both attempts are on disk as numbered captures (the rejected one with its own 400)."""
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i} " + "x" * 4000} for i in range(14)]
    w = Wire(tmp_path, capture=True)
    w.fake.flaky = [(400, {"error": {"n_prompt_tokens": 60000, "n_ctx": 49152, "type": "exceed_context_size_error"}})]
    try:
        _, raw = w.post("/v1/chat/completions", chat_body("latest question") | {"messages": history + [{"role": "user", "content": "latest question"}]})
    finally:
        w.close()
    (_, first), (_, second) = w.fake.chats
    assert json.loads(raw)["choices"][0]["message"]["content"] == "Hi" and len(second["messages"]) < len(first["messages"])
    assert second["messages"][-1]["content"] == "latest question" and "earlier turn(s) were compacted to fit the context window" in second["messages"][0]["content"]
    assert [e["real"] for e in w.events() if e["kind"] == "context.refit"] == [60000]
    assert sorted(p.name for p in (tmp_path / "calls" / "sid-1").glob("000?-proxy.json")) == ["0001-proxy.json", "0002-proxy.json"]


@pytest.mark.parametrize("mode,marker,client_status,upstream_status,tail", [
    ("chat-stream", "hello", 200, b"200 OK", b'"completion_tokens":2}}\n\ndata: [DONE]\n\n'),
    ("chat-buffered", "__500__", 502, b"500 Internal Server Error", b'{"error": {"message": "template rejected"}}'),
    ("chat-stream", "__500__", 200, b"500 Internal Server Error", b'{"error": {"message": "template rejected"}}'),
    ("chat-buffered", "__DROP__", 500, b"200 OK", b'{"choices": [{"mess')])  # the connection dies mid-body
def test_call_capture_keeps_exactly_the_bytes_the_wire_delivered_for_a_stream_a_rejection_and_a_cut_connection(tmp_path, mode, marker, client_status, upstream_status, tail):
    """The capture is custody of what the socket returned: the status line, headers and body as received (a stream's SSE frames, a 500's own error JSON, a body cut at 19 of 500
    promised bytes), with metadata that finished, closed and accounts for every returned byte. The client still gets a clean error status (a cut body is a 500 today, not a 502)."""
    w = Wire(tmp_path, capture=True)
    try:
        try:
            status = w.post(*request(mode, marker))[0]
        except urllib.error.HTTPError as e:
            status = e.code
    finally:
        w.close()
    folder = tmp_path / "calls" / "sid-1"
    raw = (folder / "0001-proxy.json.receive-0001-origin.bin").read_bytes()
    meta = json.loads((folder / "0001-proxy.json.receive.json").read_text())
    (seg,) = meta["segments"]
    assert status == client_status and raw.startswith(b"HTTP/1.0 " + upstream_status + b"\r\n") and raw.endswith(tail)
    assert meta["finished"] and seg["closed"] and seg["returned_bytes"] == seg["successful_write_bytes"] == len(raw) and meta["failed"] == []


def test_a_roles_portability_knobs_shape_the_request_the_served_model_receives(tmp_path):
    """A Nemotron/R1-style coder role (reasoning switch as a system line, no system slot, strict alternation, own sampling): over real HTTP the fake server gets ONE leading user
    turn carrying the switch line then the user's words (the harness persona is dropped by cria at this level), adjacent user turns merged, the role's sampling."""
    role = Role("coder", "local", think_protocol="system_directive", reasoning="off", collapse_system_prompt=True,
                merge_consecutive_turns=True, temperature=0.2)
    w = Wire(tmp_path, lambda url: RoutingConfig(backends={"local": Backend("local")}, roles={"classifier": Role("classifier", "local"), "coder": role},
                                                 failover={"coding": ("coder",)}, engagement_bias="task", engagement_level=3))
    try:
        w.post("/v1/chat/completions", {"model": "m", "messages": [{"role": "system", "content": "SYSTEM RULES"}, {"role": "user", "content": "write a function"},
                                                                       {"role": "user", "content": "and tests"}]})
    finally:
        w.close()
    sent = w.fake.chats[-1][1]
    assert sent["temperature"] == 0.2 and [m["role"] for m in sent["messages"]] == ["user"]
    assert sent["messages"][0]["content"].startswith("detailed thinking off") and sent["messages"][0]["content"].endswith("write a function\n\nand tests")
