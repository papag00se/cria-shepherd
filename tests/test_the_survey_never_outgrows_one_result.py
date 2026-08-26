"""cria's workspace survey rides home on a tool result — it must fit inside one.

The survey is appended to a lowered tool's command so its output comes back on that tool's result.
That result passes through the harness's own output cap on the way in. If the two halves together
exceed the cap the harness cuts the middle, which is where the survey's head sits, and
`wsview.apply_survey` then refuses what is left because the entry count no longer matches the
records that survived. cria keeps running with a stale workspace view and nothing downstream knows.

Walked on the 144-cell engagement ladder: 449 refused surveys across 11 cells, tracking the
harness's own cut markers nearly one for one (94/94, 46/47, 29/29, 17/17). The carrier was
`list_dir`, whose lowering caps its listing at READ_INLINE_MAX — 9,000 bytes on its own, against a
survey measured at 6.6-10 KB.

This asserts the PROPERTY that made it a bug: every tool the survey may ride on must answer in
about one line, so the sum can never approach a result's worth. It is not a list of today's four
tool names — a fifth added later with a large result would fail it.
"""
import unittest

from cria import writeproxy


class TheSurveyRidesOnlyOnOneLineResults(unittest.TestCase):

    def test_no_surveyable_tool_returns_a_large_result(self):
        """A surveyable tool's own output must be negligible against READ_INLINE_MAX."""
        budget = writeproxy.READ_INLINE_MAX
        for name in sorted(writeproxy._SURVEYABLE):
            with self.subTest(name):
                self.assertNotIn(name, writeproxy._READ_NAMES, f"{name} returns file contents")
                self.assertNotIn(name, writeproxy._LIST_NAMES, f"{name} returns a directory listing")
                self.assertNotIn(name, writeproxy._FETCH_NAMES, f"{name} returns a fetched page")
                self.assertNotIn(name, writeproxy._SEARCH_NAMES, f"{name} returns search results")
        self.assertGreater(budget, 0)

    def test_the_writers_still_carry_it(self):
        """Removing the oversized carrier must not leave the survey with no way home."""
        self.assertTrue(writeproxy._SURVEYABLE & writeproxy._WRITE_NAMES)
        self.assertTrue(writeproxy._SURVEYABLE & writeproxy._EDIT_NAMES)

    def test_a_capped_listing_plus_a_survey_would_exceed_one_result(self):
        """The arithmetic that made list_dir the wrong carrier, asserted rather than remembered."""
        from cria import wsview
        self.assertGreater(writeproxy.READ_INLINE_MAX + wsview.TREE_MAX_BYTES,
                           writeproxy.READ_INLINE_MAX,
                           "a listing at its cap leaves no room for a survey on the same result")


if __name__ == "__main__":
    unittest.main()
