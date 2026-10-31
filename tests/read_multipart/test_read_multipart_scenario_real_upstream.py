"""The multipart read round trip with the REAL Upstream (measurement included) in front of a fake llama.cpp: paged through a PTY, measured against the server's window, delivered exact or withheld."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cria.upstream import Upstream
from read_multipart_helpers import HEX, Backend, Wire, isolated_home  # noqa: F401


class Llama(BaseHTTPRequestHandler):
    """/props, /tokenize (1 token per 3 chars) and /apply-template like llama.cpp; chat is the scripted Backend's answer."""
    log_message = lambda *a: None

    def _send(self, obj):
        raw = (obj if isinstance(obj, str) else json.dumps(obj)).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._send({"default_generation_settings": {"n_ctx": self.server.window}} if self.path.endswith("/props") else {"data": [{"id": "test-model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/tokenize"):
            return self._send({"tokens": [1] * (len(body["content"]) // 3)})
        if self.path.endswith("/apply-template"):
            return self._send({"prompt": json.dumps(body["messages"])})
        self._send(self.server.script.chat(body))


@pytest.mark.parametrize("window,fits", [(49152, True), (8192, False)])
def test_a_paged_read_is_measured_by_the_real_upstream_then_delivered_exact_or_withheld_without_credit(tmp_path, window, fits):
    """Fits: the model's second request carries the file byte for byte as ONE tool result. Measured too big (15k tokens vs 8k): the encoded pages are never replayed, the
    model is told the measured size and earns no read credit, and it can still answer."""
    path = tmp_path / "f"
    path.write_text(HEX)
    script = Backend(path)
    llama = ThreadingHTTPServer(("127.0.0.1", 0), Llama)
    llama.window, llama.script = window, script
    threading.Thread(target=llama.serve_forever, daemon=True).start()
    try:
        with Wire(tmp_path, script) as w:
            w.srv.upstream = Upstream(f"http://127.0.0.1:{llama.server_address[1]}", engagement_level=2)
            msg, carriers = w.drive()
    finally:
        llama.shutdown()
    result = script.tool_results()[0]
    assert msg["content"] == "seen" and len(carriers) > 3
    if fits:
        assert result["content"] == HEX and len(script.bodies) == 2
    else:
        assert HEX not in result["content"] and f"({len(HEX)} bytes)" in result["content"] and "did not fit the context window" in result["content"]
