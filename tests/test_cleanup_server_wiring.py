import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cria.server import CriaHandler
from cria import server, writeproxy


def test_server_supplies_reasoner_only_when_tripwire_fires():
    handler = object.__new__(CriaHandler)
    handler.server = SimpleNamespace(reasoner_role=object(), reasoner_upstream=SimpleNamespace(chat=Mock()),
                                     cfg=SimpleNamespace(safety=SimpleNamespace(external_dir_permission='none')))
    handler._shell_tool = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
    handler._synthetic = {'write_file'}
    handler._workspace_root = '/remote/workspace'
    handler._cleanup_task = 'Build an application; preserve unrelated files.'
    def completion(content):
        return {'choices': [{'message': {'tool_calls': [{'id': 't', 'type': 'function', 'function': {
            'name': 'write_file', 'arguments': json.dumps({'path': 'app.any', 'content': content})}}]}}]}
    source = 'fs.rmSync("/", {recursive:true});'
    verdict = json.dumps(dict(verdict='UNSAFE', evidence=source, reason='Recursive root cleanup.', target='/'))
    with patch.object(server, 'ask_closed', return_value=verdict) as ask, \
            patch.object(writeproxy, '_survey_due', return_value=False), \
            patch.object(writeproxy, '_litter_leg', return_value=''):
        handler._translate_out(completion('ordinary content'), 'sid:one', Mock())
        ask.assert_not_called()
        result = handler._translate_out(completion(source), 'sid:one', Mock())
        ask.assert_called_once()
        assert source in ask.call_args.args[2]
        assert handler._cleanup_task in ask.call_args.args[2]
        args = result['choices'][0]['message']['tool_calls'][0]['function']['arguments']
        assert 'withheld' in args
        assert ask.call_args.kwargs['retry_off'] is False
