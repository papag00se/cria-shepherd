"""The off-ramp check ran once in 86 calls, and the reason was arithmetic.

`rust-toml-cli × ternary-bonsai`, 2026-08-17. Cadence 17 then every 8. The run made **54 drives**,
so under `(drive_count - start) % every == 0` there were five opportunities — 17, 25, 33, 41, 49.

**One fired. Four were eaten by `blocked`.**

`blocked` is cria deciding "not this turn", recomputed on every drive:

    blocked = bool(steer is not None or rewritten or sess.done_probe or sess.last_gate_red)

None of those four is wrong. A red gate genuinely must stop cria proposing that a task is finished;
the others mean something else is already speaking this turn. **The defect is what a block COST.**
An absolute modulo makes one drive in `every` an opportunity, so landing on a blocked one pushed the
next chance a full interval away — and that run carried 20 harness compactions and 39 gate runs, so
hitting a blocker on any given drive was likely rather than rare.

The check the whole off-ramp rests on therefore ran once, at drive 17, before the last deliverable
existed. The model finished the work at 22:47 and volunteered "Done." at 23:20 — thirty-three
minutes in which the check was due four times and asked nothing.

Measuring from when the check last RAN retries on the next unblocked drive instead. It cannot fire
faster than `every`, because the stamp moves only when the check executes — so this closes the gap
without buying a single extra call in the unblocked case.

This is the same shape the anomaly sweep found in the periodic STEP check, which triggers on an
exact modulo against a counter another guard zeroes from outside: **1,147 gate checks against 14
step checks** in the logs. One defect, two mechanisms.

ALSO FIXED: cria recorded nothing when the check did not run. "It fired once in 86 calls" could not
be told from "it was only due once" without reconstructing the drive sequence by hand from the
captures afterwards (#12). A lost opportunity is now an event.
"""

import unittest

from cria import loop


class ABlockedOpportunityIsRetriedTests(unittest.TestCase):
    def test_the_measured_run(self):
        """54 drives, cadence 17/8, blocked on every opportunity but the first. The old rule gave
        five chances; the new one keeps offering until the check actually runs."""
        old = [n for n in range(1, 55) if n >= 17 and (n - 17) % 8 == 0]
        self.assertEqual(old, [17, 25, 33, 41, 49])

        offered, last = [], -1
        for n in range(1, 55):
            if loop.satisfaction_check_due(n, 17, 8, last):
                offered.append(n)
                if n == 17:          # only the first one was unblocked
                    last = n
        self.assertEqual(offered[:3], [17, 25, 26])
        self.assertGreater(len(offered), len(old))

    def test_it_still_cannot_fire_faster_than_the_interval(self):
        """The stamp moves only when the check RUNS, so retrying buys nothing in the unblocked case."""
        ran, last = [], -1
        for n in range(1, 55):
            if loop.satisfaction_check_due(n, 17, 8, last):
                ran.append(n)
                last = n
        self.assertEqual(ran, [17, 25, 33, 41, 49])

    def test_the_first_one_is_keyed_to_start(self):
        self.assertFalse(loop.satisfaction_check_due(16, 17, 8, -1))
        self.assertTrue(loop.satisfaction_check_due(17, 17, 8, -1))

    def test_zero_still_disables_either_way(self):
        self.assertFalse(loop.satisfaction_check_due(999, 0, 8, -1))
        self.assertFalse(loop.satisfaction_check_due(999, 17, 0, -1))


class TheStampMovesOnlyWhenItRunsTests(unittest.TestCase):
    class _Sess:
        drive_count = 40
        satisfaction_last_drive = -1
        nudge_reason = ""
        done_probe = False
        last_gate_red = False
        workspace_root = ""
        plan = None

    def _loop(self):
        return loop.Loop.__new__(loop.Loop)

    def test_a_blocked_turn_does_not_consume_the_opportunity(self):
        """If `blocked` moved the stamp, a busy stretch would silently reset the clock and the
        check would be pushed out exactly as far as the old modulo pushed it."""
        s = self._Sess()
        self.assertIsNone(self._loop()._periodic_satisfaction(
            s, {"messages": []}, None, plan_off=True, blocked=True))
        self.assertEqual(s.satisfaction_last_drive, -1, "a block consumed the opportunity")

    def test_blocked_returns_before_touching_anything_else(self):
        """The fake Loop has no `_ctx`; reaching config would raise. Blocked must be the first
        word, not a term in a longer condition."""
        self.assertIsNone(self._loop()._periodic_satisfaction(
            self._Sess(), {"messages": []}, None, plan_off=True, blocked=True))


class ALostOpportunityIsAnEventTests(unittest.TestCase):
    class _Rlog:
        phase = "test"

        def __init__(self):
            self.events = []

        def emit(self, name, **k):
            self.events.append((name, k))

    def test_a_block_is_recorded_with_the_drive_it_happened_on(self):
        s = TheStampMovesOnlyWhenItRunsTests._Sess()
        rlog = self._Rlog()
        loop.Loop.__new__(loop.Loop)._periodic_satisfaction(
            s, {"messages": []}, rlog, plan_off=True, blocked=True)
        names = [n for n, _ in rlog.events]
        self.assertIn("loop.satisfaction_blocked", names)
        payload = dict(rlog.events[0][1])
        self.assertEqual(payload["drive"], s.drive_count)
        self.assertEqual(payload["last_ran"], -1)


if __name__ == "__main__":
    unittest.main()
