"""A survey that stopped at its own bound answered "empty", "0 B", and "no tests".

`isfile` and `isdir` refuse to answer when the last survey hit a bound — they return None, and every
caller handles it. `listdir`, `scandir` and `walk` return what cria KNOWS, which is right for a
caller checking things it can see and wrong for a caller reading a short list as a complete one.
Nothing separated the two questions, so five readers turned a bound into an absence.

Measured on a real 420-file root, which the survey folds to a count (`X\\t420\\t` with an empty path):

    view.isfile("main.py")        None      <- correct
    view.listdir(...)             []
    verifytools._list_dir         ".: empty directory"    (the JUDGE's list_dir tool)
    planner_tools._list_dir       ".: empty directory"    (the PLANNER's list_dir tool)
    loop._workspace_is_empty      True

And on a real 1,169-file run workspace with `complete=True` and 7 folded directories, 503 of 1,169
files known: `_basename_matches('PT.yaml')` returned `[]` — the "genuinely absent" answer — for a
file that is on disk. It feeds `_veto_refuted_by_disk`, which prints "NOT on disk" under a sentence
calling it a verified fact.

Two more of the same family, from the write side rather than the read side:

* `note_changed` recorded an edited path the survey never named as `(0, 0.0)`, so the inventory
  printed `app.py (0 B)` while `read()` correctly answered None for the same file;
* `note_written` gave a brand-new file mtime `0.0`, which sorts LAST in every newest-first inventory
  view — the file the coder wrote this turn was treated as the oldest entry even though cria had
  observed the write itself.

And one from the discovery side: `_carries_test_code` folded "cria has not been told this file's
bytes" — which is the ORDINARY case — into "contains no test code". For Rust, where the decoration
IS the discovery rule, that becomes "No cargo test tests were found".
"""

import unittest

from cria import groundtruth, loop, planner_tools, probediscovery, verifytools, wsview

FOLDED_ROOT = "X\t420\t\n"                       # the survey folded the root to a count
EMPTY_ROOT = "D\t\n"                              # a genuinely empty workspace
REAL_TREE = "D\t\nD\tlib\nF\t5\t300\tlib/old.rb\nF\t9\t120\tREADME.md\n"


def _view(tree):
    v = wsview.View("/ws", "s")
    v._ingest_tree(tree, complete=True)
    return v


class ABoundedListingCannotSayEmptyTests(unittest.TestCase):
    def _bind(self, tree):
        v = _view(tree)
        self.addCleanup(wsview.unbind, wsview.bind(v))
        return v

    def test_the_judges_list_dir_says_it_could_not_read_it(self):
        self._bind(FOLDED_ROOT)
        out = verifytools._list_dir(".", "/ws")
        self.assertNotIn("empty directory", out)
        self.assertIn("NOT evidence", out)

    def test_the_planners_list_dir_says_the_same(self):
        self._bind(FOLDED_ROOT)
        out = planner_tools._list_dir({"path": "."}, "/ws").text
        self.assertNotIn("empty directory", out)

    def test_the_workspace_is_not_called_empty(self):
        self._bind(FOLDED_ROOT)
        self.assertFalse(loop._workspace_is_empty("/ws"))

    def test_a_genuinely_empty_workspace_still_reads_as_empty(self):
        """The honest answer must survive — this is not a blanket abstain."""
        self._bind(EMPTY_ROOT)
        self.assertIn("empty directory", verifytools._list_dir(".", "/ws"))
        self.assertIn("empty directory", planner_tools._list_dir({"path": "."}, "/ws").text)
        self.assertTrue(loop._workspace_is_empty("/ws"))

    def test_the_question_has_one_owner(self):
        self.assertFalse(_view(FOLDED_ROOT).listed_everything("/ws"))
        self.assertTrue(_view(EMPTY_ROOT).listed_everything("/ws"))
        self.assertFalse(wsview.View("/ws", "s").listed_everything("/ws"))   # never surveyed


class AnUnknownSizeIsNotZeroBytesTests(unittest.TestCase):
    def _rendered(self):
        v = _view(REAL_TREE)
        v.note_changed("/ws/app.py")                       # a path the survey never named
        v.note_written("/ws/lib/brand_new.rb", "x" * 40)    # written this turn
        self.addCleanup(wsview.unbind, wsview.bind(v))
        return groundtruth.workspace_inventory("/ws"), v

    def test_it_is_not_printed_as_zero(self):
        out, v = self._rendered()
        self.assertNotIn("app.py (0 B)", out)
        self.assertIn("app.py (size not known)", out)
        self.assertIsNone(v.size("/ws/app.py"))

    def test_a_known_size_is_still_printed(self):
        out, _ = self._rendered()
        self.assertIn("README.md (120 B)", out)
        self.assertIn("lib/brand_new.rb (40 B)", out)

    def test_the_file_cria_just_watched_being_written_is_the_newest(self):
        out, _ = self._rendered()
        names = [ln.strip().split(" ")[0] for ln in out.splitlines() if ln.startswith("  ")]
        self.assertEqual(names[0], "lib/brand_new.rb")


class AnUnreadFileHasNotBeenShownToHoldNoTestsTests(unittest.TestCase):
    def test_an_unread_body_answers_unknown(self):
        self.addCleanup(wsview.unbind, wsview.bind(_view(REAL_TREE)))
        conv = next(c for c in probediscovery.TEST_CONVENTIONS if c.marker and not c.globs)
        self.assertIsNone(probediscovery._carries_test_code("/ws/lib/old.rs", conv))

    def test_a_read_body_still_answers_yes_or_no(self):
        v = _view(REAL_TREE)
        conv = next(c for c in probediscovery.TEST_CONVENTIONS if c.marker and not c.globs)
        v.note_written("/ws/src/lib.rs", "#[test]\nfn t() {}\n")
        v.note_written("/ws/src/main.rs", "fn main() {}\n")
        self.addCleanup(wsview.unbind, wsview.bind(v))
        self.assertTrue(probediscovery._carries_test_code("/ws/src/lib.rs", conv))
        self.assertFalse(probediscovery._carries_test_code("/ws/src/main.rs", conv))


if __name__ == "__main__":
    unittest.main()
