"""Independent native named-choice contract, including real producer conversions."""
import copy
import pytest
from test_localai_tool_template import READ, WRITE, calls, envelope, native_probe, request


def api_request(endpoint, choice='named'):
    if endpoint == 'chat':
        tool_choice = {'type': 'function', 'function': {'name': 'read_file'}} if choice == 'named' else choice
        return request(tool_choice=tool_choice)
    if endpoint == 'responses':
        return {'input': 'Read notes.txt.', 'tools': [dict(type='function', **copy.deepcopy(t['function'])) for t in (READ, WRITE)],
                'tool_choice': {'type': 'function', 'name': 'read_file'} if choice == 'named' else choice,
                'parallel_tool_calls': False}
    return {'messages': [{'role': 'user', 'content': 'Read notes.txt.'}],
            'tools': [{'name': t['function']['name'], 'description': t['function']['description'],
                       'input_schema': copy.deepcopy(t['function']['parameters'])} for t in (READ, WRITE)],
            'tool_choice': {'type': 'tool', 'name': 'read_file'} if choice == 'named' else {'type': {'auto': 'auto', 'required': 'any', 'none': 'none'}[choice]},
            'max_tokens': 1024}


@pytest.mark.parametrize('endpoint', ['chat', 'responses', 'anthropic'])
@pytest.mark.parametrize('enabled', [False, True])
def test_named_function_restricts_native_grammar_and_parser(native_probe, endpoint, enabled):
    body = api_request(endpoint)
    original = copy.deepcopy(body)
    right = envelope('read_file', {'path': 'notes.txt'})
    result = native_probe(right, body=body, endpoint=endpoint, enabled=enabled, grammar=right, prefixes=True)
    assert body == original
    assert result['caller_menu_unchanged']
    assert result['caller_request_unchanged']
    assert result['active_name'] == ''
    assert result['complete_parse']
    assert result['grammar_accepts']
    assert calls(result) == [{'name': 'read_file', 'arguments': {'path': 'notes.txt'}}]
    wrong = envelope('write_file', {'path': 'notes.txt', 'content': 'wrong action'})
    rejected = native_probe(wrong, body=body, endpoint=endpoint, enabled=enabled, grammar=wrong)
    assert not rejected['complete_parse']
    assert not rejected['grammar_accepts']
    assert 'write_file' not in result['grammar']


@pytest.mark.parametrize('endpoint', ['chat', 'responses', 'anthropic'])
@pytest.mark.parametrize('name', ['unknown', '', None, 7, ['read_file']])
def test_named_function_invalid_or_unknown_names_are_request_errors(native_probe, endpoint, name):
    body = api_request(endpoint)
    if endpoint == 'chat':
        body['tool_choice']['function']['name'] = name
    else:
        body['tool_choice']['name'] = name
    original = copy.deepcopy(body)
    result = native_probe(body=body, endpoint=endpoint)
    assert 'request_error' in result
    assert result['request_error_wire']['code'] == 400
    assert body == original


@pytest.mark.parametrize('endpoint', ['chat', 'responses', 'anthropic'])
def test_named_function_missing_name_rejected(native_probe, endpoint):
    body = api_request(endpoint)
    if endpoint == 'chat':
        del body['tool_choice']['function']['name']
    else:
        del body['tool_choice']['name']
    result = native_probe(body=body, endpoint=endpoint)
    assert result['request_error_wire']['code'] == 400


@pytest.mark.parametrize('malformed', [[], 7, True, {'type': 'function'},
                                      {'type': 'tool', 'function': {'name': 'read_file'}},
                                      {'type': 'function', 'function': 'read_file'},
                                      {'type': 'function', 'function': {'name': 'read_file', 'other': True}},
                                      {'type': 'function', 'function': {'name': 'read_file'}, 'other': True}])
def test_malformed_chat_named_shape_rejected(native_probe, malformed):
    result = native_probe(body=request(tool_choice=malformed))
    assert result['request_error_wire']['code'] == 400


