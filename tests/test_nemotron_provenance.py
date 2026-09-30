import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_nemotron_ladder_restores_only_l0_l4_with_original_row_ids_and_scores():
    hist = json.loads((ROOT / "suite/historical_ladder.json").read_text())
    elastic = hist["frozen"]["nemotron-elastic"]
    assert set(elastic) == {"0", "1", "2", "3", "4"}
    assert [elastic[str(i)]["pct"] for i in range(5)] == [
        [0, 0, 0, 0, 0, 0], [0, 6, 0, 0, 0, 0], [0, 6, 45, 0, 0, 18],
        [0, 0, 50, 12, 0, 15], [26, 28, 40, 19, 40, 20],
    ]
    assert [(elastic[str(i)]["min"], elastic[str(i)]["calls"]) for i in range(5)] == [
        (3, 6), (2, 5), (4, 8), (4, 7), (33, 141),
    ]
    assert all(len(elastic[str(i)]["run_ids"]) == 6 for i in range(5))
    from suite import battery_status
    report = battery_status.report([], now=2)
    levels = report.split("### Level 5", 1)[1]
    assert "| nemotron-elastic |" not in levels
    assert "| nemotron-elastic |" in report.split("### Level 4", 1)[1].split("### Level 5", 1)[0]


def test_nemotron_exact_sampling_is_in_the_canonical_table():
    import sys
    sys.path.insert(0, str(ROOT / "suite"))
    import sampling
    spec = sampling.render("nemotron-elastic")
    assert spec["coder"] == {"temperature": 0.6, "top_p": 0.95}
    assert spec["reasoner"] == {"temperature": 0.6, "top_p": 0.95}
    assert spec["classifier"] == {"temperature": 0.0}
    assert spec["compactor"] == {"temperature": 0.0}
