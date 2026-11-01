"""massage edges the reset lost: the proxy opt-out, multipart turns at the alternation wire, and a stream that carries junk frames or long prose."""
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from context_wire_b_helpers import sse
from cria import assistruntime, bodykeys, massage, outputpolicies, toolstages
from cria.config import Config, RoutingConfig
from cria.indicators import Indicator
from cria.loop import LoopStore
from cria.server import CriaHandler

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
    # a private hint rides only if both turns carry the SAME object (merging would otherwise drop one turn's hint): equal-but-distinct is not fused
    hint = ["x"]
    hinted = {**img, bodykeys.MULTIPART_UNVERIFIED: hint}
    assert len(massage.merge_for_alternation([hinted, {**note, bodykeys.MULTIPART_UNVERIFIED: hint}])) == 1
    assert len(massage.merge_for_alternation([hinted, {**note, bodykeys.MULTIPART_UNVERIFIED: ["x"]}])) == 3


def test_a_stream_survives_junk_frames_and_flushes_the_held_back_prose_at_the_end():
    """A non-JSON data frame and a non-data line are passed over (not fatal); prose longer than the hold-back streams live and all arrives, once."""
    prose = "word " * 40
    frames = [b"data: {not json}\n\n", b": keepalive\n\n", sse({"role": "assistant"}), sse({"content": prose[:120]}), sse({"content": prose[120:]}), sse({}, "stop"), b"data: [DONE]\n\n"]
    out = list(massage.massage_stream(iter(frames), "m", tools=None))
    got = "".join(json.loads(c[5:])["choices"][0]["delta"].get("content", "") for c in out if c.startswith(b"data: {") and b'"choices"' in c)
    assert got == prose and out[-1] == b"data: [DONE]\n\n"


# --- selection: which output-recovery stage runs is the bound selection's call, never the library-global switch ------------------------------

WRITE_MENU = [{"type": "function", "function": {"name": "write_file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}}]
WRITE_LEAK = '<tool_call>{"name":"write_file","arguments":{"path":"x.txt","content":"bytes"}}</tool_call>'


def test_a_bound_output_selection_can_remove_or_replace_the_text_call_recovery_stage():
    comp = {"choices": [{"finish_reason": "stop", "message": {"content": WRITE_LEAK}}]}
    original = json.loads(json.dumps(comp))
    bindings = toolstages.defaults()
    without = replace(bindings, recovery=tuple(d for d in bindings.recovery if d.policy.id != "text-call-recovery"))
    with toolstages.bound(without):
        assert massage.apply(json.loads(json.dumps(comp)), tool_call_fixes=True) == original          # unselected: the model's words stay as written
    seen = []

    def recover(c, tools=None, rlog=None):
        seen.append(tools)
        c["choices"][0]["message"]["content"] = "replacement ran"
        return c
    with toolstages.bound(replace(bindings, recovery=(replace(outputpolicies.RECOVERY[0], execute=recover),))):
        assert massage.apply(json.loads(json.dumps(comp)), tool_call_fixes=True)["choices"][0]["message"]["content"] == "replacement ran"
    assert seen == [None]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/responses"])
def test_a_handler_obeys_its_own_selection_even_when_another_server_flipped_the_library_switch_last(stream, path):
    """The library-level switch is process-global; two servers built in hostile order must not decide each other's output recovery."""
    def handler(level):
        selected = assistruntime.AssistRuntime.select(level=level, registrations=tuple(
            {d.policy.id: d for d in (*assistruntime.DEFINITIONS, *toolstages.defaults().definitions)}.values()))
        comp = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": WRITE_LEAK}}]}
        provider = SimpleNamespace(chat=lambda body, log: json.dumps(comp).encode(), stream_chat=lambda body, log: iter(
            [massage._sse({"content": WRITE_LEAK}, "fake"), massage._sse({}, "fake", finish="stop"), b"data: [DONE]\n\n"]))
        body = {"messages": [{"role": "user", "content": "request"}], "tools": WRITE_MENU, "model": "fake"}
        out, h = [], CriaHandler.__new__(CriaHandler)
        h.path, h.headers = path, {}
        h.server = SimpleNamespace(cfg=Config(routing=RoutingConfig(engagement_level=level)), loop=None, loop_store=LoopStore(),
                                   pilot_runtime=selected, reasoner_role=None)
        h._classify = h._engages_loop = lambda *a: None
        h._route = lambda *a: (provider, Indicator(False, False, "fake"))
        h._apply_route_role = lambda b, *a: b
        h._focus_trim = lambda b, *a: (b, False)
        h._translate_out = h._finalize = lambda c, *a: c
        h._handle_chat = h._handle_responses = lambda: out.extend(
            CriaHandler._produce_stream(h, json.loads(json.dumps(body)), Mock()) if stream
            else [CriaHandler._produce_completion(h, json.loads(json.dumps(body)), Mock(), "fake")[0]])
        return h, out

    def called(out):
        if stream:
            return [tc["function"]["name"] for raw in out if (choice := massage._choice(raw)) for tc in (choice.get("delta") or {}).get("tool_calls", [])]
        return [tc["function"]["name"] for c in out for ch in c["choices"] for tc in (ch.get("message") or {}).get("tool_calls", [])]
    high, high_out = handler(5)
    low, low_out = handler(0)
    try:
        massage.set_tool_call_fixes(False)
        CriaHandler.do_POST(high)
        massage.set_tool_call_fixes(True)
        CriaHandler.do_POST(low)
    finally:
        massage.set_tool_call_fixes(True)
    assert called(high_out) == ["write_file"] and called(low_out) == []
