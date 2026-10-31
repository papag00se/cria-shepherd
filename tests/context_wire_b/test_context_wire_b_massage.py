"""massage: tool calls the model wrote in the wrong place or shape are normalized, never invented, and never forwarded half-written."""
import json

from context_wire_b_helpers import rows, sse
from cria import massage

SHELL = {"type": "function", "function": {"name": "shell", "parameters": {"type": "object", "properties": {"command": {"type": "array"}}}}}
BASH = {"type": "function", "function": {"name": "bash", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}}

def tool(name, *required):
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": {p: {} for p in required}, "required": list(required)}}}

EXEC, MENU = tool("exec_command", "cmd"), [tool("web_search", "query"), tool("exec_command", "cmd")]

def comp(content=None, calls=(), **message):
    msg = {"role": "assistant", "content": content, **message}
    if calls:
        msg["tool_calls"] = [{"id": "c1", "type": "function", "function": {"name": n, "arguments": a if isinstance(a, str) else json.dumps(a)}} for n, a in calls]
    return {"choices": [{"message": msg, "finish_reason": "stop"}]}

calls_of = lambda c: [(t["function"]["name"], json.loads(t["function"]["arguments"])) for t in c["choices"][0]["message"].get("tool_calls") or []]

text_of = lambda c: c["choices"][0]["message"].get("content") or ""

@rows([
    ('Sure.\n<tool_call>{"name": "read_file", "arguments": {"path": "x.py"}}</tool_call>', "read_file", {"path": "x.py"}),
    ('<function=write_file>{"path": "h.py", "content": "x"}</function>', "write_file", {"path": "h.py", "content": "x"}),
    ("<function=read_file><parameter=path>a.py</parameter></function>", "read_file", {"path": "a.py"}),
    ('<function=ls>{"args": "-la"}</function>', "shell", {"args": "-la"}),
    ('<|tool_call>call:write_file{path:<|"|>a}b,c.py<|"|>,opts:{indent:2,force:true},lines:[<|"|>x<|"|>]}<tool_call|> done',
     "write_file", {"path": "a}b,c.py", "opts": {"indent": 2, "force": True}, "lines": ["x"]}),
    ('<|channel>let me think<channel|><|tool_call>call:shell{command:<|"|>ls<|"|>}<tool_call|>', "shell", {"command": "ls"}),
    ('<|tool_call>call:shell{command:<|"|>pytest -q<|"|>,cwd:<|"|>/ho', "shell", {"command": "pytest -q", "cwd": "/ho"})])   # a truncated dialect keeps what was written
def test_a_call_leaked_into_content_becomes_a_real_call_and_leaves_no_debris(content, name, args):
    """Each text dialect (hermes, xml, gemma incl. nested/hostile strings, truncation) is recovered once and stripped from content."""
    out = massage.recover_leaked_tool_calls(comp(content))
    assert calls_of(out) == [(name, args)] and out["choices"][0]["finish_reason"] == "tool_calls" and "tool_call" not in text_of(out) and "<function" not in text_of(out)

@rows([("Step 1.<|tool_call_start|>read_file(path='x.py')<|tool_call_end|>Step 2.", ["Step 1.", "Step 2."], True),
       ("[PLAN]\n{\n \"read_file(path='r.py')]<|tool_call_end|>", ["[PLAN]"], True),
       ("<|channel>thought: I should answer<|message>The answer is 42", ["The answer is 42"], True),
       ('{"plan":"x","commands":[{"name":"web_search","arguments":{"query":"Ada"}}]}', [], [("web_search", {"query": "Ada"})]),   # planner phase A: a JSON envelope was read as 'called no tool'
       ('{"commands":[{"name":"exec_command","arguments":"ls -la"}]}', [], [("exec_command", {"cmd": "ls -la"})]),             # one required field: the bare string can only be that
       ('{"commands":[{"name":"deploy_to_prod","arguments":{"env":"live"}}]}', None, []),                                         # the menu is the guard
       ("I will use web_search to find the docs, then web_fetch the spec.", None, [])])                                           # prose is not an action
def test_sentinel_debris_is_stripped_from_kept_prose_and_a_json_envelope_recovers_only_menu_tools(content, kept, expected):
    """llama.cpp already consumed a well-formed call; what is left is debris and the prose around it survives. Envelope calls are recovered only for tools the request offers."""
    out = massage.recover_leaked_tool_calls(comp(content), MENU)
    assert (expected is True and calls_of(out) == []) or calls_of(out) == expected
    assert all(k in text_of(out) for k in kept or []) and (kept is None or "<|" not in text_of(out))

