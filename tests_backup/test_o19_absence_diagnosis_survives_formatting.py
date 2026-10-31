"""O19: actual B4 typed diagnoses survive, without accepting altered literal requirements."""
import json
import unittest

from cria import loop, wsview
from cria.config import Role
from tests.test_negative_diagnosis_provenance import _Ask, _Rlog
from tests.wsfixture import survey

ROOT = "/home/jesse/suite-runs/o19"
SPAN = ("Add `REVIEW.md` describing remaining problems or risks in the code you changed. For every "
        "issue, include the file name and line number.")
TASK = "Fix the importer.\n\n" + SPAN

# Copied from 20261012T095640-01a1310b… / 0086-satisfaction's verdict arguments. Raw prose is
# deliberately preserved here: its Java claims and prescriptive repair must NOT reach the coder.
VERDICT_0086 = {
    "satisfied": False,
    "reason": "Two independent, evidence-grounded failures. (1) A required deliverable is entirely absent: the task mandates \"Add REVIEW.md describing remaining problems or risks in the code you changed. For every issue, include the file name and line number.\" The authoritative current workspace listing (`list_dir \".\"`) shows only README.md, data/, pom.xml, src/, target/ (total 8 entries) — no REVIEW.md exists. (2) Core requirement #2 is not met by the code: `src/main/java/pipeline/Importer.java` still does shared static-counter updates from inside the parallel worker threads via non-atomic compound increments (`rowCount += 1;` and `skippedMissingSku++` / `skippedInvalidQuantity++` / `skippedInvalidPrice++`). These are `static volatile int` fields, and volatile guarantees visibility, not atomicity of a read-modify-write — so concurrent threads lose updates and the JVM may permit any result. `rowCount` feeds \"imported %d rows\" in main() output and each counter feeds the skip breakdown, so repeated processing of the same feed is NOT guaranteed to yield identical results (violating req #2) and the reported skip counts are corrupted (violating req #3). The repo's own checks only confirm a successful compile and \"No tests to run\" — no @Test sources exist — so green does not verify this behavior. Both defects remain visible in the current file bytes; I cannot execute mvn/java here to re-demonstrate either, but neither needs execution to read plainly from the code.",
    "proposed_fix": "REVIEW.md must exist at the project root (describing changed-code risks with file name + line number for each), and Importer.java's updates of rowCount and skippedMissingSku/Quantity/Price from the worker threads must be made atomic/synchronized so repeated runs are deterministic and skip counts are correct.",
    "diagnosis_kind": "missing_file",
    "subject": "REVIEW.md",
    "task_quote": SPAN,
    "evidence_source": "workspace_absence",
    "evidence_quote": "drwxr-xr-x 1 jesse jesse   370 Oct 12 09:56 README.md / drwxr-xr-x 1 jesse jesse  116 Oct 12 10:11 data / -rw-r--r-- 1 jesse jesse  1080 Oct 12 10:03 pom.xml / drwxr-xr-x 1 jesse jesse     8 Oct 12 09:56 src / drwxr-xr-x 1 jesse jesse    72 Oct 12 09:58 target  (no REVIEW.md among the total 8 entries)",
}
VERDICT_0123 = {
    "satisfied": False,
    "reason": "The required deliverable REVIEW.md does not exist anywhere in the workspace (root listing shows only .agents/, .aws/, .codex/, README.md, data/, pom.xml, src/, target/). The task explicitly requires: \"Add REVIEW.md describing remaining problems or risks in the code you changed. For every issue, include the file name and line number.\" It is absent. The other deliverables appear implemented: Importer.java now uses a thread-safe merge (PerRowSkips objects + order-independent partial merge, no duplicate rowCount), depends on commons-csv 1.10.0 (third-party CSV library added to pom.xml dependencies), the messy-CSV handling rules are present, and README notes worker safety. However, three task requirements cannot be considered satisfied: (a) REVIEW.md is missing entirely; (b) there are no in-repo tests and mvn test reports \"No tests to run\", so required correctness/determinism behaviors were never demonstrated by executed assertions — only ad-hoc console runs, which under the judging rules do not prove behavior; (c) the README still claims \"Parallel workers are switched off\" while WORKERS_ENABLED=true, which is internally inconsistent with task #2. The strongest single missing artifact is REVIEW.md, named rather than guessed per instructions.",
    "proposed_fix": "Add a REVIEW.md at the project root documenting remaining risks/problems in the changed code, with each issue's file name and line number (e.g., integer-only quantity parsing at Importer.java valueFor(), README statement saying workers are off).",
    "diagnosis_kind": "missing_file",
    "subject": "REVIEW.md",
    "task_quote": "Add REVIEW.md describing remaining problems or risks in the code you changed. For every issue, include the file name and line number.",
    "evidence_source": "workspace_absence",
    "evidence_quote": "root listing shows only .agents/, .aws/, .codex/, README.md, data/, pom.xml, src/, target/; no REVIEW.md",
}


