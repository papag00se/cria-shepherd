"""Chain failover through the real server: a call that FAILS moves to the next resolvable role of its chain.

Real HTTP end to end (client -> CriaServer -> fake model servers). Only the model servers are fakes: one for the
coder role (the one that fails), one for the reasoner role (the standby), one shared endpoint for the classifier.
Every row asserts what the second server actually RECEIVED (its own model id, a body fitted to its own window),
what the client got back, and the structured event. Incident: chain failover was documented (heuristic-assists,
indicators, cria.example.toml) and never wired; `Router.route_chain` / `failover.run` had no production caller.
"""
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cria import callcapture, rumination
from cria.config import Backend, Config, IndicatorsConfig, LoggingConfig, Role, RoutingConfig, ServerConfig, UpstreamConfig
from cria.events import EventLog
from cria.server import CriaServer
from cria.upstream import Upstream

OPEN = urllib.request.build_opener().open
CLASSIFY = '{"engagement": "task", "task_type": "coding", "reason": "x"}'


class Model(ThreadingHTTPServer):
    """One fake llama.cpp: its own model id and window, and a script of behaviours for its next generations."""
    daemon_threads = True

    def __init__(self, model, window=49152, script=()):
        class H(BaseHTTPRequestHandler):
            log_message = lambda *a: None  # noqa: E731

            def reply(h, payload, code=200, ctype="application/json", headers=()):
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                h.send_response(code)
                h.send_header("Content-Type", ctype)
                for name, value in headers:
                    h.send_header(name, value)
                h.send_header("Content-Length", str(len(raw)))
                h.end_headers()
                h.wfile.write(raw)

            def do_GET(h):
                if h.path.endswith("/v1/models"):
                    return h.reply({"data": [{"id": self.model}]})
                if h.path.endswith("/props"):
                    return h.reply({"default_generation_settings": {"n_ctx": self.window}})
                h.reply({}, 404)

            def do_POST(h):
                body = json.loads(h.rfile.read(int(h.headers.get("Content-Length") or 0)) or b"{}")
                if h.path.endswith("/tokenize"):
                    return h.reply({"tokens": [1] * (len(body["content"]) // 3)})
                if h.path.endswith("/apply-template"):
                    return h.reply({"prompt": json.dumps(body["messages"])})
                text = json.dumps(body["messages"])
                if "REQUEST CLASSIFIER" in text:
                    return h.reply({"choices": [{"message": {"content": CLASSIFY}}]})
                self.chats.append(body)
                step = self.script.pop(0) if self.script else "ok"
                self.serve(h, body, step)

        super().__init__(("127.0.0.1", 0), H)
        self.model, self.window, self.script, self.chats = model, window, list(script), []
        threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_address[1]}"

    def serve(self, h, body, step):
        text = f"answer from {self.model}"
        if step == "503":
            return h.reply({"error": {"message": "loading model"}}, 503)
        if step.startswith("429:"):    # rate limited, the server stating how long to wait (seconds)
            return h.reply({"error": {"message": "slow down"}}, 429, headers=[("Retry-After", step[4:])])
        if step == "400":
            return h.reply({"error": {"message": "template rejected the request"}}, 400)
        if step == "overflow":
            return h.reply({"error": {"message": "too big", "n_prompt_tokens": 99999, "n_ctx": self.window}}, 400)
        if step == "protocol":   # the server says the model's output was malformed: a QUALITY fact, not transport
            return h.reply({"error": {"type": "invalid_model_output_error", "message": "malformed tool call"}}, 500)
        if step == "nonjson":
            return h.reply(b"<html>bad gateway</html>", ctype="text/html")
        if step == "hang":
            time.sleep(3)
            try:
                return h.reply({"choices": [{"message": {"role": "assistant", "content": "too late"}}]})
            except OSError:   # the client gave up long ago
                return None
        if body.get("stream"):
            h.close_connection = True
            h.send_response(200)
            h.send_header("Content-Type", "text/event-stream")
            h.end_headers()
            if step == "silent-close":      # headers, then the connection dies before any frame
                return
            h.wfile.write(b'data: {"choices":[{"delta":{"content":"first "}}]}\n\n')
            h.wfile.flush()
            if step == "die-after-first":   # a frame reached the harness; then the server dies
                return
            h.wfile.write(b'data: {"choices":[{"delta":{"content":"' + text.encode() + b'"}}]}\n\n'
                          b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"completion_tokens":2}}\n\n'
                          b"data: [DONE]\n\n")
            return
        h.reply({"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                 "usage": {"completion_tokens": 2}, "model": self.model})


def dead_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


class Rig:
    """cria in front of: a shared endpoint (classifier), a coder endpoint, a reasoner endpoint."""

    def __init__(self, tmp, coder, reasoner, *, coding=("coder", "reasoner"), level=3, timeout=600, extra_roles=None,
                 lanes=None, classifier_backend="local"):
        self.shared = Model("shared")
        self.coder, self.reasoner = coder, reasoner
        curl = coder.url if isinstance(coder, Model) else coder
        rurl = reasoner.url if isinstance(reasoner, Model) else reasoner
        routing = RoutingConfig(
            backends={"local": Backend("local"), "a": Backend("a", base_url=curl), "b": Backend("b", base_url=rurl)},
            roles={"classifier": Role("classifier", classifier_backend), "coder": Role("coder", "a"), "reasoner": Role("reasoner", "b"),
                   **(extra_roles or {})},
            failover={"coding": coding, "reasoning": ("reasoner",), **(lanes or {})}, engagement_bias="task", engagement_level=level)
        cfg = Config(server=ServerConfig(host="127.0.0.1", port=0, heartbeat_seconds=5.0),
                     upstream=UpstreamConfig(base_url=self.shared.url, timeout_seconds=timeout),
                     logging=LoggingConfig(dir=str(tmp), capture_dir=str(tmp / "calls"), console=False, capture_calls=False),
                     indicators=IndicatorsConfig(enabled=True), routing=routing)
        self.log = EventLog(dir=str(tmp), console=False)
        self.cria = CriaServer(cfg, self.log, Upstream(self.shared.url, timeout, context_window=49152, engagement_level=level))
        threading.Thread(target=self.cria.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def post(self, mode, text="write a function that adds two numbers", **kw):
        chat = mode.startswith("chat")
        stream = mode.endswith("stream")
        if chat:
            path, body = "/v1/chat/completions", {"model": "m", "stream": stream,
                                                  "messages": kw.pop("messages", [{"role": "user", "content": text}]), **kw}
        else:
            path, body = "/v1/responses", {"model": "m", "stream": stream, "prompt_cache_key": "sid-1", **kw,
                                           "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}]}
        req = urllib.request.Request(f"http://127.0.0.1:{self.cria.server_address[1]}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Cria-Session-Id": "sid-1"})
        try:
            with OPEN(req, timeout=60) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def events(self, kind=None):
        evs = [json.loads(line) for line in open(self.log.path) if line.strip()]
        return [e for e in evs if kind is None or e["kind"] == kind]

    def close(self):
        servers = [self.cria, self.shared] + [s for s in (self.coder, self.reasoner) if isinstance(s, Model)]
        for s in servers:
            s.shutdown()
            s.server_close()
        self.log.close()


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(urllib.request, "_opener", None)
    monkeypatch.setattr(callcapture, "_seq", {})
    monkeypatch.setattr(rumination, "WIRE_SILENCE_SECONDS", 1.0)  # a silent stream is dead after one second here


@pytest.fixture
def rig(tmp_path):
    made = []

    def build(coder, reasoner, **kw):
        r = Rig(tmp_path, coder, reasoner, **kw)
        made.append(r)
        return r
    yield build
    for r in made:
        r.close()


def text_of(mode, raw):
    if mode == "chat-buffered":
        return json.loads(raw)["choices"][0]["message"]["content"]
    frames = [json.loads(line[5:]) for line in raw.splitlines() if line.startswith("data:") and "[DONE]" not in line]
    if mode == "chat-stream":
        return "".join(e["choices"][0]["delta"].get("content", "") for e in frames if e.get("choices"))
    if mode == "responses-buffered":
        return json.loads(raw)["output"][0]["content"][0]["text"]
    return [e["text"] for e in frames if e.get("type") == "response.output_text.done"][-1]


MODES = ["chat-buffered", "chat-stream", "responses-buffered", "responses-stream"]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("fail", ["refused", "503"])
def test_a_failed_first_endpoint_walks_to_the_next_role_on_every_wire_mode(rig, mode, fail):
    """The coder endpoint refuses / 503s: the standby ANSWERS, with ITS model id, and the walk is a logged event."""
    standby = Model("model-b")
    first = dead_url() if fail == "refused" else Model("model-a", script=["503"] * 4)
    r = rig(first, standby)
    status, raw = r.post(mode)
    assert status == 200 and "answer from model-b" in text_of(mode, raw)
    assert [c["model"] for c in standby.chats] == ["model-b"]       # never the first server's name, never the client's "m"
    walks = r.events("failover.walk")
    assert len(walks) == 1 and walks[0]["from"] == "coder" and walks[0]["to"] == "reasoner"
    assert walks[0]["failure"] == "unavailable" and walks[0]["chain"] == "coding" and walks[0]["to_window"] == 49152
    if mode.startswith("chat"):                                    # the indicator line the docs describe (the Responses adapter renders its own status line)
        shown = text_of(mode, raw)
        assert "failover: coder → reasoner" in shown
        assert "⟦cria⟧ reasoner · model-b" in shown and "coder · model-a" not in shown   # the banner names who ANSWERED, not who was asked


def test_a_healthy_first_endpoint_never_walks_and_the_standby_is_never_called(rig):
    first, standby = Model("model-a"), Model("model-b")
    r = rig(first, standby)
    status, raw = r.post("chat-buffered")
    assert status == 200 and "answer from model-a" in raw and standby.chats == []
    assert r.events("failover.walk") == [] and "failover" not in raw


def test_a_timeout_retries_the_same_endpoint_once_then_walks(rig):
    first, standby = Model("model-a", script=["hang"] * 4), Model("model-b")
    r = rig(first, standby, timeout=1)
    status, raw = r.post("chat-buffered")
    assert status == 200 and "answer from model-b" in raw
    assert len(first.chats) == 2                                    # the transport's own retry-same-once, NOT doubled by the walker
    assert [w["failure"] for w in r.events("failover.walk")] == ["timeout"]


@pytest.mark.parametrize("step", ["400", "overflow", "nonjson", "protocol"])
def test_requests_the_endpoint_refused_or_answered_badly_are_not_transport_failures_and_do_not_walk(rig, step):
    """400 = the request's own fault (identical elsewhere), a context overflow belongs to the refit path, and a 200 that
    is not a completion is a QUALITY matter: none of them is a reason to run the same request somewhere else."""
    first, standby = Model("model-a", script=[step] * 6), Model("model-b")
    r = rig(first, standby)
    status, raw = r.post("chat-buffered")
    assert standby.chats == [] and r.events("failover.walk") == [] and "answer from model-b" not in raw
    assert status != 200 or "context" in raw.lower() or "window" in raw.lower()


@pytest.mark.parametrize("mode", ["chat-stream", "responses-stream"])
def test_a_stream_is_walked_only_before_its_first_frame(rig, mode):
    """Once a frame reached the harness the stream belongs to it: a later death is the ordinary truthful failure."""
    first, standby = Model("model-a", script=["die-after-first"] * 3), Model("model-b")
    r = rig(first, standby)
    status, raw = r.post(mode)
    assert status == 200 and standby.chats == [] and r.events("failover.walk") == []
    assert "answer from model-b" not in raw and "first " in text_of(mode, raw) or mode == "responses-stream"
    if mode == "responses-stream":   # the Responses adapter buffers from chat_watched, which owns an empty stream
        return
    # …and the dead-before-any-frame stream (headers, then nothing) DOES walk
    first2, standby2 = Model("model-a", script=["silent-close"] * 3), Model("model-b")
    r2 = rig(first2, standby2)
    status, raw = r2.post(mode)
    assert status == 200 and "answer from model-b" in text_of(mode, raw) and len(r2.events("failover.walk")) == 1


def test_the_standby_gets_a_body_fitted_to_its_own_smaller_window(rig):
    """A body fitted for 49,152 tokens is never sent to a 4,096-token standby: the target's own floor refits it,
    and the walk event names the window it refitted for."""
    standby = Model("model-b", window=4096)
    r = rig(dead_url(), standby)
    history = [{"role": "user", "content": "write a function that adds two numbers"}]
    for i in range(30):
        history += [{"role": "assistant", "content": None, "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": "shell", "arguments": json.dumps({"command": ["cat", f"f{i}.txt"]})}}]},
                    {"role": "tool", "tool_call_id": f"c{i}", "content": f"file {i}\n" + "alpha beta gamma delta " * 150}]
    history.append({"role": "user", "content": "write a function that adds two numbers"})
    status, raw = r.post("chat-buffered", messages=history)
    assert status == 200 and "answer from model-b" in raw
    sent = [c for c in standby.chats if "REQUEST" not in json.dumps(c["messages"])[:300] and len(c["messages"]) > 2][-1]
    assert len(json.dumps(sent["messages"])) // 3 < 4096 and len(sent["messages"]) < len(history)
    assert any(m.get("content") == "write a function that adds two numbers" for m in sent["messages"])
    walk = r.events("failover.walk")[0]
    assert walk["to_window"] == 4096 and "re-fitted" in walk["refit"]


