"""One model is loaded, then taken through every language.

Operator's call, 2026-08-16. This was task-major, and the grid is the argument against that: it is
model-ROWS by language-COLUMNS and the operator reads it by model. Task-major fills columns, so eight
cells into a cycle you have two complete languages and four models each a third measured - no row you
can read. Model-major fills a row at a time.

The swap cost is the smaller half, stated honestly: measured over 21 cells as driver-elapsed minus
the suite's own wall clock, setup is a median of 25s and a mean of 29s per cell - ~11 minutes across
24, or 1.6% of an eleven-hour cycle. Model-major cuts model loads from 24 to 4.

The part not measured in minutes: every swap is a window where the endpoint is down or still loading
and a leftover harness session POSTs into it. Every 503 and every connection-refused in the
campaign's logs sits in one of those windows. Four such windows instead of twenty-four.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SUITE = Path(__file__).resolve().parents[1] / "suite"
sys.path.insert(0, str(SUITE))

import battery_status as bs  # noqa: E402
import cycle_run  # noqa: E402


class ModelMajor(unittest.TestCase):
    def test_every_cell_runs_exactly_once(self):
        cells = cycle_run.cells()
        self.assertEqual(len(cells), len(bs.TASKS) * len(bs.MODELS))
        self.assertEqual(len(set(cells)), len(cells))

    def test_a_model_finishes_every_language_before_the_next_loads(self):
        """FAILS BEFORE: the order was task-major, so the model changed on every single cell."""
        order = [m for _t, m in cycle_run.cells()]
        firsts = [m for i, m in enumerate(order) if i == 0 or order[i - 1] != m]
        self.assertEqual(len(firsts), len(set(firsts)),
                         f"a model is loaded more than once: {order}")

    def test_there_are_exactly_as_many_loads_as_models(self):
        order = [m for _t, m in cycle_run.cells()]
        switches = sum(1 for a, b in zip(order, order[1:]) if a != b)
        self.assertEqual(switches, len(bs.MODELS) - 1)

    def test_selected_models_still_get_complete_rows_in_requested_order(self):
        chosen = ("ornith15", "qwen35")
        cells = cycle_run.cells(chosen)
        self.assertEqual(len(cells), len(chosen) * len(bs.TASKS))
        self.assertEqual([model for _task, model in cells[:len(bs.TASKS)]],
                         [chosen[0]] * len(bs.TASKS))
        self.assertEqual([model for _task, model in cells[len(bs.TASKS):]],
                         [chosen[1]] * len(bs.TASKS))

    def test_each_model_gets_every_task(self):
        seen = {}
        for t, m in cycle_run.cells():
            seen.setdefault(m, []).append(t)
        for m, ts in seen.items():
            with self.subTest(model=m):
                self.assertEqual(sorted(ts), sorted(bs.TASKS))


class TheFreshCellBoundaryStillLinesUp(unittest.TestCase):
    """`battery_status.cycle_start` marks a cell bold when it ran at or after the newest run of the
    matrix's FIRST cell. That only means "this pass" if the driver really does start there."""

    def test_the_driver_starts_on_the_cell_the_grid_keys_on(self):
        self.assertEqual(cycle_run.cells()[0], (bs.TASKS[0], bs.MODELS[0]))


if __name__ == "__main__":
    unittest.main()
