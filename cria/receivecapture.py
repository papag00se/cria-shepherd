"""Request-local HTTP receive custody, below buffering. No decoder or extra reads.

Bounded default urllib opener policy, not arbitrary installed-opener compatibility.
Redirect policy is injectable; CLOSED validation supplies denial, production does not.
"""
from __future__ import annotations
import hashlib
import http.client
import io
import json
import os
import sys
import urllib.request
from pathlib import Path


class CaptureFailure(OSError):
    """Already received data could not be truthfully retained."""


def metadata_path(capture_path) -> Path:
    """The transport receipt is a companion of the request, never another request."""
    return Path(str(capture_path) + '.receive.json')


class Receipt:
    def __init__(self, capture_path, *, request_sha256, sink_factory=None):
        self.base = Path(capture_path)
        self.request_sha256 = request_sha256
        self.sink_factory = sink_factory or self._file
        self.segments = []
        self.activated = []
        self.events = []
        self.failed = []
        self.partials = []
        self.on_proxy_headers = None
        self.finished = False
        # Intermediate redirect responses own segments, not the whole opening attempt.
        self.opening = 0
        self.terminal = None
        self.meta_path = metadata_path(self.base)
        self.meta = self._file(self.meta_path)
        try:
            self.origin = self._segment('origin')  # storage setup BEFORE dispatch
            self.sync()
        except BaseException:
            for s in self.segments:
                s.close()
            self.meta.close()
            raise

    @staticmethod
    def _file(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        return io.FileIO(fd, 'wb', closefd=True)

    def _segment(self, phase):
        path = Path(str(self.base) + f'.receive-{len(self.segments)+1:04d}-{phase}.bin')
        s = Segment(self, phase, path, self.sink_factory(path))
        self.segments.append(s)
        return s

    def activate(self, phase):
        s = self.origin if phase == 'origin' and self.origin not in self.activated else self._segment(phase)
        self.activated.append(s)
        self.events.append({'event': 'activate', 'phase': phase, 'file': str(s.path)})
        self.sync()
        return s

    def failure(self, operation, error):
        self.failed.append({'operation': operation, 'type': type(error).__name__, 'error': str(error)})
        if self.terminal is None:
            self.terminal = CaptureFailure('receive custody failure: ' + operation)
            self.terminal.__cause__ = error
            self.terminal.receipt = self
        return self.terminal

    def sync(self):
        data = json.dumps({'request_sha256': self.request_sha256, 'boundary': 'application SocketIO returned bytes, not TLS cipher or decoded body',
                           'events': self.events, 'failed': self.failed, 'partials': self.partials,
                           'segments': [s.state() for s in self.segments], 'finished': self.finished}, indent=2).encode()
        self.meta.seek(0)
        self.meta.truncate()
        offset = 0
        while offset < len(data):
            n = self.meta.write(data[offset:])
            if not n:
                raise CaptureFailure('receive metadata write made no progress')
            offset += n
        self.meta.flush()

    def partial(self, exc):
        seen = set()
        def visit(e):
            if e is None or id(e) in seen:
                return
            seen.add(id(e))
            if isinstance(getattr(e, 'partial', None), bytes):
                self.partials.append({'type': type(e).__name__, 'bytes': len(e.partial), 'sha256': hashlib.sha256(e.partial).hexdigest(), 'not_new_acquisition': True})
            visit(e.__cause__)
            visit(e.__context__)
        visit(exc)
        if not self.finished:
            try:
                self.sync()
            except BaseException as e:
                self.failure('partial-metadata', e)
                exc.add_note('receive partial metadata could not be stored: ' + str(e))

    def files(self):
        return [str(s.path) for s in self.activated]

    def finish(self, primary=None):
        if self.finished:
            return
        for s in self.segments:
            s.close()
        self.finished = True
        try:
            self.sync()
        except BaseException as e:
            self.failure('final-metadata', e)
        try:
            self.meta.close()
        except BaseException as e:
            self.failure('metadata-close', e)
        if primary is not None and self.failed:
            primary.add_note('secondary receive capture failures: ' + repr(self.failed))


class Segment:
    def __init__(self, receipt, phase, path, sink):
        self.receipt, self.phase, self.path, self.sink = receipt, phase, path, sink
        self.returned = self.stored = 0
        self.closed = False
        self.eof = False
        self.flush_ok = self.close_ok = False

    def state(self):
        return {'phase': self.phase, 'file': str(self.path), 'returned_bytes': self.returned,
                'successful_write_bytes': self.stored, 'raw_eof': self.eof,
                'closed': self.closed, 'flush_ok': self.flush_ok, 'close_ok': self.close_ok}

    def record(self, data):
        self.returned += len(data)
        r = self.receipt
        r.events.append({'event': 'receive-return', 'phase': self.phase, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        offset = 0
        try:
            while offset < len(data):
                r.events.append({'event': 'write-attempt', 'file': str(self.path), 'offset': self.stored, 'bytes': len(data)-offset})
                n = self.sink.write(data[offset:])
                if n is None or n <= 0 or n > len(data)-offset:
                    raise CaptureFailure('receive write made invalid progress')
                self.stored += n
                offset += n
                r.events.append({'event': 'write-success', 'file': str(self.path), 'bytes': n})
            self.sink.flush()
            self.flush_ok = True
            r.events.append({'event': 'flush-success', 'file': str(self.path)})
            r.sync()
        except BaseException as e:
            failure = r.failure('receive-store', e)
            failure.attempted = data
            raise failure from e

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.sink.flush()
            self.flush_ok = True
        except BaseException as e:
            self.receipt.failure('raw-flush', e)
        finally:
            try:
                self.sink.close()
                self.close_ok = True
            except BaseException as e:
                self.receipt.failure('raw-close', e)


class RecordingRaw(io.RawIOBase):
    def __init__(self, raw, segment):
        self.raw, self.segment = raw, segment
        super().__init__()

    def readable(self):
        return True

    def fileno(self):
        return self.raw.fileno()

    def readinto(self, buffer):
        if self.segment.receipt.terminal is not None:
            raise self.segment.receipt.terminal
        try:
            n = self.raw.readinto(buffer)
        except BaseException as e:
            self.segment.receipt.partial(e)
            raise
        if n:
            self.segment.record(bytes(memoryview(buffer)[:n]))
        elif n == 0:
            self.segment.eof = True
        return n

    def close(self):
        if self.closed:
            return
        try:
            self.raw.close()
        finally:
            self.segment.close()
            super().close()


class ResponseSocket:
    def __init__(self, sock, segment, buffer_size):
        self.sock, self.segment, self.buffer_size = sock, segment, buffer_size

    def makefile(self, mode):
        if mode != 'rb':
            raise ValueError('HTTP receive facade supports the actual rb response mode only')
        raw = self.sock.makefile(mode, buffering=0)
        try:
            recorder = RecordingRaw(raw, self.segment)
            return io.BufferedReader(recorder, self.buffer_size)
        except BaseException:
            raw.close()
            self.segment.close()
            raise


class CapturedResponse(http.client.HTTPResponse):
    def close(self):
        primary = sys.exception()
        try:
            super().close()
        finally:
            txn = self.receive_transaction
            if self.receive_phase == 'origin' and not txn.opening:
                txn.finish(primary)
            if txn.failed:
                if primary is not None:
                    primary.add_note('receive capture cleanup failed: ' + repr(txn.failed))
                else:
                    raise CaptureFailure('receive capture finalization failed: ' + repr(txn.failed))


def finalize_http_error(error, receipt=None):
    """Release the actual error response/receipt, without replacing its primary identity.

    Return adverse custody explicitly, so a caller cannot refit or acknowledge a failed store.
    No error-body read belongs here: the caller owns its single-read evidence/translation.
    """
    receipt = receipt or getattr(error, 'receive_transaction', None)
    failed = False
    if receipt is not None:
        receipt.partial(error)
    try:
        error.close()
    except BaseException as secondary:
        failed = True
        error.add_note('secondary HTTP error close: ' + str(secondary))
        if receipt is not None:
            receipt.failure('HTTPError-close', secondary)
    finally:
        if receipt is not None:
            receipt.finish(error)
    return failed or bool(receipt is not None and receipt.failed)


def response_factory(receipt, *, buffer_size=io.DEFAULT_BUFFER_SIZE, phase=lambda: 'origin'):
    def construct(sock, debuglevel=0, method=None, url=None):
        segment = receipt.activate(phase())
        response = CapturedResponse.__new__(CapturedResponse)
        response.fp = None  # construction can fail before HTTPResponse assigns fp
        response.receive_transaction = receipt
        response.receive_phase = segment.phase
        try:
            http.client.HTTPResponse.__init__(response, ResponseSocket(sock, segment, buffer_size), debuglevel, method, url)
        except BaseException:
            segment.close()
            raise
        return response
    return construct


class DefaultTransport:
    """One owner for ordinary preparation and request-local captured dispatch.

    Only a cache created by this owner's ordinary stdlib opening is admitted.
    An already installed or subsequently replaced policy is not inferred compatible.
    Shared and secondary endpoints must share this owner, not just its callable.
    """
    def __init__(self):
        self._default_cache = None
        self._default_policy = None

    @staticmethod
    def _policy(cache):
        # Snapshot only stdlib director/handler configuration, not response history.
        # Copy containers, never handlers/parents or opaque TLS objects.
        state = dict(vars(cache))
        state['handlers'] = tuple((h, {k: v.copy() if isinstance(v, dict) else v
                                      for k, v in vars(h).items()}) for h in cache.handlers)
        state['addheaders'] = tuple(cache.addheaders)
        for field in ('handle_open', 'process_request', 'process_response'):
            state[field] = {k: tuple(v) for k, v in getattr(cache, field).items()}
        state['handle_error'] = {k: {code: tuple(v) for code, v in routes.items()}
                                 for k, routes in cache.handle_error.items()}
        return state

    def ordinary(self, req, *, timeout):
        before = urllib.request._opener
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as error:
            finalize_http_error(error)
            raise
        finally:
            # urlopen builds its default cache before opening, even on failure.
            # Never adopt a preinstalled policy merely because it returned a response.
            cache = urllib.request._opener
            if before is None and type(cache) is urllib.request.OpenerDirector:
                self._default_cache = cache
                self._default_policy = self._policy(cache)

    def __call__(self, req, *, timeout, receipt=None):
        cache = self._default_cache
        if cache is not None and self._policy(cache) != self._default_policy:
            cache = None  # installed policy was changed; explicit compatibility required
        return default_open_request(req, timeout=timeout, receipt=receipt,
                                    _default_cache=cache)


def default_open_request(req, *, timeout, receipt=None, _default_cache=None):
    """Default policy; only its ordinary owner's cache may coexist with capture.

    Custom installed policies still require an explicit compatible local owner.
    No cache is cleared, modified, cloned or used as a source of bound handlers.
    """
    if urllib.request._opener is not None and urllib.request._opener is not _default_cache:
        error = ValueError('installed opener requires an explicit compatible request-local owner')
        if receipt is not None:
            receipt.partial(error)
            receipt.finish(error)
        raise error
    if _default_cache is not None:
        proxy = next((h for h in _default_cache.handlers
                      if type(h) is urllib.request.ProxyHandler), None)
        # Ordinary urllib retains this construction-time configuration, including
        # an empty mapping. Reconstruct only the plain built-in proxy handler;
        # never transfer a bound handler or rediscover ambient proxy routing.
        # ProxyHandler keeps stdlib's request-time bypass behavior unchanged.
        proxies = dict(proxy.proxies) if proxy is not None else {}
        return open_request(req, timeout=timeout, receipt=receipt,
                            handlers=(urllib.request.ProxyHandler(proxies),))
    return open_request(req, timeout=timeout, receipt=receipt)


def open_request(req, *, timeout, receipt=None, handlers=(), buffer_size=io.DEFAULT_BUFFER_SIZE,
                 http_connection=http.client.HTTPConnection, https_connection=http.client.HTTPSConnection,
                 admit=None, observe_response=None):
    def connection(base):
        class Owned(base):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.receive_phase = 'origin'
                if receipt is not None:
                    self.response_class = response_factory(receipt, buffer_size=buffer_size, phase=lambda: self.receive_phase)

            def _tunnel(self):
                self.receive_phase = 'proxy-CONNECT'
                try:
                    super()._tunnel()
                    if receipt is not None and receipt.on_proxy_headers is not None:
                        getter = getattr(self, 'get_proxy_response_headers', None)
                        headers = getter() if callable(getter) else None
                        receipt.on_proxy_headers(dict(headers.items()) if headers is not None else None)
                finally:
                    self.receive_phase = 'origin'
        return Owned

    class HTTP(urllib.request.HTTPHandler):
        def http_open(self, request):
            return self.do_open(connection(http_connection), request)

    class HTTPS(urllib.request.HTTPSHandler):
        def https_open(self, request):
            return self.do_open(connection(https_connection), request, context=self._context)

    class Policy(urllib.request.BaseHandler):
        # default_open is the common pre-transport hook, including nested redirects.
        # Protocol-specific request processors would miss a redirect to FTP/file.
        handler_order = 0

        def default_open(self, request):
            if receipt is not None and receipt.terminal is not None:
                raise receipt.terminal
            if admit is not None:
                admit(request)
            if request.type not in ('http', 'https'):
                raise ValueError('receive custody supports request-local HTTP/HTTPS only')
            return None

        def http_response(self, request, response):
            try:
                if observe_response is not None:
                    observe_response(request, response)
                return response
            except BaseException as primary:
                try:
                    response.close()
                except BaseException as secondary:
                    primary.add_note('secondary policy response close: ' + str(secondary))
                    if receipt is not None:
                        receipt.failure('policy-response-close', secondary)
                raise

        https_response = http_response

    if receipt is not None:
        receipt.opening += 1
    try:
        if any(not isinstance(h, type) and getattr(h, 'parent', None) is not None for h in handlers):
            raise ValueError('bound handler cannot be moved into a request-local opener')
        opener = urllib.request.build_opener(HTTP(), HTTPS(), Policy(), *handlers)
        response = opener.open(req, timeout=timeout)
        if receipt is not None:
            response.receive_transaction = receipt
        return response
    except BaseException as e:
        if receipt is not None:
            receipt.partial(e)
            # HTTPError owns a still-readable response; caller retains that ownership.
            if not isinstance(e, urllib.error.HTTPError):
                receipt.finish(e)
        raise
    finally:
        if receipt is not None:
            receipt.opening -= 1
