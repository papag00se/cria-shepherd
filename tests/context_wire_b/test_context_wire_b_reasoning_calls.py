"""A call left in reasoning_content is recovered only when the model clearly emitted it; jsontext tolerates model-shaped JSON."""
import json

from context_wire_b_helpers import Rlog, rows
from cria import jsontext, massage

def tool(name, props, required):
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": {p: {} for p in props}, "required": required}}}

MENU = [tool("read_file", ["path"], ["path"]), tool("write_file", ["path", "content"], ["path", "content"]), tool("edit_file", ["path", "old_string", "new_string"], ["path"]),
        tool("web_fetch", ["url", "find", "raw"], ["url"]), tool("web_search", ["query"], ["query"]), tool("exec_command", ["cmd"], ["cmd"]), tool("list_dir", ["path"], [])]
LFM = "<|tool_call_start|>[%s]<|tool_call_end|>"
XML = lambda name, **kv: "<tool_call>\n<function=%s>\n%s</function>\n</tool_call>" % (name, "".join("<parameter=%s>\n%s\n</parameter>\n" % item for item in kv.items()))
BODY = "import sys\n\ndef f():\n    return 'it\\'s fine'\n"
RM = LFM % "exec_command(cmd='rm -rf /w')"

def recover(reasoning, menu=MENU, **msg):
    return massage.recover_reasoning_tool_calls({"choices": [{"finish_reason": msg.pop("finish", "stop"), "message": {"role": "assistant", "content": None, "reasoning_content": reasoning, **msg}}]}, menu, Rlog())

calls = lambda comp: [(t["function"]["name"], json.loads(t["function"]["arguments"])) for t in comp["choices"][0]["message"].get("tool_calls") or []]

@rows([
    ("I should read it.\n" + LFM % "read_file(path='./spec.json')", [("read_file", {"path": "./spec.json"})]),
    ('<tool_call>\n{"name": "web_search", "arguments": {"query": "Ada"}}\n</tool_call>', [("web_search", {"query": "Ada"})]),
    (XML("exec_command", cmd="ls -la"), [("exec_command", {"cmd": "ls -la"})]),
    (LFM % "web_fetch(url='https://a.b/s.yml', find='GET /h/{handle}', raw=True)", [("web_fetch", {"url": "https://a.b/s.yml", "find": "GET /h/{handle}", "raw": True})]),
    (LFM % ("write_file(path='./a.py', content=%r)" % BODY), [("write_file", {"path": "./a.py", "content": BODY})]),             # a whole file byte for byte
    (LFM % "write_file(path='./a.py', content='')", [("write_file", {"path": "./a.py", "content": ""})]),                        # intentionally empty is a value
    (RM + "\nBut that destroys files. Let me list instead.\n" + LFM % "list_dir(path='.')", [("list_dir", {"path": "."})]),      # a revised plan: the last emission wins
    (LFM % "list_dir(path='.'), read_file(path='a')", [("list_dir", {"path": "."}), ("read_file", {"path": "a"})]),
    (XML("read_file", path="a.py") + "\n" + XML("read_file", path="b.py"), [("read_file", {"path": "a.py"}), ("read_file", {"path": "b.py"})]),   # back-to-back calls are one batch (10 calls lost to single re-asks)
    (LFM % "read_file(path=('a', 'b'))", [("read_file", {"path": ["a", "b"]})]),
    # an explicit JSON {} is parsed evidence of an empty argument object, not a missing body (ba1687a4: `if args:` dropped it)
    ("Inspect the workspace.\n<function=list_dir>{}</function>", [("list_dir", {})]),
    # XML parameter tags are the arguments even when the payload holds an object literal (qwen35 shipping-rates-py: scored 0/4 having touched nothing)
    (XML("edit_file", path="r.py", old_string='K = {"d": 0.75}', new_string='K = {"d": 0.75, "x": 2.5}'), [("edit_file", {"path": "r.py", "old_string": 'K = {"d": 0.75}', "new_string": 'K = {"d": 0.75, "x": 2.5}'})])])
