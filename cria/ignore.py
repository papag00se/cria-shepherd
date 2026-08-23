"""Which directories a workspace walk may skip — and the PROOF that let it.

Used by the lint-floor file walk (``linterprobe.collect_files``) and the evidence walk
(``probediscovery.inventory``) so a model's installed dependency tree — a virtualenv, ``node_modules``,
a cargo ``target/``, under ANY name — never floods the probe and overflows the model context.

This used to union eight vendored ``.gitignore`` templates. It could not stay. A VCS's "do not track
this" is a different question from "the author did not write this": Python's template lists ``lib/``,
``build/``, ``dist/`` and ``env/`` with no anchor, so a bare name matched at ANY depth — a Python
package the model had just written into ``lib/`` was pruned from the lint floor, and the gate then
said "every source file passes its syntax check" about code it never opened. A hand-kept SKIP_DIRS
list beside it pruned ``dist``, ``build``, ``target``, ``env`` and ``venv`` by name alone, for every
language at once.

So the rule is now: skip a directory only on PROOF that a tool generated it, and hand the caller the
proof so the sentence about a clean walk can say what it did not read (#11b — a mechanism may only
speak about what it reached). Proof is one of two things, and no name is guessed at:

* the directory's name is owned by a tool — a package manager or a VCS creates it, nothing an author
  writes lives there, and the name means the same thing in every language;
* the directory CONTAINS a marker a tool wrote: ``pyvenv.cfg`` (a virtualenv under any name — the
  ``handle_resolver/`` case), ``CACHEDIR.TAG`` (the cross-tool cache standard, cargo's ``target/``),
  a ``site-packages`` or ``maven-status`` child, a setuptools ``bdist.*``, or a PAIR that
  means something neither name does alone (``gems`` beside ``specifications`` is a RubyGems
  install root; ``composer`` beside ``autoload.php`` is composer's ``vendor/``).

An ambiguously-named directory with no marker — ``lib``, ``build``, ``dist``, ``out``, ``target``,
``env`` — is WALKED. Reading a stale build copy costs a duplicate finding; not reading the author's
source costs a false clean.
"""

from __future__ import annotations

from typing import Callable, Optional

# A package manager or a VCS creates these; the name is theirs in every ecosystem, and an author's
# own source is never inside one. Kept small on purpose: a name earns a place here only when it
# cannot also be something a person wrote.
_TOOL_OWNED = (
    ".git", ".hg", ".svn", ".codex-multi",
    "node_modules", "bower_components", ".yarn", ".pnpm-store",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox", ".eggs",
    "site-packages", "dist-packages",
    ".gradle", ".m2", ".cargo", ".bundle",
    ".terraform", ".next", ".nuxt", ".parcel-cache", ".sass-cache",
)

# A file or directory a tool writes INSIDE the directory it generated. This is what catches a tree
# whose own name proves nothing — a venv the model called `handle_resolver/`.
_MARKER_FILES = ("pyvenv.cfg", "CACHEDIR.TAG")
_MARKER_DIRS = ("site-packages", "dist-packages", "maven-status", "maven-archiver")
_MARKER_PREFIXES = ("bdist.",)  # setuptools' build/bdist.linux-x86_64
# A PAIR that means something no single name does. `gems` and `specifications` are each plausible on
# their own; together they are a RubyGems install root, which is what `bundle install --path` writes
# at `vendor/bundle/ruby/<abi>/`. `composer` plus `autoload.php` is the same shape for PHP.
#
# Ruby and PHP were the two ecosystems with no proof here at all, and it destroyed their gates.
# Measured across the 87 archived run workspaces: 26 of 35 `shipping-rates-rb` workspaces compose a
# gate whose sections cannot fit one result. Worst case 370 `.rb` files collected of which 363 are
# under `vendor/`, 372 probes, a 551,045-byte script, each section floored at 700 bytes against a
# 9,000-byte cap. Every other language: 0 over budget, 3 to 7 probes. Reproduced identically for an
# ordinary composer tree: 425 `.php` files, 423 under `vendor/`, 426 probes, 645,956 bytes.
# `MAX_FLOOR_FILES_PER_LANG = 100_000` is not a bound on anything.
_MARKER_PAIRS = (
    ("gems", "specifications"),      # bundle install --path → vendor/bundle/ruby/<abi>/
    ("composer", "autoload.php"),    # composer install → vendor/
)

Children = Callable[[], Optional[list[str]]]


def generated(name: str, children: Children) -> Optional[str]:
    """The proof that a tool generated this directory, or None to walk into it.

    ``children`` is called only when the name alone decides nothing, and may return None for a
    directory that could not be listed — which is NOT proof of anything, so the walk proceeds (#23c:
    unknown is its own answer, and it is not "yes")."""
    if name in _TOOL_OWNED:
        return f"{name} (a tool owns this name)"
    names = children()
    if not names:
        return None
    for m in _MARKER_FILES:
        if m in names:
            return f"{name} (contains {m})"
    for m in _MARKER_DIRS:
        if m in names:
            return f"{name} (contains {m}/)"
    for p in _MARKER_PREFIXES:
        for n in names:
            if n.startswith(p):
                return f"{name} (contains {n})"
    have = set(names)
    for pair in _MARKER_PAIRS:
        if have.issuperset(pair):
            return f"{name} (contains {pair[0]} and {pair[1]})"
    return None
