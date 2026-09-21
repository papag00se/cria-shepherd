"""Exact replay of orders drive 12's periodic completed-step confirmation chain."""

import json
import subprocess
import tempfile
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


def _id(comp): return comp["choices"][0]["message"]["tool_calls"][0]["id"]
def _script(comp): return json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["command"][-1]


class FeedObserveOnlyCaptureReplayTests(unittest.TestCase):
    """Replay the latest Feed critic positive through its formerly missing survey leg."""

    CAPTURE = Path("/home/jesse/.cria/calls/20260921T144153-01a0c5eb-172a-7002-b4cf-64ac66d26edf")

    def _body(self, root):
        return {"messages": [{"role": "user", "content": (
            f"<environment_context><cwd>{root}</cwd></environment_context>")}],
                "tools": [{"type": "function", "function": {"name": "shell", "parameters": {
                    "type": "object", "properties": {"command": {"type": "array"}}}}}]}

    def _session(self, root):
        return loop.PlanSession(plan=loop.Plan(id="feed-observe-only", task="feed",
            created="2026-09-21", items=[loop.PlanItem(STEP), loop.PlanItem("Write REVIEW.md")]),
            workspace_root=root, drive_count=72)

    def _capture_positive(self):
        critic = json.loads((self.CAPTURE / "0148-critic.response.json").read_text())
        confirm = json.loads((self.CAPTURE / "0149-confirm-applies.response.json").read_text())
        verdict = json.loads(critic["choices"][0]["message"]["content"])
        self.assertTrue(verdict["done"])
        confirmation = confirm["choices"][0]["message"]["content"]
        self.assertEqual(confirmation, "YES")
        return verdict, confirmation

    def test_latest_capture_observe_only_survey_then_reverify_advances_to_review(self):
        """Fails before: 0148's positive re-framed threading; it never acquired an observation."""
        self.assertTrue(self.CAPTURE.is_dir(), self.CAPTURE)
        verdict, captured_confirmation = self._capture_positive()
        with tempfile.TemporaryDirectory() as root:
            Path(root, "pom.xml").write_text("<project/>")
            view = wsview.View(root, "feed-observe-only")
            token = wsview.bind(view)
            self.addCleanup(wsview.unbind, token)
            sess, driver, rlog = self._session(root), loop.Loop(
                loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None, runs_dir="")), _Rlog()
            unobserved = loop.Verification(True, verdict["reason"],
                                           loop.Confirmation(captured_confirmation == "YES", False))
            observed = loop.Verification(True, verdict["reason"],
                                         loop.Confirmation(captured_confirmation == "YES", True))
            with (patch.object(driver, "_verify", side_effect=[unobserved, observed]) as verify,
                  patch.object(driver, "_replan_tail"),
                  patch.object(driver, "_work", return_value={"next": "Write REVIEW.md"})):
                first = driver._periodic_step_check(sess, "feed", self._body(root), 1, 2, rlog)
                self.assertTrue(sess.periodic_observation)
                self.assertFalse(sess.plan.items[0].done, "unobserved true must never advance directly")
                result = subprocess.run(["sh", "-c", _script(first)], cwd=root, text=True,
                                        capture_output=True, check=True).stdout
                returned = self._body(root)
                returned["messages"] += [first["choices"][0]["message"], {
                    "role": "tool", "tool_call_id": _id(first), "content": result}]
                follow_up = driver._periodic_observation_after_probe(sess, "feed", returned, rlog)
                # The first probe was survey-only, so the existing gate contract schedules its
                # one post-survey check before the fresh critic may decide the step.
                result = subprocess.run(["sh", "-c", _script(follow_up)], cwd=root, text=True,
                                        capture_output=True, check=True).stdout
                returned = self._body(root)
                returned["messages"] += [follow_up["choices"][0]["message"], {
                    "role": "tool", "tool_call_id": _id(follow_up), "content": result}]
                advanced = driver._periodic_observation_after_probe(sess, "feed", returned, rlog)
            self.assertEqual(advanced, {"next": "Write REVIEW.md"})
            self.assertTrue(view.surveyed)
            self.assertTrue(sess.plan.items[0].done)
            self.assertEqual(sess.plan.current().text, "Write REVIEW.md")
            self.assertEqual(verify.call_count, 2, "the captured positive must be judged again after survey")
            kinds = [kind for kind, _ in rlog.events]
            self.assertIn("loop.periodic_step_observation_scheduled", kinds)
            self.assertIn("loop.periodic_step_observed", kinds)
            self.assertIn("loop.step_done", kinds)

    def test_unavailable_survey_never_promotes_captured_positive(self):
        """A declined survey remains unknown: no old periodic verdict is reused as approval."""
        verdict, captured_confirmation = self._capture_positive()
        with tempfile.TemporaryDirectory() as root:
            view = wsview.View(root, "feed-observe-unavailable")
            token = wsview.bind(view)
            self.addCleanup(wsview.unbind, token)
            sess, driver, rlog = self._session(root), loop.Loop(
                loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None, runs_dir="")), _Rlog()
            unobserved = loop.Verification(True, verdict["reason"],
                                           loop.Confirmation(captured_confirmation == "YES", False))
            with (patch.object(driver, "_verify", return_value=unobserved) as verify,
                  patch.object(driver, "_work", return_value={"same": "threading"})):
                first = driver._periodic_step_check(sess, "feed", self._body(root), 1, 2, rlog)
                returned = self._body(root)
                returned["messages"] += [first["choices"][0]["message"], {
                    "role": "tool", "tool_call_id": _id(first), "content": "sandbox refused command"}]
                result = driver._periodic_observation_after_probe(sess, "feed", returned, rlog)
            self.assertEqual(result, {"same": "threading"})
            self.assertFalse(view.surveyed)
            self.assertFalse(sess.plan.items[0].done)
            self.assertFalse(sess.periodic_observation)
            self.assertEqual(verify.call_count, 1)
            self.assertIn("loop.periodic_step_observation_unavailable", [k for k, _ in rlog.events])


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
