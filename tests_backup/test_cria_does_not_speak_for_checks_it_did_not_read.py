"""cria says which of green-or-never-ran happened, and no module speaks for checks it never read.

THREE INSTANCES OF ONE SHAPE, all found by the application sweep.

`guard_gate_verdict` returns None for a GREEN gate and for a gate that COULD NOT RUN. Two of its
three callers hardcoded "The repo's automated checks pass". The prompt file has carried the honest
`never_ran` alternative since it was written and its own header records this exact incident — the fix
reached one caller of three. Measured: the passing wording shipped 80 times, twice in a prompt whose
newest check block showed failing tests; `never_ran` fired zero times.

Both live-execution markers ended "Everything else the checks cover passed" — a claim about the
repo's checks, from a module that never reads them. Caught 37 KB below a Java COMPILATION ERROR in
the same prompt.

And two judge prompts still asked for an executable next step, which is the judge choosing the
implementation (#2: cria never authors the coder's work). Yesterday's fix landed in one file of three.
"""

import unittest

from cria import loop, prompts


class Gs:
    last_gate_ran = False


class TheCheckStateSaysWhichHappenedTests(unittest.TestCase):
    def test_a_gate_that_ran_says_the_checks_passed(self):
        gs = Gs()
        gs.last_gate_ran = True
        self.assertEqual(loop._check_state_words(gs),
                         prompts.load_map("done_check_state")["passed"])

    def test_a_gate_that_could_not_run_says_so(self):
        words = loop._check_state_words(Gs())
        self.assertEqual(words, prompts.load_map("done_check_state")["never_ran"])
        self.assertIn("could NOT be run", words)

    def test_a_state_object_without_the_field_fails_to_the_honest_wording(self):
        """Fail safe: the unknown case must never claim a pass."""
        class Bare:
            pass
        self.assertIn("could NOT", loop._check_state_words(Bare()))

    def test_no_caller_hardcodes_the_passing_wording(self):
        """STRUCTURAL, deliberately: the claim is "no OTHER spot in this module reaches for the
        passing wording directly" — there is no caller to drive, only an absence across the whole
        file, which only a source scan can see. `_check_state_words` (tested above) is the one
        legitimate reader; this guards that a second one never grows back beside it, the exact
        shape of the original bug (two of three callers had their own copy)."""
        import inspect
        src = inspect.getsource(loop)
        self.assertNotIn('load_map("done_check_state")["passed"]', src,
                         "a caller is asserting a pass it has no evidence for")


class AJudgeNamesTheGapAndNotTheFixTests(unittest.TestCase):
    """The rule is about a class of prompt, so this checks every judge prompt that has the field —
    an instance test is how the first two of three sites survived."""

    FIELDS = (("satisfaction", "proposed_fix"), ("verify", "proposed_fix"),
              ("verify_tools", "verdict_fix"))

    def test_none_of_them_asks_for_a_command_or_an_action(self):
        for name, field in self.FIELDS:
            text = prompts.load(name) if name != "verify_tools" else prompts.load_map(name)[field]
            low = text.lower()
            for banned in ("executable next step", "imperative next action",
                           "exact known command", "next action the coder can perform"):
                self.assertNotIn(banned, low, f"{name}: {banned}")

    def test_each_asks_it_to_NAME_the_missing_thing(self):
        for name, field in self.FIELDS:
            text = prompts.load(name) if name != "verify_tools" else prompts.load_map(name)[field]
            self.assertIn("name", text.lower(), name)
            self.assertIn("not how to make it true", text.lower(), name)


if __name__ == "__main__":
    unittest.main()
