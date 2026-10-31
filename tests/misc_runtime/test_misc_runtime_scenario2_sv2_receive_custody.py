"""Receive custody against a REAL local HTTP server (stdlib only): the bytes cria acquired are on disk exactly as returned, redirects and error
bodies are owned, a failing sink or a truncated body is recorded rather than hidden, and the installed-opener / proxy / scheme policy refuses what it cannot capture."""
import hashlib
import http.client
import io
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cria import receivecapture as rc

BODY = b'{"ok": true, "pad": "' + b"x" * 300 + b'"}'


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def reply(self, code, body, headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.rsplit("/", 1)[-1]
        if path == "ok":
            self.reply(200, BODY)
        elif path == "hop":
            self.reply(302, b"", [("Location", "/ok")])
        elif path == "ftp":
            self.reply(302, b"", [("Location", "ftp://example.invalid/x")])
        elif path == "missing":
            self.reply(404, b'{"error": "nope"}')
        elif path == "cut":  # promises 100 bytes, sends 10, hangs up
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b"0123456789")
            self.close_connection = True


@pytest.fixture
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def clean_opener(monkeypatch):
    monkeypatch.setattr(urllib.request, "_opener", None)


def get(site, path, receipt, **kw):
    return rc.open_request(urllib.request.Request(site + path), timeout=10, receipt=receipt, **kw)


def meta(receipt):
    return json.loads(rc.metadata_path(receipt.base).read_text())


def test_a_delivered_response_is_on_disk_byte_for_byte_with_a_receipt_that_closes_with_the_response(tmp_path, site):
    """After reading and closing: the segment file is the exact wire (status line through body), the receipt's counts agree with the file and the body hash, and 'finished' flips only on close."""
    receipt = rc.Receipt(tmp_path / "call", request_sha256="ab" * 32)
    with get(site, "/ok", receipt) as resp:
        assert resp.read() == BODY
        assert meta(receipt)["finished"] is False
    (path,) = receipt.files()
    wire = open(path, "rb").read()
    assert wire.startswith(b"HTTP/1.1 200 OK\r\n") and wire.endswith(BODY)
    m = meta(receipt)
    (seg,) = m["segments"]
    assert m["finished"] is True and m["request_sha256"] == "ab" * 32 and receipt.failed == []
    assert seg["returned_bytes"] == seg["successful_write_bytes"] == len(wire) and seg["raw_eof"] is False and seg["close_ok"] and seg["flush_ok"]
    returns = [e for e in m["events"] if e["event"] == "receive-return"]
    cut = [0]
    for e in returns:  # each returned chunk is hashed exactly as the bytes that follow it on disk
        assert e["sha256"] == hashlib.sha256(wire[cut[-1]:cut[-1] + e["bytes"]]).hexdigest()
        cut.append(cut[-1] + e["bytes"])
    assert cut[-1] == len(wire)


def test_a_redirect_hop_gets_its_own_segment_and_the_receipt_waits_for_the_final_response(tmp_path, site):
    """GET /hop -> 302 -> /ok: two activated segments in order (each holding its own response bytes) and one finish, after the final close."""
    receipt = rc.Receipt(tmp_path / "call", request_sha256="00")
    with get(site, "/hop", receipt) as resp:
        assert resp.read() == BODY and meta(receipt)["finished"] is False
    first, second = [open(f, "rb").read() for f in receipt.files()]
    assert first.startswith(b"HTTP/1.1 302 ") and second.endswith(BODY) and len(receipt.files()) == 2
    assert [e["event"] for e in meta(receipt)["events"] if e["event"] == "activate"] == ["activate", "activate"] and meta(receipt)["finished"]


