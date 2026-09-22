"""A NOT_DONE control may survive when its diagnosis does not.

The regressions are language- and harness-neutral versions of the two Java failures from
20260905T093156: call 0053 called an existing review file missing, and call 0156 promoted a
documented risk into work the task never required.  The completion boolean must remain closed in
both cases; only unsupported coder-facing prose is removed.
"""

import json
from pathlib import Path
import tempfile
import unittest

from cria import loop, wsview
from cria.config import Role


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def kinds(self):
        return [kind for kind, _fields in self.events]


class _Ask:
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.answer


def _diagnosis(kind, *, task_quote, subject="", source="action_log", evidence_quote="",
               reason="the provider's untrusted diagnosis", fix="the provider's untrusted fix"):
    return {
        "satisfied": False,
        "reason": reason,
        "proposed_fix": fix,
        "diagnosis_kind": kind,
        "subject": subject,
        "task_quote": task_quote,
        "evidence_source": source,
        "evidence_quote": evidence_quote,
    }


class NegativeDiagnosisGroundingTests(unittest.TestCase):
    def test_an_existing_file_cannot_be_delivered_as_missing(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "REPORT.md").write_text("# Risks\n\n- latency\n", encoding="utf-8")
            task = "Add REPORT.md describing remaining risks."
            obj = _diagnosis(
                "missing_file", task_quote=task, subject="REPORT.md",
                source="workspace_absence", reason="REPORT.md is missing.")
            ask = _Ask("SUPPORTED")
            rlog = _Rlog()

            out = loop._negative_diagnosis_nudge(
                obj, task=task, workspace_root=root, ask=ask, rlog=rlog, phase="test")

            self.assertEqual(out, "")
            self.assertEqual(ask.prompts, [])
            self.assertIn("loop.negative_diagnosis_suppressed", rlog.kinds())

    def test_a_genuinely_absent_task_named_file_is_a_deterministic_fact(self):
        with tempfile.TemporaryDirectory() as root:
            task = "Add REPORT.md describing remaining risks."
            obj = _diagnosis(
                "missing_file", task_quote=task, subject="REPORT.md",
                source="workspace_absence", evidence_quote="",
                reason="REPORT.md is missing.")
            ask = _Ask("UNSUPPORTED")

            out = loop._negative_diagnosis_nudge(
                obj, task=task, workspace_root=root, ask=ask, rlog=_Rlog(), phase="test")

            self.assertIn(task, out)
            self.assertIn("REPORT.md", out)
            self.assertIn("not present", out)
            self.assertEqual(out.action, task)
            self.assertEqual(ask.prompts, [])

    def test_existing_file_and_missing_content_are_distinct_types(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "artifact.txt").write_text("status: pending\n", encoding="utf-8")
            task = "Make artifact.txt contain status: ready."
            obj = _diagnosis(
                "missing_content", task_quote=task, subject="artifact.txt",
                source="workspace_file", evidence_quote="status: pending",
                reason="artifact.txt lacks the required ready status.")
            ask = _Ask("SUPPORTED")

            out = loop._negative_diagnosis_nudge(
                obj, task=task, workspace_root=root, ask=ask, rlog=_Rlog(), phase="test")

            self.assertTrue(out)
            self.assertIn(task, out)
            self.assertIn("status: pending", out)
            self.assertEqual(len(ask.prompts), 1)

    def test_an_unknown_workspace_answer_suppresses_the_diagnosis(self):
        root = "/remote/workspace"
        token = wsview.bind(wsview.View(root, "session"))
        try:
            task = "Add REPORT.md describing remaining risks."
            obj = _diagnosis(
                "missing_file", task_quote=task, subject="REPORT.md",
                source="workspace_absence")
            out = loop._negative_diagnosis_nudge(
                obj, task=task, workspace_root=root, ask=_Ask("SUPPORTED"),
                rlog=_Rlog(), phase="test")
            self.assertEqual(out, "")
        finally:
            wsview.unbind(token)

    def test_a_dotted_method_prefix_is_not_a_task_named_file(self):
        with tempfile.TemporaryDirectory() as root:
            task = "Implement Shipping.zone_for for two-letter country codes."
            obj = _diagnosis(
                "missing_file", task_quote=task, subject="Shipping.zone",
                source="workspace_absence")
            out = loop._negative_diagnosis_nudge(
                obj, task=task, workspace_root=root, ask=_Ask("SUPPORTED"),
                rlog=_Rlog(), phase="test")
            self.assertEqual(out, "")

    def test_task_and_evidence_quotes_must_be_exact(self):
        task = "Preserve the public result."
        base = _diagnosis(
            "failed_check", task_quote="Preserve public result", source="checks",
            evidence_quote="AssertionError")
        ask = _Ask("SUPPORTED")
        self.assertEqual(loop._negative_diagnosis_nudge(
            base, task=task, checks="AssertionError: changed", ask=ask,
            rlog=_Rlog(), phase="test"), "")
        self.assertEqual(ask.prompts, [])

        base["task_quote"] = task
        base["evidence_quote"] = "assertion failed"
        self.assertEqual(loop._negative_diagnosis_nudge(
            base, task=task, checks="AssertionError: changed", ask=ask,
            rlog=_Rlog(), phase="test"), "")
        self.assertEqual(ask.prompts, [])

    def test_a_documented_risk_is_not_promoted_to_a_requirement(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "REPORT.md").write_text(
                "# Remaining risks\n\nPotential cache growth on very large inputs.\n",
                encoding="utf-8")
            task = "Add REPORT.md describing remaining risks."
            obj = _diagnosis(
                "other", task_quote=task, subject="REPORT.md",
                source="workspace_file",
                evidence_quote="Potential cache growth on very large inputs.",
                reason="The cache-growth risk must be fixed before completion.",
                fix="Eliminate cache growth.")
            ask = _Ask("UNSUPPORTED")

            out = loop._negative_diagnosis_nudge(
                obj, task=task, workspace_root=root, ask=ask, rlog=_Rlog(), phase="test")

            self.assertEqual(out, "")
            self.assertEqual(len(ask.prompts), 1)
            self.assertIn("documented risk", ask.prompts[0].lower())

    def test_an_undecidable_semantic_relation_is_suppressed(self):
        task = "Preserve the public result."
        obj = _diagnosis(
            "other", task_quote=task, source="action_log",
            evidence_quote="the command printed 17")
        ask = _Ask("UNDECIDABLE")
        out = loop._negative_diagnosis_nudge(
            obj, task=task, action_log="the command printed 17",
            checks="CURRENT CHECK: 8 passed", participation_facts="SOURCE REACH: verified",
            ask=ask, rlog=_Rlog(), phase="test")
        self.assertEqual(out, "")
        self.assertEqual(len(ask.prompts), 1)
        self.assertIn("CURRENT CHECK: 8 passed", ask.prompts[0])
        self.assertIn("SOURCE REACH: verified", ask.prompts[0])


