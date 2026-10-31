"""The Responses API boundary: requests translate to chat faithfully, replies translate back without altering arguments, and an incomplete turn releases no call."""
import json
from unittest import mock

import pytest

from cria import generation, massage, responses
from cria.indicators import THINK_FENCE, strip_history
from cria.upstream import Upstream, UpstreamError
from context_wire_b_helpers import Frames, Rlog, sse

CALL = {"id": "real_call", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "notes.txt", "content": "雪\n"})}}

def data(chunks):
    return [json.loads(line[6:]) for raw in chunks for line in raw.decode().splitlines() if line.startswith("data: ") and line != "data: [DONE]"]

def test_a_responses_request_becomes_one_faithful_chat_body():
    """Instructions + developer merge into exactly one system turn; flat tools nest (default object schema, strict kept); calls pair with their outputs; an orphan output is dropped rather than null-paired; controls map; Codex UI namespaces are ignored but a model-callable unknown tool is rejected."""
    body = responses.to_chat_body({"model": "m", "instructions": "You are a coding agent.", "max_output_tokens": 123, "temperature": 0.2,
        "reasoning": {"effort": "medium"}, "tool_choice": {"type": "function", "name": "f"},
        "tools": [{"type": "function", "name": "f", "strict": True}, {"type": "namespace"}, {"type": "web_search"}],
        "input": [{"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "sandbox rules"}]}, {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "do it"}]},
                  {"type": "function_call", "call_id": "c9", "name": "shell", "arguments": {"command": ["ls"]}},
                  {"type": "function_call_output", "call_id": "c9", "output": "a\nb"}, {"type": "function_call_output", "output": "orphan"}]})
    system, user, call, result = body["messages"]
    assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant", "tool"] and "sandbox rules" in system["content"] and "coding agent" in system["content"]
    assert call["tool_calls"][0]["id"] == "c9" and json.loads(call["tool_calls"][0]["function"]["arguments"]) == {"command": ["ls"]}
    assert result == {"role": "tool", "tool_call_id": "c9", "content": "a\nb"}
    assert body["tools"] == [{"type": "function", "function": {"name": "f", "parameters": {"type": "object", "properties": {}}, "strict": True}}]
    assert body["tool_choice"] == {"type": "function", "function": {"name": "f"}}
    assert (body["max_tokens"], body["temperature"], body["reasoning_effort"]) == (123, 0.2, "medium")
    for bad in ({"tools": [{"type": "computer_use_preview"}]}, {"tool_choice": {"type": "mcp"}}):
        with pytest.raises(ValueError, match="unsupported Responses"):
            responses.to_chat_body({"model": "m", "input": [], **bad})

def test_function_call_arguments_cross_the_wire_byte_for_byte_in_every_direction():
    """A fresh executable call is never 'repaired' on the way to the harness: whitespace, escapes, raw control bytes and unfinished JSON arrive exactly as generated (the harness sees the real parse failure), and the same bytes come back as history. Structured values serialize without {} substitution."""
    for raw in ('  { "cmd" : "echo safe", "n": 1.00 }  ', '{"cmd":"echo \\u65e5\\u672c"}', '{"cmd":"echo line\nbreak"}', '{"cmd":"echo nul\x00"}', '{"cmd":"unfinished'):
        completion = {"choices": [{"message": {"role": "assistant", "tool_calls": [{"id": "orig", "type": "function", "function": {"name": "exec_command", "arguments": raw}}]}}]}
        item = responses.to_responses_json(completion, "local")["output"][0]
        events = data(responses.to_responses_sse(completion, "local"))
        assert item["arguments"] == raw and item["call_id"] == "orig"
        assert next(e for e in events if e["type"] == "response.function_call_arguments.delta")["delta"] == raw
        assert next(e for e in events if e["type"] == "response.completed")["response"]["output"][0]["arguments"] == raw
        assert responses.to_chat_body({"model": "l", "input": [item]})["messages"][0]["tool_calls"][0]["function"]["arguments"] == raw
    for value in (None, False, 0, [], {"cmd": "x"}):
        assert json.loads(responses._as_args_str(value)) == value

def test_the_banner_and_reasoning_ride_without_becoming_a_summarizable_answer():
    """The banner folds INTO the content item (a standalone item was once summarized into a whole compaction); an empty reply drops it; a tool-only turn carries it as a message AHEAD of the call. Reasoning is a separate item only when asked, and the transcript fold is fenced so history stripping removes all of it."""
    say_ = lambda content, **kw: responses.to_responses_json({"choices": [{"message": {"role": "assistant", "content": content, **kw}}]}, "m", banner="⟦cria⟧ coder · m")["output"]
    assert say_("the answer")[0]["content"][0]["text"] == "⟦cria⟧ coder · m\nthe answer" and len(say_("the answer")) == 1
    assert say_("") == []
    assert data(responses.to_responses_sse({"choices": [{"message": {"role": "assistant", "content": "the answer"}}]}, "m", banner="⟦cria⟧ b"))[-1]["response"]["output"][0]["content"][0]["text"] == "⟦cria⟧ b\nthe answer"
    tool_turn = say_(None, tool_calls=[CALL])
    assert [o["type"] for o in tool_turn] == ["message", "function_call"]
    comp = {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "reasoning_content": "Fix resolve_handle().", "tool_calls": [CALL]}}]}
    kinds = lambda **kw: [r.decode().split("\n", 1)[0] for r in responses.body_events(comp, "r", "m", **kw) if r.startswith(b"event:")]
    shown = kinds(show_reasoning=True)
    assert shown.index("event: response.reasoning_summary_text.delta") < shown.index("event: response.function_call_arguments.delta")
    assert not any("reasoning" in k for k in kinds())
    text = next(json.loads(r.decode().split("data: ", 1)[1])["item"]["content"][0]["text"] for r in responses.body_events(comp, "r", "m", reasoning_transcript=True)
                if b'"message"' in r and b"output_item.done" in r)
    assert THINK_FENCE in text and "resolve_handle" in text
    cleaned, n = strip_history([{"role": "assistant", "content": text + "\nreal answer"}])
    assert n and cleaned[0]["content"] == "real answer"

