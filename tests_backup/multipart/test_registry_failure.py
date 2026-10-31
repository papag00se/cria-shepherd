import json
import threading
import urllib.request

from cria.config import Config, IndicatorsConfig, LoggingConfig, RoutingConfig, ServerConfig
from cria.events import EventLog
from cria.server import CriaServer
from test_server_integration import Backend, shell


def test_corrupt_registry_continues_with_exact_unverified_carrier(tmp_path):
    path = tmp_path / 'f'
    path.write_text(''.join('%08x\n' % (i * 2654435761 % 2**32) for i in range(5000)))
    backend = Backend(str(path))
    cfg = Config(server=ServerConfig(host='127.0.0.1', port=0),
                 logging=LoggingConfig(dir=str(tmp_path / 'logs'), console=False),
                 indicators=IndicatorsConfig(enabled=False), routing=RoutingConfig(engagement_level=2))
    log = EventLog(dir=cfg.logging.dir, console=False)
    srv = CriaServer(cfg, log, backend)
    thread = threading.Thread(target=srv.serve_forever, daemon=True); thread.start()
    url = f'http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions'
    tools = [{'type': 'function', 'function': {'name': 'exec_command', 'parameters':
             {'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}}]
    messages = [{'role': 'user', 'content': f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read file'}]
    def post():
        req = urllib.request.Request(url, data=json.dumps({'model': 'test-model', 'tools': tools, 'messages': messages}).encode(),
                                     headers={'Content-Type': 'application/json', 'X-Cria-Session-Id': 'sid'})
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response)['choices'][0]['message']
    try:
        first = post(); call = first['tool_calls'][0]
        carrier = shell(json.loads(call['function']['arguments'])['cmd']) + '\x1b[31m\x00\r\n'
        messages.extend([first, {'role': 'tool', 'tool_call_id': call['id'], 'content': carrier}])
        state = next((tmp_path / 'home' / '.cria' / 'multipart').glob('*.json'))
        state.write_text('{"broken"')
        answer = post()
        assert answer['content'] == 'seen'
        shown = next(m['content'] for m in backend.bodies[-1]['messages'] if m.get('role') == 'tool')
        assert shown.startswith(carrier) and 'read transport state could not be verified' in shown
        assert '_multipart_unverified' not in json.dumps(backend.bodies[-1], default=str)
    finally:
        srv.shutdown(); srv.server_close(); thread.join(); log.close()
