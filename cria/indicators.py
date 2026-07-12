"""TUI indicators — cria's messaging to the human, through the content channel.

cria talks to the harness over the model-answer pipe, and the harness renders
whatever text is in the completion. So cria decorates the completion with its own
status lines (which model it picked, throughput, later: assist notifications) — and
because cria is the proxy, it **strips its own lines from the conversation before
the model ever sees them** on the next turn. Decorate the human, hide from the
model. Every cria line starts with `MARKER`, which is how the strip finds them; the
harness just shows it as text and needs to understand nothing.

This is the bidirectional pattern from CUTOVER.md ("indicators surfaced out-of-band,
trivially stripped before the upstream call"), done through the content channel.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Iterator

# Distinctive enough that a model is extremely unlikely to emit it (so the inbound
# strip never eats real output), and visible so the human knows it's a cria note.
MARKER = "⟦cria⟧ "

# Below this many streamed content deltas, a tok/s figure is noise (e.g. the Claude
# provider fake-streams one big chunk) — so the metrics line is suppressed.
_MIN_DELTAS_FOR_RATE = 3


@dataclass
class Indicator:
    enabled: bool
    metrics: bool
    model: str
    role: str | None = None  # None → passthrough (no routing)
    show_route: bool = True  # show the "which model" line this turn (else metrics only)
    note: str | None = None  # an extra one-off line, e.g. "planned 5 steps → …"

    def route_text(self) -> str:
        return f"{self.role or 'passthrough'} · {self.model}"


def route_line(indic: Indicator) -> str:
    return f"{MARKER}{indic.route_text()}"


def metrics_line(deltas: int, tok_per_s: float) -> str:
    return f"{MARKER}{deltas} tok · {tok_per_s} tok/s"


# ------------------------------------------------------------------ inbound


def strip_history(messages: list[dict]) -> tuple[list[dict], int]:
    """Remove cria's own `MARKER` lines from message content, so the model never
    re-reads them. Returns (clean messages, lines stripped)."""
    out: list[dict] = []
    stripped = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str) and MARKER in content:
            cleaned, n = _strip_marker_lines(content)
            if n:
                m = {**m, "content": cleaned}
                stripped += n
        out.append(m)
    return out, stripped


def _strip_marker_lines(text: str) -> tuple[str, int]:
    lines = text.split("\n")
    kept = [ln for ln in lines if not ln.lstrip().startswith(MARKER)]
    return "\n".join(kept).strip("\n"), len(lines) - len(kept)


# ------------------------------------------------------------------ outbound


def content_chunk(model: str, text: str) -> bytes:
    """An OpenAI streaming content delta carrying `text`."""
    payload = {
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n"


def wrap_stream(chunks: Iterator[bytes], indic: Indicator) -> Iterator[bytes]:
    """Wrap an upstream SSE stream: inject the route line first (own line), forward
    the model's chunks unchanged, and — for a real token stream — inject a tok/s
    line just before `[DONE]`. Purely additive to the model's output."""
    if not indic.enabled:
        yield from chunks
        return

    if indic.show_route:
        yield content_chunk(indic.model, route_line(indic) + "\n")
    if indic.note:
        yield content_chunk(indic.model, MARKER + indic.note + "\n")

    t_first: float | None = None
    deltas = 0
    for raw in chunks:
        if raw.strip() == b"data: [DONE]":
            if indic.metrics and deltas >= _MIN_DELTAS_FOR_RATE and t_first is not None:
                dt = time.monotonic() - t_first
                if dt > 0:
                    # leading newline so it lands on its own line after the model text
                    yield content_chunk(indic.model, "\n" + metrics_line(deltas, round(deltas / dt, 1)))
            yield raw
        else:
            if _is_content_delta(raw):
                if t_first is None:
                    t_first = time.monotonic()
                deltas += 1
            yield raw


def inject_buffered(raw: bytes, indic: Indicator) -> bytes:
    """Prepend cria's status lines to a non-streaming completion's content. (No
    tok/s — a buffered response carries no timing.)"""
    if not indic.enabled:
        return raw
    header_lines = []
    if indic.show_route:
        header_lines.append(route_line(indic))
    if indic.note:
        header_lines.append(MARKER + indic.note)
    if not header_lines:
        return raw
    try:
        obj = json.loads(raw)
        msg = obj["choices"][0]["message"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return raw
    header = "\n".join(header_lines)
    existing = msg.get("content") or ""
    msg["content"] = f"{header}\n\n{existing}" if existing else header
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _is_content_delta(raw: bytes) -> bool:
    if not raw.startswith(b"data:"):
        return False
    payload = raw[5:].strip()
    if not payload or payload == b"[DONE]":
        return False
    try:
        obj = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    for choice in obj.get("choices", []) if isinstance(obj, dict) else []:
        if (choice.get("delta") or {}).get("content"):
            return True
    return False
