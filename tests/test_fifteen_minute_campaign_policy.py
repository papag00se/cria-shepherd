"""Operator policy: one review stream, a protected first half-hour, inferred continuation."""
import json
from suite import milestones, battery_status
from suite.run import MilestonePacing, milestone_terminal, milestone_progress


def verdict(decision="continue", score=20):
    return {"decision": decision, "usefulness_percent": score,
            "reason": "Inspected reusable implementation", "evidence": ["src/main.py"],
            "material_changes": "The parser now handles nested input; integration is unchanged."}


def test_reviews_start_at_fifteen_and_include_every_interval():
    clock = MilestonePacing(started_at=100, interval_minutes=15, budget_intervals=2)
    for minute in (15, 30, 45, 60):
        assert clock.next_milestone == minute * 60
        assert not clock.due(100 + minute * 60 - 1)
        assert clock.due(100 + minute * 60)
        clock.advance()


def test_fifteen_minute_judge_cannot_end_the_protected_half_hour():
    # Completion is the running gate/model's responsibility, not the observer's at minute 15.
    for decision in ("continue", "stalled", "complete"):
        assert milestone_terminal(verdict(decision), 15, False) is None


def test_continuation_is_the_judgment_not_a_score_or_legacy_budget():
    assert milestone_terminal(verdict("continue", 0), 30, True) is None
    assert milestone_terminal(verdict("continue", 0), 75, True) is None
    assert milestone_terminal(verdict("stalled", 99), 30, False) == "milestone-stalled-30min"


def test_material_changes_are_required_and_reported():
    value = verdict()
    assert milestones.parse(json.dumps(value)) == value
    for missing in (None, "", " ", []):
        assert milestones.parse(json.dumps({**value, "material_changes": missing})) is None
    report = milestone_progress(value, 15)
    assert "20%" in report and value["material_changes"] in report
    assert "protected" in report


def test_moved_report_is_the_only_generated_report(tmp_path, monkeypatch):
    (tmp_path / "suite").mkdir()
    monkeypatch.setattr(battery_status, "SUITE", tmp_path / "suite")
    from pathlib import Path
    (tmp_path / 'docs').mkdir()
    standing = battery_status.add_throughput_column(Path('docs/battery-report.md').read_text(), [])[0]
    (tmp_path / 'docs/battery-report.md').write_text(standing)
    out = battery_status.write_report([], campaign=dict(campaign_id='new', level=0,
                                                        models=[], cells=[]))
    assert out == tmp_path / "docs" / "battery-report.md"
    assert not (tmp_path / "docs" / "audits" / "battery-report.md").exists()
    assert out.read_text() == standing
