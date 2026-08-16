"""Probe orchestration: selection, the per-probe result contract, and the two
model-facing renderings (block nudge + digest).

The seven upstream Rust tests (probe_run.rs) port verbatim; the rest pin the
cria-specific surface — the pure selection helpers and the proxy path
(compose_probe_command / scrape_exit / interpret_probe_output). LocalRunner and
the bash roundtrip — the only things here that spawn a process — live in THIS
file only: cria's own modules never execute anything.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from cria.linterprobe import LinterFinding, LinterReport
from cria.probeparse import Finding, ProbeResult
from cria.proberun import (
    BLOCK_NUDGE_PREAMBLE,
    PROBE_EXIT_SENTINEL,
    PROBE_OUTPUT_CAP_BYTES,
    ProbeReport,
    completion_block_nudge,
    completion_probe_digest,
    compose_probe_command,
    failed_unparsed_probes,
    family_of,
    interpret_probe_output,
    run_candidate,
    run_probes_with,
    scrape_exit,
    select_completion_probes,
    unran_probes,
)

from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind


def synth(cmd, kind=ProbeKind.BuildCheck):
    """The upstream test fixture: a cheap, safe, synthetic BuildCheck candidate."""
    return ProbeCandidate(
        kind=kind,
        command=list(cmd),
        working_dir=tempfile.gettempdir(),
        confidence=90,
        expected_value=80,
        cost=ProbeCost.Cheap,
        mutates_code=False,
        may_hang=False,
        may_need_services=False,
        reason="test",
    )


# ---------------------------------------------------------------------------
# LocalRunner: subprocess-based, defined HERE only (cria owns no executors).
# ---------------------------------------------------------------------------

def _text(v):
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


class LocalRunner:
    """Reference Runner for tests: subprocess.run with drain + kill-on-timeout."""

    def __call__(self, argv, cwd, timeout_s):
        try:
            proc = subprocess.run(
                list(argv), cwd=cwd, capture_output=True, text=True,
                timeout=timeout_s, stdin=subprocess.DEVNULL)
            return proc.returncode, proc.stdout, proc.stderr, False
        except subprocess.TimeoutExpired as e:
            return None, _text(e.stdout), _text(e.stderr), True


class _FakeFloor:
    """Duck-typed LinterReport for branches a real report cannot reach
    (is_clean() False with nudge_text() None)."""

    def __init__(self, clean, nudge):
        self._clean = clean
        self._nudge = nudge

    def is_clean(self):
        return self._clean

    def nudge_text(self):
        return self._nudge


# ---------------------------------------------------------------------------
# The seven upstream tests, verbatim.
# ---------------------------------------------------------------------------

class TestUpstreamProbeRun(unittest.TestCase):
    def test_runs_and_captures_exit_zero(self):
        r = run_candidate(LocalRunner(), synth(["python3", "-c", "print('ok')"]), 10.0)
        self.assertEqual(r.exit_code, 0)
        self.assertEqual(r.summary, "no problems reported")

    def test_captures_stderr_and_nonzero_exit(self):
        code = "import sys; sys.stderr.write('src/x.py:9: error: boom\\n'); sys.exit(1)"
        r = run_candidate(LocalRunner(), synth(["python3", "-c", code]), 10.0)
        self.assertEqual(r.exit_code, 1)
        self.assertEqual(len(r.findings), 1)
        self.assertEqual(r.findings[0].file, "src/x.py")
        self.assertEqual(r.findings[0].line, 9)

    def test_enforces_timeout(self):
        r = run_candidate(LocalRunner(),
                          synth(["python3", "-c", "import time; time.sleep(30)"]), 0.4)
        self.assertTrue(r.summary.startswith("TIMEOUT"))
        # upstream quirk, preserved: as_secs() truncation — 0.4s reads "after 0s"
        self.assertTrue(r.summary.startswith("TIMEOUT after 0s"))
        self.assertIsNone(r.exit_code)

    def test_missing_tool_is_reported_not_panicked(self):
        r = run_candidate(LocalRunner(),
                          synth(["definitely-not-a-real-binary-xyz", "check"]), 5.0)
        self.assertIsNone(r.exit_code)
        self.assertIn("failed to launch", r.summary)

    def test_family_selection(self):
        self.assertEqual(family_of(["cargo", "check"]), "cargo")
        # token match anywhere in argv, not just argv[0]
        self.assertEqual(family_of(["pnpm", "exec", "tsc", "--noEmit"]), "tsc")
        self.assertEqual(family_of(["ruff", "check", "."]), "")

    def test_end_to_end_on_a_python_repo(self):
        # upstream name is stale — the fixture is a go repo; kept verbatim.
        d = os.path.join(tempfile.gettempdir(), f"probe_run_e2e_{os.getpid()}")
        if os.path.exists(d):
            shutil.rmtree(d)
        os.makedirs(d)
        try:
            with open(os.path.join(d, "go.mod"), "w", encoding="utf-8") as fh:
                fh.write("module x\n")
            report = run_probes_with(LocalRunner(), d, 1, 10.0)
            self.assertEqual(report.project_type, ["go"])
            self.assertEqual(len(report.selected), 1)
            self.assertEqual(len(report.results), 1)
            # go may or may not be installed; we only assert the orchestration shape
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_digest_distinguishes_ran_clean_from_did_not_run(self):
        clean_floor = LinterReport(findings=[], skipped=[])
        report = ProbeReport(
            project_type=["python"],
            selected=[],
            results=[
                ProbeResult("pytest -q", 0, "3 passed", []),
                ProbeResult("python -c import", 1,
                            "ModuleNotFoundError: No module named 'requests'", []),
            ],
        )
        digest = completion_probe_digest(report, clean_floor)
        self.assertIn("SYNTAX FLOOR: clean", digest)
        self.assertIn("exit 0 (ran clean)", digest)
        self.assertIn("ModuleNotFoundError", digest)
        self.assertIn("exit 1", digest)
        digest = completion_probe_digest(ProbeReport([], [], []), clean_floor)
        self.assertIn("none ran", digest)


# ---------------------------------------------------------------------------
# Completion selection (pure; discovery mocked at the module seam).
# ---------------------------------------------------------------------------

class TestCompletionSelection(unittest.TestCase):
    def test_top_plus_first_test_deduped_by_argv(self):
        lint = synth(["ruff", "check", "."], kind=ProbeKind.Lint)
        test1 = synth(["pytest", "-q"], kind=ProbeKind.Test)
        test2 = synth(["python3", "-m", "unittest"], kind=ProbeKind.Test)
        with mock.patch("cria.probediscovery.discover",
                        return_value=[lint, test1, test2]):
            selected = select_completion_probes("/nonexistent")
        # overall top + FIRST Test in rank order (test2 never selected)
        self.assertEqual([c.command for c in selected],
                         [["ruff", "check", "."], ["pytest", "-q"]])

    def test_top_candidate_is_the_test_runs_once(self):
        test1 = synth(["pytest", "-q"], kind=ProbeKind.Test)
        with mock.patch("cria.probediscovery.discover", return_value=[test1]):
            selected = select_completion_probes("/nonexistent")
        self.assertEqual(len(selected), 1)

    def test_no_candidates_selects_nothing(self):
        with mock.patch("cria.probediscovery.discover", return_value=[]):
            self.assertEqual(select_completion_probes("/nonexistent"), [])

    def test_bare_dir_with_root_test_file_gets_a_test_floor_probe(self):
        # A bare "script + test_*.py" project (no pyproject / pytest.ini / tests dir) is not a detected
        # ecosystem, so ranked discovery yields NO test probe — the gate would run syntax+lint but never
        # the tests (vacuous green). The TEST FLOOR guarantees a pytest probe so the tests actually run.
        import tempfile, os
        with tempfile.TemporaryDirectory() as t:
            open(os.path.join(t, "app.py"), "w").write("def f():\n    return 1\n")
            open(os.path.join(t, "test_app.py"), "w").write("def test_f():\n    assert 1\n")
            tests = [c for c in select_completion_probes(t) if c.kind is ProbeKind.Test]
            self.assertEqual(len(tests), 1)
            self.assertEqual(tests[0].command, ["python3", "-m", "pytest", "-q"])

    def test_bare_dir_without_test_files_gets_no_test_probe(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as t:
            open(os.path.join(t, "app.py"), "w").write("x = 1\n")
            self.assertEqual([c for c in select_completion_probes(t) if c.kind is ProbeKind.Test], [])


# ---------------------------------------------------------------------------
# completion_block_nudge (pure rendering).
# ---------------------------------------------------------------------------

class TestCompletionBlockNudge(unittest.TestCase):
    def _dirty_floor(self):
        return LinterReport(findings=[LinterFinding(
            language="python", tool="py_compile", passed=False,
            errors="src/a.py:3: invalid syntax")])

    def test_dirty_floor_takes_precedence(self):
        floor = self._dirty_floor()
        report = ProbeReport(["python"], [], [ProbeResult(
            "ruff check .", 1, "src/b.py:1: boom", [Finding("src/b.py", 1, None, "boom")])])
        self.assertEqual(completion_block_nudge(report, floor), floor.nudge_text())

    def test_dirty_floor_with_none_nudge_returned_as_is(self):
        # upstream returns floor.nudge_text() unconditionally when the floor is
        # dirty — even a None passes through (LinterReport contract allows it).
        floor = _FakeFloor(clean=False, nudge=None)
        report = ProbeReport(["python"], [], [ProbeResult(
            "ruff check .", 1, "boom", [Finding("src/b.py", 1, None, "boom")])])
        self.assertIsNone(completion_block_nudge(report, floor))

    def test_structured_findings_block_with_exact_format(self):
        floor = LinterReport()
        report = ProbeReport(["python"], [], [ProbeResult(
            "ruff check .", 1, "src/b.py:9: boom (+1 more)",
            [Finding("src/b.py", 9, 1, "boom"), Finding("src/c.py", None, None, "bad")])])
        nudge = completion_block_nudge(report, floor)
        self.assertTrue(nudge.startswith(BLOCK_NUDGE_PREAMBLE))
        lines = nudge[len(BLOCK_NUDGE_PREAMBLE):].split("\n")
        self.assertEqual(lines[0], "$ ruff check . — src/b.py:9: boom (+1 more)")
        self.assertEqual(lines[1], "  • src/b.py:9: boom")
        self.assertEqual(lines[2], "  • src/c.py: bad")  # line=None -> bare file

    def test_all_findings_shown_per_probe(self):
        # No .take(5) clip: EVERY finding a probe produced is shown, so an error past the 5th is never
        # hidden from the model (a probe with 12 real errors once surfaced only 5). The window-aware
        # context floor is the only place a truncation may happen.
        findings = [Finding("f.py", i, None, f"m{i}") for i in range(1, 8)]
        report = ProbeReport(["python"], [], [ProbeResult("ruff check .", 1, "s", findings)])
        nudge = completion_block_nudge(report, LinterReport())
        bullets = [l for l in nudge.split("\n") if l.startswith("  • ")]
        self.assertEqual(len(bullets), 7)

    def test_single_finding_is_not_echoed_as_a_duplicate_bullet(self):
        # When the "$ cmd — summary" header IS the one finding (summary == "file:line: msg"), the bullet
        # would be byte-identical noise — suppress it. Multi-finding summaries ("… (+N more)") differ,
        # so their bullets stay.
        report = ProbeReport(["python"], [], [ProbeResult(
            "python3 -m pytest -q", 2, "smoke_test.py:2: ImportError: rel import",
            [Finding("smoke_test.py", 2, None, "ImportError: rel import")])])
        nudge = completion_block_nudge(report, LinterReport())
        self.assertIn("$ python3 -m pytest -q — smoke_test.py:2: ImportError: rel import", nudge)
        self.assertNotIn("  • ", nudge)   # no duplicate bullet

    def test_timeouts_and_launch_failures_never_block(self):
        report = ProbeReport(["python"], [], [
            ProbeResult("pytest -q", None,
                        "TIMEOUT after 120s — probe did not finish"
                        " (consider a narrower target)", []),
            ProbeResult("mypy .", None,
                        "failed to launch (nope) — tool not installed?", []),
        ])
        self.assertIsNone(completion_block_nudge(report, LinterReport()))

    def test_all_clean_allows_completion(self):
        report = ProbeReport(["python"], [], [ProbeResult("pytest -q", 0, "clean", [])])
        self.assertIsNone(completion_block_nudge(report, LinterReport()))

    def test_timed_out_test_blocks_but_launch_failure_does_not(self):
        # M3: a hard-failure-kind probe (Test) that actually TIMED OUT ran and did NOT verify → completion
        # must fail CLOSED (block, principle #13). A LAUNCH failure (absent tool = cria's OWN setup gap)
        # still fails OPEN (must not wedge). exit_code is None for BOTH; the timed_out FLAG distinguishes them.
        from cria.proberun import gate_ran_tests
        cand = synth(["pytest", "-q"], kind=ProbeKind.Test)
        timed = ProbeReport(["python"], [cand], [
            ProbeResult("pytest -q", None, "TIMEOUT after 120s — did not finish", [], timed_out=True)])
        nudge = completion_block_nudge(timed, LinterReport())
        self.assertIsNotNone(nudge)                        # timed-out test → fail closed
        self.assertIn("pytest -q", nudge)                  # the timed-out check is surfaced to the coder
        self.assertFalse(gate_ran_tests(timed))            # a timed-out test did NOT execute a full run
        tc = synth(["mypy", "."], kind=ProbeKind.Typecheck)
        launch = ProbeReport(["python"], [tc], [
            ProbeResult("mypy .", None, "failed to launch — tool not installed?", [], timed_out=False)])
        self.assertIsNone(completion_block_nudge(launch, LinterReport()))  # absent tool → fail open


class TestUnranProbes(unittest.TestCase):
    """A probe that failed to launch / timed out (exit_code is None) is MISSING SIGNAL, not a pass —
    unran_probes surfaces it so ground truth is never rendered as "all checks pass"."""

    def test_launch_failure_and_timeout_are_unran_clean_is_not(self):
        report = ProbeReport(["python"], [], [
            ProbeResult("python -m pytest -q", None, "failed to launch — tool not installed?", []),
            ProbeResult("mypy .", None, "TIMEOUT after 45s", []),
            ProbeResult("python3 -m compileall -q .", 0, "clean", []),   # this one RAN — excluded
        ])
        unran = unran_probes(report)
        self.assertEqual(len(unran), 2)
        self.assertTrue(any("pytest" in u for u in unran))
        self.assertTrue(all("compileall" not in u for u in unran))

    def test_all_ran_yields_no_unran(self):
        report = ProbeReport(["python"], [], [ProbeResult("python3 -m pytest -q", 0, "3 passed", [])])
        self.assertEqual(unran_probes(report), [])


class TestLaunchFailureExitCodes(unittest.TestCase):
    """coreutils timeout exits 125/126/127 when the command did not really run — all must map to a
    launch failure (exit_code None) so it's never read as clean. The text fallback must not override a
    real exit 0."""

    def _interp(self, raw, kind=ProbeKind.Test):
        return interpret_probe_output(synth(["gradlew"], kind), "gradlew", raw, None, 45.0)

    def test_exit_126_not_executable_is_launch_failure(self):
        r = self._interp("permission denied\nEXIT:126\n")
        self.assertIsNone(r.exit_code)                 # launch failure
        self.assertNotIn("permission denied", "\n".join(f.message for f in r.findings))

    def test_exit_125_timeout_self_failure_is_launch_failure(self):
        self.assertIsNone(self._interp("timeout: bad usage\nEXIT:125\n").exit_code)

    def test_exit_0_with_command_not_found_in_output_stays_clean(self):
        # a test asserting on an error string must keep its real exit 0 — not be flipped by a substring
        r = self._interp("test_err PASSED\nassert 'command not found' in stderr\n1 passed\nEXIT:0\n")
        self.assertEqual(r.exit_code, 0)


class TestFailedUnparsedProbes(unittest.TestCase):
    """A hard-failure probe (test/typecheck/build) that RAN, exited non-zero, but produced no parseable
    finding is a real failure — surfaced. A LINT that exits non-zero on advisory-only findings (already
    stripped from r.findings) must NOT be — that would resurrect the unused-import footgun."""

    def _report(self, *specs):  # each spec: (cmd_list, exit_code, findings, kind)
        sel = [synth(c, k) for (c, _e, _f, k) in specs]
        res = [ProbeResult(" ".join(c), e, "sum", f) for (c, e, f, k) in specs]
        return ProbeReport([], sel, res)

    def test_hard_failure_no_findings_is_surfaced(self):
        rep = self._report(
            (["pytest", "-q"], 1, [], ProbeKind.Test),
            (["cargo", "check"], 101, [], ProbeKind.BuildCheck),
        )
        out = failed_unparsed_probes(rep)
        self.assertEqual(len(out), 2)
        self.assertTrue(any("pytest" in o for o in out))
        self.assertTrue(any("cargo" in o for o in out))

    def test_lint_nonzero_no_findings_is_not_a_failure(self):
        # ruff exits 1 on an unused import; parse_output already stripped that advisory from findings.
        rep = self._report((["ruff", "check", "."], 1, [], ProbeKind.Lint))
        self.assertEqual(failed_unparsed_probes(rep), [])

    def test_gate_ran_tests_true_only_when_a_test_probe_actually_ran(self):
        from cria.proberun import gate_ran_tests
        test = synth(["pytest", "-q"], ProbeKind.Test)
        lint = synth(["ruff", "check", "."], ProbeKind.Lint)
        self.assertTrue(gate_ran_tests(ProbeReport([], [test], [ProbeResult("pytest -q", 0, "3 passed", [])])))
        # vacuous green: the test probe collected NOTHING (exit 5) → not a real test run
        self.assertFalse(gate_ran_tests(ProbeReport([], [test], [ProbeResult("pytest -q", 5, "no tests ran", [])])))
        # no test probe at all (lint-only green) → vacuous
        self.assertFalse(gate_ran_tests(ProbeReport([], [lint], [ProbeResult("ruff check .", 0, "clean", [])])))
        self.assertFalse(gate_ran_tests(None))

    def test_clean_and_launch_failure_and_parsed_failures_are_excluded(self):
        rep = self._report(
            (["pytest", "-q"], 0, [], ProbeKind.Test),                                # clean
            (["mypy", "."], None, [], ProbeKind.Typecheck),                           # launch failure
            (["pytest", "-q2"], 1, [Finding(file="x.py", line=1, message="boom")], ProbeKind.Test),  # parsed
        )
        self.assertEqual(failed_unparsed_probes(rep), [])

    def test_pytest_no_tests_collected_exit5_is_not_a_failure(self):
        # A fresh/testless project: pytest launches fine and collects nothing (exit 5). That is NOT a
        # failing test — it must not read as "tests broke". A real cargo failure alongside still surfaces.
        rep = self._report(
            (["python3", "-m", "pytest", "-q"], 5, [], ProbeKind.Test),   # no tests collected
            (["cargo", "check"], 101, [], ProbeKind.BuildCheck),          # real failure
        )
        out = failed_unparsed_probes(rep)
        self.assertEqual(len(out), 1)
        self.assertTrue(any("cargo" in o for o in out))
        self.assertFalse(any("pytest" in o for o in out))


# ---------------------------------------------------------------------------
# completion_probe_digest extras (the upstream test covers the main shape).
# ---------------------------------------------------------------------------

class TestDigestExtras(unittest.TestCase):
    def test_dirty_floor_renders_its_nudge(self):
        floor = LinterReport(findings=[LinterFinding(
            language="python", tool="py_compile", passed=False,
            errors="src/a.py:3: invalid syntax")])
        digest = completion_probe_digest(ProbeReport([], [], []), floor)
        self.assertTrue(digest.startswith("SYNTAX FLOOR: "))
        self.assertIn("src/a.py:3: invalid syntax", digest)

    def test_dirty_floor_without_nudge_uses_fallback(self):
        floor = _FakeFloor(clean=False, nudge=None)
        digest = completion_probe_digest(ProbeReport([], [], []), floor)
        self.assertIn("SYNTAX FLOOR: parse/syntax issues found", digest)

    def test_did_not_launch_rendering(self):
        report = ProbeReport(["python"], [], [ProbeResult(
            "mypy .", None, "failed to launch (x) — tool not installed?", [])])
        digest = completion_probe_digest(report, LinterReport())
        self.assertIn("did NOT launch (tool missing?)", digest)
        self.assertIn("0 structured finding(s)", digest)

    def test_pytest_no_tests_collected_renders_benign_not_exit5(self):
        # exit 5 with no tests must read as "nothing to run", not a bare "exit 5" the critic reads as a
        # failing suite — the whole point of the digest is telling "tests pass" from "tests never ran".
        report = ProbeReport(["python"], [], [ProbeResult(
            "python3 -m pytest -q", 5, "no tests ran in 0.01s", [])])
        digest = completion_probe_digest(report, LinterReport())
        self.assertIn("no tests collected", digest)
        self.assertNotIn("exit 5", digest)


# ---------------------------------------------------------------------------
# Proxy path: compose / scrape / interpret (pure).
# ---------------------------------------------------------------------------

class TestComposeProbeCommand(unittest.TestCase):
    def test_composed_line_has_every_mechanic(self):
        c = synth(["echo", "a b"])
        c.working_dir = "/tmp/with space"
        line = compose_probe_command(c, 10.0)
        half = PROBE_OUTPUT_CAP_BYTES // 2
        self.assertIn("cd '/tmp/with space' && ", line)        # cwd, quoted
        self.assertIn("timeout -k 5 10 echo 'a b'", line)      # hard timeout + quoted argv
        self.assertIn("</dev/null 2>&1", line)                 # stdin null, merged streams
        self.assertIn(f"head -c {half}", line)                 # head+tail budget: an EARLY failure survives
        self.assertIn(f"tail -c {half}", line)                 # ...and a late one
        self.assertIn("elided", line)                          # middle-elision disclosed, never silent
        self.assertIn(PROBE_EXIT_SENTINEL, line)               # exit-code sentinel

    def test_fractional_timeout_is_not_truncated_to_zero(self):
        # int-truncating 0.4 would compose `timeout 0`, which DISABLES the timeout.
        line = compose_probe_command(synth(["sleep", "5"]), 0.4)
        self.assertIn("timeout -k 5 0.4 sleep 5", line)

    def test_empty_command_raises(self):
        with self.assertRaises(ValueError):
            compose_probe_command(synth([]), 10.0)


class TestDisplayCommand(unittest.TestCase):
    """The command STRING shown to the model (r.command) must be runnable — a naive space-join of a
    `python3 -c '<multi-line script>' <file>` argv renders an un-runnable blob the model copies verbatim
    (the pyproject-spiral footgun). shlex.join quotes each token."""

    def test_multiline_dash_c_and_glued_file_are_quoted(self):
        from cria.proberun import display_command
        argv = ["python3", "-c", "import sys\ntry:\n    import tomllib\nexcept: pass\nsys.exit(1)",
                "/home/x/pyproject.toml"]
        shown = display_command(argv)
        self.assertIn("'import sys\ntry:", shown)          # the -c script is a single quoted token
        self.assertIn(" /home/x/pyproject.toml", shown)    # the file is a separate, distinct token
        self.assertTrue(shown.startswith("python3 -c "))

    def test_simple_argv_unchanged_and_empty_is_blank(self):
        from cria.proberun import display_command
        self.assertEqual(display_command(["python3", "-m", "pytest", "-q"]), "python3 -m pytest -q")
        self.assertEqual(display_command([]), "")


class TestScrapeExit(unittest.TestCase):
    def test_scrapes_trailing_sentinel(self):
        out, code = scrape_exit("src/x.py:9: error: boom\nEXIT:1\n")
        self.assertEqual(code, 1)
        self.assertEqual(out, "src/x.py:9: error: boom")

    def test_bottom_up_last_sentinel_wins(self):
        out, code = scrape_exit("EXIT:7 mentioned in output\nreal output\nEXIT:0\n")
        self.assertEqual(code, 0)
        self.assertIn("EXIT:7 mentioned in output", out)

    def test_no_sentinel_returns_none(self):
        out, code = scrape_exit("just output\n")
        self.assertIsNone(code)
        self.assertEqual(out, "just output\n")


class TestInterpretProbeOutput(unittest.TestCase):
    def test_exit_124_maps_to_timeout_and_keeps_findings(self):
        c = synth(["ruff", "check", "."])
        r = interpret_probe_output(
            c, "ruff check .", "app/main.py:3:1: F821 undefined name `os`\n",
            124, 20.0)
        self.assertIsNone(r.exit_code)
        self.assertEqual(
            r.summary,
            "TIMEOUT after 20s — probe did not finish (consider a narrower target)")
        self.assertEqual(len(r.findings), 1)  # findings from partial output kept

    def test_exit_127_maps_to_launch_failure(self):
        c = synth(["not-a-tool"])
        r = interpret_probe_output(c, "not-a-tool", "", 127, 20.0)
        self.assertIsNone(r.exit_code)
        self.assertIn("failed to launch", r.summary)
        self.assertIn("tool not installed?", r.summary)

    def test_command_not_found_text_maps_to_launch_failure(self):
        c = synth(["not-a-tool"])
        r = interpret_probe_output(
            c, "not-a-tool", "bash: line 1: not-a-tool: command not found\n", None, 20.0)
        self.assertIsNone(r.exit_code)
        self.assertIn("failed to launch", r.summary)

    def test_text_only_result_scrapes_sentinel(self):
        c = synth(["ruff", "check", "."])
        r = interpret_probe_output(
            c, "ruff check .",
            "app/main.py:3:1: F821 undefined name `os`\nEXIT:1\n", None, 20.0)
        self.assertEqual(r.exit_code, 1)
        self.assertEqual(len(r.findings), 1)
        self.assertEqual(r.findings[0].file, "app/main.py")

    def test_empty_command_contract(self):
        r = interpret_probe_output(synth([]), "", "anything", 0, 20.0)
        self.assertEqual(r.summary, "empty command")
        self.assertIsNone(r.exit_code)


class TestComposedRoundtrip(unittest.TestCase):
    """Prove the composed line + interpret round-trips through a real shell.
    bash stands in for the harness's shell tool — test-file-only execution."""

    def _run(self, line):
        return subprocess.run(["bash", "-c", line], capture_output=True,
                              text=True, timeout=30)

    def test_diagnostic_roundtrip(self):
        code = "import sys; sys.stderr.write('src/x.py:9: error: boom\\n'); sys.exit(1)"
        c = synth(["python3", "-c", code])
        proc = self._run(compose_probe_command(c, 10.0))
        r = interpret_probe_output(c, " ".join(c.command), proc.stdout, None, 10.0)
        self.assertEqual(r.exit_code, 1)
        self.assertEqual(len(r.findings), 1)
        self.assertEqual(r.findings[0].file, "src/x.py")
        self.assertEqual(r.findings[0].line, 9)

    def test_timeout_roundtrip(self):
        c = synth(["python3", "-c", "import time; time.sleep(30)"])
        proc = self._run(compose_probe_command(c, 0.4))
        r = interpret_probe_output(c, " ".join(c.command), proc.stdout, None, 0.4)
        self.assertIsNone(r.exit_code)
        self.assertTrue(r.summary.startswith("TIMEOUT after 0s"))

    def test_missing_tool_roundtrip(self):
        c = synth(["definitely-not-a-real-binary-xyz", "check"])
        proc = self._run(compose_probe_command(c, 5.0))
        r = interpret_probe_output(c, " ".join(c.command), proc.stdout, None, 5.0)
        self.assertIsNone(r.exit_code)
        self.assertIn("failed to launch", r.summary)

    def test_head_tail_preserves_an_early_failure_under_a_huge_tail(self):
        # THE tail-only footgun: a real failure printed EARLY, then buried under a long teardown/summary.
        # head+tail keeps the head, so parse_output still localizes it (a tail -c clip would have lost
        # the failure entirely). The elided middle is disclosed, never silently dropped.
        code = ("import sys\n"
                "print('src/x.py:9: error: boom')\n"     # the real failure, printed FIRST
                "print('z' * 40000)\n"                    # a huge teardown tail > the output budget
                "sys.exit(1)")
        c = synth(["python3", "-c", code])
        proc = self._run(compose_probe_command(c, 10.0))
        r = interpret_probe_output(c, " ".join(c.command), proc.stdout, None, 10.0)
        self.assertEqual(r.exit_code, 1)
        self.assertTrue(any(f.file == "src/x.py" and f.line == 9 for f in r.findings))
        self.assertIn("elided", proc.stdout)              # the middle-elision was disclosed


