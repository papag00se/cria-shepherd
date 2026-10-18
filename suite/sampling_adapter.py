"""Per-cell checkpoint admission and optional source sampling; never authors task content."""
from __future__ import annotations
import email.utils
import fcntl
import http.client
import json
import math
import re
import threading
import time
from contextlib import contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

KNOBS = {'temperature', 'top_p', 'top_k', 'min_p', 'repeat_penalty',
         'presence_penalty', 'frequency_penalty'}
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'host', 'content-length'}


def validate_knobs(knobs):
    if not isinstance(knobs, dict) or not knobs or not set(knobs) <= KNOBS:
        raise ValueError('only explicit source numeric sampling knobs are allowed')
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in knobs.values()):
        raise ValueError('sampling values must be finite numbers')
    return dict(knobs)


def inject_sampling(raw: bytes, knobs: dict) -> bytes:
    knobs = validate_knobs(knobs)
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise ValueError('request body must be a JSON object')
    return json.dumps({**body, **knobs}, ensure_ascii=False, allow_nan=False).encode()


def _seconds(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        parts = re.findall(r'(\d+(?:\.\d+)?)(ms|s|m|h)', str(value))
        if parts and ''.join(n+u for n,u in parts) == str(value):
            return sum(float(n)*{'ms':.001,'s':1,'m':60,'h':3600}[u] for n,u in parts)
        raise ValueError('invalid wait duration')


class RateLimitGate:
    """A persistent shared deadline across adapter calls/cells, with no transport retries."""
    def __init__(self, root, now=time.time, sleep=time.sleep):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'rate-limit.json'
        self.lock = self.root / 'rate-limit.lock'
        self.now, self.sleep = now, sleep

    @contextmanager
    def edit(self):
        with self.lock.open('a+b') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            state = json.loads(self.path.read_text()) if self.path.exists() else {}
            yield state
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(state))
            temp.replace(self.path)

    def observe(self, headers, status, body=b''):
        h = {k.lower():v for k,v in headers.items()}
        delays = []
        remaining = h.get('x-ratelimit-remaining', h.get('ratelimit-remaining'))
        try: exhausted = remaining is not None and float(remaining) <= 0
        except ValueError: exhausted = False
        structured = re.search(r'\br\s*=\s*0\b.*?\bt\s*=\s*(\d+)', h.get('ratelimit',''))
        if structured: delays.append(float(structured.group(1)))
        for key, value in h.items():
            try:
                if key == 'retry-after':
                    try: delay = float(value)
                    except ValueError: delay = email.utils.parsedate_to_datetime(value).timestamp()-self.now()
                    delays.append(delay)
                elif (status == 429 or exhausted) and ('reset-after' in key or key == 'ratelimit-reset'):
                    delays.append(_seconds(value))
                elif (status == 429 or exhausted) and 'ratelimit-reset' in key:
                    try: delays.append(float(value)-self.now())
                    except ValueError: delays.append(_seconds(value))
            except (ValueError, TypeError, OverflowError):
                continue
        # Error bodies can carry the only wait signal; inspect all nested explicit fields.
        def fields(value):
            if isinstance(value, dict):
                for k,v in value.items():
                    try:
                        if k in ('retry_after','retry_after_seconds','reset_after','wait_seconds','retryDelay'):
                            delays.append(_seconds(v))
                        elif k in ('reset','reset_at'):
                            delays.append(float(v)-self.now())
                        elif k == 'message' and isinstance(v,str):
                            for duration in re.findall(r'(?:retry|try again|wait)(?: after| in| for)?\s+(\d+(?:\.\d+)?(?:ms|s|m|h)(?:\d+(?:\.\d+)?(?:ms|s|m|h))*)', v, re.I):
                                delays.append(_seconds(duration))
                            for seconds in re.findall(r'(?:retry|try again|wait)(?: after| in| for)?\s+(\d+(?:\.\d+)?)\s+seconds?',v,re.I):
                                delays.append(float(seconds))
                    except (ValueError, TypeError): pass
                    fields(v)
            elif isinstance(value, list):
                for v in value: fields(v)
        if status >= 400 and body:
            try: fields(json.loads(body))
            except (ValueError, UnicodeError): pass
        finite = [max(0,d) for d in delays if math.isfinite(d)]
        with self.edit() as state:
            if finite:
                state['not_before'] = max(state.get('not_before',0),self.now()+max(finite))
            elif status == 429:
                state['undecidable'] = True

    def wait(self):
        while True:
            with self.edit() as state:
                if state.get('undecidable'):
                    raise ValueError('rate limit has no wait signal; refusing another request')
                left = state.get('not_before',0)-self.now()
            if left <= 0: return
            self.sleep(min(1,left))


