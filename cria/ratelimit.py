"""Rate-limit signals, read once and honoured everywhere cria makes an outbound HTTP request.

A server that says "wait" has said how long, in one of a dozen dialects: ``Retry-After`` (seconds or an HTTP
date), ``Retry-After-Ms``, ``X-RateLimit-Reset-After``, ``RateLimit-Reset``, the structured ``RateLimit`` header,
``X-RateLimit-Reset`` (delta seconds, epoch seconds, a date), OpenAI's ``x-ratelimit-reset-requests: 6m0s``, and —
when the headers say nothing — the BODY (Discord ``retry_after``, Google ``RetryInfo.retryDelay``, "Please try
again in 1.5s"). This module is the one place that reads them (:func:`delay_ms`), the one place that remembers
them for the whole process (:data:`STATE`: a request to a host that is cooling down WAITS the rest of it, or is
not sent at all when the rest exceeds what a turn can hold), and the one HTTP opener that applies both
(:func:`open_response`). Waiting less than the server said is the early retry a limiter punishes; polling at a fixed
interval is the other half of the same sin, so the only retry here is ONE, after the stated wait.
"""
from __future__ import annotations

import email.utils
import io
import json
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

MAX_WAIT_MS = 30_000          # what one request may hold the turn for; a longer cooldown is reported, not slept
DEFAULT_WAIT_MS = 1_000       # a 429 that named no delay at all: the smallest honest pause before the one retry
_BODY_PROBE_BYTES = 64 * 1024  # a refusal's body is read this far for a delay; the caller still gets all of it
_REFUSED = (429, 503)

_DURATION = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_BODY_PROSE = re.compile(r"(?:try again|retry)\s+(?:in|after)\s+((?:\d+(?:\.\d+)?(?:ms|h|m|s))+|\d+(?:\.\d+)?\s*(?:seconds?|secs?))",
                         re.IGNORECASE)
_UNIT_MS = {"ms": 1, "s": 1000, "m": 60_000, "h": 3_600_000}


class RateLimited(OSError):
    """Raised INSTEAD of sending: the host asked for a wait longer than a turn can hold, and it has not elapsed."""

    code = 429

    def __init__(self, key: str, retry_after_ms: int):
        self.key = key
        self.retry_after_ms = retry_after_ms
        super().__init__(f"rate limited: {key} asked for a wait of {math.ceil(retry_after_ms / 1000)} s that has not "
                         f"elapsed; this request was NOT sent (sending it early only extends the wait)")


def duration_ms(text: str) -> Optional[int]:
    """``"1.5s"``, ``"6m0s"``, ``"20ms"``, ``"2 seconds"`` or a bare number of seconds, in ms; None when it is none of those."""
    t = (text or "").strip().lower()
    if not t:
        return None
    try:
        v = float(t)
        return int(v * 1000) if math.isfinite(v) and v >= 0 else None
    except ValueError:
        pass
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:seconds?|secs?)", t)
    if m:
        return int(float(m.group(1)) * 1000)
    parts = _DURATION.findall(t)
    if parts and "".join(f"{n}{u}" for n, u in parts) == t.replace(" ", ""):
        return int(sum(float(n) * _UNIT_MS[u] for n, u in parts))
    return None


def _date_ms(raw: str, now: float) -> Optional[int]:
    try:
        when = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    return int((when.timestamp() - now) * 1000)


def _reset_ms(raw: str, now: float) -> Optional[int]:
    """One reset value: a duration, delta seconds, epoch seconds/milliseconds, or a date."""
    raw = raw.strip()
    try:
        v = float(raw)
    except ValueError:
        return duration_ms(raw) if duration_ms(raw) is not None else _date_ms(raw, now)
    if not math.isfinite(v) or v < 0:
        return None
    if v > 1e11:                      # epoch milliseconds
        return int(v - now * 1000)
    if v > 1e8:                       # epoch seconds (a delta of 3 years is not a rate-limit window)
        return int((v - now) * 1000)
    return int(v * 1000)


