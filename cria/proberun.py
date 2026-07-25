"""Bounded probe execution + orchestration — ties discovery → run → parse together.

Upstream module doc (verbatim): "Runs a small number of the highest-ranked SAFE
probes with a hard timeout, captures output without blocking on full pipes, and
hands each result to ``probe_parse``. The end product is a compact report the
small model can act on: which probes ran, what failed, and the ``file:line`` to
fix."

Faithful port of codex-local's ``codex-rs/routing/src/probe_run.rs`` (the spec
source of truth). This module deliberately contains no vetting and no parsing:
safety is entirely upstream (``discover()`` returns only candidates that passed
discovery's is_safe gate) and output parsing lives in :mod:`cria.probeparse`.
What lives HERE is selection (which probes run, in what order), the per-probe
result contract (empty command / launch failure / timeout), and the two
model-facing renderings:

- :func:`completion_block_nudge` — the deterministic completion GATE. Silent
  (None) unless a probe produced structured ``file:line`` findings or the
  syntax floor is dirty; a probe that merely timed out or could not launch
  never blocks, because we only block on a real diagnosis.
- :func:`completion_probe_digest` — the critic-facing record of WHAT RAN and
  its raw outcome. This exposes what the gate cannot act on and what otherwise
  looks identical to "clean": a test suite that failed to RUN (import error,
  nothing collected), timed out, or never launched. The critic needs it to
  tell "tests pass" apart from "tests never ran".

WHO EXECUTES: cria owns no executors. Upstream spawned the probe inline
(pipe-drain threads, a 40ms try_wait poll loop, kill-on-timeout); all of that
host machinery sits behind the injectable ``Runner`` protocol defined in
:mod:`cria.probeparse` — ``runner(argv, cwd, timeout_s) -> (exit_code | None,
stdout, stderr, timed_out)``. For proxy deployments where even the Runner is
unavailable (the harness's shell tool is the only executor), the same probe is
expressed as one composed shell line (:func:`compose_probe_command`) and the
tool result that flows back is mapped onto the identical ProbeResult contract
(:func:`interpret_probe_output`): coreutils ``timeout`` stands in for the kill
loop (exit 124), ``exit 127`` / "command not found" stands in for the spawn
error, an output cap stands in for RAM being cheap (upstream drained pipes
unbounded and let probe_parse truncate — in cria the capture lands in the
model's context, so it is capped at composition time), and a trailing
``EXIT:<n>`` sentinel recovers the exit code when the harness returns text
only.

Timeout interplay (proxy path): the harness's own shell-tool timeout must
exceed the probe timeout, or the harness kills the command before timeout(1)
fires and cria sees a harness-level failure instead of exit 124.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from . import probediscovery, prompts
from .probeparse import (
    EMPTY_COMMAND_SUMMARY,
    LAUNCH_FAILURE_FMT,
    TIMEOUT_SUMMARY_FMT,
    ProbeResult,
    Runner,
    err_result,
    family_of,  # re-exported: upstream defines family_of in probe_run.rs
    parse_output,
)

if TYPE_CHECKING:  # annotation-only names
    from .linterprobe import LinterReport
    from .probediscovery import ProbeCandidate

# ---------------------------------------------------------------------------
# Upstream constants (probe_run.rs, verbatim values)
# ---------------------------------------------------------------------------

# Default: run at most 3 probes, 120s each. Callers can override.
DEFAULT_MAX_PROBES = 3
DEFAULT_TIMEOUT_S = 120.0
# Upstream's child try_wait() poll cadence (40ms). cria never polls a child —
# this is the contract value a host-side Runner implementation should honor.
CHILD_POLL_INTERVAL_S = 0.040
# (Upstream's .take(5) per-probe findings cap was removed — completion_block_nudge now shows EVERY
# file:line finding so an error past the 5th is never hidden from the model.)

# Message/format strings — byte-for-byte with upstream, now sourced from prompts/ so they're tunable
# (loaded once at import; a cria restart re-tunes). The preamble ends with a newline `load` strips,
# so it's re-added here; the Rust source's `\` line-continuation collapses to a single space (one
# space between "exact" and "problems"), preserved in prompts/block_nudge_preamble.txt.
BLOCK_NUDGE_PREAMBLE = prompts.load("block_nudge_preamble") + "\n"
_DIGEST = prompts.load_map("probe_digest")
DIGEST_FLOOR_FMT = _DIGEST["floor_fmt"]  # single-brace {x}, filled by .format()
DIGEST_FLOOR_CLEAN = _DIGEST["floor_clean"]
DIGEST_FLOOR_FALLBACK = _DIGEST["floor_fallback"]
DIGEST_FLOOR_NONE = _DIGEST["floor_none"]
DIGEST_NO_PROBES = _DIGEST["no_probes"]
DIGEST_EXIT_CLEAN = _DIGEST["exit_clean"]
DIGEST_EXIT_NO_LAUNCH = _DIGEST["exit_no_launch"]
DIGEST_EXIT_NO_TESTS = _DIGEST["exit_no_tests"]

# ---------------------------------------------------------------------------
# cria constants (proxy path — NOT probe_run.rs values)
# ---------------------------------------------------------------------------

# Output budget applied at composition time. Upstream read_to_string'd the pipes unbounded and let
# probe_parse truncate per-line; in cria the capture lands in the model's context, so the composed
# command bounds it. NOT tail-only: a test/build that prints its real failure EARLY then a long
# teardown/summary would lose the failure under a tail clip. compose_probe_command keeps HEAD + TAIL
# (half the budget each, with a disclosed "middle N bytes elided" marker) so an early failure AND a
# late one both survive. Only bites on genuinely huge output; the window-aware context floor is the one
# place a real truncation may happen.
PROBE_OUTPUT_CAP_BYTES = 16384
# Trailing sentinel that smuggles the probe's exit code through a text-only
# shell-tool result; scrape_exit() recovers it.
PROBE_EXIT_SENTINEL = "EXIT:"
# coreutils timeout(1) semantics standing in for upstream's kill loop.
TIMEOUT_KILL_GRACE_S = 5     # timeout -k 5: SIGKILL follow-up for SIGTERM-ignoring tools
TIMEOUT_EXIT_CODE = 124      # timeout(1) fired -> upstream's timed_out=true branch
NOT_EXECUTABLE_EXIT_CODE = 126  # shell: found but not executable (permission/broken interpreter)
NOT_FOUND_EXIT_CODE = 127    # shell: command not found -> upstream's spawn-Err branch
# Every coreutils timeout(1) exit code that means the command did NOT actually run: 125 (timeout
# itself failed), 126 (found but not executable), 127 (not found). All map to a launch failure
# (exit_code=None) so unran_probes flags them and the gate never reads a couldn't-run as clean. 124
# (timed out) is separate — there the command DID run, so partial findings are salvaged.
LAUNCH_FAILURE_EXIT_CODES = (125, NOT_EXECUTABLE_EXIT_CODE, NOT_FOUND_EXIT_CODE)
NOT_FOUND_TEXT = "command not found"
PROXY_LAUNCH_DETAIL = "command not found"  # the {e} detail when the shell, not the OS, tells us
# pytest returns exit 5 when it collected ZERO tests (a fresh/testless project, or a target with no
# matching tests). The runner launched fine and simply had nothing to run — NOT a failing test. Every
# interpreter below treats it as a benign no-signal (like a launch failure), never a hard failure, or
# a testless project's completion-gate reads "tests broke". pytest is the only common runner using 5
# this way; the text markers CONFIRM it so a bare-text gate section (no command in hand) is still
# recognized and some other tool's incidental exit-5 is not misclassified.
PYTEST_NO_TESTS_EXIT = 5
_NO_TESTS_MARKERS = ("no tests ran", "no tests collected", "collected 0 items")


def is_no_tests_collected(exit_code: Optional[int], command: str = "", output: str = "") -> bool:
    """True when a probe result is pytest's NO_TESTS_COLLECTED (exit 5 + a pytest fingerprint in the
    command or output). Callers treat it as a neutral non-signal, never a failure."""
    if exit_code != PYTEST_NO_TESTS_EXIT:
        return False
    hay = f"{command}\n{output}".lower()
    return "pytest" in hay or any(m in hay for m in _NO_TESTS_MARKERS)


@dataclass
class ProbeReport:
    """What ran and what came back; ``selected[i]`` produced ``results[i]``."""
    project_type: list[str] = field(default_factory=list)
    selected: list[ProbeCandidate] = field(default_factory=list)
    results: list[ProbeResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Selection (pure filesystem reads — stays local and synchronous)
# ---------------------------------------------------------------------------

def select_probes(root: str, max_probes: int) -> list[ProbeCandidate]:
    """The top ``max_probes`` candidates, best-first. ``discover()`` already
    safe-filtered and ranked; selection is just the slice."""
    return probediscovery.discover(root)[:max_probes]


# Non-floor ranked candidates admitted per gate (the per-file floor is bounded separately by
# MAX_FLOOR_FILES_PER_LANG). Keeps a polyglot repo's gate bounded while still guaranteeing every
# ecosystem's compile/typecheck tier runs.
MAX_RANKED_GATE_PROBES = 6


def select_completion_probes(root: str) -> list[ProbeCandidate]:
    """The completion-time selection — CONGRUENT across ecosystems:

    1. The tier-0 syntax floor for every language whose FILES are present
       (probediscovery.syntax_floor_candidates: compileall / node --check /
       php -l / ruby -c) and each language's zero-config LINTER
       (probediscovery.lint_floor_candidates: pyflakes, clippy, go vet). No manifest required — a
       fresh workspace has source files long before config.
    2. EVERY ranked candidate at tier ≤ 1 (Typecheck/BuildCheck): the compile
       floor of build-system languages (cargo check, go build, tsc, mvn/gradle
       compile, dotnet build, mix compile). All of them — a polyglot repo gets
       each language's compile check, not just the best-ranked one.
    3. The best-ranked config-driven LINTER (evidence-based: eslint/ruff/phpstan…) —
       the lint category is guaranteed a slot; ranking only decides which tool fills it.
    4. The first Test-kind candidate — upstream rationale (load-bearing, kept):
       discovery ranks typecheck/lint/build ABOVE tests, so a top-1-only gate
       green-lights a repo whose tests fail. At a "done" claim the tests run.
    Deduped by full argv equality; ranked additions capped at
    MAX_RANKED_GATE_PROBES (floor excluded from the cap, its own bounds apply).
    """
    selected: list[ProbeCandidate] = list(probediscovery.syntax_floor_candidates(root))
    for c in probediscovery.lint_floor_candidates(root):
        if not any(x.command == c.command and x.working_dir == c.working_dir for x in selected):
            selected.append(c)
    # The TEST floor: a bare "script + test_*.py" project (no pyproject/pytest.ini/tests dir) is not a
    # detected ecosystem, so ranked discovery yields NO test probe — the gate then runs syntax+lint but
    # never the tests (a vacuous-green that reports "no problems" while the tests fail). pytest
    # auto-discovers root test_*.py; add it as a guaranteed floor, like syntax/lint.
    for c in probediscovery.test_floor_candidates(root):
        if not any(x.command == c.command and x.working_dir == c.working_dir for x in selected):
            selected.append(c)

    def _add(c) -> None:
        if not any(x.command == c.command and x.working_dir == c.working_dir for x in selected):
            selected.append(c)

    ranked = probediscovery.discover(root)
    n_floor = len(selected)
    for c in ranked:
        if c.tier() <= 1 and len(selected) - n_floor < MAX_RANKED_GATE_PROBES:
            _add(c)  # the COMPILE category: every ecosystem's typecheck/build check
    # The LINT category gets a guaranteed slot too: the best-ranked config-driven linter
    # (eslint/ruff/phpstan/... — evidence-based) must not be squeezed out by higher-ranked
    # typechecks. Ranking chooses WHICH linter; the category always runs when one exists.
    lint = next((c for c in ranked if c.kind in (probediscovery.ProbeKind.Lint,
                                                 probediscovery.ProbeKind.StaticAnalysis)), None)
    if lint is not None:
        _add(lint)
    test = next((c for c in ranked
                 if c.kind is probediscovery.ProbeKind.Test), None)
    if test is not None:
        _add(test)  # the test probe is never squeezed out by the cap
    return selected


# ---------------------------------------------------------------------------
# Execution via the injectable Runner seam
# ---------------------------------------------------------------------------

def run_candidate(runner: Runner, c: ProbeCandidate, timeout_s: float) -> ProbeResult:
    """Run one candidate with a hard timeout via the injected runner.

    Never mutates the workspace (the candidate was vetted safe upstream, in
    discovery). Upstream's process machinery — spawn, drain threads so a chatty
    tool can't deadlock on a full pipe, the 40ms poll loop, kill+reap — lives
    behind the Runner; what is ported here is the result contract.
    """
    joined = display_command(c.command)
    if not c.command:
        return err_result(joined, EMPTY_COMMAND_SUMMARY)   # joined == "" here
    try:
        exit_code, stdout, stderr, timed_out = runner(list(c.command),
                                                      str(c.working_dir), timeout_s)
    except OSError as e:  # FileNotFoundError, PermissionError, ...
        return err_result(joined, LAUNCH_FAILURE_FMT.format(e=e))
    if exit_code is not None and exit_code < 0:
        # Rust status.code() is None for signal-kills; a Python subprocess
        # runner reports -signum — normalize so both worlds agree.
        exit_code = None
    result = parse_output(joined, family_of(c.command), exit_code, stdout, stderr)
    if timed_out:
        # upstream quirk, preserved: Duration::as_secs() TRUNCATES — a 0.4s
        # timeout reads "TIMEOUT after 0s". The summary is OVERWRITTEN but any
        # findings parsed from the partial pre-kill output are KEPT.
        result.summary = TIMEOUT_SUMMARY_FMT.format(secs=int(timeout_s))
        result.timed_out = True   # ran and did NOT finish → the completion gate fails CLOSED (M3)
    return result


def run_probes(runner: Runner, root: str) -> ProbeReport:
    """Default: run at most 3 probes, 120s each. Callers can override."""
    return run_probes_with(runner, root, DEFAULT_MAX_PROBES, DEFAULT_TIMEOUT_S)


def run_probes_with(runner: Runner, root: str, max_probes: int,
                    timeout_s: float) -> ProbeReport:
    """Select the top candidates and run them sequentially, in rank order."""
    selected = select_probes(root, max_probes)
    results = [run_candidate(runner, c, timeout_s) for c in selected]
    return ProbeReport(
        project_type=list(probediscovery.project_types(root)),
        selected=selected,
        results=results,
    )


def run_completion_probes(runner: Runner, root: str, timeout_s: float) -> ProbeReport:
    """Run the completion-time selection (see :func:`select_completion_probes`),
    each probe bounded by ``timeout_s``."""
    selected = select_completion_probes(root)
    results = [run_candidate(runner, c, timeout_s) for c in selected]
    return ProbeReport(
        project_type=list(probediscovery.project_types(root)),
        selected=selected,
        results=results,
    )


# ---------------------------------------------------------------------------
# Model-facing renderings (pure)
# ---------------------------------------------------------------------------

def _kind_by_command(report: ProbeReport) -> dict:
    """joined-command → ProbeKind, for results→candidate correlation (results may be a
    subset of selected when a section never came back)."""
    return {display_command(c.command): c.kind for c in report.selected}


def syntax_floor_clean(report: ProbeReport):
    """True/False for the tier-0 checks that RAN; None when none did (nothing to judge).
    The truth-capture event's floor_clean field."""
    kinds = _kind_by_command(report)
    syntax = [r for r in report.results
              if kinds.get(r.command) is probediscovery.ProbeKind.SyntaxCheck]
    if not syntax:
        return None
    return all(r.exit_code == 0 for r in syntax)


