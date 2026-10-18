"""Canonical generation selection at actual streamed transport boundaries."""
from dataclasses import replace
import io
import json
from unittest.mock import Mock
from http.server import ThreadingHTTPServer
from cria import config, server

import pytest

from cria import assistruntime, generationguards as guards, loop
from cria.upstream import Upstream, UpstreamError
from test_upstream import _Rlog


def runtime(replacement=None, disabled=()):
    selected = assistruntime.AssistRuntime.select(level=5, disabled=disabled)
    if replacement:
        selected = replace(selected, ordered_stages=tuple(
            replacement if d.policy.id == replacement.policy.id else d for d in selected.ordered_stages))
    return selected


@pytest.mark.parametrize('disabled', [False, True])
def test_actual_stream_runs_only_selected_source_replacement(disabled):
    seen = []
    class Guard:
        def feed(self, frame, elapsed, reasoning_text, content_text, log):
            seen.append(('frame', frame, content_text()))
            return guards.StreamResult(guards.StreamStatus.ABORT, {'selected_verdict': True})
    def stream(source):
        seen.append(('source', source))
        return Guard()
    definition = replace(guards.RUNAWAY, stream=stream)
    selected = runtime(definition, (definition.policy.id,) if disabled else ())
    response = io.BytesIO(b'data: {"choices":[{"delta":{"content":"actual content"}}]}\n\n'
                         b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n')
    up = Upstream('http://offline.invalid', context_window=8192, engagement_level=5,
                  open_request=lambda request, **options: response)
    log = _Rlog()
    with assistruntime.bound(selected):
        result = json.loads(up.chat_watched({'messages': [{'role': 'user', 'content': 'work'}]}, log))
    assert response.closed and log.live_t0 is None
    if disabled:
        assert seen == []
        assert result['choices'][0]['message']['content'] == 'actual content'
        assert result['choices'][0]['finish_reason'] == 'stop'
    else:
        assert seen[0][0] == 'source'
        assert seen[1][2] == 'actual content'
        assert result['choices'][0]['finish_reason'] == 'rumination'
        assert result['cria_rumination'] == {'selected_verdict': True}


@pytest.mark.parametrize('level', [0, 3])
def test_ineligible_transport_never_constructs_selected_stream(level):
    definition = replace(guards.RUNAWAY, stream=Mock(side_effect=AssertionError('ineligible stream')))
    response = io.BytesIO(b'data: {"choices":[{"delta":{"content":"baseline"},"finish_reason":"stop"}]}\n\n')
    up = Upstream('http://offline.invalid', context_window=8192, engagement_level=level,
                  open_request=lambda request, **options: response)
    log = _Rlog()
    with assistruntime.bound(runtime(definition)):
        reply = json.loads(up.chat_watched({'messages': []}, log, watch=Mock(side_effect=AssertionError('watch'))))
    assert reply['choices'][0]['message']['content'] == 'baseline'
    definition.stream.assert_not_called()
    assert response.closed and log.live_t0 is None
    assert any(kind == 'upstream.done' for kind, _ in log.events)


def test_selected_stream_factory_failure_still_closes_transport():
    definition = replace(guards.RUNAWAY, stream=Mock(side_effect=RuntimeError('selected factory')))
    response = io.BytesIO()
    up = Upstream('http://offline.invalid', context_window=8192,
                  open_request=lambda request, **options: response)
    log = _Rlog()
    with assistruntime.bound(runtime(definition)), pytest.raises(RuntimeError, match='selected factory'):
        up.chat_watched({'messages': []}, log)
    assert response.closed and log.live_t0 is None


@pytest.mark.parametrize('disabled', [False, True])
def test_real_server_constructs_no_detector_until_selected_coder_call(tmp_path, monkeypatch, disabled):
    monkeypatch.setattr(ThreadingHTTPServer, '__init__', lambda *_args, **_kwargs: None)
    endpoint = Mock()
    endpoint.chat_watched.return_value = b'{"choices":[]}'
    monkeypatch.setattr(server.Router, 'endpoint_for', lambda *_args: endpoint)
    cfg = config.Config(routing=config.RoutingConfig(engagement_level=5,
        roles={'coder': config.Role(name='coder', backend='local', output_reserve=4096)}),
        logging=config.LoggingConfig(dir=str(tmp_path)))
    detector = Mock()
    factory = Mock(return_value=detector)
    definition = replace(guards.RUNAWAY, detector=factory)
    selected = runtime(definition, (definition.policy.id,) if disabled else ())
    with assistruntime.bound(selected):
        instance = server.CriaServer(cfg, endpoint, Mock())
        factory.assert_not_called()
        assert instance.loop is not None
        instance.loop._ctx.coder_chat({'messages': []}, _Rlog())
    if disabled:
        factory.assert_not_called()
        assert endpoint.chat_watched.call_args.kwargs['watch'] is None
    else:
        factory.assert_called_once_with(4096)
        assert endpoint.chat_watched.call_args.kwargs['watch'] == detector.check


def test_disabled_recovery_keeps_required_native_quarantine_without_lazy_services(monkeypatch):
    selected = runtime(disabled=tuple(d.policy.id for d in guards.DEFINITIONS))
    monkeypatch.setattr(loop, '_generation_cut_services', Mock(side_effect=AssertionError('cuts')))
    monkeypatch.setattr(loop, '_generation_grounding_services', Mock(side_effect=AssertionError('grounding')))
    completion = {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
        'tool_calls': [{'id': 'partial', 'type': 'function', 'function': {
            'name': 'native_write', 'arguments': '{"path":"x","content":"unfinished'}}]}}]}
    body = {'messages': [{'role': 'user', 'content': 'original'}]}
    before = list(body['messages'])
    chat = Mock(side_effect=AssertionError('optional retry'))
    with assistruntime.bound(selected):
        result = loop._generation_recovery(completion, body, chat, _Rlog())
    assert result.runaway is None and result.truncation is None
    assert not result.completion['choices'][0]['message'].get('tool_calls')
    assert body['messages'] == before
    chat.assert_not_called()


