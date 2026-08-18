"""The periodic step check fired once per SESSION, at turn 12, and never again.

READ OFF THE LOGS, 2026-08-18 — every `loop.periodic_step_check` event on the box, 177 sessions:

    21 events. Every one of them `turns=12`. At most one per session.
    Not one at 24, 36 or 48.

The clearest case is session `01a006c7`: 89 coder calls and **3 completed gate cycles** before the
plan-off hand-back, and exactly **one** step check. Its own method comment costs the mechanism at
"one judge call per twelve turns"; it was delivering one per session.

TWO THINGS TOGETHER, AND NEITHER ALONE. `guard_periodic_gate` owns `coder_turns` as a COUNTDOWN and
zeroes it every `GATE_EVERY_CODER_TURNS` (15) — so 12 is the only multiple of 12 that counter can
ever hold. The once-per-tick memo beside it then read `step_checked_turn == coder_turns`, which is
true forever once the first fire has stamped 12. A memo written for a counter that only climbs
becomes a permanent refusal on a counter that resets.

This is the defect `periodic_check_due` was written for one commit earlier, on the satisfaction
check, and its docstring named this as the sibling. The fix is to stop having two owners for one
number (#23): the gate keeps its countdown, and the step check reads `drive_count`, the monotonic
clock the satisfaction check already reads.

The mechanism is OBSERVE-ONLY, so what this restores is the MEASUREMENT — the `done=true` events
across real runs that its own "WHAT FLIPS IT" note requires before it may ever advance a step. One
sample per session, all at the same tick, could never accumulate into that decision.
"""

import unittest

from cria import loop


class TheGatesResetNoLongerEndsTheCheckTests(unittest.TestCase):
    """Replayed against the real cadence: the gate zeroes `coder_turns` at 15, forever."""

    def _fires(self, drives, *, gate_every=loop.GATE_EVERY_CODER_TURNS):
        """Which drives the step check runs on, with the gate zeroing the turn counter as it does
        live. Returns (fires_on_the_turn_counter, fires_on_the_drive_counter)."""
        by_turn, by_drive = [], []
        turns, memo_turn = 0, -1
        stamp = -1
        for d in range(1, drives + 1):
            turns += 1
            if turns >= gate_every:          # guard_periodic_gate: fire and zero the countdown
                turns = 0
            if turns > 0 and turns % loop.STEP_CHECK_EVERY == 0 and memo_turn != turns:
                memo_turn = turns
                by_turn.append(d)
            if loop.periodic_check_due(d, loop.STEP_CHECK_EVERY, loop.STEP_CHECK_EVERY, stamp):
                stamp = d
                by_drive.append(d)
        return by_turn, by_drive

    def test_the_old_trigger_fired_exactly_once_in_ninety_drives(self):
        """Session 01a006c7's shape. This is the defect, stated as an executable fact."""
        by_turn, _ = self._fires(90)
        self.assertEqual(len(by_turn), 1, "the logs show one fire per session; the replay must agree")
        self.assertEqual(by_turn, [12])

    def test_it_now_fires_on_a_cadence_through_the_whole_session(self):
        _, by_drive = self._fires(90)
        self.assertEqual(by_drive, [12, 24, 36, 48, 60, 72, 84])

    def test_the_gates_reset_cannot_reach_the_new_stamp(self):
        """The point of the fix: whatever the gate does to its own countdown, the cadence holds."""
        for gate_every in (3, 7, 15, 40):
            with self.subTest(gate_every=gate_every):
                _, by_drive = self._fires(60, gate_every=gate_every)
                self.assertEqual(by_drive, [12, 24, 36, 48, 60])


class ItCannotFireMoreOftenThanTheCadenceTests(unittest.TestCase):
    """The cost this paces is a judge call. A fix that bought extra ones would be a different bug."""

    def test_never_twice_inside_one_interval(self):
        stamp, fires = -1, []
        for d in range(1, 200):
            if loop.periodic_check_due(d, loop.STEP_CHECK_EVERY, loop.STEP_CHECK_EVERY, stamp):
                stamp = d
                fires.append(d)
        self.assertTrue(all(b - a >= loop.STEP_CHECK_EVERY for a, b in zip(fires, fires[1:])))

    def test_nothing_before_the_first_interval(self):
        self.assertFalse(any(loop.periodic_check_due(d, loop.STEP_CHECK_EVERY,
                                                     loop.STEP_CHECK_EVERY, -1)
                             for d in range(1, loop.STEP_CHECK_EVERY)))

    def test_a_drive_with_no_open_step_does_not_spend_the_opportunity(self):
        """`sess.plan.current()` is None once every item is done. Stamping there would push the next
        real check a whole interval out, which is the same class of loss as the one being fixed."""
        import inspect
        src = inspect.getsource(loop.Loop._periodic_step_check)
        due = src.index("periodic_check_due")
        item = src.index("item = sess.plan.current()")
        stamp = src.index("sess.step_checked_drive = sess.drive_count")
        self.assertLess(due, item, "the cadence is tested first")
        self.assertLess(item, stamp, "the stamp must land after the open-step check, not before")


class OneNumberHasOneOwnerTests(unittest.TestCase):
    def test_the_step_check_no_longer_reads_the_gates_countdown_to_decide(self):
        import inspect
        src = inspect.getsource(loop.Loop._periodic_step_check)
        head = src[:src.index("sess.step_checked_drive")]
        self.assertNotIn("coder_turns %", head)
        self.assertNotIn("step_checked_turn", src)

    def test_both_periodic_checks_share_the_one_predicate(self):
        import inspect
        for fn in (loop.Loop._periodic_step_check, loop.Loop._periodic_satisfaction):
            with self.subTest(fn=fn.__name__):
                self.assertIn("periodic_check_due", inspect.getsource(fn))

    def test_the_gate_still_owns_its_countdown(self):
        """Nothing here takes the reset away — `coder_turns` is the gate's, and stays the gate's."""
        import inspect
        self.assertIn("gs.coder_turns = 0", inspect.getsource(loop.guard_periodic_gate))


class TheEventCarriesBothClocksTests(unittest.TestCase):
    def test_the_ratio_of_drives_to_acting_turns_is_recorded_not_argued(self):
        """A drive is the same event or slightly more often than an acting turn, and the exact ratio
        decides whether 12 is still far above the median of 5. #12: read it off the event."""
        import inspect
        src = inspect.getsource(loop.Loop._periodic_step_check)
        emit = src[src.index('rlog.emit("loop.periodic_step_check"'):]
        self.assertIn("drive=sess.drive_count", emit)
        self.assertIn("turns=sess.coder_turns", emit)


if __name__ == "__main__":
    unittest.main()
