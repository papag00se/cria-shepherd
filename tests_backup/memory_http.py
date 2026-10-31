"""Declared request-local HTTP owner over labelled memory IO, never global urllib policy.

Only the lower connection is supplied. urllib, HTTPResponse, SocketIO and the receiving
recorder run normally, including HTTP errors, buffering and finalization. Inbound requests
also run the real BaseHTTPRequestHandler, not a response/conversion adapter.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import http.client
import json
from pathlib import Path
import types
import urllib.error
import urllib.request
from unittest.mock import patch

from cria import receivecapture
from cria.server import CriaServer
from receiving.fixtures import FakeSocket, Lower, wire


@dataclass
class Reply:
    wire: bytes
    steps: list | None = None
    connect_error: OSError | None = None
    before_interrupt: object = None


def reply(body=b"", status=200, headers=b""):
    return Reply(wire(body, status, headers))


def json_reply(value, status=200):
    return reply(json.dumps(value).encode(), status, b"Content-Type: application/json\r\n")


def stream_reply(lines, *, interrupt_at=None, interruption=None, before_interrupt=None):
    headers = b"HTTP/1.1 200 Fixture\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n"
    # One lower return per complete supplied frame. This prevents read-ahead from
    # moving the intended interruption ahead of reasoning that already arrived.
    steps = [len(headers)] + [len(line) for line in lines]
    if interrupt_at is not None:
        assert interruption is not None
        steps = steps[:1 + interrupt_at] + [interruption]
    return Reply(headers + b"".join(lines), steps, before_interrupt=before_interrupt)


class MemoryTransport:
    """Explicit compatible owner shared by ordinary prep and captured dispatch."""
    def __init__(self, respond=None):
        self.respond = respond
        self.calls = []
        self.lowers = []
        self.receipts = []
        self.interruptions = []

    @contextmanager
    def respond_with(self, respond):
        previous = self.respond
        self.respond = respond
        try:
            yield self
        finally:
            self.respond = previous
            self.assert_closed()

    def ordinary(self, req, *, timeout):
        try:
            return self(req, timeout=timeout)
        except urllib.error.HTTPError as error:
            receivecapture.finalize_http_error(error)
            raise

    def __call__(self, req, *, timeout, receipt=None):
        assert req.type == "http" and req.host.endswith(".invalid"), req.full_url
        assert self.respond is not None, "memory transport needs a declared responder"
        supplied = self.respond(req)
        assert isinstance(supplied, Reply), "responder supplies wire bytes, not a response adapter"
        lower = Lower([supplied.wire], [supplied.steps] if supplied.steps is not None else None)
        sock = lower.sockets[0]
        recv = sock.recv_into
        def receive(buffer):
            if sock.steps and isinstance(sock.steps[0], BaseException):
                error = sock.steps.pop(0)
                self.interruptions.append(error)
                if supplied.before_interrupt is not None:
                    supplied.before_interrupt(error)
                raise error
            return recv(buffer)
        sock.recv_into = receive
        if supplied.connect_error is not None:
            def failed_connect(index):
                lower.connects.append(index)
                raise supplied.connect_error
            lower.connect = failed_connect
        self.calls.append(req)
        self.lowers.append(lower)
        if receipt is not None:
            self.receipts.append((receipt, lower))
        return receivecapture.open_request(req, timeout=timeout, receipt=receipt,
                                          http_connection=lower.HTTP,
                                          handlers=(urllib.request.ProxyHandler({}),))

    def assert_served(self):
        chats = [lower for req, lower in zip(self.calls, self.lowers)
                 if req.full_url.endswith("/v1/chat/completions")]
        assert chats, "the chat transport was never entered"
        assert any(sock.raws and sock.returned for lower in chats for sock in lower.sockets), \
            "the real chat reader was never entered"
        self.assert_closed()

    def assert_closed(self):
        for req, lower in zip(self.calls, self.lowers):
            lower.assert_closed()
            sent = b"".join(lower.sockets[0].sent)
            if sent:  # a declared connect failure has no sent request
                headers, body = sent.split(b"\r\n\r\n", 1)
                assert headers.split(b"\r\n", 1)[0] == f"{req.get_method()} {req.selector} HTTP/1.1".encode()
                assert body == (req.data or b"")
        for receipt, lower in self.receipts:
            assert receipt.finished and receipt.meta.closed
            acquired = b"".join(sock.acquired() for sock in lower.sockets)
            assert b"".join(Path(path).read_bytes() for path in receipt.files()) == acquired


def handler_reply(handler, server, req):
    """Run the real incoming HTTP parser against exact supplied request bytes."""
    data = req.data or b""
    fields = dict(req.header_items())
    fields["Content-Length"] = str(len(data))
    incoming = (f"{req.get_method()} {req.selector} HTTP/1.0\r\n" +
                "".join(f"{key}: {value}\r\n" for key, value in fields.items()) + "\r\n").encode() + data
    sock = FakeSocket(incoming)
    handler(sock, ("fixture.invalid", 0), server)
    assert sock._io_refs == 0 and all(raw.closed for raw in sock.raws)
    return Reply(b"".join(sock.sent))


def handler_open(handler, server, req, *, timeout=None):
    """External client: actual HTTPResponse/SocketIO, no public urllib cache."""
    supplied = handler_reply(handler, server, req)
    sock = FakeSocket(supplied.wire)
    response = http.client.HTTPResponse(sock)
    response.begin()
    if response.status >= 400:
        raise urllib.error.HTTPError(req.full_url, response.status, response.reason,
                                     response.headers, response)
    return response


def memory_server(cfg, log, upstream):
    # Only server socket allocation is absent; CriaServer construction is unchanged.
    from http.server import ThreadingHTTPServer
    with patch.object(ThreadingHTTPServer, "__init__", return_value=None):
        return CriaServer(cfg, log, upstream)


def backend(handler):
    server = types.SimpleNamespace(request_bodies=[])
    owner = MemoryTransport(lambda req: handler_reply(handler, server, req))
    return server, owner
