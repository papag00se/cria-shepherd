"""The primitives through the pinned Codex in its sandbox: the commands are echoed byte for byte (the MACs depend on it), every stub
runs under the sandbox policy, the E2BIG boundary is where the design says, and the per-round-trip cost is measured."""
import http.server
import json
import statistics
import threading

import pytest

from cria import harnessprims, responses
from codex_rig import Sandbox, Timeline, function_calls, needs_codex
from ops_rig import isolated_home  # noqa: F401
from prims_rig import GROUP, sha

pytestmark = needs_codex


class Scripted(http.server.ThreadingHTTPServer):
    """A Responses endpoint that sends one tool call per turn, in order, and a final message after the last."""
    def __init__(self, commands):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(handler):
                request = json.loads(handler.rfile.read(int(handler.headers['Content-Length'])))
                self.timeline.request_arrived()
                self.requests.append(request)
                turn = len(self.requests) - 1
                if turn < len(self.commands):
                    message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': f'call_{turn}', 'type': 'function', 'function': {
                        'name': 'exec_command', 'arguments': json.dumps({'cmd': self.commands[turn]})}}]}
                    finish = 'tool_calls'
                else:
                    message, finish = {'role': 'assistant', 'content': 'done'}, 'stop'
                data = b''.join(responses.to_responses_sse({'choices': [{'message': message, 'finish_reason': finish}]}, 'fixture'))
                handler.send_response(200)
                handler.send_header('Content-Type', 'text/event-stream')
                handler.send_header('Content-Length', str(len(data)))
                handler.end_headers()
                handler.wfile.write(data)
                self.timeline.reply_sent(turn < len(self.commands))
        super().__init__(('127.0.0.1', 0), Handler)
        self.commands, self.requests, self.timeline = commands, [], Timeline()

    def __enter__(self):
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.shutdown()
        self.server_close()

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server_port}/v1'


def outputs_of(server):
    last = server.requests[-1]
    return {cid: out for cid, _args, out in function_calls(last)}


def frame_of(output, nonce):
    return harnessprims.read_frame(output, nonce)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    return Sandbox(tmp_path, monkeypatch)


def test_every_stub_runs_under_the_sandbox_the_command_is_echoed_byte_for_byte_and_e2big_is_where_the_design_says(sandbox):
    ws, scratch = str(sandbox.workspace), str(sandbox.scratch)
    (sandbox.workspace / 'src').mkdir()
    (sandbox.workspace / 'src' / 'a.py').write_bytes(b'x = 1\r\nprint(\xff)\n')
    nonces = ['%032x' % i for i in range(1, 12)]
    new = b'written through the sandbox\n'
    big = bytes(range(256)) * 175 + b'x' * 200                              # exactly 45,000 raw bytes: the design's one-command payload
    assert len(big) == 45_000
    huge = bytes(range(256)) * 430                                        # 110,080 raw bytes: past MAX_ARG_STRLEN as base64
    commands = [
        harnessprims.compose('read', nonces[0], [ws, 'src/a.py', 0, 100], comment='read src/a.py'),
        harnessprims.compose('write', nonces[1], [ws, 'out/new.txt', '-', '-', sha(new), 0, 1, GROUP], new),
        harnessprims.compose('ls', nonces[2], [ws, '', 0, 100, 0, '[]', '']),
        harnessprims.compose('run', nonces[3], ['start', scratch, 'tok1', 20, 10, ws, 0], text='true'),
        harnessprims.compose('write', nonces[4], [ws, 'big.bin', '-', '-', sha(big), 0, 1, GROUP], big),
        harnessprims.compose('write', nonces[5], [ws, 'huge.bin', '-', '-', sha(huge), 0, 1, GROUP], huge),
        harnessprims.compose('rm', nonces[6], [ws, 'out/new.txt', 'f', sha(new)]),
    ]
    with Scripted(commands) as server:
        done = sandbox.run(server.url)
        assert done.returncode == 0, done.stderr[-2000:]
        calls = {cid: (args, out) for cid, args, out in function_calls(server.requests[-1])}
    assert [json.loads(calls[f'call_{i}'][0])['cmd'] for i in range(7)] == commands            # echoed byte for byte
    out = lambda i: calls[f'call_{i}'][1]
    assert frame_of(out(0), nonces[0]).data == b'x = 1\r\nprint(\xff)\n'
    assert frame_of(out(1), nonces[1]).header['landed'] == 1 and (sandbox.workspace / 'out' / 'new.txt').exists() is False   # removed by call 6
    assert {r[1] for r in map(json.loads, frame_of(out(2), nonces[2]).data.decode().splitlines())} >= {'src', 'src/a.py'}
    run = frame_of(out(3), nonces[3])
    assert run.header['state'] == 'done' and run.header['exit'] == 0
    assert frame_of(out(4), nonces[4]).header['landed'] == 1 and (sandbox.workspace / 'big.bin').read_bytes() == big and len(commands[4].encode()) < 64 * 1024
    assert 'Argument list too long' in out(5) and not (sandbox.workspace / 'huge.bin').exists() and len(commands[5].encode()) > 128 * 1024
    assert frame_of(out(6), nonces[6]).header['removed'] == 1


