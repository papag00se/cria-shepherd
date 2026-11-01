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
        assert not cfg.planner.enabled and cfg.system1.enabled is False and cfg.retention.auto_prune_after is None and cfg.retention.after_seconds is None
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
                         '[logging]\nlevel = "debug"\n')
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
    ('[retention]\nauto_prune_after = 14\n', "auto_prune_after must be an age string"),
    ('[retention]\nauto_prune_after = "soon"\n', "age must look like"),
    ('[retention]\nauto_prune_after = "30m"\n', "below the minimum of 60m"),
    ('[retention]\nauto_prune_after = "14d"\nauto_prune_every = "10s"\n', "auto_prune_every.*below the minimum"),
    ('[retention]\nauto_prune_after = "14d"\nauto_prune_every = 3600\n', "auto_prune_every must be an age string"),
    ('[retention]\nauto_prune_after = "14d"\nidle_days = 3\n', "supports only auto_prune_after and auto_prune_every"),
    ('[roles.coder]\nbackend = "nope"\n', "no matching"),
    ('[backends.g]\ntransport = "http"\napi_key_env = "K"\n[roles.coder]\nbackend = "g"\n', "needs a base_url"),
    ('[backends.cx]\ntransport = "cli"\ntool = "codex"\n[roles.r]\nbackend = "cx"\n', "codex exec"),
    *[(f'[backends.cl]\ntransport = "cli"\ntool = "claude"\n[roles.{r}]\nbackend = "cl"\n', f"roles.{r}\\] backend = 'cl' is a cli backend")
      for r in ("coder", "reasoner", "classifier", "compactor")],      # the loop's own calls need a chat completion: refused at load, not silently run locally
    (ROLE + '[failover]\ncoding = ["ghost"]\n', "no \\[roles.ghost\\]"),
    (ROLE + 'vision = "true"\n', "vision"),
    (ROLE + 'vision = true\n', "vision_model"),
    # a misspelt or unknown key is an error naming it, in every table (it used to be dropped: `capture_call = true` ran with capture off)
    ('[future]\nx = 1\n', r"\[config\] unknown entry future"),
    ('[server]\nprot = 1\n', r"\[server\] unknown key prot"),
    ('[defaults]\ntimeout_secs = 5\n', r"\[defaults\] unknown key timeout_secs"),
    ('[logging]\ncapture_call = true\n', r"\[logging\] unknown key capture_call"),
    ('[indicators]\nroute_banner = true\n', r"\[indicators\] unknown key route_banner"),
    ('[tools]\nfocuss = true\n', r"\[tools\] unknown key focuss"),
    ('[context]\nfocus_trims = true\n', r"\[context\] unknown key focus_trims"),
    ('[safety]\nexternal_dir_permisson = "read"\n', r"\[safety\] unknown key"),
    ('[planner]\nenable = true\n', r"\[planner\] unknown key enable"),
    ('[engagement]\nlvl = 3\n', r"\[engagement\] unknown key lvl"),
    (LOCAL + 'reasoning_stile = "x"\n', r"backends.local\] unknown key reasoning_stile"),
    ('[backends.c]\ntransport = "cli"\nbase_url = "http://x"\n', r"backends.c\] unknown key base_url"),
    (ROLE + 'temprature = 0.1\n', r"roles.coder\] unknown key temprature"),
    (ROLE + '[failover]\ncodeing = ["coder"]\n', r"\[failover\] unknown chain codeing"),
    # a quoted or wrong-typed value is an error, never coerced (bool("false") is True)
    ('[planner]\nenabled = "false"\n', r"enabled must be true or false"),
    ('[logging]\nconsole = 0\n', r"console must be true or false"),
    ('[tools]\nfocus = "no"\n', r"focus must be true or false"),
    ('[indicators]\nenabled = "off"\n', r"enabled must be true or false"),
    ('[server]\nport = "18085"\n', r"port must be an integer"),
    ('[server]\nport = 70000\n', r"port must be 0..65535"),
    ('[server]\nheartbeat_seconds = -1\n', r"at least 0"),
    ('[defaults]\ntimeout_seconds = "600"\n', r"timeout_seconds must be an integer"),
    ('[defaults]\ntimeout_seconds = 0\n', r"timeout_seconds must be at least 1"),
    ('[context]\nsatisfaction_check_start = true\n', r"must be an integer"),
    ('[engagement]\nlevel = "3"\n', r"level must be an integer"),
    ('[engagement]\nlevel = 2.5\n', r"level must be an integer"),
    ('[engagement]\nbias = 3\n', r"bias must be task"),
    (ROLE + 'temperature = "hot"\n', r"temperature must be a number"),
    (ROLE + 'top_k = 1.5\n', r"top_k must be an integer"),
    (ROLE + 'collapse_system_prompt = "yes"\n', r"collapse_system_prompt must be true or false"),
    (ROLE + '[failover]\ncoding = "coder"\n', r"coding must be an array of role names"),
    # cria's secrets file lives in one place
    ('env_file = "/etc/passwd"\n', r"env_file must be ~/.cria/.env"),
    ('env_file = "./.env"\n', r"env_file must be ~/.cria/.env"),
    ('env_file = 5\n', r"env_file must be a string"),
])
def test_removed_unknown_and_malformed_keys_fail_loudly_at_load(tmp_path, text, why):
    """Zero aliases: a removed key, a wrong type or a dangling reference stops startup with a pointed message instead of being ignored."""
    with pytest.raises(ValueError, match=why):
        load(tmp_path, text)


def test_the_example_config_loads_and_documents_every_key_the_loader_accepts():
    """cria.example.toml is the operator's reference: it must load as written, and every key any table accepts must appear in it (set or commented)."""
    import dataclasses
    import re
    Config.load(EXAMPLE)
    accepted = {f.name for cls in (cfgmod.ServerConfig, cfgmod.UpstreamConfig, cfgmod.LoggingConfig, cfgmod.IndicatorsConfig, cfgmod.ToolsConfig,
                                   cfgmod.ContextConfig, cfgmod.SafetyConfig, cfgmod.RetentionConfig, cfgmod.PlannerConfig, cfgmod.System1Config,
                                   cfgmod.AssistConfig, cfgmod.Backend) for f in dataclasses.fields(cls)}
    accepted |= cfgmod._ROLE_KEYS | cfgmod._FAILOVER_CHAINS | cfgmod._ENGAGEMENT_KEYS | cfgmod._TOP_LEVEL_KEYS
    accepted -= {"name", "drive", "question", "profile"}  # `name` is the table's own key; drive is the legacy spelling of level; question has no chain of its own
    text = EXAMPLE.read_text()
    missing = sorted(k for k in accepted if not re.search(rf"(?m)^#?\s*\[?{k}\b", text))
    assert missing == []


def test_env_file_may_name_only_the_cria_dir_secrets_file(tmp_path, monkeypatch):
    """The documented `~/.cria/.env`, its absolute spelling and `$HOME`-relative expansion load; any other path is refused."""
    assert Config.load(EXAMPLE).env_file == "~/.cria/.env"
    assert load(tmp_path, f'env_file = "{cfgmod.CRIA_HOME / ".env"}"\n').env_file == str(cfgmod.CRIA_HOME / ".env")
    assert load(tmp_path, "").env_file is None and load(tmp_path, 'env_file = ""\n').env_file is None


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
    leaked = "hmm 3x17.</think>\n\nNo, 51 is not prime."
    assert Role("c", "local", reasoning="on").clean_content(leaked) == leaked and Role("c", "local", reasoning="off").clean_content(None) == ""   # MUT2: only OFF strips


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
