import json

from suite import fresh_l5_campaign as campaign


def test_worklist_is_exact_fresh_54_cell_grid_and_revision_pinned():
    cells = campaign.worklist("abc123", [])
    assert len(cells) == 54
    assert all(c["level"] == 5 and c["planner"] == "off" and c["revision"] == "abc123"
               for c in cells)
    assert {(c["model"], c["task"]) for c in cells} == {
        (model, task) for model in campaign.MODELS for task in campaign.TASKS
    }


def test_worklist_resumes_only_its_own_planner_off_fixed_revision_rows():
    prior = [{"model": campaign.MODELS[0], "task": campaign.TASKS[0], "level": 5,
              "planner": "off", "planner_enabled": False, "planner_phase_count": 0,
              "revision": "rev-a", "note": "FRESH-L5 rev-a", "phases": {}}]
    cells = campaign.worklist("rev-a", prior)
    assert len(cells) == 53
    assert (campaign.MODELS[0], campaign.TASKS[0]) not in {
        (c["model"], c["task"]) for c in cells
    }
    for changed in (
        {**prior[0], "planner": "on"}, {**prior[0], "revision": "rev-b"},
        {**prior[0], "superseded": True}, {**prior[0], "note": "old historical row"},
        {**prior[0], "phases": {"planner": 1}}, {**prior[0], "phases": None},
        {**prior[0], "planner_enabled": True}, {**prior[0], "planner_phase_count": 1},
    ):
        assert len(campaign.worklist("rev-a", [changed])) == 54


def test_worklist_rejects_unpinned_revision():
    import pytest
    with pytest.raises(ValueError):
        campaign.worklist("")