def test_a_complete_emitted_call_in_reasoning_becomes_a_real_call_with_the_reasoning_untouched(reasoning, expected):
    """Measured over 127 sessions: 80 replies came back with no call, no text, and a dialect in reasoning; 68 recoverable. Recovery is additive: reasoning is never edited and finish becomes tool_calls."""
    out = recover(reasoning)
    assert calls(out) == expected and out["choices"][0]["finish_reason"] == "tool_calls" and out["choices"][0]["message"]["reasoning_content"] == reasoning

@rows([
    RM + "\nBut that would destroy the user's files. Instead I should look.",                                           # reasoned past: a consideration, not an emission
    "For reference:\n\n```\n" + RM + "\n```", "I propose:\n```\n" + XML("read_file", path="/tmp/x"),                      # fenced illustrations, closed or unclosed
    "Let's produce the content:\n\nimport requests\n</parameter>\n</function>\n</tool_call>\n",                          # closing tags with no opening half
    "Let me read it.\n<|tool_call_start|>[read_file(path='./tmp/reference/api.handle", "<|tool_call_start|>[list_dir(path='.')]",   # cut mid-argument / no closing sentinel
    LFM % "list_dir(path='.'), delete_everything(confirm=True)",                                                         # one off-menu call refuses the whole list
    LFM % "write_file(path='./a.py', content=None)", LFM % "write_file(path='./a.py')", LFM % "web_fetch(find='h')",     # a required field missing or null
    LFM % "read_file('./spec.json')", LFM % "read_file(path='a' + 'b')", LFM % "read_file(path=os.getcwd())",            # positional / expression: never placed by guess or evaluated
    LFM % "read_file(path=b'x')", LFM % "read_file(path={'a', 'b'})", LFM % "read_file(path=1+2j)",                      # literal_eval accepts what the wire cannot carry
    "I should use read_file on ./spec.json, or maybe web_fetch(url) would be better.",                                  # naming a tool is not calling it
    "<|tool_call>call:read_file{path:<|\"|>a.py<|\"|>}<tool_call|>"])                                                   # gemma salvage must not become a reasoning reader
def test_what_the_model_did_not_clearly_emit_is_never_taken_as_an_action(reasoning):
    """Each refusal stays as broken as before (the loop, not this, speaks about it): nothing is executed, evaluated or half-forwarded."""
    out = recover(reasoning)
    assert calls(out) == [] and out["choices"][0]["finish_reason"] == "stop"

def test_recovery_is_gated_by_the_turn_the_menu_and_prior_recovery():
    """Only a lost turn (no text, in any content shape) on a request that advertises the tool recovers; a call the server already surfaced is not doubled; replays and finish=length change nothing; an off-menu attempt is spoken as a hint, not swallowed; content wins over reasoning; sentinels in content are stripped, not parsed."""
    call = LFM % "read_file(path='a')"
    assert all(calls(recover(call, content=c)) == [] for c in ("I finished the step.", [{"type": "text", "text": "I finished."}]))
    assert all(calls(recover(call, content=c)) == [("read_file", {"path": "a"})] for c in ([], [{"type": "image_url", "image_url": {"url": "x"}}], [{"type": "text", "text": "  "}], None))
    assert all(calls(recover(call, menu)) == [] for menu in (None, [], [tool("submit_plan", ["plan"], ["plan"])]))
    native = [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "native"}'}}]
    assert recover(call, tool_calls=native)["choices"][0]["message"]["tool_calls"] == native
    once = recover(call)
    assert calls(massage.recover_reasoning_tool_calls(json.loads(json.dumps(once)), MENU, Rlog())) == calls(once)
    assert calls(recover(call, finish="length")) == [] and recover(call, finish="length")["choices"][0]["finish_reason"] == "length"
    lost = recover("I should look.\n" + XML("str_replace_editor", path="app.py"), [tool("read_file", ["path"], ["path"])])
    assert "str_replace_editor" in lost[massage.LOST_CALL_KEY]["tried"] and "read_file" in lost[massage.LOST_CALL_KEY]["menu"] and not calls(lost)
    assert massage.LOST_CALL_KEY not in recover("just thinking out loud") and massage.LOST_CALL_KEY not in once
    content = '<tool_call>{"name": "list_dir", "arguments": {"path": "."}}</tool_call>'
    assert calls(massage.recover_leaked_tool_calls(recover(call, content=content), MENU, Rlog())) == [("list_dir", {"path": "."})]
    stripped = massage.recover_leaked_tool_calls({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "Done." + LFM % "list_dir(path='.')"}}]}, MENU, Rlog())
    assert calls(stripped) == [] and stripped["choices"][0]["message"]["content"] == "Done."
    typed = [{"type": "function", "function": {"name": "exec_command", "parameters": {"type": "object", "required": ["cmd"], "properties": {"cmd": {"type": "string"}, "yield_time_ms": {"type": "number"}}}}}]
    assert calls(recover(XML("exec_command", cmd="ls", yield_time_ms="30000"), typed)) == [("exec_command", {"cmd": "ls", "yield_time_ms": 30000})]   # XML has no types; the schema does (Codex rejected "30000" 148 times)

