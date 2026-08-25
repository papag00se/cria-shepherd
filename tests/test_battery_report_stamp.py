"""The grid says when it was written AND when its data last moved.

Asked for after an hour of silence during cycle 2's run phase, where the question "is this still
going?" could not be answered from any artefact — the report rewrites itself after every cell, so a
fresh file and a stalled campaign look identical. One timestamp does not answer it: the writer runs
on a schedule the data does not keep. Both do.
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))

import battery_status as bs  # noqa: E402

# A fixed instant, so the assertions are about the format and never about the clock.
WRITTEN_AT = time.mktime(time.strptime("2026-08-15 15:30", "%Y-%m-%d %H:%M"))
STARTED_AT = time.mktime(time.strptime("2026-08-15 14:01", "%Y-%m-%d %H:%M"))


def row(run_id: str, started: float, wall: float = 0.0) -> dict:
    return {"run_id": run_id, "model": "gemma4", "task": "shipping-rates-rb",
            "score": 4.0, "max_score": 5.0, "started": started, "wall_seconds": wall,
            "note": f"{bs.NOTE_PREFIX} CRIA gemma4 deadbee p4", "capture_dir": "/tmp/x"}


class ReportCarriesALastUpdatedStamp(unittest.TestCase):
    def test_stamp_is_the_first_thing_under_the_title(self):
        """Top of the document, before the prose — it is read at a glance or not at all."""
        lines = bs.report([row("r1", STARTED_AT)], now=WRITTEN_AT).splitlines()
        self.assertTrue(lines[0].startswith("# "))
        self.assertEqual("", lines[1])
        self.assertTrue(lines[2].startswith("**Last updated 2026-08-15 15:30**"), lines[2])

    def test_stamp_names_the_newest_row_and_when_it_finished(self):
        """`started + wall_seconds` is when the row was SCORED, which is the moment that matters."""
        rs = [row("older", STARTED_AT - 3600), row("newest", STARTED_AT, wall=600)]
        out = bs._stamp(rs, now=WRITTEN_AT)
        self.assertIn("`newest`", out)
        self.assertIn("scored 2026-08-15 14:11", out)   # 14:01 + 10 minutes
        self.assertNotIn("older", out)

    def test_the_two_times_are_allowed_to_differ(self):
        """THE REGRESSION THIS FILE EXISTS FOR. A long cell leaves an hour between "written" and
        "scored", and that gap is the answer to "is anything happening" — so the stamp must never
        collapse to one number, and must not report the write time as the data time."""
        out = bs._stamp([row("r1", STARTED_AT)], now=WRITTEN_AT)
        self.assertIn("Last updated 2026-08-15 15:30", out)
        self.assertIn("scored 2026-08-15 14:01", out)

    def test_no_rows_says_so_rather_than_inventing_a_time(self):
        """An empty campaign has no data time; claiming one would be a false fact about the world."""
        out = bs._stamp([], now=WRITTEN_AT)
        self.assertIn("Last updated 2026-08-15 15:30", out)
        self.assertIn("no scored rows yet", out)

    def test_a_row_with_no_started_field_cannot_crash_the_report(self):
        """Older rows predate `started`; the grid must still render."""
        rs = [{"run_id": "ancient", "model": "gemma4", "task": "shipping-rates-rb",
               "score": 1.0, "max_score": 5.0, "note": f"{bs.NOTE_PREFIX} CRIA gemma4 x p4",
               "capture_dir": "/tmp/x"}]
        self.assertIn("no scored rows yet", bs._stamp(rs, now=WRITTEN_AT))
        # The report is TABLES ONLY since 2026-08-24 and its H1 named the two-arm campaign;
        # what this test is about is that an old row cannot crash the render, so it
        # asserts the render happened rather than pinning a title.
        self.assertIn("| model | ruby |", bs.report(rs, now=WRITTEN_AT))


if __name__ == "__main__":
    unittest.main()
