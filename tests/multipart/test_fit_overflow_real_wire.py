"""A MEASURED overflow on a route with no compaction must be reported as overflow (not unknown),
and the coder must get an actionable continuation instead of the encoded transport pages.

Found by a real 150 KB / 720 KB read against a 49152-token ornith1.5_9b server: the measured request
(55,835 tokens) became "could not be established" plus ~40k tokens of base64 pages, and a larger file
ended in HTTP 502 because the carriers themselves could not fit."""
import json
import threading
import urllib.request
from memory_http import MemoryTransport, json_reply
from cria.config import Config, RoutingConfig, ServerConfig, LoggingConfig, IndicatorsConfig
from cria.events import EventLog
from cria.server import CriaServer
from cria.upstream import Upstream
from test_server_integration import shell


def test_measured_overflow_without_compaction_is_reported_as_overflow_without_page_carriers(tmp_path):
    path = tmp_path / 'f'
    path.write_text(''.join('%08x %08x\n' % (i * 2654435761 % 2**32, i * 40503 % 2**32) for i in range(20000)))
    size = path.stat().st_size
    chats = []

    def response(req):
        url = req.full_url
        if url.endswith('/v1/models'): return json_reply({'data': [{'id': 'fixture'}]})
        if url.endswith('/props'):
            return json_reply({'chat_template': 'fixture', 'default_generation_settings': {'n_ctx': 49152}})
        if url.endswith('/apply-template'):
            return json_reply({'prompt': json.dumps(json.loads(req.data)['messages'])})
        if url.endswith('/tokenize'):
            return json_reply({'tokens': [1] * (len(json.loads(req.data)['content']) // 3)})
        if url.endswith('/v1/chat/completions'):
            data = json.loads(req.data); chats.append(data)
            msg = ({'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'original', 'type': 'function',
                    'function': {'name': 'read_file', 'arguments': json.dumps({'path': str(path)})}}]}
                   if len(chats) == 1 else {'role': 'assistant', 'content': 'seen'})
            return json_reply({'id': 'fake', 'object': 'chat.completion', 'created': 1, 'model': 'fixture',
                               'choices': [{'index': 0, 'message': msg,
                                            'finish_reason': 'tool_calls' if len(chats) == 1 else 'stop'}]})
        raise AssertionError(url)
    transport = MemoryTransport(response)
    upstream = Upstream('http://fixture.invalid', context_window=49152, capture_rendered=False,
                        engagement_level=2, open_request=transport)
    cfg = Config(server=ServerConfig(host='127.0.0.1', port=0),
                 logging=LoggingConfig(dir=str(tmp_path / 'logs'), console=False),
                 indicators=IndicatorsConfig(enabled=False), routing=RoutingConfig(engagement_level=2))
    log = EventLog(dir=cfg.logging.dir, console=False); srv = CriaServer(cfg, log, upstream)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    url = f'http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions'
    tools = [{'type': 'function', 'function': {'name': 'exec_command', 'parameters': {
        'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}}]
    messages = [{'role': 'user', 'content': f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'}]

    def post():
        req = urllib.request.Request(url, data=json.dumps({'model': 'fixture', 'tools': tools, 'messages': messages}).encode(),
                                     headers={'Content-Type': 'application/json', 'X-Cria-Session-Id': 'sid'})
        with urllib.request.urlopen(req, timeout=30) as r: return json.load(r)
    try:
        while True:
            msg = post()['choices'][0]['message']; calls = msg.get('tool_calls') or []
            if not calls: break
            messages.append(msg)
            for c in calls:
                messages.append({'role': 'tool', 'tool_call_id': c['id'],
                                 'content': shell(json.loads(c['function']['arguments'])['cmd'])})
        assert msg['content'] == 'seen' and len(chats) == 2
        result = next(m for m in chats[-1]['messages'] if m.get('role') == 'tool')['content']
        assert f'({size} bytes)' in result and 'did not fit the context window' in result
        assert 'narrower pieces' in result
        assert 'could not be established' not in result
        assert '"source_sha256"' not in result and len(result) < 2000
        # The same promise as every fallback: the file earned no read credit.
        assert '⟦ctx:read-not-delivered⟧' in result
    finally: srv.shutdown(); srv.server_close(); t.join(); log.close(); transport.assert_closed()
