"""Through the real chat handler: the menu the harness sent reaches the not-delivered note, so a one-line file and a
binary file each get a measured shape and a route the coder can actually take (and a menu with no shell gets none).

A 586 KB single-line JSON and a 100 KB binary were replayed against ornith1.5_9b through a scratch server first; the
binary read ended in `input-not-delivered` (142,264 tokens: the note replayed every encoded page)."""
import json
import random
import threading
import urllib.request

from memory_http import MemoryTransport, json_reply
from cria.config import Config, RoutingConfig, ServerConfig, LoggingConfig, IndicatorsConfig
from cria.events import EventLog
from cria.server import CriaServer
from cria.upstream import Upstream
from test_server_integration import shell

EXEC = {'type': 'function', 'function': {'name': 'exec_command', 'parameters': {
    'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}}


def run_read(tmp_path, data: bytes, tools):
    path = tmp_path / 'blob'
    path.write_bytes(data)
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
            chats.append(json.loads(req.data))
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
    messages = [{'role': 'user', 'content': f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'}]

    def post():
        req = urllib.request.Request(url, data=json.dumps({'model': 'fixture', 'tools': tools, 'messages': messages}).encode(),
                                     headers={'Content-Type': 'application/json', 'X-Cria-Session-Id': 'sid'})
        with urllib.request.urlopen(req, timeout=60) as r: return json.load(r)
    try:
        while True:
            msg = post()['choices'][0]['message']; calls = msg.get('tool_calls') or []
            if not calls: break
            messages.append(msg)
            for c in calls:
                cmd = json.loads(c['function']['arguments'])['cmd']
                messages.append({'role': 'tool', 'tool_call_id': c['id'], 'content': shell(cmd)})
        return msg, chats, path
    finally: srv.shutdown(); srv.server_close(); t.join(); log.close(); transport.assert_closed()


def test_a_one_line_file_overflow_gets_shape_facts_and_the_byte_route_through_the_handler(tmp_path):
    random.seed(5)
    data = json.dumps({'r': ['%08x' % random.getrandbits(32) for _ in range(90000)]}, separators=(',', ':')).encode()
    final, chats, path = run_read(tmp_path, data, [EXEC])
    assert final['content'] == 'seen' and len(chats) == 2
    result = next(m for m in chats[-1]['messages'] if m.get('role') == 'tool')['content']
    assert f'{len(data):,} bytes in 1 line(s)' in result
    assert f"sed -n '1p' {path} | head -c 4000" in result and 'exec_command' in result
    assert 'narrower pieces' not in result and len(result) < 2500


def test_a_binary_read_reaches_the_coder_as_a_short_fact_not_as_its_pages(tmp_path):
    random.seed(1)
    data = b'\x89PNG\r\n\x1a\n' + bytes(random.getrandbits(8) for _ in range(100_000))
    final, chats, path = run_read(tmp_path, data, [EXEC])
    assert final['content'] == 'seen', final['content']                  # was ⟦ctx:input-not-delivered⟧: the session was dead
    result = next(m for m in chats[-1]['messages'] if m.get('role') == 'tool')['content']
    assert f'({len(data):,} bytes) is not valid UTF-8 text' in result and f'od -A d -t x1z -N 256 {path}' in result
    assert len(result) < 2000 and '"source_sha256"' not in result


def test_a_small_binary_read_gets_the_same_fact_instead_of_a_transport_failure(tmp_path):
    random.seed(2)
    data = b'\x89PNG' + bytes(random.getrandbits(8) for _ in range(3000))
    final, chats, path = run_read(tmp_path, data, [EXEC])
    assert final['content'] == 'seen'
    result = next(m for m in chats[-1]['messages'] if m.get('role') == 'tool')['content']
    assert 'is not valid UTF-8 text' in result and 'The returned transport record was not verified' not in result
    assert 'Exact continuation execution output' not in result
