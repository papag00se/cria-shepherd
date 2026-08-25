"""Bold marks a cell measured in the run currently in progress.

A cycle takes hours and the grid is read throughout it, so at any moment some cells come from the run
in flight and the rest are carried from the previous pass. Without the distinction a stale cell and a
re-measured one look identical, and the report gets read as if the whole grid had moved - which
during cycle 3 meant a Ruby column re-measured that morning sitting beside a Java column from the day
before, both in plain text.

The boundary is the newest run of the FIRST cell of the matrix. cycle_run.py walks it task-major from
the top, so that run is the moment the pass began; a restart re-runs it and the boundary moves with
it, which is what you want - after a restart the earlier cells of the abandoned pass are stale again.

The TOTAL is never bold: it mixes fresh and carried cells by construction.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))

import battery_status as bs  # noqa: E402

T0, T1 = bs.TASKS[0], bs.TASKS[1]
M0 = bs.MODELS[0]


def row(model, task, score, started, max_score=5.0):
    return {"run_id": f"{task}_{model}_{started:.0f}", "model": model, "task": task,
            "score": score, "max_score": max_score, "started": started,
            "note": f"{bs.NOTE_PREFIX} CRIA {model} deadbee p4", "capture_dir": "/tmp/x"}


class BoldMeansMeasuredThisRun(unittest.TestCase):
    def _grid(self, rs):
        return [l for l in bs._arm_grid(rs, "CRIA") if M0 in l]

    def test_a_cell_from_this_run_is_bold(self):
        """FAILS BEFORE: nothing in the grid distinguished fresh from carried."""
        rs = [row(M0, T0, 4.0, 1000)]          # the first cell IS the boundary
        # `ˢ` marks a cell still scored strictly; this test is about BOLD, which means FRESH.
        self.assertIn("**80%ˢ**", self._grid(rs)[0])

    def test_a_cell_carried_from_the_previous_pass_is_not(self):
        rs = [row(M0, T1, 5.0, 500),           # ran before this pass began
              row(M0, T0, 4.0, 1000)]          # this pass's first cell
        line = self._grid(rs)[0]
        self.assertIn("**80%ˢ**", line)        # the fresh one
        self.assertIn("| 100%ˢ |", line)        # the carried one, plain

    def test_the_total_is_never_bold(self):
        """It mixes fresh and carried cells, so emphasis would claim a freshness it does not have."""
        rs = [row(M0, T1, 5.0, 500), row(M0, T0, 4.0, 1000)]
        line = self._grid(rs)[0]
        total = line.rsplit("|", 5)[1].strip()   # the total column
        self.assertNotIn("**", total)

    def test_a_restart_moves_the_boundary(self):
        """The abandoned pass's cells become stale again - which is the honest reading."""
        rs = [row(M0, T0, 1.0, 1000),          # first pass starts
              row(M0, T1, 5.0, 1100),          # ... and gets one more cell in
              row(M0, T0, 4.0, 2000)]          # restart: the boundary is now 2000
        line = self._grid(rs)[0]
        self.assertIn("**80%", line)           # the re-run first cell is fresh
        self.assertIn("| 100%ˢ |", line)        # the 1100 cell is behind the new boundary

    def test_nothing_is_marked_when_the_first_cell_has_never_run(self):
        """Fail toward marking NOTHING fresh rather than everything."""
        rs = [row(M0, T1, 5.0, 500)]
        self.assertEqual(0.0, bs.cycle_start(rs, "CRIA"))
        self.assertNotIn("**", self._grid(rs)[0].split("|")[2])

    def test_the_meaning_of_bold_is_written_down_where_the_prose_lives(self):
        """battery-report.md is TABLES ONLY since 2026-08-24 (operator: "I look at nothing else"),
        so the legend moved to battery-history.md. The claim still has to be checkable — a marker
        whose meaning is written nowhere is the defect this test was created for."""
        hist = Path(__file__).resolve().parents[1] / "docs" / "audits" / "battery-history.md"
        self.assertTrue(hist.is_file(), "battery-history.md is where the prose went")
        self.assertIn("Bold marks a cell measured in the run currently in progress",
                      hist.read_text())


if __name__ == "__main__":
    unittest.main()
