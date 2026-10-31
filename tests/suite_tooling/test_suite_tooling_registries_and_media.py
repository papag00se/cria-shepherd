"""A model the suite can NAME it can RUN (one roster, service and sampling per model), cycles load each model
once, and the best-L5 media export only reports final inferred judgments."""
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "suite"))       # these modules import siblings by bare name
import battery_status  # noqa: E402
import cycle_run  # noqa: E402
import engagement_status  # noqa: E402
import ladder_cycle  # noqa: E402
import run  # noqa: E402
import sampling  # noqa: E402

spec = importlib.util.spec_from_file_location("best_l5", ROOT / "docs/media/best_l5.py")
best = importlib.util.module_from_spec(spec)
spec.loader.exec_module(best)


def test_every_roster_model_has_one_service_and_all_four_role_samplings():
    """Rosters agree, every model has a systemd service key and canonical sampling for coder/reasoner/classifier/
    compactor. gemma4 x26: a missing entry left the previous model's numbers in cria.toml for 26 runs."""
    models = set(battery_status.MODELS)
    assert models == set(engagement_status.MODELS) == set(ladder_cycle.MODELS)
    assert models <= set(run.SERVICES) and models <= set(sampling.MODEL_SAMPLING)
    for model, roles in sampling.MODEL_SAMPLING.items():
        assert set(roles) == {"coder", "reasoner", "classifier", "compactor"}, model
    assert not set(run.SERVICES) - set(sampling.MODEL_SAMPLING)


def test_a_cycle_runs_each_cell_once_and_loads_each_model_once():
    """Model-major order: switches == models-1 (every swap is a window where the endpoint is down)."""
    cells = cycle_run.cells()
    assert len(cells) == len(set(cells)) == len(battery_status.TASKS) * len(battery_status.MODELS)
    order = [m for _t, m in cells]
    assert sum(a != b for a, b in zip(order, order[1:])) == len(battery_status.MODELS) - 1
    chosen = cycle_run.cells(("ornith1.5", "qwen35"))
    assert len(chosen) == 2 * len(battery_status.TASKS)


def ledger(rows, revision):
    return ("\n".join(json.dumps(r) for r in rows).encode(), {"path": "results.jsonl", "revision": revision, "sha256": revision})


def result(run_id, score, model="qwen3.8_9b_distill", **extra):
    return {"run_id": run_id, "model": model, "task": "shipping-rates-rb", "level": 5, "usefulness_percent": score, **extra}


def test_best_l5_uses_final_judgments_not_grades_checkpoints_or_stale_rejudgments():
    """Superseded runs still compete but an older re-judgment of the same run does not; grade-only, wrong-level,
    bool and out-of-range rows are ignored; a legacy `usefulness` field is read; zero is real, missing stays missing."""
    current = ledger([result("rejudged", 40), result("earlier", 88, "defiant-fable", superseded=True),
                      result("grade", None, grade=100, progress_judgments=[{"usefulness_percent": 100}]),
                      result("lvl", 100, level=4), result("bool", True), result("range", 101)], "current")
    older = ledger([result("rejudged", 99, "defiant-fable"), result("legacy", None, usefulness=73)], "older")
    picked = best.collect(["qwen3.8_9b_distill"], best.TASKS, [current, older], [])
    value = picked[("qwen3.8_9b_distill", "shipping-rates-rb")]
    assert value["score"] == 88 and value["source"]["run_id"] == "earlier" and value["source"]["original_model"] == "defiant-fable"
    legacy = best.collect(["qwen3.8_9b_distill"], best.TASKS, [ledger([result("legacy", None, usefulness=73)], "s")], [])
    assert legacy[("qwen3.8_9b_distill", "shipping-rates-rb")]["source"]["score_field"] == "usefulness"
    zero = best.collect(["phi4"], best.TASKS, [ledger([result("z", 0, "phi4")], "s")], [])
    assert zero[("phi4", "shipping-rates-rb")]["score"] == 0 and ("phi4", "cart-billing-go") not in zero
