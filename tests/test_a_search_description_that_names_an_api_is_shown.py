"""A description naming something CALLABLE is the one thing a search title cannot carry.

cria drops search descriptions from the inline result and writes them to a spill file. That was
written against real poison — a wrong PACKAGE name read out of a snippet — and the reasoning holds:
titles carry package names, so nothing is lost by dropping the prose around them.

An API name is the exception, and it cost a run. Walked on the sub-40 pass, shipping-rates-rb x
nemotron-elastic. Ninety seconds in, the model's first search returned the whole task as its first
result's description:

    European Union Membership · c.in_eu? #=> false

cria wrote it to disk, showed the model twenty titles and links, and closed with "you do not have to
open it". The model spent the next fifteen minutes on nine more searches for a gem whose method name
it had already been handed. Zero tool calls in the whole 89-call run touched the spill directory;
four of the nine saved search files contain `in_eu?`.

The test is a SHAPE, not a language list (#20): punctuation between word characters is how Ruby, Go,
Java, Rust and Python all write a callable.
"""

import json
import re
import subprocess
import unittest

from cria import writeproxy


NAMES_AN_API = [
    "European Union Membership · c.in_eu? #=> false",
    "Use ISO3166::Country.new('DE') to look one up",
    "call `in_eu?` on the country",
    "decimal.NewFromFloat(1.5) builds a Decimal",
    "the #in_eu? predicate returns true for members",
    "reader.readAll() returns every row",
]

NAMES_NOTHING = [
    "The countries gem is a collection of all sorts of useful information",
    "Shipping rates for the European Union and beyond",
    "Buy gemstones online - the best prices in Europe",
    "opencsv 5.12.0 released 2026-01-04",
    "A fast, correct decimal library for Go",
]


class TheShapeTestTests(unittest.TestCase):
    def setUp(self):
        self.k = re.compile(writeproxy._API_NAME_SHAPE)

    def test_a_callable_is_kept(self):
        for d in NAMES_AN_API:
            with self.subTest(description=d):
                self.assertTrue(self.k.search(d))

    def test_prose_and_package_names_are_not(self):
        """A package name is the snippet poison the drop exists for, and the title already has it."""
        for d in NAMES_NOTHING:
            with self.subTest(description=d):
                self.assertIsNone(self.k.search(d))


class TheLoweredCommandDoesItTests(unittest.TestCase):
    """Run cria's own composed parser against a Brave body, rather than testing the regex twice."""

    BODY = {"web": {"results": [
        {"title": "countries | RubyGems.org", "url": "https://rubygems.org/gems/countries",
         "description": "European Union Membership · c.in_eu? #=> false"},
        {"title": "Gemstone tours of Europe", "url": "https://example.com/tours",
         "description": "Buy gemstones online - the best prices in Europe"},
    ]}}

    def _run(self, cwd):
        """The parse half of cria's real lowered command, fed the body curl would have fetched."""
        cmd = writeproxy._search_command({"query": "country gem eu membership ruby"}, "KEY")
        parse = cmd.split("| ", 1)[1].split(" || printf", 1)[0]
        return subprocess.run(["bash", "-lc", parse], input=json.dumps(self.BODY),
                              capture_output=True, text=True, cwd=cwd)

    def test_the_api_description_is_inline_and_the_noise_is_not(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = self._run(d)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("c.in_eu?", out.stdout)
            self.assertNotIn("Buy gemstones online", out.stdout)

    def test_every_description_still_reaches_the_spill_file(self):
        """The inline choice narrows what is SHOWN; it may not narrow what is saved."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self._run(d)
            saved = os.path.join(d, "tmp", "reference")
            files = os.listdir(saved)
            self.assertEqual(len(files), 1, files)
            body = open(os.path.join(saved, files[0])).read()
            self.assertIn("c.in_eu?", body)
            self.assertIn("Buy gemstones online", body)


class TheNoteNoLongerArguesAgainstTheFileTests(unittest.TestCase):
    def test_it_does_not_tell_the_model_it_can_skip_the_answer(self):
        """cria's own measurement is that models never open the file. The old note closed with
        "you do not have to open it" — cria arguing against the only copy of the answer."""
        from cria import prompts
        note = prompts.load("search_inline_note").lower()
        self.assertNotIn("do not have to open", note)
        self.assertIn("read the file", note)


if __name__ == "__main__":
    unittest.main()