def unran_probes(report: ProbeReport) -> list[str]:
    """Human labels for probes that were selected and CAME BACK but did NOT actually complete — a
    launch failure (tool/interpreter absent) or a timeout, both of which interpret_probe_output maps
    to ``exit_code is None``. Their silence is MISSING SIGNAL, never a pass: a test suite that could
    not launch cannot vouch for behaviour. Callers that render ground truth to the model must treat a
    non-empty result here as "not verified", so absence-of-findings is never shown as "checks pass".
    """
    kinds = _kind_by_command(report)
    out: list[str] = []
    for r in report.results:
        if r.exit_code is None:
            k = kinds.get(r.command)
            label = f" ({k.name})" if k is not None else ""
            out.append(f"$ {r.command}{label} — {r.summary}")
    return out


# Kinds where a NON-ZERO exit unambiguously means "broken": a test failed, a type-check errored, a
# build/compile failed. Deliberately EXCLUDES Lint / FormatCheck / StaticAnalysis — those exit
# non-zero on ADVISORY-only findings (an unused import, a formatting diff), and parse_output has
# already stripped those advisories from r.findings, so "non-zero + no findings" there is expected and
# must NOT be surfaced as a failure (that would resurrect the unused-import footgun). SyntaxCheck is
# excluded too: completion_block_nudge already surfaces a red syntax floor.
_HARD_FAILURE_KINDS = (
    probediscovery.ProbeKind.Test,
    probediscovery.ProbeKind.Typecheck,
    probediscovery.ProbeKind.BuildCheck,
)


