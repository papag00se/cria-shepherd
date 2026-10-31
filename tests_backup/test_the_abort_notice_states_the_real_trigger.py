"""An abort notice names the arm that actually fired, and never claims a continuity cria destroyed.

Two faults, both walked on feed-pipeline-java x nemotron-elastic 1787436645.

`Detector.check` returned the same dict for both of its arms, so every abort was described to the
model as second-guessing. The four aborts in that run had marker densities of 2.50, 1.65, 1.28 and
0.73 per 1k against a threshold of 10.0 — not one was dense; every one hit the token ceiling — and
each was told "you hit N second-guessing phrases … Stop re-examining".

And the advice differs. "Just pick one and proceed — do not revisit the decision" is right for a model
circling a choice it can already make, and wrong for one circling because it has not read the thing it
needs. The model was mid-deliberation over a CSV library it had never opened when that landed;
`CSVParserBuilder`, an API that does not exist, appears in the very next turn.

Finally, an aborted turn is not written back into the conversation, so "continue from what you already
know" describes a context cria itself removed."""
import unittest

from cria import prompts, rumination

NOTICES = ("rumination_guard", "rumination_guard_degenerate",
           "rumination_guard_length", "rumination_guard_dead_stream")


class TheTriggerIsTheOneItHasTests(unittest.TestCase):
    def test_a_long_pass_reports_length_not_phrases(self):
        d = rumination.Detector(budget=16384)
        v = d.check("plain reasoning words here " * 900, 20_000)
        self.assertEqual(v["arm"], "length")

    def test_a_dense_pass_reports_second_guessing(self):
        d = rumination.Detector(budget=16384)
        v = d.check("actually wait let me reconsider hmm " * 200, 9_000)
        self.assertEqual(v["arm"], "second_guessing")

    def test_the_length_notice_blames_no_phrases(self):
        t = prompts.load("rumination_guard_length")
        self.assertNotIn("second-guessing", t)
        self.assertIn("tokens reasoning", t)


class NoNoticeClaimsAContinuityCriaRemovedTests(unittest.TestCase):
    def test_none_of_them_says_continue_from_what_you_know(self):
        for name in NOTICES:
            with self.subTest(notice=name):
                self.assertNotIn("continue from what you already know", prompts.load(name))

    def test_each_says_the_turn_did_not_survive(self):
        for name in NOTICES:
            with self.subTest(notice=name):
                self.assertIn("survive", prompts.load(name))


class NoNoticeForbidsLookingSomethingUpTests(unittest.TestCase):
    def test_none_of_them_bans_revisiting_a_decision_outright(self):
        for name in NOTICES:
            with self.subTest(notice=name):
                self.assertNotIn("do not revisit the decision", prompts.load(name))

    def test_the_two_that_stop_a_loop_name_reading_as_the_way_out(self):
        for name in ("rumination_guard", "rumination_guard_degenerate", "rumination_guard_length"):
            with self.subTest(notice=name):
                self.assertIn("tool", prompts.load(name))

    def test_the_model_never_reads_the_shim_s_name(self):
        for name in NOTICES:
            with self.subTest(notice=name):
                self.assertNotIn("cria", prompts.load(name).lower())


if __name__ == "__main__":
    unittest.main()
