"""Every test runner's tally, and every language's unused-name warning — not just Python's.

cria is task- and language-agnostic; the ada-handles matrix is one row. Two mechanisms were not:

1. THE TALLY. `runner_tally` knew pytest, unittest and cargo. The PASSED count is a coverage signal
   — a test that SKIPS rather than fails leaves the exit code at 0 and drops out of it — and it is
   the only thing standing between "the suite is self-contained" (`_offline_fact`) and "one test
   quietly stepped aside". For a Go, Java, JS, Ruby, Elixir, PHP or .NET suite there was no count,
   so a whole suite could step aside unnoticed and a coder's own green run was never recognised
   (`_checks_superseded_by_coder_run`).

2. THE ADVISORY LIST. Seven phrases covered pyflakes/ruff/flake8/eslint/tsc. The same dead local
   that is advisory in Python gated a step in Rust, Ruby, PHP, C# or Java.

THE RULE FOR BOTH, and the reason Go appears on opposite sides of it: a number counts only if it
counts TESTS, and a warning is advisory only where the program still RUNS. `go test` without `-v`
prints one verdict per PACKAGE, and a package whose only live test calls t.Skip() still prints `ok`
— not a tally. Go's `declared and not used` is a COMPILE ERROR — not advisory. Same language, both
rules applied by what is actually true of it.
"""
import unittest

from cria.probegate import runner_tally
from cria.probeparse import is_advisory


class EveryRunnerIsCountedTests(unittest.TestCase):
    CASES = {
        "pytest":        ("=========== 2 failed, 7 passed in 0.05s ============", "2f/7p"),
        "pytest-skip":   ("7 passed, 2 skipped in 0.12s", "0f/7p"),
        "cargo-2-bins":  ("test result: ok. 3 passed; 0 failed; 1 ignored\n"
                          "test result: FAILED. 1 passed; 2 failed; 0 ignored", "2f/4p"),
        "jest":          ("Tests:       1 failed, 11 passed, 12 total", "1f/11p"),
        "jest-skip":     ("Tests:       2 skipped, 10 passed, 12 total", "0f/10p"),
        "junit":         ("Tests run: 12, Failures: 1, Errors: 0, Skipped: 2", "1f/11p"),
        "junit-modules": ("Tests run: 4, Failures: 0, Errors: 0\n"
                          "Tests run: 6, Failures: 2, Errors: 1", "3f/7p"),
        "gradle":        ("12 tests completed, 1 failed", "1f/11p"),
        "rspec":         ("12 examples, 1 failure, 2 pending", "1f/11p"),
        "exunit":        ("3 doctests, 12 tests, 1 failure", "1f/11p"),
        "phpunit":       ("Tests: 12, Assertions: 30, Failures: 1", "1f/11p"),
        "dotnet":        ("Failed:     1, Passed:    12, Skipped:     0, Total:    13", "1f/12p"),
        "mocha":         ("  11 passing (2s)\n  1 failing", "1f/11p"),
        "go-verbose":    ("--- PASS: TestA (0.00s)\n--- FAIL: TestB (0.01s)\n"
                          "--- PASS: TestC (0.00s)", "1f/2p"),
        "unittest":      ("Ran 5 tests in 0.01s\n\nOK", "5ran/OK"),
        "unittest-fail": ("Ran 5 tests in 0.01s\n\nFAILED (failures=1)", "5ran/FAIL"),
    }

    def test_each_runner(self):
        for name, (text, want) in self.CASES.items():
            with self.subTest(runner=name):
                self.assertEqual(runner_tally(text), want)

    def test_a_green_run_is_recognisable_as_green(self):
        """`_checks_superseded_by_coder_run` keys on the `0f/` prefix — every runner must reach it."""
        for text in ("12 passed in 0.1s", "Tests:       12 passed, 12 total",
                     "Tests run: 12, Failures: 0, Errors: 0", "12 examples, 0 failures",
                     "12 tests, 0 failures", "--- PASS: TestA (0.0s)",
                     "test result: ok. 12 passed; 0 failed; 0 ignored"):
            with self.subTest(text=text[:34]):
                self.assertTrue(runner_tally(text).startswith("0f/"), runner_tally(text))

    def test_prose_that_merely_mentions_tests_is_not_a_tally(self):
        for text in ("I will run the tests now", "the tests passed earlier", "12 tests to write",
                     "hello world", ""):
            with self.subTest(text=text[:30]):
                self.assertEqual(runner_tally(text), "")


class PackagesAreNotTestsTests(unittest.TestCase):
    """Plain `go test` prints one verdict per PACKAGE. A package whose only live test calls t.Skip()
    still prints `ok`, so returning a package count would let _offline_fact claim "nothing in them
    reaches the real service" on evidence that cannot support it. No count → the weaker sentence."""

    def test_plain_go_test_yields_no_tally(self):
        self.assertEqual(runner_tally("ok  \thandles/pkg\t0.213s"), "")
        self.assertEqual(runner_tally("FAIL\thandles/pkg\t0.213s"), "")

    def test_but_go_test_v_does(self):
        self.assertEqual(runner_tally("--- PASS: TestA (0.0s)\nok  \thandles/pkg\t0.2s"), "0f/1p")


class UnusedIsAdvisoryWhereTheProgramStillRunsTests(unittest.TestCase):
    ADVISORY = {
        "rustc-variable":  "warning: unused variable: `x`",
        "rustc-import":    "unused import: `std::fmt`",
        "rustc-dead":      "field `name` is never read",
        "rubocop":         "Lint/UselessAssignment: Useless assignment to variable - x",
        "csharp-CS0219":   "The variable 'x' is assigned a value but never used",
        "phpstan":         "Variable $x was declared but never used",
        "clang-param":     "unused parameter 'argc' [-Wunused-parameter]",
        "pyflakes":        "'os' imported but unused",
        "tsc-TS6133":      "'x' is declared but its value is never read.",
        "eslint":          "'x' is assigned a value but never used",
    }

    def test_each_is_advisory(self):
        for name, msg in self.ADVISORY.items():
            with self.subTest(linter=name):
                self.assertTrue(is_advisory(msg), msg)


class GosUnusedIsACompileErrorAndMustStillGateTests(unittest.TestCase):
    """The same English, the opposite verdict, because Go refuses to build. A phrase is advisory
    only where the program still runs — that is the test any new entry must pass."""

    def test_go_unused_variable_gates(self):
        self.assertFalse(is_advisory("./main.go:7:2: declared and not used: x"))

    def test_go_unused_import_gates(self):
        self.assertFalse(is_advisory('./main.go:4:2: "fmt" imported and not used'))

    def test_real_errors_still_gate(self):
        for msg in ("undefined name 'requests'", "cannot find symbol: method resolve()",
                    "SyntaxError: invalid syntax", "NameError: name 'json' is not defined"):
            with self.subTest(msg=msg[:34]):
                self.assertFalse(is_advisory(msg))


if __name__ == "__main__":
    unittest.main()
