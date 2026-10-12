"""Exact counts of the CONTENT of files the coder wrote or edited, for the completion judge.

Ground truth over judgment (principle 1): deterministic code gathers, a reasoner judges.  A small
judge handed ``"content": "snow 雪\\n\\"quoted\\"\\nbackslash \\\\"`` as an escaped JSON string cannot
see that the final line break a task demanded is missing (C13-C: a 29-byte file approved for a task
requiring 30).  The counts here are of FILE CONTENT only — the workspace view's current body of a
file the session wrote or edited, or, when no view can answer, the newest write that returned a
result provided nothing afterwards could have changed that file (the caller proves that).  They are
never taken from a command string, a path string, a refused call, or a tool's own report, and a
fact that went stale (a later edit, a shell that writes) is not stated at all.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import prompts


@dataclass(frozen=True)
class FileFact:
    path: str
    raw: bytes
    on_disk: bool


def render(facts: list[FileFact]) -> str:
    """"" when there is nothing to state (silence over noise)."""
    if not facts:
        return ""
    words = prompts.load_map("file_facts")
    rows = []
    for f in facts:
        if not f.raw:
            ends = words["empty"]
        elif f.raw[-1:] in (b"\n", b"\r"):
            ends = words["ends_with_break"]
        else:
            ends = words["ends_without_break"]
        rows.append(prompts.fill(
            words["line"], path=f.path, source=words["source_disk" if f.on_disk else "source_written"],
            bytes=len(f.raw), breaks=f.raw.count(b"\n"), ends=ends))
    return words["header"] + "\n" + "\n".join(rows)


def extract(evidence: str) -> str:
    """The measured-facts block inside an evidence string ("" when absent): the header line and the
    contiguous fact rows after it, so the question is asked about exactly what the judge saw."""
    header = prompts.load_map("file_facts")["header"]
    start = evidence.find(header)
    if start < 0:
        return ""
    rows = [header]
    for ln in evidence[start + len(header):].lstrip("\n").splitlines():
        if not ln.startswith("- "):
            break
        rows.append(ln)
    return "\n".join(rows) if len(rows) > 1 else ""


def parse(evidence: str) -> list[tuple[str, int, bool]]:
    """``(path, bytes, ends_with_line_break)`` read back from the fact rows, using the SAME line
    template :func:`render` wrote them with, so the two cannot drift."""
    import re
    words = prompts.load_map("file_facts")
    pat = re.escape(words["line"])
    for key, rx in (("PATH", r"(?P<path>.+?)"), ("SOURCE", r".+?"), ("BYTES", r"(?P<bytes>\d+)"),
                    ("BREAKS", r"\d+"),
                    ("ENDS", "(?P<ends>" + "|".join(re.escape(words[k]) for k in
                                                   ("ends_with_break", "ends_without_break", "empty")) + ")")):
        pat = pat.replace(re.escape("{{" + key + "}}"), rx)
    out = []
    for ln in extract(evidence).splitlines()[1:]:
        m = re.fullmatch(pat, ln)
        if m:
            out.append((m.group("path"), int(m.group("bytes")), m.group("ends") == words["ends_with_break"]))
    return out
