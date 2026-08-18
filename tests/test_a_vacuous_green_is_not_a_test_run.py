"""cria told the completion judge that tests had executed, in every language but Python, when none had.

`gate_ran_tests` decides whether a green gate rests on real test execution. Its whole purpose, in its
own words: *"A GREEN gate that rests on zero tests collected (or no test probe at all) is a VACUOUS
green: it verifies no behavior."* It answered that question with `is_no_tests_collected`, which is
**pytest's convention** — exit code 5 plus a pytest fingerprint.

Every other runner in the fleet exits 0 on an empty suite. Measured on this machine:

    go test ./...   with no test files   -> exit 0
    ruby t.rb       with 0 runs          -> exit 0
    pytest          with 0 collected     -> exit 5   <- the only code the check accepted

So a suite that ran nothing answered `gate_ran_tests` -> True for go, minitest, cargo and rspec, and
the satisfaction judge — which holds the task and decides whether tests were part of the ask — was
told they had run. A false fact handed to a judge (#5b), from a rule keyed to one tool's convention
and silently inert on the rest (#20). `handles-go`, `shipping-rates-rb`, `rust-toml-cli` and
`feed-pipeline-java` are all live suite cells.

**THE KERNEL-LEVEL READING ALREADY EXISTED.** `probeparse` parses a runner TALLY and knows twelve of
them; an empty suite yields `0f/0p` from minitest, cargo, rspec, phpunit, junit, jest, gradle, exunit
and dotnet. Asking it is one question in one place, rather than a second per-runner phrase table
beside the first (#4).

Plain `go test` is the one runner that prints no count at all — deliberately not a tally, because a
package whose only live test calls `t.Skip()` still prints `ok`. It says `[no test files]` in words
instead, and that string belongs beside pytest's exit 5 in the one owner for "the runner found
nothing to run".

**POSITIVE KNOWLEDGE ONLY.** An unparseable result keeps the previous answer. cria not being able to
read a runner is not evidence that nothing ran (#11b), and this may only move a result from "ran" to
"did not run" on evidence, never the other way (#2).
"""

import pathlib
import unittest

from cria import probediscovery, probeparse, proberun


def _report(command, exit_code, output, kind=None):
    """A gate report shaped as the real one: one probe, its exit code, and the tally cria parses."""
    cand = probediscovery.ProbeCandidate(
        kind=kind or probediscovery.ProbeKind.Test, command=command.split(),
        working_dir=pathlib.Path("/tmp"), confidence=100, expected_value=100,
        cost=probediscovery.ProbeCost.Cheap, mutates_code=False, may_hang=False,
        may_need_services=False, reason="t")
    res = proberun.ProbeResult(command=command, exit_code=exit_code, summary=output,
                               tally=probeparse.runner_tally(output))
    return proberun.ProbeReport(project_type=["x"], selected=[cand], results=[res])


EMPTY = {
    "pytest":   ("pytest", 5, "collected 0 items"),
    "minitest": ("ruby t.rb", 0, "0 runs, 0 assertions, 0 failures, 0 errors, 0 skips"),
    "cargo":    ("cargo test", 0, "test result: ok. 0 passed; 0 failed; 0 ignored"),
    "rspec":    ("rspec", 0, "0 examples, 0 failures"),
    "go":       ("go test ./...", 0, "ok  \tz\t[no test files]"),
}
REAL = {
    "pytest":   ("pytest", 0, "===== 7 passed in 0.05s ====="),
    "minitest": ("ruby t.rb", 0, "9 runs, 9 assertions, 0 failures, 0 errors, 0 skips"),
    "cargo":    ("cargo test", 0, "test result: ok. 12 passed; 0 failed; 0 ignored"),
    "rspec":    ("rspec", 0, "12 examples, 0 failures"),
    "go":       ("go test -v ./...", 0, "--- PASS: TestA\n--- PASS: TestB\nok  \tz"),
    "jest":     ("npx jest", 0, "Tests:       1 failed, 11 passed, 12 total"),
    "junit":    ("mvn test", 0, "Tests run: 12, Failures: 0, Errors: 0, Skipped: 0"),
}


class AnEmptySuiteIsNotATestRunTests(unittest.TestCase):
    def test_no_runner_reports_a_vacuous_green_as_tests_having_run(self):
        for name, (cmd, code, out) in EMPTY.items():
            with self.subTest(runner=name):
                self.assertFalse(proberun.gate_ran_tests(_report(cmd, code, out)))

    def test_pytest_was_already_right_and_stays_right(self):
        """The one runner the old check covered must not regress."""
        cmd, code, out = EMPTY["pytest"]
        self.assertFalse(proberun.gate_ran_tests(_report(cmd, code, out)))

    def test_go_says_it_in_words_while_exiting_zero(self):
        """The exit code carries nothing here — that is why the marker is a trigger, not a
        confirmation."""
        self.assertTrue(proberun.is_no_tests_collected(0, "go test ./...", "ok  z  [no test files]"))


class RealTestRunsAreUntouchedTests(unittest.TestCase):
    def test_every_runner_with_tests_still_reports_them(self):
        for name, (cmd, code, out) in REAL.items():
            with self.subTest(runner=name):
                self.assertTrue(proberun.gate_ran_tests(_report(cmd, code, out)))

    def test_a_failing_suite_still_counts_as_having_run(self):
        """"Did tests execute" is a different question from "did they pass"."""
        self.assertTrue(proberun.gate_ran_tests(
            _report("ruby t.rb", 1, "9 runs, 9 assertions, 3 failures, 0 errors, 0 skips")))

    def test_a_non_test_probe_never_answers_this(self):
        self.assertFalse(proberun.gate_ran_tests(
            _report("cargo check", 0, "Finished dev", kind=probediscovery.ProbeKind.BuildCheck)))


class BlindnessIsNotEvidenceTests(unittest.TestCase):
    def test_an_unreadable_runner_keeps_the_previous_answer(self):
        """cria failing to parse a runner is not a finding about that runner (#11b), and this check
        may only move a result toward "did not run" on evidence."""
        self.assertTrue(proberun.gate_ran_tests(
            _report("./run-my-suite.sh", 0, "everything is fine, trust me")))

    def test_a_timed_out_probe_did_not_complete_a_run(self):
        cand = probediscovery.ProbeCandidate(
            kind=probediscovery.ProbeKind.Test, command=["pytest"], working_dir=pathlib.Path("/tmp"),
            confidence=100, expected_value=100, cost=probediscovery.ProbeCost.Cheap,
            mutates_code=False, may_hang=False, may_need_services=False, reason="t")
        res = proberun.ProbeResult(command="pytest", exit_code=None, summary="", timed_out=True)
        self.assertFalse(proberun.gate_ran_tests(
            proberun.ProbeReport(project_type=["x"], selected=[cand], results=[res])))


class OneOwnerPerQuestionTests(unittest.TestCase):
    def test_the_tally_is_asked_rather_than_a_second_phrase_table(self):
        """A per-runner list of "zero tests" phrasings beside the per-runner tally table would be the
        same table twice, and the second copy is the one that goes stale."""
        import inspect
        src = inspect.getsource(proberun._tally_says_zero)
        self.assertIn("tally", src)
        self.assertEqual(len(proberun._ZERO_TEST_MARKERS), 1)   # only the runner that prints no count

    def test_the_marker_list_holds_only_runners_with_no_tally(self):
        for marker in proberun._ZERO_TEST_MARKERS:
            with self.subTest(marker=marker):
                self.assertEqual(probeparse.runner_tally(f"ok z {marker}"), "")


if __name__ == "__main__":
    unittest.main()
