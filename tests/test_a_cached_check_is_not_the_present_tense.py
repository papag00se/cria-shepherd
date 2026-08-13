"""cria replayed a cached gate result to the steer author as current ground truth, with no age.

    qwen35/go 0034. Steer author: "The repo checks confirm: - `sum.Add` is being called with 2
    arguments but expects 1" — while the file quoted in the SAME prompt reads
    `sum.Add(price.Mul(quantity))`. The coder's own build one call later: "Build succeeded".

The author was reading a block headed GROUND TRUTH and ranked #1 for authority, told flatly to
"Trust it", describing code the coder had already replaced. 10 occurrences, four models, three
languages; two authors said in their own thinking that the block looked stale and deferred to it
anyway.

TWO HALVES, BOTH ALREADY HALF-BUILT IN CRIA.

1. The age. cria computes "they last ran X, and <file> has been written since" for the CODER-facing
   repeat prompt and did not carry it into the AUTHOR's block. Same fact, same session, one reader
   short.

2. The supersede. `_checks_superseded_by_coder_run` drops a cached finding the coder's own newer
   run has cleared — but it was gated on a PHRASE LIST over the finding's text ("does this look like
   a test finding?"), which covered pytest and minitest and missed go, java and rust. Three of the
   six battery families, and the ones where a stale error costs most.

   The question is not how the finding is spelled, it is what the newer run PROVES. A runner that
   must build before it can pass settles a compile finding too: `cargo test` cannot print "test
   result: ok" over an unresolved import. An interpreted runner cannot — a green pytest says nothing
   about an unused import pyflakes flagged. That is a property of the runner, read off the output
   cria is holding (#12), not of the prose cria rendered.
"""

import unittest

from cria import loop, probegate, prompts


def gate(finding):
    return {"role": "tool", "tool_call_id": "g1",
            "content": probegate.SECTION_PREFIX + "probe-0___\n" + finding}


def coder_ran(output):
    return {"role": "tool", "tool_call_id": "c9", "content": output}


def wrote(path):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": "w1", "type": "function",
                            "function": {"name": "write_file",
                                         "arguments": '{"path": "%s"}' % path}}]}


class WhatAGreenRunActuallyProvesTests(unittest.TestCase):
    def supersede(self, finding, coder_output):
        return loop._checks_superseded_by_coder_run([gate(finding), coder_ran(coder_output)], finding)

    def test_a_compiled_languages_build_error_is_cleared_by_its_own_green_suite(self):
        """`cargo test` cannot report ok over an unresolved import. This missed before."""
        self.assertEqual(
            self.supersede("error[E0432]: unresolved import `toml::Rows`",
                           "test result: ok. 6 passed; 0 failed"), "0f/6p")

    def test_a_java_compile_error_is_cleared_by_a_green_junit_run(self):
        self.assertTrue(
            self.supersede("Importer.java:31: error: cannot find symbol",
                           "Tests run: 9, Failures: 0, Errors: 0, Skipped: 0"))

    def test_a_test_failure_is_still_cleared_by_an_interpreted_runner(self):
        self.assertEqual(
            self.supersede("tests/test_a.py:44: AssertionError\n1 failed, 4 passed",
                           "5 passed in 0.02s"), "0f/5p")

    def test_minitest_too(self):
        self.assertEqual(
            self.supersede("test/test_rates.rb:15: Expected 0.0\n7 runs, 7 assertions, 1 failures",
                           "7 runs, 7 assertions, 0 failures, 0 errors, 0 skips"), "0f/7p")

    def test_a_lint_finding_is_NOT_cleared_by_a_green_interpreter(self):
        """Preserved exactly: an unused import fails pyflakes and runs fine."""
        self.assertEqual(self.supersede("app.py:3:1: unused import os", "5 passed in 0.02s"), "")

    def test_a_red_run_clears_nothing(self):
        self.assertEqual(
            self.supersede("tests/test_a.py:44: AssertionError\n1 failed, 4 passed",
                           "2 failed, 3 passed in 0.02s"), "")

    def test_a_run_BEFORE_the_gate_is_not_newer_information(self):
        msgs = [coder_ran("5 passed in 0.02s"),
                gate("tests/test_a.py:44: AssertionError\n1 failed, 4 passed")]
        self.assertEqual(loop._checks_superseded_by_coder_run(msgs, "tests/test_a.py:44: AssertionError"), "")