def _bind(case, tree="F\t1\t980\tpom.xml"):
    view = wsview.View(ROOT, "o19")
    assert wsview.apply_survey(view, survey(tree, root=ROOT))
    token = wsview.bind(view)
    case.addCleanup(wsview.unbind, token)


def _grounding(quote=SPAN, subject="REVIEW.md", required=True):
    return json.dumps({"required_output": required, "subject": subject, "task_quote": quote})


def _rule(obj, task=TASK, ask=None):
    # This independent answer, not the initial verdict's quote, authorizes the output requirement.
    return loop._negative_diagnosis_nudge(obj, task=task, workspace_root=ROOT,
                                         ask=ask or _Ask(_grounding()), rlog=_Rlog(), phase="test")


class CaptureDeliveryTests(unittest.TestCase):
    def test_actual_0086_and_0123_deliver_only_grounded_type_and_original_task_span(self):
        _bind(self)
        for obj in (VERDICT_0086, VERDICT_0123):
            with self.subTest(quote=obj["task_quote"]):
                out = _rule(obj)
                self.assertEqual((out.diagnosis_kind, out.subject), ("missing_file", "REVIEW.md"))
                self.assertEqual(out.action, SPAN)
                self.assertIn(SPAN, out)
                self.assertIn("not present", out)
                for raw in (obj["reason"], obj["proposed_fix"], obj["evidence_quote"]):
                    self.assertNotIn(raw, out)
                    self.assertNotIn(raw, out.action)
                self.assertNotIn("rowCount", out)
                self.assertNotIn("atomic/synchronized", out.action)

    def test_actual_negative_verdicts_stay_false_in_production_satisfaction_return(self):
        _bind(self)
        for obj in (VERDICT_0086, VERDICT_0123):
            with self.subTest(quote=obj["task_quote"]):
                calls = []

                def chat(body, rlog):
                    calls.append(body)
                    content = json.dumps(obj) if len(calls) == 1 else _grounding()
                    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

                satisfied, reason, action = loop.judge_satisfaction(
                    TASK, "the tool log", chat, Role(name="reasoner", backend="local"),
                    _Rlog(), workspace_root=ROOT)
                self.assertFalse(satisfied)
                self.assertEqual(action, SPAN)
                self.assertIn(SPAN, reason)
                self.assertEqual(len(calls), 2)  # initial verdict + independent requirement question
                for raw in (obj["reason"], obj["proposed_fix"], obj["evidence_quote"]):
                    self.assertNotIn(raw, reason)
                    self.assertNotIn(raw, action)
                self.assertNotIn("rowCount", reason)


class ScopeTests(unittest.TestCase):
    def test_file_actually_present(self):
        _bind(self, "F\t1\t980\tpom.xml\nF\t1\t12\tREVIEW.md")
        for obj in (VERDICT_0086, VERDICT_0123):
            self.assertFalse(_rule(obj))

    def test_subject_not_named(self):
        _bind(self)
        self.assertFalse(_rule({**VERDICT_0123, "subject": "NOTES.md"}))

    def test_unknown_workspace(self):
        self.assertFalse(_rule(VERDICT_0086))
        self.assertFalse(_rule(VERDICT_0123))

    def test_initial_literal_quote_is_not_requirement_authority_either(self):
        _bind(self)
        out = _rule({**VERDICT_0086, "task_quote": "REVIEW.md"})
        self.assertEqual(out.action, SPAN)

    def test_other_kind_or_source_cannot_use_backtick_recovery(self):
        _bind(self)
        for kind, source in [("other", "action_log"), ("missing_content", "workspace_absence"),
                             ("missing_file", "workspace_file"), ("failed_check", "checks")]:
            with self.subTest(kind=kind, source=source):
                self.assertFalse(_rule({**VERDICT_0123, "diagnosis_kind": kind,
                                        "evidence_source": source}))


