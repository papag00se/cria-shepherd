"""The steer author is told which lines of the transcript are cria's own earlier output.

The author is handed one flat transcript containing real tool results, the coder's speculation and
cria's previous notes, with nothing distinguishing them. A prior steer re-entering as evidence is the
worst case, because it is a FEEDBACK LOOP: cria's wrong answer becomes the grounds for cria's next
wrong answer, with more confidence each round. One run read a claim out of that wall, treated it as
endpoint evidence, reversed a correct earlier directive and began a four-way flip-flop that cost 83
edits.

`_mark_own_notes` exists to break that loop, and it keyed on three markers cria injects and then
largely replaces — so it was rarely looking at anything. The continuation reframe is different in
kind: cria composes it and the harness stores it AS the conversation, so it is in the history by
construction.

Measured across one day, 1,926 real prompts: `⟦ctx:continuation⟧` in 526 of them, `⟦ctx:steer⟧` in
150, and the tag this function exists to add in **zero**.
"""

import unittest

from cria import indicators, loop, selfcompact


class EveryChannelCriaWritesIsLabelledTests(unittest.TestCase):
    TAG = "[EARLIER NOTE FROM THIS SYSTEM — not evidence]"

    def test_the_continuation_reframe_is_labelled(self):
        line = f"the task/context said: {loop.CONTINUATION_MARKER} what was done so far"
        self.assertIn(self.TAG, loop._mark_own_notes(line))

    def test_a_prior_steer_is_labelled(self):
        self.assertIn(self.TAG, loop._mark_own_notes("the task/context said: ⟦ctx:steer⟧ read cart.go"))

    def test_the_rollup_is_labelled(self):
        line = f"the task/context said: {selfcompact.SUMMARY_MARKER} earlier work"
        self.assertIn(self.TAG, loop._mark_own_notes(line))

    def test_the_completion_sentinel_is_labelled(self):
        line = f"the coder said: {indicators.SENTINEL} done"
        self.assertIn(self.TAG, loop._mark_own_notes(line))

    def test_every_marker_cria_injects_is_a_key(self):
        """The rule is about a CLASS — anything cria writes that can re-enter the history."""
        for mark in (loop.CONTINUATION_MARKER, selfcompact.SUMMARY_MARKER,
                     indicators.SENTINEL, "⟦ctx:steer⟧"):
            with self.subTest(mark=mark):
                self.assertIn(self.TAG, loop._mark_own_notes(f"x {mark} y"))


class TheCodersOwnWordsAreNotLabelledTests(unittest.TestCase):
    def test_a_tool_result_is_untouched(self):
        line = "→ exit 1: ./cart.go:58: undefined: decimal.NewFromFloat64"
        self.assertEqual(loop._mark_own_notes(line), line)

    def test_the_coders_prose_is_untouched(self):
        line = "the coder said: I think the import path is wrong"
        self.assertEqual(loop._mark_own_notes(line), line)

    def test_an_empty_session_is_returned_unchanged(self):
        self.assertEqual(loop._mark_own_notes(""), "")

    def test_only_the_matching_line_is_tagged(self):
        out = loop._mark_own_notes(
            f"the task/context said: {loop.CONTINUATION_MARKER} a\nthe coder said: b\n→ exit 0: c")
        self.assertEqual(out.count("EARLIER NOTE"), 1)


if __name__ == "__main__":
    unittest.main()
