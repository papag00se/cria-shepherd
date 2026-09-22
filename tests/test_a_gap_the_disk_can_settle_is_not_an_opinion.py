"""The periodic path consumes the single provenance owner's result without re-judging it."""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cria import loop, prompts


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

    def test_feed_capture_missing_file_gap_commands_creation_without_choosing_contents(self):
        """Exact 1790034274 replay: the typed REVIEW.md gap reached the coder, but its old generic
        nudge did not make the bounded next action explicit.  This assertion fails against that
        generic prompt and passes only when the live periodic path turns the validated file absence
        into a create-now directive while leaving the contents to the task."""
        capture = Path.home() / ".cria" / "calls" / "20260921T164500-01a0c65b-cd75-7ab3-b3dd-3d839bfb3b35"
        verdict = json.loads((capture / "0109-satisfaction.response.json").read_text())
        args = json.loads(verdict["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
        next_coder = json.loads((capture / "0112-coder-s3.json").read_text())
        evidence = prompts.render(
            "negative_diagnosis", task_quote=args["task_quote"],
            source=args["evidence_source"],
            evidence=prompts.render("negative_diagnosis_missing_file", subject=args["subject"]))
        gap = loop.VerdictNudge(evidence, diagnosis_kind=args["diagnosis_kind"], subject=args["subject"])

        self.assertEqual((args["diagnosis_kind"], args["subject"]), ("missing_file", "REVIEW.md"))
        self.assertIn(evidence, "\n".join(str(m.get("content") or "")
                                            for m in next_coder["body"]["messages"]))
        sess, _rlog, extra = _drive(gap)
        self.assertIn("Create `REVIEW.md` now.", sess.nudge_reason)
        self.assertIn("Determine its contents from the exact task requirement", sess.nudge_reason)
        extra.assert_not_called()

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
