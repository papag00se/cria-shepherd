"""Turn raw probe output into targeted repair hints for the small model.

The last mile of the probe system: after a diagnostic command runs (cargo check,
tsc, eslint, pytest, ruff, ...), this parses its stdout/stderr into ``file:line:
message`` Findings and a one-line summary, so the model gets "fix
src/probes.rs:42: missing field" instead of a wall of tool output. A small local
model drowns in raw compiler spew; a targeted location + message is something it
can actually act on.

Faithful port of codex-local's ``codex-rs/routing/src/probe_parse.rs`` (the spec
source of truth), plus the port-relevant slivers of its single caller
``probe_run.rs``: ``family_of`` (argv tokens -> parser family), the
launch-failure/empty-command result contract (:func:`err_result`), and the
timeout summary overwrite. Upstream quirks are preserved verbatim and marked
inline — behavioral fidelity to the Rust module beats local tidiness, because
the specs are the deliverable and divergence here would silently change what
the model is told.

Parsers are conservative line-scanners (no regex dep) covering the formats the
eval + common ecosystems actually emit: rustc/cargo (``--> file:line:col``), tsc
(``file(line,col): error``), ESLint stylish (file header + indented
``line:col``), pytest, and the generic ``file:line[:col]: message`` shared by
ruff / flake8 / mypy / go vet / py_compile-style output. Edge-case behavior is
defined by the string ops, not by equivalent regexes — so the port keeps the
string ops. (:func:`parse_u32` is the one sanctioned ``re`` use, standing in
for Rust's strict ``u32::parse``.)

WHO EXECUTES: cria owns no executors. Everything in this module is pure
text -> data. The one seam that needs a process — running the probe command —
is the injectable :class:`Runner` protocol consumed by :func:`run_candidate`;
upstream's spawning/draining/kill-on-timeout machinery stays host-side. In
proxy deployments the composed command is handed to the harness/model to run
and :func:`parse_output` is called on the tool result later.

CONTRACT HAZARD (preserved, do not "fix" here): ``exit_code=None`` with zero
findings summarizes as ``"no problems reported"`` — an unknown exit is treated
as success. A call site that cannot recover the real exit code must either get
it from harness result metadata or pass a sentinel non-zero code when failure
is known; changing :func:`summarize`'s semantics is not the move.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence

# NOTE: summary/finding messages now flow WHOLE — the summary line and every finding carry the full
# checker text (a failed_unparsed probe's scraped line is the ONLY signal, and pytest's own width-clip is
# routed around by reading the traceback, not its short-summary). The window-aware context floor is the
# one place a real truncation may occur. (Former SUMMARY_*_LIMIT ceilings + truncate() removed as dead.)

# Error-ish keywords for the no-findings/non-zero-exit fallback: substring
# containment against the lowercased line, scanning lines in REVERSE (the last
# matching line wins — build tools print the fatal line last).
ERRORISH_KEYWORDS = ("error", "failed", "fatal")

# Default messages when a parser found a location but no usable message text.
DEFAULT_RUSTC_MESSAGE = "compile error"   # `-->` with no preceding error/warning header
DEFAULT_PYTEST_MESSAGE = "test failed"    # FAILED/ERROR node-id with no ` - ` suffix
CLEAN_SUMMARY = "no problems reported"    # exit 0 or unknown exit, zero findings
UNKNOWN_LOCATION = "?"                    # finding with an empty file field

# Rust u32::MAX — parse_u32 rejects anything larger, matching `str::parse::<u32>()`.
U32_MAX = 4294967295

# Executor-side message contracts (composed here, triggered by the host runner).
EMPTY_COMMAND_SUMMARY = "empty command"
LAUNCH_FAILURE_FMT = "failed to launch ({e}) — tool not installed?"
TIMEOUT_SUMMARY_FMT = "TIMEOUT after {secs}s — probe did not finish (consider a narrower target)"

# Strict u32 stand-in: optional leading '+', ASCII digits only — no '_', no '-',
# no internal whitespace, no unicode digits (Python's int() accepts all of those,
# Rust's u32::parse accepts none). The one sanctioned `re` use in this module.
_U32_RE = re.compile(r"\+?[0-9]+")


@dataclass(eq=True)
class Finding:
    """One diagnostic: where (file/line/col) and what (message)."""
    file: str
    line: Optional[int] = None
    col: Optional[int] = None
    message: str = ""


# ---------------------------------------------------------------------------
# Runner tallies — moved here from probegate 2026-08-16, because the tally has to be read
# at PARSE time. `parse_output` replaces a green run's stdout with the fixed string
# "no problems reported" and keeps no raw text, so every later reader of a GREEN result had
# nothing to count: the deleted-test detector and the skipped-test disclosure to the
# satisfaction judge were both permanently dead. Parse once, where the output is in hand (#12).
# ---------------------------------------------------------------------------
# EVERY RUNNER'S OWN TALLY LINE, one row each. The passed count is a COVERAGE signal — a test that
# skips rather than fails leaves the exit code at 0 and drops out of it — so a runner cria cannot
# count is a runner whose green is unverified. Three were covered (pytest, unittest, cargo) and the
# rest of the ecosystem was not: a Go, Java, JS, Ruby, Elixir, PHP or .NET suite could step aside
# entirely and `_offline_fact` would fall through to the uncounted wording, while
# `_checks_superseded_by_coder_run` would never recognise a coder's own green run.
#
# A ROW IS DATA, NOT CODE: (name, pattern, how to read the groups, whether to sum every match).
# Summing is for runners that print one line PER package or binary (cargo, go, .NET per-project);
# first-match is for runners that print one summary. Ordered most-specific first — the guard is that
# every pattern is anchored on that runner's own distinctive words, so two cannot claim one line.
_SKIPPED_RE = re.compile(r"(\d+) skipped")   # the runner's own skip count
_TALLY_FAILED_PASSED = "fp"     # groups are (failed, passed)
_TALLY_PASSED_FAILED = "pf"     # groups are (passed, failed)
_TALLY_TOTAL_FAILED = "tf"      # groups are (total, failed) — passed is total - failed

_TALLIES = (
    # pytest · `2 failed, 7 passed in 0.05s`  (the leading `=` is its banner)
    ("pytest", re.compile(r"(?im)^=*\s*(?:(\d+) failed[, ]+)?(\d+) passed"), _TALLY_FAILED_PASSED, False),
    # cargo · one `test result:` line per test binary
    ("cargo", re.compile(r"(?im)^test result:\s*\w+\.\s*(\d+) passed;\s*(\d+) failed"), _TALLY_PASSED_FAILED, True),
    # jest / vitest · `Tests:       1 failed, 11 passed, 12 total`
    ("jest", re.compile(r"(?im)^\s*Tests:\s+(?:(\d+) failed,\s+)?(?:\d+ skipped,\s+)?(\d+) passed"), _TALLY_FAILED_PASSED, False),
    # JUnit via maven-surefire / ant · `Tests run: 12, Failures: 1, Errors: 0, Skipped: 2`
    ("junit", re.compile(r"(?im)^\s*Tests run:\s*(\d+),\s*Failures:\s*(\d+)(?:,\s*Errors:\s*(\d+))?"), _TALLY_TOTAL_FAILED, True),
    # gradle · `12 tests completed, 1 failed`
    ("gradle", re.compile(r"(?im)^\s*(\d+) tests? completed(?:,\s*(\d+) failed)?"), _TALLY_TOTAL_FAILED, False),
    # go test -v · one `--- PASS:` / `--- FAIL:` per test (counted below, not by a group pair)
    # rspec · `12 examples, 1 failure, 2 pending`
    ("rspec", re.compile(r"(?im)^\s*(\d+) examples?,\s*(\d+) failures?"), _TALLY_TOTAL_FAILED, False),
    # ExUnit · `12 tests, 1 failure` (also `doctests`)
    ("exunit", re.compile(r"(?im)^\s*(?:\d+ doctests?,\s*)?(\d+) tests?,\s*(\d+) failures?"), _TALLY_TOTAL_FAILED, False),
    # phpunit · `Tests: 12, Assertions: 30, Failures: 1`
    ("phpunit", re.compile(r"(?im)^\s*Tests:\s*(\d+),\s*Assertions:\s*\d+(?:,\s*Failures:\s*(\d+))?"), _TALLY_TOTAL_FAILED, False),
    # dotnet test · `Failed:     1, Passed:    12, Skipped:     0`
    ("dotnet", re.compile(r"(?im)^.*?Failed:\s*(\d+),\s*Passed:\s*(\d+)"), _TALLY_FAILED_PASSED, True),
    # mocha · `11 passing` / `1 failing`, on separate lines
    ("mocha", re.compile(r"(?im)^\s*(\d+) passing\b"), None, False),
    # minitest · `9 runs, 9 assertions, 0 failures, 0 errors, 0 skips`
    ("minitest", re.compile(r"(?im)^\s*(\d+) runs?,\s*\d+ assertions?,\s*(\d+) failures?"),
     _TALLY_TOTAL_FAILED, False),
    # node --test (TAP) · `# pass 13` / `# fail 0`, on separate lines
    ("node", re.compile(r"(?im)^\s*#\s*pass\s+(\d+)\b"), None, False),
)

# node's built-in runner prints TAP: the counts are on separate `# pass` / `# fail` lines, the same
# split shape mocha has. Without a row here a green node suite was invisible to runner_tally, so
# _offline_fact fell to its weaker sentence and cria could not say the tests had actually run —
# measured on the six-language battery, where node is one of the two languages whose passing suites
# cria could never count.
_NODE_FAIL = re.compile(r"(?im)^\s*#\s*fail\s+(\d+)\b")

# go test -v prints no summary count — the per-test lines ARE the tally.
_GO_PASS = re.compile(r"(?m)^\s*--- PASS: ")
_GO_FAIL = re.compile(r"(?m)^\s*--- FAIL: ")
# Plain `go test` prints one verdict PER PACKAGE and no per-test count, so it is deliberately NOT
# a tally: a package whose only live test calls t.Skip() still prints `ok`, and returning a package
# count here would let _offline_fact claim "nothing in them reaches the real service" on evidence
# that cannot support it. No count → the weaker sentence, which claims only what the exit code
# established. Same rule for every runner: a number cria cannot read as TESTS is not a tally.
_MOCHA_FAILING = re.compile(r"(?im)^\s*(\d+) failing\b")
_UNITTEST_TALLY = re.compile(r"(?im)^Ran (\d+) tests?")

# For the rows whose reading is None: their pass count and their fail count are printed on separate
# lines, so the row's own pattern reads the passes and this one reads the failures. Keyed by row
# name so a second split-shape runner cannot silently borrow the first one's failure pattern.
_SPLIT_FAIL_PATTERNS = {"mocha": _MOCHA_FAILING, "node": _NODE_FAIL}


def _tally_counts(kind: str, groups) -> "tuple[int, int] | None":
    """(failed, passed) from one match's groups, by the row's reading — None when unreadable."""
    g = [int(x) if x else 0 for x in groups]
    try:
        if kind == _TALLY_FAILED_PASSED:
            return g[0], g[1]
        if kind == _TALLY_PASSED_FAILED:
            return g[1], g[0]
        if kind == _TALLY_TOTAL_FAILED:
            bad = sum(g[1:])                      # failures + errors, where the runner reports both
            return bad, max(g[0] - bad, 0)
    except IndexError:
        return None
    return None


# Runners that CANNOT report a pass without building the project first. A green tally from one of
# these is proof the code compiles, so it settles a compile-class finding as well as a test-class
# one — `cargo test` never prints "test result: ok" over an unresolved import, and `go test` never
# prints "ok <pkg>" over an undefined symbol.
#
# This is a property of the RUNNER, which cria reads off the output it is holding, not a property of
# the finding's wording. The alternative was a phrase list over the finding text, which is how the
# supersede came to cover pytest and minitest and miss every compiled language: three of the six
# battery families, and exactly the ones where a stale error is most expensive.
#
# The interpreted runners are absent on purpose and the distinction is load-bearing: a green pytest
# says nothing about a pyflakes finding, because an unused import fails the linter and runs fine.
COMPILES_FIRST = frozenset({"cargo", "junit", "gradle", "dotnet", "go"})


def runner_and_tally(text: str) -> tuple[str, str]:
    """``(runner name, Nf/Np)`` — the runner whose summary line matched, and its tally.

    :func:`runner_tally` is this without the name; both read the same rows, so a runner added to
    ``_TALLIES`` is known to every caller at once."""
    body = text or ""
    for _name, pat, kind, summed in _TALLIES:
        if not pat.findall(body):
            continue
        t = runner_tally(body)
        return (_name, t) if t else ("", "")
    if _GO_PASS.findall(body) or _GO_FAIL.findall(body):
        return "go", runner_tally(body)
    if _UNITTEST_TALLY.search(body):
        return "unittest", runner_tally(body)
    return "", ""


def runner_tally(text: str) -> str:
    """A runner's own pass/fail line, normalized to `Nf/Np` — "" when it printed none.

    The PASSED count is the coverage signal, not decoration: a test that skips rather than fails
    leaves the exit code at 0 and drops out of this count. That is the only thing standing between
    "the suite is self-contained" and "one test quietly stepped aside" (see _offline_fact).

    Every runner in _TALLIES, plus the two that need counting rather than reading: `go test -v`,
    which prints no summary but one line per test, and unittest, whose "Ran N tests" says nothing
    about outcome and keeps its own `Nran/OK` shape so the two callers can tell a counted result
    from an outcome-only one. Plain `go test` counts PACKAGES, not tests, and returns "" — see the
    note at _GO_PASS."""
    body = text or ""
    for _name, pat, kind, summed in _TALLIES:
        matches = pat.findall(body)
        if not matches:
            continue
        if kind is None:            # a runner whose pass and fail counts are on SEPARATE lines
            passed = sum(int(x) for x in matches)
            companion = _SPLIT_FAIL_PATTERNS.get(_name)
            failed = sum(int(x) for x in companion.findall(body)) if companion else 0
            return f"{failed}f/{passed}p"
        rows = [_tally_counts(kind, m if isinstance(m, tuple) else (m,)) for m in matches]
        rows = [r for r in rows if r is not None]
        if not rows:
            continue
        if summed:
            return f"{sum(f for f, _ in rows)}f/{sum(p for _, p in rows)}p"
        return f"{rows[0][0]}f/{rows[0][1]}p"
    # Go: `-v` gives one line per test; plain `go test` gives one verdict per package.
    go_pass, go_fail = len(_GO_PASS.findall(body)), len(_GO_FAIL.findall(body))
    if go_pass or go_fail:
        return f"{go_fail}f/{go_pass}p"
    m = _UNITTEST_TALLY.search(body)
    if m:
        ok = "OK" if re.search(r"(?m)^OK\b", body) else "FAIL"
        return f"{m.group(1)}ran/{ok}"
    return ""


@dataclass(eq=False)  # upstream derives Debug+Clone but NOT Eq — keep it non-comparable
class ProbeResult:
    """What one probe command produced, rendered model-ready."""
    command: str                       # stored verbatim for display; never re-parsed
    exit_code: Optional[int] = None    # None = unavailable (timeout / signal / wait error)
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)
    # TAKEN AT PARSE TIME, from the runner's own output, because nothing downstream can recover it:
    # a GREEN run's `summary` is the fixed string "no problems reported" and the raw text is dropped.
    # `tally` is `Nf/Np` ("" when no runner printed one); `skipped` is the runner's own skip count.
    tally: str = ""
    skipped: int = 0
    timed_out: bool = False            # the command RAN and did NOT finish (timeout) — distinct from a
    #                                    launch failure (exit_code is None for BOTH, but a timeout is a
    #                                    positive did-not-verify signal → the completion gate fails CLOSED)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def parse_u32(s: str) -> Optional[int]:
    """Rust ``str::parse::<u32>()``: '+'-optional ASCII digits fitting in u32, else None."""
    if not _U32_RE.fullmatch(s):
        return None
    value = int(s)
    return value if value <= U32_MAX else None


def looks_like_path(f: str) -> bool:
    """Gate for the generic parser: path-shaped, spaceless, not a URL."""
    return (
        f != ""
        and " " not in f
        and ("/" in f or "\\" in f or "." in f)
        and not f.startswith("http")
    )


def split_loc(s: str) -> Optional[tuple[str, Optional[int], Optional[int]]]:
    """``file:line[:col]`` -> (file, line, col). Used by parse_rustc for `-->` lines."""
    parts = s.rsplit(":", 2)  # Rust rsplitn(3, ':') reversed → [file, line, col]
    if len(parts) == 3:
        # upstream quirk, preserved: this branch TRIMS before parsing (split_diag does not)
        col = parse_u32(parts[2].strip())
        line = parse_u32(parts[1].strip())
        if col is not None and line is not None:
            return (parts[0], line, col)
    # fall through to file:line ("src/foo.rs:42:abc" lands here and fails on "abc")
    if ":" in s:
        file, _, line_s = s.rpartition(":")
        line = parse_u32(line_s.strip())
        if line is not None:
            return (file, line, None)
    return None


# `file:[line,col] message` (javac via Maven) and `file(line,col): message` (MSVC, and some .NET
# analysers) rewritten to the `file:line:col: message` shape the rest of this function reads.
_MAVEN_LOC = re.compile(r"^(\S+?):\[(\d+),(\d+)\]\s+")
_MSVC_LOC = re.compile(r"^(\S+?)\((\d+),(\d+)\):\s+")


def split_diag(s: str) -> Optional[tuple[str, Optional[int], Optional[int], str]]:
    """``file:line[:col]: message`` -> (file, line, col, message). Used by parse_generic."""
    # MAVEN PUTS THE LINE AND COLUMN IN BRACKETS. javac-via-Maven prints
    # `/…/Importer.java:[3,30] cannot find symbol` — no colon-space after the location, so every
    # Maven diagnostic fell through to `return None` and cria then told the steer author "a specific
    # line could not be parsed from the output" while the located errors sat in the same turn. The
    # author ranks that block as authority tier 1 and builds on it. Seen in every Java cell of
    # cycle 1; that column scored 0 / 40 / 0 / 0.
    #
    # Normalised here rather than matched downstream, because this is a LOCATION FORMAT and there
    # are only a handful in use — gcc/clang/rustc `file:line:col:`, MSVC `file(line,col):`, Maven
    # `file:[line,col]`. Reading a compiler's file/line/column is something this function already
    # claims to do; a rule keyed to the word "Maven" would be the per-language matcher this project
    # keeps getting burned by.
    s = _MAVEN_LOC.sub(r"\1:\2:\3: ", s, count=1)
    s = _MSVC_LOC.sub(r"\1:\2:\3: ", s, count=1)
    if ": " not in s:
        return None
    loc, msg = s.split(": ", 1)  # FIRST colon+space splits location from message
    parts = loc.rsplit(":", 2)
    if len(parts) == 3:
        # upstream quirk, preserved: NO trim before parsing in this branch (unlike split_loc)
        col = parse_u32(parts[2])
        line = parse_u32(parts[1])
        if col is not None and line is not None:
            return (parts[0], line, col, msg.strip())
    if ":" in loc:
        file, _, line_s = loc.rpartition(":")
        line = parse_u32(line_s)  # upstream quirk, preserved: no trim here either
        if line is not None:
            return (file, line, None, msg.strip())
    return None


def split_line_col(s: str) -> tuple[Optional[int], Optional[int]]:
    """``12,7`` / ``12:7`` / ``12`` -> (line, col). Used by tsc + eslint rows.

    Rust splits on either ':' or ','; the stdlib-faithful equivalent is
    normalizing ',' to ':' and splitting. ``line`` may be None while ``col``
    parses — callers gate on ``line is not None``.
    """
    pieces = s.replace(",", ":").split(":")
    line = parse_u32(pieces[0].strip()) if len(pieces) >= 1 else None
    col = parse_u32(pieces[1].strip()) if len(pieces) >= 2 else None
    return (line, col)


# ---------------------------------------------------------------------------
# the five parsers
# ---------------------------------------------------------------------------

def parse_rustc(s: str) -> list[Finding]:
    """rustc/cargo: ``error[E0063]: msg`` header, then ``  --> file:line:col``."""
    out: list[Finding] = []
    last_msg: Optional[str] = None
    for l in s.splitlines():
        t = l.lstrip()  # trim_start only
        # upstream quirk, preserved: startswith, NOT whole-word — "errors occurred"
        # matches "error" and yields message "occurred" after the char-class strip.
        severity = ""
        if t.startswith("error"):
            rest = t[len("error"):]
        elif t.startswith("warning"):
            rest = t[len("warning"):]
        # `note:` / `help:` carry their OWN `-->` span. They matched no header, so that span fell to
        # the "compile error" stand-in — inventing a phantom error at a line rustc was only pointing to
        # for context, AND laundering an advisory past the is_advisory filter that would have dropped a
        # line starting with "note:". Keep rustc's own words so the filter can do its job.
        elif t.startswith("note") or t.startswith("help"):
            severity = t[:4]          # kept, so is_advisory still recognizes it and filters it out
            rest = t[4:]
        else:
            rest = None
        if rest is not None:
            # Eat the leading "[E0433]"-style code: a run of '[', ']', or
            # alphanumerics. (Rust char::is_alphanumeric is Unicode
            # Alphabetic+Nd+Nl+No; Python str.isalnum() is a close-enough
            # superset — accepted divergence.)
            i = 0
            while i < len(rest) and (rest[i] in "[]" or rest[i].isalnum()):
                i += 1
            msg = rest[i:].lstrip(":").strip()  # leading ':' run, then whitespace both sides
            if msg != "":
                last_msg = f"{severity}: {msg}" if severity else msg
        elif t.startswith("--> "):  # elif: a line is never both header and location
            loc = t[len("--> "):].strip()
            r = split_loc(loc)
            if r is not None:
                file, line, col = r
                out.append(Finding(file, line, col,
                                   last_msg if last_msg is not None else DEFAULT_RUSTC_MESSAGE))
                last_msg = None
            elif loc:
                # A FILE WITH NO LINE IS STILL A LOCATION. `split_loc` wants `file:line:col`, and
                # cargo's manifest and target-resolution errors never print one — they point at the
                # whole file:
                #
                #     error: can't find bin `dotkey-toml` at path `…/src/main.rs`
                #      --> …/Cargo.toml
                #
                # so the finding was dropped MESSAGE AND ALL. Downstream, `completion_block_nudge`
                # came back empty and `gate_error_text` fell through to its "no specific line could
                # be parsed" branch — while ⟦ctx:checks⟧, which reads the raw section from a
                # different reader, printed the very line naming the missing file in the same prompt.
                # loop.py's own rule for this is written above `gate_error_text`: NEVER SAY "no line
                # could be parsed" WHEN A LINE WAS PARSED.
                #
                # Walked on cycle 4 cell 24 (`rust-toml-cli x nemotron-elastic`, 5% useful). The
                # crate needed one file — `src/main.rs` — from call 0028 to the end. cargo said so on
                # every check. The steer channel said "a specific line could not be parsed… run that
                # exact check yourself" six times, and the coder ran the gate seven times and re-read
                # `Cargo.toml` five times without ever creating the file.
                #
                # `Finding.line` is Optional and `summarize` already renders a file-only span
                # (`elif f.file != "": loc = f.file`) — this was the one place that refused to make
                # one.
                out.append(Finding(loc, None, None,
                                   last_msg if last_msg is not None else DEFAULT_RUSTC_MESSAGE))
                last_msg = None
    return out


def parse_tsc(s: str) -> list[Finding]:
    """tsc: ``src/foo.ts(42,5): error TS2322: message``."""
    out: list[Finding] = []
    for l in s.splitlines():
        paren = l.find("(")
        if paren == -1:
            continue
        file = l[:paren].strip()
        if file == "" or "): " not in l[paren:]:  # exact "): " must appear at/after the paren
            continue
        rest = l[paren + 1:]
        close = rest.find(")")
        if close == -1:
            continue
        nums = rest[:close]
        msg_part = rest[close + 1:].lstrip(":").strip()  # leading ':' run, then whitespace
        line, col = split_line_col(nums)
        if line is not None:
            out.append(Finding(file, line, col, msg_part))
    return out


def parse_eslint(s: str) -> list[Finding]:
    """ESLint stylish: file-path header line, then indented ``42:5  error  msg  rule`` rows."""
    out: list[Finding] = []
    cur_file: Optional[str] = None
    for l in s.splitlines():
        t = l.strip()
        is_header = (
            not (l != "" and l[0].isspace())  # !l.starts_with(char::is_whitespace)
            and ("/" in l or "\\" in l or l.endswith(".js") or l.endswith(".ts"))
            and "problem" not in t  # skips the "✖ 2 problems" footer
            and t != ""
        )
        if is_header:
            cur_file = t
            continue
        # cur_file persists across blank lines — blanks are neither headers nor
        # valid rows, so state simply carries.
        if cur_file is not None:
            toks = t.split()  # whitespace-run split
            if toks:
                line, col = split_line_col(toks[0])
                if line is not None:
                    level = toks[1] if len(toks) > 1 else ""
                    msg = " ".join(toks[2:])  # single-space rejoin; rule id stays in msg
                    if level.lower() == "warning":
                        continue  # operator filter: error-class only — style warnings never gate
                    if level.lower() != "error":
                        msg = f"{level} {msg}".strip()
                    out.append(Finding(cur_file, line, col, msg.strip()))
    return out


# pytest structure. A per-failure traceback BLOCK is headed by ``_____ TestClass.test_name _____``; it
# ends with the failing location ``path:line: ErrorType`` and carries the FULL error on ``E   <Exc>: msg``.
# We read the BLOCK, never pytest's short-summary line — pytest width-truncates that summary to the
# (tty-less → 80-col) terminal, so ``AssertionError: 400 != 200`` arrives as ``Asserti…``. The block's
# ``E`` line is never width-clipped, so the finding gets the real expected-vs-got. Never touch COLUMNS.
_PYTEST_BLOCK_HDR = re.compile(r"^_{3,} .+? _{3,}\s*$", re.M)          # ____ TestClass.test_name ____
_PYTEST_SUMMARY_HDR = re.compile(r"^=+ short test summary", re.M)     # the width-clipped summary section
# path:line: ErrorType / "in fn" — and path:line: with NOTHING after it, which is what pytest prints
# for the frame that raised when a test's own mock supplies the exception. Requiring a non-empty tail
# made that frame invisible, so `_failing_frame` fell through to the deepest frame it COULD see: the
# production module. Walked on ada-handles_mellum2_codex_poff_1785686596 — five prompts (0041, 0042,
# 0047, 0048, 0053) told the coder `resolve_handle.py:19: Exception: Network error` under "They are
# the checker's exact words", when pytest's own words named `resolve_handle_test.py`. It sent the
# model to edit working production code to satisfy a test that was scripting the failure itself.
_PYTEST_LOC_LINE = re.compile(r"^([\w./\\-]+\.py):(\d+):(?:[ \t]+(\S.*))?[ \t]*$", re.M)
_PYTEST_FRAME = re.compile(r"^([\w./\\-]+\.py):(\d+): in ", re.M)     # a traceback frame (fallback localize)
_PYTEST_ERR_LINE = re.compile(r"^E\s{2,}(.+)$", re.M)                 # E   <full error, never width-clipped>


def _pytest_blocks(s: str) -> list[str]:
    """Split pytest output into per-failure traceback blocks (text after each ``____ header ____``, up to
    the next header or the short-summary section). Empty when there are no tracebacks (e.g. ``--tb=no``)."""
    end = m.start() if (m := _PYTEST_SUMMARY_HDR.search(s)) else len(s)
    starts = [h.end() for h in _PYTEST_BLOCK_HDR.finditer(s) if h.start() < end]
    if not starts:
        return []
    bounds = starts + [end]
    return [s[bounds[i]:bounds[i + 1]] for i in range(len(starts))]


_PYTEST_COLLECT_HDR = re.compile(r"^_{3,} ERROR collecting (\S+) _{3,}\s*$", re.M)


def _pytest_collect_errors(s: str) -> dict:
    """file → the collector's OWN message for a COLLECTION error (an import-file mismatch, a syntax
    error in the test module, a broken conftest).

    These blocks carry no ``path:line:`` frame and no ``E   `` rows, so the traceback reader finds no
    location and skips them — and the short summary's bare ``ERROR <nodeid>`` (no ``` - ``` suffix)
    then fell through to the literal DEFAULT_PYTEST_MESSAGE. The coder was handed "test failed" for a
    diagnostic that had already told it exactly what to do. Observed live (run 0726-145040): two test
    files sharing a basename plus a stale __pycache__ made pytest print

        import file mismatch: ... HINT: remove __pycache__ / .pyc files and/or use a unique basename

    and cria reported `tests/test_resolve_handles.py: test failed`, so the coder edited test LOGIC for
    hundreds of calls while nothing could be collected at all."""
    out: dict = {}
    end = m.start() if (m := _PYTEST_SUMMARY_HDR.search(s)) else len(s)
    hdrs = [h for h in _PYTEST_COLLECT_HDR.finditer(s) if h.start() < end]
    for h in hdrs:
        nxt = _PYTEST_BLOCK_HDR.search(s, h.end())
        stop = min(nxt.start(), end) if nxt else end
        body = [ln.rstrip() for ln in s[h.end():stop].splitlines() if ln.strip()]
        if body:
            out[h.group(1).replace("\\", "/")] = "\n".join(body)
    return out


# A frame that is NOT the workspace's code: the interpreter's own library, an installed package, or
# a virtualenv. A failure's LAST frame is routinely one of these — `mock.py` when a mock raises,
# `ast.py` under a rewriting assertion, `pathlib.py` inside a helper — and the coder cannot edit any
# of them.
_FOREIGN_FRAME = re.compile(
    r"(?:^|/)(?:usr/lib(?:64)?/python\d[\d.]*|site-packages|dist-packages|"
    r"lib/python\d[\d.]*|\.venv|venv/lib|/opt/hostedtoolcache)/", re.I)


def _own_code(path: str) -> bool:
    """Is this traceback frame a file the CODER can actually edit?"""
    return not _FOREIGN_FRAME.search(path or "")


def _failing_frame(locs):
    """The last frame in the workspace's OWN code, else the last frame there is.

    ``locs[-1]`` — the last frame, full stop — is what this used to take, and its docstring claimed it
    "gets the real test-file location". It does not. When a test mocks something and the mock raises,
    the deepest frame is inside the interpreter's own library, and cria then handed the coder a
    file:line it has no ability to edit.

    MEASURED across every captured coder prompt carrying a check block (n=2,836): a stdlib or
    site-packages `file:line` appears **7,888 times, across 48 runs** — `mock.py` alone 2,680 times.
    Live example, run 20260802T003331 (mellum2, ada-handles, 3/4), the last steer of the run:

        • /usr/lib/python3.12/unittest/mock.py:1193: Exception: 404
        • /usr/lib/python3.12/unittest/mock.py:1193: Exception: Network error

    Falling back to the last frame when NONE are the coder's own is deliberate: the location is then
    genuinely outside the workspace, and saying so beats inventing one."""
    for f, ln, tail in reversed(locs):
        if _own_code(f):
            return f, ln, tail
    return locs[-1]


def parse_pytest(s: str) -> list[Finding]:
    """Prefer the per-failure TRACEBACK BLOCKS: each ends with the failing ``path:line: ErrorType`` and
    carries the FULL error on ``E   …`` — so the finding gets the real test-file location and the
    un-clipped message (we never read pytest's width-truncated short-summary). Falls back to the
    short-summary ``FAILED/ERROR`` lines only when no traceback block is present (``--tb=no``); a bare
    summary FAILURE has no line, so it is still enriched from any traceback frame + the ``E`` line.
    """
    out: list[Finding] = []
    for block in _pytest_blocks(s):
        locs = _PYTEST_LOC_LINE.findall(block)   # (file, line, tail); the LAST is the failing assertion's own
        errs = _PYTEST_ERR_LINE.findall(block)   # every E-line — the FULL error (multi-line assertions too)
        if not locs:
            continue
        # The last frame in the coder's OWN code — not simply the last frame. See _failing_frame.
        file, line, tail = _failing_frame(locs)
        # Join ALL E-lines, not just one: a multi-line assertion (`E AssertionError: …` + diff rows) must
        # arrive whole — taking a single row would drop either the header or the diff. Never clipped.
        msg = "\n".join(e.strip() for e in errs) if errs else tail.strip()
        out.append(Finding(file, int(line), None, msg))
    collect = _pytest_collect_errors(s)   # the collector's real text — for the merge here AND below
    # MERGE collection errors alongside whatever localized, never instead of it. `if out: return out`
    # used to run first, so one ordinary test failure hid an entire uncollectable file — the shape a
    # live run actually had (real failures AND a collection error side by side), where the coder was
    # told only about the failure and kept editing a file nothing could collect.
    for cfile, cmsg in collect.items():
        if not any(f.file.replace("\\", "/") == cfile for f in out):
            out.append(Finding(cfile, None, None, cmsg))
    if out:
        return out
    # No traceback blocks → read the short-summary lines (pytest may have width-clipped these).
    for l in s.splitlines():
        t = l.strip()
        if t.startswith("FAILED "):
            rest = t[len("FAILED "):]
        elif t.startswith("ERROR "):
            rest = t[len("ERROR "):]
        else:
            continue
        nodeid, msg = rest.split(" - ", 1) if " - " in rest else (rest, "")
        file = nodeid.split("::", 1)[0]
        # Prefer the collector's OWN diagnostic over the "test failed" stand-in: the preamble tells the
        # coder every problem below is the checker's own message, so it had better be one.
        out.append(Finding(file, line=None, col=None,
                           message=(msg or collect.get(file.replace("\\", "/")) or DEFAULT_PYTEST_MESSAGE)))
    if any(f.line is None for f in out):
        frames = {m.group(1).replace("\\", "/").rsplit("/", 1)[-1]: (m.group(1), int(m.group(2)))
                  for m in _PYTEST_FRAME.finditer(s)}          # basename → (file, line), deepest wins
        errs = _PYTEST_ERR_LINE.findall(s)
        err = errs[-1].strip() if errs else ""                # last `E   …` row = the actual exception
        for i, f in enumerate(out):
            fr = frames.get(f.file.replace("\\", "/").rsplit("/", 1)[-1])
            if f.line is None and fr is not None:
                out[i] = Finding(f.file, fr[1], None, err or f.message)
    if out:
        return out
    # NO block header and NO summary line — pytest prints a broken conftest exactly this way:
    #   ImportError while loading conftest '/repo/conftest.py'.
    #   conftest.py:1: in <module>
    #   E   ModuleNotFoundError: No module named 'nosuchmodule'
    # The `E   ` rows ARE pytest's own error text and nothing was reading them here, so the finding fell
    # to a generic file:line scrape that reported the stack FRAME — "conftest.py:1: in <module>" — and
    # dropped the actual exception. Take the outermost frame (the user's file, not the library the
    # traceback descends into) and the E-rows whole.
    errs = [e.strip() for e in _PYTEST_ERR_LINE.findall(s)]
    if errs:
        locs = _PYTEST_LOC_LINE.findall(s)
        if locs:
            file, line, _tail = locs[0]
            return [Finding(file, int(line), None, "\n".join(errs))]
        return [Finding("", None, None, "\n".join(errs))]
    return out


# A test runner that prints its location in a shape `file:line: message` does NOT cover. Verified
# against REAL failing runs of each tool on this box (a Rust crate, an rspec spec, a phpunit case) —
# not against reconstructions, which is how the maven row below was caught.
#
#   cargo test   thread 'tests::it_adds' (72242) panicked at src/lib.rs:7:20:
#   rspec            # ./a_spec.rb:3:in `block (2 levels) in <top (required)>'
#   phpunit      /w/tests/AppTest.php:14                       (bare, on its own line)
#
# Compiler and linter output was always parsed; TEST-runner failures mostly were not, so a failing
# Rust/Ruby/PHP suite reached the coder as `$ cargo test — summary` with no file:line at all.
#
# MAVEN IS DELIBERATELY ABSENT: its console output carries NO location whatsoever
# ("Failed tests: testAdd(app.AdderTest): expected:<5> but was:<4>") — the file and line exist only
# in target/surefire-reports. No pattern can extract what was never printed.
_RUNNER_LOCATIONS = (
    re.compile(r"panicked at ([^\s:][^:]*):(\d+):(\d+)"),          # cargo test / any Rust panic
    re.compile(r"^\s*#\s+(\.?[^\s:]+):(\d+)(?::in\b|\s*$)", re.M),  # rspec backtrace line
    re.compile(r"^\s*(/[^\s:]+\.php):(\d+)\s*$", re.M),            # phpunit failure location
)


def parse_runner_locations(s: str) -> list[Finding]:
    """Locations printed by TEST runners whose shape ``file:line: message`` does not match.

    The message is deliberately the runner's own nearest line rather than an invented summary: the
    gate's contract is "the checker's OWN message and the line it flagged"."""
    lines = s.splitlines()
    out: list[Finding] = []
    seen: set[tuple[str, int]] = set()
    for rx in _RUNNER_LOCATIONS:
        for m in rx.finditer(s):
            file, line = m.group(1), parse_u32(m.group(2))
            if line is None or not looks_like_path(file) or (file, line) in seen:
                continue
            seen.add((file, line))
            # The most informative nearby line: the runner states the assertion right after the
            # location (cargo) or right before it (phpunit/rspec).
            at = s[:m.start()].count("\n")
            # The LOCATION line itself is not the diagnosis — cargo prints `panicked at src/lib.rs:7`
            # and the assertion on the NEXT line. Look around it, never at it.
            near = [x.strip() for i, x in enumerate(lines[max(0, at - 3):at + 4], max(0, at - 3))
                    if i != at and x.strip() and not x.strip().startswith(("#", "-", "="))]
            msg = next((x for x in near if any(w in x.lower() for w in
                                               ("assert", "expected", "failed", "error"))),
                       (near[0] if near else "test failure"))
            out.append(Finding(file, line, None, msg[:200]))
    return out


def parse_generic(s: str) -> list[Finding]:
    """``file:line[:col]: message`` — ruff / flake8 / mypy / go vet / gcc shape.

    For mypy-shaped input (``src/x.py:7: error: Incompatible…``) the message
    KEEPS the ``error: `` prefix: the split happens at the FIRST ``": "``,
    which sits right after the line number.
    """
    out: list[Finding] = []
    for l in s.splitlines():
        t = l.strip()
        r = split_diag(t)
        if r is not None:
            file, line, col, msg = r
            if looks_like_path(file):
                out.append(Finding(file, line, col, msg))
    if not out:
        # Only when the ordinary shape found nothing: a compiler's own `file:line:` diagnostics must
        # never be crowded out by a panic location further down the same output.
        out = parse_runner_locations(s)
    return out


# `(at line N, column M)` (tomllib) or `line N column M` (json.load) embedded in a decode-error
# message. Both stdlib config parsers report location as PROSE, not the `file:line:col:` shape.
_CONFIG_PROSE_LOC_RE = re.compile(r"(?:at\s+)?line\s+(\d+)(?:,?\s+column\s+(\d+))?", re.I)


def parse_config_syntax(s: str) -> list[Finding]:
    """The tier-0 CONFIG-syntax floor prints stdlib decode errors as ``<file>: <message>`` where the
    message embeds the location in PROSE — ``Invalid value (at line 2, column 12)`` (tomllib) or
    ``Expecting value: line 2 column 1 (char 5)`` (json.load). Neither is the ``file:line:col:`` shape
    parse_generic recognizes, and the leading words ('Invalid'/'Expecting') aren't error-ish keywords,
    so a broken pyproject.toml/tsconfig.json read as ``exited 1 with no parseable diagnostics`` and the
    model was told to 'go to the reported line' with NO line (the pyproject spiral). Lift the prose
    line/column into a real Finding. Runs LAST in the fallback chain, so it never shadows a tool that
    already localized the error."""
    out: list[Finding] = []
    for l in s.splitlines():
        file, sep, rest = l.strip().partition(": ")
        if not sep or not looks_like_path(file):
            continue
        m = _CONFIG_PROSE_LOC_RE.search(rest)
        if m is None:
            continue
        col = int(m.group(2)) if m.group(2) else None
        out.append(Finding(file, int(m.group(1)), col, rest))
    return out


# ---------------------------------------------------------------------------
# assembly: dedup, summarize, parse_output
# ---------------------------------------------------------------------------

def dedup(findings: list[Finding]) -> None:
    """In place: keep the first of each (file, line, message), preserving order.

    upstream quirk, preserved: the column is deliberately NOT in the dedup key —
    the same message at the same line with a different column is still a dup.
    """
    seen: set[tuple[str, Optional[int], str]] = set()
    kept: list[Finding] = []
    for f in findings:
        key = (f.file, f.line, f.message)
        if key not in seen:
            seen.add(key)
            kept.append(f)
    findings[:] = kept


def prefer_own_code(findings: list["Finding"]) -> list["Finding"]:
    """Findings in the coder's OWN files first — foreign frames last, never dropped.

    _failing_frame fixed this inside parse_pytest, but every OTHER parser still reported whatever
    file:line it found, and the very next run proved the fix incomplete: run 20260802T014434 still
    showed the coder `/usr/lib/python3.12/json/decoder.py:355`, `json/decoder.py:337` and
    `json/__init__.py:346`, thirteen times each, from a JSONDecodeError traceback that parse_pytest
    never touched. One choke point covers all of them.

    ORDER, not deletion. A failure genuinely inside a library is still a failure the coder must know
    about; it is just never the FIRST thing to hand it, because `summarize` shows the first finding
    and that is the line the coder goes and edits."""
    own = [f for f in findings if _own_code(f.file)]
    return own + [f for f in findings if not _own_code(f.file)] if own else findings


def summarize(findings: list[Finding], exit_code: Optional[int], combined: str) -> str:
    """One line the model can act on: first finding, or the last error-ish output line."""
    findings = prefer_own_code(findings)
    if findings:
        f = findings[0]
        if f.line is not None and f.file != "":
            loc = f"{f.file}:{f.line}"
        elif f.file != "":
            loc = f.file
        else:
            loc = UNKNOWN_LOCATION
        more = f" (+{len(findings) - 1} more)" if len(findings) > 1 else ""
        return f"{loc}: {f.message.strip()}{more}"   # FULL message — never width/length-clipped
    if exit_code == 0 or exit_code is None:
        # Unknown exit reads as clean — see the CONTRACT HAZARD note in the module doc.
        return CLEAN_SUMMARY
    # Non-zero exit, nothing parsed: hunt bottom-up for the last error-ish line.
    line = ""
    for l in reversed(combined.splitlines()):
        low = l.lower()
        # upstream quirk, preserved: the `strip() != ""` clause is redundant once a
        # keyword matched (keywords contain non-space chars), but it stays.
        if any(kw in low for kw in ERRORISH_KEYWORDS) and l.strip() != "":
            line = l
            break
    line = line.strip()
    if line == "":
        return f"exited {exit_code} with no parseable diagnostics"
    return f"exited {exit_code}: {line}"   # FULL last error line — never clipped


# Family dispatch: exact match on the `family` argument. No caller ever passes
# "unittest", but upstream accepts it — the arm stays. "mypy" has NO arm on
# purpose: it falls to the rustc-then-generic fallback below.
# ---------------------------------------------------------------------------
# Tier-0 congruence parsers (cria addition — every ecosystem's parse floor yields
# file:line findings, exactly like the ranked tools' parsers)
# ---------------------------------------------------------------------------

_PYCOMPILE_LOC = re.compile(r'File "([^"]+)", line (\d+)')
# An exception HEADER — `SyntaxError: …`, `IndentationError: …`, `TabError: …`, `ValueError: …`. Anchored
# at the start so an echoed source line that merely CONTAINS an exception name (`raise ValueError("x"`)
# cannot pose as the diagnostic.
_PYCOMPILE_MSG = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Warning|Exception)\b\s*:")


