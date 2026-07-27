import json
import unittest

from cria import massage

from cria.massage import (
    coerce_text_answer,
    add_file_to_write_file,
    apply,
    has_incomplete_tool_args,
    has_tool_call_leak,
    is_truncated,
    lower_edit_file,
    massage_stream,
    normalize_apply_patch,
    normalize_tool_calls,
    recover_leaked_tool_calls,
    repair_history_tool_args,
    repair_tool_args,
)

_SHELL = {"type": "function", "function": {"name": "shell", "parameters": {"type": "object", "properties": {"command": {"type": "array"}}}}}
_SHELL_STR = {"type": "function", "function": {"name": "bash", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}}


def _completion(content=None, tool_calls=None):
    msg = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg, "finish_reason": "stop"}]}


def _tc(name, arguments):
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": arguments}}


def _first(comp):
    return comp["choices"][0]


class LeakedRecoveryTests(unittest.TestCase):
    def test_hermes_dialect(self):
        c = recover_leaked_tool_calls(_completion(content='Sure.\n<tool_call>{"name": "read_file", "arguments": {"path": "x.py"}}</tool_call>'))
        calls = _first(c)["message"]["tool_calls"]
        self.assertEqual(calls[0]["function"]["name"], "read_file")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"])["path"], "x.py")
        self.assertEqual(_first(c)["finish_reason"], "tool_calls")
        self.assertNotIn("<tool_call>", _first(c)["message"].get("content") or "")

    def test_xml_function_dialect(self):
        c = recover_leaked_tool_calls(_completion(content='<function=write_file>{"path": "h.py", "content": "x"}</function>'))
        calls = _first(c)["message"]["tool_calls"]
        self.assertEqual(calls[0]["function"]["name"], "write_file")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"])["content"], "x")

    def test_xml_parameter_pairs(self):
        c = recover_leaked_tool_calls(_completion(content="<function=read_file><parameter=path>a.py</parameter></function>"))
        self.assertEqual(json.loads(_first(c)["message"]["tool_calls"][0]["function"]["arguments"])["path"], "a.py")

    def test_shell_alias(self):
        c = recover_leaked_tool_calls(_completion(content='<function=ls>{"args": "-la"}</function>'))
        self.assertEqual(_first(c)["message"]["tool_calls"][0]["function"]["name"], "shell")

    def test_does_not_touch_real_tool_calls(self):
        original = _completion(content="<tool_call>{}</tool_call>", tool_calls=[_tc("x", "{}")])
        c = recover_leaked_tool_calls(original)
        self.assertEqual(len(_first(c)["message"]["tool_calls"]), 1)  # unchanged


class IncompleteWriteTests(unittest.TestCase):
    """A write_file with VALID JSON but a self-truncated CONTENT (docstring opened, never closed, no
    code) is a broken file the model cut off mid-string (finish=tool_calls, not length) — the JSON guard
    misses it. It must be refused like a length-truncation, but a legit \"\"\" inside a string must NOT
    false-positive (compile confirms) and non-Python content must fall through (no fragile refusal)."""

    def _c(self, name, content, path="resolve.py"):
        return _completion(tool_calls=[_tc(name, json.dumps({"path": path, "content": content}))])

    def test_truncated_python_docstring_is_refused(self):
        trunc = '#!/usr/bin/env python3\n"""\nResolver\n\nUsage:\n    resolve goose --total-handles'
        self.assertTrue(has_incomplete_tool_args(self._c("write_file", trunc)))

    def test_complete_file_is_allowed(self):
        ok = '"""Resolver."""\nimport sys\n\ndef main():\n    print("hi")\n'
        self.assertFalse(has_incomplete_tool_args(self._c("write_file", ok)))

    def test_legit_triple_quote_inside_a_string_not_false_flagged(self):
        # odd \"\"\" count, but it COMPILES → not a truncation; must be allowed
        self.assertFalse(has_incomplete_tool_args(self._c("write_file", 'sep = \'"""\'\nx = 1\n')))

    def test_non_python_odd_triple_quote_falls_through(self):
        # no in-process confirmer for .md → don't refuse on the count alone (no fragile heuristic)
        self.assertFalse(has_incomplete_tool_args(self._c("write_file", '"""x', path="README.md")))

    def test_edit_file_partial_new_string_not_checked(self):
        c = _completion(tool_calls=[_tc("edit_file",
            json.dumps({"path": "a.py", "old_string": "x", "new_string": '"""partial'}))])
        self.assertFalse(has_incomplete_tool_args(c))  # a partial edit may legitimately be mid-string

    def test_self_truncated_exec_command_is_refused(self):
        # the LIVE footgun: a self-truncated exec_command whose inline python leaked the model's
        # <|tool_call_end|> dialect token mid-string → unparseable args → Codex "failed to parse
        # function arguments" 564x. The guard is now tool-AGNOSTIC, not write-only.
        raw = '{"cmd": "python3 -c \\"import json; data=json.load(open(\'<|tool_call_end|>'
        c = _completion(tool_calls=[_tc("exec_command", raw)])
        self.assertTrue(has_incomplete_tool_args(c))

    def test_valid_exec_command_is_allowed(self):
        c = _completion(tool_calls=[_tc("exec_command", json.dumps({"cmd": "grep -n x f.json"}))])
        self.assertFalse(has_incomplete_tool_args(c))

    def test_malformed_json_still_refused(self):
        c = _completion(tool_calls=[_tc("write_file", '{"path":"a.py","content":"def f(')])  # cut mid-JSON
        self.assertTrue(has_incomplete_tool_args(c))


