"""First-turn inventory through both public HTTP APIs and a real harness shell."""
import json
from pathlib import Path
import subprocess

import pytest

from cria.config import Backend, Role, RoutingConfig
from test_server_config_http import Wire


@pytest.mark.parametrize('responses', [False, True])
@pytest.mark.parametrize('mode', ['small', 'served', 'keyed', 'missing-key', 'fallback', 'experiment'])
def test_initial_inventory_round_trip_reaches_coder(tmp_path, responses, mode, monkeypatch):
    large = mode != 'small'
    if mode == 'keyed':
        monkeypatch.setenv('INVENTORY_TEST_KEY', 'test-key')
    else:
        monkeypatch.delenv('INVENTORY_TEST_KEY', raising=False)
    from cria import system1wiring
    monkeypatch.setattr(system1wiring, 'build', lambda *args, **kwargs: None)
    root = tmp_path / 'workspace'
    root.mkdir()
    (root / 'seed.py').write_text('class Sample:\n    pass\n')
    if mode == 'experiment':
        (root / 'c').mkdir()
        (root / 'c' / 'pytest.ini').write_text('')
    if large:
        for i in range(130):
            (root / (f'{i:03d}-' + 'a' * 90)).write_text('')
    shell = {'name': 'exec_command', 'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}, 'required': ['cmd']}}
    env = f'<environment_context><cwd>{root}</cwd></environment_context>'
    task = 'Implement the feature __TOOL__'
    if mode == 'experiment':
        recorded = json.loads((Path(__file__).parent / 'fixtures' / 'inventory_reasoner_experiment_request.json').read_text())
        task = recorded['messages'][0]['content'].split('\ntask: ', 1)[1].split('\ncandidate: ', 1)[0]
    if responses:
        path = '/v1/responses'
        request = {'model': 'm', 'prompt_cache_key': 'inventory', 'tools': [{'type': 'function', **shell}],
                   'input': [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': text}]} for text in (env, task)]}
    else:
        path = '/v1/chat/completions'
        request = {'model': 'm', 'tools': [{'type': 'function', 'function': shell}],
                   'messages': [{'role': 'user', 'content': text} for text in (env, task)]}
    wire = Wire(tmp_path, routing=lambda url: RoutingConfig(backends={
        'local': Backend('local'),
        'remote': Backend('remote', base_url=url, api_key_env='INVENTORY_TEST_KEY', model='configured-remote-model')},
        roles={'classifier': Role('classifier', 'local'), 'coder': Role('coder', 'local'),
               'compactor': Role('compactor', 'local', temperature=0.23),
               'reasoner': Role('reasoner', 'remote' if mode in ('keyed', 'missing-key', 'fallback') else 'local',
                                temperature=0.8 if mode == 'experiment' else None,
                                top_p=0.95 if mode == 'experiment' else None,
                                reasoning='on' if mode == 'experiment' else 'auto')},
        failover={'coding': ('coder',), **({'reasoning': ('reasoner', 'compactor')} if mode == 'fallback' else {})}, engagement_bias='task', engagement_level=5))
    try:
        for _ in range(100):
            _, raw = wire.post(path, request, sid='inventory')
            response = json.loads(raw)
            if responses:
                calls = [item for item in response['output'] if item.get('type') == 'function_call']
                assert calls
                private = [c for c in calls if str(c['call_id']).startswith('ctx_')]
                if not private:
                    break
                for call in private:
                    run = subprocess.run(['bash', '-c', json.loads(call['arguments'])['cmd']], cwd=root, capture_output=True, text=True, check=True)
                    request['input'].extend([call, {'type': 'function_call_output', 'call_id': call['call_id'], 'output': run.stdout}])
            else:
                message = response['choices'][0]['message']
                private = [c for c in message['tool_calls'] if str(c['id']).startswith('ctx_')]
                if not private:
                    break
                request['messages'].append(message)
                for call in private:
                    run = subprocess.run(['bash', '-c', json.loads(call['function']['arguments'])['cmd']], cwd=root, capture_output=True, text=True, check=True)
                    request['messages'].append({'role': 'tool', 'tool_call_id': call['id'], 'content': run.stdout})
        judgments = [body for _, body in wire.fake.chats if body.get('tool_choice') == 'required']
        if large and mode != 'missing-key':
            assert len(judgments) == (132 if mode == 'experiment' else 131)
            assert all('task: ' + task in b['messages'][0]['content'] for b in judgments)
            expected_model = 'configured-remote-model' if mode == 'keyed' else 'loaded'
            assert all(b['model'] == expected_model and b['stream'] is False for b in judgments)
            if mode == 'fallback':
                assert all(b['temperature'] == 0.23 for b in judgments)
            if mode == 'keyed':
                assert all(headers.get('Authorization') == 'Bearer test-key' for headers, b in wire.fake.chats if b.get('tool_choice') == 'required')
            if mode == 'experiment':
                actual = next(b for b in judgments if '\ncandidate: c/pytest.ini |' in b['messages'][0]['content'])
                expected = dict(recorded)
                expected['model'] = 'loaded'
                expected.pop('seed')
                expected['messages'] = [{'role': 'user', 'content': recorded['messages'][0]['content'].replace(
                    'c/pytest.ini | unsupported (non-Python)', 'c/pytest.ini | symbols unavailable')}]
                assert actual == expected
            assert all(len(b['messages']) == 1 and b['messages'][0]['role'] == 'user' for b in judgments)
        else:
            assert not judgments
        coder = [body for _, body in wire.fake.chats if any('⟦ctx:files⟧' in str(m.get('content')) for m in body.get('messages', []))]
        assert coder
        if mode != 'missing-key':
            assert 'seed.py' in json.dumps(coder[0]['messages'])
        if large and mode != 'missing-key':
            assert 'selected by the configured reasoner' in json.dumps(coder[0]['messages'])
        if mode == 'missing-key':
            assert 'No reasoner-selected paths' in json.dumps(coder[0]['messages'])
        assert any(task in str(m.get('content')) for m in coder[0]['messages'])
        assert all('___CTX_GATE_' not in json.dumps(message) for message in coder[0]['messages'])
        assert not any(message.get('role') == 'tool' for message in coder[0]['messages'])
    finally:
        wire.close()