def parse_pycompile(text: str) -> list:
    """compileall/py_compile output: `*** Error compiling '...'` blocks with a
    `File "x.py", line N` location and a trailing `SyntaxError: ...` line."""
    findings = []
    pending = None  # (file, line) awaiting its message
    for raw in text.splitlines():
        t = raw.strip()
        m = _PYCOMPILE_LOC.search(t)
        if m:
            if pending is not None:
                findings.append(Finding(file=pending[0], line=pending[1], col=None,
                                        message="compile error"))
            pending = (m.group(1), int(m.group(2)))
            continue
        # Only an EXCEPTION HEADER counts as the message. The old test was `"Error" in t`, which the
        # echoed SOURCE line satisfies whenever the offending code merely mentions one — `raise
        # ValueError("x"` matched, was taken as the diagnostic, and cleared `pending`, so the real
        # `SyntaxError: '(' was never closed` two rows below was never read. The model got its own
        # broken line handed back as the explanation, from the tier-0 syntax floor that runs on every
        # Python workspace. Source lines and carets are skipped now; the exception header wins.
        if pending is not None and _PYCOMPILE_MSG.match(t):
            findings.append(Finding(file=pending[0], line=pending[1], col=None, message=t))
            pending = None
    if pending is not None:
        findings.append(Finding(file=pending[0], line=pending[1], col=None,
                                message="compile error"))
    return findings