class ArgRepairTests(unittest.TestCase):
    def test_fenced_json_args(self):
        c = repair_tool_args(_completion(tool_calls=[_tc("write_file", '```json\n{"path": "x"}\n```')]))
        self.assertEqual(json.loads(_first(c)["message"]["tool_calls"][0]["function"]["arguments"]), {"path": "x"})

    def test_valid_args_untouched(self):
        c = repair_tool_args(_completion(tool_calls=[_tc("x", '{"a": 1}')]))
        self.assertEqual(_first(c)["message"]["tool_calls"][0]["function"]["arguments"], '{"a": 1}')

    def test_trailing_prose_args(self):
        c = repair_tool_args(_completion(tool_calls=[_tc("x", '{"a": 1} hope that helps')]))
        self.assertEqual(json.loads(_first(c)["message"]["tool_calls"][0]["function"]["arguments"]), {"a": 1})

    def test_fused_second_call_is_recovered_not_refused(self):
        # gemma fuses a 2nd call (+ commentary) onto a valid first one, over-escaping the array quotes —
        # RECOVER the real first call (a massage, no wasted turn) rather than leaving debris for a refusal.
        # The recovery runs whenever fused debris is present — BEFORE the json.loads short-circuit, because
        # the debris often parses as VALID-but-wrong JSON (swallowed into a string value). Verified live
        # against the real valid-JSON captures 0006 (recovers) / 0011 (→ floor) before locking this in.
        raw = '{"command":["pip\\", \\"install\\", \\"requests\\"],\\"workdir\\":\\".\\"}<tool_call|>I wrote it.<|tool_call>call:shell{'
        c = repair_tool_args(_completion(tool_calls=[_tc("shell", raw)]))
        args = json.loads(_first(c)["message"]["tool_calls"][0]["function"]["arguments"])
        self.assertEqual(args["command"], ["pip", "install", "requests"])   # clean array, no debris left

    def test_genuinely_mangled_head_is_left_for_the_refusal_floor(self):
        # a stray extra bracket (`...]}` → `...]]}`) survives the unescape → not cleanly parseable; leave
        # the debris so the writeproxy refusal floor catches it (better than fabricating a wrong command).
        raw = '{"command":["pip\\", \\"install\\",\\"wheelset\\"],\\"workdir\\":\\".\\"]}<tool_call|><|channel>thought'
        c = repair_tool_args(_completion(tool_calls=[_tc("shell", raw)]))
        out = _first(c)["message"]["tool_calls"][0]["function"]["arguments"]
        self.assertTrue(any(s in out for s in ("<|tool_call>", "<tool_call|>")))  # untouched → floor handles it


class HistoryArgRepairTests(unittest.TestCase):
    """One malformed tool_call in the REPLAYED history 500s a strict template on every turn (observed
    on Fabliq: a `python3 -c` command with `{handle}\\'` — a valid shell/Python escape, forbidden JSON).
    Sanitize the history args before forward so the poison can't brick the session."""

    def _assistant_call(self, args):
        return {"role": "assistant", "tool_calls": [_tc("shell", args)]}

    def test_valid_history_args_untouched(self):
        msgs = [{"role": "user", "content": "hi"}, self._assistant_call('{"cmd": "ls"}')]
        out = repair_history_tool_args(msgs)
        self.assertEqual(out[1]["tool_calls"][0]["function"]["arguments"], '{"cmd": "ls"}')

    def test_malformed_history_call_is_made_valid_json(self):
        # the exact shape from the live 500: an f-string ending in \' inside a python3 -c command.
        bad = '{"cmd":"cd /repo && python3 -c \\"\\nhandle = \'goose\'\\nurl = f\'https://api.handle.me/{handle}\\\'"}'
        with self.assertRaises(json.JSONDecodeError):  # precondition: it really is invalid JSON
            json.loads(bad)
        msgs = [self._assistant_call(bad)]
        out = repair_history_tool_args(msgs)
        fixed = out[0]["tool_calls"][0]["function"]["arguments"]
        json.loads(fixed)  # MUST now parse — else the strict template still 500s

    def test_unrecoverable_is_neutralized_but_preserves_text(self):
        bad = '{"cmd":"\\x nonsense \\\' unterminated'
        out = repair_history_tool_args([self._assistant_call(bad)])
        fixed = out[0]["tool_calls"][0]["function"]["arguments"]
        obj = json.loads(fixed)                       # valid JSON now
        self.assertEqual(obj.get("_unparsed"), bad)   # original text preserved as context

    def test_messages_without_tool_calls_pass_through(self):
        msgs = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}]
        self.assertEqual(repair_history_tool_args(msgs), msgs)


