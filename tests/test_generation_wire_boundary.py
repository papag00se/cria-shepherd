"""Real HTTP handlers and fake transport; executor spies observe every action event.

The driver collaborator supplies real collected upstream output so the handler's
driver branch is exercised at every rung without enabling a production driver.
Separate tests cover the real existing driver truncation policy and prefix reader.
"""
import copy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import io
import json
import os
from pathlib import Path
import types
import urllib.error
import urllib.request
from unittest import mock

import pytest
from cria import bodykeys, failover, loop, massage, responses
from cria.config import Config, IndicatorsConfig, LoggingConfig, RoutingConfig, ServerConfig, UpstreamConfig
from cria.events import EventLog
from cria.server import CriaServer, CriaHandler
from cria.upstream import Upstream, UpstreamError
from test_upstream import _FakeResp, _Rlog, _delta, _sse


CALL = {'id': 'real_call', 'type': 'function', 'function': {'name': 'write_file',
        'arguments': json.dumps({'path': 'notes.txt', 'content': '雪\n'})}}
RAW = '<Output>' + json.dumps({'name': 'write_file', 'arguments': {'path': 'notes.txt', 'content': '雪\n'}}) + '</Output>'
EVIDENCE = {'stop_type': 'limit', 'stop_cause': 'output_budget', 'incomplete': True,
            'content_is_non_action': True, 'raw_hex': RAW.encode().hex(),
            'call_prefixes': [{'name': 'write_file', 'arguments': CALL['function']['arguments']}],
            'context_shifted': False, 'truncated': False}
ERROR = {'type': 'invalid_model_output_error', 'code': 500, 'reason': 'Incomplete reasoning at EOS',
         'message': 'Incomplete reasoning at EOS', 'generation_evidence': {**EVIDENCE, 'stop_type': 'eos'}}


def completion(finish='length', *, calls=True, content='Earlier content. ', evidence=True):
    result = {'choices': [{'index': 0, 'finish_reason': finish, 'message': {
              'role': 'assistant', 'content': content, 'reasoning_content': 'Reasoning 雪\n'}}]}
    if calls:
        result['choices'][0]['message']['tool_calls'] = [copy.deepcopy(CALL)]
    if evidence:
        result['generation_evidence'] = copy.deepcopy(EVIDENCE)
        result['generation_evidence']['stop_type'] = 'limit' if finish == 'length' else 'eos'
        result['generation_evidence']['incomplete'] = finish == 'length'
    return result


class ExecutorSpy:
    def __init__(self):
        self.executed = []
        self.arguments = {}
        self.done = set()
        self.call_ids = {}

    def call(self, identity, arguments):
        try:
            value = json.loads(arguments)
        except (ValueError, TypeError):
            return
        if identity not in self.done:
            self.done.add(identity)
            self.executed.append(value)

    def observe(self, obj):
        if obj.get('type') == 'response.output_item.added':
            item = obj.get('item') or {}
            if item.get('type') == 'function_call':
                self.call_ids[item['id']] = item.get('call_id', item['id'])
        for choice in obj.get('choices', []):
            for call in (choice.get('message') or {}).get('tool_calls', []):
                self.call(call.get('id'), call.get('function', {}).get('arguments'))
            for call in (choice.get('delta') or {}).get('tool_calls', []):
                identity = call.get('index', 0)
                self.arguments[identity] = self.arguments.get(identity, '') + call.get('function', {}).get('arguments', '')
                self.call(identity, self.arguments[identity])
        for item in obj.get('output', []):
            if item.get('type') == 'function_call':
                self.call(item.get('call_id'), item.get('arguments'))
        if obj.get('type') == 'response.function_call_arguments.delta':
            identity = self.call_ids.get(obj['item_id'], obj['item_id'])
            self.arguments[identity] = self.arguments.get(identity, '') + obj.get('delta', '')
            self.call(identity, self.arguments[identity])


def events(raw):
    return [json.loads(line[5:]) for line in raw.decode().splitlines()
            if line.startswith('data:') and line[5:].strip() not in ('', '[DONE]')]