@pytest.mark.parametrize('endpoint', ['chat', 'responses', 'anthropic'])
@pytest.mark.parametrize('choice', ['auto', 'required', 'none'])
def test_choice_modes_keep_their_meaning_and_protocol_gate(native_probe, endpoint, choice):
    body = api_request(endpoint, choice)
    raw = envelope('write_file', {'path': 'notes.txt', 'content': 'allowed action'})
    result = native_probe(raw, body=body, endpoint=endpoint, grammar=raw)
    assert result['active_name'] == ('answer' if choice == 'auto' else '')
    if choice == 'none':
        assert result['content'] == raw
        assert result['calls'] == []
    else:
        assert result['complete_parse']
        assert result['grammar_accepts']
        assert calls(result)[0]['name'] == 'write_file'


def test_named_generation_preserves_caller_history(native_probe):
    body = api_request('chat')
    body['messages'] += [{'role': 'assistant', 'content': '', 'tool_calls': [
        {'type': 'function', 'id': 'old_write', 'function': {'name': 'write_file', 'arguments': '{"path":"notes.txt","content":"prior bytes"}'}}]},
        {'role': 'tool', 'tool_call_id': 'old_write', 'content': 'Actual previous write result.'}]
    result = native_probe(envelope('read_file', {'path': 'notes.txt'}), body=body)
    assert result['converted_request'] == body
    assert result['caller_request_after'] == body
    assert '"name": "write_file", "arguments": {"path": "notes.txt", "content": "prior bytes"}' in result['prompt']
    assert 'Actual previous write result.' in result['prompt']
    assert 'write_file' not in result['grammar']


def test_named_choice_rejects_reserved_menu_override(native_probe):
    body = api_request('chat')
    body['chat_template_kwargs'] = {'tools': [copy.deepcopy(WRITE)]}
    result = native_probe(body=body, enabled=False)
    assert 'reserved template argument' in result['request_error']
    assert result['request_error_wire']['code'] == 400


def test_anthropic_named_parallel_option_is_preserved(native_probe):
    body = api_request('anthropic')
    body['tool_choice']['disable_parallel_tool_use'] = True
    raw = envelope('read_file', {'path': 'notes.txt'})
    assert native_probe(raw, body=body, endpoint='anthropic')['complete_parse']
    assert not native_probe(raw + raw, body=body, endpoint='anthropic')['complete_parse']
    body['tool_choice']['disable_parallel_tool_use'] = False
    result = native_probe(raw + raw, body=body, endpoint='anthropic', grammar=raw + raw)
    assert result['complete_parse']
    assert result['grammar_accepts']
    assert len(calls(result)) == 2


def test_named_caller_answer_remains_a_caller_tool(native_probe):
    import json
    from test_localai_tool_template import ANSWER
    definition = json.loads(ANSWER.read_text())
    body = request(tools=[definition], tool_choice={'type': 'function', 'function': {'name': 'answer'}})
    raw = envelope('answer', {'message': 'caller owned'})
    result = native_probe(raw, body=body, grammar=raw)
    assert result['active_name'] == ''
    assert calls(result) == [{'name': 'answer', 'arguments': {'message': 'caller owned'}}]
    assert result['content'] == ''
    assert result['grammar_accepts']
    assert result['buffered_wire']['choices'][0]['finish_reason'] == 'tool_calls'


@pytest.mark.parametrize('endpoint', ['chat', 'responses'])
@pytest.mark.parametrize('schema', [{'response_format': {'type': 'json_object'}},
                                    {'json_schema': {'type': 'object'}},
                                    {'response_format': {'type': 'json_schema', 'json_schema': {'schema': {'type': 'object'}}}}])
def test_named_choice_with_standalone_schema_is_unsupported_before_generation(native_probe, endpoint, schema):
    body = api_request(endpoint)
    body.update(copy.deepcopy(schema))
    result = native_probe('{}', body=body, endpoint=endpoint, grammar='{}')
    assert 'unsupported by this serving path' in result['request_error']
    assert result['request_error_wire']['code'] == 400
    assert 'prompt' not in result
