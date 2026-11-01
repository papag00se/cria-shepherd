"""A call left in reasoning_content is recovered only when the model clearly emitted it; jsontext tolerates model-shaped JSON."""
import json

import pytest

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
    "<|tool_call>call:read_file{path:<|\"|>a.py<|\"|>}<tool_call|>",                                                  # gemma salvage must not become a reasoning reader
    # a JSON body cut inside its OWN object: the complete object nested in it is a fragment, not the arguments (fuzz, wave 12)
    '<function=list_dir>{"path": ".", "env": {"A": "1"}, "timeout": </function>',
    '<tool_call>{"name": "list_dir", "arguments": "{\\"path\\": \\".\\", \\"env\\": {\\"A\\": 1}, \\"t\\": "}</tool_call>'])
def test_what_the_model_did_not_clearly_emit_is_never_taken_as_an_action(reasoning):
    """Each refusal stays as broken as before (the loop, not this, speaks about it): nothing is executed, evaluated or half-forwarded."""
    out = recover(reasoning)
    assert calls(out) == [] and out["choices"][0]["finish_reason"] == "stop"
    content = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": reasoning}}]}
    if reasoning.startswith("<function=list_dir>"):   # the same body in CONTENT is not promoted either
        assert calls(massage.recover_leaked_tool_calls(content, MENU, Rlog())) == []

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


@pytest.mark.parametrize("raw,expected", [
    ('{"done": false, "reason": "x"', {"done": False, "reason": "x"}),                                    # run 20260728T000013 call 0469-critic: one absent }
    ('{"a": [1, {"b": 2', {"a": [1, {"b": 2}]}),                                                          # closers come back in the nesting order the text opened
    ('{"a": "has } and \\" and ] in it", "b": [', {"a": 'has } and " and ] in it', "b": []}),             # brackets and an escaped quote inside a string open nothing
    ('Sure, here: {"a": 1', {"a": 1}), ('{ not json {"a": 1', {"a": 1}),                                 # the first `{` that repairs wins
    ('{"a": "unfinished', None), ('{"a": ', None), ('{"a": 1,', None), ('{"a": [1}', None),            # ends mid-string / needs a value / needs a comma removed / mismatched: authoring, refused
    ('{"a": 1}', None), ('[1, 2', None), ('', None),                                                      # complete (extract's job) / not an object / empty
])
def test_an_object_missing_only_its_closing_braces_is_closed_and_nothing_else_is_ever_supplied(raw, expected):
    """close_unclosed_object supplies closers and nothing else: no half-written string is closed, no value or comma is invented."""
    assert jsontext.close_unclosed_object(raw) == expected


def test_a_cut_write_with_thousands_of_unclosed_braces_is_read_in_linear_time_and_left_as_written():
    """A real cut write_file (157,000 chars, 705 braces, 28 unclosed) stalled the repair for 6.5 s: every `{` was its own scan to the end of the text, so
    a 60,000-character cut file took ~25 s and a larger one minutes, in the response path. Now one pass answers every brace; the cut text stays as written."""
    import time
    raw = '{"content":"' + '{\\n    foo(\\"a\\");\\n' * 3000      # a code file written as escaped text, never closed
    started = time.perf_counter()
    out = massage.repair_tool_args({"choices": [{"message": {"tool_calls": [{"id": "c", "type": "function", "function": {"name": "write_file", "arguments": raw}}]}}]}, Rlog())
    assert out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == raw
    assert time.perf_counter() - started < 3
    assert jsontext.extract_json_object("{" * 20000 + '"') is None
    assert jsontext.extract_json_object('{"a":"' + "\\" * 50000) is None and time.perf_counter() - started < 3   # a run of backslashes, the escape scan's own worst case
    assert jsontext.close_unclosed_object('{ "a": ' + "{ " * 20000) == {}      # only the innermost brace is repairable by closers alone


def test_thousands_of_nested_unclosed_objects_are_read_in_linear_time_and_left_as_written():
    """`{"a":` x 3,000 re-parsed the same tail once per opener (3.5 s, in the response path); an opener nested in a candidate that already failed
    where that opener's own candidate must fail is not parsed again."""
    import time
    started = time.perf_counter()
    for n in (3000, 9000):
        text = '{"a":' * n
        assert jsontext.extract_json_object(text) is None and jsontext.close_unclosed_object(text) is None
    # the first COMPLETE object is the answer; an unclosed outer candidate never promotes a nested one
    assert jsontext.extract_json_object('{"a":' * 3000 + '{"ok":1}') is None
    assert jsontext.extract_json_object('{"a":' * 3000 + '1} {"ok":1}') == {"a": 1}
    assert time.perf_counter() - started < 3
    # an outer candidate that fails on something other than a dangling key still lets the repairable inner one through
    deep = {"z": 1}
    for _ in range(50):
        deep = {"a": [deep]}
    assert jsontext.close_unclosed_object('{"a":[' * 50 + '{"z":1') == deep


