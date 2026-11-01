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
    ("<|tool_call>call:read_file<tool_call|>", [], "<|tool_call>call:read_file<tool_call|>", None),                               # no argument object at all
    ('<|tool_call>call:read_file{path:[<|"|>a<|"|>,<|"|>b<|"|>', [("read_file", {"path": ["a", "b"]})], None, "massage.leaked_recovered"),   # cut inside an array: what arrived
    ("<|tool_call>call:read_file{path:{x:1,y:", [("read_file", {"path": {"x": 1, "y": ""}})], None, "massage.leaked_recovered"),
    ("<|tool_call>call:read_file{path:{}}<tool_call|>", [("read_file", {"path": {}})], None, "massage.leaked_recovered"),
    ('```json\n{"name": "read_file", "arguments": {"path": }\n```', [], '```json\n{"name": "read_file", "arguments": {"path": }\n```', None),   # an unparseable fenced call is text
    ("```json\n[1]\n```", [], "```json\n[1]\n```", None),
    ('{"plan": "x", "commands": [{"name": "read_file", "arguments": {"path": "a"}}]}', [("read_file", {"path": "a"})], None, "massage.envelope_recovered"),
    ('{"tool_calls": [{"name": "exec_command", "arguments": "ls -la"}]}', [("exec_command", {"cmd": "ls -la"})], None, "massage.envelope_recovered"),  # a bare string lands on the schema's sole required field
    ('{"tool_calls": [{"name": "exec_command", "arguments": 5}]}', [], '{"tool_calls": [{"name": "exec_command", "arguments": 5}]}', None),
    ('{"tool_calls": [{"name": "nuke", "arguments": {}}]}', [], '{"tool_calls": [{"name": "nuke", "arguments": {}}]}', None),
    ('<tool_call>{"name": "read_file", "arguments": {"path": "a"}}</tool_call>', [("read_file", {"path": "a"})], None, "massage.leaked_recovered"),
    ('<tool_call>{"name": "read_file", "arguments": {"path": }</tool_call>', [], '<tool_call>{"name": "read_file", "arguments": {"path": }</tool_call>', None),
    ('{"tool_calls": ["junk", {"name": 5, "arguments": {}}, {"name": "read_file", "arguments": {"path": "a"}}]}', [("read_file", {"path": "a"})], None, "massage.envelope_recovered"),   # junk entries are skipped, the real one kept
    ('{"tool_calls": [{"name": "read_file"}]}', [], '{"tool_calls": [{"name": "read_file"}]}', None),                              # no arguments key: not a call
    ('<tool_call>{"name": "read_file", "arguments": "{\\"path\\": \\"a\\"}"}</tool_call>', [("read_file", {"path": "a"})], None, "massage.leaked_recovered"),   # arguments double-encoded as a string
    ("<tool_call>[1]</tool_call>", [], "<tool_call>[1]</tool_call>", None),
    ('read_file({"path": "a"}) read_file({"path": "b"', [("read_file", {"path": "a"})], ' read_file({"path": "b"', "massage.call_syntax_recovered"),   # the cut second call stays text
    ('read_file({"path": "a", "bogus": 1})', [], 'read_file({"path": "a", "bogus": 1})', None),                                    # a key the tool does not have: not its argument list
    ("read_file([1])", [], "read_file([1])", None), ("read_file({1: 2})", [], "read_file({1: 2})", None), ('nuke({"path": "a"})', [], 'nuke({"path": "a"})', None),
    ("read_file(path=\"a\")", [], "read_file(path=\"a\")", None),                                                                   # Python keyword syntax is not the JSON-object form
    ("<function=read_file><parameter=path>a<parameter=x>b</parameter></function>", [("read_file", {"path": "a", "x": "b"})], None, "massage.leaked_recovered"),
    ("<function=read_file><parameter=path><parameter=q>z</parameter>a</parameter></function>", [("read_file", {"path": "<parameter=q>z</parameter>a", "q": "z"})], None, "massage.leaked_recovered"),   # nested tags keep the outer value
    ("<function=read_file><parameter=path>a</function>", [("read_file", {"path": "a"})], None, "massage.leaked_recovered"),         # never closed: ends at the hard boundary
    ('<|tool_call>call:read_file{path:<|"|>a<|"|> junk}<tool_call|>', [("read_file", {"path": "a"})], None, "massage.leaked_recovered"),
    ('<|tool_call>call:read_file{path:[<|"|>a<|"|>,{x:1},2]}<tool_call|>', [("read_file", {"path": ["a", {"x": 1}, 2]})], None, "massage.leaked_recovered"),
    ('<|tool_call>call:read_file{path:[<|"|>a<|"|> junk]}<tool_call|>', [("read_file", {"path": ["a"]})], None, "massage.leaked_recovered"),   # junk after an element ends the array, not the call
    ("<|tool_call>call:read_file{path:a b c,}<tool_call|>", [("read_file", {"path": "a b c"})], None, "massage.leaked_recovered"),
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
    (LFM2("[read_file(**kw)]"), []),                        # not a literal argument list
    (LFM2("[read_file(path=1+)]"), []), (LFM2('[read_file(path=__import__("os"))]'), []),   # not a literal: never evaluated
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