def parse_nodecheck(text: str) -> list:
    """`node --check` output: first line `path:line` (v16+) or bare path, then the
    offending source, a caret, and `SyntaxError: message`."""
    lines = text.splitlines()
    file, lineno = None, None
    for t in (x.strip() for x in lines):
        if file is None and t and " " not in t and (("/" in t or "\\" in t or t.endswith((".js", ".mjs", ".cjs")))):
            head = t.rsplit(":", 1)
            if len(head) == 2 and head[1].isdigit():
                file, lineno = head[0], int(head[1])
            else:
                file = t
        elif t.startswith("SyntaxError") and file is not None:
            return [Finding(file=file, line=lineno, col=None, message=t)]
    return []


_PHPLINT_RE = re.compile(r"(?:Parse|Fatal) error:\s*(.+?) in (.+?) on line (\d+)")


def parse_phplint(text: str) -> list:
    """`php -l` output: `Parse error: <msg> in <file> on line <N>`."""
    out = []
    for t in text.splitlines():
        m = _PHPLINT_RE.search(t.strip())
        if m:
            out.append(Finding(file=m.group(2), line=int(m.group(3)), col=None,
                               message=m.group(1).strip()))
    return out


_FAMILY_PARSERS = {
    "cargo": parse_rustc,
    "tsc": parse_tsc,
    "eslint": parse_eslint,
    "pytest": parse_pytest,
    "unittest": parse_pytest,
    "pycompile": parse_pycompile,
    "nodecheck": parse_nodecheck,
    "phplint": parse_phplint,
}


