"""Planning is dormant unless explicitly requested; L5 is not consent."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from cria.config import Config, PlannerConfig
from suite import battery_run, run, run_guard


@pytest.mark.parametrize("text", ["", "[planner]\nmax_gather_rounds = 3\n"])
def test_missing_enablement_is_off(tmp_path, text):
    config = tmp_path / "cria.toml"
    config.write_text(text)
    assert not Config.load(config).planner.enabled


def test_constructed_defaults_are_off():
    assert not PlannerConfig().enabled
    assert not Config().planner.enabled


def test_no_configuration_files_is_off(tmp_path):
    with patch("cria.config.HOME_CONFIG", str(tmp_path / "missing-home.toml")), \
            patch("cria.config.CWD_CONFIG", str(tmp_path / "missing-cwd.toml")):
        assert not Config.load().planner.enabled


def test_explicit_config_opt_in_is_preserved(tmp_path):
    config = tmp_path / "cria.toml"
    config.write_text("[planner]\nenabled = true\n")
    assert Config.load(config).planner.enabled


def test_example_does_not_opt_in():
    assert not Config.load(Path(__file__).parents[1] / "cria.example.toml").planner.enabled


@pytest.mark.parametrize("text", ["[tools]\nfocus = true\n", "[planner]\nmax_gather_rounds = 3\n[tools]\nfocus = true\n",
                                  "[planner]\nenabled = true\n[tools]\nfocus = true\n",
                                  "[planner]", "  [planner]\n enabled = true\n  [tools]\nfocus = true\n"])
@pytest.mark.parametrize("opt_in", [False, True])
def test_model_configuration_defaults_off_even_without_planner_key(tmp_path, text, opt_in):
    config = tmp_path / "cria.toml"
    config.write_text(text)
    with patch.object(run, "CRIA_TOML", config), patch.object(run.sampling, "apply", return_value={}), \
            patch.object(run, "sh"), patch.object(run, "wait_health", return_value=True):
        if opt_in:
            run.configure_cria("test-model", planner_enabled=True)
        else:
            run.configure_cria("test-model")
    loaded = Config.load(config)
    assert loaded.planner.enabled is opt_in
    assert loaded.tools.focus  # unrelated settings survive
    if "max_gather_rounds" in text:
        assert loaded.planner.max_gather_rounds == 3


class StopBeforeExecution(Exception):
    pass


@pytest.mark.parametrize("flags,expected", [([], "off"), (["--planner", "off"], "off"),
                                             (["--planner", "on"], "on")])
def test_suite_cli_defaults_off_and_preserves_explicit_opt_in(flags, expected):
    # Observe the real parsed run identity before creating a workspace or swapping a model.
    prefixes = []
    def stop(*, prefix, dir):
        prefixes.append(prefix)
        raise StopBeforeExecution
    argv = ["run.py", "--task", "shipping-rates-rb", "--model", next(iter(run.SERVICES)), *flags]
    # CLI parsing is simulated; the real campaign process census is not this test's subject.
    with patch.object(run_guard, "other_suite_runners", return_value=[]), \
            patch.object(sys, "argv", argv), patch.object(run, "_require_codex_home"), \
            patch.object(run.tempfile, "mkdtemp", side_effect=stop):
        with pytest.raises(StopBeforeExecution):
            run.main()
    assert f"_p{expected}_" in prefixes[0]


@pytest.mark.parametrize("level", range(6))
def test_battery_never_automatically_enables_planning(tmp_path, level):
    config = tmp_path / "cria.toml"
    config.write_text("[engagement]\nlevel = 5\n")
    commands = []
    argv = ["battery_run.py", "--level", str(level), "--model", "test-model",
            "--task", "test-task"]
    with patch.object(run_guard, "other_suite_runners", return_value=[]), \
            patch.object(sys, "argv", argv), patch.object(battery_run, "TOML", config), \
            patch.object(battery_run, "sh", side_effect=lambda *cmd, **kw: commands.append(cmd) or 0):
        assert battery_run.main() == 0
    suite_command = next(c for c in commands if str(battery_run.SUITE / "run.py") in c)
    if "--planner" in suite_command:
        assert suite_command[suite_command.index("--planner") + 1] == "off"


def test_battery_planning_requires_explicit_opt_in(tmp_path):
    config = tmp_path / "cria.toml"
    config.write_text("[engagement]\nlevel = 5\n")
    commands = []
    argv = ["battery_run.py", "--level", "5", "--model", "test-model", "--task", "test-task",
            "--planner", "on"]
    with patch.object(run_guard, "other_suite_runners", return_value=[]), \
            patch.object(sys, "argv", argv), patch.object(battery_run, "TOML", config), \
            patch.object(battery_run, "sh", side_effect=lambda *cmd, **kw: commands.append(cmd) or 0):
        assert battery_run.main() == 0
    suite_command = next(c for c in commands if str(battery_run.SUITE / "run.py") in c)
    assert suite_command[suite_command.index("--planner") + 1] == "on"
