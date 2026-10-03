"""The server must not call a reasoner for filesystem safety, even if configured."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cria.server import CriaHandler


def test_server_uses_static_analysis_not_configured_reasoner():
    handler = object.__new__(CriaHandler)
    handler.server = SimpleNamespace(reasoner_role=object(), reasoner_upstream=SimpleNamespace(
        chat=Mock(side_effect=AssertionError('no inference allowed'))),
        cfg=SimpleNamespace(safety=SimpleNamespace(external_dir_permission='none')))
    handler._shell_tool = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
    handler._synthetic = {'write_file'}
    handler._workspace_root = '/remote/workspace'
    def completion(content):
        return {'choices': [{'message': {'tool_calls': [{'id': 't', 'type': 'function', 'function': {
            'name': 'write_file', 'arguments': json.dumps({'path': 'app.py', 'content': content})}}]}}]}
    with patch('cria.server.ask_closed', side_effect=AssertionError('no inference allowed')):
        ordinary = handler._translate_out(completion('value=1'), 'sid:one', Mock())
        result = handler._translate_out(completion('import shutil\nshutil.rmtree("/")'), 'sid:one', Mock())
    assert 'withheld' not in ordinary['choices'][0]['message']['tool_calls'][0]['function']['arguments']
    assert 'withheld' in result['choices'][0]['message']['tool_calls'][0]['function']['arguments']
    handler.server.reasoner_upstream.chat.assert_not_called()
