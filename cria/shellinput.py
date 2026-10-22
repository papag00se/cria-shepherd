"""Lossless shell input layout, not a shell interpreter.

Offsets always address the original string. A projection blanks owned input and
syntax, retaining newlines and *every other header byte*, including redirects
AFTER a heredoc delimiter. Callers must separately judge input execution; the
projection alone is never proof that a body is inert.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HereDoc:
    operator: int
    word_end: int
    body: tuple[int, int]
    terminator: tuple[int, int]
    quoted: bool
    strip_tabs: bool

    def text(self, source: str) -> str:
        text = source[slice(*self.body)]
        if self.strip_tabs:
            text = ''.join(line.lstrip('\t') for line in text.splitlines(keepends=True))
        if not self.quoted:
            out, i = [], 0
            while i < len(text):
                if text.startswith('\\\n', i):
                    i += 2
                    continue
                if text.startswith('\\\\', i):
                    out.append('\\\\'); i += 2
                    continue
                out.append(text[i]); i += 1
            text = ''.join(out)
        return text


@dataclass(frozen=True)
class Layout:
    source: str
    documents: tuple[HereDoc, ...]
    syntax: tuple[tuple[int, int], ...]
    error: bool = False

    @property
    def shell(self) -> str:
        chars = list(self.source)
        ranges = list(self.syntax)
        for doc in self.documents:
            ranges.extend(((doc.operator, doc.word_end), doc.body, doc.terminator))
        for start, end in ranges:
            for i in range(start, end):
                if chars[i] != '\n':
                    chars[i] = ' '
        return ''.join(chars)


def _word(source: str, start: int) -> tuple[str, int, bool] | None:
    """Heredoc words undergo quote removal, NOT parameter/command expansion."""
    i, value, quoted = start, [], False
    while i < len(source) and source[i] in ' \t\r':
        i += 1
    begin = i
    while i < len(source) and source[i] not in ' \t\r\n;&|()<>':
        c = source[i]
        if c in "\"'":
            quoted = True
            quote, i = c, i + 1
            while i < len(source) and source[i] != quote:
                if quote == '"' and source[i] == '\\' and i + 1 < len(source) and source[i + 1] in '$`"\\\n':
                    i += 1
                    if source[i] == '\n':
                        i += 1
                        continue
                value.append(source[i]); i += 1
            if i == len(source):
                return None
        elif c == '\\':
            i += 1
            if i == len(source):
                return None
            if source[i] != '\n':
                quoted = True
                value.append(source[i])
        else:
            value.append(c)
        i += 1
    return (''.join(value), i, quoted) if i > begin else None


def layout(source: str) -> Layout:
    docs, syntax, pending = [], [], []
    i, quote = 0, ''
    while i < len(source):
        c = source[i]
        if c == '\\' and quote != "'":
            i += 2
            continue
        if quote:
            if c == quote:
                quote = ''
            i += 1
            continue
        if c in "\"'":
            quote = c; i += 1
            continue
        if c == '#' and (i == 0 or source[i - 1] in ' \t\r\n;&|()'):
            end = source.find('\n', i)
            end = len(source) if end < 0 else end
            syntax.append((i, end)); i = end
            continue
        # Arithmetic is not a file operand. With command substitution inside,
        # leave it visible (and do not misread shifts as input redirections).
        if source.startswith('$((', i) or source.startswith('((', i):
            end = source.find('))', i + 2)
            if end >= 0:
                end += 2
                part = source[i:end]
                if '$(' not in part[3:] and '`' not in part:
                    syntax.append((i, end))
                i = end
                continue
        if source.startswith('<<<', i):
            i += 3
            continue
        if source.startswith('<<', i):
            start = i
            tabs = source.startswith('<<-', i)
            word = _word(source, i + (3 if tabs else 2))
            if word is None:
                return Layout(source, tuple(docs), tuple(syntax), True)
            delimiter, i, quoted = word
            pending.append((start, i, delimiter, quoted, tabs))
            continue
        if c == '\n' and pending:
            i += 1
            for start, end, delimiter, quoted, tabs in pending:
                body_start = i
                while i < len(source):
                    line_start, pieces = i, []
                    while True:
                        line_end = source.find('\n', i)
                        next_line = len(source) if line_end < 0 else line_end + 1
                        line = source[i:len(source) if line_end < 0 else line_end]
                        if tabs:
                            line = line.lstrip('\t')
                        joined = (not quoted and line_end >= 0
                                  and (len(line) - len(line.rstrip('\\'))) % 2 == 1)
                        pieces.append(line[:-1] if joined else line)
                        i = next_line
                        if not joined or i == len(source):
                            break
                    if ''.join(pieces) == delimiter:
                        docs.append(HereDoc(start, end, (body_start, line_start),
                                            (line_start, next_line), quoted, tabs))
                        break
                else:
                    return Layout(source, tuple(docs), tuple(syntax), True)
            pending = []
            continue
        i += 1
    return Layout(source, tuple(docs), tuple(syntax), bool(pending or quote))


def expansions(source: str, *, shell: bool = False) -> tuple[list[tuple[int, str]], bool]:
    """Commands expanded in an UNQUOTED heredoc, even inside body quote marks.

    Escaped dollars/backticks are data; ordinary body quotes do not suppress
    expansions. Unknown/unbalanced substitutions are reported, never erased.
    """
    commands, i, double_quote = [], 0, False
    while i < len(source):
        if shell and source[i] == "'" and not double_quote:
            end = source.find("'", i + 1)
            if end < 0:
                return commands, True
            i = end + 1
            continue
        if shell and source[i] == '"':
            double_quote = not double_quote
            i += 1
            continue
        if source[i] == '\\':
            i += 2
            continue
        if source[i] == '`':
            j = i + 1
            while j < len(source) and source[j] != '`':
                j += 2 if source[j] == '\\' else 1
            if j >= len(source):
                return commands, True
            commands.append((i, source[i + 1:j])); i = j + 1
            continue
        if source.startswith('$(', i) and not source.startswith('$((', i):
            j, depth, quote = i + 2, 1, ''
            while j < len(source) and depth:
                c = source[j]
                if c == '\\' and quote != "'":
                    j += 2
                    continue
                if quote:
                    if c == quote:
                        quote = ''
                elif c in "\"'":
                    quote = c
                elif c == '(':
                    depth += 1
                elif c == ')':
                    depth -= 1
                j += 1
            if depth:
                return commands, True
            commands.append((i, source[i + 2:j - 1])); i = j
            continue
        i += 1
    return commands, False
