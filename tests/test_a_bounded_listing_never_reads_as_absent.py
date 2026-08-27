"""A listing that stopped at its own budget must read as UNKNOWN, never as "not there".

The survey walks the workspace under two bounds — TREE_MAX_ENTRIES and a byte budget. When the inner
file loop broke on either, the directory had already been popped off the queue, its remaining files
were neither emitted nor folded, no `X` record named it, and `complete` stayed 1. So:

  * `View.isfile("pkg/file_60.py")` answered **False** for a file that exists, and
  * `groundtruth.workspace_inventory` told every judge, the planner, the briefing writer and the
    coder "This list is complete — a file not listed here does not exist in the workspace."

The budget makes this the normal case, not the edge: a gate-carried survey's tree budget is
`INLINE_RESULT_MAX_BYTES - section_cap*probes - markers`, and `section_cap*probes` is ~7,400 by
construction, so the survey lands on TREE_MIN_BYTES — about sixteen entries — however big the
workspace is.

This is the same defect the `X\\t<count>\\t` root-fold branch was written to fix, one loop further
in: a bound that turns "I could not look" into "it is not there" (#5b, #11b).
"""
import pathlib
import subprocess
import tempfile
import unittest

from cria import wsview


class ABoundedListingNeverReadsAsAbsent(unittest.TestCase):

    def _survey(self, root, budget):
        cmd = wsview.survey_command("t", cd=str(root), budget=budget)
        out = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True,
                             timeout=120).stdout
        _body, survey = wsview.strip_survey(out)
        view = wsview.View(str(root), "t")
        self.assertTrue(wsview.apply_survey(view, survey), "the survey itself is well-formed")
        return view

    def _tree(self, n):
        d = pathlib.Path(tempfile.mkdtemp()) / "pkg"
        d.mkdir(parents=True)
        for i in range(n):
            (d / f"file_{i}.py").write_text("x = 1\n")
        return d.parent

    def test_a_file_past_the_budget_is_unknown_not_missing(self):
        root = self._tree(61)
        view = self._survey(root, wsview.TREE_MIN_BYTES)
        self.assertLess(len(view._files), 61, "the budget really did bite")
        self.assertIsNone(view.isfile("pkg/file_60.py"),
                          "a file the survey never reached is unknown, not absent")
        self.assertFalse(view.listed_everything(),
                         "and the inventory must not claim the list is complete")

    def test_a_tree_that_fits_still_reads_as_complete(self):
        root = self._tree(3)
        view = self._survey(root, None)
        self.assertTrue(view.listed_everything())
        self.assertTrue(view.isfile("pkg/file_1.py"))
        self.assertFalse(view.isfile("pkg/nope.py"),
                         "inside a complete listing, absent really does mean absent")


if __name__ == "__main__":
    unittest.main()
