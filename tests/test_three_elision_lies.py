"""Three places where cria's own words did not match what cria had done.

All three came out of the 2026-08-22 elision sweep, and all three were reproduced before the fix.
"""

import json
import unittest

from cria import content_reduce as cr
from cria import webfetch


class TheDigestKeepsTheWordsItPromisedTests(unittest.TestCase):
    """`digest_reduce` exists to keep the function-word deleter away from text a model reads as
    instruction — its own docstring records the deleter inverting cria's sentence "no endpoints
    could BE READ FROM it" into "could read it". Its JSON tier walked straight back into it, on the
    compaction path, silently."""

    BODY = json.dumps({"items": [{"message": "the request could not be read from the server "
                                             "because the token is not valid"}] * 40})

    def test_the_sentence_survives_a_digest(self):
        out = cr.digest_reduce(self.BODY, "application/json", 50)
        self.assertIn("could not be read from the server", out)

    def test_it_still_minifies(self):
        """The lossless tier is free and stays."""
        spaced = json.dumps({"a": [{"b": "c"}] * 40}, indent=4)
        self.assertLess(len(cr.digest_reduce(spaced, "application/json", 10)), len(spaced))

    def test_the_lossy_caller_is_unchanged(self):
        """`content_reduce` is a different contract — it must shrink, and its caller labels it."""
        out = cr.content_reduce(self.BODY, "application/json", 50)
        self.assertNotIn("could not be read from the server", out)

    def test_the_label_explains_itself(self):
        """`⟦ctx:reduced⟧` was stamped on a rewritten tool result and explained nowhere — no prompt
        file, no legend. A disclosure no reader can decode is not one."""
        from cria import prompts
        note = prompts.render("reduced_result", body="RESULT")
        self.assertIn("⟦ctx:reduced⟧", note)
        self.assertIn("not verbatim", note)
        self.assertIn("RESULT", note)


class TwoSearchesGetTwoFilesTests(unittest.TestCase):
    """The stem is cut at 60 characters and the writer is `open(T, "w")`. Two queries agreeing in
    their first 60 slug characters wrote the same path, the earlier results were destroyed, and the
    repeat refusal then pointed the model at that file as though they were in it."""

    A = "ruby gem to determine whether a country is a member of the european union today"
    B = "ruby gem to determine whether a country is a member of the european union NOW"

    def test_two_long_queries_do_not_collide(self):
        self.assertNotEqual(webfetch.search_spill_name(self.A), webfetch.search_spill_name(self.B))

    def test_the_same_query_is_still_the_same_file(self):
        self.assertEqual(webfetch.search_spill_name(self.A), webfetch.search_spill_name(self.A))

    def test_the_stem_is_still_readable(self):
        """The model greps this path by name, so the query has to stay legible in it."""
        self.assertIn("ruby_gem_to_determine", webfetch.search_spill_name(self.A))

    def test_punctuation_alone_still_distinguishes(self):
        self.assertNotEqual(webfetch.search_spill_name("a b c"), webfetch.search_spill_name("a-b-c"))


class TheSpillSaysWhatLandedTests(unittest.TestCase):
    """`webfetch` said "it was saved IN FULL to <path>" while `writeproxy` appended "this saved copy
    holds the first 45,056 characters of a 186,444-character document" to the same tool result."""

    def setUp(self):
        webfetch.clear_cache()

    def _msg(self, n_chars: int) -> str:
        webfetch._DOC_CACHE["http://x/doc"] = (200, "text/plain", "y" * n_chars, None, False)
        return webfetch.oversized_spill("http://x/doc")[3]

    def test_a_document_that_fits_is_saved_in_full(self):
        self.assertIn("IN FULL", self._msg(cr.SPILL_CONTENT_MAX - 1000))

    def test_a_document_that_does_not_fit_does_not_claim_to_be(self):
        msg = self._msg(cr.SPILL_CONTENT_MAX + 5000)
        self.assertNotIn("IN FULL", msg)
        self.assertIn("as much of it as one step can carry", msg)

    def test_the_bound_has_one_owner(self):
        """It lived in `writeproxy`, where the module that composes the message could not see it."""
        from cria import writeproxy
        self.assertEqual(writeproxy.SPILL_CONTENT_MAX, cr.SPILL_CONTENT_MAX)
        self.assertEqual(webfetch.SPILL_CONTENT_MAX, cr.SPILL_CONTENT_MAX)


if __name__ == "__main__":
    unittest.main()
