"""End-to-end passthrough test — cria in front of a FAKE upstream.

Proves the whole request path (HTTP in → forward → SSE/JSON out → events logged)
without touching the real model server on :18084 (single-slot).
"""

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from cria.config import Config, IndicatorsConfig, LoggingConfig, ServerConfig, UpstreamConfig
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
        elif body.get("stream"):
            self._sse()
        else:
            self._json(_JSON)

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
                local_only=True,
                local_models={"classifier": "m-classifier", "coder": "m-coder"},
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

        # Two upstream calls: the classifier (m-classifier) and the proxied,
        # model-REWRITTEN completion (m-coder, not the client's "orig-model").
        proxied = [e for e in events if e["kind"] == "upstream.request" and e.get("stream")]
        self.assertTrue(proxied and proxied[-1]["model"] == "m-coder")


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
                local_only=True,
                local_models={"classifier": "m-classifier", "reasoner": "m-reasoner", "coder": "m-coder"},
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
                local_only=True,
                local_models={"classifier": "m-classifier", "reasoner": "m-reasoner", "coder": "m-coder"},
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
            routing=RoutingConfig(local_only=True, local_models={"classifier": "m-c", "coder": "m-coder"},
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


if __name__ == "__main__":
    unittest.main()
