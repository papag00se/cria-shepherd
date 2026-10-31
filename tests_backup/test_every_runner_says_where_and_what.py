"""Three runners printed a location and a message, and cria reported neither.

`parse_runner_locations` reads the places a TEST runner puts its failure when the shape is not
`file:line: message`. It had rows for cargo, rspec, phpunit, minitest and plain ruby — and none for
JavaScript or the JVM, the two ecosystems whose traces are the most structured of all.

Ran each of them:

    node --test   `location: '/w/t.test.js:3:1'` in TAP-YAML, plus the message under `error: |-`
                  -> ZERO findings, and the summary was `exited 1: name: 'AssertionError'` — a
                  classification, picked bottom-up, while "Expected values to be strictly equal:
                  5 !== 6" sat three lines above it.

    JUnit 4.13    `at pipeline.ImporterTest.adds(ImporterTest.java:14)`
                  -> ZERO findings. The note beside the maven rows says its console output "carries
                  NO location whatsoever", which is true of the `Failed tests:` summary line and
                  false of the trace printed beside it by java, gradle and surefire 3.

    phpunit 9.6   a GREEN run prints `OK (2 tests, 2 assertions)` and no `Tests:` row at all
                  -> no tally, so `gate_passing_tests` returned -1 and `passing_test_regression`
                  — the only detector that sees a coder delete a passing test — was structurally
                  silent for PHP.

Two shape rules carry the JVM and TAP cases, and neither is a list of frameworks:

* a JVM stack is INNERMOST-FIRST, so the frames above the test's own belong to the framework —
  `at org.junit.Assert.fail(Assert.java:88)` is the first line printed and the one the coder can do
  nothing about. `_FOREIGN_FRAME` cannot help: it reads paths, and a JVM frame carries a bare
  basename. The rule is "the last frame of the trace".
* a QUOTED TAP-YAML scalar or a block indicator classifies the failure; it does not describe it.
  `failureType: 'testCodeFailure'` and `name: 'AssertionError'` both carry a diagnostic word and say
  nothing. Kept narrow: minitest's `Expected: 12.0` is the same `key: value` shape and IS the
  diagnosis.
"""

import unittest

from cria import probeparse as pp

NODE_TAP = """TAP version 13
not ok 1 - adds two numbers
  ---
  duration_ms: 1.4
  location: '/w/lib/cart.test.js:12:3'
  failureType: 'testCodeFailure'
  error: |-
    Expected values to be strictly equal:
    5 !== 6
  code: 'ERR_ASSERTION'
  name: 'AssertionError'
  ...
# tests 1
# pass 0
# fail 1
"""

JUNIT = """[ERROR] Tests run: 1, Failures: 1, Errors: 0, Skipped: 0
[ERROR] adds(pipeline.ImporterTest)  Time elapsed: 0.01 s  <<< FAILURE!
java.lang.AssertionError: expected:<2> but was:<3>
\tat org.junit.Assert.fail(Assert.java:88)
\tat org.junit.Assert.failNotEquals(Assert.java:834)
\tat pipeline.ImporterTest.adds(ImporterTest.java:14)
"""


def _parse(cmd, out):
    return pp.parse_output(cmd, pp.family_of(cmd), 1, out, "")


class NodesOwnRunnerIsReadTests(unittest.TestCase):
    def test_the_location_is_found(self):
        f = _parse("node --test", NODE_TAP).findings
        self.assertEqual([(x.file, x.line) for x in f], [("/w/lib/cart.test.js", 12)])

    def test_the_message_is_the_assertion_not_its_classification(self):
        msg = _parse("node --test", NODE_TAP).findings[0].message
        self.assertIn("Expected values to be strictly equal", msg)
        self.assertNotIn("testCodeFailure", msg)
        self.assertNotIn("ERR_ASSERTION", msg)

    def test_a_quoted_tap_field_is_never_the_diagnosis(self):
        for line in ("failureType: 'testCodeFailure'", "code: 'ERR_ASSERTION'",
                     "name: 'AssertionError'", "error: |-"):
            with self.subTest(line=line):
                self.assertFalse(pp._says_what_went_wrong(line))

    def test_a_runners_own_expected_line_still_is(self):
        """Narrow on purpose — minitest's is the same shape and IS the diagnosis."""
        for line in ("Expected: 12.0", "Actual: 0.0", "expected:<3> but was:<4>"):
            with self.subTest(line=line):
                self.assertTrue(pp._says_what_went_wrong(line))


class TheJvmTraceIsReadFromTheEndTests(unittest.TestCase):
    def test_the_test_s_own_frame_is_the_finding(self):
        f = _parse("mvn -q test", JUNIT).findings
        self.assertEqual([(x.file, x.line) for x in f], [("ImporterTest.java", 14)])

    def test_the_frameworks_frames_are_not_reported(self):
        self.assertNotIn("Assert.java",
                         " ".join(x.file for x in _parse("mvn -q test", JUNIT).findings))

    def test_the_message_is_the_assertion(self):
        self.assertIn("expected:<2> but was:<3>", _parse("mvn -q test", JUNIT).findings[0].message)


class PhpunitsGreenRunIsCountableTests(unittest.TestCase):
    def test_a_passing_suite_reports_its_tally(self):
        self.assertEqual(pp.runner_and_tally("OK (2 tests, 2 assertions)"), ("phpunit", "0f/2p"))

    def test_a_failing_suite_is_unchanged(self):
        self.assertEqual(pp.runner_and_tally("Tests: 3, Assertions: 2, Failures: 1."),
                         ("phpunit", "1f/2p"))

    def test_the_regression_detector_can_now_see_php(self):
        """`passing_test_regression` needs a passing COUNT; -1 means the runner said nothing."""
        from cria import proberun
        res = pp.parse_output("vendor/bin/phpunit", "", 0, "OK (9 tests, 9 assertions)", "")
        report = proberun.ProbeReport(project_type=["php"], selected=[], results=[res])
        self.assertEqual(res.tally, "0f/9p")
        del report


if __name__ == "__main__":
    unittest.main()
