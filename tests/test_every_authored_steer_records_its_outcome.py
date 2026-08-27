"""cria refuses most of the directives it writes, and nothing counted that.

Every guard in the steer funnel logs its own fire, and every one was built from a real incident it
demonstrably prevents. Nothing logged the DENOMINATOR, so nothing showed what they add up to.

Measured across four days of this machine's logs, 2026-08-24 to 2026-08-27:

    109 authored steers refused   vs   45 delivered

    28  dictated_code (invented spans)      7  false_citation
    27  prescribes_broken                   5  answer_contradicted
    23  reanchor_ungrounded                 4  invented_version
     9  rescue_skipped                      4  truncated · 2 ungrounded

Roughly seven of every ten directives cria authors, it then kills. Every walk in the sub-40 campaign
found the run's one correct directive somewhere in that pile — the AtomicInteger import, the five
lines to delete from the CSV builder, the Cargo.toml bin section before them.

That is not an argument for removing a guard. It is an argument for being able to see the tradeoff
without walking a run by hand (#12): the metric comes from the authoritative event, and the
authoritative event is the funnel returning.
"""

import unittest

from cria import loop


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def outcomes(self):
        return [kw for k, kw in self.events if k == "loop.steer_outcome"]


class OneEventEitherWayTests(unittest.TestCase):
    def test_a_delivered_steer_says_so(self):
        rlog = _Rlog()
        loop._grounded_steer_or_none("Read the failing test and fix what it caught.", "evidence", rlog)
        self.assertEqual([o["delivered"] for o in rlog.outcomes()], [True])
        self.assertEqual(rlog.outcomes()[0]["refused_by"], "")

    def test_a_refused_steer_names_the_guard(self):
        rlog = _Rlog()
        out = loop._grounded_steer_or_none(
            "Fetch https://example.invalid/api and parse the JSON it returns", "nothing", rlog)
        self.assertIsNone(out)
        self.assertEqual(rlog.outcomes()[0]["refused_by"], "ungrounded_url")
        self.assertFalse(rlog.outcomes()[0]["delivered"])

    def test_exactly_one_outcome_per_authored_steer(self):
        """Not one per guard. The guards keep their own detail events; this is the count."""
        rlog = _Rlog()
        loop._grounded_steer_or_none("Fetch https://example.invalid/x", "nothing", rlog)
        self.assertEqual(len(rlog.outcomes()), 1)

    def test_nothing_authored_is_not_a_refusal(self):
        """An empty directive is a seat that had nothing to say, which is not the same as a steer
        cria killed — counting it as one would inflate the very ratio this exists to measure."""
        rlog = _Rlog()
        self.assertIsNone(loop._grounded_steer_or_none("", "evidence", rlog))
        self.assertIsNone(loop._grounded_steer_or_none(None, "evidence", rlog))
        self.assertEqual(rlog.outcomes(), [])

    def test_the_head_of_the_directive_rides_along(self):
        """So a refusal can be read without opening the capture."""
        rlog = _Rlog()
        loop._grounded_steer_or_none("Fetch https://example.invalid/x", "nothing", rlog)
        self.assertIn("example.invalid", rlog.outcomes()[0]["head"])


class TheVettingIsUnchangedTests(unittest.TestCase):
    """The split moved the event, not a decision. Every guard still returns the same verdict."""

    def test_the_vetter_returns_the_guard_name_beside_the_steer(self):
        steer, why = loop._vet_steer("Read the failing test.", "evidence", _Rlog(), None, None, None, None)
        self.assertEqual((steer, why), ("Read the failing test.", ""))

    def test_each_refusal_carries_a_name_and_none_is_blank(self):
        steer, why = loop._vet_steer(
            "Fetch https://example.invalid/api", "nothing", _Rlog(), None, None, None, None)
        self.assertIsNone(steer)
        self.assertTrue(why, "a refusal with no name is a refusal nobody can count")

    def test_the_guards_own_events_still_fire(self):
        rlog = _Rlog()
        loop._grounded_steer_or_none("Fetch https://example.invalid/api", "nothing", rlog)
        self.assertIn("loop.steer_ungrounded", [k for k, _ in rlog.events])


if __name__ == "__main__":
    unittest.main()
