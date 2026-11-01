"""A history an earlier release lowered is replayed through the real `Upstream._prep`: the model reads the calls it made, never a private command."""
import json
import re

from cria import bodykeys, privatenames, probegate, toolwire, upstream, wsview, writeproxy

OLD = {new: old for old, new in privatenames.LEGACY}   # current spelling -> the earlier one
NAME = re.compile(r"(?i)cria|shepherd|ctx-(?:mpsnap|done|edits|gate|helper|private)|__ctx_|___CTX_(?:SURVEY|SV|GATE)|__CTX_[A-Z_]+__")
EARLIER = "|".join(re.escape(old) for old, _ in privatenames.LEGACY)
ARGS = {"path": "app.py", "old_string": "x = 1", "new_string": "x = 2"}
FRAME = "\n".join([wsview.SURVEY_OPEN, "___CTX_SV_meta___", "root\t/w", "___CTX_SV_done___", "entries\t0", "complete\t1", wsview.SURVEY_CLOSE])


def earlier(text):
    """The spelling an earlier release wrote: the current composer's output with each current name put back."""
    for old, new in privatenames.LEGACY:
        text = text.replace(new, old)
    return text


def call(cid, command, name="exec_command"):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps({"cmd": command})}}


def result(cid, text):
    return {"role": "tool", "tool_call_id": cid, "content": "Chunk ID: a1\nWall time: 0.0000 seconds\nProcess exited with code 0\nOutput:\n" + text}


def history(note):
    """What a harness stored from the earlier release: an unreceipted lowered edit that carried a survey, a survey on its own, a
    gate command, and the model's own `cat` of a file that quotes a marker (note), which is data."""
    lowered = toolwire._sentinel("edit_file", ARGS) + "\n" + writeproxy._edit_command("app.py", "x = 1", "x = 2") + "\n" + wsview.survey_command("s", cd="/w")
    gate = probegate._gate_sentinel(["pytest -q"]) + "\necho ___CTX_GATE_probe-0___\npytest -q"
    return [{"role": "system", "content": "permissions"}, {"role": "user", "content": "fix the rounding bug"},
            {"role": "assistant", "content": "", "tool_calls": [call("e1", earlier(lowered))]}, result("e1", "Wrote app.py\n" + earlier(FRAME)),
            {"role": "assistant", "content": "", "tool_calls": [call("s1", earlier(wsview.survey_command("s2", cd="/w")))]}, result("s1", earlier(FRAME)),
            {"role": "assistant", "content": "", "tool_calls": [call("g1", earlier(gate))]}, result("g1", earlier("___CTX_GATE_probe-0___\nEXIT:0\n")),
            {"role": "assistant", "content": "", "tool_calls": [call("c1", "cat notes.md")]}, result("c1", note),
            {"role": "user", "content": "continue"}]


def wire(messages):
    up = upstream.Upstream("http://x", api_key="unused", context_window=49152, capture_rendered=False)
    body = {"model": "m", "messages": messages, bodykeys.PINNED_TASK: "fix the rounding bug"}
    return json.loads(up._prep(body, False, type("L", (), {"emit": lambda *a, **k: None})())[0])["messages"]


def test_a_replayed_earlier_history_shows_the_model_its_own_calls_and_no_private_name():
    """ornith1.5_9b / Java, 2026-10-22/23 replayed through a fresh session: 36 hits on the survey frame, the write/edit heredoc delimiter, the survey's shell
    variable and the composed programs in the model's view, because a header without a receipt is rejected (right for text a coder wrote) and nothing
    else re-presented it. The wire re-presents the declared call, drops the survey that rode home on it, drops a survey nobody asked
    for, renames the gate's own commands, and leaves text a coder or file wrote alone - the quoted marker in `notes.md` is data."""
    note = "# notes\n" + OLD["___CTX_"] + "GATE_ is the section prefix\n"
    sent = wire(history(note))
    edit = next(m for m in sent if m.get("tool_calls") and m["tool_calls"][0]["id"] == "e1")
    assert (edit["tool_calls"][0]["function"]["name"], json.loads(edit["tool_calls"][0]["function"]["arguments"])) == ("edit_file", ARGS)
    by_id = {m["tool_call_id"]: m["content"] for m in sent if m["role"] == "tool"}
    assert "Wrote app.py" in by_id["e1"] and wsview.SURVEY_OPEN not in by_id["e1"]
    assert "s1" not in by_id and not any(c["id"] == "s1" for m in sent for c in m.get("tool_calls") or [])
    assert by_id["c1"].endswith(note)                                                 # a file's own text is never renamed
    ids = lambda m: {m.get("tool_call_id"), *(c["id"] for c in m.get("tool_calls") or [])}
    gate = [json.dumps(m, ensure_ascii=False) for m in sent if "g1" in ids(m)]
    assert gate and not any(re.search(EARLIER, t) for t in gate)                      # the gate's own section names are the current ones
    private = [json.dumps(m, ensure_ascii=False) for m in sent if not ids(m) & {"c1", "g1"}]
    assert [t[:90] for t in private if NAME.search(t) or re.search(EARLIER, t)] == []
    assert {c["id"] for m in sent for c in m.get("tool_calls") or []} == {r for r in by_id}   # no orphan call or result left


def test_a_current_receipted_lowering_and_the_models_own_commands_pass_the_wire_unchanged():
    """The step is silent for what it does not own: a receipted declaration (the current release's, re-presented before the wire), a model's
    own command that quotes a header on a LATER line, and a history with nothing private are all returned as given."""
    quoted = "echo '" + toolwire._sentinel("edit_file", ARGS) + "'"
    messages = [{"role": "user", "content": "task"}, {"role": "assistant", "content": "", "tool_calls": [call("q1", quoted)]},
                result("q1", "# " + toolwire._SENTINEL + "\n"), {"role": "user", "content": "go"}]
    assert privatenames.restore_wire(messages) is messages
    assert wire(messages)[1]["tool_calls"][0]["function"]["name"] == "exec_command"
