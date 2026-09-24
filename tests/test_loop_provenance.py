"""Cross-cutting provenance invariants for completion decisions in ``loop.py``.

These fixtures deliberately use a generic artifact and a generic shell surface.  The invariants
belong to the wire/session unit, not to a language, task family, or coding harness.
"""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from cria import loop, probegate, wsview
from cria.config import Role
from cria.plan import Plan, PlanItem


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


class _GateFixtures:
    """Shared fixtures for these subprocess-backed gate tests \u2014 a plain mixin, NOT a
    ``unittest.TestCase``, so sharing it never re-runs one class's tests under another's name."""
    _SHELL = {"type": "function", "function": {"name": "shell", "parameters": {
        "type": "object", "properties": {"command": {"type": "string"}}
    }}}

    @staticmethod
    def _completion(text="summary"):
        return json.dumps({"choices": [{"message": {"content": text}}]}).encode()

    def _driver(self, root):
        context = loop.LoopContext(
            planner=None,
            coder_chat=lambda _body, _rlog: self._completion(),
            reasoner_chat=lambda _body, _rlog: self._completion(),
            runs_dir="",
            workspace_root=root,
        )
        return loop.Loop(context)

    def _bootstrap(self, root, session="session"):
        plan = probegate.plan_gate(root, session)
        result = subprocess.run(
            ["sh", "-c", plan.script], capture_output=True, text=True, check=True
        ).stdout
        return plan, result

    def _body(self, call_id, result):
        return {
            "messages": [
                {"role": "user", "content": "make the artifact match the request"},
                {"role": "tool", "tool_call_id": call_id, "content": result},
            ],
            "tools": [self._SHELL],
            "stream": True,
        }


