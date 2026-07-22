"""Language-agnostic 'is this a vendored / build / cache path?' guidance, driven by the canonical
per-language .gitignore templates vendored under ``ignore_templates/`` (github/gitignore, CC0).

Used to prune the lint-floor file walk (``linterprobe.collect_files``) and the evidence walk
(``probediscovery.inventory``) so a model's installed dependency tree — a virtualenv, ``node_modules``,
a ``target/`` dir, under ANY name — never floods the probe and overflows the model context. A named
venv (``handle_resolver/``) is caught by the Python template's ``lib/`` rule matching its inner
``lib/…/site-packages`` tree, regardless of the directory's own name.

Each language's template is applied ONLY to that language's files (``for_exts``): Python's ``lib/``
rule prunes a venv's site-packages without touching a Ruby project's real source ``lib/``. Where the
language is unknown (evidence collection), ``default_matcher`` unions every template's directory rules.

A small, dependency-free subset of the gitignore spec: comments/blanks, ``!`` negation (last match
wins), trailing ``/`` (directory-only), a slash anchoring to the root vs. a bare name matching at any
depth, and ``*`` / ``?`` / ``**`` globs. Faithful enough for pruning; not a full git implementation.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent / "ignore_templates"

# A file extension → the template whose ignore rules apply when collecting that extension. Grouped so
# each language's rules touch only its own source (no cross-language `lib/` contamination).
_EXT_TEMPLATE = {
    "py": "Python", "pyi": "Python", "pyw": "Python",
    "js": "Node", "mjs": "Node", "cjs": "Node", "jsx": "Node",
    "ts": "Node", "tsx": "Node",
    "rb": "Ruby", "rake": "Ruby", "gemspec": "Ruby",
    "php": "Composer",
    "rs": "Rust",
    "go": "Go",
    "java": "Java", "kt": "Java", "kts": "Java",
}


class _Rule:
    __slots__ = ("negate", "dir_only", "regex")

    def __init__(self, negate: bool, dir_only: bool, regex: "re.Pattern"):
        self.negate = negate
        self.dir_only = dir_only
        self.regex = regex


def _translate(pat: str) -> str:
    """A gitignore glob body (no leading `!`, no anchoring/trailing slash) → a regex fragment that
    matches one relative path. ``**`` spans directories; ``*`` and ``?`` stop at ``/``."""
    out: list[str] = []
    i, n = 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            if pat[i:i + 2] == "**":
                out.append(".*")
                i += 2
                if i < n and pat[i] == "/":  # `**/` — the `.*` already spans the slash
                    i += 1
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def _compile(line: str) -> _Rule | None:
    negate = line.startswith("!")
    if negate:
        line = line[1:]
    dir_only = line.endswith("/")
    line = line.rstrip("/")
    if not line:
        return None
    # A slash anywhere (after the trailing one is stripped) anchors the pattern to the root; a bare
    # name matches at any depth. Either way it also matches everything BELOW a matched directory.
    anchored = "/" in line
    if line.startswith("/"):
        line = line[1:]
    body = _translate(line)
    rx = (f"^{body}(/.*)?$") if anchored else (f"(^|.*/){body}(/.*)?$")
    return _Rule(negate, dir_only, re.compile(rx))


@lru_cache(maxsize=None)
def _rules(template: str) -> tuple:
    try:
        text = (_DIR / f"{template}.gitignore").read_text(encoding="utf-8")
    except OSError:
        return ()
    rules = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        r = _compile(line)
        if r is not None:
            rules.append(r)
    return tuple(rules)


class Matcher:
    """A compiled set of gitignore rules. ``ignored(relpath, is_dir)`` applies them in order — last
    match wins — so negation (``!keep/``) can re-include. ``relpath`` is workspace-root-relative."""

    __slots__ = ("_rules",)

    def __init__(self, rules: tuple):
        self._rules = rules

    def ignored(self, relpath: str, is_dir: bool) -> bool:
        rel = relpath.strip("/")
        if not rel or rel == ".":
            return False
        result = False
        for r in self._rules:
            if r.dir_only and not is_dir:
                continue
            if r.regex.match(rel):
                result = not r.negate
        return result


_EMPTY = Matcher(())


@lru_cache(maxsize=None)
def for_exts(exts: tuple) -> Matcher:
    """A matcher for the templates that own these file extensions — applied when collecting that
    language's source. Unknown extensions contribute no rules (an empty, always-False matcher)."""
    names: list[str] = []
    for e in exts:
        t = _EXT_TEMPLATE.get(e.lower())
        if t and t not in names:
            names.append(t)
    if not names:
        return _EMPTY
    return Matcher(tuple(r for t in names for r in _rules(t)))


@lru_cache(maxsize=1)
def default_matcher() -> Matcher:
    """The union of every vendored template's rules — for a language-agnostic walk (evidence
    collection) where the file extension doesn't pin one language."""
    names = sorted(set(_EXT_TEMPLATE.values()))
    return Matcher(tuple(r for t in names for r in _rules(t)))
