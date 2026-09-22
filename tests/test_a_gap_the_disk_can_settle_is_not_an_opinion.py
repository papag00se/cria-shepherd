"""The periodic path consumes the single provenance owner's result without re-judging it."""

import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cria import bodykeys, loop, prompts, upstream, wsview
from cria.plan import Plan, PlanItem
from tests.wsfixture import survey


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
        self.assertNotIn("Prioritize this step", wire_text)
        self.assertNotIn("Do ONLY this step", wire_text)
        self.assertNotIn(bodykeys.COMPLETION_REMEDIATION, wire)
        self.assertIn(args["task_quote"], wire_text)
        self.assertIn("workspace_absence", wire_text)
        self.assertIn("The task-named file REVIEW.md is not present in the current workspace.", wire_text)
        self.assertIn("Determine its contents from the exact task requirement", wire_text)
        self.assertNotIn(args["proposed_fix"], expected_nudge)

    def test_live_1790044200_red_gate_observation_suspends_step_one_on_the_prepared_wire(self):
        """The live 0033 boundary: red stays red; only a complete survey can arm REVIEW.md."""
        capture = Path.home() / ".cria" / "calls" / "20260921T193024-01a0c6f3-3dc1-7aa2-bc65-951943f81ad4"
        body = json.loads((capture / "0033-coder-s1.json").read_text())["body"]
        task = next(m["content"] for m in body["messages"]
                    if m.get("role") == "user" and str(m.get("content", "")).startswith("Fix these three"))
        active = re.search(r"Prioritize this step \(1 of 9\):\n\n(.*?)\n\nOnce it is complete",
                           body["messages"][0]["content"], re.S)
        self.assertIsNotNone(active)
        root = "/home/jesse/suite-runs/suite-feed-pipeline-java_ternary-bonsai-2_codex_pon_1790044200-vhli_z3m"
        view = wsview.View(root, "feed-1790044200-red-gate")
        self.assertTrue(wsview.apply_survey(view, survey(
            "D\tsrc\nD\tsrc/main\nD\tsrc/main/java\nD\tsrc/main/java/pipeline\n"
            "F\t1\t9938\tsrc/main/java/pipeline/Importer.java\nF\t1\t980\tpom.xml",
            root=root)))
        self.assertTrue(view.observation_fingerprint)
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)
        frames = []
        verdict = {"missing_file": True, "reason": "REVIEW.md is absent.", "proposed_fix": "",
                   "diagnosis_kind": "missing_file", "subject": "REVIEW.md",
                   "task_quote": "Add `REVIEW.md` describing remaining problems or risks in the code you changed. For every issue, include the file name and line number.",
                   "evidence_source": "workspace_absence", "evidence_quote": ""}
        driver = loop.Loop(loop.LoopContext(
            planner=None,
            coder_chat=lambda frame, _rlog: (frames.append(frame) or json.dumps({"choices": [{"message": {
                "role": "assistant", "tool_calls": [{"id": "read", "type": "function", "function": {
                    "name": "read_file", "arguments": '{"path":"README.md"}'}}]}}]}).encode()),
            reasoner_chat=lambda _body, _rlog: json.dumps({"choices": [{"message": {
                "role": "assistant", "content": json.dumps(verdict)}}]}).encode(),
            reasoner_role=None, runs_dir="", self_compact=False, focus_trim=False,
            assists=True, satisfaction_check_start=1, satisfaction_check_every=100))
        sess = loop.PlanSession(plan=Plan(id="live-0033", task=task, created="now", items=[PlanItem(active.group(1))]),
                                drive_count=10, last_gate_red=True, gate_stall=1,
                                workspace_root=root)
        rlog = _NullRlog()
        driver._work_item(sess, "live-0033", body, rlog, sess.plan.current(), 1)
        self.assertEqual(sess.completion_remediation_subject, "REVIEW.md")
        self.assertTrue(sess.last_gate_red, "deliverable observer cleared/redetermined the gate")
        self.assertIn("loop.satisfaction_blocked", rlog.events)
        self.assertIn("loop.satisfaction_gap_named", rlog.events)
        raw, _estimate, _capture = upstream.Upstream("http://unused", context_window=49152)._prep(
            frames[0], False, rlog)
        wire = json.loads(raw)
        text = "\n".join(str(m.get("content") or "") for m in wire["messages"])
        self.assertNotIn("Prioritize this step", text)
        self.assertIn(prompts.load("completion_remediation"), text)
        self.assertIn("Create REVIEW.md now.", text)
        self.assertNotIn(bodykeys.COMPLETION_REMEDIATION, wire)
        self.assertNotIn("deliverable_observation_last_drive", loop._session_to_dict(sess))
        # The actual 0033 tool calls have no receipt and cannot release a remediation they did not write.
        loop._settle_completion_remediation(sess, body["messages"], rlog)
        self.assertEqual(sess.completion_remediation_subject, "REVIEW.md")

    def test_red_gate_observer_requires_a_complete_current_survey(self):
        capture = Path.home() / ".cria" / "calls" / "20260921T193024-01a0c6f3-3dc1-7aa2-bc65-951943f81ad4"
        body = json.loads((capture / "0033-coder-s1.json").read_text())["body"]
        task = next(m["content"] for m in body["messages"]
                    if m.get("role") == "user" and str(m.get("content", "")).startswith("Fix these three"))
        active = re.search(r"Prioritize this step \(1 of 9\):\n\n(.*?)\n\nOnce it is complete",
                           body["messages"][0]["content"], re.S)
        root = "/home/jesse/suite-runs/suite-feed-pipeline-java_ternary-bonsai-2_codex_pon_1790044200-vhli_z3m"
        view = wsview.View(root, "red-gate-unknown")
        self.assertTrue(wsview.apply_survey(view, survey("F\t1\t1\tImporter.java", root=root,
                                                         complete=False)))
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)
        calls = []
        driver = loop.Loop(loop.LoopContext(
            planner=None,
            coder_chat=lambda frame, _rlog: (calls.append(frame) or json.dumps({"choices": [{"message": {
                "role": "assistant", "tool_calls": [{"id": "read", "type": "function", "function": {
                    "name": "read_file", "arguments": '{"path":"README.md"}'}}]}}]}).encode()),
            reasoner_chat=lambda *_: self.fail("unknown survey invoked observer"), reasoner_role=None,
            runs_dir="", self_compact=False, focus_trim=False, assists=True,
            satisfaction_check_start=1, satisfaction_check_every=1))
        sess = loop.PlanSession(plan=Plan(id="unknown", task=task, created="now",
                                          items=[PlanItem(active.group(1))]),
                                last_gate_red=True, gate_stall=1, workspace_root=root)
        driver._work_item(sess, "unknown", body, _NullRlog(), sess.plan.current(), 1)
        self.assertEqual(sess.completion_remediation_subject, "")

    def test_all_seven_feed_terminal_states_arm_before_their_captured_cursor_is_framed(self):
        """The owner receives live-shaped *unarmed* states, never a pre-armed serializer fixture."""
        captures = (
            ("20260921T110810-01a0c527-6c46-74b3-bf8d-91cb6d18d707", "0075-coder-s3.json", 17, False),
            ("20260921T131112-01a0c598-12c3-7973-8ebd-3f87b1ce0016", "0108-coder-s3.json", 22, False),
            ("20260921T135359-01a0c5bf-3d05-7fd0-a573-6c95720f4526", "0095-coder-s3.json", 26, False),
            ("20260921T144153-01a0c5eb-172a-7002-b4cf-64ac66d26edf", "0157-coder-s3-focus1.json", 75, False),
            ("20260921T164500-01a0c65b-cd75-7ab3-b3dd-3d839bfb3b35", "0112-coder-s3.json", 37, False),
            ("20260921T180043-01a0c6a1-2038-7a52-95be-552a62330eaf", "0088-coder-s1.json", 33, False),
            ("20260921T193024-01a0c6f3-3dc1-7aa2-bc65-951943f81ad4", "0033-coder-s1.json", 11, True),
        )
        home = Path.home() / ".cria" / "calls"
        evidence = prompts.render("negative_diagnosis", task_quote="Add REVIEW.md.",
                                  source="workspace_absence",
                                  evidence=prompts.render("negative_diagnosis_missing_file", subject="REVIEW.md"))
        gap = loop.VerdictNudge(evidence, diagnosis_kind="missing_file", subject="REVIEW.md")
        for capture, call, drive, red in captures:
            with self.subTest(capture=capture):
                body = json.loads((home / capture / call).read_text())["body"]
                system = body["messages"][0]["content"]
                active = (re.search(r"Prioritize this step \((\d+) of (\d+)\):\n\n(.*?)\n\nOnce it is complete", system, re.S)
                          or re.search(r"Do ONLY this step \((\d+) of (\d+)\), then stop:\n\n(.+)", system, re.S))
                self.assertIsNotNone(active)
                idx, total, step = active.groups()
                # Fails-before fixture: this is the exact captured cursor and no remediation state.
                before = loop._frame_for_item(body["messages"], step, "", int(idx), int(total))
                self.assertTrue("Prioritize this step" in before[0]["content"]
                                or "Do ONLY this step" in before[0]["content"])
                root = f"/captured/{capture}"
                view = wsview.View(root, capture)
                self.assertTrue(wsview.apply_survey(view, survey(
                    "D\tsrc\nD\tsrc/main\nF\t1\t10\tpom.xml\nF\t1\t99\tsrc/main/java/pipeline/Importer.java",
                    root=root)))
                token = wsview.bind(view)
                self.addCleanup(wsview.unbind, token)
                sent = []
                driver = loop.Loop(loop.LoopContext(
                    planner=None,
                    coder_chat=lambda frame, _rlog: (sent.append(frame) or json.dumps({"choices": [{"message": {
                        "role": "assistant", "tool_calls": [{"id": "read", "type": "function", "function": {
                            "name": "read_file", "arguments": '{"path":"README.md"}'}}]}}]}).encode()),
                    reasoner_chat=object(), runs_dir="", self_compact=False, focus_trim=False,
                    assists=True, satisfaction_check_start=1, satisfaction_check_every=1))
                items = [loop.PlanItem(f"completed {n}", done=True) for n in range(1, int(idx))]
                items.append(loop.PlanItem(step))
                items.extend(loop.PlanItem(f"pending {n}") for n in range(int(idx) + 1, int(total) + 1))
                sess = loop.PlanSession(plan=loop.Plan(id=capture, task="Add REVIEW.md.", created="now", items=items),
                                        drive_count=drive - 1, last_gate_red=red, gate_stall=int(red),
                                        workspace_root=root)
                rlog = _NullRlog()
                with (mock.patch.object(driver, "_periodic_satisfaction", return_value=None),
                      mock.patch.object(loop, "observe_task_missing_file", return_value=gap)):
                    driver._work_item(sess, capture, body, rlog, sess.plan.current(), int(idx))
                self.assertEqual(sess.completion_remediation_subject, "REVIEW.md")
                self.assertEqual(sess.last_gate_red, red, "observation must not change check state")
                raw, _estimate, _capture = upstream.Upstream("http://unused", context_window=49152)._prep(
                    sent[0], False, _NullRlog())
                wire = json.loads(raw)
                text = "\n".join(str(m.get("content") or "") for m in wire["messages"])
                self.assertNotIn("Prioritize this step", text)
                self.assertNotIn("Do ONLY this step", text)
                self.assertIn(prompts.load("completion_remediation"), text)
                self.assertIn("Add REVIEW.md.", text)
                self.assertIn("workspace_absence", text)
                self.assertNotIn(bodykeys.COMPLETION_REMEDIATION, wire)

    def test_delivered_comparators_keep_their_ordinary_cursor_without_a_typed_gap(self):
        """No absence verdict means no global plan override for Handles, Cart, Orders, or Rust."""
        tasks = (
            "Build the handles CLI and document it.",
            "Fix cart rounding and load discounts.json.",
            "Add the customer orders HTTP route and integration tests.",
            "Build the TOML CLI with lookup tests and README.",
        )
        for task in tasks:
            with self.subTest(task=task):
                sent = []
                driver = loop.Loop(loop.LoopContext(
                    planner=None,
                    coder_chat=lambda frame, _rlog: (sent.append(frame) or json.dumps({"choices": [{"message": {
                        "role": "assistant", "tool_calls": [{"id": "read", "type": "function", "function": {
                            "name": "read_file", "arguments": '{"path":"README.md"}'}}]}}]}).encode()),
                    reasoner_chat=object(), runs_dir="", self_compact=False, focus_trim=False,
                    assists=True, satisfaction_check_start=1, satisfaction_check_every=1))
                root = f"/comparator/{len(sent)}"
                view = wsview.View(root, task)
                self.assertTrue(wsview.apply_survey(view, survey("F\t1\t1\tREADME.md", root=root)))
                token = wsview.bind(view)
                self.addCleanup(wsview.unbind, token)
                sess = loop.PlanSession(plan=loop.Plan(id=task, task=task, created="now",
                    items=[loop.PlanItem("finish the remaining requested artifact")]), workspace_root=root)
                with (mock.patch.object(driver, "_periodic_satisfaction", return_value=None),
                      mock.patch.object(loop, "observe_task_missing_file", return_value=loop.VerdictNudge())):
                    driver._work_item(sess, task, {"messages": [{"role": "user", "content": task}], "tools": []},
                                      _NullRlog(), sess.plan.current(), 1)
                text = "\n".join(str(m.get("content") or "") for m in sent[0]["messages"])
                self.assertIn("Prioritize this step", text)
                self.assertEqual(sess.completion_remediation_subject, "")

    def test_remediation_persists_until_the_matching_write_result_is_observed(self):
        sess = _sess()
        sess.completion_remediation_subject = "REVIEW.md"
        sess.completion_remediation_reason = "typed absence evidence"
        rlog = _NullRlog()
        attempted = [{"role": "assistant", "tool_calls": [{"id": "w1", "function": {
            "name": "write_file", "arguments": json.dumps({"path": "REVIEW.md", "content": "x"})}}]}]
        loop._settle_completion_remediation(sess, attempted, rlog)
        self.assertEqual(sess.completion_remediation_subject, "REVIEW.md")
        failed = attempted + [{"role": "tool", "tool_call_id": "w1", "content": "permission denied"}]
        loop._settle_completion_remediation(sess, failed, rlog)
        self.assertEqual(sess.completion_remediation_subject, "REVIEW.md")
        landed = attempted + [{"role": "tool", "tool_call_id": "w1", "content": "Wrote REVIEW.md"}]
        loop._settle_completion_remediation(sess, landed, rlog)
        self.assertEqual(sess.completion_remediation_subject, "")
        self.assertEqual(sess.completion_remediation_reason, "")
        self.assertIn("loop.completion_remediation_written", rlog.events)

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
