"""Receive custody over TLS and through a CONNECT proxy, against local servers (stdlib `ssl`, a throwaway cert from `openssl`), plus the
storage-fault arms of the receipt itself: an HTTPS reply is recorded as the bytes the application socket returned, a CONNECT tunnel's
own reply is a separate 'proxy-CONNECT' segment activated ahead of the origin's, a refused tunnel fails the open with the proxy's answer on disk,
and a receipt whose metadata file cannot be written says so instead of reporting a clean capture."""
import http.client
import json
import shutil
import socket
import ssl
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cria import receivecapture as rc

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl CLI for a throwaway certificate")
BODY = b'{"secure": true, "pad": "' + b"y" * 200 + b'"}'


class Origin(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    log_message = lambda *a: None

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)


@pytest.fixture(scope="module")
def cert(tmp_path_factory):
    d = tmp_path_factory.mktemp("tls")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-days", "2",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
                    "-keyout", str(d / "k.pem"), "-out", str(d / "c.pem")], check=True, capture_output=True)
    return d / "c.pem", d / "k.pem"


@pytest.fixture
def https_site(cert, monkeypatch):
    """An HTTPS origin that the default client context trusts (SSL_CERT_FILE names the throwaway cert)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(*map(str, cert))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    monkeypatch.setenv("SSL_CERT_FILE", str(cert[0]))
    monkeypatch.setattr(urllib.request, "_opener", None)
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


@pytest.fixture
def connect_proxy():
    """A CONNECT proxy: answers `status` to the tunnel request, and on 200 splices the client to the requested host:port."""
    seen = []
    state = {"status": 200}
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)

    def pump(a, b):
        try:
            while chunk := a.recv(4096):
                b.sendall(chunk)
        except OSError:
            pass
        finally:
            for s in (a, b):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def serve():
        while True:
            try:
                client, _ = listener.accept()
            except OSError:
                return
            head = b""
            while b"\r\n\r\n" not in head:
                head += client.recv(1024)
            line = head.split(b"\r\n")[0].decode()
            seen.append(line)
            if state["status"] != 200:
                client.sendall(f"HTTP/1.1 {state['status']} Nope\r\nContent-Length: 0\r\nX-Proxy: refused\r\n\r\n".encode())
                client.close()
                continue
            host, port = line.split()[1].rsplit(":", 1)
            upstream = socket.create_connection((host, int(port)))
            client.sendall(b"HTTP/1.1 200 Connection established\r\nX-Proxy: yes\r\n\r\n")
            for a, b in ((client, upstream), (upstream, client)):
                threading.Thread(target=pump, args=(a, b), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    yield type("Proxy", (), {"url": f"http://127.0.0.1:{listener.getsockname()[1]}", "seen": seen, "state": state})
    listener.close()


def meta(receipt):
    return json.loads(rc.metadata_path(receipt.base).read_text())


@pytest.mark.parametrize("with_receipt", [True, False])
def test_an_https_reply_is_recorded_as_the_bytes_the_application_socket_returned(tmp_path, https_site, with_receipt):
    """Direct HTTPS: the segment is the plaintext HTTP reply (status line to body, not TLS records) and the receipt says so; the same open
    works with no receipt at all (no capture, no custody failure)."""
    receipt = rc.Receipt(tmp_path / "c", request_sha256="00") if with_receipt else None
    with rc.open_request(urllib.request.Request(f"https://localhost:{https_site}/x"), timeout=10, receipt=receipt) as resp:
        assert resp.read() == BODY
    if receipt is not None:
        wire = open(receipt.files()[0], "rb").read()
        assert wire.startswith(b"HTTP/1.1 200 OK\r\n") and wire.endswith(BODY) and "not TLS cipher" in meta(receipt)["boundary"]
        assert meta(receipt)["finished"] is True and [s["phase"] for s in meta(receipt)["segments"]] == ["origin"]


def test_a_connect_tunnel_has_its_own_segment_and_its_reply_headers_reach_the_observer(tmp_path, https_site, connect_proxy):
    """https via an HTTP proxy: the proxy's `200 Connection established` is the first activated segment (phase proxy-CONNECT), the origin's reply the second, the
    observer gets the proxy's headers, and the proxy saw CONNECT for the origin's host:port only."""
    receipt = rc.Receipt(tmp_path / "c", request_sha256="00")
    heads = []
    receipt.on_proxy_headers = heads.append
    handlers = (urllib.request.ProxyHandler({"https": connect_proxy.url}),)
    with rc.open_request(urllib.request.Request(f"https://localhost:{https_site}/x"), timeout=10, receipt=receipt, handlers=handlers) as resp:
        assert resp.read() == BODY
    assert connect_proxy.seen == [f"CONNECT localhost:{https_site} HTTP/1.1"]
    assert len(heads) == 1 and heads[0]["X-Proxy"] == "yes"
    assert [e["phase"] for e in meta(receipt)["events"] if e["event"] == "activate"] == ["proxy-CONNECT", "origin"]   # the origin's file was reserved first, used second
    first, second = [open(f, "rb").read() for f in receipt.files()]
    assert first.startswith(b"HTTP/1.1 200 Connection established") and second.endswith(BODY)


def test_a_refused_tunnel_fails_the_open_with_the_proxys_answer_on_disk_and_the_receipt_finished(tmp_path, https_site, connect_proxy):
    """A 403 to CONNECT: the open raises (no response to read), the proxy's reply is the one recorded segment, and a receipt with no
    observer does not call one."""
    connect_proxy.state["status"] = 403
    receipt = rc.Receipt(tmp_path / "c", request_sha256="00")
    handlers = (urllib.request.ProxyHandler({"https": connect_proxy.url}),)
    with pytest.raises(OSError, match="Tunnel connection failed: 403"):
        rc.open_request(urllib.request.Request(f"https://localhost:{https_site}/x"), timeout=10, receipt=receipt, handlers=handlers)
    m = meta(receipt)
    assert m["finished"] is True and [e["phase"] for e in m["events"] if e["event"] == "activate"] == ["proxy-CONNECT"]
    assert b"403 Nope" in open(receipt.files()[0], "rb").read() and b"X-Proxy: refused" in open(receipt.files()[0], "rb").read()


class Meta:
    """A metadata file whose writes/closes misbehave."""
    def __init__(self, write=lambda b: len(b), close=None):
        self.write, self._close = write, close

    def seek(self, n): pass
    def truncate(self): pass
    def flush(self): pass

    def close(self):
        if self._close:
            raise self._close


def test_a_receipt_that_cannot_store_its_metadata_says_so_at_every_point_it_is_written(tmp_path):
    """No-progress metadata write, a failed partial-metadata write, and a failed final write / close are each journaled (operation named),
    the partial's error carries a note, and the primary error of a failed finish carries the secondary failures."""
    r = rc.Receipt(tmp_path / "a", request_sha256="00")
    r.meta = Meta(write=lambda b: 0)
    with pytest.raises(rc.CaptureFailure, match="made no progress"):
        r.sync()
    boom = RuntimeError("read cut")
    boom.partial = b"abc"
    r.partial(boom)                                           # sync inside partial fails too: noted, not raised
    assert [f["operation"] for f in r.failed] == ["partial-metadata"] and "could not be stored" in boom.__notes__[0]
    assert r.partials[0]["bytes"] == 3 and isinstance(r.terminal, rc.CaptureFailure)
    primary = RuntimeError("primary")
    r.meta = Meta(write=lambda b: 0, close=OSError("close failed"))
    r.finish(primary)
    assert [f["operation"] for f in r.failed][1:] == ["final-metadata", "metadata-close"] and "secondary receive capture failures" in primary.__notes__[0]
    assert r.finished and r.files() == []
    r.finish(primary)                                         # idempotent
    assert len(primary.__notes__) == 1


