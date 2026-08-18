"""cria told the model a RubyDoc page "is YAML", then refused to let it read the page.

`shipping-rates-rb x ternary-bonsai`, calls 0016-0017 and again 0038. On the fetch:

    This document is too large for the context (10,251 chars) — it was saved IN FULL to
    ./tmp/reference/www.rubydoc.info_gems_countries_3.1.0_ISO3166_Country.txt … **It is YAML.**

The file is flattened HTML. `_doc_format`'s YAML test was `^(?:---\\s*$|[A-Za-z_][\\w.-]*:(?:\\s|$))`
— any line of the form `Word:` — and the page's first line is `RubyDoc.info:`. Documentation prose
is made of lines like that.

TWO OTHER THINGS MADE IT UNANSWERABLE AS WRITTEN, and they are why the answer is deleted rather than
tightened:

- The sniff ran on content that had already been reduced, so an ordinary HTML page arrives as TEXT
  and the function's own `"HTML"` branch could never fire for it.
- Whatever the source was, a doc that PARSED is written to the spill file by `_greppable` as pretty
  JSON. "YAML" was therefore never true of the bytes cria is describing — not even for a real YAML
  document. There was no input for which the answer was correct.

What is left is read off what cria established rather than sniffed: `parsed` is the parse that
actually happened, and a leading tag is a tag. Anything else is silence, which the caller renders as
no format sentence at all (#3).

The incident the function was built for is untouched. A `.../swagger.yml` url answered with JSON is
still announced as JSON, because `parsed` is not None — and now it is announced correctly whichever
way the server replied, which the old sniff only managed by accident.

THE PAGE THIS COST: `ISO3166::Country`, carrying `in_eu?` — the gem that works. The model went to a
different gem on the next call and its run died on that gem's broken require.
"""

import pathlib
import unittest

from cria import webfetch

SPILLED_RUBYDOC = """RubyDoc.info:
Class: ISO3166::Country
– Documentation for countries (3.1.0)
Libraries (https://www.rubydoc.info/gems) »
countries (3.1.0)
Overview:
in_eu? ⇒ Boolean
"""


class TheMeasuredPageTests(unittest.TestCase):
    def test_a_docs_page_is_not_announced_as_yaml(self):
        self.assertEqual(webfetch._doc_format(SPILLED_RUBYDOC), "")

    def test_the_real_spilled_file_if_it_survived(self):
        """The actual bytes from the run, when the workspace is still on disk."""
        f = pathlib.Path("/home/jesse/src/cria-shepherd/runs/"
                         "suite-shipping-rates-rb_ternary-bonsai_codex_poff_1787035426-46sz8hld/"
                         "tmp/reference/www.rubydoc.info_gems_countries_3.1.0_ISO3166_Country.txt")
        if not f.exists():
            self.skipTest("the walked workspace has been cleaned up")
        self.assertEqual(webfetch._doc_format(f.read_text(errors="replace")), "")

    def test_no_prose_shape_can_bring_it_back(self):
        for name, text in {
            "a colon heading": "Overview:\nsome prose here\n",
            "a definition list": "Returns:\n( Boolean )\n",
            "a log line": "INFO: started\n",
            "a made-up front matter lookalike": "Note: this is prose, not a document\n",
            "plain prose": "hello world\n",
            "empty": "",
        }.items():
            with self.subTest(shape=name):
                self.assertEqual(webfetch._doc_format(text), "")


class WhatCriaCanStillSayTests(unittest.TestCase):
    def test_a_doc_that_landed_as_json_is_json(self):
        """`_greppable` pretty-prints a parsed doc as JSON whatever the source was, so a YAML source
        still lands in the file as JSON — and the file is what the sentence describes."""
        import yaml
        for src in ("a: 1\n", "- a\n- b\n"):
            with self.subTest(src=src):
                g = webfetch._greppable(src, yaml.safe_load(src), "text/yaml")
                self.assertEqual(webfetch._doc_format(g), "JSON")

    def test_raw_json_with_no_parse_is_still_json(self):
        self.assertEqual(webfetch._doc_format('{"a": 1}'), "JSON")

    def test_a_parse_that_could_not_be_serialised_is_NOT_announced_as_json(self):
        """THE HOLE THE FIRST CUT OF THIS FIX OPENED, one commit wide. It took `parsed is not None`
        as proof of JSON, on the reasoning that `_greppable` pretty-prints every parsed doc. It does
        not always: `json.dumps` raises on a `datetime`, PyYAML turns a bare `2026-08-18` into one,
        and the doc then falls back to its raw YAML text — which cria announced as JSON. A false fact
        introduced by the fix for a false fact.

        The bytes are the authoritative object and are what is read now (#5b)."""
        import yaml
        src = "when: 2026-08-18\nwhat: a release\n"
        parsed = yaml.safe_load(src)
        self.assertIsInstance(parsed["when"], __import__("datetime").date)
        g = webfetch._greppable(src, parsed, "text/yaml")
        self.assertEqual(g, src, "precondition: it fell back to the raw text")
        self.assertEqual(webfetch._doc_format(g), "")

    def test_it_takes_no_parse_argument_at_all(self):
        """A parameter that can disagree with the bytes is a parameter that will."""
        import inspect
        self.assertEqual(list(inspect.signature(webfetch._doc_format).parameters), ["content"])

    def test_a_body_that_kept_its_tags_is_html(self):
        for head in ("<!doctype html><p>x", "<html><body>", "<?xml version='1.0'?>"):
            with self.subTest(head=head):
                self.assertIn(webfetch._doc_format(head), ("HTML",))

    def test_the_swagger_incident_still_answers_correctly(self):
        """ada-handles_nemotron-elastic_codex_pon_1785360304: a `.yml` url answered with JSON, and
        the coder grepped `properties:` against a file holding `"properties": {`. Naming the format
        is what fixed it, and it still does."""
        self.assertEqual(webfetch._doc_format('{\n  "paths": {}\n}'), "JSON")


class TheCallersPassTheParseTests(unittest.TestCase):
    def test_yaml_is_no_longer_a_possible_answer(self):
        import inspect
        body = inspect.getsource(webfetch._doc_format)
        code = body[body.index('"""', body.index('"""') + 3) + 3:]
        self.assertNotIn("YAML", code)


if __name__ == "__main__":
    unittest.main()
