"""cria told the coder a page's content was in the transcript, having refused to put it there.

`shipping-rates-rb x ternary-bonsai` 1787111689. The coder fetched the rubydoc page for
`ISO3166::Country`. cria spilled it to a file, refused the read of that file ("larger than can be
returned in one read, so nothing is shown"), and then carried this on every later prompt:

    (this page answered, but no endpoint definitions were found in it — that status is a fact about
    the REQUEST, not about what the page contains; whatever it returned is in the transcript. If
    this task needs a machine-readable API definition, nothing read so far provides one.)

Both halves were wrong about that page. It defines `in_eu?` **with its source**, and its content was
NOT in the transcript — cria had put it on disk and then declined to show it. The one place the
ledger pointed at was the only place the content was not.

The coder guessed `eu_member?`, a method that does not exist, and that guess is the entire
`country_zone_mapping` failure. cria's own judge later named `in_eu?` correctly; the coder never saw
that either.

cria composed the spill, so it knows the path. Saying it costs nothing and is the fact the model was
missing (#5b — never turn an internal limit into a claim about the world).
"""

import unittest

from cria import loop, prompts, webfetch


def entry(status="HTTP 200 OK"):
    """A ledger entry as `groundtruth.fetch_facts` reads it: (status, routes, shapes, catalog)."""
    return (status, "", "", "")


class TheLedgerNamesTheSpillTests(unittest.TestCase):
    def setUp(self):
        webfetch._DOC_CACHE.clear()
        self.addCleanup(webfetch._DOC_CACHE.clear)

    def _spill(self, url, size):
        webfetch._DOC_CACHE[url] = (200, "text/html", "x" * size, None, False)

    def test_an_oversized_doc_reports_its_path_not_the_transcript(self):
        url = "https://www.rubydoc.info/gems/countries/3.1.0/ISO3166/Country"
        self._spill(url, webfetch.OVERSIZE_CHARS + 1_000)
        out = loop._format_fetches({url: entry()})
        self.assertIn("tmp/reference/", out)
        self.assertIn("it is not in this conversation", out)
        self.assertNotIn("whatever it returned is in the transcript", out)

    def test_a_small_doc_still_says_the_body_is_above(self):
        url = "https://example.com/small"
        self._spill(url, 100)
        out = loop._format_fetches({url: entry()})
        self.assertIn("in this conversation above", out)
        self.assertNotIn("tmp/reference/", out)

    def test_the_transcript_claim_is_gone_from_the_prompt_entirely(self):
        body = prompts.load_map("fetched_facts_sections")["no_structure"]
        self.assertNotIn("in the transcript", body)

    def test_the_narrow_true_fact_survives(self):
        """The narrow fact — the page answered but cria parsed no structure from it — is TRUE and
        kept. Its API wording ("no endpoint definitions … machine-readable API definition") was read
        as an off-task injection on ornith15 x shipping-rates-rb, so the fact now stands in neutral
        words that import no API subtask."""
        body = prompts.load_map("fetched_facts_sections")["no_structure"]
        self.assertIn("no structured data could be parsed out of it", body)
        self.assertNotIn("endpoint", body)
        self.assertNotIn("machine-readable API", body)


class OneOwnerDecidesWhetherASpillHappenedTests(unittest.TestCase):
    def setUp(self):
        webfetch._DOC_CACHE.clear()
        self.addCleanup(webfetch._DOC_CACHE.clear)

    def test_it_agrees_with_the_function_that_does_the_spilling(self):
        """`spill_path_for` and `oversized_spill` must never disagree about whether a url spilled,
        or the ledger points at a file that was never written (#23)."""
        url = "https://example.com/doc"
        for size in (10, webfetch.OVERSIZE_CHARS, webfetch.OVERSIZE_CHARS + 1):
            with self.subTest(size=size):
                webfetch._DOC_CACHE[url] = (200, "text/html", "x" * size, None, False)
                spilled = bool(webfetch.spill_path_for(url))
                self.assertEqual(spilled, webfetch.oversized_spill(url) is not None)
                if spilled:
                    self.assertEqual(webfetch.spill_path_for(url), webfetch.oversized_spill(url)[1])

    def test_an_unfetched_url_claims_nothing(self):
        self.assertEqual(webfetch.spill_path_for("https://never.fetched/x"), "")


if __name__ == "__main__":
    unittest.main()
