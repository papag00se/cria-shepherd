"""Real HTTP through CriaServer in front of a fake upstream: one handler path per wire mode."""
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cria import callcapture
from cria.config import (Backend, Config, IndicatorsConfig, LoggingConfig, Role, RoutingConfig,
                         ServerConfig, UpstreamConfig)
from cria.events import EventLog
from cria.indicators import MARKER, PROSE_DROPPED_MARKER
from cria.server import CriaServer
from cria.upstream import Upstream

OPEN = urllib.request.build_opener().open  # never urlopen: it installs a global opener the capture transport refuses
WINDOW = 49152
SSE = (b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
       b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
       b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
       b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"completion_tokens":2}}\n\n'
       b"data: [DONE]\n\n")
BIG = " ".join("w%05d" % i for i in range(30000))  # ~70k tokens on the fake chars/3 tokenizer


COMPACTION_JUDGES = {"Decide PLAN only from": "RETROSPECTIVE", "Answer NARROWS if": "PRESERVES",
                     "what role does the briefing give that file": "app.py | EXISTS", "ALREADY created": "app.py | NOT CHANGED",
                     "which state of the code": "none", "what size does the briefing give": "none"}


class FakeUpstream(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, payload, ctype="application/json", code=200):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.endswith("/v1/models"):
            return self._reply({"data": [{"id": "loaded"}]})
        if self.path.endswith("/props"):
            return self._reply({"default_generation_settings": {"n_ctx": WINDOW}})
        self._reply({}, code=404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path.endswith("/tokenize"):
            return self._reply({"tokens": [1] * (len(body["content"]) // 3)})
        if self.path.endswith("/apply-template"):
            return self._reply({"prompt": json.dumps(body["messages"])})
        self.server.chats.append((dict(self.headers), body))
        text = json.dumps(body["messages"])
        if body.get('tool_choice') == 'required' and any(t.get('function', {}).get('name') == 'verdict' for t in body.get('tools', [])):
            decision = 'RELEVANT' if 'candidate: seed.py |' in text else 'UNRELATED'
            call = {'id': 'decision', 'type': 'function', 'function': {'name': 'verdict', 'arguments': json.dumps({'decision': decision})}}
            return self._reply({'choices': [{'message': {'role': 'assistant', 'tool_calls': [call]}, 'finish_reason': 'tool_calls'}]})
        if "__SLOW__" in text:  # a long prefill: hold the reply until the test saw a heartbeat
            self.server.release.wait(10)
        if "REQUEST CLASSIFIER" in text:
            return self._reply({"choices": [{"message": {"content": '{"engagement": "task", "task_type": "coding", "reason": "x"}'}}]})
        if "__NONJSON__" in text:  # an intermediary's HTML error page served as 200
            return self._reply(b"<html>502 Bad Gateway</html>", "text/html")
        system = body["messages"][0].get("content") if body.get("messages") else ""
        for lens, verdict in COMPACTION_JUDGES.items():  # the briefing validators, each answering its own lens
            if isinstance(system, str) and lens in system:
                verdict = "PLAN" if verdict == "RETROSPECTIVE" and "Next step" in text else verdict
                return self._reply({"choices": [{"message": {"content": verdict}}]})
        if "You are writing a briefing" in text:  # the compactor
            plan = "Next step: rewrite app.py with argparse." if "__PLAN__" in text else "no check has failed."
            return self._reply({"choices": [{"message": {"role": "assistant", "content": "The user asked for app.py. app.py now exists and prints 1; " + plan}}]})
        if "REQUEST CLASSIFIER" not in text and self.server.__dict__.get("flaky"):  # a server that rejects its next N generations
            code = self.server.flaky.pop(0)
            return self._reply(code[1] if isinstance(code, tuple) else {"error": {"message": "overloaded"}}, code=code[0] if isinstance(code, tuple) else code)
        if "__DROP__" in text:  # the connection dies halfway through the body
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "500")
            self.end_headers()
            self.wfile.write(b'{"choices": [{"mess')
            self.close_connection = True
            return
        if "__500__" in text:
            return self._reply({"error": {"message": "template rejected"}}, code=500)
        if "__TOOL__" in text or "__EDIT__" in text or "Make these four changes to the orders service:" in text:  # the model asks to write (or edit) a file, as a buffered completion or as streamed argument deltas
            name, args = (("write_file", {"path": "hello.txt", "content": "hi there\n"}) if "__TOOL__" in text or "Make these four changes to the orders service:" in text else
                          ("edit_file", {"path": "hello.txt", "old_string": "hi", "new_string": "bye"}))
            call = {"id": "call_1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            if not body.get("stream"):
                return self._reply({"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}, "finish_reason": "tool_calls"}]})
            args = call["function"]["arguments"]
            tc = lambda **f: {"choices": [{"delta": {"tool_calls": [{"index": 0, **f}]}}]}
            frames = [tc(id="call_1", type="function", function={"name": name, "arguments": args[:20]}), tc(function={"arguments": args[20:]}),
                      {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}]
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            return self.wfile.write(b"".join(b"data: " + json.dumps(f).encode() + b"\n\n" for f in frames) + b"data: [DONE]\n\n")
        if body.get("stream"):
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            return self.wfile.write(SSE)
        self._reply({"choices": [{"message": {"role": "assistant", "content": "Hi"}}],
                     "usage": {"completion_tokens": 1}})


class Wire:
    def __init__(self, tmp, routing=None, heartbeat=5.0, capture=False, indicators=False, assists=None):
        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
        self.fake.chats, self.fake.release = [], threading.Event()
        threading.Thread(target=self.fake.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.fake.server_address[1]}"
        cfg = Config(server=ServerConfig(host="127.0.0.1", port=0, heartbeat_seconds=heartbeat), upstream=UpstreamConfig(base_url=self.url),
                     logging=LoggingConfig(dir=str(tmp), capture_dir=str(tmp / "calls"), console=False,
                                          capture_calls=True),
                     indicators=IndicatorsConfig(enabled=indicators), **({"assists": assists} if assists else {}),
                     routing=routing(self.url) if routing else RoutingConfig(engagement_level=3))
        self.log = EventLog(dir=str(tmp), console=False)
        # The upstream carries the SAME rung as the server (as __main__ builds it): a level-0 wire test must run the wire's level-0 gates.
        up = Upstream(self.url, context_window=WINDOW, engagement_level=cfg.routing.engagement_level,
                      **({"capture_dir": tmp / "calls"} if capture else {}))
        self.cria = CriaServer(cfg, self.log, up)
        threading.Thread(target=self.cria.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def post(self, path, body, sid="sid-1"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.cria.server_address[1]}{path}",
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Cria-Session-Id": sid})
        with OPEN(req, timeout=20) as r:
            return r.status, r.read().decode()

    def events(self):
        return [json.loads(line) for line in open(self.log.path) if line.strip()]

    def close(self):
        for s in (self.cria, self.fake):
            s.shutdown()
            s.server_close()
        self.log.close()


@pytest.fixture(autouse=True)
def no_installed_opener(monkeypatch):
    """Capture mode refuses a process-global urllib opener; earlier tests' plain urlopen calls would install one."""
    monkeypatch.setattr(urllib.request, "_opener", None)
    monkeypatch.setattr(callcapture, "_seq", {})  # the capture counter is per-process, keyed by session only


@pytest.fixture
def wire(tmp_path):
    w = Wire(tmp_path)
    yield w
    w.close()


def chat_body(text="hi", stream=False, **kw):
    return {"model": "m", "stream": stream, "messages": [{"role": "user", "content": text}], **kw}


def resp_body(text="hi", stream=False, **kw):
    return {"model": "m", "stream": stream, "prompt_cache_key": "sid-1", **kw,
            "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}]}


def sse_events(raw):
    return [json.loads(line[5:]) for line in raw.splitlines() if line.startswith("data:") and "[DONE]" not in line]


def reply_text(mode, raw):
    """The assistant text a client of that wire mode reads back."""
    if mode == "chat-buffered":
        return json.loads(raw)["choices"][0]["message"]["content"]
    if mode == "chat-stream":
        return "".join(e["choices"][0]["delta"].get("content", "") for e in sse_events(raw) if e.get("choices"))
    if mode == "responses-buffered":
        return json.loads(raw)["output"][0]["content"][0]["text"]
    return next(e["text"] for e in sse_events(raw) if e.get("type") == "response.output_text.done")


@pytest.mark.parametrize("responses", [False, True])
def test_tool_descriptions_reach_model_through_real_http(wire, responses):
    shell = {"name": "exec_command", "description": "Native shell.", "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}
    stdin = {"name": "write_stdin", "description": "Native input.", "parameters": {"type": "object", "properties": {"session_id": {"type": "number", "description": "Identifier of the running unified exec session."}, "chars": {"type": "string", "description": "Bytes to write to stdin. Defaults to empty, which polls without writing."}}, "required": ["session_id"]}}
    create = {"name": "create_file", "description": "Create only; never overwrite.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}
    read = {"name": "read_file", "description": "Lines are zero-based and end-exclusive.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["path", "start_line", "end_line"]}}
    tools = [{"type": "function", **fn} if responses else {"type": "function", "function": fn} for fn in (shell, stdin, create, read)]
    path = "/v1/responses" if responses else "/v1/chat/completions"
    make = resp_body if responses else chat_body
    status, _ = wire.post(path, make(tools=tools))
    assert status == 200
    sent = wire.fake.chats[-1][1]
    menu = {t["function"]["name"]: t["function"] for t in sent["tools"]}
    assert menu["exec_command"]["description"] == "Native shell."
    assert menu["create_file"]["description"] == create["description"]
    assert menu["read_file"]["description"] == read["description"]
    assert menu["write_stdin"]["description"].startswith("Native input.")
    assert "leave chars empty" in menu["write_stdin"]["description"]
    assert "regular expression" in menu["grep"]["description"]
    assert "Args:" not in json.dumps(sent["messages"])


def test_responses_environment_reaches_coder_formatted_through_http(tmp_path):
    import subprocess
    root = tmp_path / 'work'
    root.mkdir()
    xml = f'<environment_context><cwd>{root}</cwd><filesystem><permission_profile type="managed"><file_system type="restricted"><entry access="read"><path>/</path></entry><entry access="write"><path>{root}</path></entry></file_system></permission_profile></filesystem></environment_context>'
    body = resp_body("Fix the project and add tests __TOOL__", tools=[{"type": "function", "name": "exec_command", "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}])
    body["input"].insert(0, {"type": "message", "role": "user", "content": [{"type": "input_text", "text": xml}]})
    w = Wire(tmp_path, routing=lambda url: RoutingConfig(
        backends={"local": Backend("local")},
        roles={"classifier": Role("classifier", "local"), "coder": Role("coder", "local")},
        failover={"coding": ("coder",)}, engagement_bias="task", engagement_level=5))
    try:
        while True:
            status, raw = w.post("/v1/responses", body)
            assert status == 200
            output = json.loads(raw)['output']
            calls = [item for item in output if item.get('type') == 'function_call']
            if not calls or '___CTX_GATE_' not in json.loads(calls[0]['arguments']).get('cmd', ''):
                break
            call = calls[0]
            result = subprocess.run(['bash', '-c', json.loads(call['arguments'])['cmd']], cwd=root,
                                    capture_output=True, text=True, check=True)
            body['input'].extend([call, {'type': 'function_call_output', 'call_id': call['call_id'], 'output': result.stdout}])
        messages = w.fake.chats[-1][1]["messages"]
        env = next(m["content"] for m in messages if isinstance(m.get("content"), str) and m["content"].startswith("# Environment context"))
        assert '`entry` `access="read"`:\n        - `path`: `"/"`' in env
        assert f'`entry` `access="write"`:\n        - `path`: `"{root}"`' in env
        assert any(m.get("content") == "Fix the project and add tests __TOOL__" for m in messages)
    finally:
        w.close()


MODES = ["chat-buffered", "chat-stream", "responses-buffered", "responses-stream"]


def request(mode, text="hi", **kw):
    path = "/v1/chat/completions" if mode.startswith("chat") else "/v1/responses"
    make = chat_body if mode.startswith("chat") else resp_body
    return path, make(text, stream=mode.endswith("stream"), **kw)


@pytest.mark.parametrize("mode,expected", [("chat-buffered", "Hi"), ("chat-stream", "Hello world"),
                                           ("responses-buffered", "Hi"), ("responses-stream", "Hello world")])
def test_each_wire_mode_returns_content_with_its_framing_and_logs_the_turn(wire, mode, expected):
    """Chat/Responses x buffered/stream each return the upstream text in their own framing (a query string still routes)."""
    path, body = request(mode)
    status, raw = wire.post(path + "?debug=1", body)
    assert status == 200 and reply_text(mode, raw) == expected
    if mode == "chat-stream":
        assert raw.rstrip().endswith("data: [DONE]")
    if mode == "responses-buffered":
        assert json.loads(raw)["status"] == "completed"
    if mode == "responses-stream":
        types = [e["type"] for e in sse_events(raw)]
        assert types[0] == "response.created" and types[-1] == "response.completed"
        assert types.index("response.output_text.delta") < types.index("response.completed")
    recv = [e for e in wire.events() if e["kind"] == "request.recv"]
    assert [e["session"] for e in recv] == ["sid-1"] and recv[0]["stream"] is mode.endswith("stream")


@pytest.mark.parametrize("stream", [False, True])
def test_a_failing_upstream_is_a_clean_error_never_a_fake_success(wire, stream):
    """An upstream 500 (and, buffered, a non-JSON 200 HTML page) becomes HTTP 502 / an in-stream error plus [DONE], never an empty completion."""
    if stream:
        raw = wire.post(*request("chat-stream", "__500__"))[1]
        assert "error" in raw.lower() and raw.rstrip().endswith("[DONE]") and "Hello" not in raw
        return
    for marker in ("__NONJSON__", "__500__"):
        with pytest.raises(urllib.error.HTTPError) as err:
            wire.post(*request("chat-buffered", marker))
        assert err.value.code == 502


@pytest.mark.parametrize("mode", MODES)
def test_a_final_input_larger_than_the_window_is_answered_not_a_502(wire, mode):
    """Measured on the real 49,152-token server: a ~60k-token last user message ended in a bare 502 that pinned Codex retried forever; it is now a 200 assistant message saying nothing was dropped."""
    status, raw = wire.post(*request(mode, "summarise:\n" + BIG))
    text = reply_text(mode, raw)
    assert status == 200 and wire.fake.chats == []  # nothing was sent upstream
    assert text.startswith("⟦ctx:input-not-delivered⟧") and f"{WINDOW:,}-token context window" in text
    assert "Nothing was cut, summarised or dropped" in text


def tool_result_request(mode, result, task="count the ERROR lines in logs/app.log", **kw):
    """The task, the model's own `cat` call, and what the harness returned for it, in that wire mode's shape."""
    path = "/v1/chat/completions" if mode.startswith("chat") else "/v1/responses"
    stream, call = mode.endswith("stream"), {"cmd": "cat logs/app.log"}
    if mode.startswith("chat"):
        return path, {"model": "m", "stream": stream, "messages": [
            {"role": "user", "content": task},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps(call)}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": result}], **kw}
    return path, {"model": "m", "stream": stream, "prompt_cache_key": "sid-1", **kw, "input": [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": task}]},
        {"type": "function_call", "call_id": "call_1", "name": "exec_command", "arguments": json.dumps(call)},
        {"type": "function_call_output", "call_id": "call_1", "output": result}]}


@pytest.mark.parametrize("mode", ["chat-buffered", "responses-buffered"])
def test_cria_status_banners_in_history_never_reach_the_model(wire, mode):
    """Codex echoed cria's own banner lines back inside a compaction thread; both wire modes strip them before the model reads."""
    wire.post(*request(mode, f"summarize the thread\n{MARKER}reasoner · m · 7 tok/s\nthe real summary"))
    sent = json.dumps(wire.fake.chats[-1][1]["messages"])
    assert "tok/s" not in sent and "the real summary" in sent
    assert "indicators.stripped" in [e["kind"] for e in wire.events()]


def test_a_keyed_backend_secret_is_sent_upstream_but_never_logged_or_captured(tmp_path, monkeypatch):
    """The provider key authorizes the remote call yet appears in no event log ."""
    monkeypatch.setenv("SERVER_CONFIG_KEY", "sk-live-SECRET-123")
    w = Wire(tmp_path, capture=True, routing=lambda url: RoutingConfig(
        backends={"local": Backend("local"), "remote": Backend("remote", base_url=url, api_key_env="SERVER_CONFIG_KEY", model="gpt-x")},
        roles={"classifier": Role("classifier", "local"), "coder": Role("coder", "remote")},
        failover={"coding": ("coder",)}, engagement_bias="task", engagement_level=3))
    try:
        w.post(*request("chat-buffered", "write a function and tests"))
    finally:
        w.close()
    # the classifier call rides the keyless shared endpoint; the coder call carries the key
    assert [h.get("Authorization") for h, _ in w.fake.chats] == [None, "Bearer sk-live-SECRET-123"]
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert any(p.suffix == ".jsonl" and p.stat().st_size for p in files) and any("calls" in p.parts for p in files)
    assert [p for p in files if b"SECRET-123" in p.read_bytes()] == []


def test_level_zero_forwards_tools_and_history_untouched_and_logs_only_transport(tmp_path):
    """Engagement level 0 is a pure proxy: no menu/context surgery (a campaign once ran a 'model on its own' arm with 1,011 menu edits).
    The caller's system message is forwarded as sent (it was silently dropped here until a Chat caller's system/developer text was
    carried like Responses `instructions`); a request with no system message ships exactly its history."""
    tools = [{"type": "function", "function": {"name": n, "parameters": {"type": "object"}}} for n in ("shell", "apply_patch")]
    history = [{"role": "user", "content": "do x"},
               {"role": "assistant", "content": None, "tool_calls": [
                   {"id": "c1", "type": "function", "function": {"name": "shell", "arguments": '{"command":["ls"]}'}}]},
               {"role": "tool", "tool_call_id": "c1", "content": "a\nb"}, {"role": "user", "content": "next"}]
    w = Wire(tmp_path, lambda url: RoutingConfig(engagement_level=0))
    try:
        w.post("/v1/chat/completions", chat_body(tools=tools) | {"messages": [{"role": "system", "content": "persona"}, *history]})
        w.post("/v1/chat/completions", chat_body(tools=tools) | {"messages": history}, sid="sid-2")
        bare = w.fake.chats[-1][1]
        kinds = {e["kind"] for e in w.events()}
    finally:
        w.close()
    sent = w.fake.chats[-2][1]
    assert sent["tools"] == tools and sent["messages"] == [{"role": "system", "content": "persona"}, *history]
    assert bare["tools"] == tools and bare["messages"] == history
    assert kinds <= {"config.warn", "context.prefix", "ctx.estimate", "http.access", "request.recv",
                     "response.sent", "upstream.request", "upstream.done", "context.window"}


def _atoms(messages):
    """The conversation as ordered facts (text per role, calls, result slots), blind to how adjacent assistant pieces are grouped."""
    out = []
    for m in messages:
        c = m.get("content")
        c = "".join(p.get("text", "") for p in c) if isinstance(c, list) else c
        if c and c.strip():
            out.append((m["role"], c.strip()))
        out += [("call", t["function"]["name"], t["function"]["arguments"]) for t in m.get("tool_calls") or []]
        if m["role"] == "tool":
            out.append(("result", m["tool_call_id"], m["content"]))
    return out


def _codex_bodies():
    """Real Codex-shaped Responses requests (the shapes of ~/.cria/calls inbound bodies): persona + developer, a shell function, a custom
    patch tool and a native search; a history with a failed command, a failed patch and an empty search; and text that looks like dialect."""
    shell = {"type": "function", "name": "exec_command", "description": "run", "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}}
    patch = {"type": "custom", "name": "apply_patch", "description": "edit", "format": {"type": "grammar", "syntax": "lark", "definition": "start: x"}}
    user = lambda t: {"type": "message", "role": "user", "content": [{"type": "input_text", "text": t}]}
    call = lambda i, n, a: {"type": "function_call", "call_id": i, "name": n, "arguments": json.dumps(a)}
    out = lambda i, t: {"type": "function_call_output", "call_id": i, "output": t}
    note = {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "I will look.\n```json\n{\"name\": \"exec_command\", \"arguments\": {\"cmd\": \"ls\"}}\n```"}]}
    history = [user("<environment_context>\n<cwd>/work</cwd>\n</environment_context>"), user("fix the importer and run the tests"), note,
               call("c1", "exec_command", {"cmd": "pytest -q"}), out("c1", "exec_command failed: No such file or directory"),
               call("c2", "exec_command", {"cmd": "grep -rn nothing ."}), out("c2", ""),
               {"type": "custom_tool_call", "call_id": "c3", "name": "apply_patch", "input": "*** Begin Patch\n*** End Patch"},
               {"type": "custom_tool_call_output", "call_id": "c3", "output": "apply_patch verification failed"}, user("continue")]
    common = {"model": "m", "stream": False, "instructions": "You are a coding agent running in the Codex CLI.\nBe precise.", "prompt_cache_key": "sid-1"}
    return [dict(common, input=[user("hello")], tools=[shell]),
            dict(common, input=history, tools=[shell, patch, {"type": "web_search"}], tool_choice="auto", parallel_tool_calls=True),
            dict(common, input=history * 3, tools=[shell])]


@pytest.mark.parametrize("mode,beat,text", [("chat-stream", b": cria", b"Hello world"),
                                           ("responses-stream", b"event: response.in_progress", b'"text": "Hello world"')])
def test_a_slow_prefill_is_kept_alive_with_heartbeats_and_the_content_still_arrives(tmp_path, mode, beat, text):
    """Idle streams get a keepalive (an SSE comment on chat; a real response.in_progress event on Responses because Codex's idle timer ignores comments)."""
    w = Wire(tmp_path, heartbeat=0.05)
    try:
        path, body = request(mode, "__SLOW__")
        req = urllib.request.Request(f"http://127.0.0.1:{w.cria.server_address[1]}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with OPEN(req, timeout=20) as r:
            seen = b""
            while beat not in seen:  # upstream is still holding its reply: only a heartbeat can arrive
                line = r.readline()
                assert line, "stream ended without a heartbeat"
                seen += line
            w.fake.release.set()
            seen += r.read()
    finally:
        w.fake.release.set()
        w.close()
    assert text in seen


@pytest.mark.parametrize("level", [0, 3])
@pytest.mark.parametrize("shape", ["string", "parts"])
def test_the_dropped_prose_marker_never_reaches_the_model_at_any_level(tmp_path, level, shape):
    """A harness replayed a compaction reply whose private prose-dropped marker was only stripped at level 3+ for Codex-shaped turns; the wire now scrubs it everywhere and its spelling never contains the word cria."""
    w = Wire(tmp_path, lambda url: RoutingConfig(engagement_level=level))
    text = PROSE_DROPPED_MARKER + "\nFILES ALREADY IN THIS WORKSPACE:\n  README.md"
    content = text if shape == "string" else [{"type": "text", "text": text}]
    try:
        w.post("/v1/chat/completions", {"model": "m", "messages": [
            {"role": "assistant", "content": content}, {"role": "user", "content": "continue"}]})
    finally:
        w.close()
    sent = json.dumps(w.fake.chats[-1][1]["messages"], ensure_ascii=False)
    assert "README.md" in sent and PROSE_DROPPED_MARKER not in sent and "cria" not in sent.lower()


def test_call_capture_keeps_the_exact_request_prompt_and_response(tmp_path):
    """With capture on, each model call leaves its exact body, rendered prompt and parsed response, numbered in call order."""
    w = Wire(tmp_path, capture=True)
    try:
        sent = chat_body("hello capture")
        w.post("/v1/chat/completions", sent)
        w.post("/v1/chat/completions", sent)
    finally:
        w.close()
    folder = tmp_path / "calls" / "sid-1"
    assert sorted(p.name for p in folder.glob("000?-proxy.json")) == ["0001-proxy.json", "0002-proxy.json"]
    assert json.loads((folder / "0001-proxy.json").read_text())["body"] == sent
    assert "hello capture" in (folder / "0001-proxy.prompt.txt").read_text()
    assert json.loads((folder / "0001-proxy.response.json").read_text())["choices"][0]["message"]["content"] == "Hi"
