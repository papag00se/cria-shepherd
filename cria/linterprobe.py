"""Always-available syntax floor — deterministic parse/lint ground truth for a workspace.

Small local models routinely declare "done" over a workspace that does not even PARSE.
Before any reasoner spends tokens judging a completion claim — and before cria trusts a
coder's final prose — the cheapest possible objection is the one every dev box can already
raise: run the interpreter's own syntax check over the files on disk. This module is that
floor. It needs no project config, no test suite, no discovery: if ``.py`` files exist,
``python3 -m py_compile`` must pass (escalating to ``pyflakes`` for undefined-name-class
defects when it does); if ``.js``/``.mjs``/``.cjs`` files exist, ``node --check`` must
pass. A dirty floor produces exact ``file:line`` errors the coder is re-prompted with
(``nudge_text``); the reasoner gets a routing verdict either way (``probe_digest`` —
"this is a syntax error" vs "the defect is NOT a syntax error, look elsewhere").

Two deliberate asymmetries, both load-bearing:

- **An empty report is clean.** No recognized source files, or no checker binary, means
  no deterministic objection — the floor must never block completion on its own silence.
- **Absent tools are "skipped", never "failed".** A box without node (or without the
  pyflakes module) has not flunked the check; it has abstained.

Port of codex-local's ``routing/src/linter_probe.rs`` (spec: scratchpad linter-gate.md §1).
No regexes upstream, none here — the scanners are plain string operations.

**cria owns no executors.** Upstream spawned subprocesses inline; cria is a proxy that may
not be co-located with anything allowed to execute. So this module is split into pure
composers (``py_compile_argv``/``pyflakes_argv``/``node_check_argv``), pure interpreters
(the ``check_*`` result logic and all report rendering), and a thin injectable ``Runner``
the host supplies::

    runner(argv, cwd, timeout_s) -> (exit_code | None, stdout, stderr, timed_out)

The runner returns text (lossy utf-8 decode is its job), raises ``FileNotFoundError``
when the binary is absent (Rust ``io::ErrorKind::NotFound``), and may raise other
``OSError`` for other spawn failures. Upstream ran these checks unbounded (a blocking
``Command::output()``), so cria passes ``timeout_s=None``. File paths in the composed
argv are rooted at ``project_dir`` exactly as collected, so ``cwd=None`` (the runner's
own default) preserves upstream's inherit-the-cwd behavior.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import ignore, wsview, prompts

# (exit_code | None, stdout, stderr, timed_out) — see the module docstring for the
# error-signalling contract (FileNotFoundError = binary absent).
RunResult = tuple[Optional[int], str, str, bool]
Runner = Callable[[list[str], Optional[str], Optional[float]], RunResult]

# Directories that are vendored/generated/tooling output — their files are not the
# coder's work product and their syntax is not our problem.
# Cheap always-on fast-path prune (VCS/cache dirs the language templates don't list). The
# language-aware pruning — a model's installed dependency tree under ANY name, e.g. a venv it called
# `handle_resolver/`, caught via Python's `lib/` rule — comes from the vendored .gitignore templates
# in collect_files (see cria/ignore.py), not from this name list.
SKIP_DIRS = [".git", ".codex-multi", "node_modules", "__pycache__", ".pytest_cache",
             ".venv", "venv", "env", "dist", "build", ".mypy_cache", ".ruff_cache", "target"]


@dataclass
class LinterFinding:
    language: str  # "python" | "javascript"
    tool: str      # "py_compile" | "pyflakes" | "node --check"
    passed: bool
    errors: str = ""  # "file:line: message" text, "" when passed


@dataclass
class LinterReport:
    findings: list[LinterFinding] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # languages on disk, checker binary absent

    def is_clean(self) -> bool:
        # Empty report is clean=True: silence is not an objection, and the floor must
        # not block completion when it had nothing to check (or nothing to check WITH).
        return all(f.passed for f in self.findings)

    def failing(self) -> list[LinterFinding]:
        return [f for f in self.findings if not f.passed]

    def probe_digest(self) -> str:
        """Reasoner-facing verdict — ALWAYS text, routing the diagnosis even when clean."""
        d = prompts.load_map("floor_digest")
        failing = self.failing()
        if failing:
            text = d["failing"]
            for f in failing:
                text += f"\n• {f.language} ({f.tool}):\n{f.errors.strip()}"
            return text
        if not self.findings:
            return d["none"]
        return d["clean"]

    def nudge_text(self) -> Optional[str]:
        """Coder-facing re-prompt with the exact errors; None when nothing is failing."""
        failing = self.failing()
        if not failing:
            return None
        text = prompts.load_map("floor_digest")["nudge_preamble"] + "\n"
        for f in failing:
            text += f"\n• {f.language} ({f.tool}):\n{f.errors.strip()}\n"
        return text


# ---------------------------------------------------------------------------
# File collection (pure filesystem read, no execution)

def collect_files(root: str, exts: list[str]) -> list[str]:
    """Recursively collect files under ``root`` whose extension (text after the last
    dot, not including the dot) is in ``exts``; hidden dirs and SKIP_DIRS are pruned;
    an unreadable directory contributes nothing, silently. Sorted (path order)."""
    out: list[str] = []
    # The language's own .gitignore template decides what's vendored/generated (catches an
    # arbitrarily-named venv via `lib/`, node_modules, target/, …) — applied only to this language's
    # files, so Python's `lib/` never prunes a Ruby project's source `lib/`.
    _walk(root, root, exts, out, ignore.for_exts(tuple(exts)))
    out.sort()
    return out


def _walk(root: str, dirpath: str, exts: list[str], out: list[str], matcher) -> None:
    # The workspace is the HARNESS's filesystem, so the entries come from what the harness
    # reported (:mod:`cria.wsview`), not from cria's own disk. None means the same thing the old
    # OSError meant — this directory could not be listed — so the contract is unchanged.
    entries = wsview.current().scandir(dirpath)
    if entries is None:
        return  # unlisted dir → silently return
    for e in entries:
        name = e.name
        # follow_symlinks=False mirrored Rust's DirEntry::file_type(): a symlink is neither dir
        # nor file, so it is skipped rather than followed into a loop. The survey records entries
        # the same way, so a symlink is already neither.
        is_dir = e.is_dir()
        is_file = e.is_file()
        full = os.path.join(dirpath, name)
        if is_dir:
            if name.startswith(".") or name in SKIP_DIRS:
                continue
            if matcher.ignored(os.path.relpath(full, root), True):
                continue
            _walk(root, full, exts, out, matcher)
        elif is_file:
            if "." in name and name.rsplit(".", 1)[1] in exts \
                    and not matcher.ignored(os.path.relpath(full, root), False):
                out.append(full)


# ---------------------------------------------------------------------------
# Pure command composers — what a compose-only deployment hands to the workspace host.

def py_compile_argv(files: list[str]) -> list[str]:
    """All files in ONE invocation — py_compile stops at the first failure with an
    exact file:line, which is all the nudge needs."""
    return ["python3", "-m", "py_compile", *files]


def pyflakes_argv(files: list[str]) -> list[str]:
    return ["python3", "-m", "pyflakes", *files]


def node_check_argv(path: str) -> list[str]:
    """One file at a time — ``node --check`` takes a single entry file."""
    return ["node", "--check", path]


# ---------------------------------------------------------------------------
# Checkers: compose → run (injected) → interpret. The interpretation rules are the
# ported upstream behavior; only the spawn itself is behind the Runner.

def check_python(files: list[str], report: LinterReport, runner: Runner) -> None:
    try:
        code, _out, err, _timed_out = runner(py_compile_argv(files), None, None)
    except OSError:
        # Binary not found (FileNotFoundError) OR any other spawn error → skipped,
        # not failed: an absent interpreter is an abstention.
        report.skipped.append("python")
        return
    if code == 0:
        report.findings.append(LinterFinding("python", "py_compile", passed=True, errors=""))
        escalate_pyflakes(files, report, runner)
    else:
        # Do NOT escalate: pyflakes output on unparseable code is noise; parse must
        # pass first.
        report.findings.append(LinterFinding("python", "py_compile", passed=False,
                                             errors=_text(err)))


def escalate_pyflakes(files: list[str], report: LinterReport, runner: Runner) -> None:
    """Second rung of the floor: catches undefined names / unused imports that
    py_compile can't. Only ever reached when the parse rung passed."""
    try:
        code, out, err, _timed_out = runner(pyflakes_argv(files), None, None)
    except OSError:
        return  # spawn error → ignore silently; the floor already has its parse verdict
    combined = _text(err) + _text(out)  # stderr first, then stdout — upstream order
    if "No module named pyflakes" in combined:
        return  # absent, not a fail
    passed = code == 0
    report.findings.append(LinterFinding("python", "pyflakes", passed=passed,
                                         errors="" if passed else combined.strip()))


