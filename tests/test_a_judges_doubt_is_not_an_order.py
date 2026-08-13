"""cria put a judge's prose in the coder's mouth and called it an instruction.

When the completion check cannot confirm the task is done, cria renders the judge's `reason` under
"the task is NOT fully done yet:" and closed with "finish exactly what is called out above". A
verdict written to justify a `false` became a mandate.

    qwen35/ruby, 3/3 on its own suite, call 0367 -> 0368.
    cria:   "The zone_for method hardcodes \\"EU\\" to return \\"eu\\" instead of using the countries
             gem for all two-letter codes as required."
    coder:  "Let me fix the code to not hardcode \\"EU\\" but instead let the gem handle it."
    result: a 22/22 suite went to 2 failures — one lost check each.

17 occurrences, four languages, three models. Working code broken in five runs; 15 model-written
tests reverted.

WHAT IS NOT CHANGED, because it is the part that works. The verdict still BLOCKS: fail closed on
completion (#13), the critic still re-runs on EVERY green 'done' with no once-bound (e0da427 removed
that bound after a false 'done' shipped a dropped requirement), and the coder still may not declare
done or stop (#14). Many not-satisfied verdicts are correct, so the fix is "do not relay prose as an
order", never "distrust the verdict".

WHAT CHANGED. The reason is attributed to the check that made it, marked as an opinion about the
work rather than a verified fact, and the coder is told in as many words that it may leave correct
code alone and say why the report is wrong. And when the judge named no gap at all, cria says that
— it used to substitute "a deliverable the task named is missing, stubbed, or does not actually
work", a concrete finding nobody had made (#5b).
"""

import unittest

from cria import prompts


class TheReportIsAttributedNotCommandedTests(unittest.TestCase):
    def setUp(self):
        self.body = prompts.load("done_incomplete")

    def test_the_reason_is_named_as_a_report(self):
        self.assertIn("a completion check could not confirm", self.body)
        self.assertIn("It reported:", self.body)

    def test_it_is_called_an_opinion_not_a_fact(self):
        self.assertIn("not a verified fact and not an instruction", self.body)

    def test_the_mandate_sentence_is_gone(self):
        """The clause that converted a verdict into an order."""
        self.assertNotIn("finish exactly what is called out above", self.body)

    def test_the_coder_may_keep_correct_code(self):
        """The direct counter to the measured harm: a 22/22 suite edited down to 2 failures."""
        self.assertIn("leave your code as it is", self.body)
        self.assertIn("not required to change working code", self.body)

    def test_it_must_check_the_report_against_the_task(self):
        self.assertIn("Check it against the ORIGINAL task before you act on it", self.body)


class TheBlockIsStillClosedTests(unittest.TestCase):
    """Letting the coder disagree with the REASON must not let it disagree with the VERDICT."""

    def setUp(self):
        self.body = prompts.load("done_incomplete")

    def test_it_still_may_not_declare_done_or_stop(self):
        self.assertIn("Do NOT declare done", self.body)
        self.assertIn("or stop", self.body)

    def test_it_still_may_not_rationalise_a_missing_piece(self):
        self.assertIn("rationalize a missing piece as impossible", self.body)

    def test_it_still_re_reads_the_task_and_checks_every_deliverable(self):
        self.assertIn("re-read the ORIGINAL task", self.body)
        self.assertIn("every deliverable it named is present and genuinely works", self.body)

    def test_the_slots_still_exist(self):
        for slot in ("{{CHECK_STATE}}", "{{REASON}}", "{{EXEC_FINDING}}"):
            with self.subTest(slot=slot):
                self.assertIn(slot, self.body)

    def test_the_critic_still_has_no_once_bound(self):
        """e0da427 removed it after a false 'done' shipped a dropped requirement."""
        import inspect

        from cria import loop
        src = inspect.getsource(loop.Loop._done_critic_reason)
        self.assertNotIn("done_critiqued", src)
        self.assertIn("NO once-bound", src)


class NoGapNamedMeansNoGapClaimedTests(unittest.TestCase):
    def test_the_default_does_not_invent_a_finding(self):
        text = prompts.load("done_no_named_gap")
        self.assertNotIn("is missing, stubbed", text)
        self.assertIn("did not name which deliverable", text)

    def test_it_still_sends_the_coder_to_verify(self):
        text = prompts.load("done_no_named_gap")
        self.assertIn("one by one", text)
        self.assertIn("a check that actually runs", text)

    def test_both_call_sites_use_the_one_owner(self):
        import inspect

        from cria import loop
        for fn in (loop.Loop._done_critic_reason,):
            self.assertIn('prompts.load("done_no_named_gap")', inspect.getsource(fn))
        self.assertEqual(
            inspect.getsource(loop).count('prompts.load("done_no_named_gap")'), 2)

    def test_the_prompt_file_carries_no_comment_the_model_would_read(self):
        """prompts.load returns the file whole — a `#` note would ship to the model."""
        self.assertFalse(prompts.load("done_no_named_gap").lstrip().startswith("#"))


class TheRenderedResultReadsRightTests(unittest.TestCase):
    def test_a_named_gap_renders_as_a_report(self):
        out = prompts.render("done_incomplete",
                             reason="The CLI never prints the holder's address.",
                             check_state=prompts.load_map("done_check_state")["passed"],
                             exec_finding="")
        self.assertIn("It reported:\nThe CLI never prints the holder's address.", out)
        self.assertNotIn("{{", out)

    def test_an_unnamed_gap_renders_without_a_fabricated_one(self):
        out = prompts.render("done_incomplete",
                             reason=prompts.load("done_no_named_gap"),
                             check_state=prompts.load_map("done_check_state")["never_ran"],
                             exec_finding="")
        self.assertIn("did not name which deliverable", out)
        self.assertNotIn("{{", out)


if __name__ == "__main__":
    unittest.main()
