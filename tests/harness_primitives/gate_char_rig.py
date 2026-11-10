"""The characterisation rig of the gate migration (docs/harness-programs.md, Phase 7): every case is driven through a real CriaServer at L5 over a
scripted upstream (the coder writes what the case says, then claims it is done; every other role answers as the shared fake does) and a harness that
runs cria's calls with real bash on a real pty in a real workspace. What the MODEL READS of the gate (every distinct message of every request the
upstream received that carries the checks marker), what the harness ran (calls and command bytes) and what is left on disk are recorded.

`tests/fixtures/gate_characterization.json` holds the capture of the route that shipped before Phase 7 (a detached supervisor program, a helper
installed in the harness's temp directory, pages of a spool read back as text). The test compares today's route with it, case by case; the few
differences that are intended are named in `INTENDED` with the reason."""
import io
import json
import os
import re
import sys
import threading
from http.server import ThreadingHTTPServer

from cria import probegate, system1wiring
from cria.config import (Backend, Config, IndicatorsConfig, LoggingConfig, Role, RoutingConfig, ServerConfig, UpstreamConfig)
from cria.events import EventLog
from cria.server import CriaServer
from cria.upstream import Upstream

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server_config'))
from test_server_config_http import FakeUpstream, OPEN, WINDOW  # noqa: E402

from ops_rig import Harness, command_of  # noqa: E402

CHECKS = '⟦ctx:checks'
SHELL = {'name': 'exec_command', 'parameters': {'type': 'object', 'properties': {'cmd': {'type': 'string'}}, 'required': ['cmd']}}


class Scripted(FakeUpstream):
    """The shared fake upstream, except that the coder follows the case's script: one reply per coder request, then 'Done.'."""
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}'
        body = json.loads(raw)
        names = [t.get('function', {}).get('name') for t in body.get('tools') or []]
        text = json.dumps(body.get('messages'))
        coder = 'write_file' in names and 'REQUEST CLASSIFIER' not in text and not body.get('tool_choice')
        if coder and not self.path.endswith(('/tokenize', '/apply-template')):
            self.server.chats.append((dict(self.headers), body))
            n = self.server.coder_turns = getattr(self.server, 'coder_turns', 0) + 1
            script = self.server.script
            step = script[n - 1] if n <= len(script) else ('text', 'Done. The work is finished.')
            if step[0] == 'write':
                args = json.dumps({'path': step[1], 'content': step[2]})
                frames = [{'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': f'coder_{n}', 'type': 'function', 'function': {'name': 'write_file', 'arguments': args}}]}}]},
                          {'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}]}]
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': f'coder_{n}', 'type': 'function', 'function': {'name': 'write_file', 'arguments': args}}]}
                reason = 'tool_calls'
            else:
                frames = [{'choices': [{'delta': {'role': 'assistant', 'content': step[1]}}]}, {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}]
                message, reason = {'role': 'assistant', 'content': step[1]}, 'stop'
            if not body.get('stream'):
                return self._reply({'choices': [{'message': message, 'finish_reason': reason}]})
            self.close_connection = True
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            return self.wfile.write(b''.join(b'data: ' + json.dumps(f).encode() + b'\n\n' for f in frames) + b'data: [DONE]\n\n')
        self.rfile = io.BytesIO(raw)
        return super().do_POST()


class GateWire:
    """The shared Wire of the server tests with this rig's scripted upstream."""
    def __init__(self, tmp, script):
        self.fake = ThreadingHTTPServer(('127.0.0.1', 0), Scripted)
        self.fake.chats, self.fake.release, self.fake.script = [], threading.Event(), script
        threading.Thread(target=self.fake.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.fake.server_address[1]}'
        routing = RoutingConfig(backends={'local': Backend('local')},
                                roles={r: Role(r, 'local') for r in ('classifier', 'coder', 'compactor', 'reasoner')},
                                failover={'coding': ('coder',)}, engagement_bias='task', engagement_level=5)
        cfg = Config(server=ServerConfig(host='127.0.0.1', port=0, heartbeat_seconds=5.0), upstream=UpstreamConfig(base_url=self.url),
                     logging=LoggingConfig(dir=str(tmp), capture_dir=str(tmp / 'calls'), console=False, capture_calls=True),
                     indicators=IndicatorsConfig(enabled=False), routing=routing)
        self.log = EventLog(dir=str(tmp), console=False)
        self.cria = CriaServer(cfg, self.log, Upstream(self.url, context_window=WINDOW, engagement_level=5))
        threading.Thread(target=self.cria.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True).start()

    def post(self, body, sid='gate-char'):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(f'http://127.0.0.1:{self.cria.server_address[1]}/v1/chat/completions', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json', 'X-Cria-Session-Id': sid})
        try:
            with OPEN(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            raise AssertionError(f'cria answered {exc.code}: {exc.read().decode()[:1500]}') from None

    def close(self):
        for s in (self.cria, self.fake):
            s.shutdown()
            s.server_close()
        self.log.close()


def scrub(text, ws, scratch):
    text = text.replace(str(ws), '$WS').replace(str(scratch), '$SCRATCH')
    text = re.sub(r'\b[0-9a-f]{24}\b', '<id>', text)
    text = re.sub(r'\b(\d+\.\d+)s\b', '<secs>s', text)
    text = re.sub(r'in \d+\.\d+s', 'in <secs>s', text)
    text = re.sub(r'0x[0-9a-f]+', '0x<addr>', text)
    return text


def run_case(case, tmp_path, monkeypatch, limit=60):
    """Drive one case: returns what the model read of the gate, what the harness ran and what is on disk."""
    monkeypatch.setattr(system1wiring, 'build', lambda *args, **kwargs: None)
    for name, value in (case.get('patch') or {}).items():
        monkeypatch.setattr(probegate, name, value)
    ws = tmp_path / 'ws'
    ws.mkdir()
    for rel, text in case['files'].items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text if isinstance(text, bytes) else text.encode())
    if case.get('setup'):
        case['setup'](ws)
    wire = GateWire(tmp_path / 'wire', case['script'])
    harness = Harness(ws, env=case.get('env'))
    env = f'<environment_context><cwd>{ws}</cwd></environment_context>'
    request = {'model': 'm', 'tools': [{'type': 'function', 'function': SHELL}],
               'messages': [{'role': 'user', 'content': t} for t in (env, case.get('task', 'Implement the feature'))]}
    try:
        for _ in range(limit):
            message = wire.post(request)['choices'][0]['message']
            calls = message.get('tool_calls') or []
            if not calls:
                break
            request['messages'].append(message)
            for call in calls:
                request['messages'].append({'role': 'tool', 'tool_call_id': call['id'], 'content': harness(call)})
        seen, bodies = [], 0
        for _, body in wire.fake.chats:
            bodies += 1
            for m in body.get('messages') or []:
                content = m.get('content')
                if isinstance(content, list):
                    content = ''.join(p.get('text', '') for p in content if isinstance(p, dict))
                if isinstance(content, str) and CHECKS in content:
                    text = scrub(content, ws, harness.cwd + '.scratch')
                    if text not in seen:
                        seen.append(text)
        commands = [command_of(c) for c in harness.ran]
        return {'evidence': seen, 'requests': bodies, 'harness_calls': len(commands),
                'command_bytes': sum(len(c.encode()) for c in commands),
                'litter': sorted(p for p in os.listdir(harness.cwd + '.scratch') if p.startswith('.ctx'))
                + sorted(p for p in os.listdir(ws) if p.startswith('.ctx'))}
    finally:
        wire.close()
