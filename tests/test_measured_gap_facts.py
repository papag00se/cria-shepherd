"""A completion check that names no gap used to say the SAME constant every cycle.

A1 (capture 20261010T212733): the judge's verdict was suppressed 12 of 13 times, so the steer was
`done_no_named_gap` — "go through the task's deliverables one by one" — byte for byte, twelve cycles,
while the workspace sat pristine and every reply was prose with fenced code and no call. cria HELD two
facts that say so (file sizes/mtimes since the first complete survey; the fence parse the unexecuted-write
nudge uses) and stated neither. They are appended — as facts, never as an order — when and only when they
are measurable.
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from cria import loop, prompts, wsview
from cria.config import Role
from tests.test_a_judges_doubt_is_not_an_order import _Rlog, _body, _loop, _session
from tests.wsfixture import survey

ROOT = "/home/jesse/suite-runs/suite-feed-pipeline-java_phi4_codex_poff_1791692850-a4adqg72"
JAVA = "src/main/java/pipeline/Importer.java"
FIX = json.loads((Path(__file__).parent / "fixtures" / "phi4_text_actions" / "replies.json").read_text())
A1_REPLY = FIX["replies"]["a1_0022"]["content"]
TREE = f"D\tsrc\nD\tsrc/main\nD\tsrc/main/java\nD\tsrc/main/java/pipeline\nF\t1\t4543\t{JAVA}\nF\t1\t980\tpom.xml"


def _view(tree=TREE, complete=True):
    v = wsview.View(ROOT, "gap-facts")
    assert wsview.apply_survey(v, survey(tree, root=ROOT, complete=complete))
    return v


class MeasuredGapFactsTests(unittest.TestCase):
    def sess(self):
        s = _session()
        s.workspace_root = ROOT
        s.read_files = {f"{ROOT}/{JAVA}": (4543, "4543 bytes, 130 lines"), f"{ROOT}/pom.xml": (980, "980 bytes")}
        return s

    def bind(self, view):
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)

    def test_the_pristine_workspace_and_the_pasted_fences_are_stated_as_facts(self):
        s = self.sess()
        self.bind(_view())
        loop._note_survey_baseline(s, ROOT)
        out = loop._unnamed_gap(s, A1_REPLY)
        self.assertTrue(out.startswith(prompts.load("done_no_named_gap")))         # the base is kept
        self.assertIn(f"  {JAVA} (4543 bytes)", out)
        self.assertIn("  pom.xml (980 bytes)", out)
        self.assertIn("unchanged on disk", out)
        self.assertIn("fenced code block(s) (xml, java, markdown, plaintext;", out)
        self.assertIn("no file was written or edited by that message", out)
        self.assertNotIn("no tool call", out)      # a task_complete done HAS a tool call; the fact says only what is measured
        self.assertNotIn("cria", out.lower())                                       # invisible (#17)
        for order in ("write", "call write_file", "edit "):                          # facts, not a directive
            self.assertNotIn(f"you should {order}", out)

    def test_a_changed_file_is_reported_as_changed_not_unchanged(self):
        s = self.sess()
        self.bind(_view())
        loop._note_survey_baseline(s, ROOT)
        self.bind(_view(TREE.replace("\t4543\t", "\t4999\t")))          # same mtime field, new size
        out = loop._unnamed_gap(s, "")
        self.assertIn("have changed on disk", out)
        self.assertIn(f"  {JAVA} (4999 bytes)", out)
        self.assertIn("  pom.xml (980 bytes)", out)                      # the other one is still unchanged

    def test_it_abstains_without_a_complete_baseline_and_a_complete_current_listing(self):
        s = self.sess()
        self.bind(_view(complete=False))
        loop._note_survey_baseline(s, ROOT)
        self.assertIsNone(s.survey_baseline)                              # a partial picture is no baseline
        self.assertEqual(loop._unnamed_gap(s, ""), prompts.load("done_no_named_gap"))
        self.bind(_view())
        loop._note_survey_baseline(s, ROOT)
        self.bind(_view(complete=False))                                  # baseline exists, listing now partial
        self.assertEqual(loop._unnamed_gap(s, ""), prompts.load("done_no_named_gap"))

    def test_a_listing_a_mutator_has_overtaken_is_not_a_current_fact(self):
        """Same freshness rule as the F7 observer: after a command that may have changed the tree, "unchanged
        on disk now" is not something the stale listing can state."""
        s = self.sess()
        v = _view()
        self.bind(v)
        loop._note_survey_baseline(s, ROOT)
        self.assertIn("unchanged on disk", loop._unnamed_gap(s, ""))
        v.note_a_mutator_ran()
        self.assertEqual(loop._unnamed_gap(s, ""), prompts.load("done_no_named_gap"))

    def test_no_fences_and_no_baseline_leaves_the_constant_exactly(self):
        self.assertEqual(loop._unnamed_gap(self.sess(), "All done, the tests pass."),
                         prompts.load("done_no_named_gap"))

    def test_the_baseline_is_the_first_one_and_is_never_replaced(self):
        s = self.sess()
        self.bind(_view())
        loop._note_survey_baseline(s, ROOT)
        first = dict(s.survey_baseline)
        self.bind(_view(TREE.replace("\t980\t", "\t5\t")))
        loop._note_survey_baseline(s, ROOT)
        self.assertEqual(s.survey_baseline, first)

    def test_the_plan_off_critic_uses_it_when_the_judge_names_nothing(self):
        s = self.sess()
        s.pending_done = A1_REPLY
        self.bind(_view())
        loop._note_survey_baseline(s, ROOT)
        with mock.patch.object(loop, "judge_satisfaction", lambda *a, **k: (False, "", "")):
            reason = _loop(None)._done_critic_reason(s, _body(), _Rlog())
        self.assertIn("Observed just now", reason)
        self.assertIn(f"  {JAVA} (4543 bytes)", reason)


if __name__ == "__main__":
    unittest.main()
