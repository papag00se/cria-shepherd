"""The supersede that stops cria restating cleared failures was inert in three languages.

`_checks_superseded_by_coder_run` exists because the coder has its own shell: it runs the suite
itself, cria's gate cache does not know, and cria kept asserting failures the disk had already
cleared. Its trigger was `\\btest[\\w.]*\\.\\w+:\\d+:` — a path whose basename STARTS with "test".

Checked against real findings from the six-language battery:

    tests/test_db.py:12:            matched
    test/test_rates.rb:41:          matched
    tests/handle-lookup.test.js:8:  matched
    cart_test.go:22:                MISSED
    src/test/java/OrderTest.java:31: MISSED
    tests/cli.rs:22:                MISSED

Go, Java and Rust name test files by SUFFIX, so the guard could never fire for them. Its own
consumer, `probegate.runner_tally`, is properly generalised across twelve runners; the trigger in
front of it was keyed to one naming habit. Both halves now defer to owners that already know:
`probediscovery.TEST_CONVENTIONS` for what a test file is called in each language, and
`runner_tally` for what a failure tally looks like.
"""
import unittest

from cria import loop


class EveryLanguagesTestFilesAreRecognisedTests(unittest.TestCase):
    PATHS = ("tests/test_db.py:12: AssertionError",
             "test/test_rates.rb:41: Failure",
             "tests/handle-lookup.test.js:8: expected",
             "cart_test.go:22: want 48.58",
             "src/test/java/OrderTest.java:31: expected:<1> but was:<2>",
             "tests/cli.rs:22: assertion failed",
             "spec/thing_spec.rb:9: error")

    def test_a_failing_test_is_seen_whatever_the_language_calls_it(self):
        for line in self.PATHS:
            with self.subTest(line=line):
                self.assertTrue(loop._is_test_finding(line))

    def test_a_runner_tally_alone_is_enough(self):
        for out in ("9 runs, 9 assertions, 2 failures, 0 errors",
                    "2 failed, 7 passed in 0.05s",
                    "--- FAIL: TestSubtotal",
                    "# pass 3\n# fail 2"):
            with self.subTest(out=out[:22]):
                self.assertTrue(loop._is_test_finding(out))

    def test_an_ordinary_lint_finding_is_not_a_test_finding(self):
        """The guard drops cria's cached TEST failures; it must not drop a real lint finding."""
        self.assertFalse(loop._is_test_finding("app.py:3: undefined name 'x'"))
        self.assertFalse(loop._is_test_finding("src/main.rs:9: unused variable"))

    def test_nothing_is_nothing(self):
        self.assertFalse(loop._is_test_finding(""))
        self.assertFalse(loop._is_test_finding(None))

    def test_a_test_directory_counts_even_with_an_unconventional_filename(self):
        self.assertTrue(loop._is_test_finding("tests/helpers.rb:4: boom"))


if __name__ == "__main__":
    unittest.main()