class ApplyPatchTests(unittest.TestCase):
    def test_decodes_double_escaped_newlines(self):
        patch = "*** Begin Patch\\n*** Update File: h.py\\n-a\\n+b\\n*** End Patch"  # literal backslash-n
        c = normalize_apply_patch(_completion(tool_calls=[_tc("apply_patch", json.dumps({"input": patch}))]))
        got = json.loads(_first(c)["message"]["tool_calls"][0]["function"]["arguments"])["input"]
        self.assertIn("\n", got)
        self.assertNotIn("\\n", got)

    def test_double_escaped_patch_preserves_non_ascii(self):
        # The literal-\n decode must be byte-safe: a `unicode_escape` round-trip mojibakes any
        # non-ASCII byte (é → Ã©, em-dash → garbage). Char-level decode leaves them intact.
        patch = "*** Begin Patch\\n*** Update File: h.py\\n-cafe\\n+café — draft\\n*** End Patch"
        c = normalize_apply_patch(_completion(tool_calls=[_tc("apply_patch", json.dumps({"input": patch}))]))
        got = json.loads(_first(c)["message"]["tool_calls"][0]["function"]["arguments"])["input"]
        self.assertIn("\n", got)
        self.assertIn("café", got)  # é preserved (pre-fix: mojibake)
        self.assertIn("—", got)     # em-dash preserved

    def test_adds_envelope(self):
        c = normalize_apply_patch(_completion(tool_calls=[_tc("apply_patch", json.dumps({"input": "*** Update File: h.py\n+x"}))]))
        got = json.loads(_first(c)["message"]["tool_calls"][0]["function"]["arguments"])["input"]
        self.assertTrue(got.startswith("*** Begin Patch"))
        self.assertTrue(got.rstrip().endswith("*** End Patch"))


class GemmaTests(unittest.TestCase):
    def test_gemma_dialect(self):
        content = '<|tool_call>call:read_file{ path:<|"|>src/h.py<|"|> }<tool_call|>'
        c = recover_leaked_tool_calls(_completion(content=content))
        tc = _first(c)["message"]["tool_calls"][0]
        self.assertEqual(tc["function"]["name"], "read_file")
        self.assertEqual(json.loads(tc["function"]["arguments"])["path"], "src/h.py")


class Lfm2SentinelTests(unittest.TestCase):
    def test_wellformed_pair_stripped_prose_kept(self):
        # llama.cpp already recovers the call; the sentinel TEXT must not survive into content.
        c = recover_leaked_tool_calls(_completion(
            content="Step 1.<|tool_call_start|>read_file(path='x.py')<|tool_call_end|>Step 2."))
        out = _first(c)["message"]["content"]
        self.assertNotIn("tool_call_start", out)
        self.assertNotIn("tool_call_end", out)
        self.assertIn("Step 1.", out)
        self.assertIn("Step 2.", out)

    def test_orphan_end_sentinel_stripped(self):
        # the planner-leak shape: a MALFORMED call leaves a stray end token that poisons the plan.
        c = recover_leaked_tool_calls(_completion(
            content="[PLAN]\n{\n  \"read_file(path='r.py')]<|tool_call_end|>"))
        out = _first(c)["message"]["content"]
        self.assertNotIn("tool_call_end", out)
        self.assertIn("[PLAN]", out)


class DeepPatchTests(unittest.TestCase):
    def _norm(self, patch):
        c = normalize_apply_patch(_completion(tool_calls=[_tc("apply_patch", json.dumps({"input": patch}))]))
        return json.loads(_first(c)["message"]["tool_calls"][0]["function"]["arguments"])["input"]

    def test_unified_diff_to_native(self):
        got = self._norm("--- a/handler.py\n+++ b/handler.py\n@@ -1,2 +1,2 @@\n-old\n+new\n")
        self.assertIn("*** Update File: handler.py", got)
        self.assertNotIn("+++", got)
        self.assertNotIn("@@ -1,2", got)  # line numbers dropped
        self.assertIn("-old", got)
        self.assertIn("+new", got)

    def test_add_file_from_dev_null(self):
        got = self._norm("--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+print('x')\n")
        self.assertIn("*** Add File: new.py", got)

    def test_hunk_header_keeps_anchor(self):
        got = self._norm("*** Update File: h.py\n@@ -1,1 +1,1 @@ def foo():\n-a\n+b")
        self.assertIn("@@ def foo():", got)

    def test_add_file_block_forces_plus(self):
        # L13c: in a NEW file a "removal" is impossible, so a bare '-' line is CONTENT the model forgot to
        # '+'-prefix (a YAML list item, a markdown bullet) — it must be KEPT as an addition, not dropped.
        got = self._norm("*** Add File: new.py\n context line\n+kept\n- item")
        lines = [l for l in got.splitlines() if l and not l.startswith("***")]
        self.assertTrue(all(l.startswith("+") for l in lines), got)
        self.assertIn("+- item", got)   # the bare '-' line survives as content (was silently dropped)

    def test_collapses_multiple_wrappers(self):
        got = self._norm("*** Begin Patch\n*** Update File: a.py\n+x\n*** End Patch\n*** Begin Patch\n*** Update File: b.py\n+y\n*** End Patch")
        self.assertEqual(got.count("*** Begin Patch"), 1)
        self.assertEqual(got.count("*** End Patch"), 1)


def _sse(delta):
    return b"data: " + json.dumps({"choices": [{"delta": delta}]}).encode() + b"\n\n"


