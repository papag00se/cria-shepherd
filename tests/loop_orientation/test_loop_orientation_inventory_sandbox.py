"""The pager is executable through Codex's real, machine-policy sandbox without a model."""
import http.server
import json
import os
import shutil
import subprocess
import threading
import tomllib

import pytest

from cria import dirguard, initial_inventory, loop, responses
from cria.classify import Classification
from suite import run


@pytest.mark.skipif(not shutil.which('codex'), reason='requires local Codex sandbox')
def test_initial_inventory_reaches_coder_through_real_unified_exec(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'seed.py').write_text('def sample(): pass\n')
    # Codex's sandbox may create these protected-directory mount points itself.
    for name in ('.agents', '.aws', '.codex', '.git'):
        (workspace / name).mkdir()
    installs = tmp_path / 'installs'
    installs.mkdir()
    monkeypatch.setattr(run, 'CELL_INSTALLS_DIR', installs)
    scratch = run._cell_install_root(workspace)
    scratch.mkdir()
    home = scratch / 'codex-home'
    home.mkdir()
    bodies, received, errors = [], [], []

    def coder(body, rlog):
        bodies.append(body)
        return json.dumps({'choices': [{'message': {'role': 'assistant', 'content': None,
            'tool_calls': [{'id': 'coder-action', 'type': 'function', 'function': {
                'name': 'exec_command', 'arguments': json.dumps({'cmd': 'true'})}}]},
            'finish_reason': 'tool_calls'}]}).encode()

    driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=coder, reasoner_chat=coder,
        reasoner_buffered_chat=coder, runs_dir='', workspace_root=str(workspace), assists=True), loop.LoopStore())

    class Log:
        phase = ''
        def emit(self, *args, **kwargs):
            pass

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            try:
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append(request)
                result = driver.drive(responses.to_chat_body(request), 'sid:fixture',
                                      Classification('task', 'coding', 'fixture'), Log())
                if bodies:
                    result = {'choices': [{'message': {'role': 'assistant', 'content': 'finished'}, 'finish_reason': 'stop'}]}
                data = b''.join(responses.to_responses_sse(result, 'fixture'))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as exc:
                errors.append(exc)
                self.send_error(500)

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (home / 'config.toml').write_text(
            f'model="fixture"\nmodel_provider="local"\n[model_providers.local]\n'
            f'name="local"\nbase_url="http://127.0.0.1:{server.server_port}/v1"\nwire_api="responses"\n')
        argv = run._codex_argv('Implement the feature', workspace)
        argv.insert(2, '--skip-git-repo-check')
        result = subprocess.run(argv, cwd=workspace,
            env={**os.environ, 'CODEX_HOME': str(home), 'TMPDIR': str(scratch)},
            capture_output=True, text=True, timeout=90)
        assert not errors
        assert result.returncode == 0
        assert bodies
        sent = json.dumps(bodies[0]['messages'])
        assert 'Implement the feature' in sent and 'seed.py' in sent
        assert 'Initial harness workspace inventory' in sent
        assert 'Argument list too long' not in sent and '___CTX_GATE_' not in sent
        assert sorted(str(p.relative_to(workspace)) for p in workspace.rglob('*')) == [
            '.agents', '.aws', '.codex', '.git', 'seed.py']
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.skipif(not shutil.which('codex'), reason='requires local Codex sandbox')
def test_inventory_pages_in_real_sandbox(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace with 'quote' ; metachar $cash `tick`"
    workspace.mkdir()
    installs = tmp_path / 'installs'
    installs.mkdir()
    monkeypatch.setattr(run, 'CELL_INSTALLS_DIR', installs)
    scratch = run._cell_install_root(workspace)
    scratch.mkdir()
    home = tmp_path / 'codex-home'
    home.mkdir()
    for i in range(60):
        (workspace / f'file-{i:03}.py').write_text('def okay(): pass\n')
    try:
        settings = run._codex_argv('unused', workspace)[2:-1]
    except ValueError as exc:
        pytest.skip(f'machine-local sandbox policy unavailable: {exc}')
    profile = tomllib.loads(next(a for a in settings if a.startswith('default_permissions=')))['default_permissions']
    command = initial_inventory.browse_command(str(workspace))
    assert dirguard.command_refusal(command + ' 0', 'none', str(workspace)) is None
    offset, pages = 0, []
    while True:
        result = subprocess.run(['codex', 'sandbox', '-P', profile, *settings, '-C', str(workspace),
                                 '--', 'sh', '-c', command + ' ' + str(offset)],
                                env={**os.environ, 'CODEX_HOME': str(home), 'TMPDIR': str(scratch)},
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert len(result.stdout) < 2048
        header, payload = result.stdout.split('\n', 1)
        tag, start, end, total = header.split()
        assert tag == 'current-inventory' and int(start) == offset
        payload = payload.removesuffix('\n')
        assert len(payload) == int(end) - offset
        pages.append(payload)
        offset = int(end)
        if offset == int(total):
            break
    data = json.loads(''.join(pages))
    assert len(pages) > 1 and len(data['files']) == 60 and not data['errors']
    assert len(list(workspace.iterdir())) == 60