class AdversarialRecoveryTests(unittest.TestCase):
    def test_literal_inner_backticks_and_fenced_regions_are_not_subject_wrappers(self):
        _bind(self)
        for task, quote in [
            ('Add REVIEW.md containing exactly ``literal `REVIEW.md` text``.',
             'Add REVIEW.md containing exactly ``literal REVIEW.md text``.'),
            ('Add REVIEW.md containing exactly:\n```text\n`REVIEW.md`\n```',
             'Add REVIEW.md containing exactly:\n```text\nREVIEW.md\n```'),
            ('Add REVIEW.md containing exactly:\n~~~text\n`REVIEW.md`\n~~~',
             'Add REVIEW.md containing exactly:\n~~~text\nREVIEW.md\n~~~'),
            ('An unclosed ` literal. Add `REVIEW.md` now',
             'An unclosed ` literal. Add REVIEW.md now'),
        ]:
            with self.subTest(task=task):
                # An invalid independent extraction, NOT a formatting-equivalence comparison.
                out = _rule({**VERDICT_0123, "task_quote": quote}, task, _Ask(_grounding(quote)))
                self.assertFalse(out)
                self.assertEqual(out.action, "")
                self.assertEqual(out.diagnosis_kind, "")
                self.assertEqual(out.subject, "")

    def test_nonliteral_recovery_must_cover_whole_file_token_and_delimiter_unit(self):
        _bind(self)
        for task, quote in [
            ("Add `REVIEW.md.bak`.", "Add REVIEW.md"),
            ("Add `REVIEW.md`suffix", "Add REVIEW.md"),
            ("Add `REVIEW.md`.bak", "Add REVIEW.md"),
            ("Add prefix`REVIEW.md`.", "Add prefixREVIEW.md"),
            ("Add `REVIEW.md`/child", "Add REVIEW.md"),
            ("Add `REVIEW.md`*", "Add REVIEW.md"),
            ("Add `REVIEW.md`.", "Add REVIEW"),
            ("Add `REVIEW.md`.", "VIEW.md."),
            ("Before Add `REVIEW.md` describing risks", "Add REVIEW.md describ"),
            ("ReAdd `REVIEW.md` now", "Add REVIEW.md now"),
        ]:
            with self.subTest(task=task, quote=quote):
                out = _rule({**VERDICT_0123, "task_quote": quote}, task, _Ask(_grounding(quote)))
                self.assertFalse(out)
                self.assertEqual(out.action, "")
                self.assertEqual(out.diagnosis_kind, "")
                self.assertEqual(out.subject, "")

    def test_reviewer_literal_whitespace_and_globs_are_not_formatting(self):
        _bind(self)
        for task, quote in [
            ('Add `REVIEW.md` containing `"a  b"`.', 'Add REVIEW.md containing "a b".'),
            ('Add `REVIEW.md` containing "a  b".', 'Add REVIEW.md containing "a b".'),
            ('Add `REVIEW.md` containing `a\tb`.', 'Add REVIEW.md containing a b.'),
            ('Add "*REVIEW.md*" now', 'Add "REVIEW.md" now'),
            ('Add "_REVIEW.md_" now', 'Add "REVIEW.md" now'),
            ("Add `REVIEW.md`  now", "Add REVIEW.md now"),
            ("Add `REVIEW.md`\tnow", "Add REVIEW.md now"),
            ("Add **`REVIEW.md`** now", "Add REVIEW.md now"),
            ("Add src/__REVIEW.md__/x", "Add src/REVIEW.md/x"),
            ("Add `REVIEW.md` with `a*b*c`", "Add REVIEW.md with abc"),
            ("Add `REVIEW.md` with a * b", "Add REVIEW.md with a b"),
            (r"Add \`REVIEW.md\` now", "Add REVIEW.md now"),
            ("Add `REVIEW.md now", "Add REVIEW.md now"),
            ("Add ``REVIEW.md`` now", "Add REVIEW.md now"),
        ]:
            with self.subTest(task=task, quote=quote):
                self.assertFalse(_rule({**VERDICT_0123, "task_quote": quote}, task,
                                       _Ask(_grounding(quote))))

    def test_other_literal_bytes_survive_allowed_wrapper_omission(self):
        _bind(self)
        task = 'Add `REVIEW.md`\t containing "a  b", `a*b*c`, and src/__data__/x.'
        quote = task.replace("`REVIEW.md`", "REVIEW.md")
        out = _rule({**VERDICT_0123, "task_quote": quote}, task, _Ask(_grounding(task)))
        self.assertEqual(out.action, task)
        self.assertIn(task, out)


if __name__ == "__main__":
    unittest.main()