def _csv(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def _header_delays(headers, now: float, refused: bool) -> list[int]:
    def get(name: str) -> str:
        value = headers.get(name)
        return value if isinstance(value, str) else ""      # a header is text; anything else is not a stated limit

    out: list[int] = []

    def add(v: Optional[int]) -> None:
        if v is not None and v >= 0:
            out.append(v)

    for name, scale in (("Retry-After-Ms", 1), ("Retry-After", 1000), ("X-RateLimit-Reset-After", 1000)):
        raw = get(name).strip()
        if not raw:
            continue
        try:
            v = float(raw) * scale
            add(int(v) if math.isfinite(v) else None)
        except ValueError:
            if name == "Retry-After":
                add(_date_ms(raw, now))
    # The reset family names when a WINDOW reopens: it is a wait only for a window that is exhausted, or on a refusal.
    remaining = get("X-RateLimit-Remaining") or get("RateLimit-Remaining")
    structured = get("RateLimit")
    m = re.search(r"remaining\s*=\s*(\d+)", structured)
    if m and not remaining:
        remaining = m.group(1)
    exhausted = [p == "0" for p in _csv(remaining)]
    resets: list[str] = []
    for name in ("X-RateLimit-Reset", "RateLimit-Reset", "X-RateLimit-Reset-Requests", "X-RateLimit-Reset-Tokens"):
        resets += _csv(get(name))
    m = re.search(r"reset\s*=\s*(\d+)", structured)
    if m:
        resets.append(m.group(1))
    values = [_reset_ms(r, now) for r in resets]
    values = [v for v in values if v is not None and v >= 0]
    if values:
        if exhausted and len(exhausted) == len(values):
            # Brave: "Remaining: 0, 14999" / "Reset: 1, 2345678" — only the exhausted window's reset is a wait.
            closed = [v for v, dead in zip(values, exhausted) if dead]
            values = closed or (values if refused else [])
        elif not (refused or any(exhausted)):
            values = []
        out += values
    return out


def _body_delays(body: bytes | str | None) -> list[int]:
    if not body:
        return []
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    out: list[int] = []

    def walk(node, depth=0):
        if depth > 6:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k).lower()
                if key in ("retry_after", "retryafter") and isinstance(v, (int, float)) and not isinstance(v, bool):
                    out.append(int(v * 1000))                          # Discord: seconds, fractional
                elif key == "retry_after_ms" and isinstance(v, (int, float)) and not isinstance(v, bool):
                    out.append(int(v))
                elif key in ("retrydelay", "retry_delay") and isinstance(v, str):
                    out.append(duration_ms(v))                         # Google RetryInfo: "3.5s"
                else:
                    walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)
        elif isinstance(node, str):
            for m in _BODY_PROSE.finditer(node):
                out.append(duration_ms(m.group(1)))

    start, end = text.find("{"), text.rfind("}")
    try:
        walk(json.loads(text))
    except ValueError:
        if 0 <= start < end:                                  # "API Error: 429 {...json...}": the body rides inside prose
            try:
                walk(json.loads(text[start:end + 1]))
            except ValueError:
                pass
        for m in _BODY_PROSE.finditer(text[:4096]):
            out.append(duration_ms(m.group(1)))
    return [v for v in out if v is not None and v >= 0]


def delay_ms(headers, body=None, *, now: Callable[[], float] = time.time, refused: bool = True) -> Optional[int]:
    """How long the server said to wait, in ms — the LONGEST delay any of its signals names (waiting less than one
    of them is the early retry). ``None`` when it named none. ``refused=False`` reads a SUCCESS response: the reset
    headers then count only for a window that reports itself exhausted (``Remaining: 0``)."""
    found: list[int] = []
    if headers:
        found += _header_delays(headers, now(), refused)
    if refused:
        found += _body_delays(body)
    return max(found) if found else None


