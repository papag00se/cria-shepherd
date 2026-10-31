"""Historical maxima are final inferred judgments, not grades or stale re-judgments."""
import importlib.util
import json
from pathlib import Path

import pytest

MEDIA = Path(__file__).resolve().parents[1] / "docs/media"
spec = importlib.util.spec_from_file_location("best_l5", MEDIA / "best_l5.py")
best = importlib.util.module_from_spec(spec)
spec.loader.exec_module(best)


def ledger(rows, revision):
    return ("\n".join(json.dumps(r) for r in rows).encode(),
            {"path": "suite/results/results.jsonl", "revision": revision, "sha256": revision})


def row(run_id, score, model="qwen3.8_9b_distill", task="shipping-rates-rb", **extra):
    return {"run_id": run_id, "model": model, "task": task, "level": 5,
            "usefulness_percent": score, **extra}


def test_superseded_runs_compete_but_old_rejudgments_of_same_run_do_not():
    current = ledger([row("rejudged", 40), row("earlier-run", 88, "defiant-fable", superseded=True)], "current")
    older = ledger([row("rejudged", 99, "defiant-fable"), row("another-run", 70)], "older")
    selected = best.collect(["qwen3.8_9b_distill"], best.TASKS, [current, older], [])
    value = selected[("qwen3.8_9b_distill", "shipping-rates-rb")]
    assert value["score"] == 88
    assert value["source"]["run_id"] == "earlier-run"
    assert value["source"]["original_model"] == "defiant-fable"
    assert value["source"]["superseded_run"] is True


def test_legacy_usefulness_field_is_supported_but_grades_and_checkpoints_are_not():
    records = [row("old-schema", None, usefulness=73),
               row("grade-only", None, grade=100, progress_judgments=[{"usefulness_percent": 100}]),
               row("wrong-level", 100, level=4), row("bool", True), row("outside-range", 101)]
    selected = best.collect(["qwen3.8_9b_distill"], best.TASKS, [ledger(records, "source")], [])
    assert len(selected) == 1
    value = selected[("qwen3.8_9b_distill", "shipping-rates-rb")]
    assert value["score"] == 73
    assert value["source"]["score_field"] == "usefulness"


def test_missing_stays_missing_and_zero_is_a_real_observation():
    selected = best.collect(["phi4"], best.TASKS, [ledger([row("zero", 0, "phi4")], "source")], [])
    assert selected[("phi4", "shipping-rates-rb")]["score"] == 0
    assert ("phi4", "cart-billing-go") not in selected


def test_distinct_versions_are_not_merged_and_purged_models_are_outside_roster():
    records = [row("a", 100, "qwen38"), row("b", 100, "qwen35"),
               row("c", 100, "ternary-bonsai"), row("d", 100, "gigachat31"),
               row("e", 64, "defiant-fable")]
    selected = best.collect(["qwen3.8_9b_distill", "bonsai2"], best.TASKS,
                            [ledger(records, "source")], [])
    assert list(selected) == [("qwen3.8_9b_distill", "shipping-rates-rb")]
    assert selected[("qwen3.8_9b_distill", "shipping-rates-rb")]["score"] == 64


def test_frozen_history_supplies_higher_cells_without_becoming_a_fresh_run():
    frozen = {"tasks": list(best.TASKS), "frozen": {
        "gemma4": {"5": {"pct": [73, 89, 92, 100, 91, 100]}},
        "nemotron-elastic": {"5": {"pct": [59, 31, 76, 20, 70, 84]}}}}
    frozen_source = {"path": "suite/historical_ladder.json", "revision": "old-frozen", "sha256": "frozen"}
    selected = best.collect(["gemma4_12b", "nemotron-elastic"], best.TASKS,
                            [ledger([row("new-gemma", 49, "gemma4-qat")], "working")],
                            [(json.dumps(frozen).encode(), frozen_source)])
    value = selected[("gemma4_12b", "shipping-rates-rb")]
    assert value["score"] == 73
    assert value["source"]["kind"] == "frozen-inference-judgment"
    assert value["source"]["run_id"] is None
    assert value["source"]["revision"] == "old-frozen"
    assert selected[("nemotron-elastic", "rust-toml-cli")]["score"] == 84


def test_temporarily_hiding_phi_preserves_baseline_and_can_be_reversed():
    data = {"model_order": ["phi4", "ornith1.5_9b", "bonsai2"], "excluded_models": ["phi4"],
            "levels": {"0": {"overall": 40, "rows": [
                {"model": "phi4", "cells": [0] * 6}, {"model": "bonsai2", "cells": [80] * 6}]}}}
    original = json.loads(json.dumps(data["levels"]["0"]))
    assert best.apply_display_scope(data) == ["ornith1.5_9b", "bonsai2"]
    assert data["standing_l0"] == original
    assert data["levels"]["0"]["overall"] == 80
    assert data["levels"]["0"]["rows"] == [{"model": "bonsai2", "cells": [80] * 6}]
    # Missing Ornith cells were not guessed or replaced by zeros.
    assert not any(r["model"].startswith("ornith") for r in data["levels"]["0"]["rows"])
    data["excluded_models"] = []
    assert best.apply_display_scope(data) == ["phi4", "ornith1.5_9b", "bonsai2"]
    assert data["levels"]["0"]["rows"] == original["rows"]
    assert data["levels"]["0"]["overall"] == 40


def test_unknown_roster_exclusion_is_not_silently_accepted():
    data = {"model_order": ["bonsai2"], "excluded_models": ["not-a-roster-model"], "levels": {}}
    with pytest.raises(ValueError, match="outside the retained README roster"):
        best.apply_display_scope(data)
