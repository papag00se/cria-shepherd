"""Exact counts of the string values a coder SENT in its tool calls.

Ground truth over judgment (principle 1): deterministic code gathers the facts, a reasoner judges
them.  A small judge handed ``"content": "snow 雪\\n\\"quoted\\"\\nbackslash \\\\"`` as an escaped JSON
string cannot see that the last line break a task demanded is not there — the byte-level shape of a
value is invisible in that layout (C13-C: the judge approved a 29-byte file for a task that required
30, with the task, the write and the read all intact in its prompt).  This module measures what the
CALL ARGUMENTS contained — the one envelope cria itself parsed — and nothing about tool RESULTS,
whose formats are unknown and must stay unknown.

No field names, task words or file types are consulted: every string leaf of every call gets the
same three facts, so nothing is task-specific and nothing is decided here.
"""
from __future__ import annotations

import json

from . import prompts


def _leaves(value, path: str = ""):
    if isinstance(value, str):
        yield path or "(value)", value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _leaves(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _leaves(v, f"{path}[{i}]")


def render(calls: list[tuple[str, str]]) -> str:
    """``calls``: (tool name, raw arguments string) in log order. Returns "" when no call carries a
    parseable string argument (silence over noise)."""
    words = prompts.load_map("argument_facts")
    rows: list[str] = []
    for n, (tool, raw) in enumerate(calls, 1):
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            continue
        for field, text in _leaves(parsed):
            if not text:
                ends = words["empty"]
            elif text.endswith(("\n", "\r")):
                ends = words["ends_with_break"]
            else:
                ends = words["ends_without_break"]
            rows.append(prompts.fill(
                words["line"], n=n, tool=tool, field=field, bytes=len(text.encode("utf-8")),
                breaks=text.count("\n"), ends=ends))
    if not rows:
        return ""
    return words["header"] + "\n" + "\n".join(rows)


def extract(evidence: str) -> str:
    """The measured-facts block inside an evidence string ("" when absent): the header line and the
    contiguous fact rows after it.  Callers downstream of the evidence builder read it back from the
    text the judge itself was given, so the question is asked about exactly what the judge saw."""
    header = prompts.load_map("argument_facts")["header"]
    start = evidence.find(header)
    if start < 0:
        return ""
    rows = [header]
    for ln in evidence[start + len(header):].lstrip("\n").splitlines():
        if not ln.startswith("- call "):
            break
        rows.append(ln)
    return "\n".join(rows) if len(rows) > 1 else ""
