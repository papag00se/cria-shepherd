"""Responses boundary tables: every request shape to_chat_body refuses (with the reason), the image/custom/tool-choice translations it accepts,
and the outbound to_responses_json shapes (reasoning, banner, custom tool, incomplete turn, usage details)."""
import json

import pytest

from cria import generation, responses

U = lambda *parts: {"type": "message", "role": "user", "content": list(parts)}
TEXT = {"type": "input_text", "text": "look"}
IMG = {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}


@pytest.mark.parametrize("request_body, reason", [
    ({"input": [U({"type": "input_file", "file_id": "f"})]}, "non-text content type"),
    ({"input": [U("loose string")]}, "non-text content type"),
    ({"input": [U(TEXT, IMG, "stray")]}, "unsupported Responses content part"),
    ({"input": [U({**TEXT, "annotations": []}, IMG)]}, "text metadata"),
    ({"input": [U({"type": "input_text", "text": 5}, IMG)]}, "text metadata"),
    ({"input": [{"type": "message", "role": "assistant", "content": [IMG]}]}, "image role"),
    ({"input": [U({"type": "input_image", "image_url": ""})]}, "image reference or metadata"),
    ({"input": [U({**IMG, "file_id": "x"})]}, "image reference or metadata"),
    ({"input": [U(TEXT, IMG, {"type": "input_audio"})]}, "unsupported Responses content type"),
    ({"input": [U(TEXT)], "tool_choice": {"type": "allowed_tools"}}, "tool_choice"),
    ({"input": [U(TEXT)], "tools": ["shell"]}, "tools must be objects"),
    ({"input": [U(TEXT)], "tools": [{"type": "image_generation"}]}, "tool type"),
])
def test_unsupported_request_shapes_are_refused_with_their_reason_never_silently_dropped(request_body, reason):
    """Anything cria cannot carry faithfully is a ValueError naming why (the HTTP edge turns it into a 400), not a quietly thinner request."""
    with pytest.raises(ValueError, match=reason):
        responses.to_chat_body(request_body)


def test_images_text_custom_tools_and_controls_translate_in_order():
    """A user turn mixing text and an image keeps its order and detail; custom (freeform) tools become one-string-input functions and their calls/outputs round-trip; nested/flat tool_choice forms; the Chat controls map."""
    body = responses.to_chat_body({
        "model": "m", "stream": True, "parallel_tool_calls": False, "top_k": 7, "seed": 3, "stop": ["x"], "max_output_tokens": 50,
        "reasoning": {"effort": "low"}, "tool_choice": {"type": "function", "function": {"name": "apply_patch"}},
        "tools": [{"type": "custom", "name": "apply_patch", "description": "patch", "format": {"type": "grammar"}}],
        "input": [U(TEXT, {**IMG, "detail": "high"}),
                  {"type": "custom_tool_call", "call_id": "c1", "name": "apply_patch", "input": "*** Begin"},
                  {"type": "custom_tool_call_output", "call_id": "c1", "output": [{"type": "input_text", "text": "applied"}]},
                  {"type": "function_call_output", "call_id": "c2", "output": {"text": "from dict"}},
                  {"type": "function_call_output", "call_id": "c3", "output": {"x": 1}},
                  {"type": "function_call_output", "call_id": "c4", "output": 42},
                  {"type": "function_call_output", "call_id": "c5", "output": [IMG]},
                  {"type": "reasoning", "summary": []}, "not-a-dict"]})
    assert body["messages"][0] == {"role": "user", "content": [{"type": "text", "text": "look"}, {"type": "image_url", "image_url": {"url": IMG["image_url"], "detail": "high"}}]}
    call = body["messages"][1]["tool_calls"][0]
    assert call["function"] == {"name": "apply_patch", "arguments": json.dumps({"input": "*** Begin"})}
    assert [m["content"] for m in body["messages"][2:]] == ["applied", "from dict", '{"x": 1}', "42", [{"type": "image_url", "image_url": {"url": IMG["image_url"]}}]]
    assert len(body["messages"]) == 7 and body["tool_choice"] == {"type": "function", "function": {"name": "apply_patch"}}
    (tool,) = body["tools"]
    assert tool["function"]["parameters"]["required"] == ["input"] and '{"type": "grammar"}' in tool["function"]["parameters"]["properties"]["input"]["description"]
    assert (body["stream"], body["parallel_tool_calls"], body["top_k"], body["seed"], body["stop"], body["max_tokens"], body["reasoning_effort"]) == (True, False, 7, 3, ["x"], 50, "low")