def check_javascript(files: list[str], report: LinterReport, runner: Runner) -> None:
    any_ran = False
    failed = False
    errors = ""
    for f in files:
        try:
            code, _out, err, _timed_out = runner(node_check_argv(f), None, None)
        except FileNotFoundError:
            # node absent → the whole language is skipped; no point trying the rest.
            report.skipped.append("javascript")
            return
        except OSError:
            continue  # other spawn error for THIS file → skip the file, keep going
        any_ran = True
        if code != 0:
            failed = True
            errors += _text(err) + "\n"
    if any_ran:
        report.findings.append(LinterFinding("javascript", "node --check",
                                             passed=not failed, errors=errors.strip()))


def run_linter_probe(project_dir: str, runner: Runner) -> LinterReport:
    """The syntax floor. Blocking (the injected runner runs real subprocesses) —
    callers on a serving loop must run this in a worker thread, exactly as upstream
    wrapped it in ``spawn_blocking``."""
    report = LinterReport()
    py_files = collect_files(project_dir, ["py"])
    if py_files:
        check_python(py_files, report, runner)
    js_files = collect_files(project_dir, ["js", "mjs", "cjs"])
    if js_files:
        check_javascript(js_files, report, runner)
    return report


def _text(s) -> str:
    """Lossy decode is the runner's job per the protocol, but tolerate a runner that
    hands back raw bytes rather than crash the floor over it."""
    if isinstance(s, bytes):
        return s.decode("utf-8", errors="replace")
    return s or ""
