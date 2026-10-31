"""responses.ProgressiveMessage: text may leave before the completion is whole only as far as the
buffered path would leave it, and the finished item equals what the buffered path builds."""
import json
import re

import pytest

from cria import massage, responses
from cria.config import IndicatorsConfig

LEAK = '<tool_call>{"name": "read_file", "arguments": {"path": "x.py"}}</tool_call>'
SHELL_TOOLS = [{"type": "function", "function": {"name": "read_file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}]


def make(events):
    return responses.ProgressiveMessage(events.append, massage.stream_leak_start, massage.STREAM_HOLDBACK, 0)


def parse(chunks):
    out = []
    for raw in chunks:
        head, data = raw.decode().split("\n", 1)
        out.append((head[7:], json.loads(data[6:])))
    return out


def completion(text, calls=()):
    msg = {"role": "assistant", "content": text}
    if calls:
        msg["tool_calls"] = list(calls)
    return {"choices": [{"message": msg, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}


def normalized(evs):
    """The content of an event stream: generated ids removed, consecutive text deltas folded into one."""
    out = []
    for kind, obj in parse(evs):
        if kind == "response.output_text.delta" and out and out[-1][0] == kind:
            out[-1] = (kind, out[-1][1] + obj["delta"])
        elif kind == "response.output_text.delta":
            out.append((kind, obj["delta"]))
        else:
            out.append((kind, re.sub(r'"(?:msg|fc|resp)_[0-9a-f]+"', '"ID"', json.dumps(obj, sort_keys=True))))
    return out


@pytest.mark.parametrize("text,calls", [
    ("A plain answer long enough to pass the hold-back, with several words in it. " * 3, ()),
    ("short", ()),
    ("Let me look.\n" + LEAK, [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "x.py"}'}}]),
])
def test_progressive_stream_is_content_identical_to_the_buffered_body(text, calls):
    """Fed in 7-char slices then settled, the message item/events equal body_events' for the same final
    completion (buffered path), whether the answer is plain, tiny, or ends in a recovered call."""
    final_text = text.split(LEAK)[0] if calls else text
    comp = completion(final_text, calls)
    events = []
    progressive = make(events)
    for i in range(0, len(text), 7):
        progressive.feed(text[i:i + 7])
    if calls:
        assert LEAK[:12] not in b"".join(events).decode()          # the dialect never reaches the harness
    early = len(events)
    live = [*events, *responses.body_events(comp, "resp_x", "m", progressive=progressive)]
    buffered = list(responses.body_events(comp, "resp_x", "m"))
    if len(final_text) > massage.STREAM_HOLDBACK:
        assert early >= 3, "text should have been delivered before the completion was settled"
    assert normalized(live) == normalized(buffered)


def test_the_holdback_and_the_leak_marker_bound_what_is_delivered_early():
    events = []
    progressive = make(events)
    progressive.feed("x" * 100)
    assert progressive.sent == 100 - massage.STREAM_HOLDBACK
    progressive.feed("tail <tool_ca")      # a marker may be starting inside the hold-back
    assert progressive.sent <= len("x" * 100 + "tail ")
    progressive.feed('ll>{"name": "read_file", "arguments": {"path": "x.py"}}</tool_call>')
    assert progressive.captured and progressive.sent <= len("x" * 100 + "tail ")
    assert "<tool_ca" not in "".join(o["delta"] for k, o in parse(events) if k == "response.output_text.delta")


def test_a_final_text_that_no_longer_starts_with_what_was_shown_is_refused_not_shown_twice():
    """Words already on screen cannot be taken back; settle() refuses instead of showing a second, different answer."""
    events = []
    progressive = make(events)
    progressive.feed("The first sentence is already visible here. " * 3)
    with pytest.raises(responses.ProgressiveDivergence):
        list(responses.body_events(completion("A different answer."), "r", "m", progressive=progressive))


def test_an_unopened_stream_falls_back_to_the_ordinary_item():
    """Nothing delivered yet (leak at the start / empty text): body_events builds the whole item itself."""
    progressive = make([])
    progressive.feed(LEAK)
    assert not progressive.opened
    comp = completion("", [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "x.py"}'}}])
    assert normalized(responses.body_events(comp, "r", "m", progressive=progressive)) == normalized(responses.body_events(comp, "r", "m"))


@pytest.mark.parametrize("kw,decorates", [({}, True), ({"enabled": False}, False),
                                          ({"route": False, "assists": False, "stats": False, "connect": False,
                                            "status": False, "reasoning": False, "reasoning_transcript": False}, False),
                                          ({"route": False, "assists": False, "stats": False, "connect": False,
                                            "status": False, "reasoning": False}, True)])
def test_text_may_leave_early_only_when_no_indicator_family_can_decorate_it(kw, decorates):
    assert IndicatorsConfig(**kw).decorates() is decorates