class SamplingAdapter:
    """Single-forward HTTP adapter. Responses and SSE bytes are relayed without rewriting."""
    def __init__(self, knobs, gate, target=('127.0.0.1',18085)):
        self.knobs = validate_knobs(knobs) if knobs is not None else None
        self.gate, self.target = gate, target
        self.injected = []
        self.forward_lock = threading.Lock()
        self._admission = threading.Condition()
        self._paused = self._closed = False
        self._inflight = self._parked = 0
        adapter = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *_): pass
            def do_GET(self): self.forward()
            def do_POST(self): self.forward()
            def forward(self):
                if self.path not in ('/v1/responses','/v1/responses/compact','/v1/models','/health'):
                    self.send_error(404); return
                if self.headers.get('Transfer-Encoding'):
                    self.send_error(400,'chunked request bodies unsupported'); return
                # A checkpoint parks a NEW request before it can advance the producer.
                # Existing responses finish while the client is still running. GETs do
                # not represent the client's next model turn and cannot establish idle.
                inference = self.command == 'POST' and self.path in ('/v1/responses','/v1/responses/compact')
                admission = adapter.admit() if inference else nullcontext(True)
                with admission as admitted:
                    if not admitted:
                        self.close_connection = True
                        try:
                            self.send_response(503, 'Request not forwarded during suite checkpoint')
                            self.send_header('Retry-After', '0')
                            self.send_header('Content-Length', '0')
                            self.send_header('Connection', 'close')
                            self.end_headers()
                        except OSError:
                            pass  # a parked client may already have timed out
                        return
                    self.forward_admitted()

            def forward_admitted(self):
                # Serialize both directions until a full reply has updated the shared gate.
                with adapter.forward_lock:
                    connection = None
                    try:
                        raw = self.rfile.read(int(self.headers.get('Content-Length',0)))
                        if self.command == 'POST' and adapter.knobs is not None:
                            raw = inject_sampling(raw,adapter.knobs)
                            adapter.injected.append({'path':self.path,'fields':dict(adapter.knobs)})
                        # Incoming retry hints and upstream hints share the same deadline.
                        adapter.gate.observe(self.headers, 200)
                        adapter.gate.wait()
                        connection = http.client.HTTPConnection(*adapter.target,timeout=7200)
                        headers = {k:v for k,v in self.headers.items() if k.lower() not in HOP}
                        headers['Content-Length'] = str(len(raw))
                        connection.request(self.command,self.path,body=raw,headers=headers)
                        reply = connection.getresponse()
                        error_body = reply.read() if reply.status >= 400 else None
                        adapter.gate.observe(dict(reply.getheaders()),reply.status,error_body or b'')
                        self.send_response(reply.status,reply.reason)
                        for k,v in reply.getheaders():
                            if k.lower() not in HOP: self.send_header(k,v)
                        self.send_header('Connection','close')
                        self.end_headers()
                        self.close_connection = True
                        if error_body is not None: self.wfile.write(error_body)
                        else:
                            while chunk := reply.read1(65536):
                                self.wfile.write(chunk); self.wfile.flush()
                    except (OSError, ValueError, http.client.HTTPException):
                        self.close_connection = True
                        # No synthetic assistant response, no retry. A failed transport stays failed.
                    finally:
                        if connection: connection.close()
        self.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)

    @contextmanager
    def admit(self):
        with self._admission:
            rejected = self._closed
            parked = self._paused and not rejected
            if parked:
                self._parked += 1
                self._admission.notify_all()
                try:
                    self._admission.wait_for(lambda: not self._paused)
                finally:
                    self._parked -= 1
                    self._admission.notify_all()
            elif not rejected:
                self._inflight += 1
        try:
            # Every request parked during a checkpoint is rejected, even if it
            # survived its deadline. Never infer retry identity or replay a reply.
            yield not (parked or rejected)
        finally:
            if not (parked or rejected):
                with self._admission:
                    self._inflight -= 1
                    self._admission.notify_all()

    def quiesce(self, alive):
        """Drain inference at a serial client's next request, without freezing it.

        Caller precondition: model requests are serial and each reply is consumed
        before the next request. A parked parallel client is not an acknowledgement.
        Read-only GET traffic is deliberately outside this inference boundary.
        """
        with self._admission:
            if self._closed:
                return False
            self._paused = True
            self._admission.notify_all()
            try:
                while True:
                    if self._closed or not alive():
                        self._paused = False
                        self._admission.notify_all()
                        return False
                    if not self._inflight and self._parked:
                        return True
                    self._admission.wait(.05)
            except BaseException:
                self._paused = False
                self._admission.notify_all()
                raise

    def resume(self):
        with self._admission:
            self._paused = False
            self._admission.notify_all()

    def cancel(self):
        """Terminal cleanup wakes waiters but cannot admit another model request."""
        with self._admission:
            self._closed = True
            self._paused = False
            self._admission.notify_all()

    @property
    def base_url(self):
        return f'http://127.0.0.1:{self.server.server_port}/v1'

    def __enter__(self):
        self.thread.start(); return self

    def __exit__(self,*_):
        self.cancel()
        self.server.shutdown(); self.server.server_close(); self.thread.join()
