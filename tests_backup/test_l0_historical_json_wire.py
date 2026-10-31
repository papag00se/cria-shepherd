"""A length-ended call must not poison later native history rendering."""
import copy
import json

import pytest

from cria import callliterals, config, historyarguments
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
    raw = '{"path":"file","content":"unescaped\nline"}'
    source = historyarguments.HistoricalArguments((raw,))
    # Positive control: this exact malformed text really is recoverable, not
    # a fixture for which optional readers would silently find nothing anyway.
    assert historyarguments.recover_arguments(source).values == (
        {'path': 'file', 'content': 'unescaped\nline'},)
    reached = []
    def forbid_json(*args, **kwargs):
        reached.append('json')
        raise AssertionError('optional JSON reader reached')
    def forbid_write(*args, **kwargs):
        reached.append('write')
        raise AssertionError('optional write reader reached')
    monkeypatch.setattr(historyarguments.jsontext, 'extract_json_object', forbid_json)
    monkeypatch.setattr(callliterals, '_recover_write_args', forbid_write)
    valid = '{ "cmd" : "echo \\u65e5" }'
    messages = [{"role": "assistant", "tool_calls": [
        {"id": "good", "type": "function", "function": {"name": "shell", "arguments": valid}},
        {"id": "call", "type": "function", "function": {"name": "write_file", "arguments": raw}}]}]
    original = copy.deepcopy(messages)
    wire = prep(messages)
    calls = wire[0]['tool_calls']
    assert calls[0] == original[0]['tool_calls'][0]
    assert json.loads(calls[1]['function']['arguments']) == {'_unparsed': raw}
    assert calls[1]['id'] == 'call' and calls[1]['function']['name'] == 'write_file'
    assert messages == original
    assert prep(wire) == wire
    assert reached == []

    # Both poisons guard live canonical seats. Force optional recovery in memory
    # to prove it fails; the second control merely exposes the fallback reader.
    with pytest.raises(AssertionError, match='optional JSON reader reached'):
        historyarguments.recover_arguments(source)
    with monkeypatch.context() as control:
        control.setattr(historyarguments.jsontext, 'extract_json_object', lambda _raw: None)
        with pytest.raises(AssertionError, match='optional write reader reached'):
            historyarguments.recover_arguments(source)
    assert reached == ['json', 'write']


def test_valid_history_is_byte_equivalent_at_l0():
    messages = [{"role": "user", "content": "hi"},
                {"role": "assistant", "tool_calls": [{"id": "call", "type": "function",
                 "function": {"name": "shell", "arguments": '{ "cmd" : "echo \\u65e5" }'}}]},
                {"role": "tool", "tool_call_id": "call", "content": "日"}]
    assert prep(messages) == messages
