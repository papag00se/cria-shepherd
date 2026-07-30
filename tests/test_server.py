"""End-to-end passthrough test — cria in front of a FAKE upstream.

Proves the whole request path (HTTP in → forward → SSE/JSON out → events logged)
without touching the real model server on :18084 (single-slot).
"""

import json
import threading
import types
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from cria.config import Backend, Config, IndicatorsConfig, LoggingConfig, Role, ServerConfig, UpstreamConfig
from cria.events import EventLog
from cria.server import CriaServer, _has_visible_output, _proxy_body
from cria.upstream import Upstream


class ProxyBodyTests(unittest.TestCase):
    def test_drops_harness_system_and_developer_keeps_the_rest(self):
        body = {"model": "cria", "tools": [{"x": 1}], "messages": [
            {"role": "system", "content": "You are Codex, a coding agent based on GPT-5..."},
            {"role": "developer", "content": "apps/skills/plugins boilerplate"},
            {"role": "user", "content": "generate a title for this task"},
            {"role": "assistant", "content": "prior"},
        ]}
        out = _proxy_body(body)
        roles = [m["role"] for m in out["messages"]]
        self.assertEqual(roles, ["user", "assistant"])        # harness system+developer dropped
        self.assertEqual(out["tools"], body["tools"])          # everything else intact
        self.assertEqual(body["messages"][0]["role"], "system")  # original not mutated

    def test_noop_when_no_harness_system(self):
        body = {"messages": [{"role": "user", "content": "hi"}]}
        self.assertIs(_proxy_body(body), body)  # same object → no needless copy


class ApplyRouteRoleTests(unittest.TestCase):
    """The proxy path must attach the routed local role's sampling/reasoning — else a local model
    runs on server defaults (no repeat_penalty → gemma dialect leaks; wrong temp). This was the
    'not the same Gemma 4' bug: role was applied only in the loop, never on the proxy path."""

    def _handler(self, roles):
        from cria.server import CriaHandler
        h = CriaHandler.__new__(CriaHandler)  # bare instance, no socket
        h.server = types.SimpleNamespace(cfg=types.SimpleNamespace(
            routing=types.SimpleNamespace(roles=roles)))
        return h

    def test_applies_the_indicated_role(self):
        from cria.config import Role
        coder = Role(name="coder", backend="local", reasoning="on", temperature=0.0, top_p=0.95,
                     top_k=64, repeat_penalty=1.1)
        h = self._handler({"coder": coder})
        indic = types.SimpleNamespace(role="coder")
        body = {"messages": [{"role": "user", "content": "x"}]}
        h._apply_route_role(body, indic)
        self.assertEqual(body["temperature"], 0.0)
        self.assertEqual(body["repeat_penalty"], 1.1)
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": True})

    def test_noop_on_passthrough_role_none(self):
        h = self._handler({"coder": object()})
        body = {"messages": []}
        h._apply_route_role(body, types.SimpleNamespace(role=None))
        self.assertNotIn("temperature", body)  # passthrough → untouched


class HasVisibleOutputTests(unittest.TestCase):
    """The ⟦cria⟧ banner shows only when the turn carries something to see."""

    def _comp(self, message):
        return {"choices": [{"message": message}]}

    def test_tool_call_is_visible(self):
        self.assertTrue(_has_visible_output(self._comp({"tool_calls": [{"id": "x"}]})))

    def test_text_is_visible(self):
        self.assertTrue(_has_visible_output(self._comp({"content": "hello"})))

    def test_empty_is_not_visible(self):
        self.assertFalse(_has_visible_output(self._comp({"content": "", "tool_calls": []})))
        self.assertFalse(_has_visible_output(self._comp({"content": None})))
        self.assertFalse(_has_visible_output(self._comp({"content": "   \n"})))  # whitespace-only

_SSE = (
    b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
    b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"completion_tokens":2}}\n\n'
    b"data: [DONE]\n\n"
)
_JSON = json.dumps(
    {"choices": [{"message": {"role": "assistant", "content": "Hi"}}], "usage": {"completion_tokens": 1}}
).encode()


_CLASSIFY_JSON = json.dumps(
    {"choices": [{"message": {"content": '{"engagement": "task", "task_type": "coding", "reason": "build it"}'}}]}
).encode()
_PLAN_JSON = json.dumps(
    {"choices": [{"message": {"content": '{"steps": ["step one", "step two", "step three"]}'}}]}
).encode()


def _has_system(body: dict, needle: str) -> bool:
    return any(m.get("role") == "system" and needle in str(m.get("content", "")) for m in body.get("messages", []))


