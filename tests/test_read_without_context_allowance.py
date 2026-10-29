import json
import subprocess

from cria import denial, loop, massage, writeproxy


def test_large_multiple_reads_are_not_allocated_context_room(tmp_path):
    text = 'abc界\r\n' * 5000
    (tmp_path / 'a').write_bytes(text.encode())
    calls = [{'id': str(i), 'type': 'function', 'function': {'name': 'read_file', 'arguments': json.dumps(args)}}
             for i, args in enumerate([{'path': 'a'}, {'path': 'a', 'start_line': 1, 'end_line': 5000}])]
    completion = {'choices': [{'message': {'tool_calls': calls}}]}
    shell = {'name': 'shell', 'schema': {'properties': {'command': {'type': 'string'}}}}
    writeproxy.translate_outbound(completion, shell, injected={'read_file'}, workspace_root=str(tmp_path))
    history = [{'role': 'assistant', 'tool_calls': completion['choices'][0]['message']['tool_calls']}]
    for call in history[0]['tool_calls']:
        command = json.loads(call['function']['arguments'])['command']
        result = subprocess.run(['bash', '-c', command], cwd=tmp_path, capture_output=True, text=True)
        assert result.returncode == 0
        history.append({'role': 'tool', 'tool_call_id': call['id'], 'content': result.stdout})
    shown = writeproxy.represent_inbound(history, workspace_root=str(tmp_path))
    assert shown[1]['content'] == text
    assert not denial.refused(shown[1]) and denial.refused(shown[2])
    assert denial.read_payload(shown[2]) is None
    args = json.loads(shown[2]['content'].split('Next read_file arguments: ', 1)[1])
    assert args['path'] == 'a' and args['start_line'] == 1 and 1 <= args['end_line'] < 5000
    retry = {'choices': [{'message': {'tool_calls': [{'id': 'retry', 'type': 'function', 'function': {'name': 'read_file', 'arguments': json.dumps(args)}}]}}]}
    writeproxy.translate_outbound(retry, shell, injected={'read_file'}, workspace_root=str(tmp_path))
    call = retry['choices'][0]['message']['tool_calls'][0]
    result = subprocess.run(['bash', '-c', json.loads(call['function']['arguments'])['command']], cwd=tmp_path, capture_output=True, text=True, check=True)
    retried = writeproxy.represent_inbound([{'role': 'assistant', 'tool_calls': [call]}, {'role': 'tool', 'tool_call_id': 'retry', 'content': result.stdout}], workspace_root=str(tmp_path))
    assert not denial.refused(retried[1])
    assert denial.read_payload(retried[1]) == ''.join(f'{i}: abc界\r\n' for i in range(1, args['end_line'] + 1))


def test_early_alias_keeps_typed_read_and_native_shell_is_not_read(tmp_path):
    text = 'long line\n' * 3000
    (tmp_path / 'a').write_text(text)
    shell = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}, 'max_output_tokens': {'type': 'number'}}}}
    menu = [{'type': 'function', 'function': {'name': 'exec_command', 'parameters': shell['schema']}}]
    original = {'choices': [{'message': {'tool_calls': [{'id': 'a', 'type': 'function', 'function': {
        'name': 'read_file', 'arguments': json.dumps({'path': 'a'})}}]}}]}
    alias = massage.apply(original, menu)['choices'][0]['message']['tool_calls'][0]
    native = {'id': 'n', 'type': 'function', 'function': {'name': 'exec_command', 'arguments': json.dumps({'cmd': 'printf native'})}}
    comp = {'choices': [{'message': {'tool_calls': [alias, native]}}]}
    writeproxy.translate_outbound(comp, shell, injected={'read_file'}, workspace_root=str(tmp_path))
    calls = comp['choices'][0]['message']['tool_calls']
    assert calls[1] == native
    assert 'max_output_tokens' not in json.loads(calls[0]['function']['arguments'])
    history = [{'role': 'assistant', 'tool_calls': calls}]
    for call in calls:
        command = json.loads(call['function']['arguments'])['cmd']
        result = subprocess.run(['bash', '-c', command], cwd=tmp_path, capture_output=True, text=True, check=True)
        history.append({'role': 'tool', 'tool_call_id': call['id'], 'content': result.stdout})
    shown = writeproxy.represent_inbound(history, workspace_root=str(tmp_path))
    assert denial.read_payload(shown[1]) == text
    assert 'a' in loop._extract_whole_reads(shown)
    assert shown[2]['content'] == 'native'
