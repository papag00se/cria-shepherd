"""massage.apply over realistic tool-call shapes: shell-ish names and argument shapes lowered to the harness's one shell, edit/add-file patches, argument repair
(and its refusals), name repair, text-expected turns, and the fenced-envelope admission refusals - each asserted on the calls the harness would receive."""
import json

import pytest

from cria import massage
from test_context_wire_a_recovery import run


def tool(name, props, required=()):
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": {p: {"type": "string"} for p in props}, "required": list(required)}}}


SHELL, EXEC = [tool("shell", ["command"], ["command"])], [tool("exec_command", ["cmd"], ["cmd"])]
PATCH = [tool("apply_patch", ["input"], ["input"]), *SHELL]
WRITE = [tool("write_file", ["path", "content"], ["path", "content"]), tool("apply_patch", ["input"], ["input"]), *EXEC]
NO_TOOLS = []


class Rlog:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append(kind)


def call(name, args):
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": args if isinstance(args, (str, type(None))) else json.dumps(args)}}


def apply(tools, calls=None, content=None, finish=None, **msg):
    message = {"role": "assistant", "content": content, **msg, **({"tool_calls": calls} if calls else {})}
    rlog = Rlog()
    out = massage.apply({"choices": [{"index": 0, "message": message, "finish_reason": finish or ("tool_calls" if calls else "stop")}]}, tools, rlog)["choices"][0]
    return [(c["function"]["name"], c["function"]["arguments"]) for c in out["message"].get("tool_calls") or []], out["message"].get("content"), out["finish_reason"], rlog.events


@pytest.mark.parametrize("tools, original, name, command, event", [
    (SHELL, call("ls", {"path": "."}), "shell", "ls .", "massage.tool_normalized"),
    (SHELL, call("grep", {"pattern": "TODO", "path": "src"}), "shell", "grep TODO src", "massage.tool_normalized"),
    (SHELL, call("find", {"flags": "-name", "args": ["*.py", "-print"]}), "shell", "find -name *.py -print", "massage.tool_normalized"),
    (SHELL, call("shell", {"command": ["bash", "-lc", "ls -la"]}), "shell", "ls -la", "massage.shell_reshaped"),         # argv wrapped in bash -lc
    (SHELL, call("shell", {"command": [["bash", "-c", "make test"]]}), "shell", "make test", "massage.shell_reshaped"),   # double-wrapped
    (SHELL, call("shell", {"command": ["ls", "-l", "src"]}), "shell", "ls -l src", "massage.shell_reshaped"),
    (SHELL, call("shell", {"cmd": "ls"}), "shell", "ls", "massage.shell_reshaped"),                                       # the other tool's key
    (SHELL, call("shell", {"command": "ls"}), "shell", "ls", None),                                                       # already right: untouched
    (EXEC, call("exec_command", {"cmd": ["ls", "-l"]}), "exec_command", "ls -l", "massage.shell_reshaped"),
    (SHELL, call("exec_command", {"cmd": "pytest -q"}), "shell", "pytest -q", "massage.tool_normalized"),                  # a tool the harness lacks lowers to its shell
    (SHELL, call("exec_command", {"cmd": None}), None, None, None),                                                       # nothing to run: left alone
])
def test_shell_shaped_calls_reach_the_harnesss_one_shell_tool_as_one_command_string(tools, original, name, command, event):
    """The model's shell dialects (binary-as-tool, argv, bash -lc, wrong key, foreign exec tool) become exactly one command string on the tool the harness advertises."""
    calls, _content, finish, events = apply(tools, [original])
    if name is None:
        assert calls == [(original["function"]["name"], original["function"]["arguments"])] and events == []
        return
    assert [(n, json.loads(a)) for n, a in calls] == [(name, {("cmd" if name == "exec_command" else "command"): command})] and finish == "tool_calls"
    assert events == ([event] if event else [])


@pytest.mark.parametrize("tools, original, expect_name, expect_events", [
    (PATCH, call("edit_file", {"path": "a.py", "old_string": "x=1", "new_string": "x=2"}), "apply_patch", ["massage.edit_to_patch"]),
    (PATCH, call("str_replace", {"path": "a.py", "old_str": "x=1"}), "apply_patch", ["massage.edit_to_patch"]),        # deleting text is an edit too
    (PATCH, call("edit_file", {"path": "a.py", "new_string": "x=2"}), "edit_file", []),                                  # no old text: not a patch
    ([tool("edit_file", ["path"]), *PATCH], call("edit_file", {"path": "a.py", "old_string": "a", "new_string": "b"}), "edit_file", []),   # the harness has its own editor
    (WRITE, call("apply_patch", {"input": "*** Begin Patch\n*** Add File: n.py\n+a\n+b\n*** End Patch"}), "write_file", ["massage.add_to_write"]),
    (WRITE, call("apply_patch", {"input": "*** Add File: x.py\n+1"}), "write_file", ["massage.add_to_write"]),
    (PATCH, call("apply_patch", {"input": "*** Begin Patch\\n*** Add File: x.py\\n+1\\n*** End Patch"}), "apply_patch", ["massage.patch_normalized"]),  # doubly-escaped newlines
    (PATCH, call("apply_patch", "{nope"), "apply_patch", []),
    (PATCH, call("apply_patch", {"input": 5}), "apply_patch", []),
])
def test_patch_shaped_calls_become_the_tool_the_harness_can_run_or_are_left_alone(tools, original, expect_name, expect_events):
    """An edit the harness cannot run becomes an apply_patch; a pure add-file patch becomes write_file when that exists; ambiguous or malformed ones are not touched."""
    calls, _content, _finish, events = apply(tools, [original])
    assert [n for n, _ in calls] == [expect_name] and events == expect_events
    if "edit_to_patch" in "".join(expect_events):
        body = json.loads(calls[0][1])["input"]
        assert body.startswith("*** Begin Patch\n*** Update File: a.py\n-x=1\n") and body.rstrip().endswith("*** End Patch")
    if expect_name == "write_file":
        assert json.loads(calls[0][1])["path"].endswith(".py")


