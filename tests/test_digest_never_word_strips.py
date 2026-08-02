"""A compaction digest must not silently rewrite what the model reads.

Measured on run 20260801T225200 (zaya1, ada-handles, 0/4). The context floor's per-turn digest ran
the prose stripper over a dropped turn that held the user's TASK and cria's own planner instruction:

    task,  before : "I would like you to write a Python script that accepts an Ada Handle as input
                     and resolves it to the Cardano address"
    task,  as sent: "I would like you write Python script that accepts Ada Handle input and
                     resolves it Cardano address"

    cria's ask, before : "The request above is what the WORK is — it is not addressed to you"
    cria's ask, as sent: "The request above what WORK — it not addressed you"

And one line was INVERTED, not merely degraded: cria's own fetch note "no endpoints or field names
could BE READ FROM it" became "could read it" — a statement that nothing was learned, turned into a
claim that something was.

strip_prose_text calls those words "certain-junk". `is`, `to`, `of`, `for`, `be` are not junk; they
carry the grammatical relations. The result reads as fluent English and is not, which is a worse
failure than truncation because truncation is visible.
"""
import unittest

from cria import prompts
from cria.content_reduce import content_reduce, digest_reduce, strip_prose_text


class DigestTests(unittest.TestCase):
    ASK = prompts.load("plan_closing_ask")

    def test_the_measured_corruption_is_reproducible_with_the_old_path(self):
        # If this ever stops reproducing, the finding below needs re-deriving, not deleting.
        self.assertIn("The request above what WORK", strip_prose_text(self.ASK))

    def test_the_digest_never_produces_it(self):
        out = digest_reduce(self.ASK, None, 10)
        self.assertNotIn("The request above what WORK", out)
        self.assertNotIn("it not addressed you", out)

    def test_what_survives_is_VERBATIM(self):
        out = digest_reduce(self.ASK, None, 10)
        body = out.split("[…")[0].rstrip()
        self.assertTrue(self.ASK.startswith(body), "the kept prefix must be the original text")

    def test_the_loss_is_STATED(self):
        out = digest_reduce(self.ASK, None, 10)
        self.assertIn("characters of this turn omitted", out)

    def test_text_that_fits_is_returned_untouched(self):
        self.assertEqual(digest_reduce(self.ASK, None, 100_000), self.ASK)

    def test_the_meaning_inverting_line_survives_intact(self):
        line = "no endpoints or field names could be read from it"
        self.assertIn("could read it", strip_prose_text(line))          # the old corruption
        self.assertIn("could be read from it", digest_reduce(line, None, 10_000))

    def test_structured_content_still_reduces_structurally(self):
        big = '{"a": ' + '"' + "x" * 4000 + '"}'
        out = digest_reduce(big, "application/json", 50)
        self.assertLess(len(out), len(big))

    def test_evidence_reduction_is_UNCHANGED(self):
        # content_reduce still serves fetched pages/tool output, where the trade is defensible and
        # the text is not instruction. Only the digest path changed.
        prose = ("The quick brown fox is jumping over the lazy dog in the park. " * 200)
        self.assertNotEqual(content_reduce(prose, None, 20), prose)


class WiringTests(unittest.TestCase):
    def test_the_context_floor_digest_uses_it(self):
        import inspect

        from cria import contextfloor
        src = inspect.getsource(contextfloor._compacted_note)
        self.assertIn("digest_reduce(text, _sniff_content_type(text), per_turn)", src)
        self.assertNotIn("content_reduce(text, _sniff_content_type(text), per_turn)", src)
