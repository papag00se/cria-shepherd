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


@pytest.mark.parametrize("level", [0, 5])
def test_a_cell_without_a_result_runs_and_one_with_a_result_does_not(level):
    """All 48 cells start pending; only a row of this campaign and level that is a real result counts (a judged one is
    done, an unjudged one awaits its judgment); aborted, harness-error, lost-workspace, other-campaign and other-level
    rows leave the cell pending. The launch command carries the level and no --planner flag (launcher default is off;
    4a089fe7 had enabled planning at L5)."""
    model, task = campaign.MODELS[0], campaign.TASKS[0]
    state = lambda rows: {(m, t): s for m, t, s in campaign.cells("new", level, rows)}[(model, task)]
    row = {"campaign_id": "new", "level": level, "model": model, "task": task}
    assert len(campaign.cells("new", level, [])) == 48 and state([]) == "pending"
    for change in ({"aborted": "throttled"}, {"terminal": "harness-error"}, {"workspace_lost": True},
                   {"campaign_id": "old"}, {"level": (level + 1) % 6}):
        assert state([{**row, **change, "usefulness_percent": 100}]) == "pending", change
    assert state([row]) == "awaiting-usefulness"
    assert state([{**row, "usefulness_percent": 0}]) == "done"
    cmd = campaign.cell_command("new", level, model, task)
    assert cmd[cmd.index("--level") + 1] == str(level) and "--restored-fleet" in cmd and "--planner" not in cmd


def test_lane_scheduler_tries_another_model_after_a_side_server_does_not_fit(monkeypatch):
    from suite import lane_driver, lanes
    driver = lane_driver.Driver([], ['3090x4', '3090x4b', '3080x2'], list(campaign.MODELS), list(campaign.TASKS), None)
    driver.servers['3090x4'] = {'slots': 4}
    driver.lane_model = {'3090x4': 'ornith1.5_9b', '3080x2': 'bonsai2'}
    driver.second_wait[driver.side_retry_key('3090x4b', 'bonsai2')] = 999999
    monkeypatch.setattr(lane_driver.time, 'time', lambda: 1)
    pending = [(None, 'bonsai2', campaign.TASKS[0]), (None, 'phi4', campaign.TASKS[0])]
    assert driver.next_model('3090x4b', pending) == 'phi4'
    driver.lane_model['3090x4'] = 'ling3.0_tiny'
    assert driver.next_model('3090x4b', pending) == 'bonsai2'  # different card occupancy can fit
    driver.servers['3090x4b'] = {'slots': 1}
    assert driver.card_free('3090x4b') == lanes.LANES['3090x4'].slots


def test_lane_scheduler_step_launches_an_alternative_after_a_fit_failure(monkeypatch):
    from suite import lane_driver
    driver = lane_driver.Driver([], ['3090x4', '3090x4b', '3080x2'], list(campaign.MODELS), list(campaign.TASKS), None)
    driver.servers = {'3090x4': {'slots': 4}, '3080x2': {'slots': 1}}
    driver.lane_model = {'3090x4': 'ornith1.5_9b', '3080x2': 'bonsai2'}
    driver.running = {'ornith': {'lane': '3090x4'}, 'bonsai': {'lane': '3080x2'}}
    from types import SimpleNamespace
    cell = SimpleNamespace(level=5)
    pending = [(cell, 'bonsai2', campaign.TASKS[0]), (cell, 'phi4', campaign.TASKS[0])]
    monkeypatch.setattr(driver, 'queue', lambda model=None: [p for p in pending if model is None or p[1] == model])
    monkeypatch.setattr(driver, 'fits', lambda *_: True)
    monkeypatch.setattr(driver, 'reap', lambda: None)
    monkeypatch.setattr(driver, 'stop_rows', lambda **_: None)
    monkeypatch.setattr(lane_driver.lanes, 'check_server', lambda _: None)
    attempted, launched = [], []
    def switch(lane, model):
        attempted.append(model)
        if model == 'bonsai2':
            raise RuntimeError('does not fit')
        driver.servers[lane] = {'slots': 4}
        driver.lane_model[lane] = model
    def launch(lane, cell, model, task):
        launched.append((lane, model, task))
        pending.remove((cell, model, task))
        driver.running[model] = {'lane': lane}
    monkeypatch.setattr(driver, 'switch_lane', switch)
    monkeypatch.setattr(driver, 'launch', launch)
    driver.step()
    assert attempted == ['bonsai2'] and not launched
    driver.step()
    assert attempted == ['bonsai2', 'phi4']
    assert launched == [('3090x4b', 'phi4', campaign.TASKS[0])]


def test_restored_battery_forwards_an_explicit_rust_toolchain(monkeypatch):
    calls = []
    monkeypatch.setattr(battery_run.run_guard, "other_suite_runners", lambda **_: [])
    monkeypatch.setattr(battery_run, "sh", lambda *cmd, **kw: calls.append(cmd) or 0)
    monkeypatch.setattr(sys, "argv", ["battery_run.py", "--level", "5", "--model", campaign.MODELS[0],
                                      "--task", campaign.TASKS[-1], "--restored-fleet", "--rust-toolchain", "1.99.1"])
    assert battery_run.main() == 0
    cmd = calls[0]
    assert cmd[cmd.index("--rust-toolchain") + 1] == "1.99.1"


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