CUT_PY = '#!/usr/bin/env python3\n"""\nResolver\n\nUsage:\n    resolve goose --total-handles'

@rows([
    ("write_file", {"path": "r.py", "content": CUT_PY}, True),                                         # self-truncated docstring, valid JSON
    ("write_file", {"path": "r.py", "content": 'sep = \'"""\'\nx = 1\n'}, False),                       # odd triple quotes that compile are not truncation
    ("write_file", {"path": "README.md", "content": '"""x'}, False),                                   # no in-process confirmer: no fragile refusal
    ("edit_file", {"path": "a.py", "old_string": "x", "new_string": '"""partial'}, False),             # a partial edit may be mid-string
    ("exec_command", '{"cmd": "python3 -c \\"import json; data=json.load(open(\'<|tool_call_end|>', True),   # Codex: 'failed to parse function arguments' x564
    ("exec_command", {"cmd": "grep -n x f.json"}, False), ("write_file", '{"path":"a.py","content":"def f(', True)])
def test_a_cut_off_call_is_flagged_incomplete_but_a_legitimate_one_is_not(name, args, incomplete):
    """Any tool whose arguments cannot be parsed, or a Python write whose own docstring never closed, is refused like a length truncation."""
    assert massage.has_incomplete_tool_args(comp(calls=[(name, args)])) is incomplete

@rows([('```json\n{"path": "x"}\n```', {"path": "x"}), ('{"a": 1} hope that helps', {"a": 1}),
       ('{"path": "h.py", "content": "def h():\n    return 1\n"}', {"path": "h.py", "content": "def h():\n    return 1\n"}),   # a raw newline inside a string
       ('{"command":["pip\\", \\"install\\", \\"requests\\"],\\"workdir\\":\\".\\"}<tool_call|>I wrote it.<|tool_call>call:shell{',
        {"command": ["pip", "install", "requests"], "workdir": "."})])                                                          # gemma fused a second call onto a valid first
def test_repairable_argument_text_is_repaired_to_exactly_what_was_written(raw, expected):
    assert calls_of(massage.repair_tool_args(comp(calls=[("write_file", raw)])))[0][1] == expected

def test_a_mangled_head_and_a_cut_write_are_left_for_the_refusal_floor_not_guessed():
    """A stray bracket after unescape, or a write cut mid-content, stays malformed: fabricating a command or salvaging a partial file is worse than refusing."""
    out = massage.repair_tool_args(comp(calls=[("shell", '{"command":["pip\\", \\"install\\",\\"w\\"],\\"workdir\\":\\".\\"]}<tool_call|><|channel>thought')]))
    assert "<tool_call|>" in out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    assert massage._recover_write_args(r'{"path":"a.py","content":"d = {\"k\": \"v\"},') is None
    assert massage._recover_write_args('{"path":"a.py","content":"print(\\"hi\\")\nx = \\"q\\"here"}') == {"path": "a.py", "content": 'print("hi")\nx = "q"here'}

def test_replayed_history_args_are_always_valid_json_and_never_lose_text():
    """One malformed historical tool_call 500s a strict template every turn (Fabliq: a python -c f-string ending in \\'). Valid args are untouched; unrecoverable text is preserved as _unparsed."""
    bad = '{"cmd":"cd /repo && python3 -c \\"\\nu = f\'https://x/{handle}\\\'"}'
    junk = '{"cmd":"\\x nonsense \\\' unterminated'
    msgs = [{"role": "assistant", "tool_calls": [{"id": str(i), "type": "function", "function": {"name": "shell", "arguments": a}}]} for i, a in enumerate(['{"cmd": "ls"}', bad, junk])]
    args = [m["tool_calls"][0]["function"]["arguments"] for m in massage.repair_history_tool_args(msgs)]
    assert args[0] == '{"cmd": "ls"}' and all(json.loads(a) is not None for a in args) and json.loads(args[2])["_unparsed"] == junk

