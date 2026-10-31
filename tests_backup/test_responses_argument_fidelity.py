"""Responses translation must not repair fresh executable arguments or normalize raw bytes."""
import json

import pytest

from cria import responses


@pytest.mark.parametrize('raw', [
    '  { "cmd" : "echo safe", "n": 1.00 }  ',
    '{"cmd":"echo \\u65e5\\u672c"}',
    '{"cmd":"echo line\nbreak"}',
    '{"cmd":"echo tab\tcharacter"}',
    '{"cmd":"echo nul\x00character"}',
    '{"cmd":"unfinished',
])
def test_raw_function_arguments_survive_both_wire_directions(raw):
    completion = {'choices': [{'message': {'role': 'assistant', 'tool_calls': [
        {'id': 'original-call', 'type': 'function', 'function': {
            'name': 'exec_command', 'arguments': raw}}]}}]}
    buffered = responses.to_responses_json(completion, 'local')
    call = buffered['output'][0]
    assert call['arguments'] == raw
    assert call['call_id'] == 'original-call'
    events = [json.loads(event.decode().split('data: ', 1)[1])
              for event in responses.to_responses_sse(completion, 'local')]
    delta = next(event for event in events if event['type'] == 'response.function_call_arguments.delta')
    assert delta['delta'] == raw
    completed = next(event for event in events if event['type'] == 'response.completed')
    assert completed['response']['output'][0]['arguments'] == raw
    history = responses.to_chat_body({'model': 'local', 'input': [call]})
    assert history['messages'][0]['tool_calls'][0]['function']['arguments'] == raw
    if any(char in raw for char in ('\n', '\t', '\x00')):
        with pytest.raises(json.JSONDecodeError):
            json.loads(call['arguments'])  # the harness still sees the real parse failure


@pytest.mark.parametrize('value', [None, False, 0, [], {'cmd': 'echo safe'}])
def test_structured_argument_values_are_serialized_without_empty_object_substitution(value):
    assert json.loads(responses._as_args_str(value)) == value
