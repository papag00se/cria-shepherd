"""Config loading: sane defaults, loud rejection of removed/unknown keys, role/backend semantics."""
import copy
from pathlib import Path
from unittest.mock import patch

import pytest

from cria import config as cfgmod
from cria.config import Config, Role, _deep_merge
from cria.events import EventLog
from cria.server import CriaServer
from cria.upstream import Upstream

LOCAL = '[backends.local]\ntransport = "http"\nbase_url = "http://127.0.0.1:18084"\n'
ROLE = LOCAL + '[roles.coder]\nbackend = "local"\n'
EXAMPLE = Path(__file__).parents[2] / "cria.example.toml"


def load(tmp_path, text):
    p = tmp_path / "cria.toml"
    p.write_text(text)
    return Config.load(p)


def test_defaults_are_sane_planner_off_and_env_file_confined_to_the_cria_dir(tmp_path):
    """Planner is OFF however config is absent/partial/example (commit 4a089fe7 once re-enabled it at L5); env_file is never set to an arbitrary path."""
    with patch.object(cfgmod, "HOME_CONFIG", str(tmp_path / "none-h.toml")), patch.object(cfgmod, "CWD_CONFIG", str(tmp_path / "none-c.toml")):
        nothing = Config.load()
    for cfg in (Config(), nothing, load(tmp_path, "[planner]\nmax_gather_rounds = 3\n"), Config.load(EXAMPLE)):
        assert not cfg.planner.enabled and cfg.system1.enabled is False
        assert cfg.env_file in (None, "~/.cria/.env")
    assert (Config().server.port, Config().upstream.base_url) == (18085, "http://127.0.0.1:18084")
    assert load(tmp_path, "[planner]\nenabled = true\n").planner.enabled  # explicit opt-in survives


def test_toml_layers_merge_cwd_over_home_and_defaults_normalize(tmp_path):
    """CWD wins overlapping keys, nested tables merge, inputs are not mutated, and [defaults] feeds upstream/routing."""
    home = {"server": {"port": 18085, "host": "0.0.0.0"}, "planner": {"enabled": True}}
    merged = _deep_merge(home, {"server": {"port": 9000}, "planner": {"max_gather_rounds": 5}})
    assert merged == {"server": {"port": 9000, "host": "0.0.0.0"}, "planner": {"enabled": True, "max_gather_rounds": 5}}
    assert home["server"]["port"] == 18085
    cfg = load(tmp_path, '[defaults]\nbase_url = "http://h:1/"\ntimeout_seconds = 42\ncontext_window = 49152\n'
                         '[logging]\nlevel = "debug"\n[future]\nx = 1\n')  # an unknown future table is tolerated
    assert (cfg.upstream.base_url, cfg.upstream.timeout_seconds, cfg.upstream.context_window) == ("http://h:1", 42, 49152)
    assert cfg.routing.defaults_base_url == "http://h:1" and cfg.logging.level == "debug"
    with pytest.raises(FileNotFoundError):
        Config.load(tmp_path / "absent.toml")


@pytest.mark.parametrize("text,why", [
    ('[context]\ntrigger_compaction = 90\n', "trigger_compaction was removed"),
    (LOCAL + '[roles.coder]\nbackend = "local"\nmodel = "fabliq"\n', "not the role"),
    ('[roles]\nreasoner = "some_alias"\n', "write it as a table"),
    ('[logging]\nlevel = "loud"\n', "level must be"),
    ('[assists]\nunknown = 1\n', "supports only profile and disabled"),
    ('[assists]\ndisabled = ["no-such-assist"]\n', "no-such-assist"),
    ('[system1]\nenabled = true\nbundle_dir = "/b"\nunknown = 1\n', "system1"),
    ('[system1]\nenabled = true\n', "bundle_dir is required"),
    ('[system1]\nthreads = 0\n', "threads must be"),
    ('[roles.coder]\nbackend = "nope"\n', "no matching"),
    ('[backends.g]\ntransport = "http"\napi_key_env = "K"\n[roles.coder]\nbackend = "g"\n', "needs a base_url"),
    ('[backends.cx]\ntransport = "cli"\ntool = "codex"\n[roles.r]\nbackend = "cx"\n', "codex exec"),
    (ROLE + '[failover]\ncoding = ["ghost"]\n', "no \\[roles.ghost\\]"),
    (ROLE + 'vision = "true"\n', "vision"),
    (ROLE + 'vision = true\n', "vision_model"),
])
def test_removed_unknown_and_malformed_keys_fail_loudly_at_load(tmp_path, text, why):
    """Zero aliases: a removed key, a wrong type or a dangling reference stops startup with a pointed message instead of being ignored."""
    with pytest.raises(ValueError, match=why):
        load(tmp_path, text)


