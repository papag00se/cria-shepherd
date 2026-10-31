"""Two bounds that exist so a loop must end could be set to infinity and the suite stayed green.

A mutation pass set every module-level constant in the repo to triple its value and ran the suite:
90 of 145 survived. Most are cadences and window sizes where any value is defensible. Two are not.

`MAX_COMPLETION_CHECKS` is one of the two acknowledged fail-open exits AGENTS.md names by name — its
own comment says it exists so "a task the coder genuinely can't finish still completes rather than
looping forever", because "cria DRIVES the plan loop, so it must bound the retries itself". It
survives `10**9`.

`RED_HOLDS_SATISFACTION_FOR` decides how long a red gate may hold the whole-task question back. Its
comment reasons about the third gate specifically: "two gates with the same finding-set is already
the signal `gate_stall` carries; a third says the red is not moving". At `10**9` the hold never ends
and the whole-task question is never asked.

Their neighbours in the same file ARE pinned — `GATE_EVERY_CODER_TURNS`, `STEP_CHECK_EVERY`,
`WHEEL_SPIN_WRITES`, `MAX_TRUNCATION_RETRIES`, `MAX_RUMINATION_RETRIES`, `MAX_UNEXECUTED_NUDGES`,
`REPEAT_FINGERPRINT_N` are all killed by existing tests — so this is a gap, not a policy.

These pin the PROPERTY, not the number: a bound whose job is to end something must be finite and
small enough to be reached inside a real session, and the behaviour at the boundary must actually
change. Any value in the range still passes; infinity does not.
"""

import unittest

from cria import loop


class ACompletionRetryLoopMustEndTests(unittest.TestCase):
    def test_the_retry_bound_is_reachable_inside_a_real_run(self):
        """A 30-minute cell does not run a thousand completion checks. A bound it cannot reach is
        the same as no bound at all (#13 — fail closed on completion means STOP, not spin)."""
        self.assertGreaterEqual(loop.MAX_COMPLETION_CHECKS, 1)
        self.assertLessEqual(loop.MAX_COMPLETION_CHECKS, 20)


class ARedGateMayNotHoldForever(unittest.TestCase):
    def _blocked(self, stall):
        return loop._satisfaction_blocker(steer="", rewritten=False, done_probe=False,
                                          gate_red=True, gate_stall=stall)

    def test_a_moving_red_holds_the_whole_task_question(self):
        self.assertEqual(self._blocked(0), "gate-red")

    def test_a_red_that_stops_moving_releases_it(self):
        """The property the constant encodes: there is a stall count at which the hold ends."""
        self.assertEqual(self._blocked(loop.RED_HOLDS_SATISFACTION_FOR), "")

    def test_the_release_point_is_reachable_inside_a_real_run(self):
        self.assertGreaterEqual(loop.RED_HOLDS_SATISFACTION_FOR, 1)
        self.assertLessEqual(loop.RED_HOLDS_SATISFACTION_FOR, 10)

    def test_the_other_blockers_still_outrank_it(self):
        """Order matters: a steer, a rewritten history and an in-flight probe each say the question
        cannot be asked YET, for a reason that is not the gate's colour."""
        self.assertEqual(loop._satisfaction_blocker(steer="x", rewritten=False, done_probe=False,
                                                    gate_red=True, gate_stall=99), "steer")
        self.assertEqual(loop._satisfaction_blocker(steer="", rewritten=True, done_probe=False,
                                                    gate_red=False, gate_stall=99),
                         "history-rewritten")
        self.assertEqual(loop._satisfaction_blocker(steer="", rewritten=False, done_probe=True,
                                                    gate_red=False, gate_stall=99),
                         "done-probe-in-flight")


if __name__ == "__main__":
    unittest.main()
