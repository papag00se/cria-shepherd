"""Lossless shell input layout, not a shell interpreter.

Offsets always address the original string. A projection blanks owned input and
syntax, retaining newlines and *every other header byte*, including redirects
AFTER a heredoc delimiter. Callers must separately judge input execution; the
projection alone is never proof that a body is inert.
"""
from __future__ import annotations

from dataclasses import dataclass


def _project(source, ranges, *, opaque=False):
    chars = list(source)
    for start, end in ranges:
        for i in range(start, end):
            if chars[i] != '\n':
                chars[i] = 'x' if opaque else ' '
        if opaque:
            chars[start] = '$'  # expanded operands remain unknown, never literal paths
    return ''.join(chars)


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
        ranges = list(self.syntax)
        for doc in self.documents:
            ranges.extend(((doc.operator, doc.word_end), doc.body, doc.terminator))
        return _project(self.source, ranges)


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


@dataclass(frozen=True)
class Substitution:
    start: int
    end: int
    body: tuple[int, int]

    def text(self, source: str) -> str:
        return source[slice(*self.body)]


def outer_shell(source: str, substitutions: list[Substitution]) -> str:
    """Child commands are judged separately; their cwd is not their parent's.

    Preserve original offsets and all outer syntax. An opaque dollar retains
    unresolved expansion ownership if a substitution supplies a write target.
    """
    return _project(source, ((s.start, s.end) for s in substitutions), opaque=True)


# Bash's metacharacters: a `#` that follows one of these, or opens a script, begins a COMMENT that runs to
# the next newline and in which quotes, parentheses and backticks mean nothing. Anywhere else in a word
# (`a#b`, `$#`, `${#x}`, `\#`, after a quote) it is data. The rule `dirguard._join_continuations` uses;
# `layout` above keeps its own narrower set.
_COMMENT_LEAD = " \t\n;&|()<>"


def expansions(source: str, *, shell: bool = False) -> tuple[list[Substitution], bool]:
    """Commands expanded in an UNQUOTED heredoc, even inside body quote marks.

    Escaped dollars/backticks are data; ordinary body quotes do not suppress
    expansions. Unknown/unbalanced substitutions are reported, never erased.

    With ``shell`` a real comment (see ``_COMMENT_LEAD``) is skipped to its newline wherever a script is
    being read — the text itself and the body of every `$( … )` — so an apostrophe in a comment
    (`# it's`) opens no quote and a `)` in one closes nothing.

    With ``shell`` an unquoted, unescaped process substitution (`<( … )`, `>( … )`) is a command the
    shell runs too, exactly as `$( … )` is, and is delimited the same way: its body is returned for
    judging and the outer text sees one expanded word (`/dev/fd/N` to bash). Inside double quotes, in a
    heredoc body and after a backslash it is literal text, so it is not one there. ornith1.5_9b / Java
    overnight run 1 (call 0259 and sixteen more): `diff <(grep -v x tmp/a.txt) tmp/b.txt` after
    `cd <workspace>` was refused as "cannot be established" because the outer reader met `<` then `(`.
    """
    commands, i, double_quote, at_start = [], 0, False, True
    while i < len(source):
        if shell and source[i] == "'" and not double_quote:
            end = source.find("'", i + 1)
            if end < 0:
                return commands, True
            i, at_start = end + 1, False
            continue
        if shell and source[i] == '"':
            double_quote = not double_quote
            i, at_start = i + 1, False
            continue
        if shell and source[i] == '#' and at_start and not double_quote:
            end = source.find('\n', i)
            i = len(source) if end < 0 else end
            continue
        if source[i] == '\\':
            i, at_start = i + 2, False
            continue
        if source[i] == '`':
            j = i + 1
            while j < len(source) and source[j] != '`':
                j += 2 if source[j] == '\\' else 1
            if j >= len(source):
                return commands, True
            commands.append(Substitution(i, j + 1, (i + 1, j))); i, at_start = j + 1, False
            continue
        process = (shell and not double_quote and source[i] in '<>'
                   and source.startswith('(', i + 1))
        if process or (source.startswith('$(', i) and not source.startswith('$((', i)):
            # The body is a script; a `$(` inside it (even inside double quotes) opens a script of its own
            # whose quotes are its own, so each level keeps its own quote and parenthesis depth.
            j, quote, body_start = i + 2, '', True
            levels = [[1, '']]                      # [open parentheses, quote of the text AROUND this level]
            while j < len(source) and levels:
                c = source[j]
                if c == '\\' and quote != "'":
                    j, body_start = j + 2, False
                    continue
                if quote:
                    if c == quote:
                        quote = ''
                    elif quote == '"' and c == '$' and source.startswith('(', j + 1) and not source.startswith('((', j + 1):
                        levels.append([1, quote])
                        quote, body_start, j = '', True, j + 2
                        continue
                    elif quote == '"' and c == '`':
                        k = j + 1
                        while k < len(source) and source[k] != '`':
                            k += 2 if source[k] == '\\' else 1
                        j = k
                    body_start = False
                elif c in "\"'":
                    quote, body_start = c, False
                elif shell and c == '#' and body_start:
                    end = source.find('\n', j)
                    j = len(source) if end < 0 else end
                    continue
                elif c == '`':
                    k = j + 1
                    while k < len(source) and source[k] != '`':
                        k += 2 if source[k] == '\\' else 1
                    j, body_start = k, False
                elif c == '$' and source.startswith('(', j + 1) and not source.startswith('((', j + 1):
                    levels.append([1, quote])
                    quote, body_start, j = '', True, j + 2
                    continue
                elif c == '(':
                    levels[-1][0] += 1
                    body_start = True
                elif c == ')':
                    levels[-1][0] -= 1
                    body_start = True
                    if levels[-1][0] == 0:
                        quote = levels.pop()[1]
                        if not levels:
                            j += 1
                            break
                else:
                    body_start = c in _COMMENT_LEAD
                j += 1
            if levels:
                return commands, True
            commands.append(Substitution(i, j, (i + 2, j - 1))); i, at_start = j, False
            continue
        at_start = source[i] in _COMMENT_LEAD
        i += 1
    return commands, False
