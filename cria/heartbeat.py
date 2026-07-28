"""SSE heartbeat keepalive.

A plan-driven request can chain several model calls (classify → plan → coder →
verify) before any bytes reach the client, and the upstream's prefill adds more
dead time. Clients abort a connection that goes silent too long. This drips an SSE
*comment* line (`:\n\n`, which every SSE client ignores per spec) into the stream
whenever it has been idle for `interval` seconds — so the connection stays alive
through cria's thinking without the harness having to know anything.

Idle-based, not fixed-rate: a real content write resets the clock, so heartbeats
appear only in the gaps. A background thread does the beating; it shares one lock
with the content writer so a beat never interleaves mid-chunk.
"""

from __future__ import annotations

import threading
import time

_COMMENT = b": cria\n\n"


class Heartbeat:
    def __init__(self, write_raw, interval: float = 5.0, *, clock=time.monotonic,
                 payload: bytes = _COMMENT, on_beat=None, beat_status_every: float = 30.0) -> None:
        self._write_raw = write_raw  # bytes -> write+flush to the wire
        self._interval = interval
        self._clock = clock
        self._last = clock()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._drained = False  # a terminal payload was written (shutdown drain) → no more writes
        # The beat payload. Default = an SSE COMMENT (spec-ignorable). A client whose idle timer
        # counts EVENTS rather than bytes never sees a comment (observed: the Codex extension's
        # Responses client dropped a stream mid-compaction with "idle timeout waiting for SSE"
        # while comments were flowing) — such a path passes a REAL protocol event instead.
        self._payload = payload
        # Optional VISIBLE tick: called with elapsed seconds, at most every ``beat_status_every``,
        # from the beat thread OUTSIDE the write lock (the callback may call ``write`` itself).
        # One long model call fires no events — the ticker went silent for 10 minutes while a 27B
        # coder ground at 7 tok/s (operator: "no updates in between"); this is the in-between.
        self._on_beat = on_beat
        self._beat_status_every = beat_status_every
        self._t0 = clock()
        self._last_beat_cb = clock()
        self.beats = 0

    def start(self) -> "Heartbeat":
        if self._interval > 0:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def write(self, data: bytes) -> None:
        """Write real content, serialized with heartbeats and resetting the idle clock."""
        with self._lock:
            if self._drained:
                return  # the stream was terminally drained on shutdown — never write past it
            self._write_raw(data)
            self._last = self._clock()

    def drain(self, data: bytes) -> None:
        """Write a TERMINAL payload once and stop the stream — used by the server's shutdown drain to
        end an in-flight SSE cleanly (a retryable response.failed) instead of leaving the client with
        a bare mid-stream EOF. Idempotent; safe to call from a different thread than the writer (the
        request thread is blocked in the model call), since it takes the same write lock."""
        with self._lock:
            if self._drained:
                return
            self._drained = True
            try:
                self._write_raw(data)
            except Exception:  # noqa: BLE001 — the socket may already be gone; shutting down anyway
                pass
        self._stop.set()  # stop the heartbeat thread

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        tick = min(1.0, self._interval / 2) or 0.25
        while not self._stop.wait(tick):
            fired = False
            with self._lock:
                if self._drained:
                    break
                if self._clock() - self._last >= self._interval:
                    try:
                        self._write_raw(self._payload)
                        self._last = self._clock()
                        self.beats += 1
                        fired = True
                    except Exception:
                        break  # client gone; the request thread will notice and clean up
            if fired and self._on_beat is not None:
                now = self._clock()
                if now - self._last_beat_cb >= self._beat_status_every:
                    self._last_beat_cb = now
                    try:
                        self._on_beat(now - self._t0)  # outside the lock — it may call write()
                    except Exception:  # noqa: BLE001 — narration must never break the stream
                        pass
