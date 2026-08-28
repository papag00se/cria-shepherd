"""A run is stopped for not WRITING anything, never for a strict count of finished deliverables.

The old gate ran verify.py at every mark, took its all-or-nothing `score`, and killed the run when
that count fell below the deliverables owed by then. A run with three deliverables nearly finished
scores 0 that way. All three cells on 2026-08-27 died exactly there, at thirty minutes, with real
work on disk. The strict measure is gone (operator: "I don't care about the strict measure - at
all"), and a score floor cannot be rebuilt out of the same numbers under another name.

A run still has to stop when it is getting nowhere, and the schedule is unchanged: first look at two
intervals, then one per interval.

THE FIRST VERSION OF THIS COMPARED THE VERIFIER'S DETAIL STRINGS TOO, to catch partial progress the
count discarded — `0/8 rate values present` becoming `5/8`. Checked before trusting it: run the
verifier twice against the same untouched workspace and diff. Ten of ten details are byte-identical
on `shipping-rates-rb` and `cart-billing-go`, and `feed-pipeline-java`'s `substantially_faster` reads
`seed 4.31s vs theirs 0.11s (40.2x)` — wall-clock timings that differ every run. On that task no two
readings could ever match, the gate could never fire, and a stuck run would burn its whole budget.

Normalising digits out would fix the timings and destroy the signal in the same stroke, because
`0/8` → `5/8` is a digit-only change too. So the comparison is the one thing that cannot lie about
whether work is happening: the BYTES of every file the coder could have written.
"""

import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))
import run as suite_run  # noqa: E402


def parts(**kw):
    return {k: {"ok": v[0], "detail": v[1]} for k, v in kw.items()}


class MovementIsNotACountTests(unittest.TestCase):
    def test_a_same_size_edit_is_movement(self):
        """Sized rather than hashed, this edit is invisible and a working run gets stopped."""
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / "a.py").write_text("xxxx")
        first = suite_run.progress_reading(d, None)
        (d / "a.py").write_text("yyyy")
        self.assertNotEqual(first, suite_run.progress_reading(d, None))

    def test_a_new_file_is_movement(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / "a.py").write_text("x")
        first = suite_run.progress_reading(d, None)
        (d / "b.py").write_text("y")
        self.assertNotEqual(first, suite_run.progress_reading(d, None))

    def test_an_untouched_workspace_reads_the_same_twice(self):
        """The whole gate rests on this: no timings, no seeds, nothing that moves on its own."""
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / "a.py").write_text("x")
        self.assertEqual(suite_run.progress_reading(d, None), suite_run.progress_reading(d, None))

    def test_the_verifier_is_not_run_by_the_gate(self):
        """It used to run the task's full verifier every fifteen minutes — up to thirty minutes of
        maven on the java task, inside the run's own budget."""
        import inspect
        self.assertNotIn("observe_snapshot", inspect.getsource(suite_run.progress_reading))


class ItFailsOpenTests(unittest.TestCase):
    def test_an_unreadable_look_is_not_a_stall(self):
        """None never equals anything, so it can only keep a run alive (#13)."""
        self.assertNotEqual(None, (("a.py", "deadbeef"),))


class TheFingerprintIsTheCodersWorkTests(unittest.TestCase):
    def test_the_seed_commit_and_the_cells_installs_are_not_movement(self):
        """`.git` is the seed commit; `.cell-installs` is package-manager churn inside the cell."""
        import tempfile, os
        d = Path(tempfile.mkdtemp())
        (d / "a.py").write_text("x")
        for noise in (".git", ".cell-installs"):
            os.makedirs(d / noise / "deep")
            (d / noise / "deep" / "junk").write_text("lots and lots")
        got = suite_run._workspace_fingerprint(d)
        self.assertEqual([name for name, _ in got], ["a.py"])

    def test_a_content_change_shows(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / "a.py").write_text("x")
        first = suite_run._workspace_fingerprint(d)
        (d / "a.py").write_text("y")
        self.assertNotEqual(first, suite_run._workspace_fingerprint(d))


class TheScheduleIsUnchangedTests(unittest.TestCase):
    def test_first_look_at_two_intervals_then_one_per_interval(self):
        """Operator, 2026-08-27: "The same timing gates we had before. First two in 30 mins, then 15
        per." The first interval holds everything a run does once and is never judged."""
        import inspect
        src = inspect.getsource(suite_run)
        self.assertIn("next_check = milestone_s * 2 if milestone_s else 0", src)
        self.assertIn("next_check += milestone_s", src)

    def test_no_strict_score_decides_anything(self):
        import inspect
        src = inspect.getsource(suite_run)
        self.assertNotIn("score >= due", src)
        self.assertNotIn('"floor"', src)


if __name__ == "__main__":
    unittest.main()