def test_an_error_response_keeps_its_body_readable_and_is_finalised_without_losing_the_error(tmp_path, site):
    """A 404 raises HTTPError whose body is still readable; finalize_http_error reports no adverse custody, and the file holds the error response."""
    receipt = rc.Receipt(tmp_path / "call", request_sha256="00")
    with pytest.raises(urllib.error.HTTPError) as err:
        get(site, "/missing", receipt)
    assert err.value.code == 404 and err.value.read() == b'{"error": "nope"}'
    assert rc.finalize_http_error(err.value, receipt) is False
    assert meta(receipt)["finished"] and open(receipt.files()[0], "rb").read().endswith(b'{"error": "nope"}')


def test_a_truncated_body_is_recorded_as_a_partial_that_is_not_a_new_acquisition(tmp_path, site):
    """The server promised 100 bytes and sent 10: IncompleteRead surfaces, the 10 bytes are on disk, and the receipt names the partial with its hash and the not_new_acquisition marker."""
    receipt = rc.Receipt(tmp_path / "call", request_sha256="00")
    resp = get(site, "/cut", receipt)
    with pytest.raises(http.client.IncompleteRead) as err:
        resp.read()
    receipt.partial(err.value)  # what the caller does with a read failure it cannot repair
    resp.close()
    assert meta(receipt)["partials"] == [{"type": "IncompleteRead", "bytes": 10, "sha256": hashlib.sha256(b"0123456789").hexdigest(), "not_new_acquisition": True}]
    assert open(receipt.files()[0], "rb").read().endswith(b"0123456789")


class Sink(io.RawIOBase):
    def __init__(self, write=None, flush_fails=False, close_fails=False):
        super().__init__()
        self.data, self._write, self.flush_fails, self.close_fails = bytearray(), write, flush_fails, close_fails

    def writable(self):
        return True

    def write(self, b):
        if self._write is not None:
            return self._write(b)
        self.data += b
        return len(b)

    def flush(self):
        if self.flush_fails:
            raise OSError("flush failed")

    def close(self):
        if self.close_fails:
            raise OSError("close failed")
        super().close()


def failing_receipt(tmp_path, **sink):
    sinks = []

    def factory(path):
        sinks.append(Sink(**sink))
        return sinks[-1] if str(path).endswith(".bin") else rc.Receipt._file(path)
    return rc.Receipt(tmp_path / "call", request_sha256="00", sink_factory=factory)


@pytest.mark.parametrize("write", [lambda b: (_ for _ in ()).throw(OSError(28, "no space left")), lambda b: 0, lambda b: len(b) + 5])
def test_a_sink_that_fails_or_lies_about_progress_stops_the_read_with_the_bytes_it_could_not_store(tmp_path, site, write):
    """Disk full, a zero write and an over-long write count are all CaptureFailure('receive custody failure'): the unstored bytes ride on the error, the failure is journaled, and every later read re-raises the SAME terminal."""
    receipt = failing_receipt(tmp_path, write=write)
    with pytest.raises(rc.CaptureFailure) as err:
        resp = get(site, "/ok", receipt)
        resp.read()
    first = err.value
    assert "receive custody failure: receive-store" in str(first) and first.receipt is receipt and first.attempted.startswith(b"HTTP/1.1 200")
    assert [f["operation"] for f in receipt.failed] == ["receive-store"]
    with pytest.raises(rc.CaptureFailure) as again:
        get(site, "/ok", receipt)
    assert again.value is first


def test_a_sink_that_cannot_flush_or_close_is_journaled_and_a_clean_response_cannot_hide_it(tmp_path, site):
    """flush failing on the first frame aborts the open with the primary store failure and the raw-flush as a secondary note; a sink whose close fails after a clean read makes closing the response raise instead of reporting success."""
    receipt = failing_receipt(tmp_path, flush_fails=True)
    with pytest.raises(rc.CaptureFailure) as err:
        get(site, "/ok", receipt)
    assert [f["operation"] for f in receipt.failed][:2] == ["receive-store", "raw-flush"]
    assert "secondary receive capture failures" in "".join(getattr(err.value, "__notes__", []))
    (tmp_path / "b").mkdir()
    receipt = failing_receipt(tmp_path / "b", close_fails=True)
    resp = get(site, "/ok", receipt)
    assert resp.read() == BODY
    with pytest.raises(rc.CaptureFailure, match="finalization failed"):
        resp.close()
    assert [f["operation"] for f in receipt.failed] == ["raw-close"]