def test_skipping_openers_inside_a_failed_candidate_finds_exactly_the_objects_a_parse_per_opener_finds(monkeypatch):
    """Over random brace/key/array/fence soup (and a cut of each) the objects and spans, repairable ones included, equal those with the skip disabled."""
    import random
    rng = random.Random(23)
    tokens = ['{', '{"a":', '{"a":1', '}', '[', ']', '"', '\\', ':', ',', ' ', '\n', '1', '"k":', '"s"', '```', '```json', '{"a":1}', '[1,{"b":2}', 'x', '{"a":[', '<think>', '</think>']
    texts = []
    for _ in range(3000):
        text = "".join(rng.choice(tokens) for _ in range(rng.randint(0, 24)))
        texts += [text, text[:rng.randint(0, len(text))]]
    fast = [(list(jsontext._json_objects(t, include_repairable=True)), list(jsontext._json_objects(t)), jsontext.extract_json_object(t), jsontext.close_unclosed_object(t)) for t in texts]
    monkeypatch.setattr(jsontext._Scan, "nested_hopeless", lambda self, start, fail: [])
    jsontext._scan.cache_clear()
    slow = [(list(jsontext._json_objects(t, include_repairable=True)), list(jsontext._json_objects(t)), jsontext.extract_json_object(t), jsontext.close_unclosed_object(t)) for t in texts]
    assert fast == slow


def test_the_memoized_brace_scan_answers_exactly_what_one_scan_per_brace_answers():
    """_Scan shares one pass between every `{` that reads the text the same way; for every `{` of random brace/quote/escape/fence soup (and a cut of each)
    it must equal the one-scan definitions."""
    import random
    rng = random.Random(11)
    tokens = ['{', '}', '[', ']', '"', '\\', '\\"', ':', ',', ' ', '\n', 'a', '```', '```json', '{"a":1}', '{"a":[1,{"b":2}]}', '"x"', '\\\\', '{}', '[]']
    for _ in range(4000):
        text = "".join(rng.choice(tokens) for _ in range(rng.randint(0, 40)))
        for s in (text, text[:rng.randint(0, len(text))]):
            for i, c in enumerate(s):
                if c == "{":
                    assert jsontext._balanced_object(s, i) == jsontext._balanced_object_from(s, i), (s, i)
                    assert jsontext._unclosed_tail(s, i) == jsontext._unclosed_tail_from(s, i), (s, i)


def _params_one_scan_per_opener(body):
    """The definition of callsyntax._bounded_xml_params: each opener searches the rest of the body for its own balancing closer."""
    from cria import callsyntax as cs
    out = []
    for m in cs._PARAM_OPEN.finditer(body):
        name, start = m.group(1), m.end()
        depth, i, end = 1, start, None
        while i < len(body):
            nxt_open, nxt_close = cs._PARAM_OPEN.search(body, i), body.find(cs._PARAM_CLOSE, i)
            if nxt_close == -1:
                break
            if nxt_open and nxt_open.start() < nxt_close:
                depth, i = depth + 1, nxt_open.end()
                continue
            depth -= 1
            if depth == 0:
                end = nxt_close
                break
            i = nxt_close + len(cs._PARAM_CLOSE)
        if end is None:
            end = len(body)
            sib = cs._PARAM_OPEN.search(body, start)
            if sib:
                end = min(end, sib.start())
            for tag in cs._PARAM_HARD_BOUNDARIES:
                j = body.find(tag, start)
                if j != -1:
                    end = min(end, j)
        out.append((name, body[start:end]))
    return out


def test_thousands_of_stacked_parameter_openers_are_paired_in_one_pass_exactly_as_one_scan_per_opener_would():
    """3,000 `<parameter=…>` openers (a repetition loop) cost 15 s: every opener re-searched the rest of the body. One pass now; same pairing on random tag soup."""
    import random
    import time
    from cria import callsyntax
    started = time.perf_counter()
    pairs = callsyntax._bounded_xml_params("<parameter=a>" * 3000 + "</parameter>")
    assert len(pairs) == 3000 and pairs[-1] == ("a", "") and time.perf_counter() - started < 2
    rng = random.Random(5)
    tokens = ["<parameter=a>", "<parameter=b>", "</parameter>", "</function>", "</tool_call>", "x", "\n", "<parameter=c> ", "text ", "<function=f>"]
    for _ in range(3000):
        body = "".join(rng.choice(tokens) for _ in range(rng.randint(0, 14)))
        assert callsyntax._bounded_xml_params(body) == _params_one_scan_per_opener(body), body
