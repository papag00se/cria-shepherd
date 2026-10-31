"""Shared rig: a real CriaServer over a scripted model, and a real PTY playing the harness that runs cria's lowered reads."""
import json, os, pty, subprocess, threading, urllib.request
from types import SimpleNamespace
import pytest
from cria import writeproxy
from cria.config import Config, IndicatorsConfig, LoggingConfig, RoutingConfig, ServerConfig
from cria.events import EventLog
from cria.multipart_bridge import Bridge
from cria.server import CriaServer

MENU = [{'type': 'function', 'function': {'name': 'exec_command', 'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}}]
READ_ONLY_MENU = [{'type': 'function', 'function': {'name': 'read_file', 'parameters': {'type': 'object', 'properties': {
    'path': {'type': 'string'}, 'start_line': {'type': 'integer'}, 'end_line': {'type': 'integer'}}}}}]
SHELL = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
HEX = ''.join('%08x\n' % (i * 2654435761 % 2**32) for i in range(5000))   # ~45 KB: cannot ride one 10 KB harness result

@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Multipart state lives under $HOME/.cria: keep each test's private state in its own tmp dir."""
    (tmp_path / 'home').mkdir(); monkeypatch.setenv('HOME', str(tmp_path / 'home'))

def pty_run(command, cwd=None):
    """Run `command` as the harness does (stdout is a pty: LF becomes CRLF, 10,000-byte result cap) and return its text."""
    master, slave = pty.openpty(); p = subprocess.Popen(['bash', '-c', command], stdout=slave, stderr=subprocess.PIPE, cwd=cwd); os.close(slave); data = bytearray()
    while True:
        try: chunk = os.read(master, 65536)
        except OSError: break
        if not chunk: break
        data.extend(chunk)
    os.close(master); err = p.stderr.read(); assert p.wait() == 0, err
    assert len(data) <= 10000
    return data.decode()

def run_call(call): return pty_run(json.loads(call['function']['arguments'])['cmd'])

class Backend:
    """Scripted model: turn 1 issues `read_file` for each path; later turns answer 'seen'. Records request bodies."""
    def __init__(self, *paths): self.paths, self.bodies = paths, []
    def loaded_model(self, rlog=None): return 'test-model'
    def chat(self, body, rlog=None):
        self.bodies.append(body)
        calls = [{'id': 'original' if len(self.paths) == 1 else str(i), 'type': 'function', 'function': {'name': 'read_file', 'arguments': json.dumps({'path': str(p)})}}
                 for i, p in enumerate(self.paths)] if len(self.bodies) == 1 else None
        msg = {'role': 'assistant', 'content': None, 'tool_calls': calls} if calls else {'role': 'assistant', 'content': 'seen'}
        return json.dumps({'id': 'f', 'object': 'chat.completion', 'created': 1, 'model': 'test-model', 'choices': [{'index': 0, 'message': msg, 'finish_reason': 'tool_calls' if calls else 'stop'}]})
    def tool_results(self): return [m for m in self.bodies[-1]['messages'] if m.get('role') == 'tool']

class Wire:
    """A live CriaServer. `drive()` plays coder+harness over chat or responses (optionally streamed), executing each call on a real PTY."""
    def __init__(self, tmp_path, backend, api='chat', stream=False, header=True):
        cfg = Config(server=ServerConfig(host='127.0.0.1', port=0), logging=LoggingConfig(dir=str(tmp_path / 'logs'), console=False),
                     indicators=IndicatorsConfig(enabled=False), routing=RoutingConfig(engagement_level=2))
        self.log = EventLog(dir=cfg.logging.dir, console=False); self.srv = CriaServer(cfg, self.log, backend)
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True); self.thread.start(); self.api, self.stream, self.header = api, stream, header
        self.messages = [{'role': 'user', 'content': f'<environment_context><cwd>{tmp_path}</cwd></environment_context> read'}]
    def __enter__(self): return self
    def __exit__(self, *exc): self.srv.shutdown(); self.srv.server_close(); self.thread.join(); self.log.close()
    def post(self):
        url = f'http://127.0.0.1:{self.srv.server_address[1]}/v1/' + ('chat/completions' if self.api == 'chat' else 'responses')
        headers = {'Content-Type': 'application/json', **({'X-Cria-Session-Id': 'sid'} if self.header else {})}
        if self.api == 'chat': body = {'model': 'test-model', 'tools': MENU, 'messages': self.messages}
        else:
            items = [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': m['content']}]} if m['role'] == 'user'
                     else {'type': 'function_call_output', 'call_id': m['tool_call_id'], 'output': m['content']} if m['role'] == 'tool' else None for m in self.messages]
            for i, m in enumerate(self.messages):
                if m['role'] == 'assistant': items[i] = [{'type': 'function_call', 'call_id': c['id'], 'name': c['function']['name'], 'arguments': c['function']['arguments']} for c in m.get('tool_calls') or []]
            body = {'model': 'test-model', 'tools': [{'type': 'function', **MENU[0]['function']}], 'prompt_cache_key': 'sid', 'stream': self.stream,
                    'input': [x for i in items for x in (i if isinstance(i, list) else [i])]}
        with urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode(), headers), timeout=15) as r: raw = r.read()
        if self.api == 'chat': return json.loads(raw)['choices'][0]['message']
        data = json.loads(raw) if not self.stream else next(e['response'] for e in (json.loads(x[6:]) for x in raw.decode().splitlines() if x.startswith('data: {')) if e.get('type') == 'response.completed')
        calls = [{'id': o['call_id'], 'type': 'function', 'function': {'name': o['name'], 'arguments': o['arguments']}} for o in data['output'] if o['type'] == 'function_call']
        return {'role': 'assistant', 'content': None if calls else json.dumps(data), 'tool_calls': calls}
    def drive(self, harness=run_call):
        """Run the loop until the model answers; returns (final message, every carrier the harness returned)."""
        carriers = []
        while True:
            msg = self.post()
            if not msg.get('tool_calls'): return msg, carriers
            self.messages.append({k: v for k, v in msg.items() if v is not None})
            for c in msg['tool_calls']:
                carriers.append(harness(c)); self.messages.append({'role': 'tool', 'tool_call_id': c['id'], 'content': carriers[-1]})