class StreamMassageTests(unittest.TestCase):
    def _assemble(self, chunks):
        text, calls = "", []
        for raw in chunks:
            if not raw.startswith(b"data:") or raw[5:].strip() in (b"", b"[DONE]"):
                continue
            d = json.loads(raw[5:]).get("choices", [{}])[0].get("delta", {})
            text += d.get("content") or ""
            calls += d.get("tool_calls") or []
        return text, calls

    def test_clean_stream_passes_through(self):
        stream = [_sse({"role": "assistant"}), _sse({"content": "the answer is 42"}), _sse({}), b"data: [DONE]\n\n"]
        text, calls = self._assemble(massage_stream(iter(stream), "m"))
        self.assertEqual(text, "the answer is 42")
        self.assertEqual(calls, [])

    def test_leaked_call_recovered_from_stream(self):
        # a Hermes call leaked as content, split across deltas
        leaked = '<tool_call>{"name": "read_file", "arguments": {"path": "h.py"}}</tool_call>'
        stream = [_sse({"role": "assistant"})] + [_sse({"content": c}) for c in [leaked[:20], leaked[20:]]] + [_sse({}), b"data: [DONE]\n\n"]
        text, calls = self._assemble(massage_stream(iter(stream), "m", tools=None))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "read_file")
        self.assertNotIn("<tool_call>", text)

    def test_gemma_channel_debris_not_streamed_verbatim(self):
        # Gemma's <|channel>thought… leaked into the CONTENT stream must be held back (captured), not
        # streamed raw to the client — the buffered path already strips it; the stream path must too.
        stream = [_sse({"role": "assistant"}), _sse({"content": "answer <|channel>thinking out loud"}),
                  _sse({}), b"data: [DONE]\n\n"]
        text, _calls = self._assemble(massage_stream(iter(stream), "m", tools=None))
        self.assertNotIn("<|channel", text)          # channel debris never reaches the client
        self.assertIn("answer", text)                 # the real content before it still streams

    def test_multiple_leaked_calls_get_distinct_indices(self):
        # two Hermes calls leaked as content: each streamed tool_call delta must carry a
        # DISTINCT index. OpenAI clients reassemble tool_calls BY index — two at index 0
        # merge into one corrupt call (names/ids overwrite, args concatenate to bad JSON).
        leaked = ('<tool_call>{"name": "read_file", "arguments": {"path": "a.py"}}</tool_call>'
                  '<tool_call>{"name": "read_file", "arguments": {"path": "b.py"}}</tool_call>')
        stream = [_sse({"role": "assistant"}), _sse({"content": leaked}), _sse({}), b"data: [DONE]\n\n"]
        _text, calls = self._assemble(massage_stream(iter(stream), "m", tools=None))
        self.assertEqual(len(calls), 2)
        self.assertEqual([c["index"] for c in calls], [0, 1])


class EditFileTests(unittest.TestCase):
    def test_edit_file_becomes_apply_patch(self):
        c = lower_edit_file(_completion(tool_calls=[_tc("edit_file", json.dumps({"path": "h.py", "old_string": "a\nb", "new_string": "a\nc"}))]))
        tc = _first(c)["message"]["tool_calls"][0]
        self.assertEqual(tc["function"]["name"], "apply_patch")
        patch = json.loads(tc["function"]["arguments"])["input"]
        self.assertIn("*** Update File: h.py", patch)
        self.assertIn("-b", patch)
        self.assertIn("+c", patch)

    def test_passthrough_when_harness_has_edit_file(self):
        tools = [{"type": "function", "function": {"name": "edit_file"}}]
        c = lower_edit_file(_completion(tool_calls=[_tc("edit_file", json.dumps({"path": "h.py", "old_string": "a", "new_string": "b"}))]), tools)
        self.assertEqual(_first(c)["message"]["tool_calls"][0]["function"]["name"], "edit_file")  # unchanged


