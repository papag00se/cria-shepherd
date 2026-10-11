"""A task-named file the workspace proves absent is a missing file whatever kind the judge labelled it.

A1 call 0021 (capture 20261010T212733): `diagnosis_kind=missing_content`, `subject=REVIEW.md`,
`task_quote` = "Add `REVIEW.md` describing remaining problems or risks in the code you changed." (exact),
`evidence_source=workspace_absence`, `evidence_quote=""`. Every checkable field was true; the one
verdict whose quote was exact in 13 died on "missing-content source contract" — a label.
"""
import json
import unittest
from unittest import mock

from cria import loop, prompts, wsview
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
        out = loop._negative_diagnosis_nudge(obj, task=task, workspace_root=ROOT, ask=_Ask("SUPPORTED"),
                                             rlog=rlog, phase="test")
        return out, rlog

    def test_the_a1_verdict_becomes_a_deterministic_missing_file(self):
        _bind(self, f"F\t1\t980\tpom.xml")
        out, rlog = self.ruling(_verdict())
        self.assertEqual((out.diagnosis_kind, out.subject), ("missing_file", "REVIEW.md"))
        self.assertIn(QUOTE, out)
        self.assertIn("loop.negative_diagnosis_canonicalised", rlog.kinds())
        self.assertNotIn("loop.negative_diagnosis_suppressed", rlog.kinds())

    def test_other_labels_with_absence_evidence_are_canonicalised_too(self):
        _bind(self, "F\t1\t980\tpom.xml")
        for kind in ("unverified_requirement", "other", "failed_check"):
            with self.subTest(kind):
                self.assertEqual(self.ruling(_verdict(kind=kind))[0].diagnosis_kind, "missing_file")

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
        with mock.patch.object(loop, "judge_satisfaction", lambda *a, **k: (False, "", "")), \
             mock.patch.object(loop, "observe_task_missing_file", return_value=gap) as obs:
            reason = _loop(lambda *a: b"{}")._done_critic_reason(s, _body(), _LoopRlog())
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
        with mock.patch.object(loop, "judge_satisfaction", lambda *a, **k: (False, typed, "")), \
             mock.patch.object(loop, "observe_task_missing_file") as obs:
            reason = _loop(lambda *a: b"{}")._done_critic_reason(s, _body(), _LoopRlog())
        self.assertEqual(reason, typed)
        obs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