class CartCriticCaptureReplayTests(unittest.TestCase):
    """CALL 0233 must not turn an invented map gap into coder-facing evidence.

    The captured step critic called the JSON values an absence of assignments despite the
    current ``cart.go`` action result containing the assignment loop and ``loadDiscounts()`` call.
    Its typed fields name ``action_log`` but omit the required existing-file subject, so this is
    not a source-backed missing-content diagnosis.  The raw false verdict remains fail-closed:
    the step continues rather than being approved, but the invented diagnosis cannot hold the
    coder on a fabricated red instruction.
    """

    STEP = "Read discounts.json from the workspace root directory and populate the discounts map"
    MAP_JSON = '{\n  "WELCOME10": 0.10,\n  "SUMMER25": 0.25,\n  "VIP50": 0.50\n}'
    ASSIGNMENT = "for k, v := range m {\n            discounts[k] = v\n        }"

    @staticmethod
    def _completion(content):
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def test_call_0233_unsupported_map_diagnosis_continues_without_a_red_directive(self):
        # Exact negative branch from chunk179 CALL 0233.  ``evidence`` deliberately retains the
        # raw tool voice that the critic was given, including the assignment it overlooked.
        verdict = {
            "done": False,
            "reason": "read discounts.json but discounts map not populated; no assignment of values observed",
            "proposed_fix": "assign values from discounts.json into discounts map",
            "diagnosis_kind": "missing_content",
            "subject": "",
            "task_quote": self.STEP,
            "evidence_source": "action_log",
            "evidence_quote": self.MAP_JSON,
        }
        evidence = "\n".join((
            '$ read_file {"path":"discounts.json"}', self.MAP_JSON,
            '$ read_file {"path":"cart.go"}', self.ASSIGNMENT,
            "loadDiscounts() // Populate discounts map from discounts.json",
        ))
        calls = []

        def chat(_body, _rlog):
            calls.append(1)
            return self._completion(json.dumps(verdict))

        critic = loop.Loop(loop.LoopContext(None, None, chat,
                                             reasoner_role=Role(name="reasoner", backend="local")))
        rlog = _Rlog()
        result = critic._verify(self.STEP, "", "", evidence, rlog,
                                workspace_root="", idx=1, total=1, key="cart-0233")

        done, reason = result
        self.assertFalse(done)                    # fail open only to more work, never approval
        self.assertEqual(reason, "")              # unsupported prose cannot hold the coder red
        self.assertEqual(len(calls), 1)            # invalid provenance does not spend a semantic call
        self.assertIn("loop.negative_diagnosis_suppressed", rlog.kinds())
        self.assertNotIn("no assignment of values observed", reason)
        self.assertNotIn(self.MAP_JSON, reason)
        self.assertIn(self.ASSIGNMENT, evidence)   # replay fixture preserves the tool's actual words

    def test_a_current_compiler_failure_with_an_exact_checker_quote_is_delivered_verbatim(self):
        step = "Make cart.go compile."
        checker_line = "./cart.go:40:31: undefined: decimal.NewFromFloat64"
        verdict = {
            "done": False,
            "reason": "cart.go does not compile",
            "proposed_fix": "The requested cart.go implementation must compile.",
            "diagnosis_kind": "failed_check",
            "subject": "",
            "task_quote": step,
            "evidence_source": "checks",
            "evidence_quote": checker_line,
        }
        replies = [self._completion(json.dumps(verdict)), self._completion("SUPPORTED")]

        def chat(_body, _rlog):
            return replies.pop(0)

        critic = loop.Loop(loop.LoopContext(None, None, chat,
                                             reasoner_role=Role(name="reasoner", backend="local")))
        result = critic._verify(step, "", "", "", _Rlog(), idx=1, total=1, key="compiler",
                                red_findings=checker_line)

        done, reason = result
        self.assertFalse(done)
        self.assertIn(checker_line, reason)  # checker voice, not the critic paraphrase
        self.assertNotIn("cart.go does not compile", reason)
        self.assertEqual(replies, [])


