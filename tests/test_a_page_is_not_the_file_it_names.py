"""When a fetch of a source-file URL returns a web page, cria says the spill holds the PAGE.

Walked on cart-billing-go x nemotron-elastic 1787434778. The coder fetched
`https://github.com/shopspring/decimal/blob/master/decimal.go` with raw=true. cria saved 46,389 bytes
of GitHub chrome — 39 `<link rel="stylesheet">` tags, zero occurrences of `func NewFromString` — to
`tmp/reference/github.com_shopspring_decimal_blob_master_decimal.go.txt`, and every later fetch was
refused with "Read it — do NOT re-fetch the whole url. Grep the file for what you need."

The coder grepped that markup five times for `Quantize`, got nothing each time, and concluded the
question was unanswerable. The real source was in the same directory the whole run, under the
raw.githubusercontent name, with `func (d Decimal) RoundCeil(places int32) Decimal` at line 1586."""
import unittest

from cria import webfetch, writeproxy

PAGE = "<!doctype html>" + '<link rel="stylesheet" href="a.css">' * 40 + "<div>nav</div>"
SOURCE = "package decimal\n\nfunc NewFromString(value string) (Decimal, error) {\n\treturn d, nil\n}\n"


class TheSpillSaysWhatItHoldsTests(unittest.TestCase):
    def setUp(self):
        self.blob = "https://github.com/shopspring/decimal/blob/master/decimal.go"
        self.raw = "https://raw.githubusercontent.com/shopspring/decimal/master/decimal.go"
        for u in (self.blob, self.raw):
            self.addCleanup(webfetch._DOC_CACHE.pop, u, None)

    def test_a_page_under_a_source_name_is_recognised(self):
        self.assertTrue(webfetch.html_page_about_a_file(self.blob, PAGE))

    def test_the_real_source_is_not(self):
        self.assertFalse(webfetch.html_page_about_a_file(self.raw, SOURCE))

    def test_an_ordinary_html_page_is_not(self):
        self.assertFalse(webfetch.html_page_about_a_file("https://example.com/docs", PAGE))

    def test_the_read_refusal_says_so(self):
        webfetch._DOC_CACHE[self.blob] = (200, "text/html", PAGE, None, False)
        cmd = writeproxy._spill_read_command(webfetch._spill_name(self.blob))
        self.assertIn("web PAGE at that address", cmd)
        self.assertIn("fetch the address that serves it raw", cmd)

    def test_a_real_source_spill_gets_no_such_note(self):
        webfetch._DOC_CACHE[self.raw] = (200, "text/plain", SOURCE, None, False)
        cmd = writeproxy._spill_read_command(webfetch._spill_name(self.raw))
        self.assertNotIn("web PAGE at that address", cmd)

    def test_the_note_never_names_the_shim(self):
        from cria import prompts
        self.assertNotIn("cria",
                         prompts.load_map("webfetch_guards")["spill_is_the_page_not_the_file"].lower())


if __name__ == "__main__":
    unittest.main()
