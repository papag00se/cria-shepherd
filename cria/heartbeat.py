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
    def __init__(self, write_raw, interval: float = 5.0, *, clock=time.monotonic) -> None:
        self._write_raw = write_raw  # bytes -> write+flush to the wire
        self._interval = interval
        self._clock = clock
        self._last = clock()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.beats = 0

    def start(self) -> "Heartbeat":
        if self._interval > 0:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def write(self, data: bytes) -> None:
        """Write real content, serialized with heartbeats and resetting the idle clock."""
        with self._lock:
            self._write_raw(data)
            self._last = self._clock()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        tick = min(1.0, self._interval / 2) or 0.25
        while not self._stop.wait(tick):
            with self._lock:
                if self._clock() - self._last >= self._interval:
                    try:
                        self._write_raw(_COMMENT)
                        self._last = self._clock()
                        self.beats += 1
                    except Exception:
                        break  # client gone; the request thread will notice and clean up