def failed_unparsed_probes(report: ProbeReport) -> list[str]:
    """Hard-failure probes (see :data:`_HARD_FAILURE_KINDS`) that RAN and exited NON-ZERO but produced
    NO parseable file:line finding — a real failure the parsers couldn't localize (a test that failed
    on a bare traceback, ``cargo check`` exit 101, ``tsc`` whose lines all read as advisory under
    noUnusedLocals). POSITIVE signal (the check ran and FAILED) — NOT clean, NOT couldn't-run — so it is
    surfaced coarsely (command + summary) rather than falling through to "no error-class findings". A
    normal parseable failure keeps its findings and is caught by completion_block_nudge instead."""
    kinds = _kind_by_command(report)
    out: list[str] = []
    for r in report.results:
        if is_no_tests_collected(r.exit_code, r.command, r.summary):
            continue  # pytest collected nothing — benign, not a failing test
        if r.exit_code not in (None, 0) and not r.findings \
                and kinds.get(r.command) in _HARD_FAILURE_KINDS:
            out.append(f"$ {r.command} — {r.summary or f'exited {r.exit_code}'}")
    return out


def gate_ran_tests(report: ProbeReport) -> bool:
    """True when a Test-kind probe in this report actually EXECUTED tests — ran and collected some, not
    exit-5/no-tests-collected. A GREEN gate that rests on zero tests collected (or no test probe at all)
    is a VACUOUS green: it verifies no behavior. Consumed non-model-facing as EVIDENCE for the
    satisfaction judge, which holds the task and decides whether tests were part of the ask in the first
    place (a testless script task is legitimately green; a 'unit tests required' task is not)."""
    if report is None:
        return False
    kinds = _kind_by_command(report)
    for r in report.results:
        if kinds.get(r.command) is probediscovery.ProbeKind.Test \
                and not r.timed_out \
                and not is_no_tests_collected(r.exit_code, r.command, r.summary):
            return True                # M3: a TIMED-OUT test probe did NOT execute a full run → not "ran tests"
    return False


