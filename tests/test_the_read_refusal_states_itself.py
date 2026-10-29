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
    # `spill_read_steer` is the SIBLING fix (`_spill_read_command`) — it got this right first, and
    # is included here so the same four behavioural checks below prove it is still consistent with
    # the two fixed after it, rather than checking a docstring sentence survives.
    STEERS = ("large_read_steer", "large_range_steer", "spill_read_steer")

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
                if name == "spill_read_steer":
                    self.assertIn("larger than can be returned", body)
                    self.assertIn("nothing is shown", body)
                else:
                    self.assertIn("No file content was returned.", body)

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


class TheRefusalStillRefusesTests(unittest.TestCase):
    def test_a_large_whole_read_states_the_transport_refusal(self):
        # The removed guard falsely predicted a harness truncation. A transport
        # refusal states what actually happened and its suggested range must work.
        import json
        import pathlib
        import subprocess
        import tempfile
        from cria import denial
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory, "big.txt")
            content = "large content\n" * 2000
            path.write_text(content)
            result = subprocess.run(["sh", "-c", writeproxy._read_command({"path": str(path)})],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(denial.is_denied(result.stdout))
            self.assertIn('No file content was returned', result.stdout)
            self.assertNotIn('truncat', result.stdout.lower())
            args = json.loads(result.stdout.split('Next read_file arguments: ', 1)[1])
            page = subprocess.run(["sh", "-c", writeproxy._read_command(args)], capture_output=True, text=True, check=True)
            self.assertEqual(args['path'], str(path))
            self.assertEqual(args['start_line'], 1)
            self.assertEqual(page.stdout, ''.join(f'{i}: large content\n' for i in range(1, args['end_line'] + 1)))

    def test_a_small_read_is_untouched(self):
        """A file under the transport limit still returns its exact bytes."""
        import pathlib
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory, 'small.txt')
            path.write_bytes(b'hello\r\nworld')
            result = subprocess.run(['sh', '-c', writeproxy._read_command({'path': str(path)})], capture_output=True)
        self.assertEqual((result.returncode, result.stdout), (0, b'hello\r\nworld'))





# These legacy refusal cases exercise a known, explicit context allowance.
# Unknown usage and replacement of fixed caps are covered in test_shared_read_budget.
import pytest
from cria import filecommands as _read_policy
from cria.writeproxy import translate_outbound as _translate_reads


def _translate_with_read_allowance(*args, **kwargs):
    return _translate_reads(*args, **kwargs)


if __name__ == "__main__":
    unittest.main()
