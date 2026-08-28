"""The grid's `total` column carries its movement, and computes it on comparable cells.

The total is NOT bold. Bold in this grid means "measured in the run currently in progress", and the
total mixes fresh cells with carried-over ones by construction, so emphasis there would claim a
freshness it does not have. See tests/test_battery_grid_marks_fresh_cells.py.

The per-language cells have always shown `(+40)` / `(-60)`; the total showed a bare `78%`, so the
one number the operator reads first was the one number with nothing to read it against. Asked for
during cycle 2's run phase, with the Ruby/Go/Python columns re-run and Java/Node/Rust still holding
last cycle's rows — which is exactly the state that makes the naive version wrong: comparing the
three languages that had run against all six from last time is two different questions subtracted.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))

import battery_status as bs  # noqa: E402


def row(model: str, task: str, score: float, max_score: float = 5.0) -> dict:
    # The cell's number is the JUDGEMENT — the strict all-or-nothing score was removed on
    # 2026-08-27, so a fixture that states only `score` describes a cell the grid now reads as
    # unjudged. These tests are about the DELTA, so they state the quantity the grid states.
    return {"model": model, "task": task, "score": score, "max_score": max_score,
            "usefulness": 100.0 * score / max_score,
            "note": f"{bs.NOTE_PREFIX} CRIA {model} deadbee p4", "capture_dir": "/tmp/x"}


class TotalColumnCarriesItsDelta(unittest.TestCase):
    def test_total_shows_movement_in_points(self):
        """Two full runs of one cell: 2/5 then 4/5 is 40% then 80%, so the total reads 80% (+40)."""
        rs = [row("gemma4", "shipping-rates-rb", 2.0),
              row("gemma4", "shipping-rates-rb", 4.0)]
        line = next(l for l in bs._arm_grid(rs, "CRIA") if "gemma4" in l)
        self.assertIn("80% (+40)", line)

    def test_no_prior_run_means_no_delta(self):
        """A first-ever run has nothing to move against, and says nothing rather than `(0)`."""
        rs = [row("gemma4", "shipping-rates-rb", 4.0)]
        line = next(l for l in bs._arm_grid(rs, "CRIA") if "gemma4" in l)
        self.assertIn("80%", line)
        self.assertNotIn("80% (", line)

    def test_delta_ignores_cells_that_have_not_re_run(self):
        """THE REGRESSION THIS FILE EXISTS FOR.

        Ruby has run twice; Java has only last cycle's row. The headline total weighs both (it is
        "where does this model stand"), but the DELTA may only weigh Ruby — otherwise it silently
        compares {ruby} against {ruby, java} and reports the difference as movement.

        Ruby 1/5 → 5/5 is +80 points on the pair. Java sits at 0/5 with no partner. A delta computed
        over mismatched sets would read (+40): 5/10 attempted now vs 1/10 before.
        """
        rs = [row("qwen35", "shipping-rates-rb", 1.0),
              row("qwen35", "feed-pipeline-java", 0.0),
              row("qwen35", "shipping-rates-rb", 5.0)]
        line = next(l for l in bs._arm_grid(rs, "CRIA") if "qwen35" in l)
        self.assertIn("50% (+80)", line)   # headline over both cells, delta over the pair only

    def test_flat_cell_reads_zero_not_blank(self):
        """A repeated run that did not move says `(0)` — silence would read as "never compared"."""
        rs = [row("gemma4", "cart-billing-go", 5.0), row("gemma4", "cart-billing-go", 5.0)]
        line = next(l for l in bs._arm_grid(rs, "CRIA") if "gemma4" in l)
        self.assertIn("100% (0)", line)

    def test_each_cell_gets_one_vote(self):
        """It used to weigh checks-passed over checks-attempted, so a 4/4 task and a 0/8 task
        averaged to 33% — the task carrying more checks counted for more. That weighting belonged to
        the strict all-or-nothing score, which was removed on 2026-08-27. A judgement is a verdict on
        the WHOLE cell, and a task does not matter more because its verifier happens to be split into
        more pieces. 100 and 0 average to 50."""
        rs = [row("gemma4", "orders-api-py", 4.0, 4.0), row("gemma4", "rust-toml-cli", 0.0, 8.0)]
        line = next(l for l in bs._arm_grid(rs, "CRIA") if "gemma4" in l)
        self.assertIn("50%", line)

    def test_a_part_judged_row_says_how_many_it_speaks_for(self):
        """An average over the judged cells only may not wear the row's name: three unjudged cells
        took nemotron's level-5 total from 46% to 77%, upward, by dropping its three worst."""
        rs = [row("gemma4", "orders-api-py", 4.0, 4.0)]
        rs.append({"model": "gemma4", "task": "rust-toml-cli", "score": 0.0, "max_score": 4.0,
                   "note": f"{bs.NOTE_PREFIX} CRIA gemma4 deadbee p4", "capture_dir": "/tmp/x"})
        line = next(l for l in bs._arm_grid(rs, "CRIA") if "gemma4" in l)
        self.assertIn("(1/2)", line)
        self.assertIn("?", line, "the cell that ran but has no verdict is not `·`")


if __name__ == "__main__":
    unittest.main()
