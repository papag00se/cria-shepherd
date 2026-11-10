"""Restored campaign promises: planner stays off, a cell without a result runs (again) and one with a result does
not, and the restored launch never touches the live arm."""
import sys

import pytest

from suite import battery_run, l0_campaign as campaign


@pytest.mark.parametrize("name", ["", "../other", "x/y", "x y"])
def test_campaign_id_cannot_escape_the_state_directory(name):
    """campaign_dir refuses empty, traversal and separator-bearing ids."""
    with pytest.raises(ValueError):
        campaign.campaign_dir(name)


def test_restored_battery_delegates_without_touching_the_live_arm_and_legacy_arms_keep_planner_off(monkeypatch, tmp_path):
    """--restored-fleet launches run.py through the campaign path (no set_level); legacy BASE/CRIA arms pass
    `--planner off` (4a089fe7: selecting full engagement must not opt into planning); cells have no timeout cap."""
    calls = []
    monkeypatch.setattr(battery_run.run_guard, "other_suite_runners", lambda **_: [])
    monkeypatch.setattr(battery_run, "sh", lambda *cmd, **kw: calls.append(cmd) or 0)
    monkeypatch.setattr(battery_run, "set_level", lambda *_: pytest.fail("restored run must not edit the live arm"))
    monkeypatch.setattr(sys, "argv", ["battery_run.py", "--level", "5", "--model", "gemma4_12b", "--task",
                                      campaign.TASKS[0], "--restored-fleet", "--campaign-id", "today"])
    assert battery_run.main() == 0
    assert "--restored-fleet" in calls[0] and calls[0][calls[0].index("--level") + 1] == "5"
    assert "--planner" not in calls[0] or calls[0][calls[0].index("--planner") + 1] == "off"
    assert battery_run.cell_timeout() is None
    monkeypatch.undo()
    for arm in ("BASE", "CRIA"):
        config = tmp_path / f"{arm}.toml"
        config.write_text("[engagement]\nlevel = 5\n")
        calls.clear()
        monkeypatch.setattr(battery_run.run_guard, "other_suite_runners", lambda **_: [])
        monkeypatch.setattr(battery_run, "TOML", config)
        monkeypatch.setattr(battery_run, "sh", lambda *cmd, **kw: calls.append(cmd) or 0)
        monkeypatch.setattr(sys, "argv", ["battery_run.py", "--arm", arm, "--model", "m", "--task", "t"])
        assert battery_run.main() == 0
        cmd = next(c for c in calls if str(battery_run.SUITE / "run.py") in c)
        assert cmd[cmd.index("--planner") + 1] == "off"
        monkeypatch.undo()
