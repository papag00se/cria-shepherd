"""An un-paused model's new campaign must be visible, not shadowed by its own past.

nemotron-elastic's ladder row is FROZEN in suite/historical_ladder.json (recovered inference
judgments orphaned by a field rename). When the model was un-paused for the L5 >75% campaign
(docs/goals/nemotron-l5-75-loop.md), the report generator still rendered the frozen row with
absolute precedence — a fresh comparable run would have been judged, recorded in results.jsonl,
and then silently invisible behind the stale 57% row. Fails before the per-cell merge, passes
after.

The merge is PER CELL in both directions: a live judgment supersedes its frozen cell, and cells
the campaign has not re-judged keep their frozen value — recovered history must never vanish
(the standing guarantee of test_current_model_fleet_is_coherent.py).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "suite"))

import battery_status  # noqa: E402


def _live_row(task: str, pct: int) -> dict:
    return {
        "run_id": f"{task}_nemotron-elastic_codex_pon_1790000000",
        "model": "nemotron-elastic",
        "task": task,
        "level": 5,
        "note": "BATTERY2 L5 nemotron-elastic deadbeef p4",
        "usefulness_percent": pct,
        "wall_seconds": 600,
        "calls": 50,
    }


def test_a_live_judgment_supersedes_its_frozen_cell():
    text = battery_status.report([_live_row("shipping-rates-rb", 90)], now=2)
    l5 = text.split("### Level 5")[1]
    nemo = next(line for line in l5.splitlines() if line.startswith("| nemotron-elastic |"))
    assert "90%" in nemo, f"live 90% shadowed by the frozen row: {nemo}"


def test_unrejudged_cells_keep_their_frozen_values():
    frozen_only = battery_status.report([], now=2)
    with_live = battery_status.report([_live_row("shipping-rates-rb", 90)], now=2)

    def nemo_cells(text: str) -> list[str]:
        l5 = text.split("### Level 5")[1]
        line = next(l for l in l5.splitlines() if l.startswith("| nemotron-elastic |"))
        # | model | 6 task cells | total | avg min | avg calls |
        return [c.strip() for c in line.split("|")[2:8]]

    before, after = nemo_cells(frozen_only), nemo_cells(with_live)
    assert before[1:] == after[1:], "cells without a live judgment must keep their frozen values"
    assert before[0] != after[0], "the re-judged cell must change"