class TheRunnerIsReadNotGuessedTests(unittest.TestCase):
    def test_the_tally_carries_its_runners_name(self):
        self.assertEqual(probegate.runner_and_tally("test result: ok. 6 passed; 0 failed"),
                         ("cargo", "0f/6p"))
        self.assertEqual(probegate.runner_and_tally("5 passed in 0.02s")[0], "pytest")

    def test_unknown_output_names_nothing(self):
        self.assertEqual(probegate.runner_and_tally("hello world"), ("", ""))

    def test_the_two_readers_agree(self):
        """runner_tally and runner_and_tally read the same rows, so adding a runner reaches both."""
        for text in ("5 passed in 0.02s", "test result: ok. 6 passed; 0 failed",
                     "7 runs, 7 assertions, 0 failures, 0 errors, 0 skips", "hello"):
            with self.subTest(text=text[:24]):
                self.assertEqual(probegate.runner_and_tally(text)[1], probegate.runner_tally(text))

    def test_the_build_first_set_holds_only_compiled_runners(self):
        for r in ("cargo", "junit", "gradle", "dotnet", "go"):
            self.assertIn(r, probegate.COMPILES_FIRST)
        for r in ("pytest", "rspec", "minitest", "jest", "mocha", "node"):
            self.assertNotIn(r, probegate.COMPILES_FIRST)


class TheAuthorIsToldHowOldTheBlockIsTests(unittest.TestCase):
    def test_the_slot_exists(self):
        self.assertIn("{{CHECKS_AGE}}", prompts.load("steer_diagnose_user"))

    def test_trust_it_is_qualified_by_the_date(self):
        body = prompts.load("steer_diagnose_user")
        self.assertNotIn("real output from real runs. Trust it.", body)
        self.assertIn("Trust the words; check the DATE", body)

    def test_it_says_the_coders_own_later_run_wins(self):
        self.assertIn("the coder's own later run of the same check outranks them",
                      prompts.load("steer_diagnose_user"))

    def test_the_age_line_names_the_files(self):
        line = prompts.fill(prompts.load_map("steer_checks_age")["written"], files="cart.go, sum.go")
        self.assertIn("cart.go, sum.go", line)
        self.assertIn("not as it is now", line)

    def test_the_author_call_fills_it(self):
        import inspect
        self.assertIn("checks_age=", inspect.getsource(loop))

    def test_the_ordering_of_authority_is_otherwise_unchanged(self):
        """The 1-5 ranking is load-bearing; only the caveat on #1 moved."""
        body = prompts.load("steer_diagnose_user")
        for line in ("2. THE FILES ON DISK", "3. THE CODING SESSION",
                     "4. THE CODER'S OWN WORDS AND THINKING"):
            with self.subTest(line=line):
                self.assertIn(line, body)


class TheGateAnchorStillLocatesTheGateTests(unittest.TestCase):
    """Both halves depend on 'since the last gate' meaning something. The marker survives in the RAW
    body these read; it is only the cleaned model-facing copy that has it stripped."""

    def test_only_writes_after_the_gate_are_counted(self):
        msgs = [wrote("old.py"), gate("cart.go:12: undefined: foo"), wrote("cart.go")]
        self.assertEqual(loop._writes_since_last_gate(msgs), ["cart.go"])

    def test_the_cleaned_copy_is_what_loses_the_marker(self):
        cleaned = probegate.clean_gate_results([gate("2 failed, 7 passed in 0.05s")])
        self.assertNotIn(probegate.SECTION_PREFIX, cleaned[0].get("content") or "")


if __name__ == "__main__":
    unittest.main()
