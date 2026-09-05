"""Elapsed time is a budget, never evidence about completeness or usefulness.

Work ordering and model latency cannot decide whether a run survives long enough to finish.
An independent judgment belongs once, against the final frozen workspace. `--milestone-minutes`
means only N minutes of budget per fixed deliverable.
"""

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))
import run as suite_run  # noqa: E402


class MinutesAreOnlyABudgetTests(unittest.TestCase):
    def test_the_runner_has_no_mid_run_judgment_or_kill(self):
        src = inspect.getsource(suite_run.main)
        self.assertNotIn("ask_gate(", src)
        self.assertNotIn("next_check", src)
        self.assertNotIn("threshold", src)
        self.assertNotIn("behind-", src)

    def test_the_full_budget_is_minutes_times_the_fixed_denominator(self):
        src = inspect.getsource(suite_run.main)
        self.assertIn("wall = milestone_s * deliverable_count(task_dir)", src)

    def test_inferred_judgment_is_frozen_only_after_the_run(self):
        src = inspect.getsource(suite_run.main)
        self.assertEqual(src.count("_freeze_usefulness_evidence(row)"), 1)
        self.assertIn("_freeze_usefulness_evidence(row)", src)

    def test_help_does_not_claim_that_progress_earns_clock(self):
        src = inspect.getsource(suite_run.main)
        self.assertIn("receives the full N × deliverable-count wall", src)
        self.assertNotIn("EARNS more clock", src)
        self.assertNotIn("looked at after", src)


if __name__ == "__main__":
    unittest.main()
