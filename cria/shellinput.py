"""Lossless shell input layout, not a shell interpreter.

Offsets always address the original string. A projection blanks owned input and
syntax, retaining newlines and *every other header byte*, including redirects
AFTER a heredoc delimiter. Callers must separately judge input execution; the
projection alone is never proof that a body is inert.
"""
from __future__ import annotations

import os
import re
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
    # The backslash-escaped quote characters inside ANSI-C strings (`$'\''`): see ``ansi_c_end``.
    literal: tuple[tuple[int, int], ...] = ()

    @property
    def shell(self) -> str:
        ranges = list(self.syntax) + list(self.literal)
        for doc in self.documents:
            ranges.extend(((doc.operator, doc.word_end), doc.body, doc.terminator))
        return _project(self.source, ranges)

    def without_documents(self) -> str:
        """The source with every heredoc operator+delimiter word, body and terminator line blanked (newlines
        kept, same length): the commands AROUND the documents, with the documents read as the data they are
        (an unquoted body's own `$( … )` is still reachable through ``HereDoc.text`` + ``expansions``)."""
        return _project(self.source, [r for doc in self.documents
                                      for r in ((doc.operator, doc.word_end), doc.body, doc.terminator)])

    @property
    def literal_shell(self) -> str:
        """The source with ONLY the escaped quotes inside ANSI-C strings blanked: every other byte,
        comments and heredocs included, is unchanged. A reader that tracks single quotes the POSIX way
        (shlex, the boundary owner's quote scanners) then ends each `$'…'` where bash ends it."""
        return _project(self.source, self.literal)


def ansi_c_end(source: str, start: int) -> int | None:
    """The index of the quote that closes the ANSI-C string (`$'…'`) whose body begins at ``start``,
    or None when it is unterminated. Bash finds that end before it decodes anything: a backslash takes
    the next character with it, whatever it is (`\\'` and `\\\\` included), so only an unescaped `'`
    closes. A POSIX single-quote reader instead ends `$'\\''` at its second character; for
    `echo $'\\'' ; rm -rf DIR #'` it saw one quoted word where bash runs `rm -rf DIR`."""
    j = start
    while j < len(source):
        if source[j] == '\\':
            j += 2
            continue
        if source[j] == "'":
            return j
        j += 1
    return None


def _escaped_quotes(source: str, start: int, end: int) -> list[tuple[int, int]]:
    """The escaped `'` characters of the ANSI-C body ``source[start:end]``, as projection ranges."""
    out, j = [], start
    while j < end:
        if source[j] == '\\':
            if source[j + 1:j + 2] == "'":
                out.append((j + 1, j + 2))
            j += 2
            continue
        j += 1
    return out


