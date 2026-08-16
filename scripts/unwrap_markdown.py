#!/usr/bin/env python3
"""Remove columnar (hard) line-wrapping from markdown: one paragraph = one line.

Preserved verbatim: fenced code blocks, indented code blocks, table rows, headings, horizontal
rules, blank lines, and the line structure of anything ambiguous. Wrapped list items and wrapped
blockquote paragraphs are joined into a single line, keeping their marker/prefix.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# A real fence carries an empty info string or ONE language token. A line opening with ``` followed
# by a sentence is prose that column-wrapping pushed to the line start — which is how
# docs/audits/cycle-1-walk.md came to hold an unbalanced fence that silently code-blocked 150 lines
# of an audit. Requiring a plausible info string is what lets the unwrapper repair it instead of
# refusing the file.
FENCE = re.compile(r"^\s{0,3}(```|~~~)[A-Za-z0-9_+#-]{0,20}\s*$")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
SETEXT = re.compile(r"^\s{0,3}(=+|-{2,})\s*$")
HRULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
TABLE = re.compile(r"^\s{0,3}\|")
LIST = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+")
QUOTE = re.compile(r"^(\s{0,3}>\s?)")
# A line that is its own block even mid-paragraph: an HTML block or a link-reference definition.
STANDALONE = re.compile(r"^\s{0,3}(<[a-zA-Z/!]|\[[^\]]+\]:\s)")
# A bold or italic lead-in that opens a line -- "**Rule.**", "**Why.**", "*Chain.*", "**The tell.**"
# -- is a deliberate semantic break the author chose, not a column artifact. Keep it on its own line;
# the operator's objection is to wrapping at a column, not to structure.
LEADIN = re.compile(r"^\s{0,3}(\*\*|\*|__)[A-Z(][^*_]{0,80}?[.:!?)](\*\*|\*|__)")


def _is_break(line: str) -> bool:
    """True when this line must start its own output line rather than join the previous one."""
    return bool(
        not line.strip()
        or HEADING.match(line)
        or HRULE.match(line)
        or TABLE.match(line)
        or LIST.match(line)
        or STANDALONE.match(line)
        or SETEXT.match(line)
        or LEADIN.match(line)
    )


def unwrap(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    fence: str | None = None
    # `buf` holds the paragraph being accumulated; `prefix` is its blockquote marker, if any.
    buf: list[str] = []
    prefix = ""

    def flush() -> None:
        nonlocal buf, prefix
        if buf:
            out.append(prefix + " ".join(buf))
            buf, prefix = [], ""

    for i, line in enumerate(lines):
        if fence is not None:                      # inside a fenced block: verbatim
            out.append(line)
            if line.lstrip().startswith(fence):
                fence = None
            continue

        m = FENCE.match(line)
        if m:
            flush()
            fence = m.group(1)
            out.append(line)
            continue

        # An indented code block: 4+ spaces, and the paragraph buffer is empty (so it is not a
        # wrapped continuation of the line above). Left exactly as written.
        if not buf and line.startswith("    ") and line.strip():
            flush()
            out.append(line)
            continue

        q = QUOTE.match(line)
        if q:
            body = line[q.end():]
            if not body.strip():                   # `>` on its own ends the quoted paragraph
                flush()
                out.append(line)
                continue
            if buf and prefix and not _is_break(body):
                buf.append(body.strip())
            else:
                flush()
                prefix = q.group(1)
                if _is_break(body):                # a heading/list/table inside a quote
                    out.append(line)
                    prefix = ""
                else:
                    buf = [body.strip()]
            continue

        if prefix:                                 # left the blockquote
            flush()

        if _is_break(line):
            flush()
            if LIST.match(line) or LEADIN.match(line):
                # Both open a block that may ITSELF be column-wrapped, so they start a buffer
                # rather than being emitted — otherwise their own continuation lines orphan.
                buf = [line.rstrip()]
                prefix = ""
            else:
                out.append(line)
            continue

        # An ordinary continuation line.
        if buf:
            buf.append(line.strip())
        else:
            buf = [line.rstrip()]

    flush()
    if fence is not None:                          # unbalanced fence: refuse to touch the file
        raise ValueError("unbalanced code fence")
    return "\n".join(out)


def _fences(text: str) -> list[str]:
    """Every fenced block's contents, for the round-trip check — walked with the SAME fence rule
    `unwrap` uses, so the check cannot disagree with the transform about what a fence is."""
    out, cur, inside = [], [], None
    for line in text.split("\n"):
        if inside is None:
            m = FENCE.match(line)
            if m:
                inside, cur = m.group(1), []
            continue
        if line.lstrip().startswith(inside):
            out.append("\n".join(cur))
            inside = None
            continue
        cur.append(line)
    return out


def _tables(text: str) -> list[str]:
    return [ln.strip() for ln in text.split("\n") if TABLE.match(ln)]


def _words(text: str) -> list[str]:
    """Every word, with blockquote markers dropped — joining a wrapped quote removes interior `>`."""
    return " ".join(QUOTE.sub("", ln) for ln in text.split("\n")).split()


def main(paths: list[str]) -> int:
    changed = 0
    for p in paths:
        path = Path(p)
        src = path.read_text()
        try:
            got = unwrap(src)
        except ValueError as exc:
            print(f"SKIP  {p}: {exc}")
            continue
        # Invariants: no word may be lost or gained, and code/tables must survive untouched.
        if _words(src) != _words(got):
            print(f"SKIP  {p}: word stream changed")
            continue
        if _fences(src) != _fences(got):
            print(f"SKIP  {p}: fenced code changed")
            continue
        if _tables(src) != _tables(got):
            print(f"SKIP  {p}: table rows changed")
            continue
        if got != src:
            path.write_text(got)
            before = sum(1 for _ in src.split("\n"))
            after = sum(1 for _ in got.split("\n"))
            print(f"unwrapped  {p}  ({before} -> {after} lines)")
            changed += 1
    print(f"\n{changed} file(s) unwrapped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
