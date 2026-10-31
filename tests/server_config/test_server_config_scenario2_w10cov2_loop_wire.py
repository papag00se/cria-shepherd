"""Scenario2 (w10 COV2): the real CriaServer at level 4 with the Loop ENGAGED, over real HTTP on all four wire modes.

The proxy-only Wire never reaches ``loop.drive``; here a coder role plus a 'coding' classification starts the driver, so the
loop's completions are framed for chat and Responses, buffered and streamed, and a loop that raises, a coder that 500s, or a
harness that hangs up mid-turn must each leave a terminal answer, no registered stream, and a session the NEXT turn can drive."""
import json
import socket
import time
from unittest import mock

import pytest

import test_server_config_http as H
from cria import server as server_mod
from cria.config import Backend, Role, RoutingConfig
from cria.probegate import GATE_SENTINEL
from test_server_config_http import MODES, Wire, no_installed_opener, request, sse_events  # noqa: F401

FN = {"write_file": {"path": {"type": "string"}, "content": {"type": "string"}}, "shell": {"command": {"type": "array"}}}


def driver_routing(url):
    return RoutingConfig(backends={"local": Backend("local")}, engagement_bias="task", engagement_level=4,
                         roles={"classifier": Role("classifier", "local"), "coder": Role("coder", "local")}, failover={"coding": ("coder",)})


def tooled(mode, text):
    path, body = request(mode, text)
    chat = mode.startswith("chat")
    spec = lambda n, p: {"type": "function", "function": {"name": n, "parameters": {"type": "object", "properties": p}}}  # noqa: E731
    body["tools"] = [spec(n, p) if chat else {**spec(n, p)["function"], "type": "function"} for n, p in FN.items()]
    return path, body


def harness_calls(mode, raw):
    """(name, arguments) of every call the harness is asked to run, read from the mode's own framing."""
    if mode == "chat-buffered":
        return [(c["function"]["name"], c["function"]["arguments"]) for c in json.loads(raw)["choices"][0]["message"].get("tool_calls") or []]
    if mode == "chat-stream":
        out = {}
        for e in sse_events(raw):
            for c in (e["choices"][0]["delta"].get("tool_calls") or []) if e.get("choices") else []:
                name, args = out.get(c["index"], ("", ""))
                out[c["index"]] = (name + c.get("function", {}).get("name", ""), args + c.get("function", {}).get("arguments", ""))
        return list(out.values())
    items = json.loads(raw)["output"] if mode == "responses-buffered" else next(
        e["response"]["output"] for e in sse_events(raw) if e.get("type") == "response.completed")
    return [(i["name"], i["arguments"]) for i in items if i["type"] == "function_call"]


@pytest.fixture
def loop_wire(tmp_path):
    w = Wire(tmp_path, routing=driver_routing, heartbeat=0.05, indicators=True)
    yield w
    w.fake.release.set()
    w.close()


@pytest.mark.parametrize("mode", MODES)
def test_the_loop_drives_each_wire_mode_and_a_done_claim_is_answered_by_the_repos_check_not_forwarded_as_the_end(loop_wire, mode):
    """Turn 1: the coder's write_file call reaches the harness in the mode's own framing. Turn 2 (same session): the coder just
    SAYS it is done; the harness is handed cria's check probe instead of a closing text, the route banner names the coder, and usage is reported."""
    status, raw = loop_wire.post(*tooled(mode, "__TOOL__ write hello.txt"))
    [(name, args)] = harness_calls(mode, raw)
    assert status == 200 and name == "write_file" and json.loads(args) == {"path": "hello.txt", "content": "hi there\n"}
    status, raw = loop_wire.post(*tooled(mode, "carry on"))
    [(name, args)] = harness_calls(mode, raw)
    assert name == "shell" and GATE_SENTINEL in " ".join(json.loads(args)["command"]) and "Hello" not in raw
    kinds = [e["kind"] for e in loop_wire.events()]
    assert kinds.count("loop.start") == 1 and "loop.completion_probe" in kinds and kinds.count("response.sent") == 2
    if mode == "responses-stream":
        assert "coder · loaded" in raw                      # the loop path carries no indicator: the banner names the coder on the loaded model


def send(w, mode, text):
    """POST without raising on a non-2xx: (status, body)."""
    import urllib.error
    try:
        return w.post(*tooled(mode, text))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


@pytest.mark.parametrize("mode", MODES)
def test_a_loop_that_raises_ends_the_turn_with_a_terminal_answer_leaves_nothing_registered_and_the_next_turn_still_drives(loop_wire, mode):
    """The g4 hole at the wire: whatever the loop dies of, the harness gets a failure it can show (HTTP 500, an in-stream error then [DONE], or a
    terminal response.failed) and the crash is in cria's log; the server keeps no stream and the session's next request is driven normally."""
    with mock.patch.object(loop_wire.cria.loop, "drive", side_effect=RuntimeError("loop exploded")):
        status, raw = send(loop_wire, mode, "__TOOL__ write hello.txt")
    assert "cria internal error: loop exploded" in raw
    assert status == (500 if mode.endswith("buffered") else 200)
    if mode == "chat-stream":
        assert raw.rstrip().endswith("data: [DONE]")
    if mode == "responses-stream":
        last = sse_events(raw)[-1]
        assert last["type"] == "response.failed" and last["response"]["status"] == "failed"
        assert "response.completed" not in raw
    errors = [e for e in loop_wire.events() if e["kind"] == "response.error"]
    assert len(errors) == 1 and "loop exploded" in errors[0]["error"] and loop_wire.cria.active_streams == {}
    status, raw = send(loop_wire, mode, "__TOOL__ write hello.txt")
    assert status == 200 and [n for n, _ in harness_calls(mode, raw)] == ["write_file"]