def decode_ansi_c(source: str, projection: str | None = None) -> str:
    """Render bash ANSI-C quoted words as ordinary quoted data for shell analysis.

    The optional same-length projection retains the caller's masked input and syntax;
    source supplies the original escape bytes. This is a lexical view, never a command
    to execute. Expansion results outside the quotes remain unresolved.
    """
    view = source if projection is None else projection
    if "$'" not in source:
        return view
    out, i, quote = [], 0, ''
    simple = {'a': 7, 'b': 8, 'e': 27, 'E': 27, 'f': 12, 'n': 10,
              'r': 13, 't': 9, 'v': 11, '\\': 92, "'": 39, '"': 34, '?': 63}
    while i < len(source):
        c = source[i]
        if view[i] != c:
            out.append(view[i]); i += 1; continue
        if c == '\\' and quote != "'":
            out.append(view[i:i + 2]); i += 2; continue
        if quote:
            out.append(c)
            if c == quote:
                quote = ''
            i += 1; continue
        if c == '#' and (i == 0 or source[i - 1] in _COMMENT_LEAD):
            end = source.find('\n', i)
            end = len(source) if end < 0 else end
            out.append(view[i:end]); i = end; continue
        if source.startswith('$$', i):
            out.append(view[i:i + 2]); i += 2; continue
        if source.startswith("$'", i):
            end = ansi_c_end(source, i + 2)
            if end is None:
                out.append(view[i:]); break
            body, data, j = source[i + 2:end], bytearray(), 0
            while j < len(body):
                c = body[j]
                if c != '\\' or j + 1 == len(body):
                    data.extend(os.fsencode(c)); j += 1; continue
                esc = body[j + 1]
                if esc in simple:
                    data.append(simple[esc]); j += 2
                elif esc in '01234567':
                    m = re.match(r'[0-7]{1,3}', body[j + 1:])
                    data.append(int(m.group(), 8) & 255); j += 1 + len(m.group())
                elif esc in 'xuU':
                    limit = {'x': 2, 'u': 4, 'U': 8}[esc]
                    m = re.match(r'[0-9a-fA-F]{1,%d}' % limit, body[j + 2:])
                    if not m:
                        data.extend(os.fsencode('\\' + esc)); j += 2; continue
                    value = int(m.group(), 16)
                    if esc == 'x':
                        data.append(value)
                    elif value <= 0x10ffff:
                        data.extend(chr(value).encode('utf-8', 'surrogatepass'))
                    else:
                        data.extend(os.fsencode('\\' + esc + m.group()))
                    j += 2 + len(m.group())
                elif esc == 'c' and j + 2 < len(body):
                    control = os.fsencode(body[j + 2])
                    data.append(127 if control == b'?' else control[0] & 31)
                    data.extend(control[1:])
                    j += 3
                    if control == b'\\' and body[j:j + 1] == '\\':
                        j += 1
                else:
                    data.extend(os.fsencode('\\' + esc)); j += 2
            value = os.fsdecode(bytes(data).split(b'\0', 1)[0])
            # Double quotes keep shell metacharacters inert, including a decoded dollar.
            out.append('"' + re.sub(r'([\\"$`])', r'\\\1', value) + '"')
            i = end + 1; continue
        if c in "\"'":
            quote = c
        out.append(c); i += 1
    return ''.join(out)


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
    docs, syntax, pending, literal = [], [], [], []
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
        if c == '$' and source.startswith('$', i + 1):
            i += 2              # `$$` is the shell's pid: a quote after it is an ordinary quote
            continue
        if c == '$' and source.startswith("'", i + 1):
            end = ansi_c_end(source, i + 2)
            if end is None:
                return Layout(source, tuple(docs), tuple(syntax), True, tuple(literal))
            literal.extend(_escaped_quotes(source, i + 2, end))
            i = end + 1
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
                return Layout(source, tuple(docs), tuple(syntax), True, tuple(literal))
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
                    return Layout(source, tuple(docs), tuple(syntax), True, tuple(literal))
            pending = []
            continue
        i += 1
    return Layout(source, tuple(docs), tuple(syntax), bool(pending or quote), tuple(literal))


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

    An ANSI-C string (`$'…'`, see ``ansi_c_end``) is data ended where bash ends it: at the top level
    of a script (``shell``) and in every substitution body, double-quoted or not. After `$$` a quote is
    an ordinary quote.
    """
    commands, i, double_quote, at_start = [], 0, False, True
    while i < len(source):
        if shell and source[i] == '$' and not double_quote and source.startswith('$', i + 1):
            i, at_start = i + 2, False          # `$$`: the quote after it is an ordinary quote
            continue
        if shell and source[i] == '$' and not double_quote and source.startswith("'", i + 1):
            end = ansi_c_end(source, i + 2)     # an ANSI-C string is data, ended where bash ends it
            if end is None:
                return commands, True
            i, at_start = end + 1, False
            continue
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
                elif c == '$' and source.startswith('$', j + 1):
                    j, body_start = j + 2, False
                    continue
                elif c == '$' and source.startswith("'", j + 1):
                    # A substitution body is a script even inside double quotes: its ANSI-C strings
                    # end where bash ends them, not at an escaped quote.
                    end = ansi_c_end(source, j + 2)
                    if end is None:
                        return commands, True
                    j, body_start = end + 1, False
                    continue
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