@pytest.mark.parametrize("mode", ["chat-buffered", "chat-stream"])
def test_an_exhausted_chain_is_a_truthful_failure_never_a_silent_success(rig, mode):
    r = rig(dead_url(), dead_url())
    status, raw = r.post(mode)
    assert (status != 200 or "error" in raw.lower()) and "answer from" not in raw
    assert len(r.events("failover.walk")) == 1
    gone = r.events("failover.exhausted")
    assert len(gone) == 1 and gone[0]["tried"] == ["coder", "reasoner"] and gone[0]["chain"] == "coding"


def test_two_roles_on_one_server_are_not_a_chain(rig):
    """A walk to the same endpoint cannot change a refused connection, so such a chain is the plain provider."""
    shared = Model("model-a")
    r = rig(shared, shared)
    assert type(r.cria._endpoint_for("coder")).__name__ == "Upstream"
    status, raw = r.post("chat-buffered")
    assert status == 200 and r.events("failover.walk") == []


def test_the_loops_own_role_calls_walk_their_lane_chain(rig):
    """coder_chat (watched), a buffered coder call and the classifier go through Router.endpoint_for: each walks the chain
    named for its job; a lane with nothing else to walk to is the plain provider."""
    standby = Model("model-b")
    r = rig(dead_url(), standby, lanes={"classification": ("classifier", "reasoner")}, classifier_backend="a")
    log = r.cria.log.bind(session="s", turn="t")
    body = {"model": "x", "messages": [{"role": "user", "content": "hello"}]}
    coder = r.cria._endpoint_for("coder")
    assert json.loads(coder.chat_watched(dict(body), log))["choices"][0]["message"]["content"].endswith("answer from model-b")
    assert json.loads(coder.chat(dict(body), log))["choices"][0]["message"]["content"].endswith("answer from model-b")
    assert [c["model"] for c in standby.chats] == ["model-b", "model-b"]
    assert type(r.cria._endpoint_for("reasoner")).__name__ == "Upstream"          # reasoning = [reasoner]: nothing to walk to
    status, _ = r.post("chat-buffered")                                            # the classifier's own endpoint is dead too
    assert status == 200
    assert {w["chain"] for w in r.events("failover.walk")} == {"coding", "classification"}