@rows([("*** Begin Patch\\n*** Update File: h.py\\n-cafe\\n+café — draft\\n*** End Patch", ["\n", "café", "—"], ["\\n"]),   # double-escaped newlines; non-ASCII must not mojibake
       ("*** Update File: h.py\n+x", ["*** Begin Patch"], []),
       ("--- a/handler.py\n+++ b/handler.py\n@@ -1,2 +1,2 @@\n-old\n+new\n", ["*** Update File: handler.py", "-old", "+new"], ["+++", "@@ -1,2"]),
       ("--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+print('x')\n", ["*** Add File: new.py"], []),
       ("*** Add File: new.py\n context line\n+kept\n- item", ["+- item"], []),                        # a bare '-' in a NEW file is content the model forgot to '+', not a removal
       ("*** Begin Patch\n*** Update File: a.py\n+x\n*** End Patch\n*** Begin Patch\n*** Update File: b.py\n+y\n*** End Patch", ["*** Update File: b.py"], [])])
def test_apply_patch_input_is_normalized_to_the_native_envelope_without_losing_content(patch, has, hasnt):
    out = calls_of(massage.normalize_apply_patch(comp(calls=[("apply_patch", {"input": patch})])))[0][1]["input"]
    assert all(h in out for h in has) and not any(h in out for h in hasnt) and out.count("*** Begin Patch") == 1 and out.rstrip().endswith("*** End Patch")

def test_edit_and_add_file_lower_to_patch_or_write_only_where_the_harness_can_run_it():
    """massage.edit_to_patch fired 0 times in 440,198 events on Codex (it injects edit_file); elsewhere the lowered name does not exist. Passthrough unless apply_patch is offered."""
    edit = lambda: comp(calls=[("edit_file", {"path": "h.py", "old_string": "a\nb", "new_string": "a\nc"})])
    [(name, args)] = calls_of(massage.lower_edit_file(edit(), [tool("apply_patch")]))
    assert name == "apply_patch" and "*** Update File: h.py" in args["input"] and "-b" in args["input"] and "+c" in args["input"]
    assert all(calls_of(massage.lower_edit_file(edit(), t))[0][0] == "edit_file" for t in ([tool("write_file")], [tool("edit_file")]))
    add = comp(calls=[("apply_patch", {"input": "*** Begin Patch\n*** Add File: new.py\n+import os\n+print(1)\n*** End Patch"})])
    assert calls_of(massage.add_file_to_write_file(add)) == [("write_file", {"path": "new.py", "content": "import os\nprint(1)"})]
    assert calls_of(massage.add_file_to_write_file(comp(calls=[("apply_patch", {"input": "*** Begin Patch\n*** Update File: h.py\n-a\n+b\n*** End Patch"})])))[0][0] == "apply_patch"

@rows([("cat", {"path": "h.py"}, [SHELL], "shell", "cat h.py"), ("pytest", {"args": ["-q"]}, [SHELL], "shell", "pytest"),
       ("exec_command", {"cmd": ["bash", "-lc", "pytest"]}, [SHELL], "shell", "pytest"),
       ("shell", {"command": "ls -la"}, [SHELL], "shell", {"command": ["bash", "-lc", "ls -la"]}),
       ("bash", {"command": ["bash", "-lc", "ls -la"]}, [BASH], "bash", {"command": "ls -la"}),
       ("exec_command", {"cmd": ["bash", "-lc", "ls -la"]}, [EXEC], "exec_command", {"cmd": "ls -la"}),    # an array cmd would exec program "["
       ("read_file", {"path": "h.py"}, [SHELL, tool("read_file")], "read_file", {"path": "h.py"})])      # the harness has it: untouched
def test_calls_are_lowered_to_the_shell_the_harness_has_with_the_declared_arg_shape(name, args, tools, expected_name, expected):
    [(got, got_args)] = calls_of(massage.normalize_tool_calls(comp(calls=[(name, args)]), tools))
    assert got == expected_name and (got_args == expected if isinstance(expected, dict) else expected in json.dumps(got_args))

@rows([("EditFile", "ok", "edit_file"), ("edit-file", "ok", "edit_file"), ("Write_File", "ok", "write_file"), ("edit", "ok", "edit"), ("totally_unknown", "ok", "totally_unknown"),
       ("ReadFile", "ambiguous", "ReadFile"), ("EditFile", None, "EditFile")])
