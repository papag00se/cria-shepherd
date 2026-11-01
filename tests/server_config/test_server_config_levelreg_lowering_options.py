"""The rung-gated lowering options (packing L4, edit echo L5) and the focus trim (L3) are registered assists: the bound selection decides
them at the real server, so their rung, their `[assists] disabled` opt-out and LEVELS.md are one record."""
import json
import re

import pytest

from cria import assistruntime, loweringoptions
from cria.config import AssistConfig, Backend, Role, RoutingConfig
from test_server_config_http import BIG, Wire, chat_body, request, no_installed_opener  # noqa: F401
from test_server_config_scenario_wire_tools import EXEC


def lowered_edit(tmp_path, level, disabled=()):
    """What the harness receives for the model's `edit_file` call at this rung: the call itself below the lowering rung, else the
    exec_command text (per-run tokens and the `ctx:tool` receipt line normalised)."""
    w = Wire(tmp_path, lambda url: RoutingConfig(
        backends={"local": Backend("local")}, failover={"coding": ("coder",)}, engagement_level=level,
        roles={"classifier": Role("classifier", "local"), "coder": Role("coder", "local")}),
        assists=AssistConfig(disabled=disabled) if disabled else None)
    try:
        path, body = request("chat-buffered", "__EDIT__ please edit hello.txt")
        body["tools"] = [{"type": "function", "function": EXEC}]
        call = json.loads(w.post(path, body)[1])["choices"][0]["message"]["tool_calls"][0]["function"]
    finally:
        w.close()
    cmd = json.loads(call["arguments"]).get("cmd")
    if cmd is None:
        return call["name"], call["arguments"]
    return call["name"], re.sub(r"[0-9a-f]{16}", "X", cmd.split("\n", 1)[1] if cmd.startswith("# ⟦ctx:tool") else cmd)


def test_the_options_are_registered_at_their_rung_and_resolve_to_exactly_what_the_selection_holds():
    assert {d.policy.id: d.policy.default_level for d in loweringoptions.DEFINITIONS} == {"harness-plumbing-packing": 4, "edit-result-echo": 5}
    for level in range(6):
        for disabled in ((), ("edit-result-echo",), ("harness-plumbing-packing",)):
            got = loweringoptions.resolve(assistruntime.AssistRuntime.select(level=level, disabled=disabled))
            assert got == loweringoptions.Options(pack=level >= 4 and "harness-plumbing-packing" not in disabled,
                                                  edit_echo=level >= 5 and "edit-result-echo" not in disabled)


def test_the_lowered_edit_command_carries_each_option_exactly_at_its_rung_and_honours_its_opt_out(tmp_path):
    """Through the real server at every rung: L2/L3 lower the edit without either option, L4 adds the packed plumbing, L5 adds the echo
    too; opting an assist out at L5 returns exactly the command of the rung below it, byte for byte."""
    at = {level: lowered_edit(tmp_path / f"l{level}", level) for level in range(6)}
    assert at[0][0] == at[1][0] == "edit_file"                                   # no lowering below L2: the harness gets the model's call
    for level, (packs, echoes) in {2: (False, False), 3: (False, False), 4: (True, False), 5: (True, True)}.items():
        assert at[level][0] == "exec_command"
        assert ("zlib.compress(json.dumps(kw)" in at[level][1]) is packs and ("_echo(" in at[level][1]) is echoes
    assert lowered_edit(tmp_path / "no-echo", 5, ("edit-result-echo",)) == at[4]
    assert lowered_edit(tmp_path / "no-pack", 5, ("harness-plumbing-packing",)) != at[4] != at[5]
    assert lowered_edit(tmp_path / "neither", 5, ("edit-result-echo", "harness-plumbing-packing")) == at[3]
    assert lowered_edit(tmp_path / "no-pack4", 4, ("harness-plumbing-packing",)) == at[3]


FOCUS = ("focus-duplicate-pairs", "focus-soft-failure-history", "superseded-write-history")


def sent_tool_calls(tmp_path, level, disabled=()):
    """How many `cat app.py` calls the model server received after the harness replayed the same call (same result) twice."""
    pair = lambda cid: [{"role": "assistant", "content": None, "tool_calls": [{"id": cid, "type": "function", "function": {
        "name": "exec_command", "arguments": '{"cmd":"cat app.py"}'}}]}, {"role": "tool", "tool_call_id": cid, "content": "print(1)"}]
    w = Wire(tmp_path, lambda url: RoutingConfig(engagement_level=level), assists=AssistConfig(disabled=disabled) if disabled else None)
    try:
        w.post("/v1/chat/completions", {"model": "m", "messages": [{"role": "user", "content": "check app.py"}, *pair("c1"), *pair("c2"),
                                                                 {"role": "user", "content": "and now?"}]})
        sent = w.fake.chats[-1][1]["messages"]
    finally:
        w.close()
    return sum(len(m.get("tool_calls") or []) for m in sent)


@pytest.mark.parametrize("level", range(6))
def test_the_focus_trim_folds_an_exact_repeat_exactly_at_l3_and_not_when_its_assists_are_opted_out(tmp_path, level):
    """The proxy path asks the selection: below L3 the repeat reaches the model whole, from L3 it is folded to the last occurrence, and
    opting out every focus assist is the same exact bypass at any rung."""
    assert sent_tool_calls(tmp_path / "on", level) == (1 if level >= 3 else 2)
    assert sent_tool_calls(tmp_path / "off", level, FOCUS) == 2


@pytest.mark.parametrize("level", range(6))
def test_the_context_floor_runs_exactly_at_l3_and_below_it_the_oversize_request_ships_whole(tmp_path, level):
    """The floor is a required foundation (F68), not a registered assist, so its rung is `CONTEXT_FIXES` itself: the same ~70k-token
    system message reaches the 49,152-token model server reduced and labelled from L3, and untouched at L0-L2."""
    w = Wire(tmp_path, lambda url: RoutingConfig(engagement_level=level))
    try:
        body = chat_body("check app.py")
        body["messages"].insert(0, {"role": "system", "content": BIG})
        w.post("/v1/chat/completions", body)
        sent = w.fake.chats[-1][1]["messages"]
    finally:
        w.close()
    assert (sent[0]["content"] == BIG) is (level < 3) and ("⟦ctx:reduced⟧" in sent[0]["content"]) is (level >= 3)
