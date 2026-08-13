"""cria refuses a 9,001-byte file read and let a command print 302,983 tokens.

`read_file` over `READ_INLINE_MAX` (9,000 bytes) is refused, with the coder told to grep or read a
line range instead. The coder's own `exec_command` had no bound at all — the guard was built for
cria's synthetic tools and the harness's shell was never on the same table.

Measured across the battery: **71 of 538 command results (13%) are larger than the limit cria
enforces on a file read**, and the harness had ALREADY blind-clipped 10 of them, stamping
"Warning: truncated output" — the silent truncation principle 5 exists to prevent, arriving through
a door cria was not watching.

The measured harm, gemma4's Java run: the coder wanted to know whether its importer crashed, ran it
over the 120,000-row feed with per-item printing, and got 879 lines back. That pushed the session
over the compaction trigger, which destroyed the notes of the step it had just finished. It then ran
the identical command six calls later.

A BOUND WITH A ROUTE, not a clip: both ends survive so an early failure and a final summary both
live, the loss is stated in bytes and lines, and the next action is named. The exec envelope is
kept — the exit code is the most load-bearing line in the result.
"""

import unittest

from cria import prompts, writeproxy
from cria.writeproxy import READ_INLINE_MAX, _bounded_exec_result


def result(n_lines: int, prefix: str = "SKU", exit_code: int = 0) -> str:
    body = "\n".join(f"{prefix}-{i:05d} imported ok" for i in range(n_lines))
    return f"Chunk ID: be2fc9\nWall time: 0.9s\nProcess exited with code {exit_code}\nOutput:\n{body}"


class AnOversizedResultIsBoundedTests(unittest.TestCase):
    def test_the_measured_case_shrinks(self):
        out = _bounded_exec_result(result(879))
        self.assertLess(len(out), READ_INLINE_MAX)

    def test_the_exit_code_survives(self):
        """The most load-bearing line in any command result."""
        out = _bounded_exec_result(result(900, exit_code=1))
        self.assertIn("Process exited with code 1", out)

    def test_both_ends_survive(self):
        """An early failure line and a final summary are the two places the answer sits."""
        out = _bounded_exec_result(result(900))
        self.assertIn("SKU-00000", out)
        self.assertIn("SKU-00899", out)

    def test_the_loss_is_stated_not_hidden(self):
        out = _bounded_exec_result(result(900))
        self.assertIn("not shown", out)
        self.assertIn("lines of output", out)
        self.assertRegex(out, r"[\d,]+ of [\d,]+ bytes not shown")

    def test_it_names_the_next_action(self):
        """A refusal with no route is how the read guard would have failed too."""
        out = _bounded_exec_result(result(900))
        for route in ("grep", "head -50", "> out.txt"):
            with self.subTest(route=route):
                self.assertIn(route, out)

    def test_it_says_not_to_just_re_run_it(self):
        """The measured run re-ran the identical command six calls later."""
        self.assertIn("Do not re-run it unfiltered", _bounded_exec_result(result(900)))


class WhatMustPassThroughUntouchedTests(unittest.TestCase):
    def test_a_small_result_is_identical(self):
        small = result(5)
        self.assertEqual(_bounded_exec_result(small), small)

    def test_a_result_at_the_limit_is_identical(self):
        """Same constant as the read guard — one owner for 'too big to hand over'."""
        body = "x" * (READ_INLINE_MAX - 100)
        r = f"Process exited with code 0\nOutput:\n{body}"
        self.assertEqual(_bounded_exec_result(r), r)

    def test_a_few_very_long_lines_are_left_alone(self):
        """Cutting by line would cut mid-line here, which is the lie the bound exists to avoid."""
        r = "Process exited with code 0\nOutput:\n" + "\n".join(["y" * 5000] * 4)
        self.assertEqual(_bounded_exec_result(r), r)

    def test_an_empty_result_is_untouched(self):
        self.assertEqual(_bounded_exec_result(""), "")

    def test_output_with_no_envelope_is_still_bounded(self):
        out = _bounded_exec_result("\n".join(f"line {i}" for i in range(2000)))
        self.assertLess(len(out), READ_INLINE_MAX)
        self.assertIn("not shown", out)


class ItUsesTheSameLimitAsTheReadGuardTests(unittest.TestCase):
    def test_one_owner_for_the_size(self):
        from cria import content_reduce
        self.assertEqual(READ_INLINE_MAX, content_reduce.INLINE_RESULT_MAX_BYTES)

    def test_the_note_lives_in_a_prompt_file(self):
        self.assertTrue(prompts.load_map("exec_output_bounded").get("note", "").strip())

    def test_the_note_never_names_the_program(self):
        self.assertNotIn("cria", prompts.load_map("exec_output_bounded")["note"].lower())


if __name__ == "__main__":
    unittest.main()
