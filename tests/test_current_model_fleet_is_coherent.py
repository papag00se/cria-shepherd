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


def test_gigachat_replaces_nemotron_and_ornith_names_its_release():
    models = set(battery_status.MODELS)
    assert "gigachat31" in models
    assert "ornith15" in models
    assert "nemotron-elastic" not in models
    assert "ornith" not in models


def test_ornith15_uses_the_publishers_distinct_coding_and_general_sampling():
    spec = sampling.render("ornith15")
    assert spec["coder"]["temperature"] == 0.6
    assert spec["coder"]["presence_penalty"] == 0.0
    assert spec["reasoner"]["temperature"] == 1.0
    assert spec["reasoner"]["presence_penalty"] == 1.5
