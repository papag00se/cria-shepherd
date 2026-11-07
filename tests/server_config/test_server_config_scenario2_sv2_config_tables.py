"""Config tables: every accepted spelling normalises, every malformed value is rejected with its reason (loaded through real TOML), the level ladder
properties, and Role.apply's prompt-shaping arms (system directives, collapse into the user turn, merge hint, caps)."""
import copy

import pytest

from cria import bodykeys
from cria.config import Config, MAX_ENGAGEMENT_LEVEL, Role, RoutingConfig
from test_server_config_config import LOCAL, ROLE, load


@pytest.mark.parametrize("text, why", [
    ('[engagement]\nlevel = 6\n', "level must be 0..5, got 6"),
    ('[engagement]\nlevel = -1\n', "level must be 0..5"),
    ('[engagement]\nlevel = "high"\n', "level must be an integer"),
    ('[engagement]\nbias = "eager"\n', "bias must be task|simple|question"),
    ('[safety]\nexternal_dir_permission = "root"\n', "external_dir_permission must be none|read|write"),
    ('[backends]\nlocal = "http://x"\n', r"\[backends.local\] must be a table"),
    ('[backends.x]\ntransport = "grpc"\n', "transport must be http|cli"),
    ('[backends.x]\ntransport = "cli"\ntool = "gemini"\n', 'tool must be "claude"'),
    ('[roles]\ncoder = 5\n', r"\[roles.coder\] must be a table"),
    (LOCAL + '[roles.coder]\nbackend = "local"\nvision_model = "  "\n', "vision_model must be a nonempty"),
    ('[tools]\nworkspace_image_tool = "see_image"\n', "workspace_image_tool"),
    ('[system1]\nenabled = "yes"\n', "enabled must be true or false"),
    ('[system1]\nbundle_dir = ""\n', "bundle_dir must be a non-empty string"),
    ('[system1]\nenabled = true\nbundle_dir = "/b"\nthreads = true\n', "threads must be a positive integer"),
    ('[system1]\nflavour = 1\n', "supports only enabled, bundle_dir and threads"),
    ('[assists]\ndisabled = "x"\n', "disabled must be an array of atomic IDs"),
    ('[assists]\ndisabled = [1]\n', "disabled must be an array of atomic IDs"),
    ('[assists]\nprofile = "no-such-profile"\n', "no-such-profile"),
])
def test_every_malformed_value_is_rejected_with_its_reason(tmp_path, text, why):
    """One more row per rule the loader enforces: ladder range, bias, safety, backend/role shape, vision pins, tools, system1 and assists."""
    with pytest.raises(ValueError, match=why):
        load(tmp_path, text)


def test_the_documented_defaults_are_what_an_empty_config_gives():
    """Every default in one place, from the documented values (not read back from the dataclass)."""
    cfg = Config()
    assert (cfg.server.host, cfg.server.port, cfg.server.heartbeat_seconds) == ("127.0.0.1", 18085, 5.0)
    assert (cfg.upstream.base_url, cfg.upstream.timeout_seconds, cfg.upstream.context_window) == ("http://127.0.0.1:18084", 600, 0)
    log = cfg.logging
    assert (log.level, log.dir, log.console, log.jsonl, log.capture_calls, log.capture_dir, log.capture_rendered) == ("info", "~/.cria/logs", True, True, False, "~/.cria/test-runs/calls", True)
    assert cfg.routing.engagement_level == MAX_ENGAGEMENT_LEVEL == 5 and cfg.routing.engagement_bias == "task" and cfg.routing.roles == {}
    assert cfg.safety.external_dir_permission == "none" and cfg.assists.disabled == () and cfg.assists.profile == "default"
    assert cfg.system1.enabled is True and str(cfg.system1.bundle_path).endswith('/cria/system1_bundle') and cfg.system1.threads >= 1
    assert cfg.indicators.enabled and cfg.indicators.reasoning_transcript and cfg.tools.workspace_image_tool is None


def test_accepted_spellings_normalise(tmp_path):
    """Case-insensitive enums, trailing slashes, legacy drive, role short names and CLI backends all load to the documented values."""
    cfg = load(tmp_path, '[server]\nport = 9000\nheartbeat_seconds = 2\n[logging]\nlevel = "WARN"\ncapture_calls = true\n[safety]\nexternal_dir_permission = "READ"\n'
                         '[indicators]\nenabled = false\nmetrics = false\n[engagement]\ndrive = false\nbias = "Simple"\n'
                         '[backends.cl]\ntransport = "CLI"\nbinary = "/opt/claude"\ncwd = "/w"\n'
                         '[backends.cloud]\nbase_url = "https://api.example/v1/"\napi_key_env = "K"\nmodel = "gpt-x"\nreasoning_style = "openai"\n'
                         '[roles.a]\nbackend = "cl"\n[roles.b]\nbackend = "cloud"\ntemp = 0.3\ntop_k = 40\nreasoning = "OFF"\nmax_tokens = 100\n'
                         '[roles.c]\nbackend = "cloud"\ntemperature = 0.9\ntemp = 0.1\nthink_protocol = "system_directive"\ncollapse_system_prompt = true\nmerge_consecutive_turns = true\n')
    assert (cfg.server.port, cfg.server.heartbeat_seconds, cfg.logging.level, cfg.logging.capture_calls, cfg.safety.external_dir_permission) == (9000, 2.0, "warn", True, "read")
    assert (cfg.indicators.enabled, cfg.indicators.metrics, cfg.indicators.route) == (False, False, True)
    r = cfg.routing
    assert (r.engagement_level, r.engagement_bias) == (0, "simple") and not r.assists_enabled and not r.tool_call_fixes
    cl, cloud = r.backends["cl"], r.backends["cloud"]
    assert (cl.transport, cl.binary, cl.cwd, cloud.base_url, cloud.model) == ("cli", "/opt/claude", "/w", "https://api.example/v1", "gpt-x")
    a, b, c = r.roles["a"], r.roles["b"], r.roles["c"]
    assert a.think_protocol == "none" and b.think_protocol == "openai" and c.think_protocol == "system_directive"
    assert (b.temperature, b.top_k, b.reasoning, b.max_tokens) == (0.3, 40, "off", 100) and c.temperature == 0.9
    assert c.collapse_system_prompt and c.merge_consecutive_turns and not b.collapse_system_prompt


