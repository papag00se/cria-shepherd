"""Every sentence cria writes about a spill file describes THAT FILE, not the document it came from.

Three ways it did not. The first-fetch message branches on the byte count and says "IN FULL" or "as
much as one step can carry"; the re-fetch refusal hardcoded "saved IN FULL"; and the reading hint
counted the whole cached document while naming the truncated file on disk.

Walked on cart-billing-go x nemotron-elastic 1787434778 — cria said at 0058 that the copy "holds the
first 46,080 characters of a 67,564-character document" and at 0062 that it was "saved IN FULL", then
told the coder the file "is 2,414 lines" when it is 1,656. The coder grepped the part cria kept and
read the absence as the library's rather than the file's."""
import unittest

from cria import webfetch


class OneFileOneDescriptionTests(unittest.TestCase):
    def setUp(self):
        self.url = "https://raw.githubusercontent.com/x/y/master/big.txt"
        self.addCleanup(webfetch._DOC_CACHE.pop, self.url, None)

    def _cache(self, body):
        webfetch._DOC_CACHE[self.url] = (200, "text/plain", body, None, False)

    def test_a_cut_spill_is_never_called_in_full(self):
        self._cache("z" * (webfetch.SPILL_CONTENT_MAX + 5_000))
        self.assertNotIn("IN FULL", webfetch.spill_extent_of(self.url))

    def test_a_whole_spill_still_says_in_full(self):
        self._cache("small enough")
        self.assertIn("IN FULL", webfetch.spill_extent_of(self.url))

    def test_the_refusal_and_the_first_message_agree(self):
        self._cache("z" * (webfetch.SPILL_CONTENT_MAX + 5_000))
        webfetch.note_spilled(self.url) if hasattr(webfetch, "note_spilled") else None
        self.assertEqual(webfetch.spill_extent_of(self.url),
                         webfetch._guard_msg("spill_extent_cut"))

    def test_the_line_count_is_the_files_own(self):
        whole = "\n".join(f"line {i} " + "z" * 60 for i in range(4_000))
        self._cache(whole)
        on_disk = whole.encode()[:webfetch.SPILL_CONTENT_MAX].decode("utf-8", "ignore")
        hint = webfetch.spill_reading_hint(webfetch._spill_name(self.url), 4_000)
        self.assertIn(f"{on_disk.count(chr(10)) + 1:,} lines", hint)
        self.assertNotIn(f"{whole.count(chr(10)) + 1:,} lines", hint)

    def test_an_uncached_file_claims_no_extent_it_cannot_check(self):
        """cria no longer holds the document, so it points at the file's own footer rather than
        picking one of the two answers."""
        clause = webfetch.spill_extent_of("https://never/fetched")
        self.assertNotIn("IN FULL", clause)
        self.assertIn("last line", clause)


if __name__ == "__main__":
    unittest.main()
