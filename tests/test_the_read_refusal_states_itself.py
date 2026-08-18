"""The read refusal predicted a truncation that, at the size it fires, nobody would have performed.

Two live steers told the coder its read would be cut:

    {{PATH}} is large — reading it whole would be truncated (you'd get the head and tail with the
    middle cut, and act on a false view)

    That line range of {{PATH}} is too large to return in one read — the harness would truncate it
    mid-way and you'd act on a partial view

`READ_INLINE_MAX` is **9,000 bytes**. The truncation this cites was observed once, and the recorded
cut was at **~20,707 tokens** — roughly nine times higher. So at the threshold where the refusal
actually fires, nothing would have been truncated by anyone: cria declined to hand the bytes over,
which is a fact about cria, and the sentence reported it as a fact about the world.

Rule 5b names this in those words — *"Do not turn internal limits, remembered flags, partial
matches, or assumptions into world facts."* And it is the same defect `_spill_read_command` was
already fixed for one function over, whose docstring reads: *"cria says it about its OWN read guard,
which is a claim about cria dressed as a claim about the world."* That fix was applied to the spill
path only; these two carriers were missed.

**The refusal itself is not the defect and does not change.** cria genuinely will not return that
much in one piece, and the routes it offers — grep, a line range — are unchanged and were always
true. Only the reason is corrected, which is the whole of rule 3: state a fact or stay silent.
"""

import unittest

from cria import prompts, writeproxy


class TheReasonIsTheRefusalNotAPredictionTests(unittest.TestCase):
    STEERS = ("large_read_steer", "large_range_steer")

    def test_neither_steer_predicts_a_truncation(self):
        for name in self.STEERS:
            with self.subTest(steer=name):
                self.assertNotIn("truncat", prompts.load(name).lower())

    def test_neither_steer_blames_the_harness(self):
        """#18: a claim about the harness is one cria is not positioned to make, and #17 keeps
        cria's own name out of the alternative — so the sentence is about the READ."""
        for name in self.STEERS:
            with self.subTest(steer=name):
                body = prompts.load(name).lower()
                self.assertNotIn("harness", body)
                self.assertNotIn("cria", body)

    def test_both_say_what_actually_happened(self):
        for name in self.STEERS:
            with self.subTest(steer=name):
                body = prompts.load(name)
                self.assertIn("larger than can be returned", body)
                self.assertIn("nothing is shown", body)

    def test_both_still_offer_a_route_the_coder_can_take(self):
        """A refusal must name something the coder can actually change (#5b)."""
        for name in self.STEERS:
            with self.subTest(steer=name):
                body = prompts.load(name)
                self.assertIn("grep", body)
                self.assertIn("{{PATH}}", body)


class TheGapThatMadeItFalseTests(unittest.TestCase):
    def test_the_threshold_is_far_below_the_observed_cut(self):
        """9,000 bytes against a cut recorded at ~20,707 tokens. If these were ever close, the old
        sentence would have been true near the boundary; they are an order of magnitude apart."""
        observed_cut_bytes = 20707 * 4
        self.assertLess(writeproxy.READ_INLINE_MAX * 5, observed_cut_bytes)

    def test_the_sibling_fix_is_still_in_place(self):
        """`_spill_read_command` got this right first. Its reasoning is the reason these two are
        now consistent with it rather than contradicting it."""
        import inspect
        src = inspect.getsource(writeproxy._spill_read_command)
        self.assertIn("claim about cria dressed as a claim about the world", src)


class TheRefusalStillRefusesTests(unittest.TestCase):
    def test_an_oversize_whole_read_is_still_declined(self):
        cmd = writeproxy._read_command({"path": "big.txt"})
        self.assertIn(str(writeproxy.READ_INLINE_MAX), cmd)
        self.assertIn("larger than can be returned", cmd)

    def test_a_small_read_is_untouched(self):
        """The guard is a size test in the lowered command, not a remembered flag — a file under the
        limit still cats."""
        self.assertIn("cat ", writeproxy._read_command({"path": "small.txt"}))


if __name__ == "__main__":
    unittest.main()
