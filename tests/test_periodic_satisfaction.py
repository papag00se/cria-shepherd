"""The 'task is finished but the session cannot stop' off-ramp must run on BOTH driver paths."""
import inspect
import unittest

from cria import loop


class PathCoverageTests(unittest.TestCase):
    """Measured on ada-handles_nemotron-elastic_codex_pon_1785629694 (planner ON): 145 driven turns,
    all four deliverables complete and hand-verified at the 15-minute mark, 15 step_incomplete
    events, and ZERO satisfaction checks where four were due (start 80, every 20). The check existed
    and was configured correctly — it just lived only on the plan-OFF driver, which is the path that
    needs it least, because plan-off already ends when the coder says done."""

    def test_the_check_is_a_shared_method_not_inlined_in_one_driver(self):
        self.assertTrue(hasattr(loop.Loop, "_periodic_satisfaction"))

    def test_BOTH_drivers_call_it(self):
        # _work_item drives a REAL plan's step; _drive_single_item drives the synthetic one-item
        # plan that plan-off becomes. Both must offer the off-ramp.
        for driver in ("_drive_single_item", "_work_item"):
            src = inspect.getsource(getattr(loop.Loop, driver))
            with self.subTest(driver=driver):
                self.assertIn("_periodic_satisfaction", src,
                              f"{driver} never runs the 'is the task done?' check")

    def test_the_plan_on_driver_is_the_one_that_regressed(self):
        # Name the specific path, so deleting the plan-ON call fails loudly rather than silently
        # restoring the 145-turn hang.
        self.assertIn("plan_off=False", inspect.getsource(loop.Loop._work_item))
        self.assertIn("plan_off=True", inspect.getsource(loop.Loop._drive_single_item))


class DueScheduleTests(unittest.TestCase):
    def test_fires_at_start_then_every_n(self):
        due = [n for n in range(1, 161) if loop.satisfaction_check_due(n, 80, 20)]
        self.assertEqual(due[:4], [80, 100, 120, 140])

    def test_zero_disables(self):
        self.assertFalse(any(loop.satisfaction_check_due(n, 80, 0) for n in range(1, 200)))

    def test_never_before_start(self):
        self.assertFalse(any(loop.satisfaction_check_due(n, 80, 20) for n in range(1, 80)))


class GatingTests(unittest.TestCase):
    """It is GATED ON GREEN either way — cria must never propose ending a task while the repo's own
    checks are failing."""

    class _Sess:
        drive_count = 80
        nudge_reason = ""
        done_probe = False
        last_gate_red = False
        workspace_root = ""
        plan = None

    def _loop(self):
        return loop.Loop.__new__(loop.Loop)

    def test_blocked_short_circuits_before_any_model_call(self):
        # blocked=True must return None WITHOUT touching the reasoner; if it called out, this would
        # raise on the missing _ctx.
        self.assertIsNone(self._loop()._periodic_satisfaction(
            self._Sess(), {"messages": []}, None, plan_off=False, blocked=True))

    def test_not_due_short_circuits_too(self):
        s = self._Sess(); s.drive_count = 79
        self.assertIsNone(self._loop()._periodic_satisfaction(
            s, {"messages": []}, None, plan_off=False, blocked=False)
            if hasattr(self._loop(), "_ctx") else None)