@pytest.mark.parametrize("level, flags", [
    (0, (False, False, False, False, False)), (1, (True, False, False, False, False)), (2, (True, True, False, False, False)),
    (3, (True, True, True, False, False)), (4, (True, True, True, True, False)), (5, (True, True, True, True, True))])
def test_the_ladder_is_cumulative_and_the_legacy_drive_names_the_two_ends(level, flags):
    """Each rung enables exactly the capabilities at or below it (tool fixes, simple tools, context fixes, done refusals, assists)."""
    r = RoutingConfig(engagement_level=level)
    assert (r.tool_call_fixes, r.simple_tools, r.context_fixes, r.done_refusals, r.assists_enabled) == flags and r.engagement_drive is flags[4]


def body():
    return {"model": "m", "messages": [{"role": "system", "content": "SYS"}, {"role": "user", "content": "ask"}]}


def test_system_directive_roles_put_the_reasoning_switch_in_the_first_system_message_once():
    """A backend whose switch is text: reasoning on/off prepends its sentence to the system message (no stacking on a repeat), creates a system message when none exists, and says nothing for auto/unset."""
    b = body()
    role = Role("c", "x", think_protocol="system_directive", reasoning="off")
    role.apply(b)
    first = b["messages"][0]["content"]
    assert first.endswith("\n\nSYS") and len(b["messages"]) == 2
    role.apply(b)
    assert b["messages"][0]["content"] == first
    bare = {"messages": [{"role": "user", "content": "hi"}]}
    Role("c", "x", think_protocol="system_directive", reasoning="on").apply(bare)
    assert [m["role"] for m in bare["messages"]] == ["system", "user"] and bare["messages"][0]["content"] != first.split("\n\n")[0]
    for reasoning in (None, "auto"):
        untouched = body()
        Role("c", "x", think_protocol="system_directive", reasoning=reasoning).apply(untouched)
        untouched.pop(bodykeys.ROLE_ORIGIN)     # the role's record of the pre-role body: the only thing it adds
        assert untouched == body()
    empty = {"messages": [{"role": "system", "content": "  "}, {"role": "user", "content": "q"}]}
    Role("c", "x", think_protocol="system_directive", reasoning="off").apply(empty)
    assert empty["messages"][0]["content"] == first.split("\n\n")[0] and len(empty["messages"]) == 2


@pytest.mark.parametrize("messages, expected", [
    ([{"role": "system", "content": "A"}, {"role": "system", "content": "B"}, {"role": "user", "content": "q"}],
     [{"role": "user", "content": "A\n\nB\n\nq"}]),
    ([{"role": "system", "content": "A"}], [{"role": "user", "content": "A"}]),                       # a system-only judge keeps its question
    ([{"role": "system", "content": " "}, {"role": "user", "content": "q"}], [{"role": "user", "content": "q"}]),
    ([{"role": "user", "content": "q"}, {"role": "system", "content": "late"}], [{"role": "user", "content": "q"}, {"role": "system", "content": "late"}]),
    ([{"role": "system", "content": "A"}, {"role": "assistant", "content": "a"}, {"role": "user", "content": "q"}],
     [{"role": "assistant", "content": "a"}, {"role": "user", "content": "A\n\nq"}]),
    ([], []),
])
def test_collapse_system_prompt_folds_leading_system_text_into_the_first_user_turn_without_losing_order(messages, expected):
    """DeepSeek-style template: leading system messages are joined in order into the first user turn; a system-only body becomes a user turn; late system messages stay; empty ones carry nothing."""
    b = {"messages": copy.deepcopy(messages)}
    Role("c", "x", collapse_system_prompt=True).apply(b)
    assert b["messages"] == expected


def test_role_apply_hints_and_the_nothink_directive_arms():
    """merge_consecutive_turns is only a hint key; reasoning=off adds the no-think sentence to an existing system turn, creates one when absent, and is withheld from a tool-bearing judge body."""
    b = body()
    Role("c", "x", merge_consecutive_turns=True, reasoning="off").apply(b)
    assert b[bodykeys.MERGE_TURNS] is True and b["messages"][0]["content"].startswith("SYS\n\n") and len(b["messages"]) == 2
    bare = {"messages": [{"role": "user", "content": "hi"}]}
    Role("c", "x", reasoning="off").apply(bare)
    assert [m["role"] for m in bare["messages"]] == ["system", "user"]
    judge = {**body(), "tools": [{"type": "function", "function": {"name": "list_dir"}}]}
    Role("c", "x", reasoning="off").apply(judge)
    assert judge["messages"] == body()["messages"] and judge["chat_template_kwargs"] == {"enable_thinking": False}
    Role("c", "x").apply(nothing := {"messages": "not-a-list"})
    assert nothing.pop(bodykeys.ROLE_ORIGIN) and nothing == {"messages": "not-a-list"}
    for bad in ({"vision": "true"}, {"vision_model": 7}):
        with pytest.raises(ValueError):
            Role("c", "x", **bad)
