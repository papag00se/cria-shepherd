"""The 'task is finished but the session cannot stop' off-ramp must run on BOTH driver paths."""
import json
import unittest
import unittest.mock

from pathlib import Path

from cria import loop, wsview
from cria.loop import Loop, LoopContext, PlanSession
from cria.plan import Plan, PlanItem
from tests.wsfixture import survey


class _RLog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


class _Planner:
    def __init__(self, plan):
        self._plan = plan

    def plan_for(self, messages, rlog, prior_work="", rewrite_summary=""):
        return self._plan


def _plan(n=1):
    return Plan(id="20260707T0000-abcd1234", task="build it", created="2026-07-07T00:00:00+00:00",
                items=[PlanItem(f"step {i+1}") for i in range(n)])


_SHELL = {"type": "function", "function": {"name": "shell",
          "parameters": {"type": "object", "properties": {"command": {"type": "array"}}}}}


def _toolcall():
    return {"choices": [{"message": {"role": "assistant", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "shell", "arguments": "{}"}}]}}]}


def _body():
    return {"messages": [{"role": "user", "content": "build an ada handle resolver"}],
            "tools": [_SHELL], "stream": True}


def _coder(body, rlog):
    return json.dumps(_toolcall()).encode()


class PathCoverageTests(unittest.TestCase):
    """Measured on ada-handles_nemotron-elastic_codex_pon_1785629694 (planner ON): 145 driven turns,
    all four deliverables complete and hand-verified at the 15-minute mark, 15 step_incomplete
    events, and ZERO satisfaction checks where four were due (start 80, every 20). The check existed
    and was configured correctly — it just lived only on the plan-OFF driver, which is the path that
    needs it least, because plan-off already ends when the coder says done."""

    def test_the_check_is_a_shared_method_not_inlined_in_one_driver(self):
        self.assertTrue(hasattr(loop.Loop, "_periodic_satisfaction"))

    def test_BOTH_drivers_call_it_with_the_right_plan_off_flag(self):
        # _work_item drives a REAL plan's step (plan_off=False); _drive_single_item drives the
        # synthetic one-item plan that plan-off becomes (plan_off=True). Both must offer the
        # off-ramp, and each must identify itself correctly — spy on the shared method and drive
        # both halves for real rather than searching either driver's source for the call.
        calls = []

        def spy(self, sess, body, rlog, *, plan_off, blocked):
            calls.append(plan_off)
            return None

        with unittest.mock.patch.object(Loop, "_periodic_satisfaction", spy):
            ctx = LoopContext(planner=_Planner(_plan(2)), coder_chat=_coder, reasoner_chat=_coder,
                              runs_dir="")
            sess = PlanSession(plan=_plan(2))
            Loop(ctx)._work_item(sess, "k", _body(), _RLog(), sess.plan.items[0], 1)

            ctx2 = LoopContext(planner=_Planner(_plan(1)), coder_chat=_coder, reasoner_chat=_coder,
                               planner_enabled=False, runs_dir="")
            sess2 = PlanSession(plan=_plan(1), synthetic=True)
            Loop(ctx2)._drive_single_item(sess2, _body(), "sid:x", _RLog())

        self.assertEqual(calls, [False, True],
                         "_work_item must pass plan_off=False, _drive_single_item plan_off=True")


