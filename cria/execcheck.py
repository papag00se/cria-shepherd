"""Workspace entry-point and README-command readers — what the project says it can run.

HISTORY: this module used to host a live-execution check (the model stated a run command, cria
corroborated it against the README and a real entry point, then ran it). That seat was removed
2026-08-18 (``98952c23``): cria no longer executes anything a model named. What remains is the two
deterministic READERS that corroboration used — :func:`entrypoints` (files that are programs by
their own language's convention) and :func:`readme_commands` (launcher lines the README documents) —
plus ``_SKIP_DIRS``/``_SKIP_PREFIXES``, the shared walk exclusions. Production's only consumer is
``loop`` reading ``_SKIP_DIRS``; the two readers are used by ``suite/replay_logic`` alone.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from . import probediscovery, wsview

# Command heads a README line has to start with before cria will call it a command the project
# declares. Deliberately a short, stable list of language launchers — it is read by
# `readme_commands`, which `suite/replay_logic` uses.
_RUNNERS = frozenset({"python", "python3", "node", "ruby", "php", "java", "go", "cargo", "npm",
                      "yarn", "pnpm", "bundle", "rake", "make", "mvn", "gradle", "dotnet", "deno",
                      "bun", "sh", "bash", "./"})


@dataclass(frozen=True)
class EntryConvention:
    """How THIS language says 'this file is a program, not a library'."""
    exts: tuple[str, ...]
    marker: str                       # regex that proves a source file is an entry point
    manifests: tuple[tuple[str, str], ...] = ()   # (manifest filename, regex declaring a runnable target)
    label: str = ""


ENTRY_CONVENTIONS: tuple[EntryConvention, ...] = (
    EntryConvention(("py",), r"^\s*if\s+__name__\s*==\s*['\"]__main__['\"]",
                    (("pyproject.toml", r"^\s*\[project\.scripts\]"),
                     ("setup.py", r"entry_points\s*=")),
                    "a `if __name__ == \"__main__\"` block, or a [project.scripts] entry"),
    EntryConvention(("go",), r"^\s*func\s+main\s*\(\s*\)", (), "a func main() in package main"),
    EntryConvention(("rs",), r"^\s*(?:pub\s+)?fn\s+main\s*\(\s*\)",
                    (("Cargo.toml", r"^\s*\[\[bin\]\]"),), "a fn main(), or a [[bin]] target"),
    EntryConvention(("js", "mjs", "cjs", "ts"), r"^#!.*node|require\.main\s*===\s*module",
                    (("package.json", r'"(?:bin|scripts)"\s*:'),),
                    "a \"bin\"/\"scripts\" entry in package.json, or require.main === module"),
    EntryConvention(("java",), r"public\s+static\s+void\s+main\s*\(", (), "a public static void main"),
    EntryConvention(("rb",), r"^\s*if\s+__FILE__\s*==\s*\$0|^#!.*ruby", (),
                    "a `if __FILE__ == $0` block or a ruby shebang"),
    EntryConvention(("php",), r"^#!.*php", (), "a php shebang"),
)

# Imported, not restated — see groundtruth.BUILD_ARTIFACT_DIRS for why two copies of this went out
# of sync and what it cost.
from .groundtruth import BUILD_ARTIFACT_DIRS as _SKIP_DIRS  # noqa: E402
from .groundtruth import INSTALL_PREFIXES as _SKIP_PREFIXES  # noqa: E402

# A TEST file is not the program. Test files routinely carry their own runner block
# (`if __name__ == "__main__": unittest.main()`), and counting it meant a workspace whose only
# entry point was in test_resolve_handle.py read as "this project has a program" — measured on
# mellum2 attempt 3, whose deliverable ends on a function definition and prints nothing.
#
# The convention table owns the question (probediscovery.looks_like_a_test_path). This file used to
# keep its own regex, which required `Test`/`Tests` to END the stem — so JUnit's PREFIX convention
# `TestImporter.java`, `ImporterTestCase.java` and jest's `__tests__/` directory all read as ordinary
# source here while the table already knew all three.
_is_test_file = probediscovery.looks_like_a_test_path


def entrypoints(root: str) -> list[str]:
    """Files on disk that ARE programs, by their own language's convention. Never a claim."""
    found: list[str] = []
    if not root:
        return found
    view = wsview.current(root)
    tree = view.walk(root, skip_names=_SKIP_DIRS, skip_prefixes=_SKIP_PREFIXES)
    if tree is None:
        return found      # nobody has surveyed this workspace yet — cria names no programs
    by_ext = {e: c for c in ENTRY_CONVENTIONS for e in c.exts}
    # …AND A DEPENDENCY TREE IS NOT THIS PROJECT'S PROGRAM. `_SKIP_DIRS` is keyed on directory
    # NAMES and deliberately does not hold `vendor` — a PHP or vendored-Go repo keeps real
    # deliverables there. An INSTALL destination is a relative PATH, which is exactly why
    # `INSTALL_PREFIXES` exists and why the workspace inventory folds it; this walk was the one
    # reader that did not. Both exclusions are handed to the walk itself (see View.walk), because a
    # list of triples cannot be pruned the way `os.walk`'s dirnames could.
    #
    # Measured on `shipping-rates-rb x gemma4` 1787037372, whose entire answer to "PROGRAMS THAT
    # ACTUALLY EXIST IN THE PROJECT DIRECTORY RIGHT NOW" was two files of somebody else's gem:
    #     vendor/bundle/ruby/3.2.0/gems/minitest-6.0.6/lib/minitest/complete.rb
    #     vendor/bundle/ruby/3.2.0/gems/minitest-6.0.6/lib/minitest/find_minimal_combination.rb
    # The exec-intent prompt hands that list to a judge under that heading and tells it the
    # command "must run something this project actually has: a file from the list". So cria
    # invited a model to run minitest's internals as the delivered program (#5b, #11b — a
    # workspace reader cannot judge third-party source).
    for dirpath, _dirnames, filenames in tree:
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            if _is_test_file(rel):
                continue
            conv = by_ext.get(name.rsplit(".", 1)[-1].lower()) if "." in name else None
            if conv:
                body = view.read(os.path.join(dirpath, name))
                if body is not None and re.search(conv.marker, body, re.M):
                    found.append(rel)
            for manifest, pattern in (c for conv2 in ENTRY_CONVENTIONS for c in conv2.manifests):
                if name == manifest:
                    body = view.read(os.path.join(dirpath, name))
                    if body is not None and re.search(pattern, body, re.M):
                        found.append(rel)
    return sorted(set(found))


def readme_commands(root: str) -> list[str]:
    """Run commands the README documents. A command there is an artifact the model committed to —
    not a sentence in a chat turn."""
    out: list[str] = []
    if not root:
        return out
    view = wsview.current(root)
    for name in (view.listdir(root) or []):
        if not name.lower().startswith("readme"):
            continue
        text = view.read(os.path.join(root, name))
        if text is None:
            continue
        for line in text.splitlines():
            s = line.strip().lstrip("$").strip()
            if not s or s.startswith(("#", ">", "<", "|")):
                continue
            head = s.split()[0] if s.split() else ""
            if head in _RUNNERS or head.startswith("./"):
                out.append(s)
    return out