def test_optional_off_keeps_socket_failure_and_raw_error_without_coaching():
    class Silent(io.BytesIO):
        def __next__(self):
            raise TimeoutError('wire deadline')
    response = Silent()
    log = _Rlog()
    selected = runtime(disabled=(guards.RUNAWAY.policy.id,))
    up = Upstream('http://offline.invalid', context_window=8192,
                  open_request=lambda request, **options: response)
    with assistruntime.bound(selected), pytest.raises(UpstreamError) as failure:
        up.chat_watched({'messages': []}, log)
    assert response.closed and log.live_t0 is None
    assert failure.value.response_error['generation_evidence']['wire_timeout']['error'] == 'wire deadline'
    assert 'wire_raw_hex' in failure.value.response_error['generation_evidence']
    assert not any(kind == 'rumination.abort' for kind, _ in log.events)


def test_coder_receipts_clear_stale_credit_and_do_not_record_failed_retries():
    log = _Rlog()
    log.restored_on_wire = {'stale': 'wrong'}
    adapter = loop._CoderReplyReceipts(lambda body, log: b'{}')
    adapter.chat({}, log)
    original = {}
    adapter.record(original)
    assert adapter.receipt(original) == {}
    assert adapter.receipt(dict(original)) == {}
    def failed(body, log):
        log.restored_on_wire = {'failed': 'not-retained'}
        raise RuntimeError('failed coder')
    adapter = loop._CoderReplyReceipts(failed)
    adapter.record(original, {'initial': 'authenticated'})
    assert adapter.receipt(original) == {'initial': 'authenticated'}
    assert adapter.receipt(dict(original)) == {}
    with pytest.raises(RuntimeError, match='failed coder'):
        adapter.chat({}, log)
    assert adapter.receipt(original) == {'initial': 'authenticated'}
    assert adapter.latest == {}


def test_root_registers_both_generation_sources():
    assert all(d in assistruntime.DEFINITIONS for d in guards.DEFINITIONS)
