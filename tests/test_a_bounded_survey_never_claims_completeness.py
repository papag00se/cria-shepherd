"""A workspace with 420 files in its root read as `none — the workspace has no files`.

The survey folds a directory holding more than FOLD_AT files into one `X` record and stops walking
it. For the ROOT that record's path is the empty string, and `_ingest_tree` dropped it on `if d:` —
so `_files`, `_dirs` and `_folded` all stayed empty while `_surveyed` and `_complete` stayed True.
Every predicate then answered False rather than None, and `groundtruth.workspace_inventory` told the
step critic, the satisfaction judge, the planner and the briefing writer:

    WORKSPACE FILES in <root>: none — the workspace has no files at judging time.

Reproduced on a 420-file root: `isfile(main.py)` returned False, not None.

Two halves, both here. The view must record that it was bounded, and the renderer must stop stamping
`This list is complete — a file not listed here does not exist in the workspace` on a listing built
from a survey that hit its own limit (#5b, #11b, #23c).
"""

import pathlib
import subprocess
import tempfile
import unittest

from cria import groundtruth, wsview


def _surveyed(n_files: int, extra: str | None = None) -> tuple[str, wsview.View]:
    ws = tempfile.mkdtemp()
    for i in range(n_files):
        pathlib.Path(ws, f"f{i:04}.py").write_text("x\n")
    if extra:
        pathlib.Path(ws, extra).write_text("print(1)\n")
    v = wsview.View(ws, "s")
    token = wsview.bind(v)
    raw = subprocess.run(["bash", "-c", wsview.survey_command("s", cd=ws)], cwd=ws,
                         capture_output=True, text=True).stdout
    wsview.apply_survey(v, wsview.strip_survey(raw)[1])
    return ws, v, token


class ARootTooBigToWalkIsNotAnEmptyWorkspaceTests(unittest.TestCase):
    def test_the_view_records_that_it_was_bounded(self):
        ws, v, token = _surveyed(wsview.FOLD_AT + 20, "main.py")
        self.addCleanup(wsview.unbind, token)
        self.assertFalse(v.complete, "the survey hit its bound and did not say so")

    def test_a_file_it_never_reached_is_unknown_not_absent(self):
        ws, v, token = _surveyed(wsview.FOLD_AT + 20, "main.py")
        self.addCleanup(wsview.unbind, token)
        self.assertIsNone(v.isfile(str(pathlib.Path(ws, "main.py"))),
                          "a path the survey never reached was reported as absent")

    def test_the_inventory_does_not_call_it_empty(self):
        ws, v, token = _surveyed(wsview.FOLD_AT + 20, "main.py")
        self.addCleanup(wsview.unbind, token)
        out = groundtruth.workspace_inventory(ws)
        self.assertNotIn("has no files", out)
        self.assertNotIn("is empty", out)


class TheCompletenessClauseIsEarnedTests(unittest.TestCase):
    """It is what makes the listing decisive, so it may only be printed when the survey reached
    everything. `INSTALL_PREFIXES` already folds-with-a-line for exactly this reason."""

    def test_an_ordinary_workspace_still_gets_the_clause(self):
        ws, v, token = _surveyed(3, "main.py")
        self.addCleanup(wsview.unbind, token)
        out = groundtruth.workspace_inventory(ws)
        self.assertIn("This list is complete", out)
        self.assertIn("main.py", out)

    def test_a_bounded_survey_says_so_instead(self):
        """A folded subdirectory bounds the survey without emptying it."""
        ws = tempfile.mkdtemp()
        pathlib.Path(ws, "main.py").write_text("print(1)\n")
        deep = pathlib.Path(ws, "vendored")
        deep.mkdir()
        for i in range(wsview.FOLD_AT + 20):
            (deep / f"f{i:04}.py").write_text("x\n")
        v = wsview.View(ws, "t")
        token = wsview.bind(v)
        self.addCleanup(wsview.unbind, token)
        raw = subprocess.run(["bash", "-c", wsview.survey_command("t", cd=ws)], cwd=ws,
                             capture_output=True, text=True).stdout
        wsview.apply_survey(v, wsview.strip_survey(raw)[1])
        out = groundtruth.workspace_inventory(ws)
        self.assertIn("main.py", out)                      # what it did reach is still listed
        self.assertNotIn("This list is complete", out)     # ...and the clause is withheld
        self.assertIn("NOT complete", out)


if __name__ == "__main__":
    unittest.main()