@pytest.mark.parametrize("mode", MODES)
def test_a_coder_the_model_server_rejects_is_a_clean_error_and_does_not_wedge_the_session_for_the_next_turn(loop_wire, mode):
    """The REAL loop over a coder call the model server answers with a 500: the failure comes out in the mode's framing, and the session
    (whose lock the failed drive held) is driven again by the very next request."""
    status, raw = send(loop_wire, mode, "__500__ write hello.txt")
    assert ("template rejected" if mode.startswith("responses") else "HTTP Error 500") in raw and (status >= 500 if mode.endswith("buffered") else status == 200)
    assert ("response.failed" in raw) == (mode == "responses-stream") and [e["kind"] for e in loop_wire.events()].count("loop.start") == 1
    status, raw = send(loop_wire, mode, "__TOOL__ write hello.txt")
    assert status == 200 and [n for n, _ in harness_calls(mode, raw)] == ["write_file"]
    assert loop_wire.cria.active_streams == {}


@pytest.mark.parametrize("mode", ["chat-stream", "responses-stream"])
def test_a_harness_that_hangs_up_while_the_loop_works_is_logged_and_the_session_is_driven_again_after(loop_wire, mode):
    """The harness resets the connection while the coder call is held; the handler records response.client_gone, drops the stream
    registration, and (the lock released with it) the same session answers its next request instead of hanging."""
    path, body = tooled(mode, "__SLOW__ __TOOL__ write hello.txt")
    data = json.dumps(body).encode()
    s = socket.create_connection(("127.0.0.1", loop_wire.cria.server_address[1]), timeout=10)
    s.sendall(b"POST " + path.encode() + b" HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nX-Cria-Session-Id: sid-1\r\nContent-Length: "
              + str(len(data)).encode() + b"\r\n\r\n" + data)
    seen = b""
    while b"response.in_progress" not in seen and b": cria" not in seen:
        seen += s.recv(4096)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")  # RST, not FIN
    s.close()
    loop_wire.fake.release.set()
    for _ in range(200):
        if any(e["kind"] == "response.client_gone" for e in loop_wire.events()) and not loop_wire.cria.active_streams:
            break
        time.sleep(0.05)
    assert any(e["kind"] == "response.client_gone" and e["level"] == "warn" for e in loop_wire.events()) and loop_wire.cria.active_streams == {}
    status, raw = send(loop_wire, mode, "__TOOL__ write hello.txt")
    assert status == 200 and [n for n, _ in harness_calls(mode, raw)] == ["write_file"]


def test_a_long_model_call_shows_the_live_ticker_in_the_status_item_and_the_closed_item_keeps_it(tmp_path, monkeypatch):
    """With the status ticker on, a held prefill makes the beat thread stream a 'still working' line into the open status item, and the
    item closed at the end holds it (the operator saw nothing for the first minutes before this)."""
    class Quick(server_mod.Heartbeat):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._beat_status_every = 0.0
    monkeypatch.setattr(server_mod, "Heartbeat", Quick)
    w = Wire(tmp_path, heartbeat=0.05, indicators=True)
    try:
        import threading
        threading.Timer(0.6, w.fake.release.set).start()
        status, raw = w.post(*request("responses-stream", "__SLOW__"))
    finally:
        w.fake.release.set()
        w.close()
    events = sse_events(raw)
    deltas = [e["delta"] for e in events if e.get("type") == "response.output_text.delta"]
    assert any("⋯ still working" in d for d in deltas)
    closed = next(e["item"] for e in events if e.get("type") == "response.output_item.done" and e["output_index"] == 0)
    assert "⋯ still working" in closed["content"][0]["text"] and events[-1]["type"] == "response.completed"


def test_a_reply_cut_at_the_token_limit_says_so_to_the_human_and_in_the_log(tmp_path, monkeypatch):
    """A proxied completion that ended on finish_reason=length reaches the harness with the visible truncation warning (buffered chat), not as a clean answer."""
    import io

    class Cut(H.FakeUpstream):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.rfile = io.BytesIO(raw)
            if b"__LENGTH__" in raw and b"REQUEST CLASSIFIER" not in raw:
                return self._reply({"choices": [{"message": {"role": "assistant", "content": "def f():\n    retur"}, "finish_reason": "length"}]})
            super().do_POST()
    monkeypatch.setattr(H, "FakeUpstream", Cut)
    w = Wire(tmp_path, indicators=True)
    try:
        status, raw = w.post(*request("chat-buffered", "__LENGTH__ write f"))
    finally:
        w.close()
    text = json.loads(raw)["choices"][0]["message"]["content"]
    assert status == 200 and "⚠ output truncated at the token limit" in text and "def f():\n    retur" in text
    assert [e["kind"] for e in w.events()].count("response.truncated") == 1
