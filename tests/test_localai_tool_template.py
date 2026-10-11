"""Optional native CPU integration: matching private headers/libraries, no weights or inference."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'cria/prompts/localai_functioncall_chat.jinja.txt'
ANSWER = ROOT / 'cria/prompts/localai_functioncall_answer_tool.txt'
FIXTURES = ROOT / 'tests/fixtures'
READ = {'type': 'function', 'function': {'name': 'read_file', 'description': 'Read a file', 'parameters': {
    'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}}}
WRITE = {'type': 'function', 'function': {'name': 'write_file', 'description': 'Write a file', 'parameters': {
    'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}},
    'required': ['path', 'content']}}}


def envelope(name, arguments):
    return '<Output>' + json.dumps({'name': name, 'arguments': arguments}, ensure_ascii=False) + '</Output>'


def request(**changes):
    body = {'messages': [{'role': 'system', 'content': 'Keep this exact caller instruction.'},
                         {'role': 'user', 'content': 'Read notes.txt.'}],
            'tools': [copy.deepcopy(READ), copy.deepcopy(WRITE)],
            'tool_choice': 'auto', 'parallel_tool_calls': False, 'stream': False}
    body.update(changes)
    return body


@pytest.fixture(scope='module')
def native_probe(tmp_path_factory):
    source = os.environ.get('LOCALAI_PROBE_SOURCE')
    library = os.environ.get('LOCALAI_PROBE_LIBRARY')
    if not source or not library:
        pytest.skip('set LOCALAI_PROBE_SOURCE and LOCALAI_PROBE_LIBRARY to the matching private CPU build')
    source, library = Path(source), Path(library)
    assert shutil.which('c++'), 'CPU integration requested but c++ is missing'
    assert (source / 'common/chat.h').is_file()
    assert (library / 'libllama-server-impl.so').is_file()
    directory = tmp_path_factory.mktemp('localai-native')
    binary = directory / 'probe'
    compile_command = ['c++', '-std=c++17', *['-I' + str(source / p) for p in (
        'common', 'include', 'ggml/include', 'vendor', 'src', 'tools/server', 'tools/mtmd')],
        str(FIXTURES / 'localai_template_probe.cpp'), '-L' + str(library),
        '-Wl,-rpath,' + str(library), '-lllama-server-impl', '-lllama-common', '-lmtmd',
        '-lllama', '-lggml', '-lggml-base', '-o', str(binary)]
    completed = subprocess.run(compile_command, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr

    def parse(text='', *, parallel=False, body=None, enabled=True, prefixes=False, grammar=None, definition=None,
              template_text=None, raw_endpoint=False, stop_limit=False, endpoint='chat'):
        answer_path = ANSWER
        if definition is not None:
            answer_path = directory / 'custom-tool.json'
            answer_path.write_text(json.dumps(definition, ensure_ascii=False))
        template_path = TEMPLATE
        if template_text is not None:
            template_path = directory / 'custom-template.jinja'
            template_path.write_text(template_text)
        case = {'request': body if body is not None else request(parallel_tool_calls=parallel),
                'output': text, 'prefixes': prefixes, 'raw_endpoint': raw_endpoint,
                'stop_limit': stop_limit, 'endpoint': endpoint}
        if grammar is not None:
            case['grammar_output'] = grammar
        completed = subprocess.run([str(binary), str(template_path), str(answer_path) if enabled else '-'],
                                   input=json.dumps(case, ensure_ascii=False), capture_output=True, text=True,
                                   env={**os.environ, 'LD_LIBRARY_PATH': str(library)})
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)
    return parse


def calls(result):
    return [{'name': call['name'], 'arguments': json.loads(call['arguments_raw'])} for call in result['calls']]


def assert_prefixes(result, *, answer=False):
    assert len(result['prefixes']) == len(result['raw'].encode()) + 1
    arguments = {}
    for prefix in result['prefixes']:
        assert 'error' not in prefix, prefix
        assert prefix['append_only']
        assert prefix['nondecreasing_calls']
        assert all(event['choices'][0]['finish_reason'] is None for event in prefix['partial_wire'])
        for delta in prefix['argument_deltas']:
            arguments[delta['index']] = arguments.get(delta['index'], '') + delta['hex']
        for index, call in enumerate(prefix['calls']):
            assert arguments.get(index, '') == call['arguments_hex']
        assert all(call['name'] for call in prefix['calls'])
        assert all(call['name'] != result['active_name'] for call in prefix['calls'])
        if answer:
            assert prefix['calls'] == []
            assert prefix['ids'] == []
            assert all('tool_calls' not in delta for delta in prefix['deltas'])
    assert result['streamed']['content'] == result['content']
    assert result['streamed']['reasoning'] == result['reasoning']


def test_native_call_and_separate_thought(native_probe):
    result = native_probe('<Thought>I need the real file.</Thought>' + envelope('read_file', {'path': 'notes.txt'}), prefixes=True)
    assert result['complete_parse']
    assert calls(result) == [{'name': 'read_file', 'arguments': {'path': 'notes.txt'}}]
    assert result['reasoning'] == 'I need the real file.'
    assert result['content'] == ''
    assert_prefixes(result)
    assert result['buffered_wire']['choices'][0]['finish_reason'] == 'tool_calls'
    assert result['streamed_final_wire'][-1]['choices'][0]['finish_reason'] == 'tool_calls'
    # At least one prefix delivers arguments before the complete call has arrived.
    assert any(p['calls'] and p['calls'][0]['arguments_raw'] not in ('', '{')
               for p in result['prefixes'][:-1])


def test_call_without_thought(native_probe):
    result = native_probe(envelope('read_file', {'path': 'notes.txt'}))
    assert calls(result) == [{'name': 'read_file', 'arguments': {'path': 'notes.txt'}}]
    assert result['reasoning'] == ''


def test_unicode_newline_and_quote_arguments(native_probe):
    arguments = {'path': 'notes.txt', 'content': 'snow 雪\n"quoted"\nbackslash \\ </Output>'}
    result = native_probe(envelope('write_file', arguments), prefixes=True)
    assert calls(result) == [{'name': 'write_file', 'arguments': arguments}]
    assert_prefixes(result)


def test_serial_turn_rejects_a_second_call(native_probe):
    call = envelope('read_file', {'path': 'notes.txt'})
    assert native_probe(call, grammar=call)['grammar_accepts']
    result = native_probe(call + call, grammar=call + call)
    assert not result['grammar_accepts']
    assert not result['complete_parse']
    assert (call + call).encode().hex() in result['parse_error']


def test_parallel_turn_preserves_both_calls(native_probe):
    call = envelope('read_file', {'path': 'notes.txt'})
    result = native_probe(call + call, parallel=True, prefixes=True, grammar=call + call)
    assert result['complete_parse']
    assert result['grammar_accepts']
    assert calls(result) == [{'name': 'read_file', 'arguments': {'path': 'notes.txt'}}] * 2
    assert_prefixes(result)


def test_plain_answer_remains_content(native_probe):
    text = 'The file contains snow 雪\nand a second line.'
    result = native_probe(text, prefixes=True)
    assert result['content'] == text
    assert result['calls'] == []
    assert_prefixes(result, answer=True)


def test_done_reasoning_then_wrapped_answer_is_not_a_call(native_probe):
    result = native_probe('<Thought>I read the real result.</Thought>' + envelope('answer', {'message': 'The contents match.'}), prefixes=True)
    assert result['complete_parse']
    assert result['reasoning'] == 'I read the real result.'
    assert result['content'] == 'The contents match.'
    assert result['calls'] == []
    assert_prefixes(result, answer=True)
    assert result['ids'] == []
    assert result['buffered_wire']['choices'][0]['finish_reason'] == 'stop'
    assert all(chunk['choices'][0]['finish_reason'] in (None, 'stop') for chunk in result['stream_final_wire'])
    assert result['streamed_final_wire'][-1]['choices'][0]['finish_reason'] == 'stop'
    assert all('tool_calls' not in chunk['choices'][0].get('delta', {}) for chunk in result['stream_final_wire'])


@pytest.mark.parametrize('message', ['', 'snow 雪\n"quoted"\nbackslash \\ </Output>\n',
                                     '{"result":true,"items":[1,2]}', ' 😀 \x00\t\r\n '])
def test_answer_message_decodes_exact_bytes_atomically(native_probe, message):
    answer = envelope('answer', {'message': message})
    result = native_probe(answer, prefixes=True, grammar=answer)
    assert result['complete_parse']
    assert result['grammar_accepts']
    assert result['content'] == message
    assert_prefixes(result, answer=True)
    assert all(p['content'] == '' for p in result['prefixes'][:-1])


def test_escaped_unicode_and_prior_content_survive(native_probe):
    answer = '<Output>{"name":"answer","arguments":{"message":"\\u96ea\\n\\\"q\\\"\\\\\\ud83d\\ude00"}}</Output>'
    result = native_probe('<Thought>Verified.</Thought>Earlier content. ' + answer, prefixes=True, grammar=answer)
    assert result['complete_parse']
    assert result['content'] == 'Earlier content. 雪\n"q"\\😀'
    assert result['reasoning'] == 'Verified.'
    assert_prefixes(result, answer=True)


@pytest.mark.parametrize('arguments', [{}, {'message': None}, {'message': 42}, {'message': []}, [], 'text'])
def test_invalid_answer_is_error_with_complete_raw_evidence(native_probe, arguments):
    raw = envelope('answer', arguments)
    result = native_probe(raw, prefixes=True, grammar=raw)
    assert not result['complete_parse']
    assert not result['grammar_accepts']
    assert raw.encode().hex() in result['parse_error']
    assert all(p.get('calls', []) == [] and p.get('ids', []) == [] for p in result['prefixes'])


@pytest.mark.parametrize('tail', ['{"message":"done"', '{"message":"done"}', '{"message":"do', '{"message":', '{}'])
def test_brace_completion_never_completes_answer(native_probe, tail):
    raw = '<Output>{"name":"answer","arguments":' + tail
    result = native_probe(raw, prefixes=True)
    assert not result['complete_parse']
    assert raw.encode().hex() in result['parse_error']
    assert all(p.get('content', '') == '' and p.get('calls', []) == [] for p in result['prefixes'])


@pytest.mark.parametrize('parallel', [False, True])
@pytest.mark.parametrize('answer_first', [False, True])
def test_mixed_answer_and_action_batch_rejected(native_probe, parallel, answer_first):
    answer = envelope('answer', {'message': 'done'})
    action = envelope('read_file', {'path': 'notes.txt'})
    raw = answer + action if answer_first else action + answer
    result = native_probe(raw, parallel=parallel, prefixes=True, grammar=raw)
    assert not result['complete_parse']
    assert not result['grammar_accepts']
    assert raw.encode().hex() in result['parse_error']
    assert all(p.get('name') != 'answer' for prefix in result['prefixes'] for p in prefix.get('calls', []))


@pytest.mark.parametrize('raw', [envelope('off_menu', {'path': 'notes.txt'}),
                               '<Output>{"name":"answer","arguments":{"message":"unterminated}}</Output>',
                               envelope('read_file', [])])
def test_off_menu_and_broken_argument_shape_rejected(native_probe, raw):
    result = native_probe(raw, grammar=raw)
    assert not result['complete_parse']
    assert not result['grammar_accepts']
    assert raw.encode().hex() in result['parse_error']


def test_active_collision_fails_closed(native_probe):
    body = request(tools=[copy.deepcopy(READ), json.loads(ANSWER.read_text())])
    result = native_probe(body=body)
    assert 'collides with caller tool: answer' in result['request_error']
    assert 'prompt' not in result


@pytest.mark.parametrize('choice', ['required', 'none'])
def test_inactive_choices_preserve_caller_answer_ownership(native_probe, choice):
    body = request(tools=[json.loads(ANSWER.read_text())], tool_choice=choice)
    raw = envelope('answer', {'message': 'caller owned'})
    on, off = native_probe(raw, body=body), native_probe(raw, body=body, enabled=False)
    for key in ('prompt', 'grammar', 'parser', 'grammar_triggers'):
        assert on[key] == off[key]
    assert on['active_name'] == ''
    if choice == 'required':
        assert calls(on) == [{'name': 'answer', 'arguments': {'message': 'caller owned'}}]
        assert on['content'] == ''
    else:
        assert on['content'] == raw
        assert on['calls'] == []


@pytest.mark.parametrize('changes', [{'tools': []}, {'tool_choice': 'required'}, {'tool_choice': 'none'},
                                     {'response_format': {'type': 'json_object'}},
                                     {'response_format': {'type': 'json_schema', 'json_schema': {'schema': {'type': 'object'}}}}])
def test_inactive_render_and_grammar_byte_identical(native_probe, changes):
    body = request(**changes)
    on, off = native_probe(body=body), native_probe(body=body, enabled=False)
    assert 'request_error' not in on, on
    for key in ('prompt', 'grammar', 'parser', 'grammar_lazy', 'grammar_triggers'):
        assert on[key] == off[key]
    assert on['active_name'] == ''


def test_definition_name_generic_and_loaded_from_file(native_probe):
    definition = json.loads(ANSWER.read_text())
    definition['function']['name'] = 'respond_without_action'
    result = native_probe(envelope('respond_without_action', {'message': 'done'}), definition=definition, prefixes=True)
    assert result['active_name'] == 'respond_without_action'
    assert result['content'] == 'done'
    assert_prefixes(result, answer=True)


@pytest.mark.parametrize('change', ['missing_required', 'wrong_type'])
def test_bad_definition_rejected_at_launch(native_probe, change):
    definition = json.loads(ANSWER.read_text())
    if change == 'missing_required':
        del definition['function']['parameters']['required']
    else:
        definition['function']['parameters']['properties']['message']['type'] = 'number'
    result = native_probe(definition=definition)
    assert 'Invalid --no-action-tool file' in result['request_error']


def test_effective_menu_matches_manual_render_golden(native_probe):
    body = json.loads((FIXTURES / 'localai_answer_menu_turn3.request.json').read_text())
    manual = native_probe(body=body, enabled=False)
    body['tools'].pop()
    response = json.loads((FIXTURES / 'localai_answer_menu_turn3.response.json').read_text())['choices'][0]['message']
    raw = '<Thought>' + response['reasoning_content'] + '</Thought>\n' + envelope('answer', json.loads(response['tool_calls'][0]['function']['arguments']))
    automatic = native_probe(raw, body=body, prefixes=True)
    assert automatic['prompt'] == manual['prompt'] == (FIXTURES / 'localai_answer_menu_turn3.prompt.txt').read_text()
    assert automatic['caller_menu_unchanged']
    assert automatic['content'] == 'The content of probe.txt matches the requested content.'
    assert automatic['reasoning'] == response['reasoning_content']
    assert_prefixes(automatic, answer=True)


@pytest.mark.parametrize('raw', [
    '<Thought>I read the real result.</Thought><Output>The contents match.</Output>',
    '<Output>\n{\n  "result": "The read result matches the requested content exactly."\n}\n</Output>',
])
def test_raw_wrapped_prose_characterization_stays_rejected(native_probe, raw):
    # Historical raw captures are preserved; this protocol promises canonical answer.message only.
    result = native_probe(raw)
    assert not result['complete_parse']
    assert raw.encode().hex() in result['parse_error']


def test_caller_instructions_and_real_result_survive(native_probe):
    body = request()
    body['messages'] += [{'role': 'assistant', 'content': '', 'tool_calls': [
        {'type': 'function', 'id': 'call1', 'function': {'name': 'read_file', 'arguments': '{"path":"notes.txt"}'}}]},
        {'role': 'tool', 'tool_call_id': 'call1', 'content': 'snow 雪\nsecond line'}]
    result = native_probe('Ready.', body=body)
    assert 'Keep this exact caller instruction.' in result['prompt']
    assert '<Output>{"name": "read_file", "arguments": {"path": "notes.txt"}}</Output>' in result['prompt']
    assert '<|im_start|>user<|im_sep|>\nsnow 雪\nsecond line<|im_end|>' in result['prompt']


def test_disabled_protocol_matches_serial_only_native_golden(native_probe):
    receipts = json.loads((FIXTURES / 'localai_serial_render_golden.json').read_text())
    for receipt in receipts:
        result = native_probe(body=receipt['request'], enabled=False)
        for key in ('prompt', 'grammar', 'parser', 'grammar_lazy'):
            assert result[key] == receipt['result'][key]


@pytest.mark.parametrize('parallel', [False, True])
def test_parallel_setting_does_not_allow_two_answers(native_probe, parallel):
    answer = envelope('answer', {'message': 'done'})
    result = native_probe(answer + answer, parallel=parallel, grammar=answer + answer)
    assert not result['complete_parse']
    assert not result['grammar_accepts']
    assert (answer + answer).encode().hex() in result['parse_error']


def test_disabled_caller_answer_is_a_real_tool(native_probe):
    body = request(tools=[json.loads(ANSWER.read_text())])
    result = native_probe(envelope('answer', {'message': 'caller owned'}), body=body, enabled=False)
    assert result['active_name'] == ''
    assert calls(result) == [{'name': 'answer', 'arguments': {'message': 'caller owned'}}]
    assert result['buffered_wire']['choices'][0]['finish_reason'] == 'tool_calls'


def test_collision_outside_activation_with_schema_preserves_render(native_probe):
    body = request(tools=[json.loads(ANSWER.read_text())], response_format={'type': 'json_object'})
    on, off = native_probe('{}', body=body), native_probe('{}', body=body, enabled=False)
    for key in ('prompt', 'grammar', 'parser', 'content'):
        assert on[key] == off[key]
    assert on['active_name'] == ''


def test_error_evidence_preserves_nul_bytes(native_probe):
    raw = envelope('off_menu', {'message': '雪'}) + '\x00after NUL\n'
    result = native_probe(raw)
    assert not result['complete_parse']
    assert raw.encode().hex() in result['parse_error']


def test_named_choice_preserves_selected_call_and_optin_exclusion(native_probe):
    body = request(tool_choice={'type': 'function', 'function': {'name': 'read_file'}})
    raw = envelope('read_file', {'path': 'notes.txt'})
    on, off = native_probe(raw, body=body), native_probe(raw, body=body, enabled=False)
    assert on['active_name'] == ''
    assert calls(on) == calls(off)
    for key in ('prompt', 'grammar', 'parser'):
        assert on[key] == off[key]


def test_omitted_tools_keeps_protocol_inactive(native_probe):
    body = request()
    del body['tools']
    on, off = native_probe('Ready.', body=body), native_probe('Ready.', body=body, enabled=False)
    assert on['active_name'] == ''
    for key in ('prompt', 'grammar', 'parser', 'content'):
        assert on[key] == off[key]


def test_default_automatic_choice_activates(native_probe):
    body = request()
    del body['tool_choice']
    result = native_probe(envelope('answer', {'message': 'done'}), body=body)
    assert result['active_name'] == 'answer'
    assert result['content'] == 'done'