# Operator filter (2026-07-11): probes gate on ERROR-CLASS issues only — style,
# formatting, notes, and advisory output never block a step. Applied at the single
# chokepoint every result flows through. Kept deliberately narrow: when in doubt a
# finding is treated as an error (under-filtering beats letting real bugs through).
_STYLE_CODE = re.compile(r"^(?:W\d{3}|E(?!9)\d{3}|C\d{4}|R\d{4})\b")  # pycodestyle/pylint style codes; E9xx = syntax, kept

# The unused / never-used family is cleanliness, not an error state — a program with
# an unused import or a dead local still parses, compiles, and runs. Some linters tag
# these with a severity code we already drop (pylint W0611, pycodestyle), but the most
# common ones do NOT: pyflakes prints a bare English message with no code at all, and
# ruff/flake8 attach the SAME message to an F-code we otherwise deliberately keep
# (F-series = real bugs like undefined names). Keying off the code therefore can't work
# uniformly — so we match on the MESSAGE, tool-agnostically: the identical phrase is
# treated the same whether it came from pyflakes, ruff, flake8, eslint (no-unused-vars),
# or tsc (TS6133/TS6196). Substring, case-insensitive — the same mechanic the errorish
# scan uses. Deliberately EXCLUDES Go's "imported and not used" / "declared and not
# used": those are hard COMPILE errors (the build fails), not lint advisories, so they
# must keep gating — the "and"/"not" phrasing keeps them distinct from the advisories.
_ADVISORY_PHRASES = (
    "imported but unused",                   # pyflakes · ruff F401 · flake8
    "assigned to but never used",            # pyflakes · ruff F841
    "annotated but never used",              # pyflakes
    "assigned a value but never used",       # eslint no-unused-vars
    "defined but never used",                # eslint no-unused-vars
    "declared but its value is never read",  # tsc TS6133 (unused local)
    "declared but never used",               # tsc TS6196 (unused type)
    # THE SAME CLASS — for the IMPORT form. pyflakes emits
    # `redefinition of unused 'json' from line 14` when a name is bound twice and the first binding
    # went unused. For imports it changes nothing at runtime — the unused-import warning wearing
    # different words. pyflakes prints no code, so _STYLE_CODE cannot catch it either, and it once
    # sailed through as an ERROR.
    #
    # Walked on ada-handles_mellum2_codex_poff_1785693138: for roughly 25 consecutive calls this was
    # the ONLY thing cria's gate reported, shipped under "[GROUND TRUTH — the repo's own checks
    # fail]". The edit that finally cleared it deleted the module-level `import json`. pyflakes then
    # reported nothing — the function-local `import json` satisfies it — and the delivered program
    # crashes with `NameError: name 'json' is not defined`. cria's gate demanded a change that broke
    # the program and then certified the result clean. It also taught the model to disbelieve the
    # gate: when pyflakes later reported a REAL error (`undefined name '_test'`) the model wrote
    # "The flags are false positives … The project's own checks are wrong."
    #
    # BUT F811 also fires on two FUNCTIONS/CLASSES with the same name, where the second silently
    # wins — a REAL bug. The old "KNOWN COST, accepted deliberately" trade suppressed that form too,
    # and the maple walk paid it: on ada-handles_maple-preview_codex_poff_1785956867 the coder wrote
    # two `def resolve_handle` in one file, the second shadowed the network resolver, the "live"
    # path recursed into its own simulator, and pyflakes' suppressed line was the only checker
    # output naming the root cause. The discriminator the old comment called for now exists: the
    # flagged line's on-disk text, INJECTED by callers that hold the file (``is_advisory``'s
    # ``flagged_line`` / ``parse_output``'s ``read_source_line`` — this module stays pure). A
    # def/class flagged line makes the F811 error-class; an import line (or no line available)
    # keeps the advisory default.
    "redefinition of unused",                # pyflakes F811 (import form; see discriminator above)
    "f-string is missing placeholders",      # pyflakes F541 · a cosmetic slip, runs fine
    # PARITY ACROSS THE ECOSYSTEM (2026-08-08). Seven phrases covered pyflakes/ruff/flake8/eslint/
    # tsc and nothing else, so the same dead local that is advisory in Python gated a step in Rust,
    # Ruby, PHP, C# or Java. The rule is per-LANGUAGE, not per-tool: it belongs here only when the
    # program still parses, compiles and RUNS with the finding present.
    "unused variable",                       # rustc/clippy · gcc/clang -Wunused-variable · swiftc
    "unused import",                         # rustc · scalac · kotlinc
    "unused mut",                            # rustc
    "never used",                            # rustc "field is never read" · "method is never used"
    "is never read",                         # rustc dead_code · C# IDE0052
    "useless assignment to variable",        # rubocop Lint/UselessAssignment
    "assigned but never used",               # go vet's staticcheck SA4006 wording · rubocop
    "is assigned a value but never used",    # C# CS0219
    "was declared but never used",           # phpstan/psalm · kotlinc
    "unused parameter",                      # clang/gcc -Wunused-parameter · phpmd
    "unused local variable",                 # phpstan · elixir mix compile
    # NOT HERE, DELIBERATELY: Go's own compiler. `declared and not used: x` and
    # `"fmt" imported and not used` are COMPILE ERRORS in Go — the program does not build, so the
    # finding is error-class by the language's own rule and gating on it is correct. The identical
    # English in another language's linter is a warning; in Go it is a wall. Any phrase added above
    # must be checked against this: it is advisory only where the program still runs.
)