@pytest.fixture(scope='module')
def handlers(tmp_path_factory):
    previous_fixes = massage._TOOL_CALL_FIXES
    class Fake(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            value = {'data': [{'id': 'fixture'}]} if self.path.endswith('/models') else {'default_generation_settings': {}}
            self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(value).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.server.posts.append(body)
            value = self.server.completion
            if value.get('error'):
                self.send_response(200 if body.get('stream') else 500)
                self.end_headers()
                self.wfile.write(_sse(value) if body.get('stream') else json.dumps(value).encode())
                return
            if body.get('stream'):
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                message = value['choices'][0]['message']
                for delta in ({'role': 'assistant'}, {'reasoning_content': message['reasoning_content']},
                              {'content': message['content']}, {'tool_calls': [{'index': 0, **CALL}]}):
                    self.wfile.write(_sse(_delta(**delta)))
                terminal = {'choices': [{'index': 0, 'delta': {},
                             'finish_reason': value['choices'][0]['finish_reason']}]}
                if 'generation_evidence' in value:
                    terminal['generation_evidence'] = value['generation_evidence']
                if not value.get('fixture_eof'):
                    self.wfile.write(_sse(terminal)); self.wfile.write(b'data: [DONE]\n\n')
            else:
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(value).encode())

    # Both HTTP endpoints parse and emit real wire bytes. Only their socket IO is memory-backed.
    class MemorySocket:
        def __init__(self, incoming):
            self.incoming = incoming
            self.sent = []
        def makefile(self, mode, buffering=-1):
            assert mode == 'rb'
            return io.BytesIO(self.incoming)
        def sendall(self, data):
            self.sent.append(bytes(data))

    def request(handler, target, method, path, data=b'', headers=()):
        fields = dict(headers)
        fields['Content-Length'] = str(len(data))
        wire = (f'{method} {path} HTTP/1.0\r\n' +
                ''.join(f'{k}: {v}\r\n' for k, v in fields.items()) + '\r\n').encode() + data
        connection = MemorySocket(wire)
        handler(connection, ('fixture.invalid', 0), target)
        response = http.client.HTTPResponse(MemorySocket(b''.join(connection.sent)))
        response.begin()
        return response

    fake = types.SimpleNamespace(posts=[], completion=completion())
    case_number = 0
    directory = tmp_path_factory.mktemp('generation-wire')
    cfg = Config(server=ServerConfig(host='127.0.0.1', port=0),
                 upstream=UpstreamConfig(base_url='http://fixture.invalid'),
                 routing=RoutingConfig(engagement_level=0),
                 indicators=IndicatorsConfig(enabled=False, reasoning_transcript=False),
                 logging=LoggingConfig(dir=str(directory), capture_dir=str(directory), console=False))
    log = EventLog(dir=str(directory), console=False)
    up = Upstream(cfg.upstream.base_url, context_window=16384, capture_rendered=False, capture_dir=None)
    assert not cfg.planner.enabled
    with mock.patch.object(ThreadingHTTPServer, '__init__', return_value=None):
        server = CriaServer(cfg, log, up)

    def open_upstream(req, timeout=None):
        response = request(Fake, fake, req.get_method(), req.selector, req.data or b'', req.header_items())
        if response.status >= 400:
            raise urllib.error.HTTPError(req.full_url, response.status, response.reason,
                                         response.headers, response)
        return response

    class Driver:
        # The real driver owns session state; inbound handoff-origin checks consult it.
        def __init__(self):
            self._store = server.loop_store
        def knows_session(self, key): return True
        def visible_context_tokens(self, *args, **kwargs): return 0
        def drive(self, body, *args):
            rlog = args[-1]
            return massage.apply(json.loads(up.chat_watched(body, rlog)), body.get('tools'), rlog)

    original_chat = up.chat
    def post(level, driver, api, stream, value, body_overrides=None, *, collect_eof=False):
        nonlocal case_number
        server.cfg = replace(cfg, routing=replace(cfg.routing, engagement_level=level))
        server.loop = Driver() if driver else None
        fake.completion = value
        # Buffered proxy handlers receive an actual watched-stream transport error.
        # This fixture choice does not enable a driver or change production routing.
        up.chat = (lambda body, rlog: up.chat_watched(body, rlog)) if collect_eof else original_chat
        chat = {'model': 'fixture', 'messages': [{'role': 'user', 'content': 'Perform the requested action.'}],
                'tools': [{'type': 'function', 'function': {'name': 'write_file', 'parameters': {
                    'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}}}}}],
                'stream': stream}
        body = chat if api == 'chat' else {'model': 'fixture', 'input': 'Perform the requested action.',
                'tools': [{'type': 'function', **chat['tools'][0]['function']}], 'stream': stream}
        body.update(body_overrides or {})
        first_post = len(fake.posts)
        with request(CriaHandler, server, 'POST', '/v1/' +
                     ('chat/completions' if api == 'chat' else 'responses'),
                     json.dumps(body).encode(), {'Content-Type': 'application/json'}.items()) as reply:
            raw = reply.read()
        if os.environ.get('GENERATION_WIRE_RECEIPTS'):
            directory = Path(os.environ['GENERATION_WIRE_RECEIPTS']); directory.mkdir(parents=True, exist_ok=True)
            case_number += 1
            prefix = directory / f'{case_number:04d}-{level}-{driver}-{api}-{stream}'
            prefix.with_suffix('.request.json').write_text(json.dumps(body, ensure_ascii=False, indent=2))
            prefix.with_suffix('.upstream.json').write_text(json.dumps(fake.posts[first_post:], ensure_ascii=False, indent=2))
            prefix.with_suffix('.response.raw').write_bytes(raw)
            prefix.with_suffix('.expected-source.json').write_text(json.dumps(value, ensure_ascii=False, indent=2))
        return events(raw) if stream else [json.loads(raw)]
    try:
        with mock.patch('urllib.request.urlopen', side_effect=open_upstream):
            yield post
    finally:
        log.close()
        massage.set_tool_call_fixes(previous_fixes)


@pytest.mark.parametrize('level', range(6))
@pytest.mark.parametrize('driver', [False, True])
@pytest.mark.parametrize('api,stream', [('chat', False), ('chat', True), ('responses', False), ('responses', True)])
@pytest.mark.parametrize('native_facts', [False, True])
def test_length_calls_never_reach_executors_at_any_harness_boundary(handlers, level, driver, api, stream, native_facts):
    observed = handlers(level, driver, api, stream, completion(evidence=native_facts))
    spy = ExecutorSpy()
    for event in observed:
        spy.observe(event)
        if 'response' in event: spy.observe(event['response'])
    assert spy.executed == [], (level, driver, api, stream, observed)
    terminal = observed[-1].get('response', observed[-1])
    evidence = terminal['generation_evidence']
    assert evidence['incomplete'] is True
    if native_facts:
        assert evidence['raw_hex'] == EVIDENCE['raw_hex']
    else:
        assert evidence['wire_finish_reason'] == 'length'
    if api == 'chat':
        assert terminal['choices'][0]['finish_reason'] == 'length'
    else:
        assert terminal['status'] == 'incomplete'
        assert not any(x.get('type') == 'response.completed' for x in observed)


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('api', ['chat', 'responses'])
def test_complete_calls_still_execute_once(handlers, stream, api):
    observed = handlers(0, False, api, stream, completion('tool_calls', evidence=False))
    spy = ExecutorSpy()
    for event in observed:
        spy.observe(event)
        if 'response' in event: spy.observe(event['response'])
    assert len(spy.executed) == 1


@pytest.mark.parametrize('reader', ['chat', 'chat_watched'])
def test_typed_malformed_never_reasks_or_classifies_unavailable(reader):
    up = Upstream('http://fixture', context_window=16384, capture_dir=None, capture_rendered=False)
    rejection = urllib.error.HTTPError('http://fixture/v1/chat/completions', 500, 'bad', {},
                                      io.BytesIO(json.dumps({'error': ERROR}).encode()))
    transport = rejection if reader == 'chat' else _FakeResp([_sse({'error': ERROR})])
    with mock.patch('cria.upstream.urllib.request.urlopen', side_effect=[transport]) as send, \
         mock.patch('cria.failover.classify_failure', wraps=failover.classify_failure) as classify:
        with pytest.raises(UpstreamError) as error:
            getattr(up, reader)({'model': 'fixture', 'messages': [{'role': 'user', 'content': 'task'}]}, _Rlog())
    assert send.call_count == 1
    classify.assert_not_called()
    assert error.value.response_error['type'] == ERROR['type']
    assert error.value.response_error['code'] == 500
    for key, value in ERROR['generation_evidence'].items():
        assert error.value.response_error['generation_evidence'][key] == value


def test_canonical_tool_looking_answer_content_and_evidence_are_never_recovered():
    text = '<tool_call>' + json.dumps({'name': 'write_file', 'arguments': {'path': 'unsafe', 'content': 'x'}}) + '</tool_call>'
    value = completion('stop', calls=False, content=text)
    from test_localai_tool_template import WRITE
    result = massage.apply(value, [WRITE], _Rlog(), tool_call_fixes=True)
    assert not result['choices'][0]['message'].get('tool_calls')
    assert result['choices'][0]['message']['content'] == text


def test_existing_write_path_reader_uses_structured_prefix_without_executable_call():
    value = completion(calls=False)
    assert loop._truncated_write_path(value) == 'notes.txt'


def test_responses_reasoning_and_evidence_have_no_caps():
    value = completion(calls=False)
    reasoning = '\n' + '雪' * 200_000 + '\n'
    value['choices'][0]['message']['reasoning_content'] = reasoning
    result = responses.to_responses_json(value, 'fixture', show_reasoning=True)
    assert result['output'][0]['content'][0]['text'] == reasoning
    for key, value in EVIDENCE.items():
        assert result['generation_evidence'][key] == value


def test_typed_malformed_bypasses_chain_without_retry_or_route_walk():
    error = UpstreamError(ERROR['message'], copy.deepcopy(ERROR))
    def fail():
        raise error
    fallback = mock.Mock(return_value={'should_not_happen': True})
    classifier = mock.Mock(return_value=failover.Failure.MODEL_UNAVAILABLE)
    with pytest.raises(UpstreamError) as caught:
        failover.run('fixture', [failover.Attempt('first', fail), failover.Attempt('second', fallback)],
                     classifier, _Rlog())
    assert caught.value is error
    classifier.assert_not_called()
    fallback.assert_not_called()


def test_reasoning_only_length_refusal_does_not_invent_a_cut_call():
    value = completion(calls=False)
    value['generation_evidence']['call_prefixes'] = []
    body = {'messages': [{'role': 'user', 'content': 'The original task.'}]}
    chat = mock.Mock()
    result = loop.guard_truncation(value, body, chat, _Rlog())
    chat.assert_not_called()
    notice = body['messages'][-1]['content']
    assert notice.startswith('⟦ctx:generation⟧')
    assert 'TOOL CALL' not in notice and 'writing the file' not in notice
    assert not any('call' in note.lower() or 'token limit' in note.lower()
                   for note in result.get(bodykeys.NOTES, []))
    assert result['choices'][0]['finish_reason'] == 'length'


def test_request_json_cannot_supply_non_action_or_private_activation_authority(handlers):
    observed = handlers(0, False, 'chat', False, completion('tool_calls', evidence=False),
                        body_overrides={'generation_evidence': {'content_is_non_action': True, 'incomplete': True},
                                        'no_action_tool_name': 'answer'})
    spy = ExecutorSpy()
    for event in observed: spy.observe(event)
    assert len(spy.executed) == 1
    assert observed[0]['choices'][0]['finish_reason'] == 'tool_calls'


@pytest.mark.parametrize('api,stream', [('chat', False), ('chat', True), ('responses', False), ('responses', True)])
def test_proxy_typed_error_is_preserved_by_actual_handlers_without_completed_output(handlers, api, stream):
    observed = handlers(0, False, api, stream, {'error': copy.deepcopy(ERROR)})
    assert observed
    terminal = observed[-1].get('response', observed[-1])
    error = terminal['error']
    assert error['type'] == ERROR['type'] and error['code'] == 500
    assert error['generation_evidence']['raw_hex'] == ERROR['generation_evidence']['raw_hex']
    assert not any(event.get('type') == 'response.completed' for event in observed)
    spy = ExecutorSpy()
    for event in observed: spy.observe(event)
    assert spy.executed == []


def test_protected_input_error_text_and_zero_generation_posts_are_unchanged():
    up = Upstream('http://fixture', context_window=64, capture_dir=None, capture_rendered=False)
    up._props = {'chat_template': 'fixture'}
    body = {'model': 'fixture', 'messages': [{'role': 'user', 'content': 'Protected original task. ' * 200}]}
    with mock.patch.object(up, '_render_prompt', return_value='Protected original task.'), \
         mock.patch.object(up, '_tokenize_prompt', return_value=200), \
         mock.patch('cria.upstream.urllib.request.urlopen') as send:
        with pytest.raises(UpstreamError) as error:
            up.chat(body, _Rlog())
    assert str(error.value) == 'Measured input cannot fit the context window without losing protected input'
    send.assert_not_called()


@pytest.mark.parametrize('done', [False, True])
@pytest.mark.parametrize('calls', [False, True])
def test_unterminated_stream_cannot_release_or_recover_actions(done, calls):
    text = '<tool_call>' + json.dumps(CALL['function']) + '</tool_call>'
    chunks = [_sse(_delta(reasoning_content='Unfinished reasoning 雪\n')),
              _sse(_delta(content=text))]
    if calls:
        chunks.append(_sse(_delta(tool_calls=[{'index': 0, **CALL}])))
    if done:
        chunks.append(b'data: [DONE]\n\n')
    result = list(massage.massage_stream(iter(chunks), 'fixture', [{'type': 'function', 'function': {
        'name': 'write_file', 'parameters': {'type': 'object'}}}]))
    observed = events(b''.join(result))
    spy = ExecutorSpy()
    for event in observed: spy.observe(event)
    assert spy.executed == []
    assert not any(choice.get('finish_reason') in ('stop', 'tool_calls')
                   for event in observed for choice in event.get('choices', []))
    error = observed[-1]['error']
    assert error['type'] == 'incomplete_stream_error'
    assert error['generation_evidence']['wire_raw_hex'] == b''.join(chunks).hex()
    assert ''.join(choice.get('delta', {}).get('content', '')
                   for event in observed for choice in event.get('choices', [])) == text
    assert ''.join(choice.get('delta', {}).get('reasoning_content', '')
                   for event in observed for choice in event.get('choices', [])) == 'Unfinished reasoning 雪\n'


def test_typed_stream_error_preserves_unemitted_content_tail_without_recovery():
    text = 'Earlier prose. <tool_call>' + json.dumps(CALL['function']) + '</tool_call>'
    chunks = [_sse(_delta(content=text)), _sse({'error': copy.deepcopy(ERROR)})]
    observed = events(b''.join(massage.massage_stream(iter(chunks), 'fixture')))
    assert ''.join(choice.get('delta', {}).get('content', '')
                   for event in observed for choice in event.get('choices', [])) == text
    assert observed[-1]['error']['generation_evidence']['raw_hex'] == ERROR['generation_evidence']['raw_hex']
    assert not any(choice.get('delta', {}).get('tool_calls')
                   for event in observed for choice in event.get('choices', []))


@pytest.mark.parametrize('done', [False, True])
@pytest.mark.parametrize('arguments', [None, CALL['function']['arguments'], '{"path":"雪'])
@pytest.mark.parametrize('watch_installed', [False, True])
def test_actual_collector_unknown_eof_is_structured_transport_error_with_full_evidence(done, arguments, watch_installed):
    chunks = [_sse(_delta(content='Entire content 雪\n')),
              _sse(_delta(reasoning_content='Entire reasoning 雪\n'))]
    if arguments is not None:
        chunks.append(_sse(_delta(tool_calls=[{'index': 0, **CALL, 'function': {
            'name': 'write_file', 'arguments': arguments}}])))
    if done:
        chunks.append(b'data: [DONE]\n\n')
    up = Upstream('http://fixture', context_window=16384, capture_dir=None, capture_rendered=False)
    up._open_with_refit = mock.Mock(return_value=(_FakeResp(chunks), 10, 'fixture-capture'))
    watch = mock.Mock(return_value=None) if watch_installed else None
    with mock.patch.object(up, '_save_reasoning') as saved_reasoning, \
         mock.patch.object(up, '_stream_reasoning_to_disk'), \
         mock.patch('cria.upstream.callcapture.capture_response') as saved, mock.patch.object(up, 'chat') as buffered:
        with pytest.raises(UpstreamError) as caught:
            up.chat_watched({'model': 'fixture', 'messages': [{'role': 'user', 'content': 'task'}]}, _Rlog(), watch=watch)
    error = caught.value
    assert type(error) is UpstreamError
    assert error.response_error['type'] == 'incomplete_stream_error'
    evidence = error.response_error['generation_evidence']
    assert evidence['wire_raw_hex'] == b''.join(chunks).hex()
    assert evidence['stream_prefix']['content'] == 'Entire content 雪\n'
    assert evidence['stream_prefix']['reasoning_content'] == 'Entire reasoning 雪\n'
    assert not any(key in evidence for key in ('stop_type', 'stop_cause'))
    if arguments is not None:
        assert ''.join(evidence['stream_prefix']['action_prefixes'][0]['args']) == arguments
    assert saved.call_args.args[1]['error'] == error.response_error
    assert saved_reasoning.call_args.args[1] == 'Entire reasoning 雪\n'
    buffered.assert_not_called()
    assert failover.classify_failure(error.code, str(error)) is failover.Failure.MODEL_UNAVAILABLE


def test_actual_recorded_local_abort_withholds_even_valid_calls_without_native_stop_guess():
    chunks = [_sse(_delta(tool_calls=[{'index': 0, **CALL}])),
              _sse(_delta(reasoning_content='Reasoning 雪. ' * 50))]
    up = Upstream('http://fixture', context_window=16384, capture_dir=None, capture_rendered=False)
    up._open_with_refit = mock.Mock(return_value=(_FakeResp(chunks), 10, None))
    watch = mock.Mock(return_value={'hits': 6, 'reasoning_tokens': 175, 'fixture_actual_abort': True})
    rlog = _Rlog()
    value = json.loads(up.chat_watched({'model': 'fixture', 'messages': [{'role': 'user', 'content': 'task'}]}, rlog, watch=watch))
    watch.assert_called_once()
    assert value[bodykeys.RUMINATION]['fixture_actual_abort'] is True
    assert value['choices'][0]['finish_reason'] == 'rumination'
    assert not value['choices'][0]['message'].get('tool_calls')
    evidence = value['generation_evidence']
    assert evidence['local_abort'] == value[bodykeys.RUMINATION]
    assert not any(key in evidence for key in ('stop_type', 'stop_cause'))
    assert evidence['call_prefixes'][0]['arguments'] == CALL['function']['arguments']
    assert any(kind == 'rumination.abort' for kind, _ in rlog.events)
    response = responses.to_responses_json(value, 'fixture')
    assert response['status'] == 'incomplete'
    assert response['incomplete_details']['reason'] == 'generation_aborted'


@pytest.mark.parametrize('level', range(6))
@pytest.mark.parametrize('driver', [False, True])
@pytest.mark.parametrize('api,stream', [('chat', False), ('chat', True), ('responses', False), ('responses', True)])
def test_unknown_terminal_transport_error_reaches_actual_handlers_without_actions_or_completion(handlers, level, driver, api, stream):
    source = completion(evidence=False)
    source['fixture_eof'] = True
    observed = handlers(level, driver, api, stream, source, collect_eof=True)
    spy = ExecutorSpy()
    for event in observed:
        spy.observe(event)
        if 'response' in event: spy.observe(event['response'])
    assert spy.executed == []
    terminal = observed[-1].get('response', observed[-1])
    error = terminal['error']
    assert error['type'] == 'incomplete_stream_error'
    evidence = error['generation_evidence']
    raw = bytes.fromhex(evidence['wire_raw_hex'])
    assert raw and 'Reasoning 雪\n' in raw.decode().replace('\\u96ea', '雪').replace('\\n', '\n')
    assert not any(key in evidence for key in ('stop_type', 'stop_cause'))
    assert not any(event.get('type') == 'response.completed' for event in observed)
    assert not any(choice.get('finish_reason') in ('stop', 'tool_calls', 'length')
                   for event in observed for choice in event.get('choices', []))
