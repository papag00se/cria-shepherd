"""Characterize the existing fail-closed path; this adds no retry policy."""
import io
import json
import urllib.error
from unittest import mock

import pytest
from cria.upstream import Upstream, UpstreamError
from test_upstream import _FakeResp, _Rlog, _delta, _sse

RAW = '<Thought>unfinished reasoning'
ERROR = {'code': 500, 'type': 'server_error', 'message': 'Invalid no-action protocol output; raw bytes (hex): ' + RAW.encode().hex()}
BODY = {'model': 'fixture', 'messages': [{'role': 'user', 'content': 'Read the requested file.'}]}


def rejection():
    return urllib.error.HTTPError('http://x/v1/chat/completions', 500, 'Internal Server Error', {},
                                  io.BytesIO(json.dumps({'error': ERROR}).encode()))


def upstream():
    return Upstream('http://x', context_window=16384, capture_dir=None, capture_rendered=False)


def test_buffered_protocol_500_is_not_retried_as_transient_timeout():
    log = _Rlog()
    with mock.patch('cria.upstream.urllib.request.urlopen', side_effect=rejection()) as send, \
         mock.patch('cria.upstream.time.sleep') as sleep:
        with pytest.raises(UpstreamError) as caught:
            upstream().chat(BODY, log)
    assert send.call_count == 1
    sleep.assert_not_called()
    assert caught.value.code == 500
    assert RAW.encode().hex() in caught.value.response_error['message']
    assert not any(name == 'upstream.retry' for name, _ in log.events)


def test_stream_protocol_error_drops_partial_calls_then_buffered_500_propagates():
    partial = '{"path":"notes.txt","content":"unfinished'
    response = _FakeResp([
        _sse(_delta(tool_calls=[{'index': 0, 'id': 'real_call', 'function': {'name': 'write_file'}}])),
        _sse(_delta(tool_calls=[{'index': 0, 'function': {'arguments': partial}}])),
        _sse({'error': ERROR}),
    ])
    log = _Rlog()
    with mock.patch('cria.upstream.urllib.request.urlopen', side_effect=[response, rejection()]) as send, \
         mock.patch('cria.upstream.time.sleep') as sleep:
        with pytest.raises(UpstreamError) as caught:
            upstream().chat_watched(BODY, log)
    assert response.closed
    assert send.call_count == 2  # one streaming request, then the existing single buffered re-ask
    assert json.loads(send.call_args_list[0].args[0].data)['stream'] is True
    assert json.loads(send.call_args_list[1].args[0].data)['stream'] is False
    assert 'stream_options' not in json.loads(send.call_args_list[1].args[0].data)
    events = [data for name, data in log.events if name == 'upstream.stream_error']
    assert len(events) == 1
    assert events[0]['dropped_tool_arg_chars'] == len(partial)
    assert RAW.encode().hex() in events[0]['error']
    assert caught.value.code == 500
    sleep.assert_not_called()
    assert not any(name == 'upstream.retry' for name, _ in log.events)
