import json
import unittest

from cria.content_reduce import (
    content_reduce,
    est_tokens,
    html_to_text,
    reduce_json,
    reduce_lossless,
    strip_prose_text,
)


class ContentReduceTests(unittest.TestCase):
    def test_under_cap_is_unchanged(self):
        s = "small output"
        self.assertEqual(content_reduce(s, "text/plain", 1000), s)

    def test_strips_function_words_keeps_meaning(self):
        s = ("Resolves an Ada Handle to its Cardano address; returns 404 when the handle is "
             "not found, with payment_address in the body.")
        out = strip_prose_text(s)
        # negation, identifiers, digits, logic words survive
        for keep in ["not", "Ada", "Handle", "Cardano", "404", "payment_address", "when"]:
            self.assertIn(keep, out, f"must keep `{keep}`: {out}")
        # function words gone
        for gone in [" an ", " to ", " its ", " with "]:
            self.assertNotIn(gone, out, f"must drop `{gone}`: {out}")
        self.assertLess(len(out), len(s))

    def test_json_structure_never_breaks_and_only_prose_fields_change(self):
        src = ('{"description":"This is a long human readable explanation of the thing that does '
               'work","pattern":"^[a-z]+ or [0-9]+$","example":"do not change this value at all please"}')
        out = reduce_json(src, 1)
        v = json.loads(out)  # still valid JSON
        # pattern (excluded) and example (excluded) untouched
        self.assertEqual(v["pattern"], "^[a-z]+ or [0-9]+$")
        self.assertEqual(v["example"], "do not change this value at all please")
        # description (prose field) got shorter but kept its content words
        d = v["description"]
        self.assertTrue("human" in d and "readable" in d and "explanation" in d)
        self.assertLess(len(d), len("This is a long human readable explanation of the thing that does work"))

    def test_html_strips_script_style_and_tags(self):
        html = ("<html><head><style>.x{color:red}</style><script>alert(1)</script></head>"
                "<body><h1>Title</h1><p>Hello <b>world</b> &amp; friends</p></body></html>")
        out = html_to_text(html)
        self.assertIn("Title", out)
        self.assertTrue("Hello" in out and "world" in out and "& friends" in out)
        self.assertNotIn("alert", out)
        self.assertNotIn("color:red", out)
        self.assertNotIn("<", out)

    def test_reduce_lossless_minifies_json_without_touching_prose(self):
        src = '{"description": "a b c d e f g h", "n": 1}'
        out = reduce_lossless(src, "application/json")
        self.assertEqual(json.loads(out), {"description": "a b c d e f g h", "n": 1})
        self.assertNotIn(", ", out)  # minified: no spaces after separators

    def test_reduce_lossless_bad_json_returned_unchanged(self):
        self.assertEqual(reduce_lossless("{not json", "application/json"), "{not json")

    def test_content_reduce_json_dispatch_reduces_over_cap(self):
        big = json.dumps({"description": "word " * 400, "id": "keep-me"})
        out = content_reduce(big, "application/json", 20)
        v = json.loads(out)
        self.assertEqual(v["id"], "keep-me")               # structure + non-prose intact
        self.assertLess(est_tokens(out), est_tokens(big))  # actually got smaller

    def test_html_skips_nested_template_content(self):
        out = html_to_text("<div>keep<template><p>drop me</p></template>tail</div>")
        self.assertIn("keep", out)
        self.assertIn("tail", out)
        self.assertNotIn("drop me", out)

    def test_protected_and_identifier_tokens_never_stripped(self):
        # 'and'/'or'/'if' are protected; UPPER/underscored/digit tokens are not function words
        s = "do the thing if it is A_CONST or 42 and not the other"
        out = strip_prose_text(s)
        for keep in ["if", "A_CONST", "or", "42", "and", "not"]:
            self.assertIn(keep, out)


if __name__ == "__main__":
    unittest.main()
