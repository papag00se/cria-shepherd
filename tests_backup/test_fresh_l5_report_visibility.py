import json

from suite import battery_status


def test_fresh_l5_row_is_in_canonical_level_report_without_becoming_an_arm(tmp_path, monkeypatch):
    fresh = {
        "run_id": "shipping-rates-rb_gemma4-qat_codex_poff_1790805034",
        "task": "shipping-rates-rb", "model": "gemma4-qat", "level": 5,
        "usefulness_percent": 68,
        "note": "FRESH-L5 abc123 BATTERY2 L5 gemma4-qat abc123 p4",
    }
    ordinary_base = {
        "run_id": "shipping-rates-rb_gemma4-qat_codex_poff_1790000000",
        "task": "shipping-rates-rb", "model": "gemma4-qat", "level": 0,
        "usefulness_percent": 20, "note": "BATTERY2 BASE gemma4-qat abc123 p4",
    }
    path = tmp_path / "results.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in (ordinary_base, fresh)) + "\n")
    monkeypatch.setattr(battery_status, "RESULTS", path)

    rows = battery_status.rows()
    assert [row["run_id"] for row in rows] == [ordinary_base["run_id"], fresh["run_id"]]
    assert battery_status.level_cell(rows, 5, "gemma4-qat", "shipping-rates-rb") == fresh
    assert battery_status.cell(rows, "BASE", "gemma4-qat", "shipping-rates-rb") == ordinary_base
    assert battery_status.cell(rows, "CRIA", "gemma4-qat", "shipping-rates-rb") is None

    level_five = battery_status.report(rows, now=2).split("### Level 5", 1)[1]
    assert "| gemma4_12b |" in level_five
    assert "68%" in level_five
