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

# Whether a directory is generated is decided by :mod:`cria.ignore`, on PROOF (a tool owns the name,
# or a tool's marker file is inside it) — never by a bare name list. The list that used to live here
# pruned `dist`, `build`, `target`, `env` and `venv` for every language at once, so a Python package
# in `build/` never reached the floor and the gate called the workspace clean without reading it.


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
    skipped_dirs: list[str] = field(default_factory=list)  # dirs the walk proved generated

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
        return d["clean"] + self._unread_clause(d)

    def _unread_clause(self, d: dict) -> str:
        """What the clean verdict is NOT about — named, or nothing at all."""
        if not self.skipped_dirs:
            return ""
        return " " + prompts.fill(d["unread"],
                                  dirs=prompts.named_list(self.skipped_dirs))

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
    """Recursively collect files under ``root`` whose extension (text after the last dot, not
    including the dot) is in ``exts``. A directory is skipped only on proof that a tool generated it
    (:func:`cria.ignore.generated`); an unreadable directory contributes nothing, silently. Sorted
    (path order)."""
    out: list[str] = []
    _walk(root, root, exts, out, [])
    out.sort()
    return out


def collect_files_with_skips(root: str, exts: list[str]) -> tuple[list[str], list[str]]:
    """:func:`collect_files`, plus the proof for every directory the walk did not enter.

    The floor's clean sentence is a claim about the whole workspace, so it has to be able to name
    what it never opened."""
    out: list[str] = []
    skipped: list[str] = []
    _walk(root, root, exts, out, skipped)
    out.sort()
    return out, sorted(set(skipped))


def _walk(root: str, dirpath: str, exts: list[str], out: list[str], skipped: list[str]) -> None:
    # The workspace is the HARNESS's filesystem, so the entries come from what the harness
    # reported (:mod:`cria.wsview`), not from cria's own disk. None means the same thing the old
    # OSError meant — this directory could not be listed — so the contract is unchanged.
    entries = wsview.current().scandir(dirpath)
    if entries is None:
        # UNREADABLE IS NOT EMPTY. This returned silently, so a directory the harness could not list
        # contributed nothing to the walk AND nothing to the sentence about it — and the floor then
        # said every source file passes, having been unable to open one of them (#23c, #11b).
        rel = os.path.relpath(dirpath, root)
        skipped.append(rel if rel == "." else f"{rel} (could not be listed)")
        return
    for e in entries:
        name = e.name
        # follow_symlinks=False mirrored Rust's DirEntry::file_type(): a symlink is neither dir
        # nor file, so it is skipped rather than followed into a loop. The survey records entries
        # the same way, so a symlink is already neither.
        is_dir = e.is_dir()
        is_file = e.is_file()
        full = os.path.join(dirpath, name)
        if is_dir:
            proof = ignore.generated(name, lambda: _child_names(full))
            if proof is not None:
                rel = os.path.relpath(full, root)
                skipped.append(proof.replace(name, rel, 1) if rel != name else proof)
                continue
            _walk(root, full, exts, out, skipped)
        elif is_file:
            if "." in name and name.rsplit(".", 1)[1] in exts:
                out.append(full)


def _child_names(dirpath: str) -> list[str] | None:
    entries = wsview.current().scandir(dirpath)
    return None if entries is None else [e.name for e in entries]


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
    py_files, py_skipped = collect_files_with_skips(project_dir, ["py"])
    if py_files:
        check_python(py_files, report, runner)
    js_files, js_skipped = collect_files_with_skips(project_dir, ["js", "mjs", "cjs"])
    if js_files:
        check_javascript(js_files, report, runner)
    # The clean sentence is a claim about the WHOLE workspace, so it carries the directories the walk
    # never entered. A reader who knows its code is in one of them can then say so, instead of
    # believing a clean verdict that was never about that code (#11b).
    report.skipped_dirs = sorted(set(py_skipped) | set(js_skipped))
    return report


def _text(s) -> str:
    """Lossy decode is the runner's job per the protocol, but tolerate a runner that
    hands back raw bytes rather than crash the floor over it."""
    if isinstance(s, bytes):
        return s.decode("utf-8", errors="replace")
    return s or ""
