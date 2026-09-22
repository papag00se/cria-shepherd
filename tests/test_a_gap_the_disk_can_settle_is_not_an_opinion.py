"""The periodic path consumes the single provenance owner's result without re-judging it."""

import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cria import loop, prompts, upstream


class _NullRlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **_fields):
        self.events.append(kind)


def _sess():
    return SimpleNamespace(nudge_reason="", last_gap_named="", steer_source="",
                           workspace_root="/w", drive_count=40, satisfaction_last_drive=0,
                           plan=None, gate_plan=None, last_gate_flag="", done_probe=False)


class _Ctx:
    reasoner_chat = object()
    reasoner_role = object()
    satisfaction_check_start = 1
    satisfaction_check_every = 1
    self_compact = False


def _drive(reason, *, previous=""):
    sess, rlog = _sess(), _NullRlog()
    sess.last_gap_named = previous
    lp = loop.Loop.__new__(loop.Loop)
    lp._ctx = _Ctx()
    lp._reasoner = lambda: (None, None)
    body = {"messages": [{"role": "user", "content": "Build it."}], "tools": []}
    with mock.patch.object(loop, "judge_satisfaction", return_value=(False, reason, "")), \
         mock.patch.object(loop, "_satisfaction_evidence", return_value="ev"), \
         mock.patch.object(loop, "_gate_notes", return_value=""), \
         mock.patch.object(loop, "_history_root", return_value=("task", 0)), \
         mock.patch.object(loop, "_coder_tools_summary", return_value=""), \
         mock.patch.object(loop, "known_routes", return_value=""), \
         mock.patch.object(loop, "summarize") as extra_judge:
        lp._periodic_satisfaction(sess, body, rlog, plan_off=True, blocked=False)
    return sess, rlog, extra_judge


class PeriodicDiagnosisOwnershipTests(unittest.TestCase):
    def test_the_validated_diagnosis_is_delivered_without_a_second_judge(self):
        reason = ("The completion check remains open on this exact task requirement:\n"
                  "Add REPORT.md.\n\nCurrent evidence (workspace_absence):\n"
                  "The task-named file REPORT.md is not present in the current workspace.")
        sess, rlog, extra = _drive(reason)
        self.assertIn(reason, sess.nudge_reason)
        self.assertIn("loop.satisfaction_gap_named", rlog.events)
        extra.assert_not_called()

    def test_feed_capture_missing_file_gap_reaches_the_prepared_coder_wire(self):
        """Replay 1790034274's typed verdict through the next live frame and wire boundary.

        The old generic prompt fails this test: the instruction is absent after `_work_item()`
        constructs the next coder frame and `Upstream._prep()` serializes its final body.
        """
        capture = Path.home() / ".cria" / "calls" / "20260921T164500-01a0c65b-cd75-7ab3-b3dd-3d839bfb3b35"
        verdict = json.loads((capture / "0109-satisfaction.response.json").read_text())
        args = json.loads(verdict["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
        captured = json.loads((capture / "0112-coder-s3.json").read_text())["body"]
        task = next(m["content"] for m in captured["messages"]
                    if m.get("role") == "user" and str(m.get("content", "")).startswith("Fix these three"))
        active = re.search(r"Prioritize this step \(3 of 6\):\n\n(.*?)\n\nOnce it is complete",
                           captured["messages"][0]["content"], re.S)
        self.assertIsNotNone(active)
        evidence = prompts.render(
            "negative_diagnosis", task_quote=args["task_quote"],
            source=args["evidence_source"],
            evidence=prompts.render("negative_diagnosis_missing_file", subject=args["subject"]))
        gap = loop.VerdictNudge(evidence, diagnosis_kind=args["diagnosis_kind"], subject=args["subject"])
        expected_nudge = prompts.render(
            "nudge", reason=prompts.render("periodic_missing_file_gap", reason=gap,
                                             subject=args["subject"]))
        framed = []

        def coder_chat(body, _rlog):
            framed.append(body)
            return json.dumps({"choices": [{"message": {"role": "assistant", "tool_calls": [{
                "id": "read", "type": "function", "function": {"name": "read_file",
                "arguments": '{"path":"README.md"}'}}]}}]}).encode()

        plan = loop.Plan(id="feed-wire-replay", task=task, created="2026-09-21", items=[
            loop.PlanItem(active.group(1)), loop.PlanItem("run the requested tests"),
            loop.PlanItem("write the requested review"), loop.PlanItem("verify the deliverable"),
            loop.PlanItem("finish remaining task work"), loop.PlanItem("final verification"),
        ])
        sess = loop.PlanSession(plan=plan, drive_count=1)
        driver = loop.Loop(loop.LoopContext(
            planner=None, coder_chat=coder_chat, reasoner_chat=None, runs_dir="",
            self_compact=False, focus_trim=False, assists=False,
            satisfaction_check_start=1, satisfaction_check_every=100))
        rlog = _NullRlog()
        # The captured verdict enters through the production periodic-satisfaction owner, rather
        # than a test-crafted pending nudge, before `_work_item` builds the next coder body.
        with (mock.patch.object(loop, "judge_satisfaction", return_value=(False, gap, "")),
              mock.patch.object(loop, "_satisfaction_evidence", return_value=""),
              mock.patch.object(loop, "_gate_notes", return_value="")):
            driver._periodic_satisfaction(sess, captured, rlog, plan_off=False, blocked=False)
        self.assertEqual(sess.nudge_reason, expected_nudge.removeprefix("⟦ctx:steer⟧ "))
        driver._work_item(sess, "feed-wire-replay", captured, rlog, plan.current(), 1)
        self.assertEqual(len(framed), 1)

        raw, _estimate, _capture = upstream.Upstream("http://unused", context_window=49152)._prep(
            framed[0], False, rlog)
        wire = json.loads(raw)
        wire_text = "\n".join(str(m.get("content") or "") for m in wire["messages"])
        self.assertEqual((args["diagnosis_kind"], args["subject"]), ("missing_file", "REVIEW.md"))
        self.assertIn(expected_nudge, wire_text)
        self.assertIn("Create REVIEW.md now.", wire_text)
        self.assertIn(args["task_quote"], wire_text)
        self.assertIn("workspace_absence", wire_text)
        self.assertIn("The task-named file REVIEW.md is not present in the current workspace.", wire_text)
        self.assertIn("Determine its contents from the exact task requirement", wire_text)
        self.assertNotIn(args["proposed_fix"], expected_nudge)

    def test_an_unsupported_empty_diagnosis_says_nothing(self):
        sess, rlog, extra = _drive("")
        self.assertEqual(sess.nudge_reason, "")
        self.assertNotIn("loop.satisfaction_gap_named", rlog.events)
        extra.assert_not_called()

    def test_the_same_diagnosis_twice_running_is_not_repeated(self):
        reason = "one already validated diagnosis"
        sess, _rlog, extra = _drive(reason, previous=reason)
        self.assertEqual(sess.nudge_reason, "")
        extra.assert_not_called()


if __name__ == "__main__":
    unittest.main()