F811_PHRASE = "redefinition of unused"


def f811_is_shadow(flagged_line: Optional[str]) -> bool:
    """True when the line an F811 finding flags (the SECOND binding) is a ``def``/``class``
    statement — the runtime-shadow form, a real bug. An import line or an unavailable line is the
    cleanliness form. Pure: the caller supplies the line text."""
    s = (flagged_line or "").lstrip()
    return s.startswith(("def ", "async def ", "class "))


def is_advisory(message: str, flagged_line: Optional[str] = None) -> bool:
    """True when a diagnostic is advisory/style — a ``note:``/``warning:`` severity prefix, a
    pycodestyle/pylint style code (``W###``/``C####``/``R####``, E9xx syntax kept), or an
    unused/never-used phrase (any linter). These must neither gate a step NOR reach the model as
    a "problem to fix" — the single predicate used by both the gate filter and the gate-output
    cleaner, so the two can't diverge.

    ``flagged_line`` is the on-disk text of the line the finding flags, supplied by callers with
    file access: it refines exactly one case — an F811 redefinition whose second binding is a
    ``def``/``class`` is a real shadow, NOT advisory. Without it the pure default is unchanged."""
    m = (message or "").lstrip()
    low = m.lower()
    if F811_PHRASE in low and f811_is_shadow(flagged_line):
        return False
    return (low.startswith(("note:", "warning:", "hint:", "info:", "convention:", "refactor:"))
            or bool(_STYLE_CODE.match(m))
            or any(p in low for p in _ADVISORY_PHRASES))