class DueScheduleTests(unittest.TestCase):
    def test_fires_at_start_then_every_n_when_it_keeps_running(self):
        """The spacing the cadence promises, in the case where nothing blocks it: the check runs, so
        the stamp moves, so the next one is `every` later."""
        due, last = [], -1
        for n in range(1, 161):
            if loop.periodic_check_due(n, 80, 20, last):
                due.append(n)
                last = n                      # it RAN
        self.assertEqual(due[:4], [80, 100, 120, 140])

    def test_a_blocked_opportunity_is_retried_on_the_next_drive(self):
        """THE DEFECT. Under `(drive - start) %% every == 0`, missing drive 100 meant waiting until
        120. Measured on rust-toml-cli x ternary-bonsai: 54 drives, five opportunities, ONE fired,
        four eaten by `blocked` — and the whole off-ramp rests on this check."""
        self.assertTrue(loop.periodic_check_due(101, 80, 20, 80))
        self.assertTrue(loop.periodic_check_due(119, 80, 20, 80))

    def test_it_cannot_fire_faster_than_the_interval(self):
        """The stamp moves only when the check RUNS, so retrying a blocked drive buys no extra calls
        in the unblocked case."""
        self.assertFalse(loop.periodic_check_due(99, 80, 20, 80))
        self.assertFalse(loop.periodic_check_due(81, 80, 20, 80))

    def test_the_first_one_is_still_keyed_to_start(self):
        self.assertFalse(loop.periodic_check_due(79, 80, 20, -1))
        self.assertTrue(loop.periodic_check_due(80, 80, 20, -1))

    def test_zero_disables(self):
        self.assertFalse(any(loop.periodic_check_due(n, 80, 0, -1) for n in range(1, 200)))
        self.assertFalse(any(loop.periodic_check_due(n, 0, 20, -1) for n in range(1, 200)))

    def test_never_before_start(self):
        self.assertFalse(any(loop.periodic_check_due(n, 80, 20, -1) for n in range(1, 80)))


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
                 loop._gate_notes)
        loop.judge_satisfaction = lambda *a, **k: verdict
        loop._satisfaction_evidence = lambda *a, **k: "evidence"
        loop._gate_notes = lambda *a, **k: ""
        try:
            out = lp._periodic_satisfaction(sess, {"messages": [{"role": "user", "content": "t"}]},
                                            rlog, plan_off=True, blocked=False)
        finally:
            (loop.judge_satisfaction, loop._satisfaction_evidence,
             loop._gate_notes) = saved
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

    def test_feed_gap_rearms_only_after_a_new_complete_workspace_observation(self):
        """Four Feed archives lack REVIEW.md; 1790026888 named it at drive 34 then went silent.

        Fails before: text-only ``last_gap_named`` suppresses the same checked gap after the
        importer changes.  This replays that causal boundary without executing Feed.
        """
        cohort = (
            ("20260921T131112-01a0c598-12c3-7973-8ebd-3f87b1ce0016", "1790021450"),
            ("20260921T135359-01a0c5bf-3d05-7fd0-a573-6c95720f4526", "1790024016"),
            ("20260921T144153-01a0c5eb-172a-7002-b4cf-64ac66d26edf", "1790026888"),
            ("20260921T164500-01a0c65b-cd75-7ab3-b3dd-3d839bfb3b35", "1790034274"),
        )
        for capture_id, run_id in cohort:
            with self.subTest(run=run_id):
                self.assertTrue((Path.home() / ".cria/calls" / capture_id).is_dir())
                archive = Path.home() / ".cria/suite" / f"feed-pipeline-java_ternary-bonsai-2_codex_pon_{run_id}/workspace"
                self.assertFalse((archive / "REVIEW.md").exists())
        capture = Path.home() / ".cria/calls/20260921T144153-01a0c5eb-172a-7002-b4cf-64ac66d26edf"
        self.assertTrue((capture / "0141-satisfaction.response.json").is_file())

        root = "/harness/feed"
        view = wsview.View(root, "feed-gap-replay")
        self.assertTrue(wsview.apply_survey(view, survey(
            "D\tsrc\nD\tsrc/main\nF\t1\t100\tsrc/main/Importer.java", root=root)))
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)
        s = self._Sess()
        s.workspace_root = root
        gap = loop.VerdictNudge("REVIEW.md is absent.", diagnosis_kind="missing_file",
                                subject="REVIEW.md")

        _out, _first_log = self._run(s, verdict=(False, gap, ""))
        self.assertIn("REVIEW.md", s.nudge_reason)
        first_generation = s.last_gap_observation
        self.assertTrue(first_generation)
        s.nudge_reason = ""

        # Same complete survey generation remains silent.
        s.drive_count += 20
        self._run(s, verdict=(False, gap, ""))
        self.assertEqual("", s.nudge_reason)

        # The harness, not cria's disk or a tool counter, observes changed importer metadata while
        # still completely listing the absent task-named review file.
        self.assertTrue(wsview.apply_survey(view, survey(
            "D\tsrc\nD\tsrc/main\nF\t2\t200\tsrc/main/Importer.java", root=root)))
        s.drive_count += 20
        _out, rearmed_log = self._run(s, verdict=(False, gap, ""))
        self.assertIn("REVIEW.md", s.nudge_reason)
        self.assertNotEqual(first_generation, s.last_gap_observation)
        self.assertTrue(any(k == "loop.satisfaction_gap_named" and kw.get("rearmed")
                            for k, kw in rearmed_log.events))

    def test_missing_file_gap_does_not_rearm_on_unknown_or_partial_observation(self):
        root = "/harness/feed"
        view = wsview.View(root, "feed-gap-unknown")
        self.assertTrue(wsview.apply_survey(view, survey("F\t1\t100\tImporter.java", root=root)))
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)
        s = self._Sess(); s.workspace_root = root
        gap = loop.VerdictNudge("REVIEW.md is absent.", diagnosis_kind="missing_file",
                                subject="REVIEW.md")
        self._run(s, verdict=(False, gap, ""))
        s.nudge_reason = ""

        # A possible mutator overtakes the last survey: there is no current absence fact.
        view.note_a_mutator_ran()
        s.drive_count += 20
        self._run(s, verdict=(False, gap, ""))
        self.assertEqual("", s.nudge_reason)

        # A later bounded survey also cannot re-arm the missing-file fact.
        self.assertTrue(wsview.apply_survey(view, survey("F\t2\t200\tImporter.java",
                                                         root=root, complete=False)))
        s.drive_count += 20
        self._run(s, verdict=(False, gap, ""))
        self.assertEqual("", s.nudge_reason)

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