def test_a_nested_example_never_displaces_the_call_that_encloses_it_and_nothing_is_evaluated(tmp_path):
    """v1 turned an XML write_file whose content showed a hermes example into a live `exec_command(rm -rf /)`: the enclosing span is the call, the example is payload. Argument expressions are never executed."""
    nested = XML("write_file", path="notes.md", content='Dialect: <tool_call>{"name": "exec_command", "arguments": {"cmd": "rm -rf /"}}</tool_call>')
    assert [n for n, _ in calls(recover(nested))] == ["write_file"]
    [(name, args)] = calls(recover(LFM % "write_file(path='n.md', content='ex: <function=exec_command>\\n<parameter=cmd>\\nrm -rf /\\n</parameter>\\n</function>')"))
    assert name == "write_file" and "rm -rf /" in args["content"]
    recover(LFM % ("read_file(path=__import__('pathlib').Path(%r).write_text('x'))" % str(tmp_path / "canary")))
    assert not (tmp_path / "canary").exists()

@rows([('{"a": 1}', {"a": 1}), ('Here:\n```json\n{"engagement": "task"}\n```\n', {"engagement": "task"}),
       ('<thinking>maybe {"engagement":"question"} but no</thinking>\n{"engagement":"task"}', {"engagement": "task"}),   # <thinking>, not just <think>: the reasoning's object was returned
       ('<think>deciding\n{"engagement": "task"}', {"engagement": "task"}), ('<think>hmm\n```json\n{"t": "coding"}\n```', {"t": "coding"}),
       ('{"x": 1} and then some explanation', {"x": 1}), ('{"reason": "use the {handle} field"}', {"reason": "use the {handle} field"}),
       ('{ not json } trailing {"ok": true}', {"ok": True}), ("<think>reasoning with { a brace", None), ("no json here", None), ("", None),
       ('{"steps":["real","plan"],"steps":[1,2]}', {"steps": ["real", "plan"]}),                                          # first real value wins, not the degenerate echo
       ('{"done": false, "reason": "r", "done": true}', {"done": False, "reason": "r"}),                                  # a critic that says both has not decided; false is a value, not nothing-said
       ('{"missing":[],"missing":["the tests"]}', {"missing": ["the tests"]}),
       # 6a5f57e2: a complete PRIVATE object before a real OUTSIDE closing frame is discarded with the reasoning (any case/spacing/tag)
       ('{"done": true, "reason": "quotes </think> as data"}</think>{"done": false, "reason": "answer"}', {"done": False, "reason": "answer"}),
       ('{"done": true}</THINK >{"done": false}', {"done": False}), ('{"done": true}<thinking>x</thinking>{"done": false}', {"done": False})])                                          # an empty first value never shadows a real one
def test_model_shaped_json_is_extracted_tolerantly_and_the_first_real_duplicate_wins(raw, expected):
    assert jsontext.extract_json_object(raw) == expected
