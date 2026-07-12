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

from . import probediscovery
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
# Findings shown per probe in the completion block nudge (.take(5)).
BLOCK_NUDGE_MAX_FINDINGS = 5

# Message/format strings — byte-for-byte with upstream. The Rust source writes
# the preamble with a `\` line continuation, which collapses to a single space:
# exactly one space between "exact" and "problems".
BLOCK_NUDGE_PREAMBLE = (
    "[GROUND TRUTH — the repo's own checks fail] You are not done yet. "
    "Fix these exact problems; go to the reported line, do not rewrite whole files:\n"
)
DIGEST_FLOOR_FMT = "SYNTAX FLOOR: {x}"
DIGEST_FLOOR_CLEAN = "clean (files parse)"
DIGEST_FLOOR_FALLBACK = "parse/syntax issues found"
DIGEST_NO_PROBES = "PROBES: none ran — no lint/test command was discovered for this project."
DIGEST_EXIT_CLEAN = "exit 0 (ran clean)"
DIGEST_EXIT_NO_LAUNCH = "did NOT launch (tool missing?)"

# ---------------------------------------------------------------------------
# cria constants (proxy path — NOT probe_run.rs values)
# ---------------------------------------------------------------------------

# Output cap applied at composition time. Upstream read_to_string'd the pipes
# unbounded and let probe_parse truncate per-line; in cria the capture lands in
# the model's context window, so the composed command caps it. tail (not head):
# the fatal line prints LAST for pytest/build tools.
PROBE_OUTPUT_CAP_BYTES = 16384
# Trailing sentinel that smuggles the probe's exit code through a text-only
# shell-tool result; scrape_exit() recovers it.
PROBE_EXIT_SENTINEL = "EXIT:"
# coreutils timeout(1) semantics standing in for upstream's kill loop.
TIMEOUT_KILL_GRACE_S = 5     # timeout -k 5: SIGKILL follow-up for SIGTERM-ignoring tools
TIMEOUT_EXIT_CODE = 124      # timeout(1) fired -> upstream's timed_out=true branch
NOT_EXECUTABLE_EXIT_CODE = 126  # shell: found but not executable (flows through as-is)
NOT_FOUND_EXIT_CODE = 127    # shell: command not found -> upstream's spawn-Err branch
NOT_FOUND_TEXT = "command not found"
PROXY_LAUNCH_DETAIL = "command not found"  # the {e} detail when the shell, not the OS, tells us


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
    joined = " ".join(c.command)
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
    return {" ".join(c.command): c.kind for c in report.selected}


def syntax_floor_clean(report: ProbeReport):
    """True/False for the tier-0 checks that RAN; None when none did (nothing to judge).
    The truth-capture event's floor_clean field."""
    kinds = _kind_by_command(report)
    syntax = [r for r in report.results
              if kinds.get(r.command) is probediscovery.ProbeKind.SyntaxCheck]
    if not syntax:
        return None
    return all(r.exit_code == 0 for r in syntax)


def completion_block_nudge(report: ProbeReport, floor: LinterReport | None = None) -> Optional[str]:
    """Returns None when everything the probes could check is clean (so
    completion is allowed).

    Precedence: the tier-0 syntax floor first (it localizes parse errors to the
    exact line — the single most repairable signal). The floor now lives IN the
    candidate list (kind=SyntaxCheck, congruent across ecosystems); the legacy
    LinterReport parameter is honored when a caller still passes one. A probe
    that couldn't launch (tool absent) or merely timed out never blocks — we
    only block on a real diagnosis — with ONE congruent exception: a tier-0
    SyntaxCheck that RAN and exited non-zero is itself the diagnosis ("the code
    does not parse/compile"), even when its output defeated the parsers.
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
            # launch-failures/timeouts never block — EXCEPT a syntax check that ran red.
            if is_syntax and r.exit_code not in (0, None):
                syntax_lines.append(f"$ {r.command} — {r.summary}")
            continue
        bucket = syntax_lines if is_syntax else lines
        bucket.append(f"$ {r.command} — {r.summary}")
        for f in r.findings[:BLOCK_NUDGE_MAX_FINDINGS]:
            loc = f"{f.file}:{f.line}" if f.line is not None else f.file
            bucket.append(f"  • {loc}: {f.message}")
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
            floor_txt = "did not run (no parse checks applicable)"
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

def compose_probe_command(c: ProbeCandidate, timeout_s: float) -> str:
    """One shell line the harness executes in place of upstream's spawn.

    Every upstream host mechanic has a shell equivalent: current_dir -> ``cd
    <dir> &&``; the kill loop -> coreutils ``timeout -k 5`` (fractional seconds
    kept — ``timeout 0`` would DISABLE the timeout); Stdio::null ->
    ``</dev/null`` (probes must not block on interactive prompts); the drain
    threads -> the harness's own capture, with 2>&1 merging the streams the way
    parse_output already combines them; unbounded read_to_string -> ``tail -c``
    at PROBE_OUTPUT_CAP_BYTES; exit-code retrieval -> the EXIT: sentinel.
    Every argv token is shlex-quoted — mandatory correctness under joining,
    not sanitization (discovery already vetted the command).
    """
    if not c.command:
        raise ValueError(EMPTY_COMMAND_SUMMARY)
    argv = " ".join(shlex.quote(t) for t in c.command)
    return (
        f"cd {shlex.quote(str(c.working_dir))} && "
        f"__cria_out=$(timeout -k {TIMEOUT_KILL_GRACE_S} {timeout_s:g} {argv} "
        f"</dev/null 2>&1); __cria_ec=$?; "
        f"printf '%s\\n' \"$__cria_out\" | tail -c {PROBE_OUTPUT_CAP_BYTES}; "
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
        return result
    if exit_code == NOT_FOUND_EXIT_CODE or NOT_FOUND_TEXT in output:
        return err_result(joined, LAUNCH_FAILURE_FMT.format(e=PROXY_LAUNCH_DETAIL))
    return parse_output(joined, family_of(c.command), exit_code, output, "")
