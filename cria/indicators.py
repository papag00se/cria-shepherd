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
# SENTINEL is the bare token for substring/line matching (a parroted or empty banner may
# lack the trailing space); MARKER == SENTINEL + " " is the prefix every emitted line uses.
# Everything that emits or strips a cria line references these — never a bare literal — so the
# emit/strip contract can't silently diverge if the token ever changes.
SENTINEL = "⟦cria⟧"
MARKER = SENTINEL + " "

# A reasoning-transcript block is BRACKETED by this fence line (opening and closing) so its body can
# render CLEAN — no per-line marker walling every code line a model drafts in its reasoning — while
# strip_history still removes the WHOLE block from inbound history. The fence lines carry the MARKER,
# so a legacy per-line stripper still drops them; the body between them is dropped by the fence toggle.
THINK_FENCE = MARKER + "💭"

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
    route: bool = True  # config: the "⟦cria⟧ <role> · <model>" banner is enabled
    assists: bool = True  # config: the "⟦cria⟧ <note>" guard/assist lines are enabled

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
    """Drop cria's own lines: every ``MARKER`` line, PLUS the clean (unmarked) body between a pair of
    ``THINK_FENCE`` lines (the reasoning-transcript block). The fence toggles: an unmatched open fence
    drops to the end of the content — fail-safe, so a model never re-ingests its own reasoning."""
    lines = text.split("\n")
    kept: list[str] = []
    dropped = 0
    inside = False
    for ln in lines:
        if ln.strip() == THINK_FENCE:      # a fence line → toggle in/out, drop it
            inside = not inside
            dropped += 1
            continue
        if inside:                          # reasoning body between fences → drop (clean, unmarked)
            dropped += 1
            continue
        if ln.lstrip().startswith(MARKER):  # a normal cria line (banner / assist / old per-line fold) → drop
            dropped += 1
            continue
        kept.append(ln)
    return "\n".join(kept).strip("\n"), dropped


def strip_note_lines(completion: dict) -> None:
    """Remove cria's own ``⟦cria⟧ …`` (MARKER) lines from a completion's message content, in place.
    Used when ``[indicators] assists`` is off, so the guard/assist notes cria synthesizes into the
    completion content ('running the repo's checks (…)', truncation warnings) never reach the
    harness. The separately-added route banner is unaffected (it isn't in the content)."""
    for ch in completion.get("choices", []):
        msg = ch.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str) and MARKER in content:
            msg["content"] = _strip_marker_lines(content)[0] or None


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

    # Hold the route/note lines and flush them only just before the FIRST real content delta —
    # so a content-less stream (a tool-call-only or empty turn) never emits a standalone banner
    # that the harness stores and re-summarizes. Flushed inline, the banner rides the content and
    # is stripped inbound with it.
    pending = []
    if indic.route and indic.show_route:  # the ongoing route banner (config: [indicators] route)
        pending.append(route_line(indic) + "\n")
    if indic.assists and indic.note:  # a guard/assist note line (config: [indicators] assists)
        pending.append(MARKER + indic.note + "\n")

    t_first: float | None = None
    deltas = 0
    for raw in chunks:
        if raw.strip() == b"data: [DONE]":
            # metrics only when we actually emitted content (pending was flushed)
            if indic.metrics and deltas >= _MIN_DELTAS_FOR_RATE and t_first is not None and not pending:
                dt = time.monotonic() - t_first
                if dt > 0:
                    yield content_chunk(indic.model, "\n" + metrics_line(deltas, round(deltas / dt, 1)))
            yield raw
        else:
            if _is_content_delta(raw):
                for h in pending:  # flush the banner inline, ahead of the first content token
                    yield content_chunk(indic.model, h)
                pending = []
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
    if indic.route and indic.show_route:  # config: [indicators] route
        header_lines.append(route_line(indic))
    if indic.assists and indic.note:  # config: [indicators] assists
        header_lines.append(MARKER + indic.note)
    if not header_lines:
        return raw
    try:
        obj = json.loads(raw)
        msg = obj["choices"][0]["message"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return raw
    existing = msg.get("content") or ""
    if not existing.strip():
        # No content to decorate — DON'T let the status header become the whole "response".
        # A header-only completion is summarized/handed off as if it were real content (it once
        # became an entire compaction summary) and reads as a finished answer to the harness.
        return raw
    header = "\n".join(header_lines)
    msg["content"] = f"{header}\n\n{existing}"
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
