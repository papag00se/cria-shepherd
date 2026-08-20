"""A completion check that names a missing file is checked against the disk before it is delivered.

`_veto_refuted_by_disk` is the one owner of "does the file this verdict calls missing actually
exist". It ran only from `_confirm_completion` — the brake on a false DONE — so it saw approve-path
verdicts and nothing else. The periodic gap steer carries the SAME claim, in the other direction,
and went out unchecked.

Walked on `feed-pipeline-java x qwen35` 1787249436 (0/5). Six completion checks reported
`REVIEW.md is missing (required deliverable)`. It was true, and the judge had established it on disk
itself. cria delivered all six wrapped in `periodic_gap`:

    That report is one reader's opinion of your work, not a verified fact and not an
    instruction, and you did not ask for it.

The coder restated the gap in its own words all six times and never wrote the file — the one point
in that task that needed no working build. A file's absence is not a matter of opinion.

BOTH DIRECTIONS, because only half the hedge is wrong. Where the disk REFUTES the claim the steer is
dropped whole rather than softened — a false "X is missing" in cria's voice is worse than silence
(#3, #5b), which is the rule the approve path already applies. Where the disk CORROBORATES it the
facts ride along. Anything the disk cannot speak to — an implementation the judge would prefer, a
test it thinks weak — keeps the hedge exactly as it was, which is the case it was written for.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from cria import loop


class _NullRlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **k):
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


def _drive(judge_reason, disk_result):
    """Run _periodic_satisfaction with the judge and the disk stubbed. Returns (sess, rlog)."""
    sess, rlog = _sess(), _NullRlog()
    lp = loop.Loop.__new__(loop.Loop)
    lp._ctx = _Ctx()
    lp._reasoner = lambda: (None, None)
    body = {"messages": [{"role": "user", "content": "Build it and write REVIEW.md."}], "tools": []}
    with mock.patch.object(loop, "judge_satisfaction", return_value=(False, judge_reason, "")), \
         mock.patch.object(loop, "_satisfaction_evidence", return_value="ev"), \
         mock.patch.object(loop, "_gate_notes", return_value=""), \
         mock.patch.object(loop, "_history_root", return_value=("task", 0)), \
         mock.patch.object(loop, "_coder_tools_summary", return_value=""), \
         mock.patch.object(loop, "known_routes", return_value=""), \
         mock.patch.object(loop, "_veto_refuted_by_disk", return_value=disk_result), \
         mock.patch.object(loop, "summarize", return_value=""):
        lp._periodic_satisfaction(sess, body, rlog, plan_off=True, blocked=False)
    return sess, rlog


GAP = "REVIEW.md is missing (required deliverable)."


class TheDiskIsAskedTests(unittest.TestCase):
    def test_a_corroborated_gap_is_delivered_as_a_verified_fact(self):
        sess, rlog = _drive(GAP, ("", "REVIEW.md — not present"))
        self.assertIn("loop.satisfaction_gap_confirmed_by_disk", rlog.events)
        self.assertIn("REVIEW.md — not present", sess.nudge_reason)
        # the hedge's own words are contradicted in the same message, by cria, on purpose
        self.assertIn("verified fact about the workspace", sess.nudge_reason)

    def test_a_gap_the_disk_refutes_is_dropped_whole_not_softened(self):
        sess, rlog = _drive(GAP, ("REVIEW.md", "REVIEW.md — 412 bytes"))
        self.assertIn("loop.satisfaction_gap_refuted_by_disk", rlog.events)
        self.assertEqual(sess.nudge_reason, "")
        self.assertNotIn("loop.satisfaction_gap_named", rlog.events)

    def test_a_gap_the_disk_cannot_speak_to_keeps_the_hedge_untouched(self):
        # The case the hedge was written for: an implementation opinion, no file named.
        opinion = "The Summary class should report skipped-row counts by reason."
        sess, rlog = _drive(opinion, ("", ""))
        self.assertIn("loop.satisfaction_gap_named", rlog.events)
        self.assertIn(opinion, sess.nudge_reason)
        self.assertIn("one reader's opinion", sess.nudge_reason)
        self.assertNotIn("verified fact about the workspace", sess.nudge_reason)


class TheOldBoundsStillHoldTests(unittest.TestCase):
    def test_an_empty_verdict_still_says_nothing(self):
        sess, rlog = _drive("", ("", ""))
        self.assertEqual(sess.nudge_reason, "")
        self.assertNotIn("loop.satisfaction_gap_named", rlog.events)

    def test_the_same_gap_twice_running_is_not_repeated(self):
        sess, rlog = _sess(), _NullRlog()
        sess.last_gap_named = GAP
        lp = loop.Loop.__new__(loop.Loop)
        lp._ctx = _Ctx()
        lp._reasoner = lambda: (None, None)
        body = {"messages": [{"role": "user", "content": "t"}], "tools": []}
        with mock.patch.object(loop, "judge_satisfaction", return_value=(False, GAP, "")), \
             mock.patch.object(loop, "_satisfaction_evidence", return_value="ev"), \
             mock.patch.object(loop, "_gate_notes", return_value=""), \
             mock.patch.object(loop, "_history_root", return_value=("task", 0)), \
             mock.patch.object(loop, "_coder_tools_summary", return_value=""), \
             mock.patch.object(loop, "known_routes", return_value=""), \
             mock.patch.object(loop, "_veto_refuted_by_disk", return_value=("", "x")) as disk, \
             mock.patch.object(loop, "summarize", return_value=""):
            lp._periodic_satisfaction(sess, body, rlog, plan_off=True, blocked=False)
        self.assertEqual(sess.nudge_reason, "")
        disk.assert_not_called()      # and it costs no reasoner call to stay silent


if __name__ == "__main__":
    unittest.main()