def test_a_receipt_whose_first_metadata_sync_fails_closes_everything_it_opened(tmp_path, monkeypatch):
    """Storage setup happens BEFORE dispatch: if the opening sync fails, the origin sink and the metadata file are closed, not leaked."""
    opened = []
    real = rc.Receipt._file
    monkeypatch.setattr(rc.Receipt, "_file", staticmethod(lambda path: opened.append(real(path)) or opened[-1]))
    monkeypatch.setattr(rc.Receipt, "sync", lambda self: (_ for _ in ()).throw(OSError("disk gone")))
    with pytest.raises(OSError, match="disk gone"):
        rc.Receipt(tmp_path / "a", request_sha256="00")
    assert len(opened) == 2 and all(f.closed for f in opened)


def test_finalizing_an_error_response_whose_close_fails_reports_adverse_custody(tmp_path):
    """The caller must not acknowledge a failed store: close() raising is journaled, noted on the error and returned as True."""
    class Err(Exception):
        def close(self):
            raise OSError("socket close failed")
    receipt = rc.Receipt(tmp_path / "a", request_sha256="00")
    err = Err("http error")
    assert rc.finalize_http_error(err, receipt) is True
    assert [f["operation"] for f in receipt.failed] == ["HTTPError-close"] and "socket close failed" in err.__notes__[0] and receipt.finished
    assert rc.finalize_http_error(Err("no receipt")) is True              # with no receipt the close failure alone is adverse