class SurveyGateProvenanceTests(_GateFixtures, unittest.TestCase):
    def test_a_survey_only_gate_requires_a_new_plan_before_it_is_fresh(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "artifact.txt").write_text("content\n", encoding="utf-8")
            view = wsview.View(root, "session")
            token = wsview.bind(view)
            try:
                plan = probegate.plan_gate(root, "session")
                self.assertFalse(plan.surveyed_before)
                self.assertEqual(plan.candidates, [])

                result = subprocess.run(
                    ["sh", "-c", plan.script], capture_output=True, text=True, check=True
                ).stdout
                outcome = probegate.interpret_gate(plan, result, _Rlog())
                self.assertTrue(view.surveyed)
                self.assertFalse(outcome.ran)
                self.assertTrue(outcome.replan_after_survey)

                state = loop.GuardState()
                loop.record_gate_state(state, outcome, "", _Rlog())
                self.assertFalse(state.gate_fresh)
                self.assertTrue(state.gate_replan_required)
            finally:
                wsview.unbind(token)

    def test_an_already_surveyed_no_probe_gate_keeps_the_bounded_exit(self):
        with tempfile.TemporaryDirectory() as root:
            view = wsview.View(root, "session")
            token = wsview.bind(view)
            try:
                bootstrap = probegate.plan_gate(root, "session")
                result = subprocess.run(
                    ["sh", "-c", bootstrap.script], capture_output=True, text=True, check=True
                ).stdout
                probegate.interpret_gate(bootstrap, result, _Rlog())

                planned_after_survey = probegate.plan_gate(root, "session")
                self.assertTrue(planned_after_survey.surveyed_before)
                result = subprocess.run(
                    ["sh", "-c", planned_after_survey.script],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
                outcome = probegate.interpret_gate(planned_after_survey, result, _Rlog())
                self.assertFalse(outcome.ran)
                self.assertFalse(outcome.replan_after_survey)

                state = loop.GuardState()
                loop.record_gate_state(state, outcome, "", _Rlog())
                self.assertTrue(state.gate_fresh)
                self.assertFalse(state.gate_replan_required)
            finally:
                wsview.unbind(token)

    def test_a_missing_shell_keeps_the_bounded_exit(self):
        state = loop.GuardState(gate_replan_required=True)
        self.assertIsNone(
            loop.guard_gate_replan_after_survey(
                state, {"messages": [], "tools": []}, _Rlog(), workspace_root="/workspace")
        )
        self.assertFalse(state.gate_replan_required)

    def test_plan_completion_replans_instead_of_accepting_the_survey(self):
        with tempfile.TemporaryDirectory() as root:
            view = wsview.View(root, "session")
            token = wsview.bind(view)
            try:
                first_plan, result = self._bootstrap(root)
                session = loop.PlanSession(
                    plan=Plan(id="plan", task="make the artifact", created="now", items=[]),
                    workspace_root=root,
                    gate_plan=first_plan,
                    completion_probe_id="first",
                )
                rlog = _Rlog()

                out = self._driver(root)._work(
                    session, "session", self._body("first", result), rlog)

                self.assertTrue(out["choices"][0]["message"].get("tool_calls"))
                self.assertNotEqual(session.completion_probe_id, "first")
                self.assertTrue(session.gate_plan.surveyed_before)
                self.assertNotIn("loop.done", [kind for kind, _ in rlog.events])
            finally:
                wsview.unbind(token)

    def test_single_item_completion_replans_and_keeps_the_held_answer(self):
        with tempfile.TemporaryDirectory() as root:
            view = wsview.View(root, "session")
            token = wsview.bind(view)
            try:
                first_plan, result = self._bootstrap(root)
                session = loop.PlanSession(
                    plan=Plan(
                        id="plan",
                        task="make the artifact",
                        created="now",
                        items=[PlanItem("make the artifact")],
                    ),
                    synthetic=True,
                    workspace_root=root,
                    gate_plan=first_plan,
                    probe_call_id="first",
                    done_probe=True,
                    pending_done="the artifact is ready",
                )

                out = self._driver(root)._drive_single_item(
                    session, self._body("first", result), "session", _Rlog())

                self.assertTrue(out["choices"][0]["message"].get("tool_calls"))
                self.assertTrue(session.done_probe)
                self.assertNotEqual(session.probe_call_id, "first")
                self.assertEqual(session.pending_done, "the artifact is ready")
                self.assertTrue(session.gate_plan.surveyed_before)
            finally:
                wsview.unbind(token)

    def test_step_completion_replans_before_calling_the_checker(self):
        with tempfile.TemporaryDirectory() as root:
            view = wsview.View(root, "session")
            token = wsview.bind(view)
            try:
                first_plan, result = self._bootstrap(root)
                session = loop.PlanSession(
                    plan=Plan(
                        id="plan",
                        task="make the artifact",
                        created="now",
                        items=[PlanItem("make the artifact")],
                    ),
                    workspace_root=root,
                    gate_plan=first_plan,
                    probe_call_id="first",
                    pending_coder_text="the artifact is ready",
                )

                out = self._driver(root)._verify_after_probe(
                    session, "session", self._body("first", result), _Rlog())

                self.assertTrue(out["choices"][0]["message"].get("tool_calls"))
                self.assertTrue(session.awaiting_probe)
                self.assertNotEqual(session.probe_call_id, "first")
                self.assertTrue(session.gate_plan.surveyed_before)
            finally:
                wsview.unbind(token)


class PeriodicSurveyOnlyReplanTests(_GateFixtures, unittest.TestCase):
    """C33: a periodic check-in whose result was survey-only (the harness's shell had never been
    given a real check to run yet) must not simply vanish. Before this fix, `guard_periodic_result`
    returned None on a survey-only result and BOTH callers stopped there \u2014 unlike the completion
    paths, which already call :func:`guard_gate_replan_after_survey`. The periodic check-in is now
    replanned too, kept PERIODIC (no verdict, `gate_fresh` untouched), and bounded to one replan."""

    def test_plan_off_periodic_check_in_replans_after_a_survey_only_bootstrap(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "artifact.txt").write_text("content\n", encoding="utf-8")
            Path(root, "x.py").write_text("def f(:\n    pass\n", encoding="utf-8")
            view = wsview.View(root, "session")
            token = wsview.bind(view)
            try:
                first_plan, result = self._bootstrap(root)
                self.assertEqual(first_plan.candidates, [])   # nothing has been surveyed yet

                session = loop.PlanSession(
                    plan=Plan(
                        id="plan", task="make the artifact", created="now",
                        items=[PlanItem("make the artifact")],
                    ),
                    synthetic=True,
                    workspace_root=root,
                    gate_plan=first_plan,
                    probe_call_id="first",
                    periodic_probe=True,
                    awaiting_probe=True,
                )

                out = self._driver(root)._drive_single_item(
                    session, self._body("first", result), "session", _Rlog())

                # Before the fix: guard_periodic_result reads a survey-only result → None, and the
                # caller stopped there \u2014 the check-in vanished with nothing to show for it.
                self.assertIsNotNone(out)
                self.assertTrue(out["choices"][0]["message"].get("tool_calls"))
                self.assertTrue(session.periodic_probe)          # re-armed as a PERIODIC probe...
                self.assertFalse(session.done_probe)             # ...never a completion gate
                self.assertTrue(session.gate_plan.surveyed_before)
                self.assertNotEqual(session.probe_call_id, "first")
                self.assertTrue(session.periodic_replan_done)    # bound armed for this check-in

                second_call_id = session.probe_call_id
                second_result = subprocess.run(
                    ["sh", "-c", session.gate_plan.script],
                    capture_output=True, text=True, check=True,
                ).stdout

                out2 = self._driver(root)._drive_single_item(
                    session, self._body(second_call_id, second_result), "session", _Rlog())

                self.assertIsNotNone(out2)
                self.assertFalse(session.periodic_probe)         # consumed; no further replan queued
                self.assertTrue(session.last_gate_red)            # the replanned gate found the real error
                self.assertEqual(session.gate_stall, 1)           # one RED cycle recorded
                self.assertIsNone(session.latest_satisfaction)    # never a verdict \u2014 periodic stays silent on that
            finally:
                wsview.unbind(token)

    def test_plan_loop_periodic_check_in_replans_after_a_survey_only_bootstrap(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "artifact.txt").write_text("content\n", encoding="utf-8")
            Path(root, "x.py").write_text("def f(:\n    pass\n", encoding="utf-8")
            view = wsview.View(root, "session")
            token = wsview.bind(view)
            try:
                first_plan, result = self._bootstrap(root)
                self.assertEqual(first_plan.candidates, [])

                session = loop.PlanSession(
                    plan=Plan(
                        id="plan", task="make the artifact", created="now",
                        items=[PlanItem("make the artifact")],
                    ),
                    workspace_root=root,
                    gate_plan=first_plan,
                    probe_call_id="first",
                    periodic_probe=True,
                    awaiting_probe=True,
                )

                out = self._driver(root)._verify_after_probe(
                    session, "session", self._body("first", result), _Rlog())

                self.assertTrue(out["choices"][0]["message"].get("tool_calls"))
                self.assertTrue(session.periodic_probe)
                self.assertTrue(session.gate_plan.surveyed_before)
                self.assertNotEqual(session.probe_call_id, "first")
                self.assertTrue(session.periodic_replan_done)
            finally:
                wsview.unbind(token)

    def test_a_second_consecutive_survey_only_result_stays_silent(self):
        """The bound: a periodic check-in gets exactly ONE replan. If replanning again were allowed
        every turn, a workspace the harness genuinely cannot survey (no shell, e.g.) would wedge the
        periodic check-in into an unbounded loop instead of the ordinary silence a clean/couldn't-run
        check-in has always kept."""
        from cria.loop import GuardState, guard_periodic_replan_after_survey
        gs = GuardState(gate_replan_required=True, periodic_replan_done=True)
        self.assertIsNone(
            guard_periodic_replan_after_survey(gs, {"messages": [], "tools": []}, _Rlog(),
                                                workspace_root="/workspace"))

    def test_no_shell_available_consumes_the_bound_without_looping(self):
        from cria.loop import GuardState, guard_periodic_replan_after_survey
        gs = GuardState(gate_replan_required=True)
        self.assertIsNone(
            guard_periodic_replan_after_survey(gs, {"messages": [], "tools": []}, _Rlog(),
                                                workspace_root="/workspace"))
        self.assertFalse(gs.gate_replan_required)
        self.assertTrue(gs.periodic_replan_done)


class AcceptedActionProvenanceTests(unittest.TestCase):
    @staticmethod
    def _missing(task):
        return {
            "satisfied": False,
            "reason": "raw provider diagnosis",
            "proposed_fix": "raw provider action",
            "diagnosis_kind": "missing_file",
            "subject": "REPORT.md",
            "task_quote": task,
            "evidence_source": "workspace_absence",
            "evidence_quote": "",
        }

    def test_the_task_requirement_is_the_one_returned_for_both_consumers(self):
        task = "Add REPORT.md."
        with tempfile.TemporaryDirectory() as root, \
             mock.patch.object(loop, "_satisfaction_verdict", return_value=self._missing(task)), \
             mock.patch.object(loop, "_grounded_steer_or_none") as old_guard:
            satisfied, nudge, plan_action = loop.judge_satisfaction(
                task, "the observed output", lambda *_: b"", None, _Rlog(),
                workspace_root=root, messages=[], sess=loop.GuardState())

        self.assertFalse(satisfied)
        self.assertIsInstance(nudge, loop.VerdictNudge)
        self.assertIn("REPORT.md", nudge.evidence)
        self.assertEqual(nudge.action, task)
        self.assertEqual(plan_action, task)
        self.assertNotIn("raw provider", str(nudge))
        old_guard.assert_not_called()

    def test_the_retry_also_reuses_the_validated_action_without_raw_fallback(self):
        task = "Add REPORT.md."
        obj = self._missing(task)
        with tempfile.TemporaryDirectory() as root, \
             mock.patch.object(loop, "_satisfaction_verdict", side_effect=[None, obj]), \
             mock.patch.object(loop, "_grounded_steer_or_none") as old_guard:
            satisfied, nudge, plan_action = loop.judge_satisfaction(
                task, "the observed result", lambda *_: b"", None, _Rlog(),
                workspace_root=root, messages=[], sess=loop.GuardState())

        self.assertFalse(satisfied)
        self.assertEqual(nudge.action, task)
        self.assertEqual(plan_action, task)
        self.assertNotIn(obj["proposed_fix"], str(nudge))
        old_guard.assert_not_called()

    def test_the_same_accepted_action_reaches_the_nudge_and_plan_without_a_second_veto(self):
        accepted_action = "inspect the artifact, then correct the observed mismatch"
        guidance = loop.VerdictNudge(
            "the artifact does not match the requested behavior", accepted_action)
        context = loop.LoopContext(
            planner=None,
            coder_chat=lambda *_: b"{}",
            reasoner_chat=lambda *_: b"{}",
            reasoner_role=Role(name="reasoner", backend="local"),
            runs_dir="",
        )
        driver = loop.Loop(context)
        session = loop.PlanSession(
            plan=Plan(id="plan", task="make the artifact", created="now", items=[]))
        body = {"messages": [{"role": "user", "content": "make the artifact"}], "tools": []}

        with mock.patch.object(
            loop, "judge_satisfaction", return_value=(False, guidance, guidance.action)
        ), mock.patch.object(
            loop,
            "reasoned_noise_indices",
            side_effect=AssertionError("accepted action was sent to a second provider veto"),
        ):
            driver._reopen_if_unsatisfied(session, body, _Rlog())

        self.assertEqual(
            session.plan.items[-1].text,
            loop._COMPLETION_FIX_PREFIX + accepted_action,
        )
        self.assertIn(accepted_action, session.nudge_reason)


class RecoveredVerdictProvenanceTests(unittest.TestCase):
    def test_unanchored_recovery_text_is_never_surfaced(self):
        source = "I inspected the artifact. A required case remains untested."
        rlog = _Rlog()
        out = loop.verdict_from_reasoning(
            source,
            "done",
            rlog,
            "generic",
            lambda _prompt: "NOT_DONE: the test coverage is incomplete",
        )
        self.assertIsNone(out)
        event = next(fields for kind, fields in rlog.events
                     if kind == "loop.verdict_recovery_unanchored")
        self.assertNotIn("the test coverage is incomplete", repr(event))

    def test_anchored_recovery_surfaces_only_a_contiguous_source_slice(self):
        source = "I inspected the artifact. A required case remains untested. Fixing it is necessary."
        quote = "A required case remains untested."
        out = loop.verdict_from_reasoning(
            source, "done", _Rlog(), "generic", lambda _prompt: "NOT_DONE: " + quote)
        self.assertIs(out["done"], False)
        self.assertIn(out["reason"], source)
        self.assertTrue(out["reason"].startswith(quote))

    def test_a_missing_flag_never_infers_positive_completion(self):
        out = loop._fill_missing_verdict_flag(
            {"reason": "the artifact appears complete", "proposed_fix": ""},
            "done",
            _Rlog(),
            "generic",
        )
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
