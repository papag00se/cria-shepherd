"""A replayed tool call's arguments at the final wire (Upstream._prep): always valid JSON whatever the assist selection, never silently lost; the
literal is recovered only where the historical-argument assist is selected, and everything else about the history is untouched."""
import json

import pytest

from cria import config, upstream


class Log:
    phase = "coder-s1"

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def history(raw, cid="late"):
    return [{"role": "user", "content": "continue"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": cid, "type": "function", "index": 7, "function": {"name": "old_native_api", "arguments": raw}}]},
            {"role": "tool", "tool_call_id": cid, "content": "already happened; not a new execution"}]


def wire(messages, level):
    up = upstream.Upstream("http://unused", context_window=8192, engagement_level=level)
    raw, _, _ = up._prep({"model": "offline", "messages": messages}, False, Log())
    return json.loads(raw)["messages"]


@pytest.mark.parametrize("raw,pure,full", [
    ('wrapper {"cmd": "echo hi"} trailing prose', {"_unparsed": 'wrapper {"cmd": "echo hi"} trailing prose'}, {"cmd": "echo hi"}),   # a literal the reader can lift
    ('{"cmd":"late unfinished', {"_unparsed": '{"cmd":"late unfinished'}, {"_unparsed": '{"cmd":"late unfinished'}),                # nothing to lift: the text survives, enveloped
    ('{"path": "a.py"}', None, None)])                                                                                         # valid: the very bytes at every level
def test_replayed_arguments_are_valid_json_at_every_level_and_recovered_only_where_the_assist_is_selected(raw, pure, full):
    """A malformed historical tool_call 500s a strict template on every later turn. The repair is the wire's, so it holds with every optional recovery
    off; the recovered literal is an assist's, so it appears only where selected; call id, name, extra fields and the paired result never change."""
    for level, expected in ((config.PURE_PROXY, pure), (config.MAX_ENGAGEMENT_LEVEL, full)):
        sent = wire(history(raw), level)
        call = sent[1]["tool_calls"][0]
        assert (call["function"]["arguments"] == raw) is (expected is None)
        assert json.loads(call["function"]["arguments"]) == (json.loads(raw) if expected is None else expected)
        assert (call["id"], call["index"], call["function"]["name"]) == ("late", 7, "old_native_api") and sent[2] == history(raw)[2]
