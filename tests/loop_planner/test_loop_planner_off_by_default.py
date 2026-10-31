"""Planning is OFF everywhere unless explicitly opted in (config, suite CLIs, every level, wiring)."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from cria import assistruntime, config, loop
from cria.config import (Backend, Config, ContextConfig, IndicatorsConfig, LoggingConfig, PlannerConfig,
                         Role, RoutingConfig, ServerConfig, UpstreamConfig)
from cria.events import EventLog
from cria.server import CriaServer
from cria.upstream import Upstream
from suite import battery_run, run, run_guard

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("text", ["", "[planner]\nmax_gather_rounds = 3\n", "[engagement]\nlevel = 5\n"])
def test_a_config_without_enablement_is_off_even_at_level_5(tmp_path, text):
    """Absent `[planner].enabled` means off; L5 is not consent (commit 4a089fe7 conflated the two)."""
    path = tmp_path / "cria.toml"
    path.write_text(text)
    assert not Config.load(path).planner.enabled


def test_constructed_missing_and_shipped_example_configs_are_off(tmp_path):
    """Dataclass defaults, 'no config file anywhere' and cria.example.toml all leave planning off."""
    assert not PlannerConfig().enabled and not Config().planner.enabled
    with patch("cria.config.HOME_CONFIG", str(tmp_path / "no-home.toml")), \
            patch("cria.config.CWD_CONFIG", str(tmp_path / "no-cwd.toml")):
        assert not Config.load().planner.enabled
    assert not Config.load(REPO / "cria.example.toml").planner.enabled


def test_explicit_config_opt_in_is_honoured(tmp_path):
    path = tmp_path / "cria.toml"
    path.write_text("[planner]\nenabled = true\nmax_gather_rounds = 3\n")
    loaded = Config.load(path)
    assert loaded.planner.enabled and loaded.planner.max_gather_rounds == 3


@pytest.mark.parametrize("text", ["[tools]\nfocus = true\n", "[planner]",
                                  "  [planner]\n enabled = true\n  [tools]\nfocus = true\n"])
@pytest.mark.parametrize("opt_in", [False, True])
def test_suite_model_swap_writes_the_planner_setting_it_was_given(tmp_path, text, opt_in):
    """run.configure_cria defaults to off (also overwriting a stale `enabled = true`), on only if asked."""
    path = tmp_path / "cria.toml"
    path.write_text(text)
    with patch.object(run, "CRIA_TOML", path), patch.object(run.sampling, "apply", return_value={}), \
            patch.object(run, "sh"), patch.object(run, "wait_health", return_value=True):
        run.configure_cria("m", planner_enabled=True) if opt_in else run.configure_cria("m")
    loaded = Config.load(path)
    assert loaded.planner.enabled is opt_in and loaded.tools.focus


class _Stop(Exception):
    pass


@pytest.mark.parametrize("flags,expected", [([], "off"), (["--planner", "off"], "off"), (["--planner", "on"], "on")])
def test_suite_run_cli_defaults_to_planner_off(flags, expected):
    """suite/run.py identifies the run with the parsed planner flag; absent flag = off."""
    seen = []

    def stop(*, prefix, dir):
        seen.append(prefix)
        raise _Stop
    argv = ["run.py", "--task", "shipping-rates-rb", "--model", next(iter(run.SERVICES)), *flags]
    with patch.object(run_guard, "other_suite_runners", return_value=[]), patch.object(sys, "argv", argv), \
            patch.object(run, "_require_codex_home"), patch.object(run.tempfile, "mkdtemp", side_effect=stop):
        with pytest.raises(_Stop):
            run.main()
    assert f"_p{expected}_" in seen[0]


def _battery_planner_flag(tmp_path, *args):
    toml = tmp_path / "cria.toml"
    toml.write_text("[engagement]\nlevel = 5\n")
    commands = []
    argv = ["battery_run.py", "--model", "m", "--task", "t", *args]
    with patch.object(run_guard, "other_suite_runners", return_value=[]), patch.object(sys, "argv", argv), \
            patch.object(battery_run, "TOML", toml), \
            patch.object(battery_run, "sh", side_effect=lambda *c, **kw: commands.append(c) or 0):
        assert battery_run.main() == 0
    command = next(c for c in commands if str(battery_run.SUITE / "run.py") in c)
    return command[command.index("--planner") + 1]


@pytest.mark.parametrize("args", [["--level", "0"], ["--level", "3"], ["--level", "5"],
                                  ["--arm", "BASE"], ["--arm", "CRIA"]])
def test_battery_arms_never_enable_the_planner(tmp_path, args):
    """Commit 4a089fe7 regression: it wired `--planner on` at L5 (and the CRIA arm, which is L5) because
    the published L5 capability 'includes' the planner. Every level and legacy arm must pass off."""
    assert _battery_planner_flag(tmp_path, *args) == "off"


def test_battery_planner_needs_the_explicit_flag(tmp_path):
    assert _battery_planner_flag(tmp_path, "--level", "5", "--planner", "on") == "on"


@pytest.mark.parametrize("level", range(6))
def test_assist_runtime_selects_no_planning_stage_without_consent(level):
    """No engagement level, L5 included, selects planner/living-plan/step-review stages on its own."""
    runtime = assistruntime.AssistRuntime.select(level=level)
    assert not runtime.initial_planning.enabled
    assert not runtime.living_plan.enabled and not runtime.step_review.enabled
    consented = assistruntime.AssistRuntime.select(level=5, experimental_planning=True)
    assert consented.initial_planning.enabled and consented.living_plan.enabled


def _server(tmp_path, level, enabled):
    backend = Backend(name="local", transport="http", base_url="http://127.0.0.1:1")
    roles = {n: Role(name=n, backend="local") for n in ("coder", "reasoner")}
    cfg = Config(server=ServerConfig(host="127.0.0.1", port=0), upstream=UpstreamConfig(base_url=backend.base_url),
                 logging=LoggingConfig(dir=str(tmp_path), capture_dir=str(tmp_path), console=False),
                 indicators=IndicatorsConfig(enabled=False), planner=PlannerConfig(enabled=enabled),
                 context=ContextConfig(), routing=RoutingConfig(
                     engagement_level=level, backends={"local": backend}, roles=roles,
                     defaults_base_url=backend.base_url))
    log = EventLog(dir=str(tmp_path), console=False)
    server = CriaServer(cfg, log, Upstream(backend.base_url, engagement_level=level))
    server.server_close()
    log.close()
    return server


@pytest.mark.parametrize("level,enabled,drives_plan", [
    (5, False, False),   # L5 with no opt-in: plan-off
    (4, True, False),    # below L5 the planner is an assist that cannot run, whatever the config says
    (5, True, True)])    # explicit opt-in at L5 is the only way in
def test_server_hands_the_loop_planner_consent_only_with_opt_in_at_level_5(tmp_path, level, enabled, drives_plan):
    server = _server(tmp_path, level, enabled)
    assert server.loop._ctx.planner_enabled is drives_plan
    assert server.pilot_runtime.initial_planning.enabled is drives_plan


def test_a_bare_loop_context_is_planner_off():
    """A LoopContext built without saying anything never plans."""
    assert loop.LoopContext(planner=None, coder_chat=None, reasoner_chat=None).planner_enabled is False