def _error_class_only(findings: list, read_source_line=None) -> list:
    """Drop advisory findings. ``read_source_line(path, line) -> str | None`` — supplied by
    callers with file access — lets the F811 discriminator see the flagged line (see the
    _ADVISORY_PHRASES comment); only F811 findings trigger a read."""
    out = []
    for f in findings:
        flagged = None
        if (read_source_line is not None and f.file and f.line
                and F811_PHRASE in (f.message or "").lower()):
            flagged = read_source_line(f.file, f.line)
        if not is_advisory(f.message or "", flagged):
            out.append(f)
    return out


def parse_output(command: str, family: str, exit_code: Optional[int],
                 stdout: str, stderr: str, read_source_line=None) -> ProbeResult:
    """The public entry point: raw streams -> deduped findings + one-line summary."""
    combined = stdout + "\n" + stderr  # exactly one \n between, no strip
    findings = _FAMILY_PARSERS.get(family, lambda s: [])(combined)
    # The fallbacks below are SHAPE scrapers: they know `file:line: text` and nothing about the tool
    # that printed it. That shape occurs in output which is not a failure at all — pytest's own
    # "warnings summary" section prints it for every warning of a run that PASSED. So they may only
    # run when the tool itself reported failure. A family parser knows its tool's contract and is
    # unaffected; `exit_code is None` means UNKNOWN, not zero, and still scrapes.
    #
    # MEASURED in the captures: a run whose tests passed (exit 0, "1 passed") emitted
    # `test_resolve_handle.py:95: PytestUnknownMarkWarning: Unknown pytest.mark.live` as a Finding,
    # which cria shipped under "[GROUND TRUTH — the repo's own checks fail]" in 40 consecutive
    # prompts. parse_pytest had correctly returned nothing; parse_generic manufactured it. cria
    # stating a false fact about the repo's own checks is the worst thing this module can do.
    if exit_code != 0:
        if not findings:
            # upstream quirk, preserved: when family was "cargo" and found nothing,
            # parse_rustc runs a second time here — harmless, structure kept.
            findings = parse_rustc(combined)
        if not findings:
            findings = parse_generic(combined)
        if not findings:
            # tier-0 config-syntax floor: tomllib/json decode errors report location as prose
            # (`(at line N, column M)` / `line N column M`), not `file:line:col:`.
            findings = parse_config_syntax(combined)
    findings = _error_class_only(findings, read_source_line)
    dedup(findings)
    summary = summarize(findings, exit_code, combined)
    # THE TALLY IS TAKEN HERE OR NOWHERE. `summarize` returns the fixed string "no problems reported"
    # for a green run and `combined` is not retained, so a reader that only sees the ProbeResult has
    # no way back to "4 passed, 1 skipped". Both consumers only ever look at GREEN gates, so both
    # were reading a string that can never contain a tally.
    return ProbeResult(command=command, exit_code=exit_code, summary=summary, findings=findings,
                       tally=runner_tally(combined),
                       skipped=sum(int(n) for n in _SKIPPED_RE.findall(combined)))


