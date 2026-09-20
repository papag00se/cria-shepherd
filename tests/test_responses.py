import json
import unittest

from cria import responses


class ToChatBodyTests(unittest.TestCase):
    def test_instructions_and_developer_merge_into_one_system(self):
        r = {
            "model": "m",
            "instructions": "You are a coding agent.",
            "input": [
                {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "sandbox rules"}]},
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "env context"}]},
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "do the thing"}]},
            ],
        }
        body = responses.to_chat_body(r)
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles, ["system", "user", "user"])  # exactly ONE system, merged
        self.assertIn("You are a coding agent.", body["messages"][0]["content"])
        self.assertIn("sandbox rules", body["messages"][0]["content"])
        self.assertEqual(body["messages"][2]["content"], "do the thing")
        self.assertTrue(body["stream"] is False)

    def test_tools_flat_to_nested(self):
        r = {"model": "m", "input": [], "tools": [
            {"type": "function", "name": "exec_command", "description": "run", "parameters": {"type": "object"}},
            {"type": "web_search"},  # non-function → skipped
        ]}
        body = responses.to_chat_body(r)
        self.assertEqual(len(body["tools"]), 1)
        self.assertEqual(body["tools"][0], {"type": "function", "function": {
            "name": "exec_command", "description": "run", "parameters": {"type": "object"}}})

    def test_function_call_and_output_roundtrip(self):
        r = {"model": "m", "input": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "go"}]},
            {"type": "function_call", "call_id": "call_9", "name": "shell", "arguments": '{"command":["ls"]}'},
            {"type": "function_call_output", "call_id": "call_9", "output": "file1\nfile2"},
        ]}
        body = responses.to_chat_body(r)
        m = body["messages"]
        self.assertEqual(m[0]["role"], "user")
        self.assertEqual(m[1]["role"], "assistant")
        self.assertEqual(m[1]["tool_calls"][0]["id"], "call_9")
        self.assertEqual(m[1]["tool_calls"][0]["function"]["name"], "shell")
        self.assertEqual(m[2], {"role": "tool", "tool_call_id": "call_9", "content": "file1\nfile2"})

    def test_string_input_and_dict_args(self):
        r = {"model": "m", "input": [
            {"type": "function_call", "id": "c1", "name": "f", "arguments": {"a": 1}},
        ]}
        body = responses.to_chat_body(r)
        self.assertEqual(json.loads(body["messages"][0]["tool_calls"][0]["function"]["arguments"]), {"a": 1})

    def test_tool_choice_object_form_is_nested(self):
        r = {"model": "m", "input": [], "tools": [
            {"type": "function", "name": "f", "parameters": {"type": "object"}}],
            "tool_choice": {"type": "function", "name": "f"}}
        body = responses.to_chat_body(r)
        self.assertEqual(body["tool_choice"], {"type": "function", "function": {"name": "f"}})

    def test_tool_choice_string_passes_through_object_unknown_dropped(self):
        self.assertEqual(responses.to_chat_body({"model": "m", "input": [], "tool_choice": "required"})["tool_choice"], "required")
        # an unrecognized object form (mcp/allowed_tools) is omitted, not sent as garbage
        self.assertNotIn("tool_choice", responses.to_chat_body({"model": "m", "input": [], "tool_choice": {"type": "mcp"}}))

    def test_tool_with_no_parameters_gets_default_object_and_strict_carried(self):
        r = {"model": "m", "input": [], "tools": [
            {"type": "function", "name": "f", "strict": True}]}
        fn = responses.to_chat_body(r)["tools"][0]["function"]
        self.assertEqual(fn["parameters"], {"type": "object", "properties": {}})
        self.assertIs(fn["strict"], True)

    def test_behavior_controls_are_mapped_not_silently_lost(self):
        body = responses.to_chat_body({"model": "m", "input": [], "max_output_tokens": 123,
                                       "temperature": 0.2, "top_p": 0.9, "stop": ["END"],
                                       "reasoning": {"effort": "medium"}})
        self.assertEqual(body["max_tokens"], 123)
        self.assertEqual(body["temperature"], 0.2)
        self.assertEqual(body["top_p"], 0.9)
        self.assertEqual(body["stop"], ["END"])
        self.assertEqual(body["reasoning_effort"], "medium")

    def test_function_call_output_without_id_is_dropped_not_null_paired(self):
        r = {"model": "m", "input": [
            {"type": "function_call_output", "output": "orphaned"}]}  # no call_id/id
        msgs = responses.to_chat_body(r)["messages"]
        self.assertFalse(any(m.get("role") == "tool" for m in msgs))  # no null-id tool message