class NormalizeToolCallsTests(unittest.TestCase):
    def test_shell_name_rewrite(self):
        c = normalize_tool_calls(_completion(tool_calls=[_tc("cat", json.dumps({"path": "h.py"}))]), [_SHELL])
        fn = _first(c)["message"]["tool_calls"][0]["function"]
        self.assertEqual(fn["name"], "shell")
        self.assertIn("cat h.py", " ".join(json.loads(fn["arguments"])["command"]))

    def test_read_file_lowered_to_sed(self):
        c = normalize_tool_calls(_completion(tool_calls=[_tc("read_file", json.dumps({"path": "h.py", "start_line": 2, "end_line": 5}))]), [_SHELL])
        fn = _first(c)["message"]["tool_calls"][0]["function"]
        self.assertEqual(fn["name"], "shell")
        self.assertIn("sed -n '2,5p' h.py", " ".join(json.loads(fn["arguments"])["command"]))

    def test_aliased_read_lowers_through_the_guarded_path(self):
        # A read alias (read_file when the harness has no native one, or cat_file/view_file) must lower
        # through the SAME guarded shell read as the synthetic read_file — never a bare cat/sed the
        # harness can silently truncate (that duplicate was the second place the truncation bug lived).
        whole = normalize_tool_calls(_completion(tool_calls=[_tc("read_file", json.dumps({"path": "big.json"}))]), [_SHELL])
        wcmd = " ".join(json.loads(_first(whole)["message"]["tool_calls"][0]["function"]["arguments"])["command"])
        self.assertIn("grep", wcmd)                          # big whole read → grep steer, not a raw cat
        ranged = normalize_tool_calls(_completion(tool_calls=[_tc("read_file", json.dumps(
            {"path": "f.json", "start_line": 9999, "end_line": 9999}))]), [_SHELL])
        rcmd = " ".join(json.loads(_first(ranged)["message"]["tool_calls"][0]["function"]["arguments"])["command"])
        self.assertIn("past the end of the file", rcmd)      # past-EOF signal, not a silent empty

    def test_reshapes_shell_string_to_array(self):
        c = normalize_tool_calls(_completion(tool_calls=[_tc("shell", json.dumps({"command": "ls -la"}))]), [_SHELL])
        self.assertEqual(json.loads(_first(c)["message"]["tool_calls"][0]["function"]["arguments"])["command"], ["bash", "-lc", "ls -la"])

    def test_reshapes_array_to_string(self):
        c = normalize_tool_calls(_completion(tool_calls=[_tc("bash", json.dumps({"command": ["bash", "-lc", "ls -la"]}))]), [_SHELL_STR])
        self.assertEqual(json.loads(_first(c)["message"]["tool_calls"][0]["function"]["arguments"])["command"], "ls -la")

    def test_exec_command_to_shell(self):
        c = normalize_tool_calls(_completion(tool_calls=[_tc("exec_command", json.dumps({"cmd": ["bash", "-lc", "pytest"]}))]), [_SHELL])
        fn = _first(c)["message"]["tool_calls"][0]["function"]
        self.assertEqual(fn["name"], "shell")
        self.assertIn("pytest", " ".join(json.loads(fn["arguments"])["command"]))

    def test_harness_tool_untouched(self):
        tools = [_SHELL, {"type": "function", "function": {"name": "read_file"}}]
        c = normalize_tool_calls(_completion(tool_calls=[_tc("read_file", json.dumps({"path": "h.py"}))]), tools)
        self.assertEqual(_first(c)["message"]["tool_calls"][0]["function"]["name"], "read_file")  # harness has it


class NormalizeToolNamesTests(unittest.TestCase):
    _TOOLS = [_SHELL,
              {"type": "function", "function": {"name": "edit_file"}},
              {"type": "function", "function": {"name": "write_file"}},
              {"type": "function", "function": {"name": "read_file"}}]

    _DEFAULT = object()
    def _name(self, called, tools=_DEFAULT):
        from cria.massage import normalize_tool_names
        use = self._TOOLS if tools is self._DEFAULT else tools
        c = normalize_tool_names(_completion(tool_calls=[_tc(called, "{}")]), use)
        return _first(c)["message"]["tool_calls"][0]["function"]["name"]

    def test_case_and_separator_spellings_fold_to_the_advertised_name(self):
        self.assertEqual(self._name("EditFile"), "edit_file")     # CamelCase (the observed leak)
        self.assertEqual(self._name("edit-file"), "edit_file")    # hyphen
        self.assertEqual(self._name("Write_File"), "write_file")  # mixed case

    def test_already_valid_or_genuinely_different_names_are_untouched(self):
        self.assertEqual(self._name("edit_file"), "edit_file")    # idempotent on a real tool
        self.assertEqual(self._name("edit"), "edit")              # different intent → not folded
        self.assertEqual(self._name("totally_unknown"), "totally_unknown")

    def test_ambiguous_key_is_never_guessed(self):
        amb = [{"type": "function", "function": {"name": "read_file"}},
               {"type": "function", "function": {"name": "readfile"}}]   # share canon key 'readfile'
        self.assertEqual(self._name("ReadFile", amb), "ReadFile")        # refuse to guess

    def test_no_tools_is_a_no_op(self):
        self.assertEqual(self._name("EditFile", None), "EditFile")       # nothing to match against


class TruncationTests(unittest.TestCase):
    def test_detects_length_finish(self):
        self.assertTrue(is_truncated({"choices": [{"finish_reason": "length", "message": {}}]}))
        self.assertFalse(is_truncated({"choices": [{"finish_reason": "stop", "message": {}}]}))


class IncompleteWriteTests(unittest.TestCase):
    """A write_file call the model cut off mid-content must NOT be salvaged into a partial file."""

    def test_recover_refuses_truncated_content(self):
        from cria.massage import _recover_write_args
        cut = r'{"path":"r.py","content":"print(f\"a: {r[\'k'  # unclosed content, invalid \' escape
        self.assertIsNone(_recover_write_args(cut))

    def test_recover_keeps_complete_messy_content(self):
        # A COMPLETE call whose content merely has a raw newline + unescaped quotes is still recovered.
        from cria.massage import _recover_write_args
        messy = '{"path":"a.py","content":"print(\\"hi\\")\nx = \\"q\\"here"}'
        got = _recover_write_args(messy)
        self.assertEqual(got, {"path": "a.py", "content": 'print("hi")\nx = "q"here'})

    def test_recover_refuses_truncation_ending_in_internal_quote_comma(self):
        from cria.massage import _recover_write_args
        cut = r'{"path":"a.py","content":"d = {\"k\": \"v\"},'  # truncated mid-dict-literal
        self.assertIsNone(_recover_write_args(cut))

    def test_structural_scan_rejects_object_ending_in_a_nested_close(self):
        # Ends in `}` but the OUTER object is still open — endswith("}") would be fooled; the
        # brace-depth scan is not. (The reported hole.)
        from cria.massage import _json_structurally_complete
        self.assertFalse(_json_structurally_complete('{"this":{"is": "invalid json"}'))
        self.assertTrue(_json_structurally_complete('{"this":{"is": "valid json"}}'))

    def test_structural_scan_follows_backslash_escapes(self):
        from cria.massage import _json_structurally_complete
        self.assertTrue(_json_structurally_complete(r'{"c":"a \" b \' c"}'))   # escaped quotes stay in-string
        self.assertFalse(_json_structurally_complete(r'{"c":"open \" never closed'))  # cut mid-string

    def test_flags_incomplete_after_repair(self):
        from cria.massage import repair_tool_args, has_incomplete_tool_args
        cut = r'{"path":"r.py","content":"print(f\"a: {r[\'k'
        comp = {"choices": [{"message": {"tool_calls": [
            {"function": {"name": "write_file", "arguments": cut}}]}}]}
        repair_tool_args(comp)                       # recovery refuses → args stay malformed
        self.assertTrue(has_incomplete_tool_args(comp))

    def test_complete_write_not_flagged(self):
        from cria.massage import has_incomplete_tool_args
        comp = {"choices": [{"message": {"tool_calls": [
            {"function": {"name": "write_file", "arguments": '{"path":"a.py","content":"print(1)"}'}}]}}]}
        self.assertFalse(has_incomplete_tool_args(comp))


