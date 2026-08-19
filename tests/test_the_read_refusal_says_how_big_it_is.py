"""The refusal told the coder to grep a document whose shape and size it could not see.

`shipping-rates-rb x ternary-bonsai`, twice — run 1787102312 and again 1787111689. The coder fetched
the rubydoc page for `ISO3166::Country`, cria spilled it to a file and told it to read the file, and
then refused the read:

    ./tmp/reference/www.rubydoc.info_…_ISO3166_Country.txt is a large reference document — larger
    than can be returned in one read, so nothing is shown.
    Read it deliberately instead: grep the file for what you need (grep -n on …), or read a specific
    line range with read_file start_line/end_line.

For a document with no parsed structure the outline slot beside that sentence is EMPTY, so the coder
was told to grep with nothing to grep FOR, and to choose a line range with no idea how many lines
exist or how large a range would fit. **In both runs it asked once, was refused, and never opened the
file again.** It then guessed `eu_member?`, a method that does not exist. That guess is the whole
`country_zone_mapping` failure.

Both numbers are facts cria already holds: the document is in `_DOC_CACHE`, which is where the format
and the outline printed beside this sentence come from. Nothing is measured on the filesystem and
nothing is guessed — no cached doc, no sentence.

For the real page the answer is *"It is 309 lines — read_file with start_line=1 end_line=271 fits in
one read"*, and `def in_eu?` is at line 180. The one read cria now names would have shown it.
"""

import pathlib
import unittest

from cria import prompts, webfetch, writeproxy

REAL_SPILL = pathlib.Path(
    "/home/jesse/src/cria-shepherd/runs/"
    "suite-shipping-rates-rb_ternary-bonsai_codex_poff_1787111689-o4b2t3r5/"
    "tmp/reference/www.rubydoc.info_gems_countries_3.1.0_ISO3166_Country.txt")
URL = "https://www.rubydoc.info/gems/countries/3.1.0/ISO3166/Country"


class _Cached:
    def __init__(self, url, body):
        self.url, self.body = url, body

    def __enter__(self):
        webfetch._DOC_CACHE[self.url] = (200, "text/html", self.body, None, False)
        return webfetch._spill_name(self.url)

    def __exit__(self, *a):
        webfetch._DOC_CACHE.pop(self.url, None)
        return False


class TheMeasuredPageTests(unittest.TestCase):
    def test_the_refusal_names_a_range_that_reaches_the_answer(self):
        """The whole point, in one assertion: the range cria offers must cover `def in_eu?`."""
        if not REAL_SPILL.exists():
            self.skipTest("the walked workspace has been cleaned up")
        body = REAL_SPILL.read_text(errors="replace")
        with _Cached(URL, body) as path:
            hint = webfetch.spill_reading_hint(path, writeproxy.READ_INLINE_MAX)
        self.assertTrue(hint, "no hint for the document the run turned on")
        end = int(hint.split("end_line=")[1].split()[0])
        in_eu_line = next(i for i, l in enumerate(body.splitlines(), 1) if l.startswith("def in_eu?"))
        self.assertLess(in_eu_line, end,
                        f"the offered range stops at {end}; `def in_eu?` is at line {in_eu_line}")

    def test_it_states_the_line_count(self):
        if not REAL_SPILL.exists():
            self.skipTest("the walked workspace has been cleaned up")
        with _Cached(URL, REAL_SPILL.read_text(errors="replace")) as path:
            self.assertIn("309 lines", webfetch.spill_reading_hint(path, writeproxy.READ_INLINE_MAX))


class TheRangeItPromisesActuallyFitsTests(unittest.TestCase):
    def test_the_named_range_is_under_the_limit(self):
        for line_len, count in ((60, 500), (200, 300), (12, 4000)):
            body = "".join("x" * line_len + "\n" for _ in range(count))
            with self.subTest(line_len=line_len):
                with _Cached("https://e.com/d", body) as path:
                    hint = webfetch.spill_reading_hint(path, 9000)
                self.assertTrue(hint)
                end = int(hint.split("end_line=")[1].split()[0])
                kept = "\n".join(body.splitlines()[:end])
                self.assertLessEqual(len(kept), 9000)

    def test_a_document_that_would_fit_whole_gets_no_range(self):
        """Then the refusal is not about size and this sentence would be nonsense."""
        with _Cached("https://e.com/small", "a\nb\nc\n") as path:
            self.assertEqual(webfetch.spill_reading_hint(path, 9000), "")

    def test_a_document_cria_does_not_hold_says_nothing(self):
        self.assertEqual(webfetch.spill_reading_hint("./tmp/reference/never_seen.txt", 9000), "")

    def test_a_single_line_document_says_nothing(self):
        with _Cached("https://e.com/oneline", "x" * 20000) as path:
            self.assertEqual(webfetch.spill_reading_hint(path, 9000), "")


class ItReachesTheSteerTests(unittest.TestCase):
    def test_the_extent_is_rendered_into_the_refusal(self):
        with _Cached("https://e.com/doc", "".join(f"line {i}\n" for i in range(2000))) as path:
            extent = webfetch.spill_reading_hint(path, 9000)
            steer = prompts.render("spill_read_steer", path=path, format="",
                                   extent=f" {extent}\n", outline="")
        self.assertIn("lines — read_file with start_line=1", steer)
        self.assertIn("nothing is shown", steer)

    def test_no_placeholder_survives_when_there_is_no_extent(self):
        steer = prompts.render("spill_read_steer", path="x.txt", format="", extent="", outline="")
        self.assertNotIn("{{", steer)


if __name__ == "__main__":
    unittest.main()
