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

import re
from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence

# Summary truncation lengths (Unicode code points, matching Rust `chars()`).
SUMMARY_MSG_LIMIT = 100    # first finding's message inside the summary line
SUMMARY_LINE_LIMIT = 120   # last-error-line fallback for non-zero exits
TRUNCATION_SUFFIX = "…"  # … U+2026 HORIZONTAL ELLIPSIS

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


@dataclass(eq=False)  # upstream derives Debug+Clone but NOT Eq — keep it non-comparable
class ProbeResult:
    """What one probe command produced, rendered model-ready."""
    command: str                       # stored verbatim for display; never re-parsed
    exit_code: Optional[int] = None    # None = unavailable (timeout / signal / wait error)
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def parse_u32(s: str) -> Optional[int]:
    """Rust ``str::parse::<u32>()``: '+'-optional ASCII digits fitting in u32, else None."""
    if not _U32_RE.fullmatch(s):
        return None
    value = int(s)
    return value if value <= U32_MAX else None


def truncate(s: str, n: int) -> str:
    """Trim, then cap at ``n`` code points with a trailing ellipsis (only when over)."""
    s = s.strip()
    return s if len(s) <= n else s[:n] + TRUNCATION_SUFFIX


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


def split_diag(s: str) -> Optional[tuple[str, Optional[int], Optional[int], str]]:
    """``file:line[:col]: message`` -> (file, line, col, message). Used by parse_generic."""
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
        if t.startswith("error"):
            rest = t[len("error"):]
        elif t.startswith("warning"):
            rest = t[len("warning"):]
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
                last_msg = msg
        elif t.startswith("--> "):  # elif: a line is never both header and location
            loc = t[len("--> "):].strip()
            r = split_loc(loc)
            if r is not None:
                file, line, col = r
                out.append(Finding(file, line, col,
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


def parse_pytest(s: str) -> list[Finding]:
    """pytest short-test-summary lines only: ``FAILED path::test - Error: msg``.

    No line numbers ever — pytest findings carry ``line=None``. Traceback
    ``file:line:`` rows are deliberately NOT read here; the generic fallback
    only runs if this returns zero findings.
    """
    out: list[Finding] = []
    for l in s.splitlines():
        t = l.strip()
        if t.startswith("FAILED "):
            rest = t[len("FAILED "):]
        elif t.startswith("ERROR "):
            rest = t[len("ERROR "):]
        else:
            continue
        if " - " in rest:
            nodeid, msg = rest.split(" - ", 1)  # FIRST " - " splits node-id from message
        else:
            nodeid, msg = rest, ""
        file = nodeid.split("::", 1)[0]
        out.append(Finding(file, line=None, col=None,
                           message=(msg if msg != "" else DEFAULT_PYTEST_MESSAGE)))
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


def summarize(findings: list[Finding], exit_code: Optional[int], combined: str) -> str:
    """One line the model can act on: first finding, or the last error-ish output line."""
    if findings:
        f = findings[0]
        if f.line is not None and f.file != "":
            loc = f"{f.file}:{f.line}"
        elif f.file != "":
            loc = f.file
        else:
            loc = UNKNOWN_LOCATION
        more = f" (+{len(findings) - 1} more)" if len(findings) > 1 else ""
        return f"{loc}: {truncate(f.message, SUMMARY_MSG_LIMIT)}{more}"
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
    return f"exited {exit_code}: {truncate(line, SUMMARY_LINE_LIMIT)}"


# Family dispatch: exact match on the `family` argument. No caller ever passes
# "unittest", but upstream accepts it — the arm stays. "mypy" has NO arm on
# purpose: it falls to the rustc-then-generic fallback below.
# ---------------------------------------------------------------------------
# Tier-0 congruence parsers (cria addition — every ecosystem's parse floor yields
# file:line findings, exactly like the ranked tools' parsers)
# ---------------------------------------------------------------------------

_PYCOMPILE_LOC = re.compile(r'File "([^"]+)", line (\d+)')


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
        if pending is not None and ("Error" in t or "error" in t.split(":")[0:1] == ["error"]):
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
)


def is_advisory(message: str) -> bool:
    """True when a diagnostic is advisory/style — a ``note:``/``warning:`` severity prefix, a
    pycodestyle/pylint style code (``W###``/``C####``/``R####``, E9xx syntax kept), or an
    unused/never-used phrase (any linter). These must neither gate a step NOR reach the model as
    a "problem to fix" — the single predicate used by both the gate filter and the gate-output
    cleaner, so the two can't diverge."""
    m = (message or "").lstrip()
    low = m.lower()
    return (low.startswith(("note:", "warning:", "hint:", "info:", "convention:", "refactor:"))
            or bool(_STYLE_CODE.match(m))
            or any(p in low for p in _ADVISORY_PHRASES))


def _error_class_only(findings: list) -> list:
    return [f for f in findings if not is_advisory(f.message or "")]


def parse_output(command: str, family: str, exit_code: Optional[int],
                 stdout: str, stderr: str) -> ProbeResult:
    """The public entry point: raw streams -> deduped findings + one-line summary."""
    combined = stdout + "\n" + stderr  # exactly one \n between, no strip
    findings = _FAMILY_PARSERS.get(family, lambda s: [])(combined)
    if not findings:
        # upstream quirk, preserved: when family was "cargo" and found nothing,
        # parse_rustc runs a second time here — harmless, structure kept.
        findings = parse_rustc(combined)
    if not findings:
        findings = parse_generic(combined)
    findings = _error_class_only(findings)
    dedup(findings)
    summary = summarize(findings, exit_code, combined)
    return ProbeResult(command=command, exit_code=exit_code,
                       summary=summary, findings=findings)


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
