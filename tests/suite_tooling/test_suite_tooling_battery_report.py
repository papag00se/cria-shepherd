"""Battery scorecard promises: official model/language labels, one shared L5 order, and the writer
(docs/battery-report.md) that publishes the six tables with their Updated line."""
import re

import pytest

from suite import battery_status as status
from suite.report_labels import TASK_LANGUAGES, cell_label

T = status.TASKS


def result(model, level, scores, **extra):
    return [dict(run_id=f"{model}-{level}-{i}", model=model, task=T[i], level=level, usefulness_percent=p,
                 wall_seconds=60, calls=10, **extra) for i, p in enumerate(scores)]


def tables(text):
    return [[l.split("|")[1].strip() for l in s.splitlines() if l.startswith("| ") and not l.startswith(("| model |", "| **average** |"))]
            for s in re.split(r"(?=^## L[0-5] \u2014 )", text, flags=re.M)[1:]]


def test_every_level_shares_the_exact_l5_order_with_identity_tiebreak_and_unscored_last(monkeypatch):
    """Ties are broken by the exact L5 mean (80.5 beats 80), then by name; a model without an L5 score ranks last
    in every table it appears in; the title carries the table average."""
    monkeypatch.setattr(status, "_historical", lambda: {"frozen": {}})
    rs = []
    for model, l5 in (("phi4", [81, 81]), ("k2_horizon_7b", [81, 81]), ("ornith1.5_9b", [80, 81]),
                      ("bonsai2", [80, 80]), ("ling3.0_tiny", [])):
        rs += result(model, 0, [10, 10]) + result(model, 5, l5)
    text = status.report(rs, now=2)
    assert tables(text)[0] == ["k2_horizon_7b", "phi4", "ornith1.5_9b", "bonsai2", "ling3.0_tiny"]
    assert tables(text)[5] == ["k2_horizon_7b", "phi4", "ornith1.5_9b", "bonsai2"]
    assert "## L0 \u2014 " in text and text.count("| model |") == 6


def test_writer_publishes_six_tables_with_an_updated_line_and_the_latest_judged_cell(tmp_path, monkeypatch):
    """The writer replaces the report with the tables built from the rows: title, `Updated:` line, six tables,
    legend; a later unjudged or aborted attempt never hides the cell's latest judgment."""
    monkeypatch.setattr(status, "_historical", lambda: {"frozen": {}})
    monkeypatch.setattr(status, "REPORT_PATH", tmp_path / "battery-report.md")
    rs = result("phi4", 5, [40]) + [dict(run_id="later", model="phi4", task=T[0], level=5, wall_seconds=1),
                                    dict(run_id="bad", model="phi4", task=T[0], level=5, usefulness_percent=99,
                                         aborted="throttled")]
    path = status.write_report(rs, now=0)
    text = path.read_text()
    assert re.match(r"# Battery report\n\nUpdated: \d{4}-\d\d-\d\d \d\d:\d\d \S+\n\n## L0 ", text)
    assert text.endswith(status.LEGEND + "\n") and len(re.findall(r"^## L[0-5] ", text, re.M)) == 6
    assert "| phi4 | \U0001F7E0 40% |" in text and "99%" not in text
    assert [p.name for p in tmp_path.iterdir()] == ["battery-report.md"]


@pytest.mark.parametrize("legacy,official", [
    ("gemma4-qat", "gemma4_12b"), ("gemma4", "gemma4_12b"), ("ornith1.5", "ornith1.5_9b"),
    ("ornith15", "ornith1.5_9b"), ("ling3-tiny", "ling3.0_tiny"), ("defiant-fable", "qwen3.8_9b_distill"),
    ("phi4", "phi4")])
def test_report_uses_official_names_without_rewriting_row_provenance(monkeypatch, legacy, official):
    """Legacy executable keys render as the official model row; the stored row/run_id is untouched."""
    monkeypatch.setattr(status, "_historical", lambda: {"frozen": {}})
    r = {"model": legacy, "task": T[0], "level": 5, "run_id": f"orig_{legacy}_1", "usefulness_percent": 73}
    before = dict(r)
    text = status.report([r], now=2)
    assert f"| {official} |" in text and r == before
    assert legacy == official or f"| {legacy} |" not in text


def test_aliases_share_one_row_and_a_live_judgment_supersedes_only_its_frozen_cell(monkeypatch):
    """gemma4/gemma4-qat/gemma4_12b rows merge (latest judgment wins) over frozen history, cell by cell."""
    monkeypatch.setattr(status, "_historical", lambda: {"frozen": {"gemma4": {"0": {"pct": [10, 20, 30, 40, 50, 60]}}}})
    rows = [{"model": m, "task": T[0], "level": 0, "usefulness_percent": p}
            for m, p in (("gemma4-qat", 71), ("gemma4_12b", 82), ("gemma4", 93))]
    text = status.report(rows, now=2)
    assert text.count("| gemma4_12b |") == 1
    line = next(l for l in text.splitlines() if l.startswith("| gemma4_12b |"))
    cells = [c.strip() for c in line.split("|")[2:8]]
    assert "93%" in cells[0] and [c.split()[-1] for c in cells[1:]] == ["20%", "30%", "40%", "50%", "60%"]


def test_operator_labels_use_official_model_and_scorecard_language_for_every_task():
    """Chat/progress labels and the table header share one language mapping; task ids stay out of labels."""
    assert {t: cell_label("gemma4-qat", t).split(" / ")[1] for t in T} == dict(zip(
        T, ["Ruby", "Go", "Python", "Java", "Node", "Rust"]))
    assert cell_label("gemma4-qat", "cart-billing-go") == "gemma4_12b / Go"
    header = next(l for l in status.report([{"model": "phi4", "task": T[0], "level": 0, "usefulness_percent": 5}],
                                           now=2).splitlines() if l.startswith("| model |"))
    assert header.split("|")[2:8] == [f" {TASK_LANGUAGES[t].lower()} " for t in T]
    with pytest.raises(KeyError):
        cell_label("gemma4_12b", "unknown-task")
