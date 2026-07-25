"""Extract a JSON object from a small local model's noisy output.

Local models routinely wrap JSON in ```` ```json ```` fences and emit ``<think>``
reasoning before it — both break a naive ``json.loads``. This is the one place
that noise is dealt with, so every JSON-consuming caller (classifier, later the
completion critic and planner) parses the same way.
"""

from __future__ import annotations

import json
import re

_THINK = re.compile(r"<think(?:ing)?\b[^>]*>.*?</think(?:ing)?\s*>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*", re.IGNORECASE)


def strip_think(text: str) -> str:
    """Remove ``<think>…</think>`` blocks (reasoning models emit these before the
    answer). Also drops a dangling unclosed ``<think>`` and everything after it —
    UNLESS a parseable JSON object follows the tag. A model that forgot to close
    its ``<think>`` before emitting the answer (``<think>deciding…\n{"x":1}``)
    still has a real object in the tail; blindly slicing from ``<think`` to the
    end would silently discard that answer, so we keep the tail when it parses.
    """
    text = _THINK.sub("", text)
    lower = text.lower()
    idx = lower.rfind("<think")
    if idx != -1 and "</think" not in lower[idx:]:
        if _scan_object(text[idx:]) is None:
            text = text[:idx]
    return text


def extract_json_object(text: str) -> dict | None:
    """Return the first balanced ``{…}`` JSON object in ``text``, or ``None``.

    Tolerates ```` ```json ```` fences, ``<think>`` preambles, and trailing prose.
    Scans for a brace-balanced span (respecting strings/escapes) so a JSON object
    that itself contains braces in string values still parses.
    """
    if not text:
        return None
    cleaned = _FENCE.sub("", strip_think(text)).replace("```", "")
    return _scan_object(cleaned)


def _scan_object(s: str) -> dict | None:
    """First brace-balanced span in ``s`` that parses to a ``dict``, else ``None``."""
    start = s.find("{")
    while start != -1:
        span = _balanced_object(s, start)
        if span is not None:
            try:
                obj = json.loads(span)
            except json.JSONDecodeError:
                obj = None
            if isinstance(obj, dict):
                return obj
        start = s.find("{", start + 1)
    return None


def _balanced_object(s: str, start: int) -> str | None:
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None
