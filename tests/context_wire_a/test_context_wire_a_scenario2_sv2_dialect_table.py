"""Call-dialect table through massage.recover_leaked_tool_calls: Gemma, JSON envelopes, Hermes/XML, fenced pairs, channel prefixes, call syntax and the
LFM2 sentinels (stripped from content, recovered from reasoning) - each recovered exactly as typed or left alone, with the event that says which path ran."""
import pytest

from test_context_wire_a_recovery import run

LFM2 = lambda body: "<|tool_call_start|>" + body + "<|tool_call_end|>"


@pytest.mark.parametrize("reply, calls, left, event", [
    ('<|tool_call>call:read_file{path:<|"|>a.py<|"|>,start_line:3}<tool_call|>', [("read_file", {"path": "a.py", "start_line": 3})], None, "massage.leaked_recovered"),
    ('<|tool_call>call:exec_command{cmd:[<|"|>ls<|"|>,<|"|>-la<|"|>]}<tool_call|>', [("exec_command", {"cmd": ["ls", "-la"]})], None, "massage.leaked_recovered"),
    ("<|tool_call>call:read_file{path:a.py,start_line:-5,x:true,y:false,z:1_000,w:+5}<tool_call|>",    # Rust i64 fidelity: only -?digits is a number
     [("read_file", {"path": "a.py", "start_line": -5, "x": True, "y": False, "z": "1_000", "w": "+5"})], None, "massage.leaked_recovered"),
    ("<|tool_call>call:exec_command{cmd:{a:1,b:[1,2]}}<tool_call|>", [("exec_command", {"cmd": {"a": 1, "b": [1, 2]}})], None, "massage.leaked_recovered"),
    ('<|tool_call>call:write_file{path:<|"|>a.py<|"|>,content:<|"|>print(1', [("write_file", {"path": "a.py", "content": "print(1"})], None, "massage.leaked_recovered"),  # cut: what arrived, not nothing
    ('<|tool_call>call:ls{cmd:<|"|>ls<|"|>}<tool_call|>', [("shell", {"cmd": "ls"})], None, "massage.leaked_recovered"),   # a shell binary named as a tool is the shell
    ("<|tool_call>call:{path:x}<tool_call|>", [], "<|tool_call>call:{path:x}<tool_call|>", None),
    ('{"plan": "x", "commands": [{"name": "read_file", "arguments": {"path": "a"}}]}', [("read_file", {"path": "a"})], None, "massage.envelope_recovered"),
    ('{"tool_calls": [{"name": "exec_command", "arguments": "ls -la"}]}', [("exec_command", {"cmd": "ls -la"})], None, "massage.envelope_recovered"),  # a bare string lands on the schema's sole required field
    ('{"tool_calls": [{"name": "exec_command", "arguments": 5}]}', [], '{"tool_calls": [{"name": "exec_command", "arguments": 5}]}', None),
    ('{"tool_calls": [{"name": "nuke", "arguments": {}}]}', [], '{"tool_calls": [{"name": "nuke", "arguments": {}}]}', None),
    ('<tool_call>{"name": "read_file", "arguments": {"path": "a"}}</tool_call>', [("read_file", {"path": "a"})], None, "massage.leaked_recovered"),
    ('<tool_call>{"name": "read_file", "arguments": {"path": }</tool_call>', [], '<tool_call>{"name": "read_file", "arguments": {"path": }</tool_call>', None),
    ('```json\n{"tool": "read_file", "args": {"path": "a"}}\n```', [("read_file", {"path": "a"})], None, "massage.fenced_call_recovered"),   # any one-string + one-object pair
    ('```json\n{"name": "read_file", "description": "x", "parameters": {}}\n```', [], None, None),                                   # a schema echo is not a call
    ('<|channel>thought<channel|>read_file({"path":"a"})', [("read_file", {"path": "a"})], None, "massage.call_syntax_recovered"),
    ('<|channel|>analysis<|message|>read_file({"path":"a"})', [("read_file", {"path": "a"})], None, "massage.call_syntax_recovered"),
    ('read_file({"path": "a"}) and then prose', [("read_file", {"path": "a"})], " and then prose", "massage.call_syntax_recovered"),
    ('```\nread_file({"path": "a"})\n```', [], None, None),                                                                          # displayed, not made
    ('read_file({"path": null})', [], "read_file({\"path\": null})", None),                                                        # a present-but-null required argument is unfinished
    ("<function=read_file><parameter=path>\n</parameter></function>", [("read_file", {"path": ""})], None, "massage.leaked_recovered"),
    ("<function=write_file><parameter=path>a</parameter><parameter=content>text <parameter=zz>", [], None, None),
    ('｜DSML｜invoke name="read_file"', [], None, None),
])
def test_dialect_table_content_recovery(reply, calls, left, event):
    """Each dialect is recovered as the model typed it (or refused whole); `left` is the content that remains (None = nothing asserted beyond the calls)."""
    got_calls, got_content, finish, events = run(reply)
    assert got_calls == calls and finish == ("tool_calls" if calls else "stop")
    assert event in events if event else "massage.leaked_recovered" not in events and not any(e.endswith("_recovered") for e in events)
    if left is not None:
        assert got_content == (left if left else None)


@pytest.mark.parametrize("reasoning, calls", [
    (LFM2('[read_file(path="a.py")]'), [("read_file", {"path": "a.py"})]),
    (LFM2('[read_file(path="a.py"), exec_command(cmd="ls")]'), [("read_file", {"path": "a.py"}), ("exec_command", {"cmd": "ls"})]),
    ("I will read it. " + LFM2('[read_file(path="a")]'), [("read_file", {"path": "a"})]),
    (LFM2('[read_file("a.py")]'), []),                      # positional: which field would it be?
    (LFM2('[os.read_file(path="a")]'), []),                 # an attribute call is not a menu tool
    (LFM2('[read_file(path=b"a")]'), []),                   # a literal the wire cannot carry
    (LFM2("[read_file(path=]"), []),                        # truncated grammar
    ('<|tool_call_start|>[read_file(path="a")]', []),       # no close: generation was cut mid-emission
    ('<tool_call>{"name":"read_file","arguments":"{\\"path\\": \\"a\\"}"}</tool_call>', [("read_file", {"path": "a"})]),
    ('<tool_call>{"arguments":{}}</tool_call>', []),
    ('<function=read_file>{"path": "a"}</function>', [("read_file", {"path": "a"})]),
    ("<function=read_file>no params</function>", []),
])
def test_dialect_table_reasoning_recovery(reasoning, calls):
    """A call that only ever reached the reasoning channel is recovered when complete and exactly typed; every partial or ambiguous one yields no call."""
    got, _content, finish, events = run("", reasoning_content=reasoning)
    assert got == calls and finish == ("tool_calls" if calls else "stop") and ("massage.reasoning_call_recovered" in events) is bool(calls)


def test_lfm2_sentinels_in_content_are_stripped_never_recovered():
    """llama.cpp's own parser owns a well-formed native call, so content carrying the sentinels is scrubbed (pairs and orphans) and nothing is invented."""
    got, content, finish, events = run("before " + LFM2('[read_file(path="a.py")]') + " after <|tool_call_end|>")
    assert got == [] and finish == "stop" and "<|tool_call" not in (content or "") and "before" in content and "after" in content
