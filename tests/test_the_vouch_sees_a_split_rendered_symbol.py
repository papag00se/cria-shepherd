"""The "checks do NOT report a problem with X" vouch must not fire when the checks DO name X.

Walked on feed-pipeline-java x nemotron-elastic 1788243086 (calls 0073/0076/0084/0102/0122): the
vouch named `com.opencsv.CSVParseException` as working, directly above javac's `symbol: class
CSVParseException` / `location: package com.opencsv` — a #5b false fact, because javac splits the
FQN across lines so the whole dotted string never appears in the checks and the whole-string test
missed it. The leaf (`CSVParseException`) is right there. Leaf-match only WITHHOLDS a vouch, never
emits one, so ba5f226's genuinely-absent case still speaks.
"""
import unittest

from cria import loop


BRIEFING = ("The build fails: undefined symbols remain, including "
            "com.opencsv.CSVParseException and com.example.TotallyAbsentThing.")
# javac's split rendering: the FQN never appears whole; the leaf class name does.
FINDINGS = ("Importer.java:[92,76] cannot find symbol\n"
            "  symbol:   class CSVParseException\n"
            "  location: package com.opencsv")


class LeafMatchWithholdsTheFalseVouchTests(unittest.TestCase):
    def test_a_split_rendered_fqn_is_seen_as_named(self):
        self.assertTrue(loop._checks_name_symbol("com.opencsv.CSVParseException", FINDINGS))

    def test_the_vouch_does_not_name_the_split_symbol(self):
        named = loop._briefing_denies_working_symbols(BRIEFING, FINDINGS)
        self.assertNotIn("com.opencsv.CSVParseException", named)

    def test_a_genuinely_absent_symbol_is_still_named(self):
        # ba5f226's motivating case: the checks say nothing about this one — the vouch still speaks.
        named = loop._briefing_denies_working_symbols(BRIEFING, FINDINGS)
        self.assertIn("com.example.TotallyAbsentThing", named)

    def test_a_short_leaf_collision_cannot_silence_a_vouch(self):
        # leaf 'Map' is <=3 chars and common; a broken 'com.foo.Map' is still named despite an
        # unrelated 'Map' in the checks — the leaf rule requires >3 chars.
        self.assertFalse(loop._checks_name_symbol("com.foo.Map", "cannot find symbol Map"))

    def test_whole_token_match_still_works(self):
        self.assertTrue(loop._checks_name_symbol("decimal.NewFromFloat64",
                                                 "undefined: decimal.NewFromFloat64"))


if __name__ == "__main__":
    unittest.main()
