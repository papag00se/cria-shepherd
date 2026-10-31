"""`spill_extent` names a first window; `_ranged_read` refuses ranges over the byte limit.

467da62 made the FILE-path sibling exact ("the window it names has to fit") and left the spilled-doc
sibling estimated from an average line width. Walked on feed-pipeline-java x nemotron-elastic
1788232218: cria said "It is 824 lines — start_line=1 end_line=205 fits in one read" about the
spilled opencsv POM — the one document naming the correct `com.opencsv` groupId — and then refused
the coder's SMALLER 1-200 request as "larger than can be returned in one read", in every prompt of
the run. A promise computed over average bytes and checked against real ones is a false fact (#5b)
made about a different artifact than the one the check reads (#12). The window is now measured over
the NUMBERED bytes `_ranged_read` returns, and cria abstains when even line 1 alone is over (#11b).
"""
import unittest

from cria import webfetch


def numbered_bytes(body: str, upto: int) -> int:
    """The bytes `_ranged_read` returns for lines 1..upto: `n: line\\n` each."""
    total = 0
    for n, line in enumerate(body.split("\n")[:upto], 1):
        total += len(str(n)) + 2 + len(line.encode("utf-8", "replace")) + 1
    return total


WIDE_FIRST = "\n".join(["W" * 2000] * 10 + ["x" * 10] * 1000)   # early lines far wider than average


class TheWindowIsMeasuredNotEstimatedTests(unittest.TestCase):
    def test_the_promised_window_provably_fits(self):
        fits = webfetch._numbered_prefix_fits(WIDE_FIRST, 9000)
        self.assertGreaterEqual(fits, 1)
        self.assertLessEqual(numbered_bytes(WIDE_FIRST, fits), 9000)

    def test_and_it_is_the_largest_such_window(self):
        fits = webfetch._numbered_prefix_fits(WIDE_FIRST, 9000)
        self.assertGreater(numbered_bytes(WIDE_FIRST, fits + 1), 9000)

    def test_the_old_proportional_estimate_overpromised_on_this_shape(self):
        """The fails-before, stated as arithmetic: the removed formula names a window the ranged
        read would refuse. If this stops holding, the fixture no longer exercises the defect."""
        lines = WIDE_FIRST.count("\n") + 1
        proportional = max(1, int(lines * 9000 / len(WIDE_FIRST)))
        self.assertGreater(numbered_bytes(WIDE_FIRST, proportional), 9000)

    def test_a_first_line_over_the_limit_yields_no_window(self):
        self.assertEqual(webfetch._numbered_prefix_fits("A" * 20000 + "\nshort", 9000), 0)

    def test_uniform_lines_still_get_a_generous_window(self):
        """The fix must not shrink the window where the estimate WAS honest: uniform lines."""
        body = "\n".join(["y" * 50] * 500)
        fits = webfetch._numbered_prefix_fits(body, 9000)
        self.assertGreater(fits, 100)
        self.assertLessEqual(numbered_bytes(body, fits), 9000)


class ItReachesTheHintTests(unittest.TestCase):
    """Through `spill_reading_hint` itself, with a seeded doc cache."""

    URL = "https://example.test/wide-doc"

    def setUp(self):
        self._saved = dict(webfetch._DOC_CACHE)
        webfetch._DOC_CACHE.clear()
        webfetch._DOC_CACHE[self.URL] = (200, "text/plain", WIDE_FIRST, None, False)

    def tearDown(self):
        webfetch._DOC_CACHE.clear()
        webfetch._DOC_CACHE.update(self._saved)

    def test_the_hint_names_a_window_the_ranged_read_will_honour(self):
        import os
        path = os.path.basename(webfetch._spill_name(self.URL))
        hint = webfetch.spill_reading_hint(path, 9000)
        self.assertIn("fits in one read", hint)
        import re
        m = re.search(r"end_line=(\d+)", hint)
        self.assertIsNotNone(m)
        promised = int(m.group(1))
        body = webfetch._greppable(WIDE_FIRST, None, "text/plain")
        self.assertLessEqual(numbered_bytes(body, promised), 9000,
                             "the hint promised a window the ranged read would refuse")


if __name__ == "__main__":
    unittest.main()
