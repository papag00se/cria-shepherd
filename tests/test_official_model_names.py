"""Official project identities survive report regeneration and historical aliases."""
from copy import deepcopy

import pytest

from suite import battery_status


@pytest.mark.parametrize("legacy,official", [
    ("gemma4-qat", "gemma4_12b"), ("gemma4", "gemma4_12b"),
    ("ornith1.5", "ornith1.5_9b"), ("ornith15", "ornith1.5_9b"),
    ("ling3-tiny", "ling3.0_tiny"),
    ("bonsai2", "bonsai2"), ("k2_horizon_7b", "k2_horizon_7b"),
    ("phi4", "phi4"), ("qwen3.8_9b_distill", "qwen3.8_9b_distill"),
])
def test_reports_use_official_names_without_rewriting_evidence(monkeypatch, legacy, official):
    monkeypatch.setattr(battery_status, "_historical", lambda: {"frozen": {}})
    row = {"model": legacy, "task": "shipping-rates-rb", "level": 5,
           "run_id": f"original_{legacy}_123", "usefulness_percent": 73}
    before = deepcopy(row)
    text = battery_status.report([row], now=2)
    assert f"| {official} |" in text
    assert row == before
    if legacy != official:
        assert f"| {legacy} |" not in text


def test_aliases_share_one_row_and_latest_judgment_wins(monkeypatch):
    monkeypatch.setattr(battery_status, "_historical", lambda: {
        "frozen": {"gemma4": {"0": {"pct": [10, 20, 30, 40, 50, 60]}}}})
    rows = [
        {"model": "gemma4-qat", "task": "shipping-rates-rb", "level": 0, "usefulness_percent": 71},
        {"model": "gemma4_12b", "task": "shipping-rates-rb", "level": 0, "usefulness_percent": 82},
        {"model": "gemma4", "task": "shipping-rates-rb", "level": 0, "usefulness_percent": 93},
    ]
    text = battery_status.report(rows, now=2)
    assert text.count("| gemma4_12b |") == 1
    rendered = next(line for line in text.splitlines() if line.startswith("| gemma4_12b |"))
    assert "93%" in rendered and "20%" in rendered
    assert "71%" not in rendered and "82%" not in rendered
    assert battery_status.level_cell(rows, 0, "gemma4_12b", "shipping-rates-rb") is rows[-1]


def test_official_frozen_key_and_legacy_live_key_merge(monkeypatch):
    monkeypatch.setattr(battery_status, "_historical", lambda: {
        "frozen": {"ornith1.5_9b": {"4": {"pct": [10, 20, 30, 40, 50, 60]}}}})
    rows = [{"model": "ornith1.5", "task": "shipping-rates-rb", "level": 4,
             "usefulness_percent": 83}]
    text = battery_status.report(rows, now=2)
    assert text.count("| ornith1.5_9b |") == 1
    line = next(line for line in text.splitlines() if line.startswith("| ornith1.5_9b |"))
    assert "83%" in line and "20%" in line