def test_a_message_whose_content_is_not_text_translates_to_an_empty_message_in_its_role():
    """A harness item with `content: null` (or a bare number) is an empty turn, not a crash and not the text "None"; a developer item like it adds no system text."""
    body = responses.to_chat_body({"input": [{"type": "message", "role": "developer", "content": None},
                                             {"type": "message", "role": "user", "content": None},
                                             {"type": "message", "role": "assistant", "content": 7}]})
    assert body["messages"] == [{"role": "user", "content": ""}, {"role": "assistant", "content": ""}]


def completion(message, finish="stop", **extra):
    return {"choices": [{"message": message, "finish_reason": finish}], **extra}


def test_outbound_shapes_for_reasoning_banner_custom_calls_usage_and_an_incomplete_turn():
    """Reasoning is shown only when asked; a banner leads the text (or stands alone beside a tool call); a custom tool call returns its one-string input; native usage details survive; a length-cut turn is status=incomplete with every non-reasoning item incomplete."""
    call = {"id": "c1", "type": "function", "function": {"name": "apply_patch", "arguments": json.dumps({"input": "patch body"})}}
    plain = {"id": "c2", "type": "function", "function": {"name": "shell", "arguments": {"cmd": "ls"}}}
    out = responses.to_responses_json(
        completion({"role": "assistant", "content": None, "reasoning_content": "hmm", "tool_calls": [call, plain]}, "tool_calls",
                   usage={"prompt_tokens": 10, "completion_tokens": 4, "prompt_tokens_details": {"cached_tokens": 2}, "completion_tokens_details": {"reasoning_tokens": 1}}),
        "m", show_reasoning=True, banner="⟦cria⟧ coder · m", custom_tools=frozenset({"apply_patch"}))
    kinds = [i["type"] for i in out["output"]]
    assert kinds == ["reasoning", "message", "custom_tool_call", "function_call"] and out["output"][1]["content"][0]["text"] == "⟦cria⟧ coder · m"
    assert out["output"][2]["input"] == "patch body" and out["output"][3]["arguments"] == '{"cmd": "ls"}'
    assert out["usage"]["input_tokens"] == 10 and out["usage"]["total_tokens"] == 14
    assert out["usage"]["input_tokens_details"] == {"cached_tokens": 2} and out["usage"]["output_tokens_details"] == {"reasoning_tokens": 1}
    cut = responses.to_responses_json(completion({"role": "assistant", "content": "half an ans", "reasoning_content": "t"}, "length"), "m",
                                      show_reasoning=True, reasoning_transcript=True)
    assert cut["status"] == "incomplete" and cut["incomplete_details"]["reason"] and {i["status"] for i in cut["output"] if i["type"] != "reasoning"} == {"incomplete"}
    assert "t" in cut["output"][1]["content"][0]["text"] and cut["output"][1]["content"][0]["text"].endswith("half an ans")


def test_a_custom_call_with_anything_but_one_string_input_is_refused_on_the_way_out():
    """The model emitted apply_patch arguments that are not exactly {input: str}: that is an error, never a call with invented input."""
    for args in ('{"input": 5}', '{"input": "a", "extra": 1}', '["a"]'):
        bad = {"id": "c", "type": "function", "function": {"name": "apply_patch", "arguments": args}}
        with pytest.raises(ValueError, match="exactly one string input"):
            responses.to_responses_json(completion({"role": "assistant", "content": None, "tool_calls": [bad]}, "tool_calls"), "m", custom_tools=frozenset({"apply_patch"}))
