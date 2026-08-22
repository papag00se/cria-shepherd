"""The "go read that file" refusal names the file cria WROTE, not a name derived a second time.

`search_spill_name` digests the query, so two spellings of one search name two different files while
only one was ever written. Live on `shipping-rates-rb x nemotron-elastic` 1787431835: the coder
searched "ruby gem detect EU membership", cria spilled it, the coder searched the lower-cased
spelling, and cria refused the repeat by pointing at
`search-ruby_gem_detect_eu_membership-2d34dace.txt` — a path nothing had written. The coder read it,
cria answered "is not there — nothing was read" about its own suggestion, and that dead note rode in
26 later prompts."""
import unittest

from cria import webfetch


class ThePathIsRememberedTests(unittest.TestCase):
    def setUp(self):
        webfetch._SEARCH_SPILLED.clear()
        webfetch._SEARCH_SEEN.clear()

    def test_a_case_variant_finds_the_file_that_exists(self):
        written = webfetch.search_spill_name("ruby gem detect EU membership")
        webfetch.note_search_spill("s1", "ruby gem detect EU membership", written)
        self.assertEqual(webfetch.spilled_path("s1", "ruby gem detect eu membership"), written)

    def test_the_derived_name_really_does_differ_by_case(self):
        # If this ever stops being true the test above is guarding nothing.
        self.assertNotEqual(webfetch.search_spill_name("ruby gem detect EU membership"),
                            webfetch.search_spill_name("ruby gem detect eu membership"))

    def test_the_repeat_refusal_names_the_written_path(self):
        q = "ruby gem detect EU membership"
        written = webfetch.search_spill_name(q)
        webfetch.note_search_spill("s2", q, written)
        webfetch.set_visible("s2", [], [q])
        msg = webfetch.gate_search("s2", "ruby gem detect eu membership")
        self.assertIsNotNone(msg)
        self.assertIn(written, msg)

    def test_the_judge_index_is_keyed_by_the_written_path(self):
        q = "eu_countries"
        written = webfetch.search_spill_name(q)
        webfetch.note_search_spill("s3", q, written)
        self.assertEqual(webfetch.spilled_search_files("s3"), {written: q})


if __name__ == "__main__":
    unittest.main()
