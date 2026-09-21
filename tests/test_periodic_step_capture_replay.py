"""Exact replay of orders drive 12's periodic completed-step confirmation chain."""

import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from cria import config, loop, wsview


CAPTURE = Path("/home/jesse/.cria/calls/20260920T172321-01a0c158-8d64-7530-a279-4230b8760875")
WORKSPACE = Path("/home/jesse/suite-runs/suite-orders-api-py_ternary-bonsai-2_codex_pon_1789950190-n6seaqdq")
STEP = ("Add a status column to the orders table (default 'pending') and create an index on the "
        "customer column in the schema/DDL, and write an in-place migration in orders/db.py that, "
        "on open, detects an existing orders.db lacking the status column or the customer index and "
        "adds them without losing existing rows.")


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kwargs):
        self.events.append((kind, kwargs))


class _CapturedReplies:
    """The drive-12 critic plus every captured harness-backed confirmation reply."""
    def __init__(self):
        self.files = [CAPTURE / "0059-critic.response.json"] + [
            CAPTURE / f"{n:04d}-critic-confirm.response.json" for n in range(60, 67)]
        self.replies = [f.read_bytes() for f in self.files]
        self.bodies = []

    def __call__(self, body, _rlog):
        self.bodies.append(body)
        return self.replies.pop(0)


class OrdersDrive12PeriodicReplayTests(unittest.TestCase):
    def test_observed_capture_confirmation_advances_to_step_two(self):
        """Drive 12 stayed at step 1 before this change despite this exact successful inspection."""
        self.assertTrue(CAPTURE.is_dir(), CAPTURE)
        self.assertTrue(WORKSPACE.is_dir(), WORKSPACE)
        replies = _CapturedReplies()
        view = wsview.View(str(WORKSPACE), "orders-drive-12-replay")
        raw = subprocess.run(["bash", "-c", wsview.survey_command("orders-drive-12-replay")],
                             cwd=WORKSPACE, capture_output=True, text=True, check=True).stdout
        wsview.apply_survey(view, wsview.strip_survey(raw)[1])
        self.assertTrue(view.surveyed)
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)

        plan = loop.Plan(id="orders-drive-12", task="orders", created="2026-09-21", items=[
            loop.PlanItem(STEP), loop.PlanItem("step 2"),
        ])
        session = loop.PlanSession(plan=plan, workspace_root=str(WORKSPACE), drive_count=12)
        context = loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=replies, runs_dir="")
        context.reasoner_role = config.Role(name="reasoner", backend="local")
        driver = loop.Loop(context)
        rlog = _Rlog()
        with (patch.object(driver, "_replan_tail"),
              patch.object(driver, "_work", return_value={"next": "step 2"})):
            result = driver._periodic_step_check(session, "orders", {"messages": []}, 1, 2, rlog)

        self.assertEqual(result, {"next": "step 2"})
        self.assertTrue(plan.items[0].done)
        self.assertEqual(plan.current().text, "step 2")
        self.assertFalse(replies.replies, "the replay must consume every captured confirmation reply")
        self.assertEqual(len(replies.bodies), 8)
        self.assertTrue(any(m.get("role") == "tool" for m in replies.bodies[-1]["messages"]))
        self.assertIn("loop.step_done", [kind for kind, _ in rlog.events])


if __name__ == "__main__":
    unittest.main()
