"""Per-user-turn stats — a terse end-of-turn summary cria appends to the agent's final answer.

A 'user turn' spans the many harness requests between one user message and the agent's final
text answer. cria accumulates activity per session (calls, tok/s, guard fires, wall time) and,
when the agent finishes (a text-only turn after real multi-step work), emits ONE ``⟦cria⟧`` line.
Stateful per session (like the write-translation / guard stores), reset each turn. Stdlib only.
"""
from __future__ import annotations

import threading
import time
from collections import Counter

from .indicators import MARKER

# The assist ledger is counted from cria's own EVENT fires (one event == one distinct fire), NOT by
# text-matching note echoes — which under-counted (a periodic gate / redirect matches no needle),
# over-counted (a persisting note re-tallied each request), and broke on any prompt reword.
#
# The two `kind -> label` maps that used to live here are gone. They were a hand-maintained list of
# other modules' events, kept beside the thing they described, and they drifted exactly the way such
# a list does: four mechanisms that rewrite model-visible content — the ledger, repeat and anchor
# dedups, and the de-orphaner — fired invisibly under a heading about silent reshaping. Each fire
# site now declares itself (`steer=` / `reshape=` on the emit, see :mod:`cria.events`), so this
# renders what actually happened and cannot disagree with it.
#
# 🛡 STEERS are model-FACING interventions the coder reads. 🧰 RESHAPES are SILENT context/output
# reshaping the coder never reads as a steer but which changes what it sees (a many-fire count there
# is normal — self-compact runs each time the window fills).


def _fmt_tokens(n: int) -> str:
    """Compact token count: 3.2k over a thousand, the bare number below it."""
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


class TurnStats:
    """One user turn's running tally. ``observe`` folds in each harness response; ``summary``
    renders the terse ⟦cria⟧ line."""

    def __init__(self) -> None:
        self.t0: float | None = None
        self.calls = 0          # finalized harness responses — the reset gate ("real work" = ≥2)
        self.model_calls = 0    # ACTUAL model calls (upstream.done) — what "🧮 N calls" shows
        self.tps: list[float] = []
        self.tokens = 0
        self.events: Counter = Counter()   # every event kind fired this turn (from each request's rlog)
        self.ledger: Counter = Counter()   # (bucket, label) -> fires, as each fire site declared it

    def observe(self, tok_per_s: float | None,
                gen_tokens: int = 0, model_calls: int = 0, events: Counter | None = None,
                ledger: Counter | None = None) -> None:
        if self.t0 is None:
            self.t0 = time.monotonic()
        self.calls += 1
        self.model_calls += int(model_calls or 0)
        if tok_per_s:
            self.tps.append(tok_per_s)
        self.tokens += int(gen_tokens or 0)
        if events:
            self.events.update(events)   # authoritative per-fire tally, summed across the turn's requests
        if ledger:
            self.ledger.update(ledger)

    def _bucket(self, bucket: str) -> "Counter":
        out: Counter = Counter()
        for (b, label), n in self.ledger.items():
            if b == bucket:
                out[label] += n
        return out

    def summary(self) -> str:
        secs = int(time.monotonic() - self.t0) if self.t0 is not None else 0
        avg = round(sum(self.tps) / len(self.tps), 1) if self.tps else 0
        parts = [f"⏱ {secs}s", f"🧮 {self.model_calls} calls", f"⚡ {avg} tok/s"]
        if self.tokens:  # generated tokens this turn — the volume behind the rate
            parts.append(f"🔢 {_fmt_tokens(self.tokens)} tok")
        steers = self._bucket("steer")
        if steers:  # model-facing interventions the coder read
            parts.append("🛡 " + " ".join(f"{k}×{v}" for k, v in steers.most_common()))
        reshapes = self._bucket("reshape")
        if reshapes:  # silent context/output reshaping
            parts.append("🧰 " + " ".join(f"{k}×{v}" for k, v in reshapes.most_common()))
        return f"{MARKER}turn done · " + " · ".join(parts)


class StatsStore:
    """Per-session TurnStats — reset when a turn ends and its summary is emitted."""

    def __init__(self) -> None:
        self._m: dict[str, TurnStats] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> TurnStats:
        with self._lock:
            st = self._m.get(key)
            if st is None:
                st = self._m[key] = TurnStats()
            return st

    def reset(self, key: str) -> None:
        with self._lock:
            self._m.pop(key, None)
