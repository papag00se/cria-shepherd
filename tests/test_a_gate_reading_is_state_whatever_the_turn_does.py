"""A gate cria READ and then threw away, because the turn returned through a different door.

`guard_probe_steer` handles the turn after a repetition-redirect or wheel-spin probe. It reads the
SAME probe result the completion gate reads — same `probe_call_id`, same `gate_plan`, same
`read_gate` call — and it recorded none of it:

    outcome = read_gate(gs.gate_plan, probe, rlog)     # ← read
    if gs.redirect_probe:
        ...
        return f"[REDIRECT]\\n{redirect}"              # ← and gone

`_verify_after_probe` then returns on that steer, ABOVE its own state mirror, so a gate that went
green → red on a guard-probe turn left `last_gate_red` False and `gate_fresh` True. Everything
downstream that asks "was the last check red?" — the completion backstop, the satisfaction judge's
evidence, the anti-laundering rollup override, the steer author's findings slot — was answered with
the PREVIOUS gate. Failing open toward "done" is the one direction #13 forbids.

THE SHAPE OF THE BUG, not just the instance: three readers of one fact, two writing the state inline
in their own words with their own idea of which fields mattered, and the third writing none. So this
is fixed by extraction rather than by adding a fourth copy — `record_gate_state` is now the only
place a reading becomes state, and `gate_error_text` the only place "is it red" is decided.
(A FOURTH reader turned up while wiring it: `guard_periodic_result`, whose omission was
`last_gate_ran` — a check-in that ran was indistinguishable from one that never happened.)

Two things that were plan-off-only now hold on both paths, and both are the fail-CLOSED direction:
the stall streak (`track_gate_progress`, whose docstring already said it must be the one funnel), and
the second red arm — a check that RAN and exited non-zero with nothing parseable. `_verify_after_probe`
kept `completion_block_nudge` for the STEP verdict; only the recorded state uses the fuller reading.
"""

import unittest

from cria import loop, proberun
from cria.loop import GuardState, gate_error_text, record_gate_state
from cria.probegate import GateOutcome


class _Report:
    def __init__(self, results=(), selected=()):
        self.results = list(results)
        self.selected = list(selected)


def outcome(ran=True, **kw):
    return GateOutcome(ran=ran, report=_Report(), **kw)


class TheReadingIsRecordedTests(unittest.TestCase):
    def test_a_red_reading_sets_red_and_clears_fresh(self):
        gs = GuardState()
        gs.last_gate_red = False
        gs.gate_fresh = True
        record_gate_state(gs, outcome(), "x.py:3 SyntaxError: bad")
        self.assertTrue(gs.last_gate_red)
        self.assertFalse(gs.gate_fresh)
        self.assertTrue(gs.last_gate_ran)
        self.assertIn("SyntaxError", gs.last_gate_flag)

    def test_a_green_reading_clears_red(self):
        gs = GuardState()
        gs.last_gate_red = True
        record_gate_state(gs, outcome(), "")
        self.assertFalse(gs.last_gate_red)
        self.assertTrue(gs.gate_fresh)
        self.assertEqual(gs.last_gate_flag, "")

    def test_a_gate_that_could_not_run_is_neither(self):
        """A neutral non-signal: never red, never green, and it must not touch the stall streak —
        track_gate_progress says so in its own words. Still ATTEMPTED, so gate_fresh is set."""
        gs = GuardState()
        gs.last_gate_red = True
        gs.last_gate_flag = "the previous finding"
        gs.gate_stall = 2
        record_gate_state(gs, outcome(ran=False), "")
        self.assertTrue(gs.last_gate_red)                  # unchanged — no evidence either way
        self.assertEqual(gs.last_gate_flag, "the previous finding")
        self.assertEqual(gs.gate_stall, 2)
        self.assertTrue(gs.gate_fresh)
        self.assertFalse(gs.last_gate_ran)

    def test_the_stall_streak_advances_on_an_unchanged_finding(self):
        gs = GuardState()
        record_gate_state(gs, outcome(), "same error")
        record_gate_state(gs, outcome(), "same error")
        self.assertEqual(gs.gate_stall, 2)
        record_gate_state(gs, outcome(), "a different error")
        self.assertEqual(gs.gate_stall, 1)


