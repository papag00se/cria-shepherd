"""The gate's probe run: composed command -> real shell -> honest ProbeResult, tallies and vacuous greens."""
import pathlib
import subprocess
import tempfile
from unittest import mock

import pytest

from cria import probediscovery as pd, probegate, probeparse, proberun, toolpath
from research_discovery_helpers import disk_view

pytestmark = pytest.mark.usefixtures("disk_view")


def cand(command, kind=pd.ProbeKind.Test, cwd="/tmp"):
    return pd.ProbeCandidate(kind=kind, command=list(command), working_dir=pathlib.Path(cwd), confidence=90,
                             expected_value=90, cost=pd.ProbeCost.Cheap, mutates_code=False, may_hang=False,
                             may_need_services=False, reason="t")


def report(command, code, out, kind=pd.ProbeKind.Test):
    """Built the way production builds it: parse_output replaces a green run's text with CLEAN_SUMMARY."""
    command = command.split()
    res = probeparse.parse_output(" ".join(command), probeparse.family_of(command), code, out, "")
    return proberun.ProbeReport(project_type=["x"], selected=[cand(command, kind)], results=[res])


def through_shell(command, py, timeout=10.0):
    """Run the composed probe line in a real bash (the harness shell) and interpret what comes back."""
    c = cand([command, "-c", py] if command == "python3" else [command, py], pd.ProbeKind.BuildCheck)
    proc = subprocess.run(["bash", "-c", proberun.compose_probe_command(c, timeout)], capture_output=True, text=True, timeout=30)
    return proc.stdout, proberun.interpret_probe_output(c, " ".join(c.command), proc.stdout, None, timeout)


def test_composed_probe_roundtrips_through_a_real_shell():
    """exit code, localized findings, timeout and missing tool survive compose->shell->interpret."""
    out, r = through_shell("python3", "import sys; sys.stderr.write('src/x.py:9: error: boom\\n'); sys.exit(1)")
    assert (r.exit_code, r.findings[0].file, r.findings[0].line) == (1, "src/x.py", 9)
    _, r = through_shell("python3", "import time; time.sleep(30)", timeout=0.4)
    assert r.exit_code is None and r.timed_out and r.summary.startswith("TIMEOUT after 0s")
    _, r = through_shell("definitely-not-a-real-binary-xyz", "check")
    assert r.exit_code is None and "failed to launch" in r.summary
    # a launch failure by code, but a green run that merely PRINTS "command not found" stays green
    c = cand(["x"])
    assert proberun.interpret_probe_output(c, "x", "", 126, 5).exit_code is None
    assert proberun.interpret_probe_output(c, "x", "command not found\nEXIT:0", None, 5).exit_code == 0


def test_a_huge_tail_never_elides_or_splices_an_early_failure():
    """Probe composition elides nothing: an early failure, the middle and the tail arrive whole, in order."""
    body = ("print('FIRST_FAILURE')\nprint('src/x.py:9: error: boom')\nprint('z'*40000)\nprint('MIDDLE')\n"
            "print('y'*40000)\nprint('LAST_FAILURE')\nimport sys; sys.exit(1)")
    out, r = through_shell("python3", body)
    assert "z" * 40000 in out and "y" * 40000 in out and "elided" not in out
    assert out.index("FIRST_FAILURE") < out.index("MIDDLE") < out.index("LAST_FAILURE")
    assert (r.exit_code, r.findings[0].line) == (1, 9)


EMPTY = {  # runners that exit 0 (or pytest's 5) on an empty suite, in their own words
    "pytest": ("pytest", 5, "collected 0 items"), "minitest": ("ruby t.rb", 0, "0 runs, 0 assertions, 0 failures, 0 errors, 0 skips"),
    "cargo": ("cargo test", 0, "test result: ok. 0 passed; 0 failed; 0 ignored"), "rspec": ("rspec", 0, "0 examples, 0 failures"),
    "go": ("go test ./...", 0, "ok  \tz\t[no test files]"),
    "maven": ("mvn -q test", 0, "[INFO] No tests to run."), "phpunit": ("vendor/bin/phpunit", 0, "No tests executed!"),
    "gradle": ("gradle test", 0, "> Task :test NO-SOURCE\nBUILD SUCCESSFUL"), "dotnet": ("dotnet test", 0, "No test is available in /ws/a.dll."),
}
REAL = {
    "pytest": ("pytest", 0, "===== 7 passed in 0.05s ====="), "minitest": ("ruby t.rb", 0, "9 runs, 9 assertions, 0 failures, 0 errors, 0 skips"),
    "cargo": ("cargo test", 0, "test result: ok. 12 passed; 0 failed; 0 ignored"), "go": ("go test -v ./...", 0, "--- PASS: TestA\nok  \tz"),
    "jest": ("npx jest", 0, "Tests:       1 failed, 11 passed, 12 total"), "junit": ("mvn test", 0, "Tests run: 12, Failures: 0, Errors: 0, Skipped: 0"),
    "red minitest": ("ruby t.rb", 1, "9 runs, 9 assertions, 3 failures, 0 errors, 0 skips"),
    "unreadable runner": ("./run-my-suite.sh", 0, "everything is fine, trust me"),
}


def test_gate_ran_tests_is_false_for_a_vacuous_green_in_every_language():
    """Only pytest's exit 5 was recognised, so every other language's empty suite read as 'tests executed'."""
    for name, (cmd, code, out) in (EMPTY | REAL).items():
        assert proberun.gate_ran_tests(report(cmd, code, out)) is (name in REAL), name


