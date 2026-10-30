"""The measured SHAPE of a read that could not be delivered, and the next step named from the tool menu.

A read overflows (or is refused) on SIZE, but a line range can only narrow what has LINES. Two shapes
have no line-oriented way forward: a file dominated by one very long line (minified JSON, a one-line
log, a base64 blob) -- every line range, `grep -n`, `sed -n` and `head -n` returns that whole line --
and a file that is not valid UTF-8 text at all. Both facts are already measurable where the read is
verified (the bridge holds the verified bytes), so they are measured here, once, and stated beside the
size; the remedy clause is generated from the tool menu the reader holds (R5), never assumed.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from . import prompts
from .shelltool import find_shell_tool, is_read_tool_name

_NUMBERED = re.compile(rb'\d+: ')


@dataclass(frozen=True)
class Shape:
    size: int            # bytes of the selected text (the file for a whole read, the window for a range)
    lines: int
    longest: int         # bytes of the longest line, its terminator excluded
    longest_line: int    # 1-based position of that line within the selection


def measure(body: bytes, *, numbered: bool = False, first: int = 1) -> Shape:
    """Shape of ``body``. A range read's body is ``N: text`` per line; ``numbered`` measures the text and
    reports the file's own line number (``first`` is only used when the numbering cannot be read back)."""
    parts = body.split(b'\n')
    if parts and parts[-1] == b'':
        parts.pop()
    best, at = 0, 1
    for i, line in enumerate(parts):
        if numbered:
            head = _NUMBERED.match(line)
            n = len(line) - (head.end() if head else 0)
        else:
            n = len(line)
        if n > best:
            best, at = n, i + 1
    if numbered and parts:
        head = _NUMBERED.match(parts[at - 1])
        at = int(head.group(0)[:-2]) if head else first + at - 1
    return Shape(len(body), len(parts), best, at)


def line_bound(shape: Shape) -> bool:
    """True when no line range can return less than HALF of the selection: the longest line alone is more
    than half of it. (Past that point narrowing by lines is a route that cannot get anywhere.)"""
    return shape.size > 0 and 2 * shape.longest > shape.size


# Parameter names a read tool may declare while still returning only whole lines of a file.
_WHOLE_LINE_PARAMS = frozenset({
    'path', 'file', 'file_path', 'filepath', 'filename', 'dir_path', 'start_line', 'end_line',
    'startline', 'endline', 'offset', 'limit', 'line', 'lines', 'from', 'to'})


def reads_only_whole_lines(menu) -> bool:
    """True when every read tool in ``menu`` is known to return whole lines (a path and a line window, nothing
    that counts bytes or columns). A tool with a parameter this does not recognise answers False: unknown is
    never turned into "no route exists"."""
    for tool in menu or []:
        fn = (tool.get('function') or tool) if isinstance(tool, dict) else {}
        if not is_read_tool_name(fn.get('name')):
            continue
        props = ((fn.get('parameters') or {}).get('properties') or {})
        if any(str(p).lower() not in _WHOLE_LINE_PARAMS for p in props):
            return False
    return True


def _path(path: str) -> tuple[str, str] | None:
    """(display, shell-quoted) for ``path``, or None when it is too long to quote into a command a reader would run."""
    if not isinstance(path, str) or not path or len(path.encode('utf-8')) > 1024:
        return None
    return path, shlex.quote(path)


def _facts(shape: Shape, path: str, *, window: bool) -> str:
    return prompts.fill(prompts.load_map('read_shape')['facts_window' if window else 'facts_file'],
                        path=path, size=f'{shape.size:,}', lines=f'{shape.lines:,}',
                        longest=f'{shape.longest:,}', longest_line=shape.longest_line)


def overflow_next(shape: Shape | None, path: str, menu, *, window: bool) -> str:
    """What follows "Do not repeat the whole-file read." in the not-delivered note. Today's wording for a file
    line ranges can narrow; for a long-line-dominated file the measured shape plus a route the menu holds."""
    routes = prompts.load_map('read_shape')
    if shape is None or not line_bound(shape):
        return routes['narrow']
    facts = _facts(shape, path, window=window)
    shell, quoted = (find_shell_tool(menu) if menu is not None else None), _path(path)
    if shell is not None and quoted is not None:
        return facts + ' ' + prompts.fill(routes['long_line_shell'], shell=shell['name'], qpath=quoted[1],
                                          line=shape.longest_line)
    if menu is not None and shell is None and reads_only_whole_lines(menu):
        return facts + ' ' + routes['long_line_none']
    return facts


def binary_note(size: int, path: str, menu) -> str:
    """The note for a read whose body is not valid UTF-8 text: the size, the fact, and a byte-oriented route."""
    routes = prompts.load_map('read_shape')
    shell, quoted = (find_shell_tool(menu) if menu is not None else None), _path(path)
    route = ''
    if shell is not None and quoted is not None:
        route = ' ' + prompts.fill(routes['binary_shell'], shell=shell['name'], qpath=quoted[1])
    elif menu is not None and shell is None and reads_only_whole_lines(menu):
        route = ' ' + routes['binary_none']
    return prompts.render('multipart_binary', path=path if quoted is not None else 'the requested path',
                          size=f'{size:,}', route=route)
