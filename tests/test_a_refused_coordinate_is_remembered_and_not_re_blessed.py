"""A coordinate the coder's toolchain refused must not be re-blessed by a later steer.

Walked on feed-pipeline-java x nemotron-elastic 1788243086 (0071->0073) and cart-billing-go
1788241229 (0095->0096): a reasoner/satisfaction seat ordered the coder to add
`com.opencsv.exception.CSVParseException` / re-blessed `shopspring/decimal v0.5.0` after the
session's own tools had said `package com.opencsv.exception does not exist` / `unknown revision
v0.5.0`. The existing prescribes-guard cannot reach it: `_shared_symbols` drops `/` tokens and its
findings die in compaction. The refusal ledger is durable, so the fact survives the fold.
"""
import unittest

from cria import refusalledger as rl
from cria import loop


class TheDetectorReadsResolverRefusalsTests(unittest.TestCase):
    def test_go_missing_module(self):
        self.assertIn("github.com/arndt/decimal",
                      rl.refused_names("go: no required module provides package "
                                       "github.com/arndt/decimal; to add it:"))

    def test_go_repository_not_found_url_normalizes_to_bare_path(self):
        # Walked on cart-billing-go x nemotron-elastic 1788413612: Go prints the refused module as a
        # URL, but the re-bless steer (0049/0058/0070/0082/0083/0107) named the bare host/path, so
        # the URL-form ledger entry never matched. The ledger must hold the bare path steers use.
        got = rl.refused_names("go: github.com/arborize/decimal: git ls-remote -q origin: "
                               "remote: Repository not found.\n\tfatal: repository "
                               "'https://github.com/arborize/decimal/' not found")
        self.assertIn("github.com/arborize/decimal", got)
        self.assertNotIn("https://github.com/arborize/decimal/", got)

    def test_a_dot_git_suffix_is_stripped(self):
        self.assertIn("github.com/arborize/decimal",
                      rl.refused_names("fatal: repository "
                                       "'https://github.com/arborize/decimal.git' not found"))

    def test_go_unknown_revision_module_at_version(self):
        self.assertIn("github.com/shopspring/decimal@v0.5.0",
                      rl.refused_names("go: github.com/shopspring/decimal@v0.5.0: reading "
                                       "go.mod at revision v0.5.0: unknown revision v0.5.0"))

    def test_java_missing_package(self):
        self.assertIn("com.opencsv.exception",
                      rl.refused_names("Importer.java:[18,29] package com.opencsv.exception "
                                       "does not exist"))

    def test_maven_missing_artifact(self):
        self.assertIn("org.opencsv:opencsv:jar:5.9.3",
                      rl.refused_names("Could not find artifact org.opencsv:opencsv:jar:5.9.3 "
                                       "in central"))

    def test_an_ordinary_word_is_not_a_coordinate(self):
        self.assertEqual(rl.refused_names("the build failed and nothing resolved"), set())

    def test_scan_reads_only_tool_results(self):
        msgs = [{"role": "assistant", "content": "package com.foo does not exist"},   # model prose
                {"role": "tool", "content": "package com.opencsv.exception does not exist"}]
        got = rl.scan_messages(msgs)
        self.assertIn("com.opencsv.exception", got)
        self.assertNotIn("com.foo", got)   # not from the model's own words (#10)


class TheTriggerNamesWhatTheDirectivePrescribesTests(unittest.TestCase):
    def test_a_directive_naming_a_refused_package_triggers(self):
        self.assertEqual(
            rl.prescribed("import com.opencsv.exception.CSVParseException;", {"com.opencsv.exception"}),
            "com.opencsv.exception")

    def test_longest_refused_token_wins(self):
        led = {"v0.5.0", "github.com/shopspring/decimal@v0.5.0"}
        self.assertEqual(
            rl.prescribed("require github.com/shopspring/decimal@v0.5.0", led),
            "github.com/shopspring/decimal@v0.5.0")

    def test_a_directive_naming_nothing_refused_is_clear(self):
        self.assertIsNone(rl.prescribed("add the correct import", {"com.opencsv.exception"}))

    def test_a_bare_path_steer_matches_a_url_form_refusal(self):
        # End to end for P3b: refusal seen as a URL, steer names the bare path; the trigger must fire.
        led = rl.refused_names("fatal: repository 'https://github.com/arborize/decimal/' not found")
        self.assertEqual(
            rl.prescribed("Replace it with the correct two-field entry "
                          "github.com/arborize/decimal ./ 1.0.0 now.", led),
            "github.com/arborize/decimal")


class TheGuardWithholdsOnlyWhenAReasonerSaysPrescribesTests(unittest.TestCase):
    DIRECTIVE = "Replace the import with import com.opencsv.exception.CSVParseException;"
    LEDGER = {"com.opencsv.exception"}

    def test_prescribes_verdict_withholds(self):
        got = loop._prescribes_a_refused_coordinate(
            self.DIRECTIVE, self.LEDGER, _rlog(), ask=lambda s, u: "PRESCRIBES")
        self.assertEqual(got, "com.opencsv.exception")

    def test_quotes_verdict_delivers(self):
        # "remove the refused import" is a QUOTES directive — it must NOT be withheld.
        got = loop._prescribes_a_refused_coordinate(
            "Remove the import of com.opencsv.exception; it does not resolve.",
            self.LEDGER, _rlog(), ask=lambda s, u: "QUOTES")
        self.assertEqual(got, "")

    def test_no_reasoner_delivers(self):
        # #4: no deterministic fallback behind an absent reasoner — the steer stands.
        self.assertEqual(
            loop._prescribes_a_refused_coordinate(self.DIRECTIVE, self.LEDGER, _rlog(), ask=None), "")

    def test_untriggered_directive_never_calls_the_reasoner(self):
        calls = []
        loop._prescribes_a_refused_coordinate(
            "add the correct import", self.LEDGER, _rlog(),
            ask=lambda s, u: calls.append(1) or "PRESCRIBES")
        self.assertEqual(calls, [])


class _rlog:
    def emit(self, *a, **k):
        pass


if __name__ == "__main__":
    unittest.main()
