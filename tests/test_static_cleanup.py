"""Analyze incident source as data, never import or execute it."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cria import cleanupsafety, writeproxy
from cria.server import CriaHandler

INCIDENT = (Path(__file__).parent / 'fixtures/incident_parent_cleanup.py.txt').read_text()


def test_incident_blocks_without_a_reasoner():
    handler = object.__new__(CriaHandler)
    handler.server = SimpleNamespace(reasoner_role=None, cfg=SimpleNamespace(
        safety=SimpleNamespace(external_dir_permission='none')))
    handler._shell_tool = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
    handler._synthetic = {'write_file'}
    handler._workspace_root = '/remote/project'
    completion = {'choices': [{'message': {'tool_calls': [{'id': 'one', 'type': 'function',
        'function': {'name': 'write_file', 'arguments': json.dumps(
            {'path': 'tests/test_http.py', 'content': INCIDENT})}}]}}]}
    log = Mock()
    with patch('cria.server.ask_closed', side_effect=AssertionError('no inference allowed')):
        result = handler._translate_out(completion, 'sid:static-incident', log)
    cmd = json.loads(result['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['cmd']
    assert writeproxy._write_command('tests/test_http.py', INCIDENT) not in cmd
    assert 'withheld' in cmd
