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

import dataclasses
import json
import unittest

from cria import loop
from cria.loop import Loop, PlanSession
from cria.plan import Plan, PlanItem

from test_loop import _ctx, _Rlog


def _step_plan(n=1, *, all_done=False):
    items = [PlanItem(f"step {i + 1}") for i in range(n)]
    for it in items:
        it.done = all_done
    return Plan(id="x", task="t", created="c", items=items)


def _reasoner(done=True):
    """A step critic that always answers the same way — the fixture varies the SESSION state,
    not the verdict, so what's under test is whether the check ran/stamped at all."""
    def chat(body, rlog):
        return json.dumps({"choices": [{"message": {"content": json.dumps(
            {"done": done, "reason": "r", "proposed_fix": ""})}}]}).encode()
    return chat


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
        real check a whole interval out, which is the same class of loss as the one being fixed —
        driven for real: a due drive with every step already done must leave the stamp untouched."""
        sess = PlanSession(plan=_step_plan(1, all_done=True))
        sess.drive_count = loop.STEP_CHECK_EVERY
        sess.step_checked_drive = -1
        L = Loop(_ctx(None, _reasoner(), sess.plan))
        out = L._periodic_step_check(sess, "k", {"messages": []}, 1, 1, _Rlog())
        self.assertIsNone(out)
        self.assertEqual(sess.step_checked_drive, -1, "no open step: the opportunity is not spent")


class OneNumberHasOneOwnerTests(unittest.TestCase):
    def test_the_step_check_no_longer_reads_the_gates_countdown_to_decide(self):
        """Behavioural: `coder_turns` must not be part of the DUE decision any more — the old bug
        was `step_checked_turn == coder_turns`, true forever once the gate's countdown first hit
        12. Hold drive_count/step_checked_drive fixed at a due tick and sweep coder_turns across
        the gate's own range and past it; the check must fire every time, unaffected."""
        for turns in (0, 1, loop.GATE_EVERY_CODER_TURNS - 1, loop.GATE_EVERY_CODER_TURNS, 999):
            with self.subTest(turns=turns):
                sess = PlanSession(plan=_step_plan(1, all_done=False))
                sess.drive_count = loop.STEP_CHECK_EVERY
                sess.step_checked_drive = -1
                sess.coder_turns = turns
                L = Loop(_ctx(None, _reasoner(True), sess.plan))
                L._periodic_step_check(sess, "k", {"messages": []}, 1, 1, _Rlog())
                self.assertEqual(sess.step_checked_drive, loop.STEP_CHECK_EVERY,
                                 "the check must fire on the drive cadence alone")

    def test_the_removed_field_stays_removed(self):
        """`step_checked_turn` was the second, colliding owner of the same fact. A namespace check
        beats a source-text search — rename-proof and comment-proof."""
        self.assertNotIn("step_checked_turn", {f.name for f in dataclasses.fields(PlanSession)})

    def test_both_periodic_checks_share_the_one_predicate(self):
        """Structural: no fixture exercises 'this function calls that one' directly, but the
        function's own compiled bytecode names what it references — a namespace check on the
        code object, immune to a comment merely mentioning the name."""
        for fn in (loop.Loop._periodic_step_check, loop.Loop._periodic_satisfaction):
            with self.subTest(fn=fn.__name__):
                self.assertIn("periodic_check_due", fn.__code__.co_names)

    def test_the_gate_still_owns_its_countdown(self):
        """Nothing here takes the reset away — `coder_turns` is the gate's, and stays the gate's.
        Behavioural: drive it past the threshold and read the state back."""
        gs = loop.GuardState()
        gs.coder_turns = loop.GATE_EVERY_CODER_TURNS
        loop.guard_periodic_gate(gs, {"messages": []}, _Rlog(), workspace_root=None)
        self.assertEqual(gs.coder_turns, 0)


class TheEventCarriesBothClocksTests(unittest.TestCase):
    def test_the_ratio_of_drives_to_acting_turns_is_recorded_not_argued(self):
        """A drive is the same event or slightly more often than an acting turn, and the exact ratio
        decides whether 12 is still far above the median of 5. #12: read it off the event —
        behaviourally, the emitted numbers must track the REAL session state, not a placeholder:
        two different (drive, turns) pairs must show up as two different emitted pairs."""
        seen = []
        for drive, turns in ((loop.STEP_CHECK_EVERY, 3), (loop.STEP_CHECK_EVERY * 2, 47)):
            sess = PlanSession(plan=_step_plan(1, all_done=False))
            sess.drive_count = drive
            sess.step_checked_drive = -1  # never checked yet → due once drive_count >= STEP_CHECK_EVERY
            sess.coder_turns = turns
            rlog = _Rlog()
            L = Loop(_ctx(None, _reasoner(True), sess.plan))
            L._periodic_step_check(sess, "k", {"messages": []}, 1, 1, rlog)
            evt = next(kw for k, kw in rlog.events if k == "loop.periodic_step_check")
            seen.append((evt["drive"], evt["turns"]))
        self.assertEqual(seen, [(loop.STEP_CHECK_EVERY, 3), (loop.STEP_CHECK_EVERY * 2, 47)])


if __name__ == "__main__":
    unittest.main()
