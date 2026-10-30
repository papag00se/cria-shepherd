"""A final user message (or tool result) larger than the whole context window ended in a bare HTTP 502.

Measured on the real 49,152-token server: a ~60k-token last user message through Chat and Responses came back
`502 {"error": "upstream error: Measured input cannot fit the context window without losing protected input"}`; pinned
Codex retried a failure that can never succeed. The same size spread across OLD history already degrades (the floor
compacts it, labelled), so only the protected final input can overflow. It is now answered — HTTP 200, an assistant
message in every wire shape — with what was measured, that nothing was dropped, and what the sender can do.
"""
import json
import threading
import urllib.request

from memory_http import MemoryTransport, json_reply
from cria.config import Config, RoutingConfig, ServerConfig, LoggingConfig, IndicatorsConfig
from cria.events import EventLog
from cria.server import CriaServer
from cria.upstream import Upstream

WINDOW = 49152
SEEN = 'hi'


def _serve(tmp_path, chats):
    def response(req):
        url = req.full_url
        if url.endswith('/v1/models'): return json_reply({'data': [{'id': 'fixture'}]})
        if url.endswith('/props'):
            return json_reply({'chat_template': 'fixture', 'default_generation_settings': {'n_ctx': WINDOW}})
        if url.endswith('/apply-template'):
            return json_reply({'prompt': json.dumps(json.loads(req.data)['messages'])})
        if url.endswith('/tokenize'):
            return json_reply({'tokens': [1] * (len(json.loads(req.data)['content']) // 3)})
        if url.endswith('/v1/chat/completions'):
            chats.append(json.loads(req.data))
            return json_reply({'id': 'fake', 'object': 'chat.completion', 'created': 1, 'model': 'fixture',
                               'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': SEEN},
                                            'finish_reason': 'stop'}]})
        raise AssertionError(url)
    transport = MemoryTransport(response)
    upstream = Upstream('http://fixture.invalid', context_window=WINDOW, capture_rendered=False,
                        engagement_level=3, open_request=transport)
    cfg = Config(server=ServerConfig(host='127.0.0.1', port=0),
                 logging=LoggingConfig(dir=str(tmp_path / 'logs'), console=False),
                 indicators=IndicatorsConfig(enabled=False), routing=RoutingConfig(engagement_level=3))
    log = EventLog(dir=cfg.logging.dir, console=False)
    srv = CriaServer(cfg, log, upstream)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, t, log, transport


def _post(srv, path, body):
    req = urllib.request.Request(f'http://127.0.0.1:{srv.server_address[1]}{path}', data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json', 'X-Cria-Session-Id': 'sid'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode()


ENV = '<environment_context><cwd>/work</cwd></environment_context>\n'
BIG = ' '.join('w%05d' % i for i in range(30000))        # ~210k chars: ~70k tokens on the fixture's chars/3 tokenizer
CHAT_TOOLS = [{'type': 'function', 'function': {'name': 'exec_command', 'parameters': {
    'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}}]
RESP_TOOLS = [{'type': 'function', 'name': 'exec_command', 'parameters': {
    'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}]


def _run(tmp_path, path, body):
    chats = []
    srv, t, log, transport = _serve(tmp_path, chats)
    try:
        status, raw = _post(srv, path, body)
    finally:
        srv.shutdown(); srv.server_close(); t.join(); log.close()
    return status, raw, chats


def _assert_notice(text):
    assert text.startswith('⟦ctx:input-not-delivered⟧')
    assert f'against a {WINDOW:,}-token context window' in text
    assert ' tokens against ' in text and 'measured ' in text.split(' tokens against ')[0].rsplit('this request ', 1)[1]
    assert 'Nothing was cut, summarised or dropped' in text and 'smaller pieces' in text


def _chat_body(stream=False):
    return {'model': 'fixture', 'tools': CHAT_TOOLS, 'stream': stream, 'max_tokens': 400,
            'messages': [{'role': 'user', 'content': ENV + 'summarise:\n' + BIG}]}


def _resp_body(stream=False):
    return {'model': 'fixture', 'tools': RESP_TOOLS, 'stream': stream,
            'input': [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': ENV + 'summarise:\n' + BIG}]}]}


def test_chat_final_message_over_the_window_is_an_assistant_message_not_a_502(tmp_path):
    status, raw, chats = _run(tmp_path, '/v1/chat/completions', _chat_body())
    msg = json.loads(raw)['choices'][0]['message']
    assert status == 200 and msg['role'] == 'assistant' and chats == []
    _assert_notice(msg['content'])


def test_chat_stream_final_message_over_the_window_is_an_assistant_message(tmp_path):
    status, raw, chats = _run(tmp_path, '/v1/chat/completions', _chat_body(stream=True))
    deltas = [json.loads(line[6:])['choices'][0]['delta'].get('content') or ''
              for line in raw.splitlines() if line.startswith('data: {')]
    assert status == 200 and chats == [] and raw.rstrip().endswith('data: [DONE]')
    _assert_notice(''.join(deltas))


def test_responses_final_message_over_the_window_is_an_assistant_message(tmp_path):
    status, raw, chats = _run(tmp_path, '/v1/responses', _resp_body())
    item = json.loads(raw)['output'][0]
    assert status == 200 and chats == [] and item['role'] == 'assistant'
    _assert_notice(item['content'][0]['text'])


def test_responses_stream_final_message_over_the_window_is_an_assistant_message(tmp_path):
    status, raw, chats = _run(tmp_path, '/v1/responses', _resp_body(stream=True))
    done = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith('data: {"item_id"')]
    text = next(d['text'] for d in done if d['type'] == 'response.output_text.done')
    assert status == 200 and chats == []
    _assert_notice(text)
    assert 'response.completed' in raw and 'response.failed' not in raw


def test_the_same_size_in_old_history_still_degrades_through_the_floor_with_a_label(tmp_path):
    msgs = [{'role': 'user', 'content': ENV + 'inspect then say hi'}]
    for i in range(3):
        msgs += [{'role': 'assistant', 'content': None, 'tool_calls': [{'id': f'c{i}', 'type': 'function', 'function': {
                      'name': 'exec_command', 'arguments': json.dumps({'cmd': f'cat log{i}'})}}]},
                 {'role': 'tool', 'tool_call_id': f'c{i}', 'content': f'log{i} ' + BIG[:150000]}]
    msgs += [{'role': 'assistant', 'content': 'looked'}, {'role': 'user', 'content': 'Now just say hi.'}]
    status, raw, chats = _run(tmp_path, '/v1/chat/completions',
                              {'model': 'fixture', 'tools': CHAT_TOOLS, 'max_tokens': 400, 'messages': msgs})
    assert status == 200 and json.loads(raw)['choices'][0]['message']['content'] == SEEN
    assert len(chats) == 1 and 'compacted to fit the context window' in json.dumps(chats[0]['messages'])


def test_an_estimated_size_is_never_called_measured():
    from cria.upstream import InputOverflow
    said = InputOverflow('x', 60000, WINDOW, 8192, False).notice()
    assert 'is estimated at about 60,000 tokens' in said and 'measured' not in said
    assert 'leaves 40,960 tokens' in said
