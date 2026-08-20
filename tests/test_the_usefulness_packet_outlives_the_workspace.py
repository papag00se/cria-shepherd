"""The inferred score died with the workspace, and the workspace is the part that gets deleted.

The usefulness judge — "was real work done?", the question the campaign is actually asking — grades
an evidence packet built by walking the ARCHIVED workspace and, where the working directory holds no
manifest, re-running the verifier from where the project really is. Once that directory is gone the
packet cannot be built and the run can never be judged; the strict all-or-nothing score is all that
survives it.

Measured when the operator asked why the inferred score was missing: of 503 recorded runs, 455 had
no verdict and only 138 of those still had a workspace on disk. Every BASE row that could still be
judged had already been judged — the other 57 were gone — so the two arms can never be compared on
the number that matters for anything run before this. Nothing in `suite/` deletes an archive, so the
loss came from outside, which is exactly why judgeability must not depend on 3.4 GB of trees
surviving indefinitely. The packets for all 185 surviving workspaces are 816 KB.

So the packet is frozen at the END of a cell, while the workspace is warm, and `evidence()` reads it
back when the archive is gone. The digest is still recomputed against the CURRENT rubric, so a
reworded rubric invalidates old verdicts exactly as before.
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
    return {"run_id": run_id, "task": TASK, "archive": archive, "score": 3.0, "max_score": 5.0,
            "terminal": "milestone-miss-30min", "calls": 44, "wall_seconds": 3685.2,
            "verify": {"review_written": {"ok": True, "detail": "550 words"},
                       "csv_library": {"ok": False, "detail": "did not build"}}}


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

    def test_without_a_packet_a_reaped_workspace_still_reports_the_facts_it_has(self):
        # No packet saved. evidence() must not crash — the row's own verify parts are still real.
        row = _row(str(self.tmp), run_id="r2")
        shutil.rmtree(self.tmp / "workspace")
        text, _ = usefulness.evidence(row)
        self.assertIn("did not build", text)

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

    def test_a_judged_row_leaves_the_worklist(self):
        (self.packets / "done.txt").write_text("frozen")
        (self.verdicts / "done.json").write_text(json.dumps({"usefulness": 80}))
        rows = [{"run_id": "done", "archive": "/nowhere"}]
        self.assertEqual(usefulness.pending(rows), [])


if __name__ == "__main__":
    unittest.main()