def test_a_spelling_variant_folds_to_the_advertised_name_but_a_different_name_or_ambiguity_never_does(called, menu, expected):
    tools = {"ok": [tool("edit_file"), tool("write_file")], "ambiguous": [tool("read_file"), tool("readfile")], None: None}[menu]
    assert calls_of(massage.normalize_tool_names(comp(calls=[(called, {})]), tools))[0][0] == expected

SCHEMAS = {"exec_command": {"type": "object", "properties": {"cmd": {"type": "string"}, "yield_time_ms": {"type": "number"}, "tty": {"type": "boolean"}}}}

@rows([("30000", "yield_time_ms", 30000), ("1.5", "yield_time_ms", 1.5), ("3e4", "yield_time_ms", 30000.0), ("true", "tty", True), ("False", "tty", False),
       ("soon", "yield_time_ms", "soon"), ("30000ms", "yield_time_ms", "30000ms"), ("1,000", "yield_time_ms", "1,000"), ("", "yield_time_ms", ""), ("yes", "tty", "yes"), (500, "yield_time_ms", 500)])
def test_text_recovered_arguments_get_the_declared_type_only_on_an_exact_match(given, key, expected):
    """qwen35 run 1786299798: XML-dialect calls forwarded yield_time_ms as the STRING "30000" and Codex rejected it 148 times, discarding the live-run calls. A wrong cast forges an argument, so only exact matches change; whole numbers stay ints (u64)."""
    got = massage.coerce_args("exec_command", {"cmd": "ls", key: given}, SCHEMAS)[key]
    assert got == expected and type(got) is type(expected)
    assert massage.coerce_args("mystery", {key: given}, SCHEMAS) == {key: given} == massage.coerce_args("exec_command", {key: given}, {})

@rows([({"content": "<|tool_call>call:Gemma4__Try{max_tokens:200}<tool_call|>", "reasoning_content": "Summary: built the handler."}, "built the handler"),
       ({"content": None, "reasoning_content": "The answer is 42.", "tool_calls": [{"id": "c", "type": "function", "function": {"name": "x", "arguments": "{}"}}]}, "The answer is 42."),
       ({"content": '<|tool_call>call:write_file{content:<|"|># How to run<|"|>}<tool_call|>', "reasoning_content": ""}, "# How to run"),
       ({"content": "a real summary"}, "a real summary"), ({"content": ""}, "")])
def test_a_toolless_request_gets_text_back_never_a_spurious_call_or_dialect_blob(message, expect):
    """A gemma4 compaction reasoned out a full summary, then emitted a hallucinated call and lost it: the reasoning (or the call's string payload) is the answer; real text and empty stay as they were. Surviving sentinels are detectable as a leak, prose that mentions a 'call' is not."""
    out = massage.coerce_text_answer({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", **message}}]})
    assert expect in text_of(out) and text_of(out).strip() == text_of(out) and not out["choices"][0]["message"].get("tool_calls") and not massage.has_tool_call_leak(text_of(out))
    assert all(map(massage.has_tool_call_leak, ["<|tool_call>call:X abcd", "done <tool_call|>", "<|tool_call_start|> x"])) and not massage.has_tool_call_leak("The function makes an API call.")

def test_streams_recover_split_leaked_calls_with_distinct_indices_and_hold_back_debris():
    """OpenAI clients reassemble by index, so two recovered calls at index 0 would merge into one corrupt call. Clean text passes; <|channel> debris never streams raw."""
    def run(*deltas):
        out = massage.massage_stream(iter([sse({"role": "assistant"}), *map(sse, deltas), sse({}, "stop"), b"data: [DONE]\n\n"]), "m", tools=None)
        frames = [json.loads(r[5:])["choices"][0]["delta"] for r in out if r.startswith(b"data:") and r[5:].strip() not in (b"", b"[DONE]")]
        return "".join(f.get("content") or "" for f in frames), [c for f in frames for c in f.get("tool_calls") or []]
    assert run({"content": "the answer is 42"}) == ("the answer is 42", [])
    both = ''.join('<tool_call>{"name": "read_file", "arguments": {"path": "%s"}}</tool_call>' % p for p in ("a.py", "b.py"))
    text, found = run({"content": both[:30]}, {"content": both[30:]})
    assert [(c["index"], c["function"]["name"]) for c in found] == [(0, "read_file"), (1, "read_file")] and "<tool_call>" not in text
    assert "<|channel" not in run({"content": "answer <|channel>thinking out loud"})[0]
