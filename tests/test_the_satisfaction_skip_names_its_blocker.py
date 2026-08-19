"""`loop.satisfaction_blocked` said THAT the check was skipped and never WHY.

Walked on `rust-toml-cli x ternary-bonsai`, 2026-08-19. The run reached three of four deliverables
by minute 30 and then sat there for thirty minutes with a README that was never written — the exact
gap the satisfaction check exists to name. It fired **zero** times in 66 drives.

The skip event recorded 50 occurrences and, between them, one opaque bit: `blocked`. Four
independent conditions feed it, so answering "which one" meant reading the gate events, the probe
events and three call sites by hand, and getting it wrong twice on the way. A metric must come from
the authoritative event (#12).

THE ANSWER, once found, was `last_gate_red` — and it LATCHES. `record_gate_state` sets it when a
gate RAN and found problems; only a later gate that runs and comes back genuinely clean clears it,
and a gate that could not run leaves it untouched. This session's first gate reading was red (the
build was broken) and no clean gate ever landed, so 34 due drives were skipped in a row.

Note what that costs: a run with persistent red checks is exactly the run most likely to ALSO be
missing a deliverable, and red is what silences the mechanism that would say so.
"""

import unittest

from cria import loop


class TheBlockerIsNamedTests(unittest.TestCase):
    def test_each_condition_reports_itself(self):
        for kw, name in ((dict(steer="do the thing"), "steer"),
                         (dict(rewritten=True), "history-rewritten"),
                         (dict(done_probe=True), "done-probe-in-flight"),
                         (dict(gate_red=True), "gate-red")):
            args = dict(steer=None, rewritten=False, done_probe=False, gate_red=False)
            args.update(kw)
            with self.subTest(blocker=name):
                self.assertEqual(loop._satisfaction_blocker(**args), name)

    def test_nothing_blocking_is_the_empty_string(self):
        self.assertEqual(loop._satisfaction_blocker(steer=None, rewritten=False,
                                                    done_probe=False, gate_red=False), "")

    def test_it_is_falsey_exactly_when_nothing_blocks(self):
        """The caller still treats it as a boolean; naming it must not change when it skips."""
        self.assertFalse(loop._satisfaction_blocker(steer="", rewritten=False,
                                                    done_probe=False, gate_red=False))
        self.assertTrue(loop._satisfaction_blocker(steer=None, rewritten=False,
                                                   done_probe=False, gate_red=True))


class TheEventCarriesTheNameTests(unittest.TestCase):
    class _Rlog:
        def __init__(self): self.events = []
        def emit(self, kind, **kw): self.events.append((kind, kw))

    def _skip(self, why):
        from cria.loop import Loop, PlanSession
        from cria.plan import Plan
        rlog = self._Rlog()
        sess = PlanSession(plan=Plan(id="x", task="t", created="c", items=[]))
        lp = Loop.__new__(Loop)
        out = lp._periodic_satisfaction(sess, {"messages": []}, rlog, plan_off=True, blocked=why)
        self.assertIsNone(out)
        return [kw for k, kw in rlog.events if k == "loop.satisfaction_blocked"]

    def test_the_skip_says_which_condition_it_saw(self):
        [ev] = self._skip("gate-red")
        self.assertEqual(ev["why"], "gate-red")

    def test_a_bare_boolean_caller_is_recorded_as_unnamed(self):
        """No caller should pass one — but a skip that cannot say why must SAY it cannot, never
        report a condition it did not observe (#5b)."""
        [ev] = self._skip(True)
        self.assertEqual(ev["why"], "unnamed")


class TheLatchIsRealTests(unittest.TestCase):
    """The behaviour behind the walked run, asserted directly on `record_gate_state`."""

    def _gate(self, ran):
        """The real GateOutcome — a stand-in would be testing the stand-in.

        NOT named `_outcome`: `unittest.TestCase` sets `self._outcome` to its own internal
        `unittest.case._Outcome` while a test runs, so the helper was silently shadowed and every
        call raised "'_Outcome' object is not callable"."""
        from cria.probegate import GateOutcome
        return GateOutcome(ran=ran, report=None)

    def test_a_red_gate_sets_it(self):
        gs = loop.GuardState()
        loop.record_gate_state(gs, self._gate(True), "E0277: mismatched types")
        self.assertTrue(gs.last_gate_red)

    def test_a_gate_that_could_not_run_leaves_it_exactly_as_it_was(self):
        """This is the latch. Seven readings in the walked run came back ran=False."""
        gs = loop.GuardState()
        loop.record_gate_state(gs, self._gate(True), "E0277: mismatched types")
        loop.record_gate_state(gs, self._gate(False), "")
        self.assertTrue(gs.last_gate_red, "a gate that could not run must not be read as green")

    def test_only_a_gate_that_RAN_and_was_clean_clears_it(self):
        gs = loop.GuardState()
        loop.record_gate_state(gs, self._gate(True), "E0277: mismatched types")
        loop.record_gate_state(gs, self._gate(True), "")
        self.assertFalse(gs.last_gate_red)


if __name__ == "__main__":
    unittest.main()
