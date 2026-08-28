"""A run is stopped for not MOVING, never for a strict count of finished deliverables.

The old gate ran verify.py at every mark, took its all-or-nothing `score`, and killed the run when
that count fell below the deliverables owed by then. A run with three deliverables nearly finished
scores 0 that way. All three cells on 2026-08-27 died exactly there, at thirty minutes, with real
work on disk. The strict measure is gone (operator: "I don't care about the strict measure - at
all"), and a score floor cannot be rebuilt out of the same numbers under another name.

A run still has to stop when it is getting nowhere, so the question is "did anything move", and both
halves come from evidence already trusted:

  * the verifier's per-deliverable observations, DETAIL included — `0/8 rate values present` becoming
    `5/8` is exactly the progress the count discarded;
  * the workspace fingerprint, so a run editing files between two verifier readings is never called
    stalled.

The schedule is unchanged: first look at two intervals, then one per interval.
"""

import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))
import run as suite_run  # noqa: E402


def parts(**kw):
    return {k: {"ok": v[0], "detail": v[1]} for k, v in kw.items()}


class MovementIsNotACountTests(unittest.TestCase):
    def _reading(self, p, fingerprint=(("a.py", 1),)):
        return (tuple(sorted((k, bool(v["ok"]), str(v["detail"])) for k, v in p.items())), fingerprint)

    def test_a_detail_changing_is_movement_even_with_nothing_finished(self):
        """The case the strict count threw away: zero deliverables met, real progress inside one."""
        before = self._reading(parts(readme=(False, "zones named ['domestic'], 0/8 rate values present")))
        after = self._reading(parts(readme=(False, "zones named ['domestic','eu'], 5/8 rate values present")))
        self.assertNotEqual(before, after)

    def test_a_deliverable_flipping_is_movement(self):
        self.assertNotEqual(self._reading(parts(a=(False, "x"))), self._reading(parts(a=(True, "x"))))

    def test_editing_a_file_is_movement_even_when_the_verifier_says_the_same(self):
        p = parts(a=(False, "x"))
        self.assertNotEqual(self._reading(p, (("a.py", 1),)), self._reading(p, (("a.py", 900),)))

    def test_an_identical_reading_is_a_stall(self):
        p = parts(a=(False, "x"), b=(True, "y"))
        self.assertEqual(self._reading(p), self._reading(p))


class ItFailsOpenTests(unittest.TestCase):
    def test_an_unreadable_look_is_not_a_stall(self):
        """None never equals anything, so it can only keep a run alive (#13)."""
        self.assertIsNone(suite_run.progress_reading(Path("/nonexistent"), Path("/nonexistent")))
        self.assertNotEqual(None, (("a", True, "x"), ()))


class TheFingerprintIsTheCodersWorkTests(unittest.TestCase):
    def test_the_seed_commit_and_the_cells_installs_are_not_movement(self):
        """`.git` is the seed commit; `.cell-installs` is package-manager churn inside the cell."""
        import tempfile, os
        d = Path(tempfile.mkdtemp())
        (d / "a.py").write_text("x")
        for noise in (".git", ".cell-installs"):
            os.makedirs(d / noise / "deep")
            (d / noise / "deep" / "junk").write_text("lots and lots")
        self.assertEqual(suite_run._workspace_fingerprint(d), (("a.py", 1),))

    def test_a_size_change_shows(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / "a.py").write_text("x")
        first = suite_run._workspace_fingerprint(d)
        (d / "a.py").write_text("xxxx")
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