class AddFileTests(unittest.TestCase):
    def test_pure_add_becomes_write_file(self):
        patch = "*** Begin Patch\n*** Add File: new.py\n+import os\n+print(os.getcwd())\n*** End Patch"
        c = add_file_to_write_file(_completion(tool_calls=[_tc("apply_patch", json.dumps({"input": patch}))]))
        fn = _first(c)["message"]["tool_calls"][0]["function"]
        self.assertEqual(fn["name"], "write_file")
        self.assertEqual(json.loads(fn["arguments"]), {"path": "new.py", "content": "import os\nprint(os.getcwd())"})

    def test_update_patch_left_alone(self):
        patch = "*** Begin Patch\n*** Update File: h.py\n-a\n+b\n*** End Patch"
        c = add_file_to_write_file(_completion(tool_calls=[_tc("apply_patch", json.dumps({"input": patch}))]))
        self.assertEqual(_first(c)["message"]["tool_calls"][0]["function"]["name"], "apply_patch")


class ChannelStripTests(unittest.TestCase):
    def test_strips_gemma_channel(self):
        c = recover_leaked_tool_calls(_completion(content="<|channel>thought: I should answer<|message>The answer is 42"))
        self.assertEqual(_first(c)["message"]["content"], "The answer is 42")


class RawArgsTests(unittest.TestCase):
    def test_recovers_content_with_raw_newlines(self):
        # a write_file whose content has RAW newlines, breaking JSON
        raw = '{"path": "h.py", "content": "def h():\n    return 1\n"}'
        c = repair_tool_args(_completion(tool_calls=[_tc("write_file", raw)]))
        args = json.loads(_first(c)["message"]["tool_calls"][0]["function"]["arguments"])
        self.assertEqual(args["path"], "h.py")
        self.assertIn("def h():", args["content"])


class ApplyTests(unittest.TestCase):
    def test_full_pipeline_recovers_and_repairs(self):
        # a leaked call whose args are also fenced → recover then repair.
        c = apply(_completion(content='<function=write_file>```json\n{"path": "h.py"}\n```</function>'))
        tc = _first(c)["message"]["tool_calls"][0]
        self.assertEqual(tc["function"]["name"], "write_file")
        self.assertEqual(json.loads(tc["function"]["arguments"])["path"], "h.py")


if __name__ == "__main__":
    unittest.main()