def test_per_round_trip_latency_of_a_lowered_primitive_call_through_the_sandboxed_harness(sandbox):
    ws = str(sandbox.workspace)
    for i in range(40):
        (sandbox.workspace / f'file-{i}.txt').write_text('x' * i)
    commands = []
    for i in range(24):
        commands.append(harnessprims.compose('ls', '%032x' % (100 + i), [ws, '', 1, 1000, 0, '[]', ''], comment='list_dir .'))
    with Scripted(commands) as server:
        done = sandbox.run(server.url)
        assert done.returncode == 0, done.stderr[-2000:]
        seconds = server.timeline.seconds
    assert len(seconds) >= 24 - 1
    seconds = sorted(seconds)
    print('LATENCY ls round trips (s): n=%d min=%.3f median=%.3f p90=%.3f max=%.3f' % (
        len(seconds), seconds[0], statistics.median(seconds), seconds[int(len(seconds) * .9)], seconds[-1]))
    assert statistics.median(seconds) < 5


def test_list_dir_through_the_pinned_codex_and_a_real_cria_server(sandbox, tmp_path):
    """The whole route, nothing imitated: scripted model -> real CriaServer -> real pinned Codex in its sandbox -> real stubs."""
    import os
    import re
    import sys
    sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / 'read_multipart'))
    from cria.config import Config, IndicatorsConfig, LoggingConfig, RoutingConfig, ServerConfig
    from cria.events import EventLog
    from cria.server import CriaServer
    from ops_rig import ListBackend
    ws = sandbox.workspace
    (ws / 'src').mkdir()
    (ws / 'src' / 'a.py').write_text('x = 1\n')
    for i in range(150):
        (ws / f'a_fairly_long_file_name_to_force_a_spill_{i:04}.txt').write_text('')
    backend = ListBackend('src', '.')
    cfg = Config(server=ServerConfig(host='127.0.0.1', port=0), logging=LoggingConfig(dir=str(tmp_path / 'logs'), console=False),
                 indicators=IndicatorsConfig(enabled=False), routing=RoutingConfig(engagement_level=2))
    log = EventLog(dir=cfg.logging.dir, console=False)
    server = CriaServer(cfg, log, backend)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        done = sandbox.run(f'http://127.0.0.1:{server.server_address[1]}/v1')
        assert done.returncode == 0, done.stderr[-2000:]
    finally:
        server.shutdown()
        server.server_close()
        log.close()
    assert len(backend.bodies) >= 2
    seen = json.dumps(backend.bodies[-1]['messages'])
    results = [m for m in backend.bodies[-1]['messages'] if m.get('role') == 'tool']
    assert [m['tool_call_id'] for m in results] == ['model_call_0', 'model_call_1']
    assert 'a.py' in results[0]['content'] and re.search(r'stdout-[0-9a-f]{64}\.txt', results[1]['content'])
    assert not [p for p in ('CTX1', 'ctx_', 'python3', '-I -S', 'harness-call', 'CTX_EOF') if p in seen]
    saved = next((ws / 'tmp' / 'reference').iterdir())
    assert saved.read_text().count('\n') >= 150