class _FakeUpstream(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = json.loads(self.rfile.read(length)) if length else {}
        if _has_system(body, "REQUEST CLASSIFIER"):  # the classifier call
            self._json(_CLASSIFY_JSON)
        elif _has_system(body, "planner for a SMALL local coding model"):  # the planner call
            self._json(_PLAN_JSON)
        elif any("__NONJSON__" in str((m or {}).get("content") or "") for m in body.get("messages") or []):
            self._raw200(b"<html><body>502 Bad Gateway</body></html>")  # an intermediary's HTML error, 200
        elif body.get("stream"):
            self._sse()
        else:
            self._json(_JSON)

    def _raw200(self, payload: bytes):  # a 200 whose body is NOT JSON (proxy/LB HTML error page)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        # cria asks the server what model is loaded (/v1/models) — there are no config aliases, so
        # this IS the wire model cria rewrites every local request to.
        if self.path.endswith("/v1/models"):
            self._json(json.dumps({"data": [{"id": "gemma-loaded"}]}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def _sse(self):
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(_SSE)
        self.wfile.flush()

    def _json(self, payload: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _serve(server) -> threading.Thread:
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return t


class PassthroughTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstream)
        _serve(self.fake)
        self.addCleanup(self.fake.server_close)
        self.addCleanup(self.fake.shutdown)
        fake_port = self.fake.server_address[1]

        cfg = Config(
            server=ServerConfig(host="127.0.0.1", port=0),
            upstream=UpstreamConfig(base_url=f"http://127.0.0.1:{fake_port}"),
            logging=LoggingConfig(dir=self._tmp.name, capture_dir=self._tmp.name, console=False),
            indicators=IndicatorsConfig(enabled=False),  # test raw transport fidelity
        )
        self.log = EventLog(dir=cfg.logging.dir, console=False)
        self.addCleanup(self.log.close)
        self.cria = CriaServer(cfg, self.log, Upstream(cfg.upstream.base_url))
        _serve(self.cria)
        self.addCleanup(self.cria.server_close)
        self.addCleanup(self.cria.shutdown)
        self.base = f"http://127.0.0.1:{self.cria.server_address[1]}"

    def _events(self) -> list[dict]:
        assert self.log.path is not None
        return [json.loads(l) for l in Path(self.log.path).read_text().splitlines() if l.strip()]

    def _post(self, body: dict) -> bytes:
        req = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "X-Cria-Session-Id": "sess-1"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()

    def test_streaming_preserves_content(self):
        # The stream now passes through the streaming massager (which may re-chunk),
        # so the contract is content-faithful, not byte-faithful.
        out = self._post({"model": "m", "stream": True, "messages": [{"role": "user", "content": "hi"}]}).decode()
        text = "".join(
            json.loads(line[5:])["choices"][0]["delta"].get("content", "")
            for line in out.splitlines()
            if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]")
        )
        self.assertEqual(text, "Hello world")
        self.assertTrue(out.rstrip().endswith("[DONE]"))

    def test_buffered_passthrough(self):
        out = self._post({"model": "m", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(json.loads(out)["choices"][0]["message"]["content"], "Hi")

    def test_non_json_200_fails_closed_not_empty(self):
        # M4: a non-JSON 200 (an intermediary's HTML 502 page, a truncated body) must fail CLOSED — a
        # clean 502 — NOT be recorded as a successful EMPTY completion (the old `return {}` fail-open).
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._post({"model": "m", "messages": [{"role": "user", "content": "__NONJSON__ please"}]})
        self.assertEqual(cm.exception.code, 502)

    def test_post_with_query_string_still_routes(self):
        # L9: do_POST didn't strip the query string (do_GET did), so a client appending ?param 404'd.
        req = urllib.request.Request(
            self.base + "/v1/chat/completions?debug=1",
            data=json.dumps({"model": "m", "messages": [{"role": "user", "content": "hi"}]}).encode(),
            method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:   # 404 would raise HTTPError
            self.assertEqual(json.loads(r.read())["choices"][0]["message"]["content"], "Hi")

    def test_events_capture_the_turn_with_metrics(self):
        self._post({"model": "m", "stream": True, "messages": [{"role": "user", "content": "hi"}]})
        kinds = [e["kind"] for e in self._events()]
        for expected in ("request.recv", "upstream.request", "upstream.first_token", "upstream.done", "response.sent"):
            self.assertIn(expected, kinds)
        done = next(e for e in self._events() if e["kind"] == "upstream.done")
        self.assertEqual(done["tokens"], 2)  # from the usage block
        self.assertTrue(done["from_usage"])
        self.assertEqual(done["session"], "sess-1")  # X-Cria-Session-Id threaded through

    def test_health(self):
        with urllib.request.urlopen(self.base + "/health", timeout=10) as r:
            self.assertEqual(json.loads(r.read())["status"], "ok")

    def _post_responses(self, body: dict) -> bytes:
        req = urllib.request.Request(
            self.base + "/v1/responses", data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()

    def test_responses_path_strips_cria_banner_from_history(self):
        # The Responses API path (what Codex speaks) must strip cria's own "⟦cria⟧" lines
        # inbound, same as the chat path — else the banner leaks into the compaction summary
        # and the plan task (observed live).
        from cria.indicators import MARKER
        body = {"model": "m", "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text",
             "text": f"summarize the thread\n{MARKER}reasoner · m · 7 tok/s\nthe real summary"}]}]}
        self._post_responses(body)
        self.assertIn("indicators.stripped", [e["kind"] for e in self._events()])


class RoutedTests(unittest.TestCase):
    """cria WITH routing config: classify → route → rewrite model → proxy."""

    def setUp(self):
        from cria.config import RoutingConfig

        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstream)
        _serve(self.fake)
        self.addCleanup(self.fake.server_close)
        self.addCleanup(self.fake.shutdown)
        fake_port = self.fake.server_address[1]

        cfg = Config(
            server=ServerConfig(host="127.0.0.1", port=0),
            upstream=UpstreamConfig(base_url=f"http://127.0.0.1:{fake_port}"),
            logging=LoggingConfig(dir=self._tmp.name, capture_dir=self._tmp.name, console=False),
            routing=RoutingConfig(
                backends={"local": Backend("local")},
                roles={"classifier": Role(name="classifier", backend="local"),
                       "coder": Role(name="coder", backend="local")},
                failover={"coding": ("coder",)},
                engagement_bias="task",
            ),
        )
        self.log = EventLog(dir=cfg.logging.dir, console=False)
        self.addCleanup(self.log.close)
        self.cria = CriaServer(cfg, self.log, Upstream(cfg.upstream.base_url))
        _serve(self.cria)
        self.addCleanup(self.cria.server_close)
        self.addCleanup(self.cria.shutdown)
        self.base = f"http://127.0.0.1:{self.cria.server_address[1]}"

    def _events(self):
        return [json.loads(l) for l in Path(self.log.path).read_text().splitlines() if l.strip()]

    def test_classify_then_route_rewrites_the_model(self):
        req = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=json.dumps({"model": "orig-model", "stream": True, "messages": [{"role": "user", "content": "write a handler and tests"}]}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            out = r.read()
        self.assertIn(b"Hello", out)  # the model's tokens are still forwarded
        self.assertIn("⟦cria⟧".encode(), out)  # cria's indicator is injected
        self.assertIn(b"coder", out)  # the routed role is shown to the human

        events = self._events()
        decisions = {e["decision"]: e for e in events if e["kind"] == "decision"}
        self.assertEqual(decisions["engagement"]["choice"], "task")
        self.assertEqual(decisions["route"]["choice"], "coder")

        # The proxied completion is model-REWRITTEN to the server's LOADED model (gemma-loaded, from
        # /v1/models), not the client's "orig-model" and not a config alias (there are none).
        proxied = [e for e in events if e["kind"] == "upstream.request" and e.get("stream")]
        self.assertTrue(proxied and proxied[-1]["model"] == "gemma-loaded")


_SHELL_TOOL = {"type": "function", "function": {"name": "shell", "parameters": {"type": "object", "properties": {"command": {"type": "array"}}}}}


class PlanningTests(unittest.TestCase):
    """A fresh coding task starts the plan-driven loop, which writes the plan file
    via a harness shell tool call and surfaces it as an indicator."""

    def setUp(self):
        from cria.config import PlannerConfig, RoutingConfig

        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstream)
        _serve(self.fake)
        self.addCleanup(self.fake.server_close)
        self.addCleanup(self.fake.shutdown)

        cfg = Config(
            server=ServerConfig(host="127.0.0.1", port=0),
            upstream=UpstreamConfig(base_url=f"http://127.0.0.1:{self.fake.server_address[1]}"),
            logging=LoggingConfig(dir=self._tmp.name, capture_dir=self._tmp.name, console=False),
            routing=RoutingConfig(
                backends={"local": Backend("local")},
                roles={"classifier": Role(name="classifier", backend="local"),
                       "reasoner": Role(name="reasoner", backend="local"),
                       "coder": Role(name="coder", backend="local")},
                failover={"coding": ("coder",)},
            ),
            planner=PlannerConfig(enabled=True),
        )
        self.log = EventLog(dir=cfg.logging.dir, console=False)
        self.addCleanup(self.log.close)
        self.cria = CriaServer(cfg, self.log, Upstream(cfg.upstream.base_url))
        _serve(self.cria)
        self.addCleanup(self.cria.server_close)
        self.addCleanup(self.cria.shutdown)
        self.base = f"http://127.0.0.1:{self.cria.server_address[1]}"

    def test_fresh_task_starts_loop_and_drives_the_coder(self):
        req = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=json.dumps({
                "model": "m",
                "stream": True,
                "tools": [_SHELL_TOOL],
                "messages": [{"role": "user", "content": "build an ada handle resolver with tests"}],
            }).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            out = r.read().decode()

        # The loop drafts the plan and drives straight into the coder — NO `.cria/` file is written
        # into the workspace (cria's plan mirror lives in its OWN dir). The coder here produces no
        # tool call, so (after the one no-tools nudge) the loop emits its ground-truth GATE.
        self.assertIn("tool_calls", out)
        from cria.probegate import SECTION_PREFIX
        self.assertIn(SECTION_PREFIX, out)   # the composed gate is running
        self.assertNotIn("cd . ||", out)     # unknown cwd NEVER discovers cria's own repo
        self.assertNotIn(".cria/", out)      # cria's scratch never leaks into the workspace
        events = [json.loads(l) for l in Path(self.log.path).read_text().splitlines() if l.strip()]
        self.assertTrue(any(e["kind"] == "loop.start" and e["steps"] == 3 for e in events))


class _Fake500Coder(BaseHTTPRequestHandler):
    """Classifier and planner succeed; the coder (any other call) returns 500 — the
    exact Qwythos/Ornith incident (strict template rejects the coder request)."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = json.loads(self.rfile.read(length)) if length else {}
        if _has_system(body, "REQUEST CLASSIFIER"):
            return self._json(_CLASSIFY_JSON)
        if _has_system(body, "planner for a SMALL local coding model"):
            return self._json(_PLAN_JSON)
        # the coder call
        payload = json.dumps({"error": {"message": "System message must be at the beginning.", "type": "server_error"}}).encode()
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, payload: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class ResilienceTests(unittest.TestCase):
    """An upstream 500 inside the plan loop must degrade to a clean error, never a
    dropped connection / dead handler thread."""

    def setUp(self):
        from cria.config import PlannerConfig, RoutingConfig

        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), _Fake500Coder)
        _serve(self.fake)
        self.addCleanup(self.fake.server_close)
        self.addCleanup(self.fake.shutdown)
        cfg = Config(
            server=ServerConfig(host="127.0.0.1", port=0),
            upstream=UpstreamConfig(base_url=f"http://127.0.0.1:{self.fake.server_address[1]}"),
            logging=LoggingConfig(dir=self._tmp.name, capture_dir=self._tmp.name, console=False),
            routing=RoutingConfig(
                backends={"local": Backend("local")},
                roles={"classifier": Role(name="classifier", backend="local"),
                       "reasoner": Role(name="reasoner", backend="local"),
                       "coder": Role(name="coder", backend="local")},
                failover={"coding": ("coder",)},
            ),
            planner=PlannerConfig(enabled=True),
        )
        self.log = EventLog(dir=cfg.logging.dir, console=False)
        self.addCleanup(self.log.close)
        self.cria = CriaServer(cfg, self.log, Upstream(cfg.upstream.base_url))
        _serve(self.cria)
        self.addCleanup(self.cria.server_close)
        self.addCleanup(self.cria.shutdown)
        self.base = f"http://127.0.0.1:{self.cria.server_address[1]}"

    def _post(self, body: dict, stream: bool):
        req = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=json.dumps({**body, "stream": stream}).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "X-Cria-Session-Id": "res-1"},
        )
        return urllib.request.urlopen(req, timeout=10)

    _TOOLS = [_SHELL_TOOL]
    _MSGS = [{"role": "user", "content": "build an ada handle resolver with tests"}]

    def test_streaming_loop_500_yields_error_not_crash(self):
        # The loop now drives straight into the coder on turn 1 (no plan-file round-trip), so the
        # coder's 500 surfaces immediately — as a clean in-stream error, never a dropped connection.
        out1 = self._post({"model": "m", "tools": self._TOOLS, "messages": self._MSGS}, stream=True).read().decode()
        self.assertIn("error", out1.lower())
        self.assertTrue(out1.rstrip().endswith("[DONE]"))
        events = [json.loads(l) for l in Path(self.log.path).read_text().splitlines() if l.strip()]
        self.assertTrue(any(e["kind"] == "response.error" for e in events))

    def test_buffered_loop_500_returns_502(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:  # coder 500 on turn 1 → clean 502, not a drop
            self._post({"model": "m", "tools": self._TOOLS, "messages": self._MSGS}, stream=False)
        self.assertEqual(cm.exception.code, 502)


class ResponsesApiTests(unittest.TestCase):
    """The /v1/responses endpoint (what Codex speaks): a Responses request is
    translated to chat, run through the pipeline, and returned as Responses SSE."""

    def setUp(self):
        from cria.config import RoutingConfig

        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstream)
        _serve(self.fake)
        self.addCleanup(self.fake.server_close)
        self.addCleanup(self.fake.shutdown)
        cfg = Config(
            server=ServerConfig(host="127.0.0.1", port=0),
            upstream=UpstreamConfig(base_url=f"http://127.0.0.1:{self.fake.server_address[1]}"),
            logging=LoggingConfig(dir=self._tmp.name, capture_dir=self._tmp.name, console=False),
            routing=RoutingConfig(backends={"local": Backend("local")},
                                  roles={"classifier": Role(name="classifier", backend="local"),
                                         "coder": Role(name="coder", backend="local")},
                                  failover={"coding": ("coder",)}),
            indicators=IndicatorsConfig(enabled=False),  # test raw translation (no ⟦cria⟧ banner)
        )
        self.log = EventLog(dir=cfg.logging.dir, console=False)
        self.addCleanup(self.log.close)
        self.cria = CriaServer(cfg, self.log, Upstream(cfg.upstream.base_url))
        _serve(self.cria)
        self.addCleanup(self.cria.server_close)
        self.addCleanup(self.cria.shutdown)
        self.base = f"http://127.0.0.1:{self.cria.server_address[1]}"

    def _post_responses(self, body: dict) -> str:
        req = urllib.request.Request(self.base + "/v1/responses", data=json.dumps(body).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode()

    def test_responses_stream_roundtrip(self):
        out = self._post_responses({
            "model": "m", "stream": True, "instructions": "You are a coding agent.",
            "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
        })
        # the buffered upstream reply "Hi" comes back as Responses events, not chat
        self.assertIn("response.created", out)
        self.assertIn("response.completed", out)
        completed = [json.loads(l[6:]) for l in out.splitlines()
                     if l.startswith("data: ") and "response.completed" in l][0]
        text = completed["response"]["output"][0]["content"][0]["text"]
        self.assertEqual(text, "Hi")

    def test_models_endpoint_has_models_field(self):
        with urllib.request.urlopen(self.base + "/v1/models", timeout=10) as r:
            doc = json.loads(r.read())
        self.assertIn("models", doc)  # Codex's model manager requires this field
        self.assertIn("data", doc)    # plain OpenAI clients want this one


class RewriteDetectionTests(unittest.TestCase):
    """Harness-compaction detection (the seed anomaly): a changed conversation root under a stable
    session key = the history was replaced → re-anchor the coder. The single driver composes it in
    _drive_locked as `_stable_session(key) and store.observe_shape(key, root_fp, n)` — no phrase-
    matching. (Both the multi-item and synthetic paths go through that one detection now.)"""

    def _fp(self, text):
        from cria.loop import _history_root
        return _history_root([{"role": "user", "content": text}])[1]

    def test_rewrite_detected_on_replaced_root_under_stable_key(self):
        from cria.loop import LoopStore, _stable_session
        store, key = LoopStore(), "sid:abc"
        self.assertTrue(_stable_session(key))
        self.assertFalse(store.observe_shape(key, self._fp("build the lambda"), 1))  # first sight → no rewrite
        self.assertFalse(store.observe_shape(key, self._fp("build the lambda"), 2))  # append keeps the root
        self.assertTrue(store.observe_shape(key, self._fp("SUMMARY: earlier we built the lambda…"), 1))  # replaced

    def test_task_keys_never_detect_rewrite(self):
        from cria.loop import _stable_session
        self.assertFalse(_stable_session("task:xyz"))  # the loop gates observe_shape on this → no detection


class SessionCwdTests(unittest.TestCase):
    """The workspace cwd is the HARNESS's own repo — never cria's dir — and it must persist across a
    turn that drops the <cwd> block (a harness compaction), so the gate/steer never lose the repo."""

    def _env(self, cwd):
        return [{"role": "user", "content": f"<environment_context>\n<cwd>{cwd}</cwd>\n</environment_context>"}]

    def test_persists_across_a_turn_that_drops_cwd_and_never_uses_cria_dir(self):
        from cria.server import _session_cwd, _CWD_BY_SESSION
        _CWD_BY_SESSION.clear()
        # turn 1: harness advertises its repo
        self.assertEqual(_session_cwd("sk1", self._env("/home/u/project")), "/home/u/project")
        # turn 2: harness compaction dropped the <cwd> block → the last-known repo is kept, NOT "."/None
        self.assertEqual(_session_cwd("sk1", [{"role": "user", "content": "continue"}]), "/home/u/project")
        # a session that NEVER advertised a cwd stays unknown (None) — callers skip; never cria's dir
        self.assertIsNone(_session_cwd("sk_unknown", [{"role": "user", "content": "hi"}]))

    def test_a_fresh_cwd_updates_the_remembered_one(self):
        from cria.server import _session_cwd, _CWD_BY_SESSION
        _CWD_BY_SESSION.clear()
        _session_cwd("sk2", self._env("/a"))
        self.assertEqual(_session_cwd("sk2", self._env("/b")), "/b")   # newest advertised wins


class VisibleWebCallsTests(unittest.TestCase):
    """_visible_web_calls extracts the full (url, find, cursor) key + queries from the calls still
    present, so the exact-repeat gate only refuses a repeat while its result is in context."""

    def test_extracts_url_find_cursor_and_queries(self):
        from cria.server import _visible_web_calls
        msgs = [
            {"role": "assistant", "tool_calls": [
                {"function": {"name": "web_fetch", "arguments": '{"url":"https://x/spec","find":"resolve","cursor":"c500"}'}}]},
            {"role": "assistant", "tool_calls": [
                {"function": {"name": "web_fetch", "arguments": '{"url":"https://y/"}'}},
                {"function": {"name": "web_search", "arguments": '{"query":"ada handle api"}'}}]},
            {"role": "user", "content": "not a tool call"},
        ]
        fk, sq = _visible_web_calls(msgs)
        self.assertIn(("https://x/spec", "resolve", "c500"), fk)
        self.assertIn(("https://y/", "", ""), fk)
        self.assertEqual(sq, ["ada handle api"])


class CompactorRoleWiringTests(unittest.TestCase):
    """The self-compaction summarizer must ride the [models.local.compactor] role (temp 0.6, reasoning
    on) — NEVER the coder role (temp 0.1, coding-primed: it misreads "summarize this" as "continue the
    task"). Falls back to the reasoner (same sampling family) when no compactor table is configured."""

    def _server(self, roles, planner=False):
        from cria.config import PlannerConfig, RoutingConfig
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = Config(
            server=ServerConfig(host="127.0.0.1", port=0),
            upstream=UpstreamConfig(base_url="http://127.0.0.1:1"),  # never called — __init__ only
            logging=LoggingConfig(dir=tmp.name, capture_dir=tmp.name, console=False),
            routing=RoutingConfig(backends={"local": Backend("local")}, roles=roles, failover={"coding": ("coder",)}),
            planner=PlannerConfig(enabled=planner),
        )
        log = EventLog(dir=cfg.logging.dir, console=False)
        self.addCleanup(log.close)
        srv = CriaServer(cfg, log, Upstream(cfg.upstream.base_url))
        self.addCleanup(srv.server_close)
        return srv

    def test_uses_compactor_role_when_configured(self):
        compactor = Role(name="compactor", backend="local", temperature=0.6)
        coder = Role(name="coder", backend="local", temperature=0.1)
        reasoner = Role(name="reasoner", backend="local", temperature=0.6)
        srv = self._server({"classifier": Role(name="classifier", backend="local"), "reasoner": reasoner,
                            "coder": coder, "compactor": compactor})
        self.assertIs(srv.compactor_role, compactor)
        self.assertIsNot(srv.compactor_role, coder)

    def test_falls_back_to_reasoner_not_coder_when_no_compactor(self):
        coder = Role(name="coder", backend="local", temperature=0.1)
        reasoner = Role(name="reasoner", backend="local", temperature=0.6)
        srv = self._server({"classifier": Role(name="classifier", backend="local"), "reasoner": reasoner, "coder": coder})
        self.assertIs(srv.compactor_role, reasoner)
        self.assertIsNot(srv.compactor_role, coder)

    def test_loop_context_carries_the_compactor_role(self):
        compactor = Role(name="compactor", backend="local", temperature=0.6)
        coder = Role(name="coder", backend="local", temperature=0.1)
        reasoner = Role(name="reasoner", backend="local", temperature=0.6)
        srv = self._server({"classifier": Role(name="classifier", backend="local"), "reasoner": reasoner,
                            "coder": coder, "compactor": compactor}, planner=True)
        self.assertIsNotNone(srv.loop)
        self.assertIs(srv.loop._ctx.compactor_role, compactor)
        self.assertIsNot(srv.loop._ctx.compactor_role, coder)


class CompactionRoutingTests(unittest.TestCase):
    """A harness `<<<LOCAL_COMPACT>>>` request is a SUMMARIZE turn (correctly tool-less) — it must route
    to the COMPACTOR endpoint + role's tuned sampling, never the classifier's guess (its text reads as a
    plain question → reasoner) or a bare passthrough (server-default sampling misreads 'summarize')."""

    def _handler(self, roles, compactor_upstream, upstream):
        from cria.server import CriaHandler
        h = CriaHandler.__new__(CriaHandler)
        h.server = types.SimpleNamespace(
            compactor_upstream=compactor_upstream, upstream=upstream, router=None,
            cfg=types.SimpleNamespace(
                routing=types.SimpleNamespace(roles=roles),
                indicators=types.SimpleNamespace(enabled=True, metrics=True, route=True, assists=True)))
        return h

    def _rlog(self):
        return types.SimpleNamespace(emit=lambda *a, **k: None)

    def _compact_body(self):
        return {"messages": [{"role": "user", "content": "<<<LOCAL_COMPACT>>> Summarize the thread."}]}

    def test_routes_to_compactor_endpoint_and_role(self):
        compactor_up = object()
        h = self._handler({"compactor": object()}, compactor_up, object())
        provider, indic = h._route(self._compact_body(), None, self._rlog())
        self.assertIs(provider, compactor_up)       # the compactor ENDPOINT, not the shared upstream
        self.assertEqual(indic.role, "compactor")   # → _apply_route_role applies compactor sampling

    def test_falls_back_to_reasoner_role_when_no_compactor(self):
        compactor_up = object()
        h = self._handler({"reasoner": object()}, compactor_up, object())
        provider, indic = h._route(self._compact_body(), None, self._rlog())
        self.assertIs(provider, compactor_up)
        self.assertEqual(indic.role, "reasoner")     # compactor_upstream falls back to reasoner's box too

    def test_normal_request_is_not_treated_as_compaction(self):
        upstream = object()
        h = self._handler({"compactor": object()}, object(), upstream)  # router None → passthrough
        body = {"messages": [{"role": "user", "content": "Write an Ada Handle resolver."}]}
        provider, indic = h._route(body, None, self._rlog())
        self.assertIs(provider, upstream)            # passthrough, NOT the compactor endpoint
        self.assertIsNone(indic.role)


class LoopConstructionGateTests(unittest.TestCase):
    """Route-unify: the loop is cria's ONE coder driver, so it is built whenever a coder exists — with
    the planner OFF too (it then drives the synthetic 1-item path). A reasoner is required only when the
    planner is ON. No coder → no loop (a smart proxy)."""

    def _server(self, roles, planner):
        from cria.config import PlannerConfig, RoutingConfig
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = Config(
            server=ServerConfig(host="127.0.0.1", port=0),
            upstream=UpstreamConfig(base_url="http://127.0.0.1:1"),  # never called — __init__ only
            logging=LoggingConfig(dir=tmp.name, capture_dir=tmp.name, console=False),
            routing=RoutingConfig(backends={"local": Backend("local")}, roles=roles, failover={"coding": ("coder",)}),
            planner=PlannerConfig(enabled=planner),
        )
        log = EventLog(dir=cfg.logging.dir, console=False)
        self.addCleanup(log.close)
        srv = CriaServer(cfg, log, Upstream(cfg.upstream.base_url))
        self.addCleanup(srv.server_close)
        return srv

    def test_built_when_planner_off_even_without_a_reasoner(self):
        srv = self._server({"coder": Role(name="coder", backend="local")}, planner=False)
        self.assertIsNotNone(srv.loop)                     # the synthetic 1-item driver
        self.assertFalse(srv.loop._ctx.planner_enabled)
        self.assertIsNone(srv.loop._ctx.reasoner_role)     # off-ramps that need it just skip

    def test_requires_reasoner_when_planner_on(self):
        srv = self._server({"coder": Role(name="coder", backend="local")}, planner=True)
        self.assertIsNone(srv.loop)                        # planner on but no reasoner → no loop

    def test_no_coder_means_no_loop(self):
        srv = self._server({"reasoner": Role(name="reasoner", backend="local")}, planner=False)
        self.assertIsNone(srv.loop)                        # no coder → a smart proxy


if __name__ == "__main__":
    unittest.main()


class ResponsesStatusTickerTests(unittest.TestCase):
    """The LIVE status item: opened before any model work, ⟦cria⟧ phase lines streamed as
    output_text deltas while the pipeline grinds, closed into the completed response's output.
    The real message follows at the next output index."""

    def setUp(self):
        from cria.config import RoutingConfig
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstream)
        _serve(self.fake)
        self.addCleanup(self.fake.server_close)
        self.addCleanup(self.fake.shutdown)
        cfg = Config(
            server=ServerConfig(host="127.0.0.1", port=0),
            upstream=UpstreamConfig(base_url=f"http://127.0.0.1:{self.fake.server_address[1]}"),
            logging=LoggingConfig(dir=self._tmp.name, capture_dir=self._tmp.name, console=False),
            routing=RoutingConfig(backends={"local": Backend("local")},
                                  roles={"classifier": Role(name="classifier", backend="local"),
                                         "coder": Role(name="coder", backend="local")},
                                  failover={"coding": ("coder",)}),
            indicators=IndicatorsConfig(enabled=True, status=True, route=False, metrics=False,
                                        assists=False, stats=False, reasoning=False,
                                        reasoning_transcript=False),
        )
        self.log = EventLog(dir=cfg.logging.dir, console=False)
        self.addCleanup(self.log.close)
        self.cria = CriaServer(cfg, self.log, Upstream(cfg.upstream.base_url))
        _serve(self.cria)
        self.addCleanup(self.cria.server_close)
        self.addCleanup(self.cria.shutdown)
        self.base = f"http://127.0.0.1:{self.cria.server_address[1]}"

    def test_status_item_streams_and_lands_in_the_completed_output(self):
        req = urllib.request.Request(
            self.base + "/v1/responses",
            data=json.dumps({"model": "m", "stream": True, "instructions": "agent",
                             "input": [{"type": "message", "role": "user",
                                        "content": [{"type": "input_text", "text": "hi"}]}]}).encode(),
            method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            out = r.read().decode()
        # a ⟦cria⟧ status delta streamed BEFORE the completed event
        deltas = [l for l in out.splitlines() if "output_text.delta" in l and "⟦cria⟧" in l]
        self.assertTrue(deltas, "no live status delta on the wire")
        self.assertLess(out.index("output_text.delta"), out.index("response.completed"))
        completed = [json.loads(l[6:]) for l in out.splitlines()
                     if l.startswith("data: ") and '"response.completed"' in l][0]
        output = completed["response"]["output"]
        self.assertGreaterEqual(len(output), 2)
        self.assertIn("⟦cria⟧", output[0]["content"][0]["text"])   # the closed status item
        self.assertEqual(output[1]["content"][0]["text"], "Hi")    # the real message after it


class HardenCompactionReplyTests(unittest.TestCase):
    """The harness stores the compaction reply as the session's ENTIRE remembered past — an empty
    briefing is amnesia (B3 0094), and fetched-spec facts that lived only in the discarded transcript
    got re-guessed as invented endpoints (/v1, /resolve). Retry the empty case reasoning-off; append
    the deterministic fetch ledger always."""

    class _Srv:
        class cfg:
            class routing:
                roles = {}

    class _Rlog:
        phase = "proxy"

        def emit(self, kind, **kw):
            return self

    @staticmethod
    def _comp(text):
        return {"choices": [{"message": {"role": "assistant", "content": text}}]}

    @staticmethod
    def _history():
        return [{"role": "user", "content": "task"},
                {"role": "tool", "tool_call_id": "f1", "content":
                    "HTTP 200 OK · https://api.example.com/openapi.json\n"
                    "[API endpoints (2): /handles/{handle}, /holders/{address}]"},
                {"role": "user", "content": "<<<LOCAL_COMPACT>>> Summarize the thread"}]

    def test_good_summary_gains_the_fetch_facts_appendix(self):
        from cria.server import _harden_compaction_reply
        comp = _harden_compaction_reply(self._comp("Did X, then Y."), {"messages": self._history()},
                                        provider=None, server=self._Srv, rlog=self._Rlog())
        text = comp["choices"][0]["message"]["content"]
        self.assertTrue(text.startswith("Did X, then Y."))          # the model's summary leads
        self.assertIn("/handles/{handle}", text)                    # the real routes survive the fold
        self.assertIn("api.example.com", text)

    def test_empty_summary_retries_reasoning_off_and_adopts_the_retry(self):
        from cria.server import _harden_compaction_reply

        calls = []

        class _Provider:
            @staticmethod
            def chat(pb, rlog):
                calls.append(pb)
                return json.dumps({"choices": [{"message": {
                    "role": "assistant", "content": "Recovered briefing."}}]})

        comp = _harden_compaction_reply(self._comp(""), {"messages": self._history()},
                                        provider=_Provider, server=self._Srv, rlog=self._Rlog())
        self.assertEqual(len(calls), 1)                             # one retry, no loop
        self.assertFalse(calls[0].get("tools"))                     # still a toolless summarize
        text = comp["choices"][0]["message"]["content"]
        self.assertTrue(text.startswith("Recovered briefing."))
        self.assertIn("/handles/{handle}", text)                    # appendix rides the retry too

    def test_failed_retry_never_breaks_the_reply(self):
        from cria.server import _harden_compaction_reply

        class _Provider:
            @staticmethod
            def chat(pb, rlog):
                raise RuntimeError("upstream dead")

        comp = _harden_compaction_reply(self._comp(""), {"messages": self._history()},
                                        provider=_Provider, server=self._Srv, rlog=self._Rlog())
        text = comp["choices"][0]["message"]["content"]
        self.assertIn("/handles/{handle}", text)                    # facts still appended to the empty