class PortFidelityTests(unittest.TestCase):
    """Fidelity fixes vs Codex Local, from the 2026-07 port audit."""

    _EXEC = [{"type": "function", "function": {"name": "exec_command", "parameters": {
        "type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}}}]
    _SHELL = [{"type": "function", "function": {"name": "shell", "parameters": {
        "type": "object", "properties": {"command": {"type": "array"}}}}}]

    def _call(self, name, args):
        return {"choices": [{"message": {"tool_calls": [
            {"id": "c", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}

    def test_exec_command_array_cmd_normalized_to_string(self):
        comp = self._call("exec_command", {"cmd": ["bash", "-lc", "ls -la"]})
        normalize_tool_calls(comp, self._EXEC)
        args = json.loads(comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
        self.assertEqual(args, {"cmd": "ls -la"})  # not left as an array (which execs program "[")

    def test_pytest_as_tool_name_lowered_to_shell(self):
        # `pytest` was outside the truncated 17-name alias table → previously rejected.
        comp = self._call("pytest", {"args": ["-q"]})
        normalize_tool_calls(comp, self._SHELL)
        fn = comp["choices"][0]["message"]["tool_calls"][0]["function"]
        self.assertEqual(fn["name"], "shell")
        self.assertIn("pytest", " ".join(json.loads(fn["arguments"])["command"]))

    def test_update_hunk_bare_line_prefixed(self):
        from cria.massage import _normalize_patch_body
        body = "*** Begin Patch\n*** Update File: a.py\n context\n-old line\nnew bare line\n*** End Patch"
        fixed = _normalize_patch_body(body)
        self.assertIn("+new bare line", fixed)   # bare content line in an Update hunk → addition
        self.assertIn(" context", fixed)          # existing context untouched
        self.assertIn("-old line", fixed)         # existing removal untouched


class GemmaDialectTests(unittest.TestCase):
    """The gemma-fable bespoke tool-call syntax (ported from codex-local): recursive descent,
    NOT regex — nested objects, `<|"|>`-delimited strings that may contain `}`/`,`, bare
    bools/ints, arrays, and truncation tolerance."""

    def test_nested_numbers_bools_arrays_and_hostile_strings(self):
        from cria.massage import _extract_gemma
        c = ('<|tool_call>call:write_file{path:<|"|>a}b,c.py<|"|>,'
             'opts:{indent:2,force:true},lines:[<|"|>x<|"|>,<|"|>y<|"|>]}<tool_call|> done')
        calls, cleaned = _extract_gemma(c)
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertEqual(args, {"path": "a}b,c.py",
                                "opts": {"indent": 2, "force": True}, "lines": ["x", "y"]})
        self.assertEqual(cleaned.strip(), "done")

    def test_truncated_call_recovers_earlier_args(self):
        from cria.massage import _extract_gemma
        calls, _ = _extract_gemma('<|tool_call>call:shell{command:<|"|>pytest -q<|"|>,cwd:<|"|>/ho')
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertEqual(args["command"], "pytest -q")   # earlier arg fully intact
        self.assertEqual(args["cwd"], "/ho")             # truncated remainder still captured

    def test_multiple_calls_and_shell_aliasing(self):
        from cria.massage import _extract_gemma
        c = ('a <|tool_call>call:python{code:<|"|>print(1)<|"|>}<tool_call|> '
             'b <|tool_call>call:read_file{path:<|"|>x.py<|"|>}<tool_call|>')
        calls, _ = _extract_gemma(c)
        self.assertEqual([x["function"]["name"] for x in calls], ["shell", "read_file"])

    def test_end_to_end_recovery_promotes_to_tool_calls(self):
        comp = {"choices": [{"message": {"role": "assistant", "content":
                '<|channel>let me think<channel|><|tool_call>call:shell{command:<|"|>ls<|"|>}<tool_call|>'},
                "finish_reason": "stop"}]}
        out = recover_leaked_tool_calls(comp)
        msg = out["choices"][0]["message"]
        self.assertEqual(msg["tool_calls"][0]["function"]["name"], "shell")
        self.assertFalse((msg.get("content") or "").strip())      # dialect + channel fully stripped
        self.assertEqual(out["choices"][0]["finish_reason"], "tool_calls")

    def test_fable_channel_stripping_including_truncated(self):
        from cria.massage import _strip_channel
        self.assertEqual(_strip_channel("<|channel>thought...<channel|>Answer."), "Answer.")
        self.assertEqual(_strip_channel("Answer. <|channel>cut-off thought"), "Answer.")

    def test_float_stays_string_upstream_quirk(self):
        from cria.massage import _extract_gemma
        calls, _ = _extract_gemma("<|tool_call>call:t{x:1.5,y:2}<tool_call|>")
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertEqual(args, {"x": "1.5", "y": 2})     # i64-only bare parsing, preserved


class CoerceTextAnswerTests(unittest.TestCase):
    """A text-expected call (no tools offered) whose model answered with a TOOL CALL must be
    recovered to text — dialect-agnostic. Motivating incident: a gemma4 compaction reasoned out
    a full summary, then emitted a hallucinated `<|tool_call>call:Gemma4__Try{…}` and lost it."""

    def test_gemma_dialect_answer_recovers_the_reasoning_summary(self):
        comp = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant",
            "content": "<|tool_call>call:Gemma4__Try{max_tokens:200,temperature:0.15}<tool_call|>",
            "reasoning_content": "Summary: built the handler, added tests, migrated the error path."}}]}
        out = coerce_text_answer(apply(comp, None))          # None tools = compaction/reasoner call
        msg = out["choices"][0]["message"]
        self.assertIsNone(msg.get("tool_calls"))
        self.assertIn("built the handler", msg["content"])
        self.assertNotIn("Gemma4__Try", msg["content"])
        self.assertEqual(out["choices"][0]["finish_reason"], "stop")

    def test_native_tool_call_without_text_recovers_reasoning(self):
        # dialect-agnostic: a NATIVE tool_calls answer on a no-tools call is equally spurious
        comp = {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant",
            "content": None, "reasoning_content": "The answer is 42.",
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "whatever", "arguments": "{}"}}]}}]}
        out = coerce_text_answer(apply(comp, None))
        msg = out["choices"][0]["message"]
        self.assertIsNone(msg.get("tool_calls"))
        self.assertEqual(msg["content"], "The answer is 42.")

    def test_real_text_answer_is_untouched(self):
        comp = {"choices": [{"message": {"role": "assistant", "content": "a real summary"}}]}
        out = coerce_text_answer(apply(comp, None))
        self.assertEqual(out["choices"][0]["message"]["content"], "a real summary")

    def test_tool_call_preserved_when_tools_offered(self):
        # with tools available, a tool call IS a valid answer — never coerced
        comp = {"choices": [{"message": {"role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "shell", "arguments": "{}"}}]}}]}
        out = apply(comp, [{"type": "function", "function": {"name": "shell"}}])
        self.assertTrue(out["choices"][0]["message"].get("tool_calls"))

    def test_empty_with_no_reasoning_stays_empty(self):
        comp = {"choices": [{"message": {"role": "assistant", "content": ""}}]}
        out = coerce_text_answer(apply(comp, None))
        self.assertEqual((out["choices"][0]["message"].get("content") or ""), "")


class HasToolCallLeakTests(unittest.TestCase):
    """A summarizer's 'prose' answer that still carries tool-call-dialect debris is a leaked call,
    not a briefing — the summarizer uses this to fail the pass and retry."""

    def test_detects_surviving_dialect_sentinels(self):
        self.assertTrue(has_tool_call_leak("<|tool_call>call:Gemma4__1025 abcd0000 hex"))
        self.assertTrue(has_tool_call_leak("done <tool_call|>"))
        self.assertTrue(has_tool_call_leak('args {<|"|>value<|"|>}'))
        self.assertTrue(has_tool_call_leak("<|tool_call_start|> leftover"))
        self.assertTrue(has_tool_call_leak("<tool_call>{}</tool_call>"))

    def test_clean_prose_and_empty_are_not_leaks(self):
        self.assertFalse(has_tool_call_leak("Built the handler, added tests, migrated the error path."))
        self.assertFalse(has_tool_call_leak(""))
        # a legitimate summary that merely mentions the word 'call' in prose is fine
        self.assertFalse(has_tool_call_leak("The function makes an API call to resolve the handle."))


class JsonEnvelopeToolCallTests(unittest.TestCase):
    """A model that emits tool calls as JSON DATA in `content` instead of in the `tool_calls` field.
    The leaked-call recovery only looked at angle-bracket dialects (`"<" not in content: continue`),
    so a JSON envelope was discarded whole and the turn recorded as "called no tool".

    MEASURED (run 0727-132935, planner phase A): the planner had exec_command/read_file/web_fetch/
    web_search on its menu and answered with the exact OpenAI call shape nested under a `commands`
    key — `{"name": "web_search", "arguments": {"query": "Ada Handles API resolve endpoint"}}` — its
    reasoning ending "Let's start with web_search to verify API details." cria saw no tool call,
    spent its one research nudge, moved to drafting with the 12-round gather untouched, and the plan
    it then produced was handed back TWICE by the grounding checks (ungrounded URL, unread host)
    before being accepted with "Use web_search to find …" as step 1. The model did its job; the
    envelope was the only thing wrong.

    The menu is the guard: a name is recovered only if it is a tool THIS request actually offers, so
    prose that happens to mention a name-shaped word cannot become an action."""

    MENU = [{"type": "function", "function": {"name": n, "parameters": p}} for n, p in (
        ("web_search", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
        ("web_fetch", {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}),
        ("exec_command", {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}),
    )]

    def _completion(self, content):
        return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}

    def _recover(self, content):
        out = massage.recover_leaked_tool_calls(self._completion(content), self.MENU)
        return (out["choices"][0]["message"].get("tool_calls") or [])

    def test_the_real_captured_envelope_becomes_a_real_call(self):
        content = ('\n{\n  "plan": "1. Use web_search to find the Ada Handles API documentation.",\n'
                   '  "commands": [\n    {\n      "name": "web_search",\n'
                   '      "arguments": {\n        "query": "Ada Handles API resolve endpoint handle.me"\n'
                   '      }\n    }\n  ],\n  "output": ""\n}')
        calls = self._recover(content)
        self.assertEqual([c["function"]["name"] for c in calls], ["web_search"])
        self.assertIn("Ada Handles API resolve endpoint", calls[0]["function"]["arguments"])

    def test_a_bare_string_argument_maps_to_the_schema_s_one_required_field(self):
        """The same run's next turn used `"arguments": "ls -la\\n"` and `"arguments":
        "https://api.handle.me/"`. When a tool's schema has exactly ONE required property the string
        can only be that property — read off the schema, not guessed."""
        content = ('{"plan": "look around", "commands": ['
                   '{"name": "exec_command", "arguments": "ls -la\\n"},'
                   '{"name": "web_fetch", "arguments": "https://api.handle.me/"}]}')
        calls = self._recover(content)
        self.assertEqual([c["function"]["name"] for c in calls], ["exec_command", "web_fetch"])
        self.assertIn("ls -la", calls[0]["function"]["arguments"])
        self.assertIn("api.handle.me", calls[1]["function"]["arguments"])

    def test_a_name_that_is_not_on_the_menu_is_not_recovered(self):
        content = '{"commands": [{"name": "deploy_to_prod", "arguments": {"env": "live"}}]}'
        self.assertEqual([], self._recover(content))

    def test_prose_describing_a_tool_is_not_turned_into_an_action(self):
        content = "I will use web_search to find the docs, then web_fetch the spec."
        self.assertEqual([], self._recover(content))

    def test_a_real_tool_call_is_never_second_guessed(self):
        comp = {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant",
                "content": '{"commands": [{"name": "web_search", "arguments": {"query": "x"}}]}',
                "tool_calls": [{"id": "1", "type": "function",
                                "function": {"name": "web_fetch", "arguments": '{"url": "https://real"}'}}]}}]}
        out = massage.recover_leaked_tool_calls(comp, self.MENU)
        names = [c["function"]["name"] for c in out["choices"][0]["message"]["tool_calls"]]
        self.assertEqual(names, ["web_fetch"])
