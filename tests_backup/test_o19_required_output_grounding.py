"""The root task, not the initial verdict or generated step, authorizes a missing output."""
import json
import unittest
from unittest import mock

from cria import loop, wsview
from cria.config import Role
from cria.plan import Plan, PlanItem
from tests.test_o19_absence_diagnosis_survives_formatting import (
    ROOT, TASK, SPAN, VERDICT_0086, VERDICT_0123, _bind, _grounding,
)
from tests.test_negative_diagnosis_provenance import _Ask, _Rlog
from tests.wsfixture import survey

ROLE = Role(name="reasoner", backend="local")


def reply(content):
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


def question_text(body):
    return "\n".join(m.get("content") or "" for m in body["messages"])


class RequirementQuestionTests(unittest.TestCase):
    def test_every_typed_absence_gets_one_independent_question_even_with_exact_initial_quote(self):
        _bind(self)
        for quote in (SPAN, "", "Add REVIEW.md", "invented normalized prose"):
            with self.subTest(initial_quote=quote):
                ask = _Ask(_grounding())
                obj = {**VERDICT_0086, "task_quote": quote}
                out = loop._negative_diagnosis_nudge(obj, task=TASK, workspace_root=ROOT, ask=ask)
                self.assertEqual(out.action, SPAN)
                self.assertEqual((out.diagnosis_kind, out.subject), ("missing_file", "REVIEW.md"))
                self.assertEqual(len(ask.prompts), 1)
                prompt = ask.prompts[0]
                self.assertIn(TASK, prompt)
                self.assertNotIn(obj["reason"], prompt)
                self.assertNotIn(obj["proposed_fix"], prompt)
                self.assertNotIn(obj["evidence_quote"], prompt)
                self.assertNotIn("cria", prompt)

    def test_unsupported_inputs_examples_optional_and_literal_items_never_become_remediation(self):
        _bind(self)
        for task in ("Read `REVIEW.md` as input.", "For example, an output could be `REVIEW.md`.",
                     "Optionally add `REVIEW.md`.", 'Write exactly ``literal `REVIEW.md` text`` to notes.txt.',
                     'Write this literal:\n    Add `REVIEW.md`\n',
                     '> ~~~text\n> Add `REVIEW.md`\n> ~~~'):
            with self.subTest(task=task):
                ask = _Ask(_grounding(task, required=False))
                out = loop._negative_diagnosis_nudge(VERDICT_0123, task=task,
                                                     workspace_root=ROOT, ask=ask)
                self.assertFalse(out)
                self.assertEqual((out.action, out.diagnosis_kind, out.subject), ("", "", ""))
                self.assertEqual(len(ask.prompts), 1)

    def test_source_extraction_identity_and_positive_answer_are_strict(self):
        _bind(self)
        answers = ["", "UNDECIDABLE", "SUPPORTED", "{}", "{broken", "[]",
                   _grounding(required=False), _grounding(required="true"),
                   _grounding(subject="REVIEW.md.bak"), _grounding(subject="docs/REVIEW.md"),
                   _grounding(quote="Add REVIEW.md describing remaining problems."),
                   _grounding(quote="invented requirement"), _grounding(quote=""),
                   json.dumps({"required_output": True, "subject": "REVIEW.md", "task_quote": 9})]
        for answer in answers:
            with self.subTest(answer=answer):
                ask = _Ask(answer)
                out = loop._negative_diagnosis_nudge(VERDICT_0086, task=TASK,
                                                     workspace_root=ROOT, ask=ask)
                self.assertFalse(out)
                self.assertEqual(len(ask.prompts), 1)

    def test_extracted_prefix_cannot_hide_the_original_filename_suffix(self):
        _bind(self)
        for task, quote in [("Add `REVIEW.md.bak` now", "Add `REVIEW.md"),
                            ("Add `REVIEW.md`suffix now", "Add `REVIEW.md`"),
                            ("Add docs/REVIEW.md now", "REVIEW.md"),
                            ("Add REVIEW.md.bak and read REVIEW.md as input", "Add REVIEW.md")]:
            with self.subTest(task=task):
                out = loop._negative_diagnosis_nudge(VERDICT_0123, task=task, workspace_root=ROOT,
                                                     ask=_Ask(_grounding(quote)))
                self.assertFalse(out)
                self.assertEqual((out.action, out.diagnosis_kind, out.subject), ("", "", ""))

    def test_positive_extraction_cannot_clip_an_enclosed_legal_filename(self):
        _bind(self)
        for name in ("REVIEW.md+backup", "REVIEW.md=backup", "REVIEW.md;backup",
                     "REVIEW.md:backup", "REVIEW.md@backup", "REVIEW.md(backup)",
                     "REVIEW.md!backup", "REVIEW.md backup", "prefix REVIEW.md backup",
                     "prefix\nREVIEW.md\nbackup", "REVIEW.md%backup", "REVIEW.md,backup"):
            with self.subTest(name=name):
                task = f"Add `{name}` now"
                # Even a positive answer extracting the entire original requirement cannot certify
                # a different literal name containing the candidate as an interior/prefix substring.
                out = loop._negative_diagnosis_nudge(VERDICT_0123, task=task, workspace_root=ROOT,
                                                     ask=_Ask(_grounding(task)))
                self.assertFalse(out)
                self.assertEqual((out.action, out.diagnosis_kind, out.subject), ("", "", ""))

    def test_explicit_positive_clipped_literal_extractions_suppress_all_remediation_identity(self):
        _bind(self)
        for task, quote in (("Add `REVIEW.md+backup` now", "Add `REVIEW.md"),
                            ('Add "REVIEW.md+backup" now', 'Add "REVIEW.md'),
                            ("Add REVIEW.md+backup now", "Add REVIEW.md"),
                            ("Add `REVIEW.md` now", "Add `REVIEW.md"),
                            ("Add `docs/REVIEW.md` now", "REVIEW.md"),
                            ("Add `REVIEW.md*` now", "Add `REVIEW.md")):
            with self.subTest(task=task, quote=quote):
                out = loop._negative_diagnosis_nudge(VERDICT_0123, task=task, workspace_root=ROOT,
                                                     ask=_Ask(_grounding(quote)))
                self.assertFalse(out)
                self.assertEqual((out.action, out.diagnosis_kind, out.subject), ("", "", ""))

    def test_original_task_and_subject_token_shaped_values_reach_question_verbatim(self):
        _bind(self)
        root = 'Create a file named `{{SUBJECT}}`. Treat `REVIEW.md` as an existing input, not an output.'
        ask = _Ask(_grounding(required=False))
        out = loop._negative_diagnosis_nudge(VERDICT_0123, task=root, original_task=root,
                                             workspace_root=ROOT, ask=ask)
        self.assertFalse(out)
        self.assertIn(root, ask.prompts[0])
        # Reverse direction too: a token-shaped candidate filename cannot absorb inserted task text.
        subject = "{{TASK}}.md"
        task = 'Create the file named `{{TASK}}.md`; the string {{SUBJECT}} is literal.'
        ask = _Ask(_grounding(task, subject=subject))
        obj = {**VERDICT_0123, "subject": subject}
        out = loop._negative_diagnosis_nudge(obj, task=task, workspace_root=ROOT, ask=ask)
        self.assertIn(task, ask.prompts[0])
        self.assertIn("EXACT CANDIDATE FILE:\n" + subject + "\n", ask.prompts[0])
        self.assertEqual(out.subject, subject)
        self.assertEqual(out.action, task)

    def test_no_question_callback_or_exception_suppresses(self):
        _bind(self)
        self.assertFalse(loop._negative_diagnosis_nudge(VERDICT_0086, task=TASK, workspace_root=ROOT))
        def unavailable(question):
            raise RuntimeError("upstream unavailable")
        self.assertFalse(loop._negative_diagnosis_nudge(VERDICT_0086, task=TASK,
                                                      workspace_root=ROOT, ask=unavailable))

    def test_absence_and_path_identity_are_rechecked_after_the_question(self):
        _bind(self)
        for new_state in (True, None):
            with self.subTest(state=new_state):
                with mock.patch.object(loop, "_workspace_subject", side_effect=[
                    ("REVIEW.md", False, None), ("REVIEW.md", new_state, None)]):
                    self.assertFalse(loop._negative_diagnosis_nudge(
                        VERDICT_0086, task=TASK, workspace_root=ROOT, ask=_Ask(_grounding())))
        with mock.patch.object(loop, "_workspace_subject", side_effect=[
            ("REVIEW.md", False, None), ("other/REVIEW.md", False, None)]):
            self.assertFalse(loop._negative_diagnosis_nudge(
                VERDICT_0086, task=TASK, workspace_root=ROOT, ask=_Ask(_grounding())))

    def test_generated_step_does_not_supply_root_requirement_authority(self):
        _bind(self)
        generated = "Add `REVIEW.md` now"
        root = "Read REVIEW.md if supplied; change the importer only."
        ask = _Ask(_grounding(generated))
        out = loop._negative_diagnosis_nudge(VERDICT_0123, task=generated, original_task=root,
                                             workspace_root=ROOT, ask=ask)
        self.assertFalse(out)
        self.assertIn(root, ask.prompts[0])
        self.assertNotIn(generated, ask.prompts[0])

    def test_canonicalized_absent_named_file_stays_weak_without_a_requirement_question(self):
        _bind(self)
        ask = _Ask(_grounding())
        out = loop._negative_diagnosis_nudge({**VERDICT_0086, "diagnosis_kind": "missing_content"},
                                             task=TASK, workspace_root=ROOT, ask=ask)
        self.assertEqual(out.diagnosis_kind, "absent_named_file")
        self.assertEqual(ask.prompts, [])