class WaitState:
    """Per-key cooldown deadlines for the whole process: every thread's request to a cooling-down host waits it out."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self._clock, self._sleep = clock, sleep
        self._until: dict[str, float] = {}
        self._lock = threading.Lock()

    def note(self, key: str, delay_ms_: int) -> None:
        """Record that ``key`` is closed for ``delay_ms_`` more ms (never shortens a longer wait already recorded)."""
        with self._lock:
            until = self._clock() + delay_ms_ / 1000.0
            if until > self._until.get(key, 0.0):
                self._until[key] = until
            if len(self._until) > 256:                          # bounded on a long-lived server: drop the elapsed
                now = self._clock()
                self._until = {k: v for k, v in self._until.items() if v > now}

    def remaining_ms(self, key: str) -> int:
        with self._lock:
            left = self._until.get(key, 0.0) - self._clock()
        return max(0, math.ceil(left * 1000))

    def hold(self, key: str, max_wait_ms: int = MAX_WAIT_MS) -> None:
        """Wait out ``key``'s cooldown; raise :class:`RateLimited` (nothing sent, nothing slept) when it is longer than ``max_wait_ms``."""
        while True:
            left = self.remaining_ms(key)
            if left <= 0:
                return
            if left > max_wait_ms:
                raise RateLimited(key, left)
            self._sleep(left / 1000.0)

    def clear(self) -> None:
        with self._lock:
            self._until.clear()


STATE = WaitState()


def key_for(url: str) -> str:
    """The cooldown key of a request: scheme-less ``host:port`` — a limiter's quota is the service's, not one path's."""
    return urllib.parse.urlsplit(url).netloc.rsplit("@", 1)[-1].lower()


def _replayable(err: urllib.error.HTTPError, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(err.url, err.code, err.msg, err.headers, io.BytesIO(body))


def observe(state: WaitState, key: str, status: int, headers, body=None, *, now: Callable[[], float] = time.time) -> Optional[int]:
    """Record what a response said about waiting; returns the delay (ms) a REFUSAL asked for, else None."""
    refused = status in _REFUSED
    delay = delay_ms(headers, body, now=now, refused=refused)
    if refused:
        if status == 429 and delay is None:
            delay = DEFAULT_WAIT_MS
        if delay is not None:
            state.note(key, delay)
        return delay
    if delay is not None and delay > 0:
        state.note(key, delay)
    return None


def open_response(req: urllib.request.Request, timeout: float, *, state: Optional[WaitState] = None,
                  opener: Optional[Callable] = None, max_wait_ms: int = MAX_WAIT_MS,
                  now: Callable[[], float] = time.time):
    """``urlopen`` that honours rate limits. Returns the response — a non-2xx too (an :class:`~urllib.error.HTTPError`
    is a response object, its body replayable), exactly what callers that read a refusal's body already expect.

    Before sending, waits out any cooldown recorded for the host (or raises :class:`RateLimited` when it is longer
    than ``max_wait_ms``). A 429/503 that named a delay within ``max_wait_ms`` is retried ONCE, after exactly that
    delay; any other refusal is returned with its wait recorded, so the NEXT request to the host waits."""
    state = STATE if state is None else state
    key = key_for(req.full_url)
    attempt = 0
    while True:
        state.hold(key, max_wait_ms)
        try:
            resp = (opener or urllib.request.urlopen)(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            resp = e
        status = int(getattr(resp, "status", 0) or getattr(resp, "code", 0) or 0)
        body = None
        if status in _REFUSED and isinstance(resp, urllib.error.HTTPError):
            body = resp.read(_BODY_PROBE_BYTES + 1)
            rest = resp.read()
            resp = _replayable(resp, body + rest)
            body = body[:_BODY_PROBE_BYTES]
        delay = observe(state, key, status, resp.headers, body, now=now)
        if delay is not None and attempt == 0 and delay <= max_wait_ms:
            attempt += 1
            resp.close()
            continue
        return resp
