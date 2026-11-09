"""First-turn inventory through both public HTTP APIs and a real harness shell."""
import json
import subprocess

import pytest

from cria.config import Backend, Role, RoutingConfig
from test_server_config_http import Wire


@pytest.mark.parametrize('responses', [False, True])
def test_initial_inventory_round_trip_reaches_coder(tmp_path, responses, monkeypatch):
    from cria import system1wiring
    monkeypatch.setattr(system1wiring, 'build', lambda *args, **kwargs: None)
    root = tmp_path / 'workspace'
    root.mkdir()
    (root / 'seed.py').write_text('class Sample:\n    pass\n')
    shell = {'name': 'exec_command', 'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}, 'required': ['cmd']}}
    env = f'<environment_context><cwd>{root}</cwd></environment_context>'
    task = 'Implement the feature __TOOL__'
    if responses:
        path = '/v1/responses'
        request = {'model': 'm', 'prompt_cache_key': 'inventory', 'tools': [{'type': 'function', **shell}],
                   'input': [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': text}]} for text in (env, task)]}
    else:
        path = '/v1/chat/completions'
        request = {'model': 'm', 'tools': [{'type': 'function', 'function': shell}],
                   'messages': [{'role': 'user', 'content': text} for text in (env, task)]}
    wire = Wire(tmp_path, routing=lambda url: RoutingConfig(backends={'local': Backend('local')},
        roles={'classifier': Role('classifier', 'local'), 'coder': Role('coder', 'local')},
        failover={'coding': ('coder',)}, engagement_bias='task', engagement_level=5))
    try:
        for _ in range(100):
            _, raw = wire.post(path, request, sid='inventory')
            response = json.loads(raw)
            if responses:
                calls = [item for item in response['output'] if item.get('type') == 'function_call']
                assert calls
                call = calls[0]
                args = json.loads(call['arguments'])
            else:
                message = response['choices'][0]['message']
                call = message['tool_calls'][0]
                args = json.loads(call['function']['arguments'])
            if '___CTX_GATE_' not in args.get('cmd', ''):
                break
            run = subprocess.run(['bash', '-c', args['cmd']], cwd=root, capture_output=True, text=True, check=True)
            if responses:
                request['input'].extend([call, {'type': 'function_call_output', 'call_id': call['call_id'], 'output': run.stdout}])
            else:
                request['messages'].extend([message, {'role': 'tool', 'tool_call_id': call['id'], 'content': run.stdout}])
        coder = [body for _, body in wire.fake.chats if any('⟦ctx:files⟧' in str(m.get('content')) and 'Sample' in str(m.get('content')) for m in body.get('messages', []))]
        assert coder
        assert any(task in str(m.get('content')) for m in coder[0]['messages'])
        assert all('___CTX_GATE_' not in json.dumps(message) for message in coder[0]['messages'])
        assert not any(message.get('role') == 'tool' for message in coder[0]['messages'])
    finally:
        wire.close()
