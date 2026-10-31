"""Real Loop provider assembly and canonical lowering under root selection."""
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cria import assistruntime, loop, shrinkprotection, toolstages, writeproxy
from test_shrink_protection_policy import FRAGMENT, View


SHELL = {'name': 'bash', 'parameters': {'type': 'object', 'properties': {
    'command': {'type': 'string'}}, 'required': ['command']}}
REAL_VIEW = loop.wsview.current


def scoped_view(root=None):
    return View() if root else REAL_VIEW()


def foundation_view_only(root=None):
    if root:
        raise AssertionError('original shrink view')
    return REAL_VIEW()


def driver(runtime):
    sess = SimpleNamespace(first_survey_files={'file.txt'}, shrink_write_judged={})
    instance = loop.Loop.__new__(loop.Loop)
    instance._ctx = SimpleNamespace(pilot_runtime=runtime, assists=True,
                                    reasoner_chat=Mock(), reasoner_role=Mock())
    instance._store = SimpleNamespace(get=Mock(return_value=sess))
    return instance, sess


def lower(services, log):
    comp = {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
        'content': None, 'tool_calls': [{'id': 'w', 'type': 'function', 'function': {
            'name': 'write_file', 'arguments': json.dumps({'path': 'file.txt', 'content': FRAGMENT})}}]}}]}
    writeproxy.translate_outbound(comp, SHELL, log, injected={'write_file', 'edit_file'},
                                  shrink_services=services)
    return comp['choices'][0]['message']['tool_calls'][0]['function']['arguments']


def test_actual_loop_services_are_lazy_and_shared_closed_reader_owns_semantics():
    runtime = assistruntime.AssistRuntime.select()
    instance, sess = driver(runtime)
    log = Mock()
    view = Mock(side_effect=scoped_view)
    with assistruntime.bound(runtime), patch.object(loop.wsview, 'current', view), \
            patch.object(loop, 'ask_closed', return_value='OTHER') as ask:
        services = instance.shrinking_write_services('session', [], '/workspace', log)
        instance._store.get.assert_not_called()
        view.assert_not_called()
        ask.assert_not_called()
        result = lower(services, log)
        assert 'python3 -c' in result
        instance._store.get.assert_called_once_with('session')
        assert sum(call.args == ('/workspace',) for call in view.call_args_list) == 1
        assert ask.call_args.args[:2] == (instance._ctx.reasoner_chat, instance._ctx.reasoner_role)
        assert FRAGMENT in ask.call_args.args[2]
        assert ask.call_args.kwargs == {'phase': 'write-shrink',
            'max_tokens': loop.JUDGE_MAX_TOKENS, 'retry_off': False}
    assert sess.shrink_write_judged == {}


def test_actual_root_disabled_shrink_never_assembles_or_reads_services():
    runtime = assistruntime.AssistRuntime.select(disabled=(shrinkprotection.DEFINITION.policy.id,))
    instance, sess = driver(runtime)
    with assistruntime.bound(runtime), \
            patch.object(loop.wsview, 'current', side_effect=foundation_view_only), \
            patch.object(loop, 'ask_closed', side_effect=AssertionError('disabled question')):
        assert instance.shrinking_write_services('session', [], '/workspace', Mock()) is None
        assert instance.shrinking_write_check('session', [], '/workspace', Mock()) is None
        assert 'python3 -c' not in lower(None, Mock())
    instance._store.get.assert_not_called()
    assert sess.shrink_write_judged == {}


def test_root_semantic_replacement_executes_instead_of_original_whole_policy():
    calls = []
    def replacement(source, command):
        calls.append(source.request.shrink_services)
        return command + '\n# chosen whole-policy replacement'
    selected = replace(shrinkprotection.DEFINITION, execute=replacement)
    runtime = assistruntime.AssistRuntime.select()
    runtime = replace(runtime, ordered_stages=tuple(
        selected if d.policy.id == selected.policy.id else d for d in runtime.ordered_stages))
    instance, sess = driver(runtime)
    with assistruntime.bound(runtime), \
            patch.object(loop.wsview, 'current', side_effect=foundation_view_only), \
            patch.object(loop, 'ask_closed', side_effect=AssertionError('original question')):
        services = instance.shrinking_write_services('session', [], '/workspace', Mock())
        assert 'chosen whole-policy replacement' in lower(services, Mock())
    assert calls == [services]
    instance._store.get.assert_not_called()
    assert sess.shrink_write_judged == {}
