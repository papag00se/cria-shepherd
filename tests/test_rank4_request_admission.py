"""Fresh production dispatch must not lose retained policies with classification off."""
import copy
import json
from unittest.mock import Mock

import pytest

from cria import admission, assistruntime, classify, loop, server
from cria.config import AssistConfig, Config, LoggingConfig, Role, RoutingConfig
from test_executable_assist_pilots import Log, TOOLS
from test_whole_task_review_boundaries import gate_reply


def completion(content='Done', call=False):
    message = {'role': 'assistant', 'content': content}
    if call:
        message['tool_calls'] = [{'id': 'inspect', 'type': 'function', 'function': {
            'name': 'exec_command', 'arguments': '{"cmd":"echo inspection"}'}}]
    return {'choices': [{'finish_reason': 'tool_calls' if call else 'stop', 'message': message}]}


@pytest.mark.parametrize('streaming', [False, True])
def test_fresh_dispatch_without_classifier_uses_coder_checks_and_review(tmp_path, monkeypatch, streaming):
    monkeypatch.setattr(server.ThreadingHTTPServer, '__init__', lambda *_a, **_k: None)
    coder, reasoner, shared = Mock(), Mock(), Mock()
    replies = iter([completion(), completion(), completion(call=True), completion(call=True)])
    coder.chat_watched.side_effect = lambda *_a, **_k: json.dumps(next(replies)).encode()
    shared.chat.side_effect = AssertionError('coding request escaped to shared proxy')
    shared.stream_chat.side_effect = AssertionError('coding request escaped to shared proxy')
    monkeypatch.setattr(server.Router, 'endpoint_for',
                        lambda _self, role: coder if role == 'coder' else reasoner)
    # Classification is L1 and kept by the assist ablation; disable it explicitly here.
    cfg = Config(assists=AssistConfig(disabled=('task-classification',)),
                 routing=RoutingConfig(engagement_level=5, roles={
                     name: Role(name=name, backend='local') for name in ('coder', 'reasoner')}),
                 logging=LoggingConfig(dir=str(tmp_path), capture_dir=str(tmp_path / 'calls')))
    classifier = classify.Classifier(Mock())
    instance = server.CriaServer(cfg, Mock(), shared)
    instance.classifier = classifier
    handler = server.CriaHandler.__new__(server.CriaHandler)
    handler.server = instance
    handler.headers = {'X-Cria-Session-Id': 'fresh-ablation'}
    monkeypatch.setattr(handler, '_translate_out', lambda comp, *_a: comp)
    monkeypatch.setattr(handler, '_finalize', lambda comp, *_a: comp)
    monkeypatch.setattr(loop, 'judge_satisfaction', lambda *_a, **_k: (False, 'work remains', ''))
    checks = Mock(wraps=loop._requested_repository_probe)
    monkeypatch.setattr(loop, '_requested_repository_probe', checks)
    body = {'messages': [{'role': 'user', 'content': 'Implement the requested artifact.'}],
            'tools': copy.deepcopy(TOOLS)}
    key = 'sid:fresh-ablation'
    assert not instance.loop.knows_session(key)
    drive = Mock(wraps=instance.loop.drive)
    monkeypatch.setattr(instance.loop, 'drive', drive)
    log = Log()
    def dispatch(request):
        if streaming:
            frames = list(handler._produce_stream(request, log))
            assert not any(b'"error"' in frame for frame in frames), frames
            return frames
        return handler._produce_completion(request, log, key)[0]
    with assistruntime.bound(instance.pilot_runtime):
        first = dispatch(body)
        assert coder.chat_watched.called
        assert checks.called, ([event for event, _fields in log.events], coder.chat_watched.call_count, first)
        session = instance.loop._store.get(key)
        assert session is not None and session.probe_call_id
        returned = gate_reply(session, body)
        dispatch(returned)
    assert any(event == 'loop.task_review' for event, _fields in log.events)
    assert session.latest_satisfaction is False
    assert drive.call_count == 2
    assert all(call.args[2] is None for call in drive.call_args_list)
    classifier._provider.chat.assert_not_called()
    shared.chat.assert_not_called()
    shared.stream_chat.assert_not_called()


@pytest.mark.parametrize('planning', [False, True])
@pytest.mark.parametrize('profile', ['default', 'rank4-ablation', 'no-classifier'])
def test_shared_admission_preserves_selected_semantics_and_auxiliary_exclusions(planning, profile):
    runtime = (assistruntime.AssistRuntime.select(disabled=('task-classification',))
               if profile == 'no-classifier' else assistruntime.AssistRuntime.select(profile=profile))
    body = {'messages': [{'role': 'user', 'content': 'Work on the artifact'}], 'tools': TOOLS}
    with assistruntime.bound(runtime):
        for engagement, task_type in [('task', 'coding'), ('question', 'coding'), ('task', 'question')]:
            verdict = classify.Classification(engagement, task_type, 'scripted classification')
            expected = engagement == 'task' if planning else task_type == 'coding'
            assert admission.starts_driver(body, verdict, planning=planning) is expected
        assert admission.starts_driver(body, None, planning=planning) is ('task-classification' not in runtime.selected)
        for request in (
            {**body, 'tools': []},
            {**body, 'tools': [{'type': 'function', 'function': {'name': 'task_complete'}}]},
            {**body, 'messages': [{'role': 'user', 'content': 'Generate a concise UI title for this task: change the artifact'}]},
            {**body, 'messages': [{'role': 'user', 'content': '<<<LOCAL_COMPACT>>> Summarize this work'}]},
        ):
            assert not admission.starts_driver(request, None, planning=planning)
        assert not admission.starts_driver(body, None, planning=planning, compaction=True)
