"""Rig for the primitive-operation tests: a real CriaServer over a scripted model, and a harness that runs cria's calls as the
pinned Codex does (`bash -lc` on a pty, LF to CRLF, the 10,000-byte cut, its envelope) in a real workspace."""
import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from chatty_shell import chatty_pty, codex_result  # noqa: E402,F401  (the shared rig: a real pty as the pinned Codex runs a command)
import threading  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

from cria import privatepaths  # noqa: E402
from cria.config import Config, IndicatorsConfig, LoggingConfig, RoutingConfig, ServerConfig  # noqa: E402
from cria.events import EventLog  # noqa: E402
from cria.server import CriaServer  # noqa: E402

MENU = [{'type': 'function', 'function': {'name': 'exec_command', 'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}}]
SHELL = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
HEX = ''.join('%08x\n' % (i * 2654435761 % 2**32) for i in range(5000))     # ~45 KB: more than one frame of one harness result


def pty_run(command, cwd=None):
    """Run `command` as the harness does (stdout is a pty: LF becomes CRLF) and return its text."""
    import pty
    import subprocess
    master, slave = pty.openpty()
    p = subprocess.Popen(['bash', '-c', command], stdout=slave, stderr=subprocess.PIPE, cwd=cwd)
    os.close(slave)
    data = bytearray()
    while True:
        try:
            chunk = os.read(master, 65536)
        except OSError:
            break
        if not chunk:
            break
        data.extend(chunk)
    os.close(master)
    err = p.stderr.read()
    assert p.wait() == 0, err
    return data.decode()


def run_call(call):
    return pty_run(json.loads(call['function']['arguments'])['cmd'])


class _BaseWire:
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



@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """The key, the ledger and every other private artefact live under CRIA_HOME: each test gets its own."""
    (tmp_path / 'home').mkdir()
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setattr(privatepaths, 'CRIA_HOME', tmp_path / 'home' / '.cria')


class Wire(_BaseWire):
    """The read tests' rig, with a server error shown as what it said; ``level`` is [safety] external_dir_permission."""
    def __init__(self, *args, level=None, **kw):
        super().__init__(*args, **kw)
        if level:
            import dataclasses
            from cria.config import SafetyConfig
            self.srv.cfg = dataclasses.replace(self.srv.cfg, safety=SafetyConfig(level))

    def post(self):
        try:
            return super().post()
        except urllib.error.HTTPError as exc:
            raise AssertionError(f'cria answered {exc.code}: {exc.read().decode()[:2000]}') from None


def command_of(call):
    return json.loads(call['function']['arguments'])['cmd']


class Harness:
    """Runs a call's command in `cwd` the way the pinned Codex does (a real `bash -lc` on a real pty, CRLF, a private HOME and
    TMPDIR beside the workspace, never inside it); returns the text the harness would hand back."""
    def __init__(self, cwd, env=None, **noise):
        self.cwd, self.noise, self.env, self.ran = str(cwd), noise, env or {}, []
        self.home = self.cwd + '.home'

    def __call__(self, call):
        self.ran.append(call)
        os.makedirs(self.home, exist_ok=True)
        env = {'TMPDIR': self.cwd + '.scratch', **self.env}
        os.makedirs(env['TMPDIR'], exist_ok=True)
        raw, code = chatty_pty(command_of(call), self.cwd, env=env, home=self.home, **self.noise)
        return codex_result(raw, code)


def start_in(wire, workspace):
    """Point a started Wire's conversation at `workspace` (the harness's announced cwd), not at the directory its logs live in."""
    wire.messages[0]['content'] = f'<environment_context><cwd>{workspace}</cwd></environment_context> list'
    return wire


class ListBackend:
    """Scripted model: turn 1 calls `list_dir` for each path; every later turn answers 'seen'. Records request bodies."""
    def __init__(self, *paths, name='list_dir'):
        self.paths, self.name, self.bodies = paths, name, []

    def loaded_model(self, rlog=None):
        return 'test-model'

    def chat(self, body, rlog=None):
        self.bodies.append(body)
        calls = [{'id': 'model_call_%d' % i, 'type': 'function', 'function': {'name': self.name, 'arguments': json.dumps({'path': str(p)})}}
                 for i, p in enumerate(self.paths)] if len(self.bodies) == 1 else None
        msg = {'role': 'assistant', 'content': None, 'tool_calls': calls} if calls else {'role': 'assistant', 'content': 'seen'}
        return json.dumps({'id': 'f', 'object': 'chat.completion', 'created': 1, 'model': 'test-model',
                           'choices': [{'index': 0, 'message': msg, 'finish_reason': 'tool_calls' if calls else 'stop'}]})

    def tool_results(self):
        return [m for m in self.bodies[-1]['messages'] if m.get('role') == 'tool']


class TurnBackend:
    """Scripted model: turn N issues the calls ``turns[N-1]`` (a list of ``(tool, arguments)``), then answers 'seen'."""
    def __init__(self, *turns):
        self.turns, self.bodies = turns, []

    def loaded_model(self, rlog=None):
        return 'test-model'

    def chat(self, body, rlog=None):
        self.bodies.append(body)
        n = len(self.bodies) - 1
        calls = [{'id': f'model_call_{n}_{i}', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}
                 for i, (name, args) in enumerate(self.turns[n])] if n < len(self.turns) else None
        msg = {'role': 'assistant', 'content': None, 'tool_calls': calls} if calls else {'role': 'assistant', 'content': 'seen'}
        return json.dumps({'id': 'f', 'object': 'chat.completion', 'created': 1, 'model': 'test-model',
                           'choices': [{'index': 0, 'message': msg, 'finish_reason': 'tool_calls' if calls else 'stop'}]})
