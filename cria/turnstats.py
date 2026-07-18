"""Per-user-turn stats — a terse end-of-turn summary cria appends to the agent's final answer.

A 'user turn' spans the many harness requests between one user message and the agent's final
text answer. cria accumulates activity per session (calls, tok/s, guard fires, wall time) and,
when the agent finishes (a text-only turn after real multi-step work), emits ONE ``⟦cria⟧`` line.
Stateful per session (like the write-translation / guard stores), reset each turn. Stdlib only.
"""
from __future__ import annotations

import threading
import time

from .indicators import MARKER

# A cria note's wording → its emoji tally label (matched against cria's own note text, so it
# stays in sync with the guards). Order matters: first match wins.
_GUARD_KINDS = (
    ("reasoning loop", "🧠 rumination"),
    ("token limit", "✂️ truncation"),
    ("repeated rewrites", "🌀 wheel-spin"),
    ("repeated action", "🔁 repetition"),
    ("steer", "🧭 steer"),
)


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
        self.guards: dict[str, int] = {}

    def observe(self, completion: dict, tok_per_s: float | None,
                gen_tokens: int = 0, model_calls: int = 0) -> None:
        if self.t0 is None:
            self.t0 = time.monotonic()
        self.calls += 1
        self.model_calls += int(model_calls or 0)
        if tok_per_s:
            self.tps.append(tok_per_s)
        self.tokens += int(gen_tokens or 0)
        # Tally guard fires from BOTH channels: the out-of-band cria_notes (rumination/truncation/
        # steer) and any ⟦cria⟧ line already in the content (the repetition/wheel-spin probes).
        texts = list(completion.get("cria_notes") or [])
        content = ((completion.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        texts += [ln for ln in content.split("\n") if ln.lstrip().startswith(MARKER)]
        for t in texts:
            low = t.lower()
            for needle, label in _GUARD_KINDS:
                if needle in low:
                    self.guards[label] = self.guards.get(label, 0) + 1
                    break

    def summary(self) -> str:
        secs = int(time.monotonic() - self.t0) if self.t0 is not None else 0
        avg = round(sum(self.tps) / len(self.tps), 1) if self.tps else 0
        parts = [f"⏱ {secs}s", f"🧮 {self.model_calls} calls", f"⚡ {avg} tok/s"]
        if self.tokens:  # generated tokens this turn — the volume behind the rate
            parts.append(f"🔢 {_fmt_tokens(self.tokens)} tok")
        if self.guards:
            parts.append("🛡 " + " ".join(f"{k}×{v}" for k, v in self.guards.items()))
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