def test_an_incomplete_turn_releases_no_call_but_keeps_it_as_evidence_and_a_finished_one_executes_once():
    """A length or locally-aborted turn may hold a perfectly valid-looking call; no harness boundary may run it. It is withheld as call_prefixes evidence, the Responses status is incomplete (never response.completed), and a finished turn still emits its call exactly once."""
    for finish, extra, reason in (("length", {}, "generation_limit"), ("rumination", {"cria_rumination": {"hits": 6}}, "generation_aborted")):
        comp = {"choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": "Earlier. ", "tool_calls": [dict(CALL)]}}], **extra}
        safe = massage.apply(comp, [{"type": "function", "function": {"name": "write_file", "parameters": {"type": "object"}}}])
        assert not safe["choices"][0]["message"].get("tool_calls") and safe["choices"][0]["finish_reason"] == finish
        assert safe["generation_evidence"]["call_prefixes"][0]["arguments"] == CALL["function"]["arguments"]
        done = responses.to_responses_json(safe, "m")
        assert done["status"] == "incomplete" and done["incomplete_details"]["reason"] == reason and not [o for o in done["output"] if o["type"] == "function_call"]
        events = data(responses.to_responses_sse(safe, "m"))
        types = [e["type"] for e in events]
        assert events[-1]["response"]["status"] == "incomplete"
        assert types[-1] == "response.incomplete" and "response.completed" not in types and "response.function_call_arguments.delta" not in types
    ok = {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [CALL]}}]}
    assert [o["type"] for o in responses.to_responses_json(ok, "m")["output"]] == ["function_call"]
    assert generation.may_recover(ok) and not generation.may_recover(safe)

def test_a_stream_that_ends_without_a_terminal_frame_releases_nothing_and_keeps_every_byte():
    """No [DONE]/finish is not a stop: a tool-looking text, a half-written call or a typed protocol error must never be released as an action. Content and reasoning stay live; the terminal frame is a structured incomplete_stream_error carrying the raw wire bytes."""
    text = '<tool_call>' + json.dumps(CALL["function"]) + '</tool_call>'
    menu = [{"type": "function", "function": {"name": "write_file", "parameters": {"type": "object"}}}]
    for done in (False, True):
        for with_call in (False, True):
            chunks = [sse({"reasoning_content": "Unfinished 雪\n"}), sse({"content": text})] + ([sse({"tool_calls": [{"index": 0, **CALL}]})] if with_call else []) + ([b"data: [DONE]\n\n"] if done else [])
            frames = data(massage.massage_stream(iter(chunks), "m", menu))
            choices = [c for f in frames for c in f.get("choices", [])]
            assert not any((c.get("delta") or {}).get("tool_calls") for c in choices) and not any(c.get("finish_reason") in ("stop", "tool_calls") for c in choices)
            assert "".join((c.get("delta") or {}).get("content", "") for c in choices) == text
            assert frames[-1]["error"]["type"] == "incomplete_stream_error" and frames[-1]["error"]["generation_evidence"]["wire_raw_hex"] == b"".join(chunks).hex()
    held = list(massage.massage_stream(iter([sse({"tool_calls": [{"index": 0, **CALL}]}), sse({}, "length"), b"data: [DONE]\n\n"]), "m", menu))
    assert not any((c.get("delta") or {}).get("tool_calls") for f in data(held) for c in f.get("choices", [])) and any("withheld_action_deltas" in json.dumps(f) for f in data(held))
    chunks = [sse({"content": "Earlier prose. " + text}), b"data: " + json.dumps({"error": {"type": "invalid_model_output_error", "code": 500, "message": "cut", "generation_evidence": {"raw_hex": "ab"}}}).encode() + b"\n\n"]
    frames = data(massage.massage_stream(iter(chunks), "m"))
    assert frames[-1]["error"]["generation_evidence"]["raw_hex"] == "ab" and not any((c.get("delta") or {}).get("tool_calls") for f in frames for c in f.get("choices", []))
    with mock.patch("cria.upstream.urllib.request.urlopen", return_value=Frames([sse({"content": "Entire 雪\n"}), sse({"tool_calls": [{"index": 0, **CALL, "function": {"name": "write_file", "arguments": '{"path":"雪'}}]})])):
        with pytest.raises(UpstreamError) as caught:
            Upstream("http://fixture", context_window=16384, capture_dir=None, capture_rendered=False).chat_watched({"model": "f", "messages": [{"role": "user", "content": "t"}]}, Rlog())
    evidence = caught.value.response_error["generation_evidence"]
    assert caught.value.response_error["type"] == "incomplete_stream_error" and evidence["stream_prefix"]["content"] == "Entire 雪\n"
    assert "stop_type" not in evidence and "".join(evidence["stream_prefix"]["action_prefixes"][0]["args"]) == '{"path":"雪'
