"""A runner cria cannot count is a runner whose green is permanently unverifiable.

`runner_tally` reads a suite's own pass/fail line. The PASSED count is the coverage signal: it is
what stands between "the suite is self-contained" and "one test quietly stepped aside" (see
`_offline_fact`). A runner with no row returns "" — so its passing suite is invisible, and cria
falls back to the weaker sentence that claims only what the exit code established.

Measured on the six-language battery: minitest's `9 runs, 9 assertions, 0 failures` and node's TAP
`# pass 13` were both unreadable, and those are precisely the two languages where the walkers report
the gate never counted a single test. Both are data completeness in an existing, correctly-shaped
table — not a per-language special case.

Node's built-in runner had a second, separate hole: `probeclassify` seeded jest/mocha/ava/tap/uvu/
vitest/deno but not `node`, and `node --test` is invoked by FLAG rather than subcommand, the one
shape the sub-seed table cannot express. `build_js` drops a package.json script it cannot classify,
so a project choosing the most conservative runner available got no test probe at all.
"""
import unittest

from cria import probeclassify as pc
from cria import probegate as pg


class EveryRunnersGreenIsCountableTests(unittest.TestCase):
    CASES = {
        "minitest":      ("9 runs, 9 assertions, 0 failures, 0 errors, 0 skips", "0f/9p"),
        # AN ERROR IS NOT A PASS. This read `2f/22p` while the runner said 2 failures AND 1 error,
        # so the errored test was counted as passing and the tally began "0f/" whenever failures
        # happened to be zero — which `_checks_superseded_by_coder_run` reads as a clean run.
        "minitest red":  ("24 runs, 30 assertions, 2 failures, 1 errors, 0 skips", "3f/21p"),
        "minitest error only": ("2 runs, 1 assertions, 0 failures, 1 errors, 0 skips", "1f/1p"),
        "node TAP":      ("TAP version 13\nok 1 - a\n# tests 13\n# pass 13\n# fail 0", "0f/13p"),
        "node TAP red":  ("# tests 5\n# pass 3\n# fail 2", "2f/3p"),
    }

    def test_the_new_rows_read_their_runners(self):
        for name, (out, want) in self.CASES.items():
            with self.subTest(runner=name):
                self.assertEqual(pg.runner_tally(out), want)

    def test_the_rows_that_already_worked_still_do(self):
        for out, want in (("2 failed, 7 passed in 0.05s", "2f/7p"),
                          ("  11 passing\n  1 failing", "1f/11p"),
                          ("12 examples, 1 failure, 2 pending", "1f/11p"),
                          ("Tests run: 12, Failures: 1, Errors: 0", "1f/11p")):
            with self.subTest(out=out[:24]):
                self.assertEqual(pg.runner_tally(out), want)

    def test_a_split_shape_runner_cannot_borrow_another_ones_failure_line(self):
        """mocha and node both print pass and fail on separate lines. Keyed by row name so the
        second one added cannot silently read the first one's pattern."""
        self.assertEqual(pg.runner_tally("# pass 4\n# fail 1"), "1f/4p")
        self.assertEqual(pg.runner_tally("4 passing\n1 failing"), "1f/4p")

    def test_plain_go_test_still_refuses_to_count_packages(self):
        """A number cria cannot read as TESTS is not a tally — unchanged."""
        self.assertEqual(pg.runner_tally("ok  \tpkg\t0.01s"), "")


class NodesOwnRunnerIsARunnerTests(unittest.TestCase):
    def test_node_dash_dash_test_is_a_test_command(self):
        d = pc.classify_command("node --test tests/*.js")
        self.assertEqual(d.kind, pc.ProbeKind.TEST)

    def test_bare_node_test_flag_counts(self):
        self.assertEqual(pc.classify_command("node --test").kind, pc.ProbeKind.TEST)

    def test_running_a_program_with_node_is_not_a_test(self):
        self.assertEqual(pc.classify_command("node server.js").kind, pc.ProbeKind.UNKNOWN)

    def test_node_check_is_not_a_test(self):
        """`node --check` is the syntax floor, a different kind entirely."""
        self.assertEqual(pc.classify_command("node --check a.js").kind, pc.ProbeKind.UNKNOWN)



class AnErrorIsNotAPassTests(unittest.TestCase):
    """Only JUnit's row read the runner's ERROR count, and a run with errors read as green.

    Ran each runner with a test that raises rather than asserts:

        pytest    `1 failed, 1 passed, 1 error`                     -> 0f/1p
        minitest  `2 runs, 1 assertions, 0 failures, 1 errors`      -> 0f/2p
        phpunit   `Tests: 3, Assertions: 2, Errors: 1`              -> 0f/3p
        surefire  `Tests run: 5, Failures: 0, Errors: 2`            -> 2f/3p   (the only right one)

    Every wrong one starts `0f/`, which `_checks_superseded_by_coder_run` reads as a clean coder run
    and uses to DROP cria's real cached findings; `gate_passing_tests` over-counts by the same
    amount. The `0 failures, N errors` shape occurs 1,749 times across 9 sessions in the captures.
    """

    ERRORS = {
        "pytest":            ("1 failed, 1 passed, 1 error in 0.02s", "2f/1p"),
        "pytest error only": ("2 passed, 1 error in 0.02s", "1f/2p"),
        "minitest":          ("2 runs, 1 assertions, 0 failures, 1 errors, 0 skips", "1f/1p"),
        "phpunit":           ("Tests: 3, Assertions: 2, Errors: 1.", "1f/2p"),
        "phpunit both":      ("Tests: 5, Assertions: 5, Errors: 1, Failures: 2.", "3f/2p"),
        "rspec":             ("3 examples, 0 failures, 1 error occurred outside of examples", "1f/2p"),
        "junit":             ("Tests run: 5, Failures: 0, Errors: 2, Skipped: 0", "2f/3p"),
    }
    CLEAN = {
        "pytest":   ("===== 7 passed in 0.05s =====", "0f/7p"),
        "minitest": ("9 runs, 9 assertions, 0 failures, 0 errors, 0 skips", "0f/9p"),
        "phpunit":  ("Tests: 3, Assertions: 3, Failures: 1.", "1f/2p"),
        "rspec":    ("12 examples, 0 failures", "0f/12p"),
    }

    def test_an_errored_run_never_starts_with_zero_failures(self):
        from cria.probeparse import runner_tally
        for name, (text, want) in self.ERRORS.items():
            with self.subTest(runner=name):
                got = runner_tally(text)
                self.assertEqual(got, want)
                self.assertFalse(got.startswith("0f/"), "an errored run must not read as clean")

    def test_a_genuinely_clean_or_failing_run_is_unchanged(self):
        from cria.probeparse import runner_tally
        for name, (text, want) in self.CLEAN.items():
            with self.subTest(runner=name):
                self.assertEqual(runner_tally(text), want)

    def test_the_coder_run_supersede_check_sees_the_difference(self):
        """The consumer that made this expensive: `0f/` is what lets a coder's own run drop cria's
        cached findings."""
        from cria.probeparse import runner_tally
        self.assertTrue(runner_tally("9 runs, 9 assertions, 0 failures, 0 errors, 0 skips")
                        .startswith("0f/"))
        self.assertFalse(runner_tally("2 runs, 1 assertions, 0 failures, 1 errors, 0 skips")
                         .startswith("0f/"))


if __name__ == "__main__":
    unittest.main()
