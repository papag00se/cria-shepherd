"""The judge's READ-ONLY inspection tools (operator directive: the judge gets real tools).

The toolless critic judged artifact steps from inference — it passed a "write README.md" step on
FEASIBILITY with no README on disk, and its own reasoning showed it REACHING for the missing tool
("no test file exists in the repo yet (list_dir would show this)"), asserting the result of a call
it could not make. These tests pin the executor's contract: read-only, workspace-contained,
never-truncating, every outcome a factual sentence the judge can proceed from."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cria import verifytools, wsview


class VerifyToolExecutorTests(unittest.TestCase):

    def _ws(self):
        d = tempfile.TemporaryDirectory()
        root = Path(d.name)
        (root / "resolve_handle.py").write_text("def resolve():\n    return 1\n")
        (root / "empty.py").write_text("")
        (root / "sub").mkdir()
        (root / "sub" / "notes.md").write_text("line1\nline2\nline3\nline4\n")
        return d, str(root)

    def test_list_dir_shows_entries_with_sizes_and_dir_markers(self):
        d, root = self._ws()
        with d:
            out = verifytools.execute("list_dir", {}, root)
        self.assertIn("resolve_handle.py (28 B)", out)
        self.assertIn("sub/", out)

    def test_read_file_returns_the_whole_file_untruncated(self):
        d, root = self._ws()
        with d:
            out = verifytools.execute("read_file", {"path": "resolve_handle.py"}, root)
        self.assertEqual(out, "def resolve():\n    return 1\n")

    def test_read_file_line_range_is_exact_and_numbered(self):
        d, root = self._ws()
        with d:
            out = verifytools.execute("read_file",
                                      {"path": "sub/notes.md", "start_line": 2, "end_line": 3}, root)
        self.assertEqual(out, "2: line2\n3: line3")

    def test_read_file_on_a_directory_states_the_truth_not_missing(self):
        """Walked on maple 1785956867 call 0054: read_file on an existing __pycache__/ answered
        "does not exist" — a 5b false fact the steer author then built a phantom stale-cache
        theory on. A directory is a directory; say so and point at list_dir."""
        d, root = self._ws()
        with d:
            out = verifytools.execute("read_file", {"path": "sub"}, root)
        self.assertIn("DIRECTORY", out)
        self.assertIn("list_dir", out)
        self.assertNotIn("does not exist", out)

    def test_an_empty_file_is_reported_as_a_fact_not_blank_output(self):
        """A stub deliverable's emptiness must be STATED — blank output reads as a tool failure."""
        d, root = self._ws()
        with d:
            out = verifytools.execute("read_file", {"path": "empty.py"}, root)
        self.assertIn("EMPTY", out)

    def test_reads_outside_the_workspace_are_refused_factually(self):
        d, root = self._ws()
        with d:
            dotdot = verifytools.execute("read_file", {"path": "../../etc/passwd"}, root)
            absolute = verifytools.execute("read_file", {"path": "/etc/passwd"}, root)
        self.assertIn("outside the workspace", dotdot)
        self.assertIn("outside the workspace", absolute)

    def test_a_symlink_cannot_smuggle_a_read_outside(self):
        d, root = self._ws()
        with d:
            (Path(root) / "escape").symlink_to("/etc")
            out = verifytools.execute("read_file", {"path": "escape/passwd"}, root)
        self.assertIn("outside the workspace", out)

    def test_a_remote_workspace_path_is_never_resolved_on_this_machine(self):
        root = "/harness/workspace"
        view = wsview.View(root, "remote")
        token = wsview.bind(view)
        try:
            with mock.patch("cria.verifytools.os.path.realpath",
                            side_effect=AssertionError("local disk touched")):
                self.assertEqual(verifytools._resolve("src/app.any", root),
                                 "/harness/workspace/src/app.any")
                self.assertIsNone(verifytools._resolve("../outside", root))
                self.assertIsNone(verifytools._resolve("/other-machine/file", root))
        finally:
            wsview.unbind(token)

    def test_missing_paths_and_unknown_tools_are_factual_sentences(self):
        d, root = self._ws()
        with d:
            missing = verifytools.execute("read_file", {"path": "nope.py"}, root)
            unknown = verifytools.execute("write_file", {"path": "x", "content": "y"}, root)
        self.assertIn("does not exist", missing)
        self.assertIn("not one of your tools", unknown)   # the coder's tools are not the judge's


if __name__ == "__main__":
    unittest.main()