def _sse_events(chunks) -> list[dict]:
    out = []
    for raw in chunks:
        for line in raw.decode().splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


class ToResponsesSseTests(unittest.TestCase):
    def test_text_completion_events(self):
        comp = {"choices": [{"message": {"role": "assistant", "content": "hello world"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
        events = _sse_events(responses.to_responses_sse(comp, "m"))
        types = [e["type"] for e in events]
        self.assertEqual(types[0], "response.created")
        self.assertIn("response.output_text.delta", types)
        self.assertEqual(types[-1], "response.completed")
        delta = next(e for e in events if e["type"] == "response.output_text.delta")
        self.assertEqual(delta["delta"], "hello world")
        completed = events[-1]["response"]
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["output"][0]["content"][0]["text"], "hello world")
        self.assertEqual(completed["usage"], {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7})

    def test_tool_call_becomes_function_call_item(self):
        comp = {"choices": [{"message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "call_1", "type": "function",
                                "function": {"name": "shell", "arguments": '{"command":["ls"]}'}}]}}]}
        events = _sse_events(responses.to_responses_sse(comp, "m"))
        types = [e["type"] for e in events]
        self.assertIn("response.function_call_arguments.delta", types)
        done = next(e for e in events if e["type"] == "response.output_item.done")
        self.assertEqual(done["item"]["type"], "function_call")
        self.assertEqual(done["item"]["name"], "shell")
        self.assertEqual(done["item"]["call_id"], "call_1")
        self.assertEqual(json.loads(done["item"]["arguments"]), {"command": ["ls"]})

    def test_created_can_be_split_from_body(self):
        comp = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
        created = responses.created_event("resp_x", "m")
        self.assertIn(b"response.created", created)
        body = list(responses.body_events(comp, "resp_x", "m"))
        self.assertTrue(any(b"response.completed" in c for c in body))
        # the response id is threaded through
        self.assertIn("resp_x", json.loads(body[-1].decode().split("data: ", 1)[1])["response"]["id"])

    def test_banner_folds_into_the_content_item(self):
        # The banner rides INSIDE the content item — never its own message item, which the
        # harness would store and re-summarize (it once became an entire compaction summary).
        comp = {"choices": [{"message": {"role": "assistant", "content": "the answer"}}]}
        events = _sse_events(responses.to_responses_sse(comp, "m", banner="⟦cria⟧ coder · fabliq"))
        out = events[-1]["response"]["output"]
        msg_items = [o for o in out if o.get("type") == "message"]
        self.assertEqual(len(msg_items), 1)  # ONE item, not banner + content
        self.assertEqual(msg_items[0]["content"][0]["text"], "⟦cria⟧ coder · fabliq\nthe answer")

    def test_banner_dropped_on_empty_completion(self):
        # No content to ride on → the banner is not emitted at all (no standalone item that
        # reads as a finished answer or gets summarized into a fake handoff).
        comp = {"choices": [{"message": {"role": "assistant", "content": ""}}]}
        events = _sse_events(responses.to_responses_sse(comp, "m", banner="⟦cria⟧ reasoner · m · 9 tok/s"))
        out = events[-1]["response"]["output"]
        self.assertEqual([o for o in out if o.get("type") == "message"], [])

    def test_banner_shown_on_tool_call_only_turn(self):
        # A tool-call turn carries no text, but the banner still rides as its own message item
        # AHEAD of the call — safe because the tool call keeps the loop alive (not a "done" turn).
        # Without this, a coding run (nearly all tool calls) would never show a single ⟦cria⟧ line.
        comp = {"choices": [{"message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "shell", "arguments": "{}"}}]}}]}
        events = _sse_events(responses.to_responses_sse(comp, "m", banner="⟦cria⟧ coder · m"))
        out = events[-1]["response"]["output"]
        msg_items = [o for o in out if o.get("type") == "message"]
        self.assertEqual(len(msg_items), 1)
        self.assertEqual(msg_items[0]["content"][0]["text"], "⟦cria⟧ coder · m")
        self.assertEqual(len([o for o in out if o.get("type") == "function_call"]), 1)
        # order: banner message item precedes the function call
        self.assertEqual([o["type"] for o in out], ["message", "function_call"])

    def test_session_key_from_prompt_cache_key(self):
        self.assertEqual(responses.session_key_of({"prompt_cache_key": "abc"}), "abc")
        self.assertIsNone(responses.session_key_of({}))

    def test_buffered_json_folds_the_banner_like_the_stream(self):
        # parity: to_responses_json now takes a banner and folds it into the content item, same as
        # body_events — the buffered (stream:false) path was dropping the ⟦cria⟧ line.
        comp = {"choices": [{"message": {"role": "assistant", "content": "the answer"}}]}
        out = responses.to_responses_json(comp, "m", banner="⟦cria⟧ coder · m")["output"]
        msg = [o for o in out if o.get("type") == "message"][0]
        self.assertEqual(msg["content"][0]["text"], "⟦cria⟧ coder · m\nthe answer")

    def test_buffered_json_drops_banner_on_empty_completion(self):
        comp = {"choices": [{"message": {"role": "assistant", "content": ""}}]}
        out = responses.to_responses_json(comp, "m", banner="⟦cria⟧ x")["output"]
        self.assertEqual([o for o in out if o.get("type") == "message"], [])


class ArgSanitizeTests(unittest.TestCase):
    def test_raw_newline_arguments_made_valid(self):
        bad = '{"content": "import requests\nx = 1"}'  # raw newline → invalid JSON
        with self.assertRaises(json.JSONDecodeError):
            json.loads(bad)                              # confirm it starts invalid
        fixed = responses._as_args_str(bad)
        self.assertEqual(json.loads(fixed)["content"], "import requests\nx = 1")  # now parses

    def test_valid_and_dict_args_preserved(self):
        self.assertEqual(json.loads(responses._as_args_str('{"a": 1}')), {"a": 1})
        self.assertEqual(json.loads(responses._as_args_str({"b": 2})), {"b": 2})


class ReasoningForwardingTests(unittest.TestCase):
    """The model's reasoning ('thinking') is forwarded as a Responses reasoning item so Codex
    renders it — the preamble that's missing vs a normal OpenAI session."""

    _COMP = {"choices": [{"message": {"role": "assistant", "content": None,
              "reasoning_content": "Read the failing test, then fix resolve_handle().",
              "tool_calls": [{"id": "c", "type": "function",
                              "function": {"name": "read_file", "arguments": '{"path":"t.py"}'}}]},
              "finish_reason": "tool_calls"}]}

    def _event_kinds(self, show):
        from cria.responses import body_events
        return [r.decode().split("\n", 1)[0] for r in body_events(self._COMP, "r", "m", show_reasoning=show)
                if r.startswith(b"event:")]

    def test_reasoning_item_emitted_when_enabled(self):
        kinds = self._event_kinds(True)
        self.assertIn("event: response.reasoning_summary_text.delta", kinds)  # the transient header
        self.assertIn("event: response.reasoning_text.delta", kinds)          # the persistent channel
        # reasoning comes BEFORE the action
        self.assertLess(kinds.index("event: response.reasoning_summary_text.delta"),
                        kinds.index("event: response.function_call_arguments.delta"))

    def test_reasoning_item_carries_both_summary_and_raw_content(self):
        # The persisted reasoning item (in output_item.done) must include BOTH channels: `summary`
        # for the transient header AND `content` (raw) for the persistent transcript — the latter is
        # what was missing when reasoning only flashed and vanished.
        import json as _json
        from cria.responses import body_events
        done_item = None
        for r in body_events(self._COMP, "r", "m", show_reasoning=True):
            line = r.decode()
            if "response.output_item.done" in line:
                data = _json.loads(line.split("data: ", 1)[1])
                if data["item"].get("type") == "reasoning":
                    done_item = data["item"]
        self.assertIsNotNone(done_item)
        self.assertTrue(done_item["summary"] and done_item["summary"][0]["type"] == "summary_text")
        self.assertTrue(done_item["content"] and done_item["content"][0]["type"] == "reasoning_text")

    def test_no_reasoning_when_disabled(self):
        self.assertFalse(any("reasoning" in k for k in self._event_kinds(False)))

    def test_no_reasoning_item_when_none_present(self):
        from cria.responses import body_events
        comp = {"choices": [{"message": {"content": "hi"}}]}
        kinds = [r.decode() for r in body_events(comp, "r", "m", show_reasoning=True)]
        self.assertFalse(any("reasoning" in k for k in kinds))

    def _reasoning_message_text(self, **kw):
        """The text of the assistant MESSAGE item body_events emits (where the transcript block rides)."""
        import json as _json
        from cria.responses import body_events
        for r in body_events(self._COMP, "r", "m", **kw):
            line = r.decode()
            if "response.output_item.done" in line:
                data = _json.loads(line.split("data: ", 1)[1])
                if data["item"].get("type") == "message":
                    return "".join(p.get("text", "") for p in data["item"]["content"])
        return None

    def test_reasoning_transcript_folds_into_persistent_message(self):
        from cria.indicators import THINK_FENCE, strip_history
        text = self._reasoning_message_text(reasoning_transcript=True)
        self.assertIsNotNone(text)                       # a message item now exists (tool-call-only turn)
        self.assertIn(THINK_FENCE, text)                 # the reasoning rides in a ⟦cria⟧ 💭-fenced block
        self.assertIn("resolve_handle", text)            # the actual thinking is present
        # the block is FENCED, not per-line-marked: at least one reasoning line is CLEAN (no MARKER),
        # so a multi-line/code reasoning renders readably instead of a ⟦cria⟧-per-line wall
        self.assertTrue(any("resolve_handle" in ln and not ln.startswith("⟦cria⟧") for ln in text.split("\n")))
        # …yet strip_history still removes the WHOLE fenced block from inbound history
        cleaned, n = strip_history([{"role": "assistant", "content": text}])
        self.assertTrue(n > 0)
        self.assertNotIn("resolve_handle", cleaned[0]["content"])

    def test_reasoning_fold_renders_code_clean_and_round_trips(self):
        from cria.indicators import strip_history
        from cria.responses import _reasoning_transcript_block
        block = _reasoning_transcript_block("plan:\n```python\nimport os\nx = 1\n```\ndone")
        self.assertIn("import os", block)                                   # code kept verbatim
        self.assertNotIn("⟦cria⟧ import os", block)                         # NOT walled per-line
        cleaned, n = strip_history([{"role": "assistant", "content": block + "\nreal answer"}])
        self.assertEqual(cleaned[0]["content"], "real answer")              # block gone, real content kept

    def test_reasoning_transcript_not_folded_when_flag_absent(self):
        text = self._reasoning_message_text()  # neither flag passed → no fold
        self.assertIsNone(text)  # no message item, no folded reasoning


if __name__ == "__main__":
    unittest.main()