def completion_block_nudge(report: ProbeReport, floor: LinterReport | None = None) -> Optional[str]:
    """Returns None when everything the probes could check is clean (so
    completion is allowed).

    Precedence: the tier-0 syntax floor first (it localizes parse errors to the
    exact line — the single most repairable signal). The floor now lives IN the
    candidate list (kind=SyntaxCheck, congruent across ecosystems); the legacy
    LinterReport parameter is honored when a caller still passes one. A probe
    that couldn't LAUNCH (tool absent = cria's own setup gap) never blocks — we
    only block on a real diagnosis — with TWO congruent exceptions: (a) a tier-0
    SyntaxCheck that RAN and exited non-zero is itself the diagnosis ("the code
    does not parse/compile"), even when its output defeated the parsers; and (b) a
    hard-failure-kind probe (Test/Typecheck/BuildCheck) that TIMED OUT — the command
    RAN and did NOT finish, so it did NOT verify; a timeout is an undecidable result,
    not an absent tool, so completion fails CLOSED on it (principle #13, M3).
    """
    if floor is not None and not floor.is_clean():
        # nudge_text() may itself be None per the LinterReport contract;
        # returned as-is, exactly like upstream.
        return floor.nudge_text()
    kinds = _kind_by_command(report)
    lines: list[str] = []
    syntax_lines: list[str] = []
    for r in report.results:
        is_syntax = kinds.get(r.command) is probediscovery.ProbeKind.SyntaxCheck
        if not r.findings:
            # A LAUNCH failure (absent tool) never blocks. EXCEPT: a syntax check that ran red, OR a
            # hard-failure-kind probe that TIMED OUT (ran and did not verify — M3) — both are real
            # not-clean signals with no file:line, so they block coarsely (command + summary).
            if is_syntax and r.exit_code not in (0, None):
                syntax_lines.append(f"$ {r.command} — {r.summary}")
            elif r.timed_out and kinds.get(r.command) in _HARD_FAILURE_KINDS:
                lines.append(f"$ {r.command} — {r.summary or 'timed out and did not verify'}")
            continue
        bucket = syntax_lines if is_syntax else lines
        bucket.append(f"$ {r.command} — {r.summary}")
        # EVERY finding, not a .take(5) slice: a probe with 12 real errors once showed only 5, so the
        # model fixed those, re-ran, and hit the 6th it never saw. The window-aware context floor is the
        # one place a truncation may happen — never a blind per-probe cap here.
        for f in r.findings:
            loc = f"{f.file}:{f.line}" if f.line is not None else f.file
            bullet = f"{loc}: {f.message}"
            if bullet == r.summary:
                continue  # the "$ cmd — summary" header already IS this finding — don't echo it twice
            bucket.append(f"  • {bullet}")
    combined = syntax_lines + lines  # floor first, exactly the old precedence
    if not combined:
        return None
    return BLOCK_NUDGE_PREAMBLE + "\n".join(combined)