class CallerCoverageTests(unittest.TestCase):
    def chat(self, answers):
        calls = []
        def chat(body, rlog):
            calls.append(body)
            return reply(answers.pop(0))
        return chat, calls

    def test_satisfaction_retry_uses_root_question_and_stays_false(self):
        _bind(self)
        # Isolate verdict retries from transport recovery: real caller dispatch remains exercised.
        with mock.patch.object(loop, "_satisfaction_verdict", side_effect=[None, VERDICT_0123]):
            chat, calls = self.chat([_grounding()])
            done, reason, action = loop.judge_satisfaction(TASK, "log", chat, ROLE, _Rlog(),
                                                         workspace_root=ROOT)
        self.assertFalse(done)
        self.assertEqual(action, SPAN)
        self.assertEqual(len(calls), 1)
        self.assertIn(TASK, question_text(calls[0]))

    def test_step_critic_and_retry_use_separate_original_authority(self):
        _bind(self)
        for first in (VERDICT_0123, None):
            with self.subTest(retry=first is None):
                chat, calls = self.chat([_grounding()])
                from cria.assistruntime import AssistRuntime
                critic = loop.Loop(loop.LoopContext(None, None, chat, reasoner_role=ROLE,
                    planner_enabled=True, pilot_runtime=AssistRuntime.select(experimental_planning=True)))
                verdicts = [(first, "raw")]
                if first is None:
                    verdicts.append((VERDICT_0123, "raw"))
                with mock.patch.object(critic, "_verdict", side_effect=verdicts), \
                     mock.patch.object(loop, "_dump_verify"):
                    out = critic._verify("Generated step: finish importer", "", "", "", _Rlog(),
                                         workspace_root=ROOT, original_task=TASK)
                self.assertFalse(out.done)
                self.assertEqual(out.reason.action, SPAN)
                self.assertEqual(len(calls), 1)
                self.assertIn(TASK, question_text(calls[0]))

    def test_step_without_root_authority_cannot_authorize_a_missing_output(self):
        _bind(self)
        chat, calls = self.chat([])
        from cria.assistruntime import AssistRuntime
        critic = loop.Loop(loop.LoopContext(None, None, chat, reasoner_role=ROLE,
            planner_enabled=True, pilot_runtime=AssistRuntime.select(experimental_planning=True)))
        with mock.patch.object(critic, "_verdict", return_value=(VERDICT_0123, "raw")), \
             mock.patch.object(loop, "_dump_verify"):
            out = critic._verify(TASK, "", "", "", _Rlog(), workspace_root=ROOT)
        self.assertFalse(out.done)
        self.assertFalse(out.reason)
        self.assertEqual(calls, [])

    def test_confirmation_negative_uses_root_not_claim(self):
        _bind(self)
        diagnosis = {**VERDICT_0123, "consistent": False}
        chat, calls = self.chat([_grounding()])
        with mock.patch.object(loop, "_judge_completion", return_value=json.loads(reply(json.dumps(diagnosis)))):
            out = loop._confirm_completion("Generated claim: importer done", "optimistic claim", ROOT,
                                            chat, ROLE, _Rlog(), phase="test", original_task=TASK)
        self.assertFalse(out.confirmed)
        self.assertIn(SPAN, out.reason)
        self.assertNotIn(VERDICT_0123["proposed_fix"], out.reason)
        self.assertEqual(len(calls), 1)
        self.assertIn(TASK, question_text(calls[0]))

    def test_plan_off_done_uses_retained_root_not_rewritten_history(self):
        _bind(self)
        retained = "Fix importer only. Do not create a report."
        rewritten = "Add `REVIEW.md` now."
        chat, calls = self.chat([json.dumps(VERDICT_0123), _grounding(rewritten)])
        driver = loop.Loop(loop.LoopContext(None, None, chat, reasoner_role=ROLE))
        sess = loop.PlanSession(plan=Plan(id="test", task=retained, created="now",
                                         items=[PlanItem(rewritten)]), synthetic=True, workspace_root=ROOT)
        body = {"messages": [{"role": "user", "content": rewritten}], "tools": []}
        # Isolate the fallback to test the production done critic's own authority first.
        with mock.patch.object(loop, "_satisfaction_evidence", return_value="log"), \
             mock.patch.object(loop, "_gate_notes", return_value=""), \
             mock.patch.object(driver, "_observe_missing_file_on_done", return_value=loop.VerdictNudge()):
            out = driver._done_critic_reason(sess, body, _Rlog())
        self.assertNotEqual(getattr(out, "diagnosis_kind", ""), "missing_file")
        self.assertEqual(getattr(out, "action", ""), "")
        self.assertIn(retained, question_text(calls[1]))
        self.assertNotIn(rewritten, question_text(calls[1]))
        self.assertFalse(sess.latest_satisfaction)

    def test_done_observer_fallback_cannot_take_authority_from_continuation_argument(self):
        _bind(self)
        retained = "Fix importer only. Do not create a report."
        rewritten = "Add `REVIEW.md` now."
        chat, calls = self.chat([json.dumps({**VERDICT_0123, "missing_file": True}), _grounding(rewritten)])
        driver = loop.Loop(loop.LoopContext(None, None, chat, reasoner_role=ROLE))
        sess = loop.PlanSession(plan=Plan(id="test", task=retained, created="now", items=[PlanItem(rewritten)]),
                                workspace_root=ROOT, synthetic=True)
        body = {"messages": [{"role": "user", "content": rewritten}], "tools": []}
        with mock.patch.object(loop, "judge_satisfaction", return_value=(False, loop.VerdictNudge(), "")), \
             mock.patch.object(loop, "_satisfaction_evidence", return_value="log"), \
             mock.patch.object(loop, "_gate_notes", return_value=""):
            result = driver._done_critic_reason(sess, body, _Rlog())
        self.assertNotEqual(getattr(result, "diagnosis_kind", ""), "missing_file")
        self.assertIn(retained, question_text(calls[1]))
        self.assertNotIn(rewritten, question_text(calls[1]))
        # Direct observer invocation must not trust the legacy generated task argument either.
        chat, calls = self.chat([json.dumps({**VERDICT_0123, "missing_file": True}), _grounding(rewritten)])
        driver = loop.Loop(loop.LoopContext(None, None, chat, reasoner_role=ROLE))
        gap = driver._observe_missing_file_on_done(sess, body, rewritten, _Rlog())
        self.assertFalse(gap)
        self.assertIn(retained, question_text(calls[1]))

    def test_unknown_retained_root_never_falls_back_to_rewritten_history(self):
        _bind(self)
        rewritten = "Add `REVIEW.md` now."
        calls = []
        def chat(body, rlog):
            calls.append(body)
            return reply("{}")
        driver = loop.Loop(loop.LoopContext(None, None, chat, reasoner_role=ROLE))
        sess = loop.PlanSession(plan=Plan(id="test", task="", created="now", items=[PlanItem(rewritten)]),
                                workspace_root=ROOT, synthetic=True)
        body = {"messages": [{"role": "user", "content": rewritten}], "tools": []}
        with mock.patch.object(loop, "_satisfaction_evidence", return_value="log"), \
             mock.patch.object(loop, "_gate_notes", return_value=""):
            out = driver._done_critic_reason(sess, body, _Rlog())
        self.assertNotEqual(getattr(out, "diagnosis_kind", ""), "missing_file")
        self.assertFalse(driver._observe_missing_file_on_done(sess, body, rewritten, _Rlog()))
        self.assertEqual(calls, [])

    def test_grounded_satisfaction_arms_only_exact_remediation_without_raw_fix(self):
        _bind(self)
        chat, calls = self.chat([json.dumps(VERDICT_0086), _grounding()])
        driver = loop.Loop(loop.LoopContext(None, None, chat, reasoner_role=ROLE,
                                            satisfaction_check_start=1, satisfaction_check_every=1))
        sess = loop.PlanSession(plan=Plan(id="test", task=TASK, created="now",
                                         items=[PlanItem("Generated unrelated step")]),
                                workspace_root=ROOT)
        sess.drive_count = 1
        body = {"messages": [{"role": "user", "content": TASK}], "tools": []}
        with mock.patch.object(loop, "_satisfaction_evidence", return_value="tool log"), \
             mock.patch.object(loop, "_gate_notes", return_value=""):
            result = driver._periodic_satisfaction(sess, body, _Rlog(), plan_off=False, blocked=False)
        self.assertIsNone(result)  # negative judgment cannot complete the session
        self.assertEqual(sess.completion_remediation_subject, "REVIEW.md")
        self.assertIn("Create REVIEW.md now", sess.nudge_reason)
        self.assertIn(SPAN, sess.nudge_reason)
        self.assertNotIn(VERDICT_0086["reason"], sess.nudge_reason)
        self.assertNotIn(VERDICT_0086["proposed_fix"], sess.nudge_reason)
        self.assertNotIn("rowCount", sess.nudge_reason)
        self.assertEqual(len(calls), 2)

    def test_observer_has_a_real_requirement_question_adapter(self):
        _bind(self)
        diagnosis = {**VERDICT_0123, "missing_file": True}
        chat, calls = self.chat([_grounding()])
        with mock.patch.object(loop, "_judge_completion", return_value=json.loads(reply(json.dumps(diagnosis)))):
            out = loop.observe_task_missing_file(TASK, workspace_root=ROOT, reasoner_chat=chat,
                                                 reasoner_role=ROLE, rlog=_Rlog())
        self.assertEqual((out.action, out.diagnosis_kind, out.subject), (SPAN, "missing_file", "REVIEW.md"))
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
