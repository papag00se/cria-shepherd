"""massage edges the reset lost: the proxy opt-out, multipart turns at the alternation wire, and a stream that carries junk frames or long prose."""
import json
from context_wire_b_helpers import sse
from cria import massage

IMG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
LEAK = {"choices": [{"message": {"role": "assistant", "content": '<tool_call>{"name": "read_file", "arguments": {"path": "x"}}</tool_call>'}, "finish_reason": "stop"}]}


def test_the_tool_call_fix_opt_out_leaves_a_leaked_call_as_the_model_wrote_it():
    """At the pure proxy (explicit flag, or the library-level default) nothing the model said is rewritten; with fixes on it becomes a call."""
    assert massage.apply(json.loads(json.dumps(LEAK)), tool_call_fixes=False) == LEAK
    massage.set_tool_call_fixes(False)
    try:
        assert massage.apply(json.loads(json.dumps(LEAK))) == LEAK
    finally:
        massage.set_tool_call_fixes(True)
    assert massage.apply(json.loads(json.dumps(LEAK)))["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "read_file"


def test_multipart_user_turns_merge_as_parts_and_an_incompatible_structured_turn_gets_an_empty_boundary():
    """A string user turn after an image turn joins its parts (nothing dropped); a turn that differs in anything but content is never fused: an empty assistant turn separates them."""
    img, note = {"role": "user", "content": [{"type": "text", "text": "look"}, IMG]}, {"role": "user", "content": "then this"}
    assert massage.merge_for_alternation([img, note]) == [{"role": "user", "content": [*img["content"], {"type": "text", "text": "\n\n"}, {"type": "text", "text": "then this"}]}]
    out = massage.merge_for_alternation([img, {**note, "name": "other"}])
    assert [m["role"] for m in out] == ["user", "assistant", "user"] and out[1]["content"] == "" and out[2]["content"] == "then this"


def test_a_stream_survives_junk_frames_and_flushes_the_held_back_prose_at_the_end():
    """A non-JSON data frame and a non-data line are passed over (not fatal); prose longer than the hold-back streams live and all arrives, once."""
    prose = "word " * 40
    frames = [b"data: {not json}\n\n", b": keepalive\n\n", sse({"role": "assistant"}), sse({"content": prose[:120]}), sse({"content": prose[120:]}), sse({}, "stop"), b"data: [DONE]\n\n"]
    out = list(massage.massage_stream(iter(frames), "m", tools=None))
    got = "".join(json.loads(c[5:])["choices"][0]["delta"].get("content", "") for c in out if c.startswith(b"data: {") and b'"choices"' in c)
    assert got == prose and out[-1] == b"data: [DONE]\n\n"
