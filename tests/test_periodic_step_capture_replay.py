"""Portable regressions for observation and completed-step confirmation.

The original Feed positive/confirmation records and the end of the Orders chain are
missing. These explicit scripted judgments exercise the production transitions and
real read-only probes; they make no claim to reproduce those historical sessions.
"""

import json
import subprocess
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cria import config, loop, wsview


STEP = ("Add a status column to the orders table (default 'pending') and create an index on the "
        "customer column in the schema/DDL, and write an in-place migration in orders/db.py that, "
        "on open, detects an existing orders.db lacking the status column or the customer index and "
        "adds them without losing existing rows.")


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kwargs):
        self.events.append((kind, kwargs))


class _InspectionReplies:
    """Critic, applies ruling, actual read request, then an observed confirmation."""
    def __init__(self):
        messages = [
            {"content": json.dumps({"done": True, "reason": "The schema includes status and customer index."})},
            {"content": "YES"},
            {"tool_calls": [{"id": "inspect-db", "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps({"path": "orders/db.py"})}}]},
            {"content": json.dumps({"consistent": True, "why": "The inspected DDL has both changes."})},
        ]
        self.replies = [json.dumps({"choices": [{"message": {"role": "assistant", **message},
                                                "finish_reason": "stop"}]}).encode()
                        for message in messages]
        self.bodies = []

    def __call__(self, body, _rlog):
        self.bodies.append(body)
        return self.replies.pop(0)


def _id(comp): return comp["choices"][0]["message"]["tool_calls"][0]["id"]
def _script(comp): return json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])["command"][-1]


class FeedObserveOnlyCaptureReplayTests(unittest.TestCase):
    """An unobserved positive needs a real survey and a fresh verification."""

    def _body(self, root):
        return {"messages": [{"role": "user", "content": (
            f"<environment_context><cwd>{root}</cwd></environment_context>")}],
                "tools": [{"type": "function", "function": {"name": "shell", "parameters": {
                    "type": "object", "properties": {"command": {"type": "array"}}}}}]}

    def _session(self, root):
        return loop.PlanSession(plan=loop.Plan(id="feed-observe-only", task="feed",
            created="2026-09-21", items=[loop.PlanItem("Fix the threading bug."), loop.PlanItem("Write REVIEW.md")]),
            workspace_root=root, drive_count=72)

    def _capture_positive(self):
        # Explicit synthetic judgment; the historical 0148/0149 replies are unavailable.
        return {"done": True, "reason": "Threading work is complete."}, "YES"

    def test_observe_only_survey_then_reverify_advances_to_review(self):
        """The first positive alone must not advance; observation and fresh verification can."""
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
            self.assertEqual(verify.call_count, 2, "the unobserved positive must be judged again after survey")
            kinds = [kind for kind, _ in rlog.events]
            self.assertIn("loop.periodic_step_observation_scheduled", kinds)
            self.assertIn("loop.periodic_step_observed", kinds)
            self.assertIn("loop.step_done", kinds)

    def test_unavailable_survey_never_promotes_unobserved_positive(self):
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
    def test_observed_read_only_confirmation_advances_to_step_two(self):
        """Exercise the actual confirmation reader, not a patched verification result."""
        workspace = Path(self.enterContext(tempfile.TemporaryDirectory()))
        orders = workspace / "orders"
        orders.mkdir()
        (orders / "db.py").write_text(
            "DDL = \"CREATE TABLE orders (customer TEXT, status TEXT DEFAULT 'pending');\"\n"
            "INDEX = 'CREATE INDEX orders_customer_idx ON orders(customer);'\n")
        with sqlite3.connect(workspace / "orders.db") as db:
            db.executescript("CREATE TABLE orders (customer TEXT, status TEXT DEFAULT 'pending');"
                             "CREATE INDEX orders_customer_idx ON orders(customer);"
                             "INSERT INTO orders(customer) VALUES ('retained-customer');")
        replies = _InspectionReplies()
        view = wsview.View(str(workspace), "orders-drive-12-replay")
        self.assertIsNone(view.read("orders/db.py"))  # Request its actual bytes in the harness survey.
        raw = subprocess.run(["bash", "-c", wsview.survey_command("orders-drive-12-replay")],
                             cwd=workspace, capture_output=True, text=True, check=True).stdout
        wsview.apply_survey(view, wsview.strip_survey(raw)[1])
        self.assertTrue(view.surveyed)
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)

        plan = loop.Plan(id="orders-drive-12", task="orders", created="2026-09-21", items=[
            loop.PlanItem(STEP), loop.PlanItem("step 2"),
        ])
        session = loop.PlanSession(plan=plan, workspace_root=str(workspace), drive_count=12)
        context = loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=replies, runs_dir="")
        context.planner_enabled = True
        context.reasoner_role = config.Role(name="reasoner", backend="local")
        driver = loop.Loop(context)
        rlog = _Rlog()
        with (patch.object(driver, "_replan_tail"),
              patch.object(driver, "_work", return_value={"next": "step 2"})):
            result = driver._periodic_step_check(session, "orders", {"messages": []}, 1, 2, rlog)

        self.assertEqual(result, {"next": "step 2"})
        self.assertTrue(plan.items[0].done)
        self.assertEqual(plan.current().text, "step 2")
        self.assertFalse(replies.replies, "the real confirmation must consume the scripted chain")
        self.assertEqual(len(replies.bodies), 4)
        inspected = [m for m in replies.bodies[-1]["messages"] if m.get("role") == "tool"]
        self.assertTrue(inspected)
        self.assertIn("orders_customer_idx", inspected[-1]["content"])
        self.assertIn("DEFAULT 'pending'", inspected[-1]["content"])
        self.assertIn("loop.step_done", [kind for kind, _ in rlog.events])


if __name__ == "__main__":
    unittest.main()