def test_gate_ran_tests_needs_a_completed_test_probe():
    """A timed-out test did not run a suite; a build check is not a test; no report is not a run."""
    res = proberun.ProbeResult(command="pytest", exit_code=None, summary="", timed_out=True)
    assert not proberun.gate_ran_tests(proberun.ProbeReport(project_type=["x"], selected=[cand(["pytest"])], results=[res]))
    assert not proberun.gate_ran_tests(report("cargo check", 0, "Finished", pd.ProbeKind.BuildCheck))
    assert not proberun.gate_ran_tests(None)
    # a counted run outranks a sentence; an uncounted green claims nothing about the words in its summary
    counted = proberun.ProbeResult(command="rspec", exit_code=0, summary="ok", tally="0f/9p", no_tests=True)
    assert not proberun.result_collected_nothing(counted)


def test_runner_tally_reads_each_runners_own_count():
    """An ERROR is not a pass (read as `0f/` it is a clean run to the supersede check); plain `go test` prints packages, not tests."""
    for text, tally in [
        ("9 runs, 9 assertions, 0 failures, 0 errors, 0 skips", "0f/9p"), ("2 runs, 1 assertions, 0 failures, 1 errors, 0 skips", "1f/1p"),
        ("1 failed, 1 passed, 1 error in 0.02s", "2f/1p"), ("Tests: 5, Assertions: 5, Errors: 1, Failures: 2.", "3f/2p"),
        ("OK (2 tests, 2 assertions)", "0f/2p"), ("Tests run: 5, Failures: 0, Errors: 2, Skipped: 0", "2f/3p"),
        ("TAP version 13\n# tests 13\n# pass 13\n# fail 0", "0f/13p"), ("  11 passing\n  1 failing", "1f/11p"),
        ("test result: ok. 2 passed; 0 failed; 0 ignored\ntest result: ok. 3 passed; 1 failed; 0 ignored\n", "1f/5p"),
        ("ok  \tcartsvc\t0.003s\n", ""), ("--- PASS: TestA\n--- FAIL: TestB\nok  \tcartsvc\n", "1f/1p")]:
        assert probeparse.runner_tally(text) == tally, text


def test_skipped_tests_are_counted_from_a_green_run_only_for_test_probes():
    """run 0728-m11: '3 passed, 2 skipped' read as green; the count is taken at parse time (green summary is fixed)."""
    rep = report("python3 -m pytest -q", 0, "3 passed, 2 skipped in 0.24s")
    assert rep.results[0].summary == probeparse.CLEAN_SUMMARY and proberun.gate_skipped_count(rep) == 2
    assert proberun.gate_skipped_count(report("pytest", 0, "5 passed in 0.1s")) == 0
    assert proberun.gate_skipped_count(report("ruff", 0, "2 skipped", pd.ProbeKind.Lint)) == 0
    assert proberun.gate_skipped_count(None) == 0


def test_offline_sentence_claims_only_what_the_two_runs_establish():
    """'nothing reaches the internet' needs two green runs with the same count and no new skips (mellum2 1786047222: a live test that SKIPS)."""
    plan = probegate.GatePlan(workspace="", candidates=[cand(["python3", "-m", "pytest", "-q"])])
    for online, offline, expect in [
        ("2 passed in 0.1s\nEXIT:0", "2 passed in 0.1s\nEXIT:0", "(0f/2p)"),
        ("1 failed, 1 passed\nEXIT:1", "1 failed, 1 passed\nEXIT:1", ""),     # failing on a box with no network proves nothing
        ("2 passed\nEXIT:0", "1 failed, 1 passed\nEXIT:1", ""),               # really needs the network
        ("6 passed in 0.1s\nEXIT:0", "5 passed, 1 skipped in 0.02s\nEXIT:0", ""),
        ("test result: ok. 4 passed; 0 failed; 0 ignored\nEXIT:0", "test result: ok. 3 passed; 0 failed; 1 ignored\nEXIT:0", ""),
        ("ok  \tpkg\t0.01s\nEXIT:0", "ok  \tpkg\t0.01s\nEXIT:0", "still succeeds with the network switched off")]:
        fact = probegate._offline_fact({"probe-0": online, "offline": offline}, plan)
        assert (expect in fact) if expect else fact == "", (online, offline)
    assert proberun.offline_probe_command(cand(["pyflakes", "x.py"], pd.ProbeKind.Lint), 60) == ""


def test_a_probe_naming_a_certainly_absent_program_is_dropped(tmp_path):
    """UNSURE MEANS KEEP: only a certain absence (read off the coder's PATH) removes a probe; a project-local wrapper is checked as a file."""
    with mock.patch.object(toolpath, "resolved", lambda p: p if p in ("ruby", "python3") else ""):
        present = lambda *command: proberun.program_is_installed(cand(command, cwd=str(tmp_path)))
        assert present("python3", "-c", "pass") and present("GEM_HOME=v", "ruby", "-c", "x")   # an env prefix is not the program
        assert not present("definitely-not-a-real-tool-xyz") and not present("bundle", "exec", "rubocop") and not present("./gradlew", "test")
        write = tmp_path / "gradlew"
        write.write_text("#!/bin/sh\n")
        write.chmod(0o755)
        assert present("./gradlew", "test")
