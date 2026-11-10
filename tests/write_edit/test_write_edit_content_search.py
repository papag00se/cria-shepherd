"""Search tools are advertised only when the harness has none of its own, and a call the model makes is the call it sees. (What a search finds, skips and says is
tests/harness_primitives/test_search_ops.py and, against the program it replaced, test_search_characterization.py.)"""
import json

from cria import massage, toolmenu, writeproxy


def test_search_tools_are_only_advertised_when_not_native():
    body = {'tools': [{'type': 'function', 'function': {'name': 'grep', 'parameters': {'type': 'object'}}}]}
    injected = writeproxy.advertise(body)
    assert 'grep' not in injected and 'glob' in injected
    assert sum(t['function']['name'] == 'grep' for t in body['tools']) == 1
    native_write = {'tools': [{'type': 'function', 'function': {'name': 'write_file'}}, {'type': 'function', 'function': {'name': 'grep'}}]}
    assert writeproxy.advertise(native_write, search_only=True) == {'glob'}
    assert {t['function']['name'] for t in native_write['tools']} == {'write_file', 'grep', 'glob'}


def test_menu_normalization_and_native_calls_remain_distinct():
    issue_search = lambda call, args: {'id': 'ctx_x', 'type': 'function', 'function': {'name': 'exec_command', 'arguments': json.dumps({'cmd': 'true'})}}     # the engine's first call
    shell = {'type': 'function', 'function': {'name': 'exec_command', 'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}}
    body = {'tools': [shell]}
    injected = writeproxy.advertise(body)
    toolmenu.focus_tools(body)
    tools = body['tools']
    call = {'id': 'x', 'type': 'function', 'function': {'name': 'grep', 'arguments': json.dumps({'pattern': 'x'})}}
    completion = {'choices': [{'message': {'tool_calls': [call]}}]}
    normalized = massage.apply(completion, tools)
    assert normalized['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'grep'
    writeproxy.translate_outbound(normalized, {'name': 'exec_command', 'schema': shell['function']['parameters']}, injected=injected, issue_search=issue_search)
    assert normalized['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'exec_command'
    native_call = {'id': 'y', 'type': 'function', 'function': {'name': 'grep', 'arguments': json.dumps({'pattern': 'x'})}}
    native = {'choices': [{'message': {'tool_calls': [native_call]}}]}
    writeproxy.translate_outbound(native, {'name': 'exec_command', 'schema': shell['function']['parameters']}, injected=set())
    assert native['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'grep'
    native_write = {'id': 'z', 'type': 'function', 'function': {'name': 'write_file', 'arguments': '{"path":"x","content":"abc"}'}}
    mixed = {'choices': [{'message': {'tool_calls': [native_write, native_call]}}]}
    writeproxy.translate_outbound(mixed, {'name': 'exec_command', 'schema': shell['function']['parameters']}, injected={'grep'}, only_injected=True, issue_search=issue_search)
    assert mixed['choices'][0]['message']['tool_calls'][0] == native_write
    assert mixed['choices'][0]['message']['tool_calls'][1]['function']['name'] == 'exec_command'