class TheGuardProbeTurnRecordsItTests(unittest.TestCase):
    """THE REGRESSION, driven through guard_probe_steer itself."""

    def _gs(self, *, spin: bool):
        gs = GuardState()
        gs.gate_plan = object()          # any non-None plan; read_gate is patched below
        gs.probe_call_id = "c1"
        gs.spin_path = "handler.py"
        gs.spin_probe = spin
        gs.redirect_probe = not spin
        gs.last_gate_red = False         # the PREVIOUS gate was green — this is what used to survive
        gs.gate_fresh = True
        return gs

    def _run(self, gs, findings):
        red = outcome()

        def fake_read_gate(plan, probe_text, rlog):
            return red

        def fake_findings(o):
            return findings

        real_read, real_find = loop.read_gate, loop.gate_error_text
        loop.read_gate, loop.gate_error_text = fake_read_gate, fake_findings
        try:
            return loop.guard_probe_steer(gs, {"messages": []}, _Rlog(), author=loop.CANNED, step=1)
        finally:
            loop.read_gate, loop.gate_error_text = real_read, real_find

    def test_a_wheel_spin_turn_records_a_red_gate(self):
        gs = self._gs(spin=True)
        steer = self._run(gs, "handler.py:3 SyntaxError: bad")
        self.assertIsNotNone(steer)                 # it still steers
        self.assertTrue(gs.last_gate_red)           # ...and no longer forgets what it just read
        self.assertFalse(gs.gate_fresh)
        self.assertIn("SyntaxError", gs.last_gate_flag)

    def test_a_repetition_redirect_turn_records_it_too(self):
        gs = self._gs(spin=False)
        steer = self._run(gs, "handler.py:3 SyntaxError: bad")
        self.assertTrue(steer.startswith("[REDIRECT]"))
        self.assertTrue(gs.last_gate_red)

    def test_a_green_guard_probe_clears_a_stale_red(self):
        gs = self._gs(spin=True)
        gs.last_gate_red = True
        self._run(gs, "")
        self.assertFalse(gs.last_gate_red)

    def test_a_non_guard_probe_turn_reads_nothing(self):
        """The completion gate's own turn: guard_probe_steer must return before touching anything —
        the loop owns that reading."""
        gs = GuardState()
        gs.last_gate_red = True
        self.assertIsNone(loop.guard_probe_steer(gs, {"messages": []}, _Rlog(), author=loop.CANNED))
        self.assertTrue(gs.last_gate_red)


class TheRednessDecisionHasOneOwnerTests(unittest.TestCase):
    def test_a_gate_that_never_ran_is_not_red(self):
        self.assertEqual(gate_error_text(outcome(ran=False)), "")

    def test_there_is_no_second_redness_function(self):
        """The first cut of this fix added one — a private copy of gate_error_text with a
        hand-written prefix, which is the fifth copy of a rule that already had an owner. Worse, it
        reproduced the bug gate_error_text exists to fix: it returned the located findings OR the
        unparseable failures, never both."""
        self.assertFalse(hasattr(loop, "gate_findings_text"))

    def test_both_failure_classes_are_surfaced_together(self):
        """A located finding and a check that failed with nothing parseable are not alternatives."""
        import inspect
        src = inspect.getsource(gate_error_text)
        self.assertIn("findings and failed", src)

    def test_no_reader_writes_the_state_inline_any_more(self):
        import inspect
        for fn in (loop.guard_gate_verdict, loop.guard_probe_steer, loop.Loop._verify_after_probe,
                   loop.guard_periodic_result):
            with self.subTest(fn=fn.__name__):
                src = inspect.getsource(fn)
                self.assertIn("record_gate_state(", src)
                self.assertNotIn("last_gate_red = True", src)
                self.assertNotIn("last_gate_red = False", src)

    def test_the_plan_on_step_verdict_is_unchanged(self):
        """Only the recorded STATE uses the fuller reading. The step still advances or holds on
        completion_block_nudge, exactly as before — that was not measured and is not changed."""
        import inspect
        src = inspect.getsource(loop.Loop._verify_after_probe)
        self.assertIn("nudge = proberun.completion_block_nudge(outcome.report)", src)
        self.assertIn("passed=nudge is None", src)

    def test_the_stall_comparison_reads_the_previous_flag(self):
        """The mirror now runs BEFORE the stall check, so comparing against the live field would
        compare the new flag with itself and report a stall on every red gate."""
        import inspect
        src = inspect.getsource(loop.Loop._verify_after_probe)
        self.assertIn("prev_flag = sess.last_gate_flag", src)
        self.assertIn("if nudge and nudge == prev_flag:", src)


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


class ThePeriodicCheckInKeepsItsOneDifferenceTests(unittest.TestCase):
    """A periodic check-in is a real gate run — so it records the reading — but the coder has NOT
    claimed done, and letting its clean result set `gate_fresh` would pre-satisfy the completion
    backstop for a 'done' that arrives later. That single field is the reason this reader is not
    simply the shared one."""

    def _gs(self):
        gs = GuardState()
        gs.periodic_probe = True
        gs.gate_plan = object()
        gs.probe_call_id = "c1"
        return gs

    def _run(self, gs, err, ran=True):
        got = outcome(ran=ran)
        real_read, real_err = loop.read_gate, loop.gate_error_text
        loop.read_gate = lambda plan, probe, rlog: got
        loop.gate_error_text = lambda o: err
        try:
            return loop.guard_periodic_result(gs, {"messages": []}, _Rlog())
        finally:
            loop.read_gate, loop.gate_error_text = real_read, real_err

    def test_a_clean_check_in_does_not_mark_ground_truth_fresh(self):
        gs = self._gs()
        gs.gate_fresh = False
        self._run(gs, "")
        self.assertFalse(gs.gate_fresh)
        self.assertFalse(gs.last_gate_red)
        self.assertTrue(gs.last_gate_ran)

    def test_a_red_check_in_records_the_finding(self):
        gs = self._gs()
        out = self._run(gs, "cart.go:12: undefined: Total")
        self.assertIn("undefined: Total", out)
        self.assertTrue(gs.last_gate_red)
        self.assertIn("undefined: Total", gs.last_gate_flag)

    def test_a_check_in_that_could_not_run_says_nothing_and_records_that_it_did_not(self):
        gs = self._gs()
        gs.last_gate_red = True
        self.assertIsNone(self._run(gs, "", ran=False))
        self.assertTrue(gs.last_gate_red)      # no evidence either way
        self.assertFalse(gs.last_gate_ran)


if __name__ == "__main__":
    unittest.main()
