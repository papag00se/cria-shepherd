import json

import pytest

from suite import fresh_l5_campaign as campaign
from suite.run import validate_fresh_l5_live_level


def candidate(tmp_path, **changes):
    archive = tmp_path / "archive"
    (archive / "workspace").mkdir(parents=True)
    capture = tmp_path / "calls"
    capture.mkdir()
    (capture / "0001-proxy.json").write_text(json.dumps({"messages": [{"role": "user", "content": "x"}]}))
    (capture / "0001-proxy.response.json").write_text(json.dumps({
        "choices": [{"message": {"role": "assistant", "content": "ok"}}]
    }))
    row = {
        "model": campaign.MODELS[0], "task": campaign.TASKS[0], "level": 5,
        "live_engagement_level": 5, "planner": "off", "planner_enabled": False,
        "planner_phase_count": 0, "revision": "rev-a", "note": "FRESH-L5 rev-a",
        "phases": {"proxy": 1}, "calls": 1, "capture_dirs": [str(capture)],
        "archive": str(archive), "workspace_lost": False, "terminal": "exited",
    }
    row.update(changes)
    return row


def test_worklist_is_exact_fresh_54_cell_grid_and_revision_pinned():
    cells = campaign.worklist("abc123", [])
    assert len(cells) == 54
    assert all(c["level"] == 5 and c["planner"] == "off" and c["revision"] == "abc123"
               for c in cells)
    assert {(c["model"], c["task"]) for c in cells} == {
        (model, task) for model in campaign.MODELS for task in campaign.TASKS
    }


def test_worklist_credits_only_preserved_live_l5_candidate_with_valid_capture(tmp_path):
    row = candidate(tmp_path)
    cells = campaign.worklist("rev-a", [row])
    assert len(cells) == 53
    assert (row["model"], row["task"]) not in {(c["model"], c["task"]) for c in cells}


def test_worklist_rejects_requested_but_unobserved_or_invalid_candidates(tmp_path):
    row = candidate(tmp_path)
    rejected = (
        {**row, "level": 0}, {**row, "level": None}, {**row, "level": "5"},
        {**row, "live_engagement_level": 0}, {**row, "live_engagement_level": None},
        {**row, "terminal": "crashed-early"}, {**row, "terminal": None},
        {**row, "aborted": "throttled"}, {**row, "archive": str(tmp_path / "missing")},
        {**row, "workspace_lost": True}, {**row, "capture_dirs": []},
        {**row, "calls": 0}, {**row, "phases": {}},
        {**row, "planner": "on"}, {**row, "planner_enabled": True},
        {**row, "planner_phase_count": 1}, {**row, "revision": "rev-b"},
        {**row, "superseded": True}, {**row, "note": "old historical row"},
    )
    for invalid in rejected:
        assert len(campaign.worklist("rev-a", [invalid])) == 54

    response = next((tmp_path / "calls").glob("*.response.json"))
    response.write_text("not json")
    assert len(campaign.worklist("rev-a", [row])) == 54


def test_requested_level_five_cannot_override_observed_live_level():
    with pytest.raises(RuntimeError, match="live cria engagement level 5, got 0"):
        validate_fresh_l5_live_level(True, 0)
    validate_fresh_l5_live_level(True, 5)
    validate_fresh_l5_live_level(False, 0)


def test_worklist_rejects_unpinned_revision():
    with pytest.raises(ValueError):
        campaign.worklist("")
