"""Gemma4 and gemma4-qat are one report identity, with live cells over frozen history."""

from suite import battery_status


def _row(task, level, pct):
    return {
        "run_id": f"{task}_gemma4-qat_codex_pon_1790000000",
        "model": "gemma4-qat", "task": task, "level": level,
        "note": f"FRESH-L5 BATTERY2 L{level} gemma4-qat", "usefulness_percent": pct,
        "wall_seconds": 600, "calls": 50,
    }


def test_live_alias_keeps_unreplaced_frozen_cells_and_overrides_only_its_cell():
    rows = [_row("shipping-rates-rb", 0, 17), _row("cart-billing-go", 5, 71)]
    text = battery_status.report(rows, now=2)
    # Exactly one canonical row per level; no separate historical alias row.
    for level in range(6):
        block = text.split(f"### Level {level}", 1)[1].split("### Level ", 1)[0]
        assert sum(line.startswith("| gemma4-qat |") for line in block.splitlines()) == 1
        assert "| gemma4 |" not in block

    level0 = text.split("### Level 0", 1)[1].split("### Level ", 1)[0]
    row0 = next(line for line in level0.splitlines() if line.startswith("| gemma4-qat |"))
    assert "17%" in row0
    # L0 historical cart-billing value remains where no live judgment replaced it.
    assert battery_status._historical()["frozen"]["gemma4"]["0"]["pct"][1] == 92
    assert row0.count("92%") == 1

    level5 = text.split("### Level 5", 1)[1]
    row5 = next(line for line in level5.splitlines() if line.startswith("| gemma4-qat |"))
    assert "71%" in row5


def test_report_alias_does_not_rewrite_live_row_provenance():
    row = _row("shipping-rates-rb", 5, 71)
    rendered = battery_status.report([row], now=2)
    assert row["model"] == "gemma4-qat"
    assert row["run_id"].endswith("gemma4-qat_codex_pon_1790000000")
    assert "| gemma4 |" not in rendered
    assert "| gemma4-qat |" in rendered
