"""How a fetched body is read: bounded in TOTAL time (a slow drip never trips urlopen's per-read timeout) and decoded with the charset the
server declared (latin-1 / Shift-JIS read as UTF-8-with-replacement lose every accented or CJK character the model then trusts)."""
import http.server
import threading
import time

import pytest

from cria import httpread, webfetch


class Drip:
    """A response that delivers one byte per read1 and advances a fake clock by `step` each time."""
    def __init__(self, n, step):
        self.left, self.step, self.now = n, step, 0.0

    def read1(self, amt):
        if not self.left:
            return b""
        self.left -= 1
        self.now += self.step
        return b"x"


def test_a_body_that_outlasts_the_total_deadline_is_abandoned_with_what_arrived_and_a_fast_one_is_not():
    slow = Drip(1000, 1.0)
    with pytest.raises(httpread.SlowBody) as slowed:
        httpread.read_bounded(slow, 10_000, total_seconds=5, clock=lambda: slow.now)
    assert slowed.value.received == 6 and slow.left == 994                  # stopped on the first read past the deadline, not drained
    fast = Drip(1000, 0.001)
    assert httpread.read_bounded(fast, 10_000, total_seconds=5, clock=lambda: fast.now) == b"x" * 1000
    capped = Drip(50, 0.1)
    assert httpread.read_bounded(capped, 10, total_seconds=5, clock=lambda: capped.now) == b"x" * 10   # the size cap, reached in time, is no timeout


class Site(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/drip":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "40")
            self.end_headers()
            try:
                for _ in range(40):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.1)
            except OSError:
                pass
            return
        body, ctype = {"/latin": ("café crème brûlée".encode("latin-1"), "text/html; charset=iso-8859-1"),
                       "/undeclared": ("café crème brûlée".encode("latin-1"), "text/plain"),
                       "/octet": ("café crème brûlée".encode("latin-1"), "application/octet-stream"),
                       "/sjis": (b'<html><head><meta charset="shift_jis"></head><body>' + "日本語のページ".encode("shift_jis") + b"</body></html>", "text/html"),
                       "/utf8": ("café — ✓".encode(), "text/plain; charset=utf-8")}[self.path]
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_a_slow_dripping_server_is_abandoned_at_the_total_deadline_and_the_model_is_told_why(site, monkeypatch):
    """Per-read timeout is 30 s; a byte every 0.1 s never trips it. The fetch must give up at the total deadline instead of riding the whole transfer."""
    monkeypatch.setattr(httpread, "TOTAL_READ_SECONDS", 0.5)
    started = time.monotonic()
    out = webfetch.fetch_nav(site + "/drip")
    assert time.monotonic() - started < 3.0
    assert "error fetching" in out and "abandoned" in out and "bytes had arrived" in out


@pytest.mark.parametrize("path, expected", [
    ("/latin", "café crème brûlée"),            # declared charset
    ("/undeclared", "café crème brûlée"),       # not UTF-8 and undeclared: the web's default (Windows-1252), never U+FFFD
    ("/octet", "café crème brûlée"),            # the sniffed-as-text path decodes the same way
    ("/sjis", "日本語のページ"),                  # declared only by <meta charset>
    ("/utf8", "café — ✓"),
])
def test_a_body_is_decoded_with_the_charset_it_declared(site, path, expected):
    result = webfetch.fetch(site + path)
    assert expected in result.body and "\ufffd" not in result.body
