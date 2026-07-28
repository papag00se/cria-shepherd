import json
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tempfile import TemporaryDirectory
from threading import Thread

from cria.config import Config, IndicatorsConfig, LoggingConfig, ServerConfig, UpstreamConfig
from cria.events import EventLog
from cria.heartbeat import Heartbeat
from cria.server import CriaServer
from cria.upstream import Upstream


class HeartbeatUnitTests(unittest.TestCase):
    def test_beats_when_idle(self):
        writes = []
        hb = Heartbeat(writes.append, interval=0.05).start()
        time.sleep(0.3)  # ~6 intervals of silence
        hb.stop()
        self.assertGreaterEqual(hb.beats, 2)
        self.assertTrue(all(w == b": cria\n\n" for w in writes))

    def test_content_writes_suppress_beats(self):
        writes = []
        hb = Heartbeat(writes.append, interval=0.3).start()
        for _ in range(8):  # a write every 0.05s → never idle 0.3s
            hb.write(b"data: x\n\n")
            time.sleep(0.05)
        hb.stop()
        self.assertEqual(hb.beats, 0)
        self.assertTrue(all(w == b"data: x\n\n" for w in writes))

    def test_disabled_when_interval_zero(self):
        hb = Heartbeat(lambda d: None, interval=0).start()
        time.sleep(0.1)
        hb.stop()
        self.assertEqual(hb.beats, 0)


_SSE = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'


class _SlowUpstream(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        self.rfile.read(length)
        time.sleep(0.4)  # slow prefill: cria should heartbeat during this
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(_SSE)
        self.wfile.flush()


class HeartbeatIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), _SlowUpstream)
        Thread(target=self.fake.serve_forever, daemon=True).start()
        self.addCleanup(self.fake.server_close)
        self.addCleanup(self.fake.shutdown)
        cfg = Config(
            server=ServerConfig(host="127.0.0.1", port=0, heartbeat_seconds=0.1),
            upstream=UpstreamConfig(base_url=f"http://127.0.0.1:{self.fake.server_address[1]}"),
            logging=LoggingConfig(dir=self._tmp.name, capture_dir=self._tmp.name, console=False),
            indicators=IndicatorsConfig(enabled=False),
        )
        self.log = EventLog(dir=cfg.logging.dir, console=False)
        self.addCleanup(self.log.close)
        self.cria = CriaServer(cfg, self.log, Upstream(cfg.upstream.base_url))
        Thread(target=self.cria.serve_forever, daemon=True).start()
        self.addCleanup(self.cria.server_close)
        self.addCleanup(self.cria.shutdown)
        self.base = f"http://127.0.0.1:{self.cria.server_address[1]}"

    def test_heartbeats_fill_the_slow_prefill(self):
        req = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=json.dumps({"model": "m", "stream": True, "messages": [{"role": "user", "content": "hi"}]}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            out = r.read()
        self.assertIn(b": cria", out)  # a heartbeat comment appeared during the 0.4s wait
        self.assertIn(b"hi", out)  # and the real content still arrived (re-chunked by the massager)


if __name__ == "__main__":
    unittest.main()


class HeartbeatPayloadTests(unittest.TestCase):
    """A client whose idle timer counts EVENTS ignores SSE comments (observed: the Codex extension
    dropped a Responses stream mid-compaction — "idle timeout waiting for SSE" — while ": cria"
    comments were flowing). The beat payload is now caller-chosen; the Responses path passes a real
    response.in_progress event."""

    def test_custom_payload_is_what_beats(self):
        from cria.heartbeat import Heartbeat
        wrote = []
        t = {"now": 0.0}
        hb = Heartbeat(wrote.append, interval=5.0, clock=lambda: t["now"],
                       payload=b"event: response.in_progress\n\n")
        t["now"] = 6.0
        with hb._lock:
            pass
        # drive one tick manually (no thread): emulate _run's beat condition
        if t["now"] - hb._last >= hb._interval:
            hb._write_raw(hb._payload); hb.beats += 1
        self.assertEqual(wrote, [b"event: response.in_progress\n\n"])

    def test_responses_in_progress_event_shape(self):
        import json
        from cria.responses import in_progress_event
        raw = in_progress_event("resp_x").decode()
        self.assertIn("event: response.in_progress", raw)
        payload = json.loads(raw.split("data: ", 1)[1].strip())
        self.assertEqual(payload["response"]["status"], "in_progress")
        self.assertEqual(payload["response"]["id"], "resp_x")