# ---------------------------------------------------------------------------
# caller-contract slivers ported from probe_run.rs (all still pure)
# ---------------------------------------------------------------------------

def family_of(tokens: Sequence[str]) -> str:
    """Argv tokens -> parser family. Whole-token equality, NEVER substring.

    Must run over the pre-join token list the composer built — re-tokenizing a
    joined shell string would break whole-token equality under quoting.
    """
    def has(t: str) -> bool:
        return any(tok == t for tok in tokens)

    if has("compileall") or has("py_compile"):
        return "pycompile"   # tier-0 congruence layer (not in the Rust)
    if has("node") and has("--check"):
        return "nodecheck"   # tier-0 congruence layer
    if has("php") and has("-l"):
        return "phplint"     # tier-0 congruence layer
    if has("cargo"):
        return "cargo"
    if has("tsc") or has("vue-tsc"):
        return "tsc"
    if has("eslint"):
        return "eslint"
    # Upstream also writes (has("python") && has("pytest")) || (has("python3") &&
    # has("pytest")) — both disjuncts are redundant with has("pytest"); collapsed
    # per spec.
    if has("pytest"):
        return "pytest"
    if has("mypy"):
        # upstream quirk, preserved: parse_output has no "mypy" arm — this family
        # falls to the rustc-then-generic fallback. Intentional.
        return "mypy"
    return ""  # generic scanners: ruff/flake8/go/gcc/etc.