def completion_probe_digest(report: ProbeReport, floor: LinterReport | None = None) -> str:
    """WHAT RAN and its raw outcome, for the critic.

    Upstream rationale (kept): unlike completion_block_nudge — which surfaces
    ONLY structured file:line findings and is silent otherwise — this reports
    what ran and how it exited. That exposes the cases the deterministic gate
    cannot act on and which look identical to "clean": a test suite that
    FAILED TO RUN (import error, nothing collected), TIMED OUT, or couldn't
    launch (runner not installed). The critic needs this to tell "tests pass"
    apart from "tests never ran".
    """
    lines: list[str] = []
    if floor is not None:
        floor_txt = DIGEST_FLOOR_CLEAN if floor.is_clean() else (floor.nudge_text() or DIGEST_FLOOR_FALLBACK)
    else:
        # The floor is in the candidates now (kind=SyntaxCheck) — derive its one-line state.
        kinds = _kind_by_command(report)
        syntax = [r for r in report.results
                  if kinds.get(r.command) is probediscovery.ProbeKind.SyntaxCheck]
        if not syntax:
            floor_txt = DIGEST_FLOOR_NONE
        elif all(r.exit_code == 0 for r in syntax):
            floor_txt = DIGEST_FLOOR_CLEAN
        else:
            floor_txt = DIGEST_FLOOR_FALLBACK
    lines.append(DIGEST_FLOOR_FMT.format(x=floor_txt))
    if not report.results:
        lines.append(DIGEST_NO_PROBES)
    else:
        for r in report.results:
            if r.exit_code == 0:
                exit_txt = DIGEST_EXIT_CLEAN
            elif is_no_tests_collected(r.exit_code, r.command, r.summary):
                exit_txt = DIGEST_EXIT_NO_TESTS  # exit 5 = nothing collected, NOT a failing test
            elif r.exit_code is not None:
                exit_txt = f"exit {r.exit_code}"
            else:
                exit_txt = DIGEST_EXIT_NO_LAUNCH
            lines.append(f"$ {r.command} — {exit_txt} — {r.summary} — "
                         f"{len(r.findings)} structured finding(s)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Proxy path: composed shell line out, tool result back in (both pure)
# ---------------------------------------------------------------------------

def display_command(command) -> str:
    """The command string SHOWN to the model as ``r.command`` (and used as the results→kinds map key,
    so every builder of it must agree). shlex.join, not a bare space-join: a probe argv can hold a
    multi-line ``python3 -c '<script>'`` blob or a path with spaces, and a space-join renders an
    UN-RUNNABLE command (the ``-c`` script unquoted, the file glued onto the end) that the model then
    copies verbatim. shlex.join quotes each token so the echoed command is the runnable one.
    ``shlex.join([]) == ""`` — the empty-argv contract is preserved."""
    return shlex.join(command)


def compose_probe_command(c: ProbeCandidate, timeout_s: float) -> str:
    """One shell line the harness executes in place of upstream's spawn.

    Every upstream host mechanic has a shell equivalent: current_dir -> ``cd
    <dir> &&``; the kill loop -> coreutils ``timeout -k 5`` (fractional seconds
    kept — ``timeout 0`` would DISABLE the timeout); Stdio::null ->
    ``</dev/null`` (probes must not block on interactive prompts); the drain
    threads -> the harness's own capture, with 2>&1 merging the streams the way
    parse_output already combines them; unbounded read_to_string -> a HEAD+TAIL
    budget of PROBE_OUTPUT_CAP_BYTES (half each end) so a failure printed EARLY
    survives a long teardown/summary tail — with a disclosed ``middle N bytes
    elided`` marker so nothing vanishes silently; exit-code retrieval -> the
    EXIT: sentinel. Small output (the common case) passes through untouched.
    Every argv token is shlex-quoted — mandatory correctness under joining,
    not sanitization (discovery already vetted the command).
    """
    if not c.command:
        raise ValueError(EMPTY_COMMAND_SUMMARY)
    argv = " ".join(shlex.quote(t) for t in c.command)
    half = PROBE_OUTPUT_CAP_BYTES // 2
    # One physical shell line (no literal newlines — ``\\n`` are printf escapes): capture, then if the
    # byte size is within budget print it whole, else print the first half + an elided-count marker +
    # the last half, so BOTH an early and a late failure land in the parseable capture.
    return (
        f"cd {shlex.quote(str(c.working_dir))} && "
        f"__cria_out=$(timeout -k {TIMEOUT_KILL_GRACE_S} {timeout_s:g} {argv} "
        f"</dev/null 2>&1); __cria_ec=$?; "
        f"__cria_n=$(printf '%s' \"$__cria_out\" | wc -c | tr -cd '0-9'); "
        f"if [ \"$__cria_n\" -le {PROBE_OUTPUT_CAP_BYTES} ]; then "
        f"printf '%s\\n' \"$__cria_out\"; "
        f"else printf '%s' \"$__cria_out\" | head -c {half}; "
        f"printf '\\n...[middle %d bytes elided; head+tail kept so an early failure survives]...\\n' "
        f"\"$((__cria_n - {PROBE_OUTPUT_CAP_BYTES}))\"; "
        f"printf '%s' \"$__cria_out\" | tail -c {half}; printf '\\n'; fi; "
        f"printf '{PROBE_EXIT_SENTINEL}%d\\n' \"$__cria_ec\""
    )


def scrape_exit(raw: str) -> tuple[str, Optional[int]]:
    """Recover the EXIT:<n> sentinel from a text-only capture.

    Scans bottom-up (probe output could itself mention "EXIT:"); returns the
    output with the sentinel line removed plus the parsed code, or
    ``(raw, None)`` when no sentinel survived (e.g. the ``cd`` failed and ``&&``
    short-circuited before anything ran).
    """
    lines = raw.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith(PROBE_EXIT_SENTINEL):
            try:
                code = int(stripped[len(PROBE_EXIT_SENTINEL):].strip())
            except ValueError:
                continue
            return "\n".join(lines[:i] + lines[i + 1:]), code
    return raw, None


def interpret_probe_output(c: ProbeCandidate, joined: str, raw_output: str,
                           exit_code: Optional[int], timeout_s: float) -> ProbeResult:
    """Map a harness shell-tool result onto the upstream ProbeResult contract.

    The composed command's exit codes REPLACE upstream's in-process signals:
    124 -> the timed_out branch (exit_code=None, TIMEOUT summary overwrite,
    findings salvaged from partial output KEPT); 127 or "command not found" in
    the output -> the spawn-failure branch (exit_code=None, "failed to
    launch"). Pass ``exit_code=None`` when the harness returned text only —
    the EXIT: sentinel is scraped instead. The merged capture goes to
    parse_output as ``stdout`` with an empty ``stderr``: parse_output combines
    the streams anyway, so parse behavior is identical to upstream's.
    """
    if not c.command:
        return err_result(joined, EMPTY_COMMAND_SUMMARY)
    output = raw_output
    if exit_code is None:
        output, exit_code = scrape_exit(raw_output)
    if exit_code == TIMEOUT_EXIT_CODE:
        result = parse_output(joined, family_of(c.command), None, output, "")
        # Same as_secs() truncation as run_candidate; findings kept.
        result.summary = TIMEOUT_SUMMARY_FMT.format(secs=int(timeout_s))
        result.timed_out = True   # ran and did NOT finish → the completion gate fails CLOSED (M3)
        return result
    # A launch failure by exit code (125/126/127); OR, only when NO sentinel survived (exit_code is
    # None), the text fallback. The `exit_code is None` guard matters: a probe that exited 0 whose
    # OUTPUT merely mentions "command not found" (a test asserting on an error string) must keep its
    # real exit 0 — not be flipped to a launch failure by a substring.
    if exit_code in LAUNCH_FAILURE_EXIT_CODES or (exit_code is None and NOT_FOUND_TEXT in output):
        return err_result(joined, LAUNCH_FAILURE_FMT.format(e=PROXY_LAUNCH_DETAIL))
    return parse_output(joined, family_of(c.command), exit_code, output, "")