@pytest.mark.parametrize("reply, args", [
    ('<|tool_call>call:exec_command{cmd:[<|"|>ls<|"|>,<|"|>-l', {"cmd": ["ls", "-l"]}),                    # cut inside an array and its string
    ('<|tool_call>call:read_file{path:<|"|>a<|"|>,start_line:}<tool_call|>', {"path": "a", "start_line": ""}),   # an empty value is an empty string, not a dropped call
    ("<|tool_call>call:read_file{path:a.py,}<tool_call|>", {"path": "a.py"}),
    ("<|tool_call>call:read_file{path:a.py", {"path": "a.py"}),
    ("<|tool_call>call:read_file{path:a.py start_line:3}<tool_call|>", {"path": "a.py start_line:3"}),
    ('<|tool_call>call:read_file{path:{},start_line:[]}<tool_call|>', {"path": {}, "start_line": []}),
    ('<|tool_call>read_file{path:<|"|>a<|"|>}<tool_call|>', {"path": "a"}),                                 # the `call:` prefix is optional
])
def test_gemma_objects_keep_every_argument_that_arrived_intact(reply, args):
    """Truncation and junk inside a Gemma call never drop the call or fabricate a value: what parsed before the break is the argument set."""
    calls, _content, _finish, _events = run(reply)
    assert calls == [("read_file" if "read_file" in reply else "exec_command", args)]


@pytest.mark.parametrize("reply", ["<|tool_call>call:read_file<tool_call|>", "<|tool_call>call:read_file path:a<tool_call|>"])
def test_a_gemma_block_without_an_argument_object_is_not_a_call(reply):
    """No `{`: nothing to parse, so no call is made (and none invented from the name)."""
    assert run(reply)[0] == []