def start(tmp_path, data, args=None, name='f', storage=None):
    """Lower one read_file call through the real writeproxy into a Bridge and run its first page on the PTY."""
    p = tmp_path / name; p.write_bytes(data if isinstance(data, bytes) else data.encode())
    tc = {'id': 'original', 'type': 'function', 'function': {'name': 'read_file', 'arguments': json.dumps({'path': str(p), **(args or {})})}}
    completion = {'choices': [{'message': {'tool_calls': [tc]}}]}; bridge = Bridge(storage or str(tmp_path / ('state-' + name)))
    writeproxy.translate_outbound(completion, SHELL, SimpleNamespace(emit=lambda *a, **k: None), injected={'read_file'}, workspace_root=str(tmp_path),
        multipart_command=lambda original, effect, receipt: bridge.register('s', original, effect, SHELL, receipt))
    bridge.bind('s', completion); call = completion['choices'][0]['message']['tool_calls'][0]
    return bridge, [{'role': 'assistant', 'tool_calls': [call]}, {'role': 'tool', 'tool_call_id': 'original', 'content': run_call(call)}], p

def page_through(bridge, messages, tools=None, restart=None):
    """Answer each private continuation on the PTY until none is left; returns (projected messages, read facts)."""
    while True:
        projected, calls, facts = bridge.incoming('s', messages, tools=tools)
        if not calls: return projected, facts
        messages += [{'role': 'assistant', 'tool_calls': [calls[0]]}, {'role': 'tool', 'tool_call_id': calls[0]['id'], 'content': run_call(calls[0])}]
        if restart: bridge = restart()