@pytest.mark.parametrize("arguments, repaired, events", [
    ('{"path": "a.py", "content": "line1\nline2"}', {"path": "a.py", "content": "line1\nline2"}, ["massage.args_repaired"]),   # raw newline in a string
    ({"path": "a", "content": "b"}, {"path": "a", "content": "b"}, []),                                                         # structured arguments are serialised
    (None, {}, []),
    ('{"path": "a", "content": "ok"}', {"path": "a", "content": "ok"}, []),
])
def test_argument_strings_are_repaired_only_to_what_the_model_wrote(arguments, repaired, events):
    """Raw-newline JSON, dict and null arguments all reach the harness as valid JSON of the model's own values."""
    calls, _c, _f, got = apply(WRITE, [{"id": "c", "type": "function", "function": {"name": "write_file", "arguments": arguments}}])
    assert json.loads(calls[0][1]) == repaired and got == events


def test_unrecoverable_arguments_are_forwarded_exactly_as_the_model_wrote_them():
    """A garbage string is not replaced by {} (that would delete the call): the harness sees the real bytes and its own parse error."""
    calls, _c, _f, events = apply(WRITE, [call("write_file", "{{{{ nothing")])
    assert calls == [("write_file", "{{{{ nothing")] and events == []


def test_a_misspelt_tool_name_is_folded_to_the_one_advertised_tool_and_unknown_names_are_not_invented():
    """Write_File -> write_file (event logged); a name matching no advertised tool is left as the model wrote it."""
    calls, *_ , events = apply(WRITE, [call("Write_File", {"path": "a", "content": "b"})])
    assert [n for n, _ in calls] == ["write_file"] and events == ["massage.tool_renamed"]
    assert apply(WRITE, [call("teleport", {"x": 1})])[0][0][0] == "teleport"


def test_a_stop_turn_with_only_reasoning_is_answered_with_that_reasoning_but_a_turn_with_a_call_is_not():
    """The answer drafted in reasoning (empty content, finish=stop, no call) is surfaced as the content once; any tool call or real content leaves the turn alone."""
    calls, content, finish, events = apply(NO_TOOLS, None, None, reasoning_content="the answer is 4")
    assert (calls, content, finish, events) == ([], "the answer is 4", "stop", ["massage.reasoning_text_recovered"])
    assert apply(SHELL, [call("shell", {"command": "ls"})], None, reasoning_content="thinking")[1] is None
    assert apply(NO_TOOLS, None, "real answer", reasoning_content="thinking")[1] == "real answer"
    assert apply(NO_TOOLS, None, None, "length", reasoning_content="cut off")[1] is None


CODE = "".join(f"value_{i} = compute({i})\n" for i in range(12))   # well over the 80-character echo floor
ENV = lambda name, args: "```json\n" + json.dumps({"name": name, "arguments": args}) + "\n```"


@pytest.mark.parametrize("reply, finish, calls, reason", [
    ("Draft:\n```python\n" + CODE + "```\n" + ENV("write_file", {"path": "a.py", "content": "y"}), "stop", [], "prefix_fence"),   # a draft the call does not echo: prose, not a call
    ("Draft:\n```python\n" + CODE + "```\n" + ENV("write_file", {"path": "a.py", "content": CODE}), "stop", [("write_file", {"path": "a.py", "content": CODE})], None),
    ("Out:\n```text\nhello\n```\n" + ENV("read_file", {"path": "a"}), "stop", [("read_file", {"path": "a"})], None),               # a text fence is not a draft
    (ENV("nuke", {}), "stop", [], "off_menu"),
    (ENV("read_file", {"zzz": 1}), "stop", [], "inadmissible"),
    (ENV("read_file", {"path": "a"}), "length", [], None),                                                                       # cut at the cap: never executed
    ("```\nexample:\n" + ENV("read_file", {"path": "a"}) + "\n```", "stop", [], None),                                             # shown inside another fence
    (ENV("read_file", {"path": "a"}) + "\n" + ENV("read_file", {"path": "b"}), "stop", [("read_file", {"path": "a"})], None),      # only the first
    ('```json\n{"a": 1}\n```\n' + ENV("read_file", {"path": "a"}), "stop", [], "prefix_fence"),
])
def test_a_fenced_call_envelope_is_admitted_only_by_its_leader_menu_and_draft_rules(reply, finish, calls, reason):
    """Each refusal keeps the reply as the model wrote it (and says why); each admission removes only the call from the content."""
    got, content, _finish, events = run(reply, finish=finish)
    assert got == calls
    refused = [e for e in events if e == "massage.fenced_call_refused"]
    assert bool(refused) is bool(reason) and (content == reply if not calls else True)
