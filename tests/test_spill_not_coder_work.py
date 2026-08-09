"""nemotron-nano 1786243834, calls 0069/0074: the unstick reasoner's prompt listed, under
"THE FILES IT HAS BEEN CHANGING (on disk right now…)", exactly one file —
tmp/read-only/api.handle.me_openapi.json — cria's OWN spilled reference copy. The coder had
changed NOTHING. File activity where there was none supported the 'making progress' read, and the
reasoner answered ON_TRACK five times over an untouched workspace.

Spill entries are LABELLED, never removed: "not listed = does not exist" must keep holding.
Scoped to the steer-author path — the critic's "WORKSPACE FILES" header claims no authorship,
so its inventory is untouched.
"""
import unittest

from cria import loop, prompts, webfetch

DISK = ("WORKSPACE FILES in /tmp/ws (on-disk ground truth at judging time, newest first):\n"
        "  tmp/read-only/api.handle.me_openapi.json (96221 B)\n"
        "  resolver.py (2582 B)\n"
        "This list is complete — a file not listed here does not exist in the workspace.")


class SpillEntriesAreLabelledTests(unittest.TestCase):
    def test_the_spill_line_is_labelled_and_kept(self):
        out = loop._label_spill_entries(DISK)
        spill = [l for l in out.splitlines() if "read-only" in l][0]
        self.assertIn("NOT something the coder wrote", spill)
        self.assertIn("96221 B", spill)

    def test_a_real_coder_file_is_untouched(self):
        out = loop._label_spill_entries(DISK)
        self.assertIn("  resolver.py (2582 B)", out.splitlines())

    def test_the_completeness_clause_survives(self):
        self.assertIn("This list is complete", loop._label_spill_entries(DISK))

    def test_empty_stays_empty(self):
        self.assertEqual(loop._label_spill_entries(""), "")

    def test_the_prefix_tracks_the_spill_dir_constant(self):
        """If SPILL_DIR moves, the label must move with it — no second copy of the path."""
        moved = DISK.replace("tmp/read-only/", webfetch.SPILL_DIR.lstrip("./").rstrip("/") + "/")
        self.assertIn("NOT something the coder wrote", loop._label_spill_entries(moved))

    def test_the_steer_author_fallback_is_the_labelled_one(self):
        import inspect
        src = inspect.getsource(loop.author_steer)
        self.assertIn("_label_spill_entries(workspace_inventory(workspace_root))", src)


if __name__ == "__main__":
    unittest.main()
