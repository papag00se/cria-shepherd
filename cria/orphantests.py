"""Test files the test runner cannot SEE — found deterministically, stated as a fact.

Measured on maple run 2 (ada-handles_maple-preview_codex_poff_1785973706): the model wrote a
19KB pytest suite named ``pytest_da_resolvers.py``. pytest collects ``test_*.py`` /
``*_test.py`` only, so every run reported "no tests ran" — a signal the gate treats as benign
by design (genuinely testless projects exist, and scolding them was the false-red class). The
run flatlined for 30 minutes with real tests invisible on disk and lost the unit-test point.

The discriminator is the F811 pattern again: keep the benign default, and read the disk to
tell the two cases apart. When the runner collected NOTHING and a file on disk CONTAINS test
functions under a name the runner's pattern cannot match, that is a checkable fact worth an
error-class finding — the coder is told the file, the count, and the pattern, and renames it
itself. cria NEVER renames the file: the model's context holds the old name, so a
behind-the-back rename turns every later edit into a phantom-target miss (the stale-context
class), and cria does not write into the user's workspace.

Language-agnostic by the same contract as the probe stack: one detector per supported test
runner's collection rule (pytest, go test, jest/vitest-style JS/TS). Rust is deliberately
absent — ``#[test]`` functions are collected by the build, not by filename. Conservative on
purpose: only files whose CONTENT matches the runner's own test shape are flagged, and the
gate consults this only when the run's test signal was "collected nothing".
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from . import ignore

# Bounds: a workspace scan that runs inside gate-output cleaning must stay cheap. Depth and
# file-count caps large enough for any suite workspace, small enough to be harmless on a
# monorepo; files above the size cap are skipped (a 5MB "test file" is data, not a suite).
_MAX_DEPTH = 6
_MAX_FILES = 4000
_MAX_BYTES = 512 * 1024

_PY_TEST_DEF = re.compile(r"^\s*def (test_\w+)\s*\(", re.M)
_PY_TEST_CLASS = re.compile(r"^\s*class \w+\([^)]*TestCase[^)]*\)", re.M)
_PY_NAME_OK = re.compile(r"^(test_.*|.*_test)\.py$")

_GO_TEST_FUNC = re.compile(r"^func (Test\w+)\s*\(\w+ \*testing\.T\)", re.M)

_JS_DESCRIBE = re.compile(r"\bdescribe\s*\(")
_JS_CASE = re.compile(r"\b(?:it|test)\s*\(")
_JS_NAME_OK = re.compile(r".*\.(test|spec)\.[jt]sx?$")


@dataclass(frozen=True)
class OrphanTests:
    """One file the runner cannot collect: where, how many tests, and the pattern it misses."""
    path: str      # workspace-relative
    n_tests: int
    pattern: str   # the runner's collection rule, stated for the finding
    language: str


def orphan_test_files(root: str) -> list[OrphanTests]:
    """Every file under ``root`` whose CONTENT is a test suite but whose NAME the language's
    test runner will never collect. Empty list on any doubt — missing root, unreadable files,
    ignored trees (venv/node_modules/.git via the standard ignore rules)."""
    if not root or not os.path.isdir(root):
        return []
    matcher = ignore.default_matcher()
    out: list[OrphanTests] = []
    seen = 0
    base = os.path.realpath(root)
    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = os.path.relpath(dirpath, base)
        depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
        if depth >= _MAX_DEPTH:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if not matcher.ignored(os.path.join("" if rel_dir == "." else rel_dir, d), True)]
        for name in filenames:
            rel = name if rel_dir == "." else os.path.join(rel_dir, name)
            if matcher.ignored(rel, False):
                continue
            seen += 1
            if seen > _MAX_FILES:
                return out
            found = _classify(os.path.join(dirpath, name), rel)
            if found is not None:
                out.append(found)
    out.sort(key=lambda o: o.path)
    return out


def _classify(full: str, rel: str) -> OrphanTests | None:
    name = os.path.basename(rel)
    lower = name.lower()
    if lower.endswith(".py"):
        if _PY_NAME_OK.match(lower) or lower == "conftest.py":
            return None
        text = _read(full)
        n = len(_PY_TEST_DEF.findall(text)) or (
            len(re.compile(r"^\s*def (test_?\w*)\s*\(", re.M).findall(text))
            if _PY_TEST_CLASS.search(text) else 0)
        if _PY_TEST_CLASS.search(text) and n == 0:
            n = 1   # a TestCase class whose methods we couldn't count is still a suite
        if n:
            return OrphanTests(rel, n, "test_*.py or *_test.py", "python")
        return None
    if lower.endswith(".go"):
        if lower.endswith("_test.go"):
            return None
        n = len(_GO_TEST_FUNC.findall(_read(full)))
        if n:
            return OrphanTests(rel, n, "*_test.go", "go")
        return None
    if lower.endswith((".js", ".jsx", ".ts", ".tsx")):
        if _JS_NAME_OK.match(lower) or "__tests__" in rel.split(os.sep):
            return None
        text = _read(full)
        if _JS_DESCRIBE.search(text) and _JS_CASE.search(text):
            return OrphanTests(rel, len(_JS_CASE.findall(text)),
                               "*.test.* / *.spec.* (or a __tests__/ directory)", "js")
        return None
    return None


def _read(full: str) -> str:
    try:
        if os.path.getsize(full) > _MAX_BYTES:
            return ""
        with open(full, "rb") as fh:
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def findings(root: str) -> list[str]:
    """The model-facing error-class lines, one per orphan file — the fact, the count, the
    pattern; the rename is the coder's to make (state the fact, prescribe nothing further)."""
    return [f"{o.path}: holds {o.n_tests} test function(s) the test runner cannot collect — "
            f"the filename does not match the runner's pattern ({o.pattern}); rename the file "
            f"so these tests actually run"
            for o in orphan_test_files(root)]


# The runner-said-nothing-ran markers, per supported runner. Consulted by the gate ONLY to
# decide whether the disk scan is worth asking for — the scan result, not the marker, is the
# finding.
_ZERO_TESTS_MARKERS = ("no tests ran", "[no test files]", "no tests found")


def zero_tests_marker(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _ZERO_TESTS_MARKERS)