def test_fenced_blocks_bindings_and_whole_file_writes_read_the_reply_as_written():
    """The file-writing-as-text reader: depth-aware fences (a pasted README keeps its inner fences), the binding line above each block, path tokens vs versions/URLs, and the menu's own write tool built from its own schema."""
    from cria import callsyntax
    reply = ("Here is `README.md`:\n```markdown\n# T\n```bash\npip i\n```\n```\n\nNow main.py\n\n```python\nprint(1)\n```\n```js\ncut")
    blocks = callsyntax.fenced_file_blocks(reply)
    assert [(b["lang"], b["closed"], b["binding"]) for b in blocks] == [("markdown", True, "Here is `README.md`:"), ("python", True, "Now main.py"), ("js", False, None)]
    assert blocks[0]["lines"] == ["# T", "```bash", "pip i", "```"] and blocks[1]["lines"] == ["print(1)"]
    assert callsyntax.binding_paths("see `a/b.py`, v1.9.0 at https://x.io/f.txt and c.md") == ["a/b.py"]
    assert callsyntax.binding_paths("edit src/Main.java then Util.java. Also 1.9.0") == ["src/Main.java", "Util.java"]
    assert callsyntax.binding_paths(None) == []
    tool = lambda name, props, req: {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": {p: {"type": t} for p, t in props.items()}, "required": req}}}
    write = tool("write_file", {"path": "string", "content": "string"}, ["path", "content"])
    made = callsyntax.whole_file_write_call([write], "a.py", "x=1\n")
    assert made["id"].startswith("call_") and {k: v for k, v in made.items() if k != "id"} == {"type": "function", "function": {"name": "write_file", "arguments": '{"path": "a.py", "content": "x=1\\n"}'}}
    for refused in (tool("write_file", {"path": "string", "content": "string", "overwrite": "boolean"}, ["path", "content"]),   # extra optional flag
                    tool("write_file", {"path": "string", "content": "string"}, ["path"]),                                       # not exactly two required
                    tool("write_file", {"path": "string", "mode": "string", "content": "string"}, ["path", "mode", "content"]),
                    tool("write_file", {"path": "string", "n": "integer"}, ["path", "n"]),                                       # not both strings
                    tool("write_file", {"path": "string", "file": "string"}, ["path", "file"]),                                  # two path aliases
                    tool("cat", {"path": "string", "content": "string"}, ["path", "content"])):                                  # not a write tool
        assert callsyntax.whole_file_write_call([refused], "a.py", "x") is None
    assert callsyntax.whole_file_write_call(None, "a.py", "x") is None
    assert callsyntax.has_call_envelope('```json\n{"name": "read_file", "arguments": {}}\n```') and not callsyntax.has_call_envelope("```json\n[1]\n```\nprose")
    assert callsyntax.content_text([{"type": "text", "text": "a"}, "junk", {"text": None}, {"text": "b"}]) == "a  b" and callsyntax.content_text(None) == ""
    assert callsyntax.turn_text({"content": "  ", "reasoning_content": " thought "}) == "thought" and callsyntax.turn_text({"content": "x", "reasoning": "r"}) == "x"
    assert callsyntax.turn_text({"content": None, "reasoning": " "}) == "" and callsyntax.turn_text("not a dict") == ""


NO_REQUIRED = [{"type": "function", "function": {"name": n, "parameters": {"type": "object", "properties": {p: {} for p in props}}}}
               for n, props in (("ping", []), ("echo", ["text"]), ("pair", ["a", "b"]))]


@pytest.mark.parametrize("reply, calls", [
    ('{"tool_calls": [{"name": "echo", "arguments": "hi "}]}', [("echo", {"text": "hi"})]),    # no `required`: the schema's ONLY property takes the bare string
    ('{"tool_calls": [{"name": "pair", "arguments": "x"}]}', []),                           # two candidate fields: never guess one
    ('{"tool_calls": [{"name": "ping", "arguments": "x"}]}', []),
    ('echo({"text": "hi"})', [("echo", {"text": "hi"})]),                                    # nothing required: every key must still be a property
    ('ping({})', []),                                                                       # a tool with no properties has no argument list to match
])
def test_call_recovery_against_a_menu_whose_schemas_declare_no_required_fields(reply, calls):
    assert run(reply, menu=NO_REQUIRED)[0] == calls


@pytest.mark.parametrize("body", ["[echo(**kw)]", '[echo(text=__import__("os"))]', "[echo(text=1+)]"])
def test_a_non_literal_argument_is_never_dropped_into_a_call_that_needs_nothing_else(body):
    """With no required field to make the call incomplete, the only thing refusing `echo(text=<expression>)` is the literal-only rule."""
    assert run("", menu=NO_REQUIRED, reasoning_content=LFM2(body))[0] == []
    assert run("", menu=NO_REQUIRED, reasoning_content=LFM2('[echo(text="hi")]'))[0] == [("echo", {"text": "hi"})]
