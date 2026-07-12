"""Prompt templates, kept as plain-text files in THIS folder so every prompt cria sends
a model can be found, read, and tuned without touching Python.

Placeholders are ``{{UPPERCASE}}`` tokens filled at call time. Double braces are used on
purpose: a literal single brace — e.g. the JSON ``{"done": true}`` the critic is told to
emit — passes through untouched. Files are re-read on every call, so editing a ``.txt``
here takes effect on the next request with no restart.

- ``load(name)``         → the whole file ``<name>.txt``, verbatim (trailing newlines trimmed).
- ``render(name, **kw)`` → ``load`` + fill every ``{{TOKEN}}`` from the keyword args.
- ``fill(text, **kw)``   → fill ``{{TOKEN}}``s in an arbitrary string (e.g. a map value).
- ``load_map(name)``     → parse a ``key = value`` file into a dict, for the two prompts
                          assembled from several fragments (the tool cheat-sheet and the
                          critic's user message). ``\\n`` in a value becomes a real newline.
"""

from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).parent


def fill(text: str, **tokens: object) -> str:
    """Replace every ``{{TOKEN}}`` in ``text`` with the matching keyword arg (the key is
    upper-cased, so ``fill(t, step=x)`` fills ``{{STEP}}``). Tokens with no arg are left
    in place; single braces are never touched."""
    for key, value in tokens.items():
        text = text.replace("{{" + key.upper() + "}}", str(value))
    return text


def load(name: str) -> str:
    """The raw text of ``<name>.txt`` with trailing newlines trimmed (editors add one;
    the prompt strings don't want it). Placeholders are left intact."""
    return (_DIR / f"{name}.txt").read_text(encoding="utf-8").rstrip("\n")


def render(name: str, **tokens: object) -> str:
    """``load(name)`` then ``fill`` its ``{{TOKEN}}``s from the keyword args."""
    return fill(load(name), **tokens)


def load_map(name: str) -> dict[str, str]:
    """Parse a ``key = value`` prompt file into a dict. Blank lines and ``#`` comments are
    skipped; a literal ``\\n`` in a value becomes a newline."""
    out: dict[str, str] = {}
    for line in load(name).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition(" = ")
        if sep:
            out[key.strip()] = value.replace("\\n", "\n")
    return out
