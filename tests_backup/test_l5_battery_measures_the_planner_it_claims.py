"""Regression for 4a089fe7: selecting full engagement must not opt into planning."""
from unittest.mock import patch

import pytest

from suite import battery_run, run_guard


@pytest.mark.parametrize("arm", ["BASE", "CRIA"])
def test_legacy_arm_does_not_enable_the_retired_planner(tmp_path, arm):
    config = tmp_path / "cria.toml"
    config.write_text("[engagement]\nlevel = 5\n")
    commands = []
    # Observe the fake launch's planner argument, not unrelated live machine processes.
    with patch.object(run_guard, "other_suite_runners", return_value=[]), \
            patch("sys.argv", ["battery_run.py", "--arm", arm, "--model", "test-model",
                            "--task", "test-task"]), \
            patch.object(battery_run, "TOML", config), \
            patch.object(battery_run, "sh", side_effect=lambda *cmd, **kw: commands.append(cmd) or 0):
        assert battery_run.main() == 0
    command = next(c for c in commands if str(battery_run.SUITE / "run.py") in c)
    assert command[command.index("--planner") + 1] == "off"
