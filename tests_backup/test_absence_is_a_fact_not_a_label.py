"""A task-named file the workspace proves absent is a missing file whatever kind the judge labelled it.

A1 call 0021 (capture 20261010T212733): `diagnosis_kind=missing_content`, `subject=REVIEW.md`,
`task_quote` = "Add `REVIEW.md` describing remaining problems or risks in the code you changed." (exact),
`evidence_source=workspace_absence`, `evidence_quote=""`. Every checkable field was true; the one
verdict whose quote was exact in 13 died on "missing-content source contract" — a label.
"""
import json
import unittest
from unittest import mock

from cria import completiondiagnosis, loop, prompts, wsview
from tests.test_a_gap_the_disk_can_settle_is_not_an_opinion import _selected_observer
from tests.test_a_judges_doubt_is_not_an_order import _Rlog as _LoopRlog, _body, _loop, _session
from tests.test_negative_diagnosis_provenance import _Ask, _Rlog, _diagnosis
from tests.wsfixture import survey

ROOT = "/home/jesse/suite-runs/suite-feed-pipeline-java_phi4_codex_poff_1791692850-a4adqg72"
QUOTE = "Add `REVIEW.md` describing remaining problems or risks in the code you changed."
TASK = "Fix these three problems in the supplier feed importer.\n\n" + QUOTE + " For every issue, include the file name."


def _bind(case, tree):
    view = wsview.View(ROOT, "absence")
    assert wsview.apply_survey(view, survey(tree, root=ROOT))
    token = wsview.bind(view)
    case.addCleanup(wsview.unbind, token)


def _verdict(**kw):
    return _diagnosis(kw.pop("kind", "missing_content"), task_quote=kw.pop("quote", QUOTE),
                      subject=kw.pop("subject", "REVIEW.md"), source=kw.pop("source", "workspace_absence"),
                      evidence_quote=kw.pop("evidence_quote", ""), **kw)


class CanonicaliseTests(unittest.TestCase):
    def ruling(self, obj, task=TASK):
        rlog = _Rlog()
        # Only originally typed missing_file needs the new required-output question. Canonicalized
        # absence facts still cost no question and carry no remediation authority.
        ask = _Ask(json.dumps({"required_output": True, "subject": obj["subject"], "task_quote": QUOTE}))
        out = loop._negative_diagnosis_nudge(obj, task=task, workspace_root=ROOT, ask=ask,
                                             rlog=rlog, phase="test")
        return out, rlog

    def test_the_a1_verdict_becomes_a_deterministic_missing_file(self):
        _bind(self, f"F\t1\t980\tpom.xml")
        out, rlog = self.ruling(_verdict())
        # Re-typed by cria from an absence fact: it says the named file is not there, and carries a kind
        # NO remediation site acts on (a task can name an INPUT that is absent — no "create it" order).
        self.assertEqual((out.diagnosis_kind, out.subject), ("absent_named_file", "REVIEW.md"))
        self.assertIn("not present", out)
        self.assertIn(QUOTE, out)
        self.assertIn("loop.negative_diagnosis_canonicalised", rlog.kinds())
        self.assertNotIn("loop.negative_diagnosis_suppressed", rlog.kinds())

    def test_other_labels_with_absence_evidence_are_canonicalised_too(self):
        _bind(self, "F\t1\t980\tpom.xml")
        for kind in ("unverified_requirement", "other", "failed_check"):
            with self.subTest(kind):
                self.assertEqual(self.ruling(_verdict(kind=kind))[0].diagnosis_kind, "absent_named_file")

    def test_a_present_file_stays_suppressed(self):
        _bind(self, "F\t1\t980\tpom.xml\nF\t1\t12\tREVIEW.md")
        out, rlog = self.ruling(_verdict())
        self.assertEqual(out, "")
        self.assertIn("loop.negative_diagnosis_suppressed", rlog.kinds())

    def test_an_unknown_workspace_stays_suppressed(self):
        token = wsview.bind(wsview.View(ROOT, "nothing-surveyed"))
        self.addCleanup(wsview.unbind, token)
        self.assertEqual(self.ruling(_verdict())[0], "")

    def test_a_subject_that_is_only_a_prefix_of_a_task_token_stays_suppressed(self):
        _bind(self, "F\t1\t980\tpom.xml")
        task = "Implement Shipping.zone_for for two-letter country codes."
        out, _ = self.ruling(_verdict(subject="Shipping.zone", quote=task), task=task)
        self.assertEqual(out, "")

    def test_an_inexact_task_quote_stays_suppressed(self):
        _bind(self, "F\t1\t980\tpom.xml")
        stitched = "Add REVIEW.md describing remaining problems or risks."      # not a substring of the task
        self.assertEqual(self.ruling(_verdict(quote=stitched))[0], "")

    def test_a_missing_content_claim_about_an_existing_file_is_not_touched(self):
        """The real missing_content contract (source workspace_file) is exactly as before."""
        _bind(self, "F\t1\t980\tpom.xml")
        out, _ = self.ruling(_verdict(source="workspace_file", evidence_quote="<project>"))
        self.assertEqual(out, "")


    def test_a_judge_typed_missing_file_keeps_its_type(self):
        """Only the RE-typed diagnosis is demoted; one the judge itself called missing_file is unchanged."""
        _bind(self, "F\t1\t980\tpom.xml")
        self.assertEqual(self.ruling(_verdict(kind="missing_file"))[0].diagnosis_kind, "missing_file")

    def test_a_retyped_absence_delivers_no_create_order(self):
        """Driven through the periodic delivery site: a RE-typed absence (a task can name an absent INPUT)
        reaches the coder as a neutral gap; the judge-typed missing_file still gets the 'Create X now' order."""
        from tests.test_a_gap_the_disk_can_settle_is_not_an_opinion import _drive
        retyped = loop.VerdictNudge("The task-named file data/feed.csv is not present.", "q",
                                    diagnosis_kind="absent_named_file", subject="data/feed.csv")
        typed = loop.VerdictNudge("The task-named file data/feed.csv is not present.", "q",
                                  diagnosis_kind="missing_file", subject="data/feed.csv")
        sess, _, _ = _drive(retyped)
        self.assertIn("not present", sess.nudge_reason)
        self.assertNotIn("Create data/feed.csv now", sess.nudge_reason)
        sess, _, _ = _drive(typed)
        self.assertIn("Create data/feed.csv now", sess.nudge_reason)


