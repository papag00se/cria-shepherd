"""The repetition guard gave advice that inverts depending on whether the call worked.

Its note says the repeated call "has told you everything it can. Read what it already returned
above, or take a DIFFERENT action." That is true of a call that SUCCEEDED and is being repeated
pointlessly — the guard's original case.

It is false and harmful of a call that FAILED. A failed call told the model nothing, and there is no
answer above to read. Measured on the six-language battery, where the guard sent a model back to
re-read an error as though it were the result it wanted, and forbade the retry that would have
fixed it.

One guard, two failure modes, two different true sentences.
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

    def test_an_empty_body(self):
        self.assertTrue(focustrim._repeat_failed(_result("   "), "c1"))

    def test_a_nonzero_exit_from_the_lowered_command(self):
        self.assertTrue(focustrim._repeat_failed(_result("boom\nEXIT:2"), "c1"))

    def test_a_real_result_is_not_a_failure(self):
        self.assertFalse(focustrim._repeat_failed(_result("48.58\nEXIT:0"), "c1"))

    def test_no_result_at_all_keeps_the_original_wording(self):
        """Conservative: only a KNOWN failure changes the sentence."""
        self.assertFalse(focustrim._repeat_failed([], "c1"))


if __name__ == "__main__":
    unittest.main()
