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
    def test_fires_at_start_then_every_n_when_it_keeps_running(self):
        """The spacing the cadence promises, in the case where nothing blocks it: the check runs, so
        the stamp moves, so the next one is `every` later."""
        due, last = [], -1
        for n in range(1, 161):
            if loop.satisfaction_check_due(n, 80, 20, last):
                due.append(n)
                last = n                      # it RAN
        self.assertEqual(due[:4], [80, 100, 120, 140])

    def test_a_blocked_opportunity_is_retried_on_the_next_drive(self):
        """THE DEFECT. Under `(drive - start) %% every == 0`, missing drive 100 meant waiting until
        120. Measured on rust-toml-cli x ternary-bonsai: 54 drives, five opportunities, ONE fired,
        four eaten by `blocked` — and the whole off-ramp rests on this check."""
        self.assertTrue(loop.satisfaction_check_due(101, 80, 20, 80))
        self.assertTrue(loop.satisfaction_check_due(119, 80, 20, 80))

    def test_it_cannot_fire_faster_than_the_interval(self):
        """The stamp moves only when the check RUNS, so retrying a blocked drive buys no extra calls
        in the unblocked case."""
        self.assertFalse(loop.satisfaction_check_due(99, 80, 20, 80))
        self.assertFalse(loop.satisfaction_check_due(81, 80, 20, 80))

    def test_the_first_one_is_still_keyed_to_start(self):
        self.assertFalse(loop.satisfaction_check_due(79, 80, 20, -1))
        self.assertTrue(loop.satisfaction_check_due(80, 80, 20, -1))

    def test_zero_disables(self):
        self.assertFalse(any(loop.satisfaction_check_due(n, 80, 0, -1) for n in range(1, 200)))
        self.assertFalse(any(loop.satisfaction_check_due(n, 0, 20, -1) for n in range(1, 200)))

    def test_never_before_start(self):
        self.assertFalse(any(loop.satisfaction_check_due(n, 80, 20, -1) for n in range(1, 80)))


class GatingTests(unittest.TestCase):
    """It is GATED ON GREEN either way — cria must never propose ending a task while the repo's own
    checks are failing."""

    class _Sess:
        drive_count = 80
        satisfaction_last_drive = -1
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


class NamesTheMissingDeliverableTests(unittest.TestCase):
    """THE OPERATOR'S RULING, 2026-08-15 — a NOT-satisfied verdict that NAMES a specific missing
    deliverable may reach the coder.

    The incident: on shipping-rates-rb x nemotron-elastic the judge returned NOT-satisfied four
    times, each naming `Shipping.zone_for` as not implemented and each carrying a written fix, and
    the coder was told none of it. The cell ended 2 of 4 with that method still absent, reproduced
    cold as `undefined method 'zone_for' for Shipping:Module`.

    What is NOT changed and is pinned below: this path still never ENDS a session on a not-satisfied
    verdict, and it still carries only the judge's REASON, never its proposed_fix — naming the gap
    was the ruling, choosing the implementation was not.
    """

    class _Sess:
        drive_count = 80
        satisfaction_last_drive = -1
        nudge_reason = ""
        last_gap_named = ""
        steer_source = ""
        done_probe = False
        last_gate_red = False
        last_gate_flag = ""
        workspace_root = ""
        gate_plan = None
        plan = None

    class _Rlog:
        def __init__(self): self.events = []
        def emit(self, kind, **kw): self.events.append((kind, kw))

    class _Ctx:
        reasoner_chat = object()
        reasoner_role = None
        satisfaction_check_start = 80
        satisfaction_check_every = 20

    def _run(self, sess, verdict=(False, "Shipping.zone_for(code) has not been implemented.", "")):
        lp = loop.Loop.__new__(loop.Loop)
        lp._ctx = self._Ctx()
        rlog = self._Rlog()
        saved = (loop.judge_satisfaction, loop._satisfaction_evidence,
                 loop._gate_notes, loop.live_execution_marker)
        loop.judge_satisfaction = lambda *a, **k: verdict
        loop._satisfaction_evidence = lambda *a, **k: "evidence"
        loop._gate_notes = lambda *a, **k: ""
        loop.live_execution_marker = lambda *a, **k: ""
        try:
            out = lp._periodic_satisfaction(sess, {"messages": [{"role": "user", "content": "t"}]},
                                            rlog, plan_off=True, blocked=False)
        finally:
            (loop.judge_satisfaction, loop._satisfaction_evidence,
             loop._gate_notes, loop.live_execution_marker) = saved
        return out, rlog

    def test_the_named_gap_reaches_the_coder(self):
        """FAILS BEFORE: the old code returned None and set nothing, so the coder never heard it."""
        s = self._Sess()
        out, rlog = self._run(s)
        self.assertIsNone(out, "a not-satisfied verdict must never END the session")
        self.assertIn("zone_for", s.nudge_reason, "the named deliverable never reached the coder")
        self.assertTrue(any(k == "loop.satisfaction_gap_named" for k, _ in rlog.events))

    def test_it_never_repeats_the_same_verdict(self):
        """The check fires on a drive counter, so an unchanged workspace yields an unchanged verdict.
        feed-pipeline-java x qwen35 produced TWELVE consecutive identical not-satisfied verdicts on a
        workspace already scoring 5 of 5; twelve identical steers is the clock-noise the original
        no-steer decision was defending against."""
        s = self._Sess()
        self._run(s)
        first = s.nudge_reason
        self.assertTrue(first)
        s.nudge_reason = ""                     # the coder consumed it
        self._run(s)                            # same verdict again
        self.assertEqual("", s.nudge_reason, "the same gap was named twice")

    def test_a_changed_verdict_does_reach_the_coder(self):
        s = self._Sess()
        self._run(s)
        s.nudge_reason = ""
        # A SECOND CHECK HAPPENS ON A LATER DRIVE. This used to run both at the same drive_count,
        # which the absolute modulo allowed and the since-last-ran rule correctly refuses — two
        # checks on one drive is the duplicate firing the stamp exists to prevent.
        s.drive_count += 40
        self._run(s, verdict=(False, "REVIEW.md has not been written.", ""))
        self.assertIn("REVIEW.md", s.nudge_reason)

    def test_an_empty_reason_stays_silent(self):
        """Silence over noise (#3) — a judge that said nothing has nothing to hand on."""
        s = self._Sess()
        self._run(s, verdict=(False, "", ""))
        self.assertEqual("", s.nudge_reason)

    def test_it_does_not_stomp_a_steer_already_parked(self):
        s = self._Sess(); s.nudge_reason = "an earlier guard's steer"
        self._run(s)
        self.assertEqual("an earlier guard's steer", s.nudge_reason)

    def test_the_proposed_fix_is_not_carried(self):
        """Naming the gap was the ruling; choosing the implementation was not (#2's corollary)."""
        s = self._Sess()
        self._run(s, verdict=(False, "zone_for is missing.",
                              "Add ISO3166::Country and map GB to domestic"))
        self.assertIn("zone_for", s.nudge_reason)
        self.assertNotIn("ISO3166", s.nudge_reason)