class PlanOffObserverTests(unittest.TestCase):
    """A negative completion verdict whose diagnosis was suppressed asks the plan-ON observer (A1: 0007, 0016, 0031)."""

    def critic(self, gap, *, survey_tree="F\t1\t980\tpom.xml", surveyed=True):
        s = _session()
        s.workspace_root = ROOT
        s.plan.task = TASK
        if surveyed:
            _bind(self, survey_tree)
        else:
            token = wsview.bind(wsview.View(ROOT, "x"))
            self.addCleanup(wsview.unbind, token)
        typed_gap = (completiondiagnosis.DiagnosisResult(completiondiagnosis.DiagnosisStatus.GROUNDED,
            gap.evidence,gap.action,gap.diagnosis_kind,gap.subject) if gap else
            completiondiagnosis.DiagnosisResult(completiondiagnosis.DiagnosisStatus.NOT_APPLICABLE))
        obs = mock.Mock(return_value=typed_gap)
        with mock.patch.object(loop, "judge_satisfaction", lambda *a, **k: (False, "", "")), \
             _selected_observer(obs):
            reason = _loop(lambda *a: b"{}")._done_critic_reason(s, _body(), _LoopRlog())
        if surveyed:
            obs.assert_called_once_with(completiondiagnosis.ObservationInput(TASK,True),mock.ANY)
        return reason, obs

    def test_a_suppressed_verdict_over_an_absent_named_file_reaches_the_coder_typed(self):
        gap = loop.VerdictNudge("The task-named file REVIEW.md is not present.", QUOTE,
                                diagnosis_kind="missing_file", subject="REVIEW.md")
        reason, obs = self.critic(gap)
        self.assertEqual(reason, gap)
        self.assertEqual(reason.subject, "REVIEW.md")
        obs.assert_called_once()

    def test_nothing_observed_falls_back_to_the_unnamed_gap(self):
        reason, obs = self.critic(loop.VerdictNudge())
        self.assertTrue(reason.startswith(prompts.load("done_no_named_gap")))
        obs.assert_called_once()

    def test_without_a_complete_current_survey_the_observer_is_not_even_asked(self):
        reason, obs = self.critic(loop.VerdictNudge("x", "y", diagnosis_kind="missing_file", subject="a"),
                                  surveyed=False)
        self.assertTrue(reason.startswith(prompts.load("done_no_named_gap")))
        obs.assert_not_called()

    def test_a_typed_verdict_is_never_second_guessed(self):
        typed = loop.VerdictNudge("typed", "q", diagnosis_kind="missing_file", subject="X.md")
        s = _session()
        s.workspace_root = ROOT
        _bind(self, "F\t1\t980\tpom.xml")
        obs = mock.Mock(side_effect=AssertionError("typed verdict must not ask the selected observer"))
        with mock.patch.object(loop, "judge_satisfaction", lambda *a, **k: (False, typed, "")), \
             _selected_observer(obs):
            reason = _loop(lambda *a: b"{}")._done_critic_reason(s, _body(), _LoopRlog())
        self.assertEqual(reason, typed)
        obs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
