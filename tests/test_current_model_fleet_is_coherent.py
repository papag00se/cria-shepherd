import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "suite"
sys.path.insert(0, str(SUITE))

import battery_status  # noqa: E402
import engagement_status  # noqa: E402
import ladder_cycle  # noqa: E402
import run  # noqa: E402
import sampling  # noqa: E402


def test_every_current_matrix_model_has_service_and_sampling_configuration():
    models = set(battery_status.MODELS)
    assert models == set(engagement_status.MODELS) == set(ladder_cycle.MODELS)
    assert models <= set(run.SERVICES)
    assert models <= set(sampling.MODEL_SAMPLING)


def test_the_matrix_names_the_current_ornith_release_not_the_retired_names():
    models = set(battery_status.MODELS)
    assert "ornith15" in models
    assert "nemotron-elastic" not in models
    assert "ornith" not in models


def test_retired_models_are_named_not_silently_dropped():
    # 2026-09-27: the report renders only the current roster (plus gemma4's frozen row). A retired
    # model's history stays in results.jsonl / historical_ladder.json and the report NAMES it, so it
    # can never vanish silently — it just no longer occupies a battery row.
    text = battery_status.report([], now=2)
    assert "| nemotron-elastic |" not in text
    assert "| gemma4 |" in text
    retired = [l for l in text.splitlines() if l.startswith("Retired from the battery")]
    assert retired and "nemotron-elastic" in retired[0]
    assert "engagement ladder" in text
    assert "### Level 5" in text


def test_the_battery_roster_is_the_operator_named_fleet():
    assert set(battery_status.MODELS) == {"gemma4-qat", "ternary-bonsai-2", "defiant-fable", "ornith15",
                                          "k2-horizon", "phi4", "ling3-tiny", "qwen38-distill"}
    assert "qwen38" not in run.SERVICES and "qwen38" not in run.EXTERNAL  # the 27B is not cria's


def test_ornith15_uses_the_publishers_distinct_coding_and_general_sampling():
    spec = sampling.render("ornith15")
    assert spec["coder"]["temperature"] == 0.6
    assert spec["coder"]["presence_penalty"] == 0.0
    assert spec["reasoner"]["temperature"] == 1.0
    assert spec["reasoner"]["presence_penalty"] == 1.5
