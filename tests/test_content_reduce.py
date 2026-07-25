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

    def test_code_output_over_cap_is_not_keyword_stripped(self):
        # A file read of source code sniffs as unknown/text; the prose stripper would remove bare
        # `for`/`in`/`is`/`as`/`from`/`with` keywords and hand the model a broken file to edit.
        code = "\n".join(
            f"def handler_{n}(items):\n"
            f"    for item in items:\n"
            f"        if item is not None and item.kind in KINDS:\n"
            f"            yield transform(item) from cache with lock"
            for n in range(40)
        )
        out = content_reduce(code, None, cap_tokens=10)  # cap far below size → reduction attempted
        self.assertEqual(out, code)          # code left byte-intact (not prose → not stripped)
        self.assertIn("for item in items", out)
        self.assertIn("is not None", out)

    def test_prose_over_cap_is_still_stripped(self):
        # Genuine prose must STILL compress — the gate mustn't over-refuse.
        prose = ("The service resolves an incoming request to the correct handler and returns "
                 "a response to the caller, with the payload embedded in the body of the message. ") * 8
        out = content_reduce(prose, None, cap_tokens=10)
        self.assertLess(len(out), len(prose))
        self.assertNotIn(" to the ", out)  # a function word was dropped

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

    def test_anchor_href_is_kept_with_its_text(self):
        # A landing page linking to its spec: the model must SEE where the link goes,
        # not just its label — otherwise it can't follow it and resorts to guessing URLs.
        html = '<ul><li><a href="/openapi.json">OpenAPI spec (JSON)</a></li></ul>'
        out = html_to_text(html)
        self.assertIn("OpenAPI spec (JSON)", out)
        self.assertIn("/openapi.json", out)  # the target survives, not only the label

    def test_relative_href_is_resolved_against_the_page_url(self):
        # A bare /path is not directly fetchable without the host; resolve it so the
        # model gets an absolute URL it can hand straight back to web_fetch.
        html = '<a href="/openapi.json">spec</a>'
        out = html_to_text(html, "https://api.handle.me")
        self.assertIn("https://api.handle.me/openapi.json", out)

    def test_non_navigational_hrefs_are_dropped_and_bare_anchors_stay_clean(self):
        html = ('<a href="#top">frag</a> <a href="javascript:void(0)">js</a> '
                '<a>plain</a> <a href="https://x.io/y">abs</a>')
        out = html_to_text(html, "https://api.handle.me/p")
        self.assertNotIn("#top", out)
        self.assertNotIn("javascript:", out)
        self.assertIn("https://x.io/y", out)   # absolute href passes through
        self.assertIn("plain", out)
        self.assertNotIn("()", out)            # hrefless anchor adds no empty parens

    def test_protected_and_identifier_tokens_never_stripped(self):
        # 'and'/'or'/'if' are protected; UPPER/underscored/digit tokens are not function words
        s = "do the thing if it is A_CONST or 42 and not the other"
        out = strip_prose_text(s)
        for keep in ["if", "A_CONST", "or", "42", "and", "not"]:
            self.assertIn(keep, out)


if __name__ == "__main__":
    unittest.main()