class GateSkippedCountTests(unittest.TestCase):
    """A SUITE CAN PASS WHILE SKIPPING THE CHECKS THAT MATTER (run 0728-m11): the coder's live tests
    skipTest() on the exact 404 that proves the resolver broken, and "3 passed, 2 skipped" read as
    green — the run ended done with a resolver that 404s against the real API. The skip count is a
    tool-reported fact (the runner's own summary line), surfaced deterministically; runners without
    the "N skipped" phrase report 0 — an under-count only ever means silence, never a false alarm."""

    def _report(self, summary, kind=None, timed_out=False):
        from cria import probediscovery
        from cria.proberun import ProbeReport
        from cria.probeparse import ProbeResult
        kind = kind or probediscovery.ProbeKind.Test
        cand = probediscovery.cand(kind, ["python3", "-m", "pytest", "-q"], ".", 60, 90,
                                   probediscovery.ProbeCost.Moderate, "tests")
        r = ProbeResult(command="python3 -m pytest -q")
        r.summary = summary
        r.timed_out = timed_out
        rep = ProbeReport(results=[r])
        rep.selected = [cand]
        return rep

    def _parsed(self, raw):
        """A report built through the REAL parser.

        THIS TEST USED TO HAND-BUILD `summary`, and that is how the defect survived: `parse_output`
        replaces a GREEN run's output with the fixed string "no problems reported" and keeps no raw
        text, so `gate_skipped_count` — which is only ever asked about GREEN gates — re-scanned a
        string that can never contain "N skipped" and returned 0 for every run cria has ever made.
        The count is taken at parse time now, and this fixture goes through it."""
        from cria import probeparse
        return ProbeReport([], [synth(["pytest", "-q"], ProbeKind.Test)],
                           [probeparse.parse_output("pytest -q", "pytest", 0, raw, "")])

    def test_the_m11_summary_reports_two_skipped(self):
        from cria.proberun import gate_skipped_count
        self.assertEqual(gate_skipped_count(self._parsed("3 passed, 2 skipped in 0.24s")), 2)

    def test_a_green_run_is_where_this_is_ASKED_and_it_works_there(self):
        """The regression guard. Green is the only state this is consulted in."""
        from cria.proberun import gate_skipped_count
        rep = self._parsed("3 passed, 2 skipped in 0.24s")
        self.assertEqual(rep.results[0].summary, "no problems reported")   # nothing to re-scan
        self.assertEqual(gate_skipped_count(rep), 2)                        # counted anyway

    def test_a_clean_run_reports_zero(self):
        from cria.proberun import gate_skipped_count
        self.assertEqual(gate_skipped_count(self._report("5 passed in 0.10s")), 0)

    def test_non_test_probes_and_timeouts_never_count(self):
        from cria import probediscovery
        from cria.proberun import gate_skipped_count
        self.assertEqual(gate_skipped_count(
            self._report("2 skipped", kind=probediscovery.ProbeKind.Lint)), 0)
        self.assertEqual(gate_skipped_count(self._report("2 skipped", timed_out=True)), 0)

    def test_none_report_is_zero(self):
        from cria.proberun import gate_skipped_count
        self.assertEqual(gate_skipped_count(None), 0)


if __name__ == "__main__":
    unittest.main()