def test_unsafe_requests_are_refused_before_any_byte_is_taken(tmp_path, site, monkeypatch):
    """A redirect to FTP, an admit() refusal, a bound handler and an installed opener are each an error that finishes the receipt with no bytes written."""
    cases = [
        ("/ftp", {}, "HTTP/HTTPS only"),
        ("/ok", {"admit": lambda request: (_ for _ in ()).throw(PermissionError("denied by policy"))}, "denied by policy"),
        ("/ok", {"handlers": (urllib.request.HTTPCookieProcessor(),)}, None),
    ]
    bound = urllib.request.HTTPRedirectHandler()
    bound.parent = object()
    cases.append(("/ok", {"handlers": (bound,)}, "bound handler"))
    for n, (path, kw, message) in enumerate(cases):
        receipt = rc.Receipt(tmp_path / f"c{n}", request_sha256="00")
        if message is None:
            get(site, path, receipt, **kw).close()
            continue
        with pytest.raises((ValueError, PermissionError, urllib.error.URLError)) as err:
            get(site, path, receipt, **kw)
        assert message in str(err.value) and meta(receipt)["finished"] is True
    receipt = rc.Receipt(tmp_path / "installed", request_sha256="00")
    urllib.request.install_opener(urllib.request.build_opener())
    with pytest.raises(ValueError, match="installed opener requires an explicit compatible"):
        rc.default_open_request(urllib.request.Request(site + "/ok"), timeout=5, receipt=receipt)
    assert meta(receipt)["finished"] is True and receipt.files() == []
    with pytest.raises(ValueError, match="installed opener"):
        rc.default_open_request(urllib.request.Request(site + "/ok"), timeout=5)


def test_an_observe_hook_that_fails_aborts_the_response_and_a_failing_close_is_noted_on_it(tmp_path, site):
    """observe_response raising stops the open with that error (the response is closed, nothing delivered)."""
    seen = []
    def observe(request, response):
        seen.append(response.status)
        raise RuntimeError("observer says no")
    receipt = rc.Receipt(tmp_path / "call", request_sha256="00")
    with pytest.raises(RuntimeError, match="observer says no"):
        get(site, "/ok", receipt, observe_response=observe)
    assert seen == [200] and meta(receipt)["finished"] is True


def test_the_default_transport_reuses_only_the_cache_it_built_and_honours_its_proxy_but_not_a_changed_policy(tmp_path, site, monkeypatch):
    """After an ordinary open the owner admits captured dispatch (keeping the env-configured proxy: the request goes to the PROXY with an absolute URI); once the cache policy is changed, captured dispatch is refused as an installed opener."""
    monkeypatch.setenv("http_proxy", site)
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.delenv("NO_PROXY", raising=False)
    transport = rc.DefaultTransport()
    req = lambda: urllib.request.Request("http://upstream.invalid:9/ok")
    assert transport.ordinary(req(), timeout=10).read() == BODY      # the stdlib default opener, via the proxy
    receipt = rc.Receipt(tmp_path / "call", request_sha256="00")
    with transport(req(), timeout=10, receipt=receipt) as resp:
        assert resp.read() == BODY
    assert open(receipt.files()[0], "rb").read().endswith(BODY)
    with pytest.raises(urllib.error.HTTPError) as err:
        transport.ordinary(urllib.request.Request("http://upstream.invalid:9/missing"), timeout=10)
    assert err.value.code == 404
    urllib.request._opener.addheaders.append(("X-Changed", "1"))      # the installed policy moved under us
    with pytest.raises(ValueError, match="installed opener"):
        transport(req(), timeout=10, receipt=rc.Receipt(tmp_path / "late", request_sha256="00"))
