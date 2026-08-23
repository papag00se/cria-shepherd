"""cria must not tell the coder no line could be parsed while quoting the line it parsed.

The incident: `gate_error_text` had two readers of one report and returned the first non-empty one.
When `completion_block_nudge` came back empty, the `ground_truth_failed` wording — "the repo's own
checks FAILED, but a specific line could not be parsed from the output" — went out in the same turn
as a `⟦ctx:checks⟧` block quoting the located error, and its coarse text quoted Maven's trailing
`[Help 1]` URL instead of the diagnostic. Five occurrences across two cycle-2 runs
(feed-pipeline-java x qwen35 calls 0018/0045/0056/0170, x gemma4 call 0020).

It is the same sentence `probeparse.split_diag`'s own comment records costing the Java column
0 / 40 / 0 / 0 in cycle 1. That fix repaired the parser. This one stops the readers contradicting
each other, and it also stops a real failing check being DROPPED whenever any other probe parsed.

AND THE THIRD SHAPE, FOUND BY THE 2026-08-23 SWEEP: the two readers can disagree about ONE probe.
`probegate.guard_ground_truth` keeps raw lines and `parse_output` builds structured findings, so a
location the first kept and the second missed produced, in one prompt, both "each is the checker's
OWN message and the line it flagged" over `rates.rb:21:in 'zone_for'` and "the repo's own checks
FAILED, but a specific line could not be parsed" over the identical command and tally. 176 prompts
across 54 sessions. A parser gap is not an unparseable output, and the wording now branches on
`probeparse.names_a_location` — one owner for the shape question, so the two readers can no longer
disagree about whether a line is THERE, only about whether cria managed to structure it.
"""
from __future__ import annotations

import unittest
from unittest import mock

from cria import loop


class _Outcome:
    def __init__(self, ran=True, report="report"):
        self.ran, self.report = ran, report


class GateErrorTextTests(unittest.TestCase):
    def _run(self, findings, failed):
        with mock.patch.object(loop.proberun, "completion_block_nudge", lambda *a, **k: findings), \
             mock.patch.object(loop.proberun, "failed_unparsed_probes", lambda *a, **k: failed):
            return loop.gate_error_text(_Outcome())

    def test_both_present_says_neither_is_the_whole_story(self):
        """FAILS BEFORE: returned the findings and silently dropped the failing check."""
        out = self._run("Importer.java:96 cannot find symbol", ["$ mvn -q compile — exited 1"])
        self.assertIn("Importer.java:96", out)
        self.assertIn("mvn -q compile", out)
        self.assertNotIn("could not be parsed", out)

    def test_a_parsed_line_is_never_called_unparseable(self):
        """The sentence that cost the Java column two cycles running."""
        out = self._run("Importer.java:96 cannot find symbol", ["$ mvn -q compile — exited 1"])
        self.assertNotIn("a specific line could not be parsed", out)

    def test_findings_alone_are_unchanged(self):
        self.assertEqual("Importer.java:96 cannot find symbol",
                         self._run("Importer.java:96 cannot find symbol", []))

    def test_unparsed_alone_still_says_so(self):
        """When nothing WAS parsed, the original wording is correct and must survive."""
        out = self._run(None, ["$ cargo check — exited 101: could not compile `shipping`"])
        self.assertIn("could not be parsed", out)
        self.assertIn("cargo check", out)

    def test_an_unstructured_failure_that_names_a_line_is_not_called_unparseable(self):
        """The sweep's shape: cria's parsers missed it, the raw reader did not, and the two blocks
        contradicted each other in one prompt."""
        for quoted in (
                "$ ruby -Ilib t.rb — exited 1: /ws/lib/shipping/rates.rb:21: NoMethodError",
                "$ go build ./... — exited 2: ./rates.go:4:2: undefined: multiplier",
                "$ mvn -q test — exited 1: /w/Importer.java:[99,22] cannot find symbol",
        ):
            with self.subTest(quoted=quoted):
                out = self._run(None, [quoted])
                self.assertNotIn("could not be parsed", out)
                self.assertIn(quoted, out)
                self.assertNotIn("Run that exact check yourself", out)

    def test_a_tally_is_not_a_location(self):
        """`18 runs, 14 assertions, 0 failures, 4 errors` says how many, never where — so the
        honest 'could not be parsed' wording still applies."""
        out = self._run(None, ["$ ruby t.rb — exited 1: 18 runs, 14 assertions, 0 failures, 4 errors"])
        self.assertIn("could not be parsed", out)

    def test_clean_stays_silent(self):
        self.assertEqual("", self._run(None, []))

    def test_a_gate_that_never_ran_stays_silent(self):
        with mock.patch.object(loop.proberun, "completion_block_nudge", lambda *a, **k: "x"), \
             mock.patch.object(loop.proberun, "failed_unparsed_probes", lambda *a, **k: ["y"]):
            self.assertEqual("", loop.gate_error_text(_Outcome(ran=False)))


if __name__ == "__main__":
    unittest.main()