def test_backends_and_roles_resolve_their_wire_conventions(tmp_path):
    """A role inherits its backend's reasoning convention: served -> chat_template, keyed host -> openai/openrouter, cli -> none, explicit style wins."""
    cfg = load(tmp_path, LOCAL + '''
[backends.groq]
transport = "http"
base_url = "https://api.groq.com/openai/v1"
api_key_env = "GK"
model = "llama-70b"
[backends.or]
transport = "http"
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OK"
[backends.odd]
transport = "http"
base_url = "https://odd/v1"
api_key_env = "K"
reasoning_style = "openrouter"
[backends.claude]
transport = "cli"
tool = "claude"
[roles.a]
backend = "local"
temperature = 0.1
max_tokens = 4096
[roles.b]
backend = "groq"
temp = 0.3
reasoning = "OFF"
[roles.c]
backend = "or"
[roles.d]
backend = "odd"
[roles.e]
backend = "claude"
[failover]
coding = ["a", "b"]
''')
    r = cfg.routing
    assert {k: v.think_protocol for k, v in r.roles.items()} == {
        "a": "chat_template", "b": "openai", "c": "openrouter", "d": "openrouter", "e": "none"}
    assert (r.roles["a"].temperature, r.roles["a"].max_tokens, r.roles["b"].temperature) == (0.1, 4096, 0.3)
    assert r.roles["b"].reasoning == "off" and r.failover["coding"] == ("a", "b")
    assert [r.backends[n].keyed for n in ("local", "groq", "claude")] == [False, True, True]  # cli needs its binary
    assert r.backends["local"].model is None and r.backends["groq"].model == "llama-70b"


def body(**kw):
    return {"model": "m", "messages": [{"role": "system", "content": "You are X."}, {"role": "user", "content": "hi"}], **kw}


def test_role_apply_attaches_sampling_reasoning_and_the_output_reserve_hint():
    """Role.apply writes sampling, thinking flag + a no-think directive merged into the one system message, and output_reserve as a cria-internal hint (never max_tokens)."""
    b = body()
    Role("coder", "local", reasoning="off", temperature=0.2, repeat_penalty=1.1, output_reserve=8192).apply(b)
    assert (b["temperature"], b["repeat_penalty"], b["cria_output_reserve"]) == (0.2, 1.1, 8192)
    assert b["chat_template_kwargs"] == {"enable_thinking": False} and "max_tokens" not in b
    assert "Do not think out loud" in b["messages"][0]["content"]
    assert [m["role"] for m in b["messages"]].count("system") == 1
    on = body()
    Role("coder", "local", reasoning="on").apply(on)
    assert on["chat_template_kwargs"] == {"enable_thinking": True} and on["messages"] == body()["messages"]
    assert Role("c", "local", reasoning="off").clean_content("hmm 3x17.</think>\n\nNo, 51 is not prime.") == "No, 51 is not prime."


@pytest.mark.parametrize("cap,internal,budget,expected", [
    (4096, True, 8192, 8192),    # an operator cap must not starve a MEASURED internal budget (2000 gave zero content)
    (8192, True, 2000, 8192),    # ...but a cap above it still applies
    (4096, False, 32000, 4096),  # a harness pass-through is exactly what the cap is for
])
def test_a_role_cap_is_a_floor_for_cria_built_bodies_only(cap, internal, budget, expected):
    """One `max_tokens` line once silently overwrote every internal budget (classifier, critics, summarize): empty answers read as 'nothing to report'."""
    b, events = {"max_tokens": budget, "messages": []}, []
    rlog = type("L", (), {"emit": lambda self, kind, **kw: events.append((kind, kw))})()
    Role("reasoner", "local", max_tokens=cap).apply(b, internal=internal, rlog=rlog)
    assert b["max_tokens"] == expected
    assert [k for k, _ in events] == (["role.cap_below_measured_floor"] if cap < budget and internal else [])


@pytest.mark.parametrize("role_kw,harness,expected", [
    ({"reasoning": "on"}, {"reasoning_effort": "none"}, {"chat_template_kwargs": {"enable_thinking": True}}),
    ({"reasoning": "off"}, {"reasoning_effort": "high"}, {"chat_template_kwargs": {"enable_thinking": False}}),
    ({"reasoning": "off", "think_protocol": "openai"}, {"chat_template_kwargs": {"enable_thinking": True}},
     {"reasoning_effort": "none"}),
    ({"reasoning": None}, {"reasoning_effort": "none"}, {"reasoning_effort": "none"}),  # no setting: untouched
])
def test_a_roles_reasoning_setting_beats_an_inherited_harness_control(role_kw, harness, expected):
    """phi4 A2 coder call 0011: Codex's reasoning_effort 'none' beat the configured enable_thinking true because llama.cpp reads it last."""
    b = body(**copy.deepcopy(harness))
    Role("coder", "local", **role_kw).apply(b)
    assert {k: b[k] for k in ("reasoning_effort", "chat_template_kwargs") if k in b} == expected


def test_a_configured_context_window_pins_every_upstream_the_server_builds(tmp_path):
    """The `context_window` TOML key reaches the router-built Upstream as authoritative (a dropped argument once committed an 8,192 fallback and destroyed 934 messages)."""
    cfg = load(tmp_path, '[defaults]\ncontext_window = 49152\n[logging]\nconsole = false\n' + f'dir = "{tmp_path}"\n'
               '[server]\nport = 0\n[backends.other]\ntransport = "http"\nbase_url = "http://otherhost:1"\n'
               '[roles.reasoner]\nbackend = "other"\n')
    log = EventLog(dir=str(tmp_path), console=False)
    srv = CriaServer(cfg, log, Upstream(cfg.upstream.base_url))
    try:
        ep = srv.router.endpoint_for("reasoner")
        assert (ep._window, ep._window_final) == (49152, True)
        assert Upstream("http://x")._window_final is False
    finally:
        srv.server_close()
        log.close()
