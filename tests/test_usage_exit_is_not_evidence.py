"""A program that printed its usage line and refused was never exercised — say nothing about it.

maple-preview ran `python resolve_handle.py`, the script's argv guard rejected it, and cria reported
`⟦ctx:live-execution⟧ The delivered program was run and did not show the result it was meant to` —
a claim about the program drawn from a run that never reached the program's behaviour (rule 5b).
Shipped to the judge in both maple runs, and once to the coder.

WHAT THIS DOES NOT ASSERT (operator, 2026-08-08): that a command needs an argument. A program with
no arguments is a perfectly good program, and running one bare may be exactly what the task asked
for — that is a reason to run it, not a defect. The only signal read here is the PROGRAM'S OWN
REPLY: it printed its usage and exited nonzero. An earlier cut of this fix also swapped in a fuller
command from the README when the probe's ended at the program name; that presumed the bare command
was a mistake, which is the ada-handles task talking, and it was removed.
"""
import unittest

from cria import execcheck


class TheProgramsOwnReplyDecidesTests(unittest.TestCase):
    def test_usage_plus_nonzero_is_inconclusive(self):
        for out in ("usage: resolve_handle.py [-h] handle\nresolve_handle.py: error: required",
                    "Usage of ./resolver:\n  -handle string",
                    "Usage: cli <handle>\n\nOptions:\n  -h, --help"):
            self.assertTrue(execcheck._USAGE_LINE.search(out), out[:40])

    def test_a_crash_is_still_a_finding_about_the_program(self):
        out = "Traceback (most recent call last):\nNameError: name 'json' is not defined"
        self.assertIsNone(execcheck._USAGE_LINE.search(out))

    def test_the_word_usage_in_prose_output_is_not_a_usage_line(self):
        # must anchor to line start — a program that PRINTS the word is not refusing the call
        self.assertIsNone(execcheck._USAGE_LINE.search("Total disk usage: 4.2 GB\n"))
        self.assertIsNone(execcheck._USAGE_LINE.search("Reporting memory usage:\n" .replace("\n", " ")))

    def test_usage_with_exit_zero_is_untouched(self):
        """`prog --help` exits 0 and prints usage; that is the program working, not refusing."""
        self.assertTrue(execcheck._USAGE_LINE.search("usage: prog [-h]"))
        # the verdict branch is gated on code != 0 — pinned by reading the source contract
        import inspect
        src = inspect.getsource(execcheck.evaluate)
        self.assertIn("if code != 0 and _USAGE_LINE.search", src)


class NoAssumptionAboutArgumentsTests(unittest.TestCase):
    def test_the_probe_prompt_claims_nothing_about_argless_programs(self):
        from cria import prompts
        text = prompts.load("exec_intent")
        for claim in ("proves nothing", "only prints its usage line", "needs an argument"):
            self.assertNotIn(claim, text)
        self.assertIn("put that exact value in the command", text)   # what to DO still stands

    def test_cria_never_rewrites_the_probes_command(self):
        """The README-extension override was removed: cria runs the command it was given."""
        import inspect
        src = inspect.getsource(execcheck)
        self.assertNotIn("_readme_extension", src)


if __name__ == "__main__":
    unittest.main()
