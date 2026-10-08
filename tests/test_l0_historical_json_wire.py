"""A length-ended call must not poison later native history rendering."""
import copy
import json

import pytest

from cria import config, massage
from cria.upstream import Upstream


class Log:
    def emit(self, *args, **kwargs):
        pass


def prep(messages):
    upstream = Upstream("http://unused", api_key="unused", context_window=49152,
                        engagement_level=config.PURE_PROXY)
    body = {"model": "fixture", "messages": messages}
    wire, _, _ = upstream._prep(body, False, Log())
    return json.loads(wire)["messages"]


@pytest.mark.parametrize("raw", ['{"cmd":"cd /workspace-mc',
                                  '{"cmd":"echo\\x"}',
                                  '{"cmd":"quote: " nested"}'])
def test_l0_incomplete_history_is_lossless_context_not_guessed_command(raw):
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)
    messages = [
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "good", "type": "function", "function": {
                "name": "shell", "arguments": '{"cmd":"true"}'}},
            {"id": "bad", "type": "function", "function": {
                "name": "shell", "arguments": raw}}]},
        {"role": "tool", "tool_call_id": "good", "content": "exit=0"},
        {"role": "tool", "tool_call_id": "bad", "content": "failed to parse arguments"},
        {"role": "user", "content": "CONTEXT CHECKPOINT COMPACTION"},
    ]
    original = copy.deepcopy(messages)
    wire = prep(messages)
    calls = wire[1]["tool_calls"]
    # Strict native renderers reparse arguments even with NO tool menu (compaction).
    parsed = [json.loads(call["function"]["arguments"]) for call in calls]
    assert parsed == [{"cmd": "true"}, {"_unparsed": raw}]
    assert calls[0] == original[1]["tool_calls"][0]
    assert calls[1]["id"] == "bad"
    assert calls[1]["function"]["name"] == "shell"
    assert wire[2:] == original[2:]
    assert messages == original
    assert prep(wire) == wire


def test_l0_does_not_recover_even_recoverable_malformed_history(monkeypatch):
    def forbid(*args, **kwargs):
        raise AssertionError("L0 must not infer missing arguments")
    monkeypatch.setattr(massage, "extract_json_object", forbid)
    monkeypatch.setattr(massage, "_recover_write_args", forbid)
    raw = '{"path":"file","content":"unescaped\nline"}'
    messages = [{"role": "assistant", "tool_calls": [{"id": "call",
        "type": "function", "function": {"name": "write_file", "arguments": raw}}]}]
    wire = prep(messages)
    assert json.loads(wire[0]["tool_calls"][0]["function"]["arguments"]) == {"_unparsed": raw}


def test_valid_history_is_byte_equivalent_at_l0():
    messages = [{"role": "user", "content": "hi"},
                {"role": "assistant", "tool_calls": [{"id": "call", "type": "function",
                 "function": {"name": "shell", "arguments": '{ "cmd" : "echo \\u65e5" }'}}]},
                {"role": "tool", "tool_call_id": "call", "content": "日"}]
    assert prep(messages) == messages