class CompletionControlIntegrationTests(unittest.TestCase):
    @staticmethod
    def _completion(obj):
        content = obj if isinstance(obj, str) else json.dumps(obj)
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def test_satisfaction_stays_not_done_when_its_diagnosis_is_refuted(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "REPORT.md").write_text("# Risks\n", encoding="utf-8")
            task = "Add REPORT.md describing remaining risks."
            obj = _diagnosis(
                "missing_file", task_quote=task, subject="REPORT.md",
                source="workspace_absence", reason="REPORT.md is missing.")

            satisfied, reason, action = loop.judge_satisfaction(
                task, "the action log", lambda _body, _rlog: self._completion(obj),
                None, _Rlog(), workspace_root=root)

            self.assertFalse(satisfied)
            self.assertEqual(reason, "")
            self.assertEqual(action, "")

    def test_satisfaction_semantic_support_judgment_is_one_shot(self):
        task = "Preserve the public result."
        obj = _diagnosis(
            "other", task_quote=task, source="action_log",
            evidence_quote="the command printed 17")
        replies = [self._completion(obj), self._completion("")]
        calls = []

        def chat(_body, _rlog):
            calls.append(1)
            return replies.pop(0)

        satisfied, reason, action = loop.judge_satisfaction(
            task, "the command printed 17", chat,
            Role(name="reasoner", backend="local"), _Rlog())

        self.assertFalse(satisfied)
        self.assertEqual(reason, "")
        self.assertEqual(action, "")
        self.assertEqual(len(calls), 2)  # verdict + one support judgment, with no retry
        self.assertEqual(replies, [])

    def test_confirm_refutation_never_becomes_approval(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "REPORT.md").write_text("# Risks\n", encoding="utf-8")
            task = "Add REPORT.md describing remaining risks."
            obj = {
                **_diagnosis(
                    "missing_file", task_quote=task, subject="REPORT.md",
                    source="workspace_absence", reason="REPORT.md is missing."),
                "consistent": False,
            }
            calls = []

            def chat(_body, _rlog):
                calls.append(1)
                return self._completion(obj)

            confirmed, reason = loop._confirm_completion(
                task, "all requested artifacts exist", root, chat,
                Role(name="reasoner", backend="local"), _Rlog(), phase="test-confirm")

            self.assertFalse(confirmed)
            self.assertEqual(reason, "")
            self.assertEqual(len(calls), 1)

    def test_confirm_does_not_confuse_missing_content_with_a_missing_file(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "artifact.txt").write_text("status: pending\n", encoding="utf-8")
            task = "Make artifact.txt contain status: ready."
            obj = {
                **_diagnosis(
                    "missing_content", task_quote=task, subject="artifact.txt",
                    source="workspace_file", evidence_quote="status: pending",
                    reason="artifact.txt lacks the required ready status."),
                "consistent": False,
            }
            replies = [self._completion(obj), self._completion("SUPPORTED")]

            def chat(_body, _rlog):
                return replies.pop(0)

            confirmed, reason = loop._confirm_completion(
                task, "artifact.txt is complete", root, chat,
                Role(name="reasoner", backend="local"), _Rlog(), phase="test-confirm")

            self.assertFalse(confirmed)
            self.assertIn("status: pending", reason)
            self.assertEqual(replies, [])

    def test_confirm_semantic_support_judgment_is_one_shot(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "artifact.txt").write_text("status: pending\n", encoding="utf-8")
            task = "Make artifact.txt contain status: ready."
            obj = {
                **_diagnosis(
                    "missing_content", task_quote=task, subject="artifact.txt",
                    source="workspace_file", evidence_quote="status: pending",
                    reason="artifact.txt lacks the required ready status."),
                "consistent": False,
            }
            replies = [self._completion(obj), self._completion("")]
            calls = []

            def chat(_body, _rlog):
                calls.append(1)
                return replies.pop(0)

            confirmed, reason = loop._confirm_completion(
                task, "artifact.txt is complete", root, chat,
                Role(name="reasoner", backend="local"), _Rlog(), phase="test-confirm")

            self.assertFalse(confirmed)
            self.assertEqual(reason, "")
            self.assertEqual(len(calls), 2)  # verdict + one support judgment, with no retry
            self.assertEqual(replies, [])


if __name__ == "__main__":
    unittest.main()
