"""A usefulness evidence packet is frozen while the workspace is still available.

The packet preserves the task, archive location, and file inventory. If the archive is later reaped,
`evidence()` can still return that packet, and rubric changes still invalidate its digest.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))
import usefulness  # noqa: E402


TASK = "feed-pipeline-java"


def _row(archive: str, run_id: str = "r1") -> dict:
    return {"run_id": run_id, "task": TASK, "archive": archive,
            "terminal": "budget-killed", "calls": 44, "wall_seconds": 3685.2}


class ThePacketOutlivesTheWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "workspace" / "src").mkdir(parents=True)
        (self.tmp / "workspace" / "REVIEW.md").write_text("findings, Importer.java:31\n")
        self.packets = self.tmp / "_packets"
        self.p = mock.patch.object(usefulness, "PACKETS", self.packets)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_frozen_packet_is_readable_after_the_workspace_is_deleted(self):
        row = _row(str(self.tmp))
        live, live_digest = usefulness.evidence(row)
        self.assertIsNotNone(usefulness.save_packet(row))

        shutil.rmtree(self.tmp / "workspace")           # the archive is reaped
        after, after_digest = usefulness.evidence(row)

        self.assertEqual(after, live)
        self.assertEqual(after_digest, live_digest)
        self.assertIn("THE TASK THE CODER WAS GIVEN", after)
        self.assertNotIn("TASK METADATA", after)

    def test_without_a_packet_a_reaped_workspace_reports_that_it_is_unavailable(self):
        row = _row(str(self.tmp), run_id="r2")
        shutil.rmtree(self.tmp / "workspace")
        text, _ = usefulness.evidence(row)
        self.assertIn("workspace unavailable", text)

    def test_the_digest_still_tracks_the_rubric_not_just_the_evidence(self):
        row = _row(str(self.tmp))
        usefulness.save_packet(row)
        shutil.rmtree(self.tmp / "workspace")
        before = usefulness.evidence(row)[1]
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("a different rubric entirely\n")
            other = Path(fh.name)
        with mock.patch.object(usefulness, "SYSTEM", other):
            self.assertNotEqual(usefulness.evidence(row)[1], before)
        other.unlink()

    def test_a_legacy_frozen_packet_cannot_restore_task_metadata_as_a_contract(self):
        shutil.rmtree(self.tmp / "workspace")
        self.packets.mkdir()
        (self.packets / "legacy.txt").write_text(
            "THE TASK THE CODER WAS GIVEN:\nBuild it.\n\n"
            "TASK METADATA:\ndeliverables = [\"a private requirement\"]\n\n"
            "WORKSPACE ARCHIVE (inspect it with read-only tools):\n/gone\n\n"
            "EVERY VISIBLE FILE DELIVERED (on disk, with sizes):\n"
            "  answer.txt (3 B)\n  … listing stopped at 400 entries")

        text, _ = usefulness.evidence(_row(str(self.tmp), run_id="legacy"))

        self.assertIn("Build it.", text)
        self.assertIn("answer.txt", text)
        self.assertNotIn("TASK METADATA", text)
        self.assertNotIn("private requirement", text)
        self.assertIn("PARTIAL LEGACY WORKSPACE TREE", text)

    def test_saving_never_raises_on_a_row_it_cannot_read(self):
        # A packet that cannot be written must not fail a run that finished.
        self.assertIsNone(usefulness.save_packet({"run_id": "x", "task": "no-such-task"}))


class TheWorklistOnlyHoldsJudgEABLERowsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.packets = self.tmp / "_packets"
        self.verdicts = self.tmp / "_verdicts"
        self.packets.mkdir(); self.verdicts.mkdir()
        self.ps = [mock.patch.object(usefulness, "PACKETS", self.packets),
                   mock.patch.object(usefulness, "VERDICTS", self.verdicts)]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_row_with_a_packet_is_judgeable_even_with_no_workspace(self):
        (self.packets / "gone.txt").write_text("frozen evidence")
        rows = [{"run_id": "gone", "archive": "/nowhere"}]
        self.assertEqual([r["run_id"] for r in usefulness.pending(rows)], ["gone"])

    def test_a_row_with_neither_is_not_in_the_worklist(self):
        # Unjudgeable for good. Leaving it in the list forever claims work that cannot be done (#5b).
        rows = [{"run_id": "lost", "archive": "/nowhere"}]
        self.assertEqual(usefulness.pending(rows), [])

    def test_a_judged_row_leaves_the_worklist_when_its_digest_still_matches(self):
        (self.packets / "done.txt").write_text("frozen")
        row = {"run_id": "done", "archive": "/nowhere"}
        (self.verdicts / "done.json").write_text(
            json.dumps({"usefulness": 80, "evidence_digest": usefulness.evidence(row)[1]}))
        self.assertEqual(usefulness.pending([row]), [])

    def test_a_verdict_written_against_a_DIFFERENT_rubric_is_reopened(self):
        """The digest covers the rubric, and this is what makes that mean something. `pending` used
        to ask only whether a verdict FILE existed, so rewriting the rubric silently kept every
        stale verdict on its row and the grid went on reporting numbers earned under a scale that no
        longer exists."""
        (self.packets / "done.txt").write_text("frozen")
        row = {"run_id": "done", "archive": "/nowhere"}
        (self.verdicts / "done.json").write_text(
            json.dumps({"usefulness": 80, "evidence_digest": usefulness.evidence(row)[1]}))
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("a different rubric entirely\n")
            other = Path(fh.name)
        with mock.patch.object(usefulness, "SYSTEM", other):
            self.assertEqual([r["run_id"] for r in usefulness.pending([row])], ["done"])
        other.unlink()

    def test_a_verdict_with_no_digest_at_all_is_reopened(self):
        # It predates the stamp, so nothing can vouch for what it was written against.
        (self.packets / "done.txt").write_text("frozen")
        (self.verdicts / "done.json").write_text(json.dumps({"usefulness": 80}))
        rows = [{"run_id": "done", "archive": "/nowhere"}]
        self.assertEqual([r["run_id"] for r in usefulness.pending(rows)], ["done"])


if __name__ == "__main__":
    unittest.main()