def test_a_watched_call_whose_text_already_left_for_the_harness_is_not_walked(rig):
    first, standby = Model("model-a", script=["die-after-first"]), Model("model-b")
    r = rig(first, standby)
    seen = []
    with pytest.raises(Exception):
        r.cria._endpoint_for("coder").chat_watched({"model": "x", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
                                                   r.cria.log.bind(session="s", turn="t"), on_content=seen.append)
    assert seen and standby.chats == [] and r.events("failover.walk") == []


def test_a_rate_limited_endpoint_is_retried_only_after_the_wait_it_advertised(rig, monkeypatch):
    """Retry-After: 3 is the server's own number: the retry waits 3 s (it used to wait a made-up 1 s and hit the limiter again)."""
    waits = []
    monkeypatch.setattr(time, "sleep", waits.append)
    first, standby = Model("model-a", script=["429:3"]), Model("model-b")
    r = rig(first, standby)
    status, raw = r.post("chat-buffered")
    assert status == 200 and "answer from model-a" in raw and standby.chats == []
    assert waits.count(3.0) == 1 and 1.0 not in waits


@pytest.mark.parametrize("mode", ["chat-buffered", "chat-stream"])
def test_a_rate_limit_wait_longer_than_cria_will_hold_a_turn_walks_instead_of_retrying_early(rig, monkeypatch, mode):
    """Retry-After: 600 is beyond the 30 s cap: retrying at 30 s would be the early retry the limiter punishes. The next
    endpoint takes the request at once and the first endpoint is asked exactly once."""
    waits = []
    monkeypatch.setattr(time, "sleep", waits.append)
    first, standby = Model("model-a", script=["429:600"] * 4), Model("model-b")
    r = rig(first, standby)
    status, raw = r.post(mode)
    assert status == 200 and "answer from model-b" in text_of(mode, raw)
    assert len(first.chats) == 1 and not [w for w in waits if w >= 1.0]
    assert [w["failure"] for w in r.events("failover.walk")] == ["rate_limit"]
