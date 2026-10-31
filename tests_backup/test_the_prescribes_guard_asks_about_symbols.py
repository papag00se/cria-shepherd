"""The shared-name gather must hand the provider-status guard real names, not failure vocabulary.

The current diagnostic guard still needs concrete names present in BOTH a directive and red
findings so its focused provider-status question can ask about one subject at a time. Its predecessor
asked one reasoner to decide the whole prescription relationship directly.

The gather was any identifier-shaped run of four or more letters — which, on a failing build, is the
vocabulary of failure itself. MEASURED over every fire the guard has ever had, all 18, found in the
cycle-4 walk. At most two were correct. The tokens it fired on:

    error · orders · countries · failures · compile · declared · annotations · shopspring · python3
    LoadError · decimal.Decimal · orders.db · http.client · AttributeError · Cargo.toml

and the directives it killed include the exact fixes two cells of cycle 4 did not get:

    "Replace `axed` on line 90 with `taxed` — the variable is declared as axed :="   [on: declared]
    "correcting the [bin] section in Cargo.toml to define..."                        [on: Cargo.toml]
    "replace `from http.client import HTTPServer` with `from http.server import ...`"[on: http.client]
    "Edit the line `from .db import db` to `import orders.db as db`"                 [on: orders.db]

Asking "is this directive PRESCRIBING `declared`?" is not a question with an answer, and a weak
judge answering it wrongly refuses the steer — so cria diagnosed a one-character typo correctly and
then suppressed its own diagnosis.

An API symbol is QUALIFIED or COMPOUND in every language cria meets: a dot, a `::`, an underscore,
or an internal capital. That is a shape test, not a stoplist — a list of English words to exclude
would be a rule needing an exception list, which is the tell that it should have been a question
(#9's corollary, #20).

The gather is not a verdict. The provider-status and directive-relation judgments are separate so a
missing source import is not conflated with a package that does not provide the named member.
"""

import unittest

from cria.loop import _looks_like_a_symbol, _shared_symbols


WORDS = ["error", "orders", "countries", "failures", "compile", "declared",
         "annotations", "shopspring", "python3", "tests", "install", "bundle"]
SYMBOLS = ["decimal.NewFromFloat64", "NewFromInt64", "getTotalAmount", "setSkipInitialNewline",
           "decimal.Decimal", "orders.db", "http.client", "AttributeError", "Cargo.toml",
           "LoadError", "cart.go", "std::vector", "snake_case_name"]


class OnlyANameIsAskedAboutTests(unittest.TestCase):
    def test_the_vocabulary_of_failure_is_not_a_symbol(self):
        for w in WORDS:
            with self.subTest(token=w):
                self.assertFalse(_looks_like_a_symbol(w))

    def test_every_symbol_the_guard_was_built_for_survives(self):
        for t in SYMBOLS:
            with self.subTest(token=t):
                self.assertTrue(_looks_like_a_symbol(t))

    def test_the_measured_incident(self):
        """"Replace axed on line 90 with taxed" against "axed declared and not used" — the shared
        token was `declared`, and the guard killed the correct fix."""
        directive = "Replace `axed` on line 90 with `taxed` — the variable is declared as axed :="
        findings = "./cart.go:90:2: axed declared and not used\n./cart.go:91:11: undefined: taxed"
        self.assertNotIn("declared", _shared_symbols(directive, findings))

    def test_the_real_symbol_is_still_offered(self):
        """The 2026-08-04 incident must still reach the judge: a steer saying to USE a name the
        compiler calls undefined."""
        directive = "Use decimal.NewFromFloat64 to build the value"
        findings = "./cart.go:58:27: undefined: decimal.NewFromFloat64"
        self.assertIn("decimal.NewFromFloat64", _shared_symbols(directive, findings))

    def test_no_shared_symbol_asks_nothing(self):
        self.assertEqual(_shared_symbols("run the tests again", "3 tests failed"), [])

    def test_longest_first_is_preserved(self):
        d = "call decimal.Decimal and decimal.NewFromFloat"
        f = "undefined: decimal.NewFromFloat / undefined: decimal.Decimal"
        got = _shared_symbols(d, f)
        self.assertEqual(got, sorted(got, key=len, reverse=True))


if __name__ == "__main__":
    unittest.main()
