"""`symbols_fine` vouched "the checks do NOT report a problem with: pom.xml" over a resolver error.

Walked on feed-pipeline-java x nemotron-elastic 1788232218 (calls 0065/0070/0080): the checks' own
text was `Could not find artifact org.opencsv:opencsv:jar:5.9.3` — a pom problem that no file:line
ever names — so text-containment found "pom.xml" nowhere in the findings and the briefing guard
declared the file unflagged, telling the coder "Do not rewrite working code" about the one file that
needed changing. Lexically true, substantively false: a failure reported WITHOUT a location could
concern any file, so while one exists no file may be vouched for (#11b). The flag rides the same
funnel that already persists the finding-set (`record_gate_state`), and the motivating ba5f226 case
— located compiler errors, all parsed — still speaks, because there the flag stays False.
"""
import types
import unittest
from unittest import mock

from cria import loop


BRIEFING = "The build fails: undefined symbols remain, including decimal.NewFromString and Importer.load."
FINDINGS = "cart.go:5:2: undefined: decimal.NewFromFloat64"


class TheGuardAbstainsWhenItCannotReachTests(unittest.TestCase):
    def test_an_unlocated_failure_silences_the_vouching(self):
        out = loop._briefing_symbol_truth(BRIEFING, FINDINGS, unlocated=True)
        self.assertEqual(out, BRIEFING)
        self.assertNotIn("do NOT report a problem", out)

    def test_located_failures_still_speak_the_ba5f226_case(self):
        out = loop._briefing_symbol_truth(BRIEFING, FINDINGS, unlocated=False)
        self.assertIn("do NOT report a problem", out)
        self.assertIn("decimal.NewFromString", out)


def outcome(report=None):
    stub = types.SimpleNamespace(selected=[], results={})   # a report both probers can walk
    return types.SimpleNamespace(ran=True, report=report or stub, unran=[])


class TheFlagRidesTheOneFunnelTests(unittest.TestCase):
    def test_a_red_gate_with_unlocated_failures_sets_it(self):
        gs = loop.GuardState()
        with mock.patch.object(loop.proberun, "failed_unparsed_probes", return_value=["p"]):
            loop.record_gate_state(gs, outcome(), "some finding")
        self.assertTrue(gs.last_gate_unlocated)

    def test_a_red_gate_with_only_located_failures_clears_it(self):
        gs = loop.GuardState()
        gs.last_gate_unlocated = True
        with mock.patch.object(loop.proberun, "failed_unparsed_probes", return_value=[]):
            loop.record_gate_state(gs, outcome(), "some finding")
        self.assertFalse(gs.last_gate_unlocated)

    def test_a_clean_complete_gate_clears_it(self):
        gs = loop.GuardState()
        gs.last_gate_unlocated = True
        with mock.patch.object(loop.probegate, "gate_is_partial", return_value=False), \
             mock.patch.object(loop.proberun, "gate_ran_tests", return_value=True):
            loop.record_gate_state(gs, outcome(), "")
        self.assertFalse(gs.last_gate_unlocated)


if __name__ == "__main__":
    unittest.main()
