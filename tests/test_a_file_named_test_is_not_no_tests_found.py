"""cria announced "No jest/vitest tests were found" over a file called `test_lookup.js`.

Cycle 4 cell 5, handles-cli-node x gemma4. The model wrote its tests into `test_lookup.js` — a
hand-rolled runner driving the CLI through `execSync` — and cria's disclosure read:

    No jest/vitest tests were found — to be run they must be named *.test.js / *.spec.ts, or
    placed under __tests__/.

Every word of that is technically true and the whole of it is misleading: the project HAS test code,
sitting in the workspace root with `test` in its name, and the sentence tells the coder there is
none. What it needed was the sentence cria already owns for this exact state — *"Test code in
test_lookup.js will not run: …"* — which is one rename away from fixed.

WHY THE STRANDED CHECK MISSED IT. `_audit_tests` calls a file stranded when it matches no convention
glob AND `_carries_test_code` recognises it. The JS marker is `^\\s*describe\\s*\\(`, and this file has
no `describe`, no `it`, no framework import at all — it is a plain script with an assert loop. A
marker keyed to one framework's spelling cannot see test code written without a framework, and
loosening it is how production code gets called a stranded test.

The filename is the signal that survives that, and it is safe HERE specifically: a hit produces a
sentence saying the file will not run, never a refusal and never a dropped probe. The rule is tight —
`test` or `spec` as a whole leading or trailing word — so `testing.js`, `tests.js`, `protest.rb` and
`specification.py` stay out.
"""

import pathlib
import tempfile
import unittest

from cria import probediscovery as pd


class ATestyNameIsEvidenceTests(unittest.TestCase):
    def test_the_measured_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "package.json").write_text('{"name":"x"}')
            (root / "lookup.js").write_text("console.log(1)\n")
            (root / "test_lookup.js").write_text(
                "const { execSync } = require('child_process');\n"
                "function runTest(h) { execSync(`node lookup.js ${h}`); }\nrunTest('goose');\n")
            sent = " ".join(pd.stranded_test_sentences(root))
            self.assertIn("test_lookup.js", sent)
            self.assertIn("will not run", sent)
            self.assertNotIn("No jest/vitest tests were found", " ".join(pd.undiscoverable_tests(root)))

    def test_the_two_sentences_are_different_facts(self):
        """"your tests exist and will not run" and "you have no tests" are different instructions,
        and the file's own name decides which is true."""
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "package.json").write_text('{"name":"x"}')
            (root / "lookup.js").write_text("console.log(1)\n")
            self.assertIn("No jest/vitest tests were found", " ".join(pd.undiscoverable_tests(root)))


class TheNameRuleIsTightTests(unittest.TestCase):
    def test_names_that_say_test(self):
        for stem in ("test_lookup", "test-lookup", "test.lookup", "lookup_test",
                     "lookup-test", "lookup.test", "spec_rates", "rates_spec"):
            with self.subTest(stem=stem):
                self.assertTrue(pd._name_says_test(stem))

    def test_names_that_do_not(self):
        """A loose rule here would have cria calling production code a stranded test."""
        for stem in ("testing", "tests", "protest", "latest", "specification", "specs",
                     "lookup", "contest", "manifest", "greatest"):
            with self.subTest(stem=stem):
                self.assertFalse(pd._name_says_test(stem))

    def test_it_is_case_forgiving(self):
        self.assertTrue(pd._name_says_test("Test_Lookup"))
        self.assertTrue(pd._name_says_test("LookupSpec".replace("Spec", "_spec")))


class WhatWasAlreadyWorkingIsUntouchedTests(unittest.TestCase):
    def test_a_properly_named_test_is_discoverable_not_stranded(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "package.json").write_text('{"name":"x"}')
            (root / "lookup.test.js").write_text("describe('x', () => {});\n")
            self.assertEqual(pd.stranded_test_sentences(root), [])

    def test_the_marker_still_strands_framework_code(self):
        """The primary signal is unchanged: a `describe(` block in a badly-named file is still
        stranded on its CONTENT, with no help from the filename."""
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "package.json").write_text('{"name":"x"}')
            (root / "checks.js").write_text("describe('x', () => { it('y', () => {}); });\n")
            self.assertIn("checks.js", " ".join(pd.stranded_test_sentences(root)))

    def test_python_is_unaffected(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "app.py").write_text("x = 1\n")
            (root / "test_app.py").write_text("def test_x():\n    assert True\n")
            self.assertEqual(pd.stranded_test_sentences(root), [])


if __name__ == "__main__":
    unittest.main()