def err_result(command: str, msg: str) -> ProbeResult:
    """Executor-failure result shape: no exit code, no findings, message as summary."""
    return ProbeResult(command=command, exit_code=None, summary=msg, findings=[])


def timeout_summary(secs: float) -> str:
    """The summary that OVERWRITES a timed-out probe's parsed summary."""
    if isinstance(secs, float) and secs.is_integer():
        secs = int(secs)  # "TIMEOUT after 20s", not "20.0s"
    return TIMEOUT_SUMMARY_FMT.format(secs=secs)


class Runner(Protocol):
    """The injectable execution seam — cria owns no executors.

    A Runner runs ``argv`` in ``cwd`` with a wall-clock cap of ``timeout_s``
    seconds and returns ``(exit_code_or_None, stdout, stderr, timed_out)``.
    ``exit_code`` is None when unavailable (killed by timeout or signal, wait
    error). On timeout, partial output already drained should still be
    returned — findings salvaged from it are kept. A launch failure (binary
    missing, not executable) must raise :class:`OSError`.
    """

    def __call__(self, argv: Sequence[str], cwd: str,
                 timeout_s: float) -> tuple[Optional[int], str, str, bool]: ...


def run_candidate(runner: Runner, tokens: Sequence[str], cwd: str,
                  timeout_s: float) -> ProbeResult:
    """Run one probe candidate via the injected runner and parse what came back.

    Port of probe_run.rs::run_candidate minus the host-side process machinery
    (spawn, pipe-drain threads, poll loop, kill) — that all lives behind the
    Runner. What remains is the upstream result contract: empty command and
    launch failure produce :func:`err_result` shapes; a timeout parses the
    partial output normally, then OVERWRITES the summary (findings kept).
    """
    if not tokens:
        return err_result("", EMPTY_COMMAND_SUMMARY)
    command = " ".join(tokens)  # display-only; family comes from the token list
    try:
        exit_code, stdout, stderr, timed_out = runner(tokens, cwd, timeout_s)
    except OSError as e:
        return err_result(command, LAUNCH_FAILURE_FMT.format(e=e))
    result = parse_output(command, family_of(tokens), exit_code, stdout, stderr)
    if timed_out:
        result.summary = timeout_summary(timeout_s)
    return result


# ---------------------------------------------------------------------------
# "Your dependency is missing" is a different problem from "your code is wrong"
# ---------------------------------------------------------------------------
# A weak model cannot tell them apart from the raw output, and the cost of confusing them is not a
# wasted call, it is the rest of the run. Measured on the six-language battery: 39 of 73
# dependency-shaped checks failed, and 8 of those had the dependency DECLARED correctly and simply
# not loadable. gemma4's ruby run installed two gems, `require` failed, three checks that had been
# passing went red, and it spent the remaining twenty minutes fighting the package manager instead
# of the task.
#
# Every ecosystem says this plainly in its own words, so this is CLASSIFICATION of the tool's own
# error class (#12), not a guess about prose. Rows are only included where the message can mean
# nothing else — an ambiguous one ("package X does not exist", which is equally a typo in the
# project's own code) is left out rather than risk mislabelling a real bug (#3).
_DEPENDENCY_MISSING = (
    # ruby: cannot load such file -- countries (LoadError)
    ("ruby", re.compile(r"cannot load such file -- (\S+)\s*\(LoadError\)")),
    # python: ModuleNotFoundError: No module named 'requests'
    ("python", re.compile(r"ModuleNotFoundError: No module named ['\"]([\w.]+)['\"]")),
    # node: Error: Cannot find module 'commander'
    ("node", re.compile(r"Cannot find module ['\"]([^'\"]+)['\"]")),
    # rust: error[E0463]: can't find crate for `toml`
    ("rust", re.compile(r"can't find crate for `([\w-]+)`")),
    # go: no required module provides package example.com/x
    ("go", re.compile(r"no required module provides package (\S+)")),
    # maven: Could not resolve dependencies for project … commons-csv:jar:1.10.0
    ("java", re.compile(r"Could not resolve dependencies[^\n]*?([\w.-]+:[\w.-]+:[\w.:-]+)")),
)


# Evidence on disk that an install into THIS PROJECT has actually happened, per ecosystem. Only the
# three where the answer lives inside the workspace: rust/go/java resolve from caches outside it, and
# their notes are about DECLARING a dependency rather than loading an installed one.
_INSTALL_EVIDENCE = {
    "ruby": ("Gemfile.lock", "vendor", ".bundle"),
    "node": ("node_modules",),
    "python": (".venv", "venv", "site-packages", ".tox"),
}


def install_landed(eco: str, workspace_root: str) -> bool | None:
    """Has an install into this project actually landed? ``None`` when cria cannot tell.

    The note beside a `cannot load such file` says how to put an installed library on the load path.
    That is the right advice AFTER an install and a false description of the world before one.

    Walked twice in cycle 4, independently — cell 13 (`shipping-rates-rb x ternary-bonsai`) and cell
    19 (`shipping-rates-rb x nemotron-elastic`). In cell 19 cria said, at call 0061:

        Note: `countries` is installed nowhere ruby is looking. A gem installed with --install-dir is
        not on the load path by default … Fix the loading; the code that uses it is not what failed
        here.

    Every `gem install` that run had been REFUSED and every `bundle install` was `command not found`;
    the surviving workspace has no `vendor/`, no `.bundle/` and no `Gemfile.lock`. So the sentence
    describes an install that never happened, and its last clause rules out the one correct next
    move — the install IS what failed. The model read it and went straight back to `gem install`,
    which was the last action of the run.

    Recorded as `MODIFY FIRST — add a condition, never soften the sentence` in the cycle-3 ledger and
    not landed then; two more sightings is enough."""
    ev = _INSTALL_EVIDENCE.get(eco)
    # `os.walk` on a path that does not exist yields NOTHING and raises nothing, so without this the
    # answer to "is anything installed" would be a confident False about a workspace cria cannot see
    # — the same class of false fact this function exists to stop.
    if not ev or not workspace_root or not os.path.isdir(workspace_root):
        return None
    root = os.path.join(workspace_root, "")
    try:
        for dirpath, dirnames, filenames in os.walk(workspace_root):
            if any(n in ev for n in filenames) or any(n in ev for n in dirnames):
                return True
            # Bounded: an install tree lives at the top of a project, not eight levels down.
            if dirpath[len(root):].count(os.sep) >= 2:
                dirnames[:] = []
        return False
    except OSError:
        return None


def dependency_missing(text: str) -> tuple[str, str] | None:
    """``(ecosystem, name)`` when this output says a dependency could not be loaded — else None.

    The name is whatever the TOOL named, verbatim. cria adds no interpretation here; a caller that
    wants to know whether the name is the project's own file asks the filesystem
    (:func:`names_a_workspace_file`), because that is a fact, not a judgment (#8)."""
    for eco, pat in _DEPENDENCY_MISSING:
        m = pat.search(text or "")
        if m:
            return eco, m.group(1)
    return None


# A dotted or slashed name's FIRST segment is the thing that has to resolve — `shipping.rates` is
# the project's own `shipping/` package, `commons.csv` is not. Matching on the whole name would call
# every submodule third-party.
def names_a_workspace_file(name: str, workspace_root: str) -> bool:
    """Does this import name correspond to something the workspace itself provides?

    Deliberately generous about extension and layout: the question is only "is this the project's
    own code", and a false YES is the safe direction — it means cria says nothing (#3) rather than
    telling the coder its own module is a missing dependency."""
    import os as _os
    if not name or not workspace_root or not _os.path.isdir(workspace_root):
        return False
    head = re.split(r"[./\\:]", name.strip("'\"" ))[0]
    if not head:
        return False
    for dirpath, dirnames, filenames in _os.walk(workspace_root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if head in dirnames:
            return True
        for f in filenames:
            if f == head or f.rsplit(".", 1)[0] == head:
                return True
    return False
