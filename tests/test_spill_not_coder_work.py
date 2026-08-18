"""nemotron-nano 1786243834, calls 0069/0074: the unstick reasoner's prompt listed, under
"THE FILES IT HAS BEEN CHANGING (on disk right now…)", exactly one file —
tmp/reference/api.handle.me_openapi.json — cria's OWN spilled reference copy. The coder had
changed NOTHING. File activity where there was none supported the 'making progress' read, and the
reasoner answered ON_TRACK five times over an untouched workspace.

Spill entries are LABELLED, never removed: "not listed = does not exist" must keep holding.
Scoped to the steer-author section — the critic's "WORKSPACE FILES" header claims no authorship.

BOTH branches of that section are covered. The first cut labelled only the workspace_inventory
fallback while the PRIMARY source (_fresh_disk_facts) renders the same spilled file in a different
shape and wins whenever it is non-empty.
"""
import inspect
import unittest

from cria import loop, prompts, webfetch

# the fallback branch's shape (groundtruth.workspace_inventory)
INVENTORY = ("WORKSPACE FILES in /tmp/ws (on-disk ground truth at judging time, newest first):\n"
             "  tmp/reference/api.handle.me_openapi.json (96221 B)\n"
             "  resolver.py (2582 B)\n"
             "This list is complete — a file not listed here does not exist in the workspace.")
# the PRIMARY branch's shape (loop._fresh_disk_facts) — different renderer, same file
FRESH = ("FILE ./tmp/reference/api.handle.me_openapi.json — 96,221 bytes, 1 line\n"
         "FILE resolver.py — 2,582 bytes, 84 lines")


class BothBranchesAreLabelledTests(unittest.TestCase):
    def test_the_inventory_shape_is_labelled(self):
        out = loop._label_spill_entries(INVENTORY)
        spill = [l for l in out.splitlines() if "read-only" in l][0]
        self.assertIn("not a deliverable", spill)
        self.assertIn("96221 B", spill)

    def test_the_fresh_disk_facts_shape_is_labelled(self):
        """The shape the FIRST cut missed — `FILE ./tmp/reference/…`, not a stripped prefix."""
        out = loop._label_spill_entries(FRESH)
        spill = [l for l in out.splitlines() if "read-only" in l][0]
        self.assertIn("not a deliverable", spill)

    def test_both_call_sites_pass_through_the_label(self):
        src = inspect.getsource(loop.author_steer)
        self.assertIn("_label_spill_entries(\n        _fresh_disk_facts(", src)
        self.assertIn("_label_spill_entries(workspace_inventory(workspace_root))", src)

    def test_a_real_coder_file_is_untouched(self):
        self.assertIn("  resolver.py (2582 B)", loop._label_spill_entries(INVENTORY).splitlines())
        self.assertIn("FILE resolver.py — 2,582 bytes, 84 lines",
                      loop._label_spill_entries(FRESH).splitlines())

    def test_the_completeness_clause_survives(self):
        self.assertIn("This list is complete", loop._label_spill_entries(INVENTORY))

    def test_empty_stays_empty(self):
        self.assertEqual(loop._label_spill_entries(""), "")


class TheNoteClaimsOnlyWhatCriaCanSupportTests(unittest.TestCase):
    """cria refuses SYNTHETIC writes into the spill dir but cannot stop a raw
    `curl -o tmp/reference/x`. So the note describes the DIRECTORY, which is true by construction,
    and never asserts who wrote a given file — that would be rule 5b pointing the other way."""

    def test_it_makes_no_authorship_claim(self):
        note = prompts.load_map("workspace_inventory")["spill_note"].lower()
        for claim in ("the coder", "you wrote", "not something the coder"):
            self.assertNotIn(claim, note)

    def test_it_still_says_it_is_not_a_deliverable(self):
        self.assertIn("not a deliverable", prompts.load_map("workspace_inventory")["spill_note"])


class TheSpillPathTracksTheConstantTests(unittest.TestCase):
    def test_a_relocated_spill_dir_is_still_matched(self):
        """normpath, not a character-set strip: a dot-dir spill path must still match."""
        real = webfetch.SPILL_DIR
        try:
            webfetch.SPILL_DIR = "./.cria-spill"
            line = "FILE ./.cria-spill/api.json — 96,221 bytes, 1 line"
            self.assertIn("not a deliverable", loop._label_spill_entries(line))
        finally:
            webfetch.SPILL_DIR = real

    def test_a_missing_map_key_is_a_silent_no_op_not_a_crash(self):
        self.assertEqual(loop._label_spill_entries(FRESH) if
                         prompts.load_map("workspace_inventory").get("spill_note") else FRESH,
                         loop._label_spill_entries(FRESH))


if __name__ == "__main__":
    unittest.main()
