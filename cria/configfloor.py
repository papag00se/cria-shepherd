"""The config-file syntax floor, decided in cria: does a TOML, JSON or XML file of the project parse.

It used to be three Python one-liners the harness ran as checks of the completion gate (`python3 -I -c '<tomllib|json|xml.etree loop>' <files>`).
The gate asks the harness for nothing of the kind now: cria reads each file through the ``read`` primitive (``cria.floorops``), parses the bytes here, and
the gate's section for the check is what the one-liner printed, line for line: ``<path>: <the parser's own message>`` for each file that does not parse,
and exit status 1 when any did.

The messages are the parsers' own (``tomllib.TOMLDecodeError``, ``json.JSONDecodeError``, ``xml.etree.ElementTree.ParseError``, ``UnicodeDecodeError``
and the ``OSError`` text), because the model reads them and they carry the line and column; the three one-liners printed ``'%s: %s' % (path, error)``
and so does this module. A file is read as bytes and decoded as UTF-8 (the old JSON check opened the file in text mode, so a CR or CRLF line end is one
LF before the parser sees it, and so it is here).

What is parsed is bounded: ``FILE_MAX`` bytes (a larger file is not parsed, and the check does not report, it did not run).
"""
import json
import os
import xml.etree.ElementTree as ElementTree

try:
    import tomllib
except ModuleNotFoundError:                 # Python < 3.11 without the standard library parser: the check abstains, as the one-liner did
    tomllib = None

FILE_MAX = 4 * 1024 * 1024
# What the gate shows of a check cria itself evaluates, in the place a command stands (`shlex.join` of the argv: ``<head> <file> ...``). They are names
# of checks, not commands the model could run.
HEADS = {'toml': 'toml-syntax', 'json': 'json-syntax', 'xml': 'xml-syntax'}


def format_of(kind: str, composed_by_cria: bool, command) -> str:
    """The format of a syntax check cria evaluates itself (``toml``, ``json`` or ``xml``), or ``''``: what a persisted check names (its kind, who composed
    it, its argv) is all the gate's result keeps of it."""
    head = command[0] if command else ''
    return next((fmt for fmt, name in HEADS.items() if name == head), '') if composed_by_cria and kind == 'SyntaxCheck' else ''


def _text(raw: bytes) -> str:
    return raw.decode()


def _toml(raw: bytes) -> None:
    tomllib.loads(_text(raw))


def _json(raw: bytes) -> None:
    json.loads(_text(raw).replace('\r\n', '\n').replace('\r', '\n'))          # a text-mode `open()` reads every line end as LF


def _xml(raw: bytes) -> None:
    ElementTree.fromstring(raw)


PARSERS = {'toml': _toml, 'json': _json, 'xml': _xml}


def error(fmt: str, raw: bytes, path: str) -> str:
    """The line the one-liner printed for a file that does not parse (``<path>: <message>``), or ``''`` when it parses (or when no parser exists)."""
    if fmt == 'toml' and tomllib is None:
        return ''
    try:
        PARSERS[fmt](raw)
    except Exception as exc:                # noqa: BLE001 - every parser's failure is the finding, as `except Exception` was
        return f'{path}: {exc}'
    return ''


def unreadable(path: str, code: int) -> str:
    """The line for a file the harness could not read: Python's own text for the ``OSError`` the one-liner's ``open`` raised."""
    return f'{path}: {OSError(code, os.strerror(code), path)}'
