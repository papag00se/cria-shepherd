"""The repetition guard gave advice that inverts depending on whether the call worked.

Its note says the repeated call "has told you everything it can. Read what it already returned
above, or take a DIFFERENT action." That is true of a call that SUCCEEDED and is being repeated
pointlessly — the guard's original case.

It is false and harmful of a call that FAILED. A failed call told the model nothing, and there is no
answer above to read. Measured on the six-language battery, where the guard sent a model back to
re-read an error as though it were the result it wanted, and forbade the retry that would have
fixed it.

One guard, two failure modes, two different true sentences.

AND THE SPLIT IS ONLY AS GOOD AS WHAT COUNTS AS FAILED. See
`test_an_empty_body_is_NOT_a_known_failure`: an empty body was on that list, and calling a true
empty answer a failure cost twelve turns in a walked run.
"""
import unittest

from cria import denial, focustrim, prompts


def _result(body):
    return [{"role": "tool", "tool_call_id": "c1", "content": body}]


class TheNoteTellsTheTruthAboutWhatHappenedTests(unittest.TestCase):
    def test_a_successful_repeat_keeps_the_original_advice(self):
        self.assertFalse(focustrim._repeat_failed(_result("total: 48.58\nEXIT:0"), "c1"))
        t = prompts.render("trim_repeat_collapsed", n=3, tried="read_file(a.py)")
        self.assertIn("told you everything it can", t)
        self.assertIn("Read what it already returned", t)

    def test_a_failed_repeat_gets_the_other_sentence(self):
        t = prompts.render("trim_repeat_collapsed_failed", n=3, tried="read_file(ghost.py)")
        self.assertIn("failed the same way", t)
        self.assertIn("has not answered the question", t)
        self.assertNotIn("told you everything it can", t)

    def test_the_failed_note_does_not_send_it_back_to_the_error(self):
        t = prompts.render("trim_repeat_collapsed_failed", n=2, tried="x")
        self.assertIn("do not read its result as the answer", t)


class WhatCountsAsFailedTests(unittest.TestCase):
    def test_a_refusal_cria_authored(self):
        self.assertTrue(focustrim._repeat_failed(
            _result(denial.mark("that path is outside the workspace")), "c1"))

    def test_an_empty_body_is_NOT_a_known_failure(self):
        """This assertion used to read True, and it contradicted this file's own rule.

        `test_no_result_at_all_keeps_the_original_wording` states it: only a KNOWN failure changes
        the sentence. An empty body is not one — an empty file, a grep that matched nothing, a
        command that printed nothing are all answers the coder asked for and got.

        Measured cost of calling them failures, on orders-api-py x nemotron-elastic 1787270062:
        `orders/__init__.py` is 0 bytes, `read_file` returned it correctly, and cria answered "you
        have now made this exact call 12 times and it failed the same way every time … do not read
        its result as the answer". The model obeyed for twelve turns and, pushed by "use a different
        tool", called `view_image` on a `.py` file.

        The residual risk is a harness tool that fails silently with an empty body: it now gets the
        successful wording. That is the conservative direction this file already chose for the
        unknown case, and the other two discriminators — a cria-authored refusal and a nonzero
        `EXIT:` — still catch every failure cria can actually see."""
        self.assertFalse(focustrim._repeat_failed(_result("   "), "c1"))
        self.assertFalse(focustrim._repeat_failed(_result(""), "c1"))

    def test_a_nonzero_exit_from_the_lowered_command(self):
        self.assertTrue(focustrim._repeat_failed(_result("boom\nEXIT:2"), "c1"))

    def test_a_real_result_is_not_a_failure(self):
        self.assertFalse(focustrim._repeat_failed(_result("48.58\nEXIT:0"), "c1"))

    def test_output_that_MENTIONS_the_sentinel_is_not_the_shell_reporting_it(self):
        """The exit code is the LAST one, because a program can print that string itself — a log
        line, a test name, a here-doc. Read top-down, `grep -n EXIT: run.log` was a failed call
        whatever the shell said."""
        self.assertFalse(focustrim._repeat_failed(
            _result('run.log:14:EXIT:1\nrun.log:88:EXIT:3\nEXIT:0'), "c1"))
        self.assertTrue(focustrim._repeat_failed(
            _result('run.log:14:EXIT:0\nEXIT:1'), "c1"))

    def test_it_reads_the_sentinel_its_owner_writes(self):
        """One spelling, one parser: `proberun` composes the line and `proberun.scrape_exit` reads
        it. A second copy of the string here would drift out of step with a rename."""
        from cria import proberun
        self.assertTrue(focustrim._repeat_failed(
            _result("boom\n" + proberun.PROBE_EXIT_SENTINEL + "9"), "c1"))

    def test_no_result_at_all_keeps_the_original_wording(self):
        """Conservative: only a KNOWN failure changes the sentence."""
        self.assertFalse(focustrim._repeat_failed([], "c1"))


if __name__ == "__main__":
    unittest.main()