def test_the_response_socket_refuses_a_non_rb_mode_and_a_construction_failure_closes_its_segment(tmp_path):
    """HTTPResponse only ever asks for 'rb'; anything else is a refusal, a wrapper that cannot be built releases its raw and segment, and a response that
    cannot be constructed leaves no open sink behind."""
    receipt = rc.Receipt(tmp_path / "a", request_sha256="00")
    segment = receipt.activate("origin")

    class Sock:
        def makefile(self, mode, buffering=None):
            raise OSError("no fp")
    facade = rc.ResponseSocket(Sock(), segment, 64)
    with pytest.raises(ValueError, match="actual rb response mode only"):
        facade.makefile("r")
    closed = []
    live = type("Live", (), {"makefile": lambda self, mode, buffering=None: type("R", (), {"close": lambda r: closed.append(1)})()})()
    with pytest.raises(ValueError, match="buffer size"):          # the buffered wrapper cannot be built: the raw and the segment are released
        rc.ResponseSocket(live, segment, 0).makefile("rb")
    assert closed and segment.closed
    receipt2 = rc.Receipt(tmp_path / "b", request_sha256="00")
    with pytest.raises(OSError, match="no fp"):
        rc.response_factory(receipt2, buffer_size=64)(Sock(), 0, "GET", "http://x/")
    assert receipt2.segments[0].closed is True


def test_a_failing_raw_read_is_recorded_as_a_partial_and_a_failed_policy_close_is_journaled(tmp_path, monkeypatch):
    """readinto raising is journaled as a partial (its bytes hashed) and re-raised; observe_response failing AND the close failing leaves
    the observer's error as primary and the close error as its note plus a journal entry."""
    receipt = rc.Receipt(tmp_path / "a", request_sha256="00")
    segment = receipt.activate("origin")

    class Raw:
        def readinto(self, buf):
            e = http.client.IncompleteRead(b"xyz")
            raise e
        def close(self): pass
    recorder = rc.RecordingRaw(Raw(), segment)
    with pytest.raises(http.client.IncompleteRead):
        recorder.readinto(bytearray(8))
    assert receipt.partials[0]["bytes"] == 3

    class Origin2(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        log_message = lambda *a: None
        def do_GET(self):
            self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"ok")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Origin2)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    monkeypatch.setattr(urllib.request, "_opener", None)

    def observe(request, response):
        monkeypatch.setattr(http.client.HTTPResponse, "close", lambda self: (_ for _ in ()).throw(OSError("close boom")))
        raise RuntimeError("observer says no")
    receipt = rc.Receipt(tmp_path / "b", request_sha256="00")
    try:
        with pytest.raises(RuntimeError, match="observer says no") as err:
            rc.open_request(urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/"), timeout=5, receipt=receipt, observe_response=observe)
    finally:
        server.shutdown(); server.server_close()
    assert "close boom" in "".join(err.value.__notes__) and "policy-response-close" in [f["operation"] for f in receipt.failed]


def test_a_recording_reader_reports_eof_only_for_a_zero_read_and_refuses_reads_after_a_custody_failure(tmp_path):
    """None (nothing ready) is not EOF, 0 is; a receipt that already failed re-raises its terminal on the next read instead of returning
    unstored bytes; close is idempotent and fileno is the raw's. An error with no receipt is closed and reports clean custody."""
    receipt = rc.Receipt(tmp_path / "a", request_sha256="00")
    segment = receipt.activate("origin")
    replies = iter([None, 0])
    closes = []

    class Raw:
        fileno = lambda self: 42
        readinto = lambda self, buf: next(replies)
        close = lambda self: closes.append(1)
    reader = rc.RecordingRaw(Raw(), segment)
    assert reader.readable() and reader.fileno() == 42
    assert reader.readinto(bytearray(4)) is None and segment.eof is False
    assert reader.readinto(bytearray(4)) == 0 and segment.eof is True
    receipt.failure("receive-store", OSError("full"))
    with pytest.raises(rc.CaptureFailure) as err:
        reader.readinto(bytearray(4))
    assert err.value is receipt.terminal
    reader.close()
    reader.close()
    assert closes == [1] and segment.closed
    closed = []
    assert rc.finalize_http_error(type("E", (), {"close": lambda self: closed.append(1)})()) is False and closed == [1]
