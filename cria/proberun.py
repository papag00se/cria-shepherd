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
error, and a trailing ``EXIT:<n>`` sentinel recovers the exit code when the
harness returns text only.  The gate transport spools the complete combined
result on the harness and pages it back over later requests; this function
therefore never selects or clips the checker's bytes.

Timeout interplay (proxy path): the harness's own shell-tool timeout must
exceed the probe timeout, or the harness kills the command before timeout(1)
fires and cria sees a harness-level failure instead of exit 124.
"""
from __future__ import annotations

import base64
import re
import os
import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from . import probediscovery, probeparse, prompts, toolpath, wsview
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
BLOCK_NUDGE_PREAMBLE = prompts.render(
    "block_nudge_preamble",
    seeded_test_rule=prompts.load("seeded_test_rule").strip()) + "\n"
_DIGEST = prompts.load_map("probe_digest")
DIGEST_FLOOR_FMT = _DIGEST["floor_fmt"]  # single-brace {x}, filled by .format()
DIGEST_FLOOR_CLEAN = _DIGEST["floor_clean"]
DIGEST_FLOOR_FALLBACK = _DIGEST["floor_fallback"]
DIGEST_FLOOR_NONE = _DIGEST["floor_none"]
DIGEST_NO_PROBES = _DIGEST["no_probes"]
DIGEST_EXIT_CLEAN = _DIGEST["exit_clean"]
DIGEST_EXIT_NO_LAUNCH = _DIGEST["exit_no_launch"]
DIGEST_EXIT_UNFINISHED = _DIGEST["exit_unfinished"]
# The stable head of probeparse.LAUNCH_FAILURE_FMT — the deterministic marker that a
# None exit_code means a REAL launch failure rather than a cut-short section.
LAUNCH_FAILURE_MARKER = "failed to launch"
DIGEST_EXIT_NO_TESTS = _DIGEST["exit_no_tests"]
DIGEST_MISSING_FMT = _DIGEST["missing_fmt"]

# The offline re-run's non-model-visible raw parse fallback. Its tally lines travel whole above it;
# this is not part of the completion gate's evidence transport.
OFFLINE_TAIL_BYTES = 600
# A RUNNER'S TALLY, BY SHAPE. `7 runs, 1 failures`, `12 passed, 1 failed`, `ok 3 - …`, `FAIL` — the
# counts every runner prints, wherever they sit in the output. Used only to make sure the tally
# survives a window; nothing is parsed here.
_TALLY_LINE_RE = r"[0-9]+ (runs|tests|passed|failed|failures|errors|examples)|^(ok|not ok|FAIL|PASS)\b"


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
    """True when RAW runner output says the runner collected NOTHING to run. Callers treat it as a
    neutral non-signal, never a failure.

    Two shapes: pytest's exit 5 plus a pytest fingerprint, and a runner that says so in words while
    exiting 0 — the second read by :func:`probeparse.says_nothing_ran`, which owns that question for
    every caller. Everything else is read from the parsed tally by :func:`_tally_says_zero`.

    THIS WANTS THE RUNNER'S OWN TEXT. A ProbeResult no longer carries it (a green run's ``summary``
    is the fixed string "no problems reported"), so a caller holding a result asks
    :func:`result_collected_nothing` instead."""
    if probeparse.says_nothing_ran(output):
        return True
    if exit_code != PYTEST_NO_TESTS_EXIT:
        return False
    hay = f"{command}\n{output}".lower()
    return "pytest" in hay or any(m in hay for m in _NO_TESTS_MARKERS)


def result_collected_nothing(result: "ProbeResult") -> bool:
    """The same question, asked of a PARSED result rather than raw output.

    The three callers below used to pass ``r.summary`` to :func:`is_no_tests_collected`, and on a
    green run that string is the constant "no problems reported" — so the go marker the function was
    written for was never once seen, and `gate_ran_tests` told the satisfaction judge that an empty
    Go package had executed tests. Same trap, and same fix, as the one already applied to ``tally``
    and ``skipped``: the fact is taken at parse time and carried on the result.

    A PARSED COUNT OUTRANKS A SENTENCE. A suite that really ran can print anything, these words
    included, so the prose is consulted only when no runner tally was read."""
    if (getattr(result, "tally", "") or "").strip():
        return _tally_says_zero(result)
    if getattr(result, "no_tests", False):
        return True
    return is_no_tests_collected(result.exit_code, result.command, result.summary)


@dataclass
class ProbeReport:
    """What ran and what came back; a truncated gate may omit results, so consumers join by command."""
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
    return [c for c in selected if program_is_installed(c)]


def _head_program(command) -> str:
    """The program a candidate would actually execute — the first token, ignoring env assignments."""
    toks = list(command) if isinstance(command, (list, tuple)) else str(command or "").split()
    for tok in toks:
        tok = str(tok)
        if "=" in tok and not tok.startswith(("-", "/", ".")) and tok.split("=", 1)[0].isidentifier():
            continue        # FOO=bar prefix, not the program
        return tok
    return ""


def program_is_installed(candidate) -> bool:
    """False only when cria is SURE the candidate's program is absent from this machine.

    cria composed `bundle exec rubocop` and `bundle exec rspec` for every ruby workspace on a box
    with no bundler installed — two of five ruby probes that could never launch, every gate, burning
    a slot and a timeout each. A launch failure already abstains rather than misreporting, so this
    costs nothing in correctness; it costs the gate its budget and the operator a confusing
    "could not run" on a check that was never available. cria knows the answer for free (#5b, #10).

    UNSURE MEANS KEEP. A tool inside the project (`./gradlew`, `node_modules/.bin/jest`) is checked
    as a file rather than on PATH, and anything this cannot resolve is kept — dropping a real probe
    is far worse than running one that abstains, so the check only ever removes a certainty.

    AND THE CERTAINTY MUST BE ABOUT THE MACHINE, NOT ABOUT CRIA. This asked `shutil.which`, which
    answers for cria's own process — a service with a bare systemd PATH. Every toolchain under the
    user's home read as absent, so on this box cargo, rustc, node, npm, npx, pytest and pyflakes were
    all "not installed" while the coder ran them freely. Two Rust cells ran no Rust tool at any gate
    and the empty result was published as "no error-class problems" over a project that did not
    compile. The question is what the coder's shell can launch, so ``toolpath`` is what gets asked
    (#5b). The original bundler case still drops: `bundle` is absent from both paths."""
    prog = _head_program(getattr(candidate, "command", candidate))
    if not prog:
        return True
    if "/" in prog or prog.startswith("."):
        # A tool inside the PROJECT (`./gradlew`, `node_modules/.bin/jest`) is a workspace file, so
        # it is a question about the harness's disk like every other one here. Unknown keeps the
        # probe, which is this function's documented safe direction.
        base = os.path.join(getattr(candidate, "working_dir", "") or "", prog)
        view = wsview.current()
        return view.isfile(base) is not False or view.isfile(prog) is not False
    # UNSURE MEANS KEEP, and unsure is now a state cria can actually be in: `resolved` answers None
    # until the harness has been asked about this program, and a probe dropped on an unanswered
    # question is a check that silently never ran.
    return toolpath.resolved(prog) != ""


# ---------------------------------------------------------------------------
# Execution via the injectable Runner seam
# ---------------------------------------------------------------------------

def source_line_reader(cwd: str):
    """A ``(path, line_no) -> str | None`` reader rooted at the probe's working dir — the file
    access probeparse's F811 discriminator needs (a def/class redefinition is a real shadow, an
    import rebinding is cleanliness; see probeparse._ADVISORY_PHRASES). Missing file / bad line →
    None, which keeps the pure advisory default."""
    import os
    from pathlib import Path

    def read(path: str, line_no: int) -> Optional[str]:
        p = str(Path(path) if os.path.isabs(path) else Path(cwd) / path)
        body = wsview.current().read(p)
        if body is None:
            return None
        try:
            return body.splitlines()[line_no - 1]
        except IndexError:
            return None
    return read


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
    result = parse_output(joined, family_of(c.command), exit_code, stdout, stderr,
                          read_source_line=source_line_reader(str(c.working_dir)))
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
        if result_collected_nothing(r):
            continue  # the runner collected nothing — benign, not a failing test
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
                and not result_collected_nothing(r):
            return True                # M3: a TIMED-OUT test probe did NOT execute a full run → not "ran tests"
    return False


def _tally_says_zero(result: "ProbeResult") -> bool:
    """True only when cria PARSED a runner tally and it counted no tests at all.

    `is_no_tests_collected` above is pytest's convention — exit code 5 plus a pytest fingerprint —
    and every other runner in the fleet exits 0 on an empty suite. Measured on this machine:
    `go test` with no test files exits 0, and so does minitest with `0 runs`. So a vacuous green
    answered `gate_ran_tests` -> True in five of six languages, and cria told the satisfaction judge
    tests had executed when none had (#5b to a judge, #20 keyed to one runner's convention).

    The tally is the kernel-level reading of the same question wherever a count is printed:
    `0f/0p` from minitest, cargo, rspec, jest, exunit, mocha and node. It does NOT cover the four
    that print prose and no count at all on an empty suite — maven-surefire, phpunit, gradle and
    dotnet all yield tally "" — and this docstring used to claim it did. Those are read by
    :func:`probeparse.says_nothing_ran` from the runner's own words instead.

    POSITIVE KNOWLEDGE ONLY. No tally parsed means cria could not read the runner, not that nothing
    ran — plain `go test` prints one verdict per package and deliberately produces no tally — so an
    unreadable result keeps the previous answer rather than converting cria's blindness into "no
    tests" (#11b). This can only move a result from "ran" to "did not run" on evidence, never the
    other way, which is the additive direction (#2)."""
    tally = (getattr(result, "tally", "") or "").strip()
    if not tally:
        return False
    return all(int(n) == 0 for n in re.findall(r"(\d+)[fp]", tally)) and bool(re.search(r"\d", tally))



def gate_skipped_count(report: ProbeReport) -> int:
    """Tool-reported SKIPPED-test count across the report's Test-kind probes — a deterministic fact
    for the satisfaction judge. Measured need (run 0728-m11): the coder's live tests skipTest() on
    the exact 404 that proves the resolver broken; "3 passed, 2 skipped" read as green and the run
    ended done with a resolver that 404s. Parsed from the runner's own summary line ("N skipped" —
    pytest/jest/vitest all emit it), never from prose; runners without that phrase report 0 (the
    same Python-first bound as the test floor, and an under-count only ever means silence).

    READ FROM `ProbeResult.skipped`, taken at parse time. This used to re-scan ``r.summary``, which on
    a GREEN run — the only kind this is asked about — is the fixed string "no problems reported". It
    therefore returned 0 for every run cria has ever made, and the judge was told no tests skipped
    whatever the runner said."""
    if report is None:
        return 0
    kinds = _kind_by_command(report)
    total = 0
    for r in report.results:
        if kinds.get(r.command) is probediscovery.ProbeKind.Test and not r.timed_out:
            total += r.skipped
    return total


def block_findings(report: ProbeReport, floor: LinterReport | None = None) -> Optional[str]:
    """The checker's OWN failing lines, with NO preamble — or None when everything that could be
    checked is clean. This is the body of :func:`completion_block_nudge`, split out because it has a
    SECOND reader that must not receive the coder-facing preamble: the step critic, which is now
    handed a red gate as evidence and asked whose failure it is (loop._verify_after_probe).
    ``block_nudge_preamble`` is an imperative addressed to the coder ("resolve exactly what it
    names"), and an imperative reads as a task briefing to a weak judge — the measured fence problem
    in principle 8, where a judge handed a work-shaped prompt did the work instead of ruling on it.
    One renderer, two framings; the findings themselves are byte-identical for both readers.
    """
    if floor is not None and not floor.is_clean():
        # nudge_text() may itself be None per the LinterReport contract; returned as-is, exactly like
        # upstream — it carries the FLOOR's own digest header (floor_digest.nudge_preamble), never
        # BLOCK_NUDGE_PREAMBLE, so there is nothing to strip and completion_block_nudge must not add one.
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
    return "\n".join(combined)


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
        return floor.nudge_text()   # the legacy floor already carries its own preamble — untouched
    body = block_findings(report)
    if body is None:
        return None
    # THE ROOT, OR THE NOTE IS THE OLD FALSE ONE. `dependency_note` picks the "not installed
    # anywhere" wording only when `install_landed` returns a definite False, and that needs a
    # workspace to look at. This call passed none, so the default `""` made `install_landed`
    # return None on every gate, the `<eco>_none` branch was unreachable, and the coder kept
    # getting the sentence the branch exists to replace: "a gem installed with --install-dir is
    # not on the load path by default". Walked twice before the branch was written and once after
    # (#11b — a mechanism that cannot observe the thing it is asked about must not answer as if it
    # had). The sibling caller in writeproxy passed the root all along; this one was missed, and
    # the test for the branch called `dependency_line` directly, so it stepped over the gap.
    return BLOCK_NUDGE_PREAMBLE + body + dependency_note(report, report_root(report))


def report_root(report: "ProbeReport") -> str:
    """The workspace the probes in ``report`` ran in — "" when the report cannot say.

    NOT A PARAMETER, ON PURPOSE. `dependency_note` needs a root to ask the disk whether an install
    actually landed, and it used to take one: `writeproxy` passed it, the gate path did not, so
    `install_landed` returned None on every gate, the "not installed anywhere" branch was
    unreachable, and the coder kept getting the sentence that branch exists to replace. A value two
    callers must remember to pass is a value one caller will forget — and the test for the branch
    called `dependency_line` directly, so it stepped over the gap rather than catching it.

    cria was holding the fact the whole time: it composed every probe in this report and set
    `working_dir` on each one. Reading it from the report makes the note's reach a property of the
    report instead of a promise about call sites (#23, one owner).

    First probe wins; they share a workspace by construction, and a report with no probes has no
    workspace to name."""
    for c in getattr(report, "selected", None) or []:
        d = str(getattr(c, "working_dir", "") or "")
        if d:
            return d
    return ""


def dependency_line(eco: str, workspace_root: str) -> str:
    """The load-path line, or the not-installed-at-all line when cria can see that is the truth.

    The `<eco>_none` wording is used ONLY when `install_landed` returns a definite False — an
    ecosystem cria cannot settle, or a workspace it cannot read, keeps the original sentence (#3).
    See probeparse.install_landed for the two cells the wrong one cost."""
    words = prompts.load_map("dependency_note")
    if probeparse.install_landed(eco, workspace_root) is False and f"{eco}_none" in words:
        return words[f"{eco}_none"]
    # …and when something DID land, say which mechanism put it there rather than assuming one. The
    # general line names `--install-dir`, and appending that to a bundler project sent a coder after
    # GEM_HOME and broke its Rakefile — see probeparse.install_flavour.
    flavour = probeparse.install_flavour(eco, workspace_root)
    if flavour and f"{eco}_{flavour}" in words:
        return words[f"{eco}_{flavour}"]
    return words[eco]


def dependency_note(report: "ProbeReport", workspace_root: str = "") -> str:
    """One line naming a MISSING DEPENDENCY when a check's own output says that is what failed.

    A weak model cannot tell "the library you declared is not loadable" from "your code is wrong",
    and the cost of confusing them is the rest of the run rather than a wasted call. Measured on the
    six-language battery: 8 checks failed with the dependency declared correctly and simply not
    reachable, and gemma4's ruby run turned 3-of-5 passing into 1-of-5 doing it — two gems installed,
    `require` failing, twenty minutes spent on the package manager.

    Every ecosystem states this in its own words, so the classification reads the tool's error class
    (#12) rather than guessing at prose, and only where the message can mean nothing else. The
    checker's line is untouched and still shown above; this is one labelled sentence beside it, the
    same shape as the disk-truth and gate-state lines already appended to the briefing — cria may
    SELECT a checker's real lines and add its own fact beside them, never substitute.

    Silent unless a probe actually failed that way, and silent when the name turns out to be the
    project's own file (a false "your own module is a missing dependency" is the expensive direction,
    so an unresolvable name is left alone)."""
    # ProbeResult keeps no raw output — what survives is the summary and the parsed findings, which
    # is where the tool's own error line ends up either way (summarize() falls back to the last
    # error-ish line when nothing parsed, and a LoadError / "Cannot find module" is exactly that).
    for res in (report.results if report is not None else []) or []:
        text = "\n".join([getattr(res, "summary", "") or ""]
                         + [f.message for f in (getattr(res, "findings", None) or [])])
        hit = probeparse.dependency_missing(text)
        if not hit:
            continue
        eco, name = hit
        if workspace_root and probeparse.names_a_workspace_file(name, workspace_root):
            # …AND WHEN cria CAN NAME THE FILE, SILENCE IS THE WRONG ANSWER. "Say nothing rather than
            # call the project's own module a missing dependency" is right where cria is guessing. It
            # is not guessing here: it walked the tree and found the file. That file is a SHADOW — the
            # name the coder typed resolves to its own file instead of the library — which is the one
            # dependency failure neither the error nor the package manager ever mentions.
            own = probeparse.resolves_to_workspace_file(name, workspace_root)
            if own:
                return "\n" + prompts.fill(prompts.load_map("dependency_note")["shadowed"],
                                            name=name, path=own)
            return ""
        return "\n" + prompts.fill(dependency_line(eco, workspace_root), name=name)
    return ""


def completion_probe_digest(report: ProbeReport, floor: LinterReport | None = None,
                            missing: list | None = None) -> str:
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
    if missing:
        # Checks that were SELECTED but whose section never came back (a cut-short gate script). Their
        # absence used to be invisible — `results` quietly became a subset of `selected` — so a
        # truncated gate read exactly like a passing one to the critic.
        lines.append(DIGEST_MISSING_FMT.format(x="; ".join(missing)))
    if not report.results:
        lines.append(DIGEST_NO_PROBES)
    else:
        for r in report.results:
            if r.exit_code == 0:
                exit_txt = DIGEST_EXIT_CLEAN
            elif result_collected_nothing(r):
                exit_txt = DIGEST_EXIT_NO_TESTS  # nothing collected, NOT a failing test
            elif r.exit_code is not None:
                exit_txt = f"exit {r.exit_code}"
            elif LAUNCH_FAILURE_MARKER in (r.summary or ""):
                # A REAL launch failure (EXIT:125/126/127 or shell "command not found" — normalized
                # to exit_code=None upstream, but its summary carries the launch-failure text).
                exit_txt = DIGEST_EXIT_NO_LAUNCH
            else:
                # No sentinel AND no launch-failure evidence: the harness returned before the check
                # finished (its yield window / output cap cut the stream — a missing tool would still
                # print EXIT:127). Observed live: a 10s exec yield cut the gate mid-pytest and this
                # read "did NOT launch (tool missing?)" — a false fact handed to the critic.
                exit_txt = DIGEST_EXIT_UNFINISHED
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
    """The uncut probe invocation the harness writes into the gate spool.

    The harness still supplies the execution mechanics: working directory, a hard
    timeout, closed stdin, merged stdout/stderr, and the exit sentinel consumed by
    :func:`scrape_exit`. Output is not held in a shell variable, filtered, or
    clipped. :mod:`cria.probegate` redirects the complete combined gate stream to
    a harness-side temporary file and transports it back losslessly over as many
    request/response turns as are required.
    """
    if not c.command:
        raise ValueError(EMPTY_COMMAND_SUMMARY)
    argv = " ".join(shlex.quote(t) for t in c.command)
    return (
        f"cd {shlex.quote(str(c.working_dir))} && "
        f"{compose_probe_cmd_echo(c.command)}; "
        f"timeout -k {TIMEOUT_KILL_GRACE_S} {timeout_s:g} {argv} </dev/null 2>&1; "
        f"__cria_ec=$?; printf '\\n{PROBE_EXIT_SENTINEL}%d\\n' \"$__cria_ec\""
    )
# The network block for the OFFLINE re-run: an empty KERNEL network namespace, not a language shim.
#
# `unshare -rn` puts the test process in a namespace with no route to anywhere, so the block lands at
# the syscall for EVERY runtime — measured against a static Go binary, which issues syscalls directly
# and therefore walks straight through LD_PRELOAD, sitecustomize, and every other interpreter-level
# patch. The earlier CPython-only sitecustomize was replaced by it: strictly weaker (blind to a test
# that shells out to curl, to a C extension, to connect_ex, to UDP) and strictly narrower (silent on
# `go test` and `cargo test`, which are 3 of the suite's 5 task families).
#
# Loopback is brought back UP inside the namespace. A test that stands up its own mock server on
# 127.0.0.1 must still pass offline — that is precisely the shape this check exists to SEE. Only the
# outside world is gone. (The sitecustomize version raised on loopback too, a latent false-red.)
# THE SECOND EXECUTION MAY NOT TOUCH THE WORKSPACE. The leg re-runs the coder's own suite in the
# coder's own directory, and a suite with side effects then has them twice: measured on
# `orders-api-py x nemotron-elastic`, the model's tests append to one repo-relative `orders.db` that
# nothing deletes, and the next gate read `assert 22.5 < 0.01` where 30.0 is FOUR rows of 3 x 2.50 —
# one from the coder's run and three from cria's. The coder never saw the other three and spent the
# tail of the run theorising about pytest parallelism. `sweep_litter` cannot help: it removes files
# the probes CREATED, and this is a file that already existed being written to again.
#
# ATTEMPTED AND ABANDONED (do not re-try): running the leg against a COPY of the workspace. It
# produced 7.0 GB of copied trees, because `cp -a` is not cheap and `working_dir` is not always the
# workspace — one leaked mirror held 14,262 directories of `/tmp`.
#
# ALSO REJECTED: running the offline leg FIRST and skipping the online one when it passes. That
# sounds like a removal and is a FALSE-GREEN generator — this module's own `_offline_fact` records
# the hole: a live test can SKIP rather than fail when the service is gone, so an offline pass does
# not imply an online pass, and the authoritative run has to be the unblocked one.
#
# What is bounded instead is what the second run CAN DO. The namespace already exists; adding a
# mount namespace and re-binding the working directory onto itself read-only costs one syscall pair
# and makes the whole class impossible. Reads are untouched, /tmp is untouched, and a suite that
# genuinely writes inside its own tree now FAILS offline — which `_offline_fact` reads as "say
# nothing" (it speaks only when both sides are green). Silence, never a manufactured red.
#
# MEASURED against the four real seeds that have a runnable suite (orders-api-py, feed-pipeline-py,
# cart-billing-go, shipping-rates-rb): every one returns the SAME exit code read-only as writable.
#
# The capability probe performs the very same bind, so a kernel or sandbox that refuses it skips the
# leg entirely and prints nothing. There is no writable fallback: an instrument cria cannot set up
# is an instrument it does not read (#4, #11b).
def _netns_readonly(working_dir) -> str:
    ws = shlex.quote(str(working_dir))
    return f"mount --bind {ws} {ws} && mount -o remount,bind,ro {ws}"


def _netns_capable(working_dir) -> str:
    return f"unshare -rnm -- sh -c {shlex.quote(_netns_readonly(working_dir))}"


_NETNS_ENTER = "unshare -rnm -- sh -c"
_NETNS_LOOPBACK_UP = "ip link set lo up 2>/dev/null; exec "

# The shell variable the composed script parks the TEST probe's exit code in, so the offline leg can
# ask whether the online run passed. ONE owner: `probegate` writes it, `offline_probe_command` reads
# it, and `probegate._strip_gate_plumbing` drops every line that mentions it — three places that
# must agree, and did not while it was a bare literal in each (#23).
TEST_EC_VAR = "__cria_test_ec"


def offline_probe_command(c: "ProbeCandidate", timeout_s: float) -> str:
    """The same test command, re-run with the network blocked — or "" when cria cannot block it.

    A test suite that mocks the thing it is testing passes whether or not the network exists, and
    that is the shape behind the false greens: mellum2 1786047222 shipped five tests that patch
    `requests.get` and assert the fixture the test itself supplied ("addr1x456..."), the gate said
    "no error-class problems", and cria's satisfaction judge — which had read all three files and
    could not run anything — passed a run verify scores 2/4.

    Running the suite twice settles it deterministically. This is the same discriminator verify.py
    already uses ("passed with network, fails without — provably live"). It produces a FACT for the
    judge, never a verdict: an offline pass is not a defect on its own, because plenty of tasks have
    no network in them. Whether it matters for THIS task is the judge's call (principle 8).

    LANGUAGE-AGNOSTIC — the block is a kernel namespace (see _netns_capable), so any Test probe
    qualifies. Where the kernel refuses the namespace (no unprivileged user namespaces, no unshare,
    no bind mount) the whole leg is skipped and prints NOTHING: an absent section is silence, and
    silence is the only honest output for a block cria did not actually establish.

    THE WORKSPACE IS READ-ONLY INSIDE IT — see the note above _netns_readonly. cria's extra
    execution of the coder's suite cannot write into the coder's tree, so it cannot manufacture the
    failure the next check reports."""
    if c.kind is not probediscovery.ProbeKind.Test or not c.command:
        return ""
    argv = " ".join(shlex.quote(t) for t in c.command)
    # RE-ENTER THE DIRECTORY AFTER THE BIND, and this is not decoration. The outer script has
    # already `cd`-ed here, and a process's cwd is a resolved dentry: mounting over the path does
    # not move it, so the suite kept writing THROUGH the old cwd to the underlying directory and the
    # read-only mount changed nothing. Caught by the fixture that appends to a repo-relative file.
    inner = (f"{_netns_readonly(c.working_dir)} || exit 98; "
             f"cd {shlex.quote(str(c.working_dir))} || exit 98; " + _NETNS_LOOPBACK_UP + argv)
    return (
        f"cd {shlex.quote(str(c.working_dir))} && "
        # ONLY WHEN THE ONLINE RUN PASSED. The leg's single product is the COMPARISON — "these same
        # tests also pass with the network gone". After a red online run there is nothing to compare:
        # both runs fail, the sentence cannot be written, and all that is left is a second execution
        # of the suite in the live workspace with its side effects.
        #
        # Measured, gemma4/python 0061-0077. The coder's own run: "8 passed in 2.08s", exit 0. The
        # next gate reported a higher row count, because the tests had been run twice against the
        # same database. The coder's theory: "The test `test_get_customer_orders` might be running
        # multiple times in a loop within pytest (e.g., `pytest -n auto` for parallel execution)."
        # It spent the rest of the run chasing a duplication cria had created. ~25 coder calls.
        #
        # A removal, and it uses a fact the script already holds (probegate saves the test probe's
        # exit code into __cria_test_ec). Unset means the test probe never ran, which is also a
        # reason not to run it twice.
        f'if [ "${{__cria_test_ec:-1}}" -eq 0 ] && {_netns_capable(c.working_dir)} >/dev/null 2>&1; then '
        f"__cria_out=$(timeout -k {TIMEOUT_KILL_GRACE_S} {timeout_s:g} "
        f"{_NETNS_ENTER} {shlex.quote(inner)} </dev/null 2>&1); __cria_ec=$?; "
        # THE TALLY LINE BY ITS SHAPE, NOT BY BEING LAST. This was a bare `tail -c 600` — no marker,
        # no named constant, and it is ALL the offline evidence there is: the section is skipped for
        # findings entirely, so 600 bytes is the whole basis of the sentence cria then tells the
        # model about whether the tests passed with the network gone. A runner that prints its tally
        # and then anything else (a coverage table, a teardown, a warnings summary) lost the tally,
        # and `_offline_fact` fell silently to its weaker wording or returned "" (#12).
        # THE TALLY LINES GO WHOLE. They are what `_offline_fact` parses, and they are the entire
        # basis of a sentence 3,218 model-facing prompts have carried — "the same tests pass with
        # the network switched off … nothing in them reaches a service on the internet". `grep`
        # already bounds this leg to lines that look like a runner's summary; putting a byte tail
        # after it could only ever remove one of the few lines that matter, which is the failure the
        # comment above records. Nothing here is shown to a model, so this is not rule 5 — it is 5b:
        # a claim cria states as fact must not rest on bytes cria threw away.
        f"printf '%s' \"$__cria_out\" | grep -E {shlex.quote(_TALLY_LINE_RE)}; "
        # The raw tail behind it is a PARSE fallback for a runner whose summary the pattern missed,
        # never something a model reads. It stays bounded.
        f"printf '%s' \"$__cria_out\" | tail -c {OFFLINE_TAIL_BYTES}; "
        f"printf '\\n{PROBE_EXIT_SENTINEL}%d\\n' \"$__cria_ec\"; "
        f"fi"
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


# A section's OWN raw bytes are the only fact that survives a gate becoming an OLDER, superseded
# transport: `clean_gate_results` rebuilds every earlier gate as a bare plan with no candidates
# attached (loop.py's `sess.gate_plan` is replaced by the newest gate every turn), so a NAME for a
# timed-out or cut-short section that lives only on `plan.candidates[idx]` is gone the moment a
# newer gate exists (C39 re-review: an older empty pytest timeout lost its command name once
# superseded). Self-describing the section instead \u2014 one line, printed BEFORE the probe itself
# runs, so it is baked into the transport's own immutable bytes \u2014 needs no plan, no session state,
# and survives supersession for free. Base64, not the plain command: a cria-composed probe's argv can
# itself be a multi-line inline program (the TOML/JSON/XML parse floors), and a literal embedded
# newline would break the "first line only" contract below.
PROBE_CMD_MARKER = "___CRIA_PROBE_CMD___"


def compose_probe_cmd_echo(command: list[str]) -> str:
    """The shell fragment that self-describes a probe's own section, emitted once before the probe
    itself runs (see :func:`compose_probe_command`). ``peel_probe_cmd_echo`` is the exact inverse."""
    label = display_command(command)
    b64 = base64.b64encode(label.encode("utf-8")).decode("ascii")
    return f"printf '{PROBE_CMD_MARKER}%s\\n' {b64}"


def peel_probe_cmd_echo(text: str) -> tuple[str, str]:
    """(label, text with the echo line removed). ``label`` is ``""`` when no echo line is present \u2014
    an older transport captured before this existed, or a section with no output at all \u2014 which
    callers treat exactly like today's "cria can't say which command this was" case."""
    lines = text.splitlines()
    if lines and lines[0].startswith(PROBE_CMD_MARKER):
        try:
            label = base64.b64decode(lines[0][len(PROBE_CMD_MARKER):]).decode("utf-8", "replace")
        except (ValueError, UnicodeDecodeError):
            label = ""
        return label, "\n".join(lines[1:])
    return "", text


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
    read_line = source_line_reader(str(c.working_dir))
    if exit_code == TIMEOUT_EXIT_CODE:
        result = parse_output(joined, family_of(c.command), None, output, "",
                              read_source_line=read_line)
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
    return parse_output(joined, family_of(c.command), exit_code, output, "",
                        read_source_line=read_line)
