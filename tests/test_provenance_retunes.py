"""The 2026-08-04 provenance retunes: guards rebased off blind-author-era evidence.

Operator ruling: dictated code and first-person steers are observe-only (tested in their own
files); the flail cap resets when the gate findings MOVE; the same-checks suppression allows ONE
grounded second look per unchanged-findings streak; editrecovery's whole-file escalation emits.
"""

import base64
import json
import unittest

from cria import editrecovery
from cria.loop import GuardState, PlanSession, track_gate_progress
from cria.plan import Plan, PlanItem


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


def _sess():
    return PlanSession(plan=Plan(id="x", task="t", created="c", items=[PlanItem("s")]))


class FlailBudgetResetTests(unittest.TestCase):
    def test_moved_findings_reset_the_budget(self):
        sess = _sess()
        sess.flail_steers_this_step = 3
        sess.flail_cap_logged = True
        track_gate_progress(sess, "app.py:3: undefined name 'x'")   # first finding: movement
        self.assertEqual(sess.flail_steers_this_step, 0)
        self.assertFalse(sess.flail_cap_logged)

    def test_unchanged_findings_keep_the_cap(self):
        sess = _sess()
        track_gate_progress(sess, "app.py:3: undefined name 'x'")
        sess.flail_steers_this_step = 3
        track_gate_progress(sess, "app.py:3: undefined name 'x'")   # same finding: no reset
        self.assertEqual(sess.flail_steers_this_step, 3)

    def test_green_resets_the_budget(self):
        sess = _sess()
        track_gate_progress(sess, "app.py:3: undefined name 'x'")
        sess.flail_steers_this_step = 3
        track_gate_progress(sess, "")                                # green: movement
        self.assertEqual(sess.flail_steers_this_step, 0)


class SameChecksSecondLookTests(unittest.TestCase):
    """The one-second-look mechanics live on the session flag; author_steer consumes it."""

    def test_flag_defaults_unspent_and_rearms_on_movement(self):
        gs = GuardState()
        self.assertFalse(gs.same_checks_relooked)

    def test_author_grants_one_second_look_then_suppresses(self):
        # Drive author_steer's gate directly: same checks twice → first re-ask allowed (flag
        # spent), second re-ask suppressed (reattach/silence path).
        from cria.loop import author_steer
        gs = _sess()
        rlog = _Rlog()
        body = {"messages": [{"role": "user", "content": "t"}], "tools": []}
        checks = "app.py:3: undefined name 'x'"
        # First steer on these findings: records steered_checks_text.
        author_steer(lambda b, r: json.dumps({"choices": [{"message": {"content": "ON_TRACK"}}]}).encode(),
                     None, None, gs, body, rlog, condition="flail", truth_text=checks)
        self.assertEqual(gs.steered_checks_text, checks)
        self.assertFalse(gs.same_checks_relooked)
        # Second call, SAME findings: the one second look is granted (the author runs — our stub
        # returns ON_TRACK so the result is None either way) and the flag is spent.
        author_steer(lambda b, r: json.dumps({"choices": [{"message": {"content": "ON_TRACK"}}]}).encode(),
                     None, None, gs, body, rlog, condition="flail", truth_text=checks)
        self.assertTrue(gs.same_checks_relooked)
        # Third call, SAME findings: suppressed — reattach or silence, never a fresh authoring.
        out = author_steer(lambda b, r: json.dumps({"choices": [{"message": {"content": "ON_TRACK"}}]}).encode(),
                           None, None, gs, body, rlog, condition="flail", truth_text=checks)
        self.assertTrue(any(k in ("loop.steer_checks_reattached", "loop.steer_same_checks")
                            for k in rlog.kinds()))
        # Findings MOVE: the second look rearms.
        author_steer(lambda b, r: json.dumps({"choices": [{"message": {"content": "ON_TRACK"}}]}).encode(),
                     None, None, gs, body, rlog, condition="flail", truth_text="other.py:9: new error")
        self.assertFalse(gs.same_checks_relooked)


class EditRecoveryTelemetryTests(unittest.TestCase):
    def _fail_report(self, mode="identical", path="handle.py"):
        fail = {"mode": mode, "path": path, "current": "x = 1\n", "anchor": ""}
        return editrecovery.EDITFAIL + base64.b64encode(json.dumps(fail).encode()).decode()

    def test_escalation_emits(self):
        rlog = _Rlog()
        # Enough prior edit-steer tags in history to trip the escalation clock.
        tag = editrecovery._tag("handle.py")
        prior = [{"role": "user", "content": tag + " earlier edit steer"}
                 for _ in range(editrecovery.ESCALATE_AFTER)]
        out = editrecovery.recover(self._fail_report(), prior, rlog)
        self.assertIn("editrecovery.escalated", rlog.kinds())
        self.assertNotIn(editrecovery.EDITFAIL, out)

    def test_early_failures_do_not_emit(self):
        rlog = _Rlog()
        editrecovery.recover(self._fail_report(), [], rlog)
        self.assertNotIn("editrecovery.escalated", rlog.kinds())

    def test_no_rlog_is_fine(self):
        self.assertNotIn(editrecovery.EDITFAIL, editrecovery.recover(self._fail_report(), []))


if __name__ == "__main__":
    unittest.main()
