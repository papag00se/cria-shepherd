"""The grid's `total` column carries its movement, and computes it on comparable cells.

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
    return {"model": model, "task": task, "score": score, "max_score": max_score,
            "note": f"{bs.NOTE_PREFIX} CRIA {model} deadbee p4", "capture_dir": "/tmp/x"}


class TotalColumnCarriesItsDelta(unittest.TestCase):
    def test_total_shows_movement_in_points(self):
        """Two full runs of one cell: 2/5 then 4/5 is 40% then 80%, so the total reads 80% (+40)."""
        rs = [row("gemma4", "shipping-rates-rb", 2.0),
              row("gemma4", "shipping-rates-rb", 4.0)]
        line = next(l for l in bs._arm_grid(rs, "CRIA") if "gemma4" in l)
        self.assertIn("**80%** (+40)", line)

    def test_no_prior_run_means_no_delta(self):
        """A first-ever run has nothing to move against, and says nothing rather than `(0)`."""
        rs = [row("gemma4", "shipping-rates-rb", 4.0)]
        line = next(l for l in bs._arm_grid(rs, "CRIA") if "gemma4" in l)
        self.assertIn("**80%**", line)
        self.assertNotIn("**80%** (", line)

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
        self.assertIn("**50%** (+80)", line)   # headline over both cells, delta over the pair only

    def test_flat_cell_reads_zero_not_blank(self):
        """A repeated run that did not move says `(0)` — silence would read as "never compared"."""
        rs = [row("gemma4", "cart-billing-go", 5.0), row("gemma4", "cart-billing-go", 5.0)]
        line = next(l for l in bs._arm_grid(rs, "CRIA") if "gemma4" in l)
        self.assertIn("**100%** (0)", line)

    def test_headline_still_weighs_by_checks_not_by_cell(self):
        """The total was checks-passed over checks-attempted before this change and still is: a
        4/4 task and a 0/8 task average to 33%, never to 50%."""
        rs = [row("gemma4", "orders-api-py", 4.0, 4.0), row("gemma4", "rust-toml-cli", 0.0, 8.0)]
        line = next(l for l in bs._arm_grid(rs, "CRIA") if "gemma4" in l)
        self.assertIn("**33%**", line)


if __name__ == "__main__":
    unittest.main()
