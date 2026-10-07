"""Real pinned harness, fake upstream: patch advertised, executed, and replayed at L0."""
import json
import os
import subprocess
from pathlib import Path
import pytest
from suite import run
from test_engagement_levels import _Harness
from test_server import _FakeUpstream


@pytest.mark.skipif(not run.RESTORED_CODEX_BINARY.exists(), reason='pinned Codex integration')
@pytest.mark.parametrize('outside_write', [False, True])
def test_pinned_codex_executes_custom_patch_at_l0_without_shared_home_drift(tmp_path, monkeypatch, outside_write):
    outside = tmp_path / 'outside.txt'
    outside.write_text('preserve')
    target = '../outside.txt' if outside_write else 'proof.txt'
    patch = f'*** Begin Patch\n*** Add File: {target}\n+written by sandboxed patch tool\n*** End Patch'
    from cria import massage
    monkeypatch.setattr(massage, '_TOOL_CALL_FIXES', massage._TOOL_CALL_FIXES)
    seen = []

    def post(handler):
        body = json.loads(handler.rfile.read(int(handler.headers['Content-Length'])))
        seen.append(body)
        if any(m.get('role') == 'tool' for m in body['messages']):
            msg, finish = {'content': 'Done'}, 'stop'
        else:
            msg, finish = {'tool_calls': [{'index': 0, 'id': 'proof-call', 'type': 'function',
                'function': {'name': 'apply_patch', 'arguments': json.dumps({'input': patch})}}]}, 'tool_calls'
        if body.get('stream'):
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/event-stream')
            handler.send_header('Connection', 'close')
            handler.end_headers()
            handler.close_connection = True
            chunks = [{'choices': [{'index': 0, 'delta': msg}]},
                      {'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}]}]
            handler.wfile.write((''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks)
                                 + 'data: [DONE]\n\n').encode())
            handler.wfile.flush()
        else:
            handler._json(json.dumps({'choices': [{'index': 0, 'message': {'role': 'assistant', **msg},
                                                   'finish_reason': finish}]}).encode())

    monkeypatch.setattr(_FakeUpstream, 'do_POST', post)
    policy = tmp_path / 'policy.toml'
    policy.write_text('workspace_sandbox=true\n')
    monkeypatch.setattr(run, 'SUITE_CODEX_POLICY', policy)
    template = tmp_path / 'template'
    template.mkdir()
    (template / 'config.toml').write_text('model_provider="cria"\n[model_providers.cria]\n'
        'name="Local"\nbase_url="http://127.0.0.1:18085/v1"\nwire_api="responses"\n')
    baseline = (template / 'config.toml').read_bytes()
    monkeypatch.setattr(run, 'SUITE_CODEX_HOME', template)
    workspace, state = tmp_path / 'workspace', tmp_path / 'state'
    workspace.mkdir()
    state.mkdir()
    monkeypatch.setattr(run, '_cell_install_root', lambda _: state)
    env = run._codex_env(dict(os.environ), workspace)
    env['TMPDIR'] = str(state)
    h = _Harness(0, False)
    try:
        argv, provenance = run.restored_codex_argv(run._codex_argv('Create proof.txt', workspace),
            'gemma4_12b', 49152, h.base + '/v1', Path(env['CODEX_HOME']))
        result = subprocess.run([*argv[:-1], '--skip-git-repo-check', argv[-1]], cwd=workspace,
            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert 'Model metadata' not in result.stderr
        assert outside.read_text() == 'preserve'
        if not outside_write:
            assert (workspace / 'proof.txt').read_text() == 'written by sandboxed patch tool\n'
        assert (template / 'config.toml').read_bytes() == baseline
        assert provenance['model_catalog']['sha256']
        assert len(seen) == 2
        assert 'apply_patch' in [t['function']['name'] for t in seen[0]['tools']]
        historical = next(m for m in seen[1]['messages'] if m.get('tool_calls'))
        assert json.loads(historical['tool_calls'][0]['function']['arguments']) == {'input': patch}
        assert any(m['role'] == 'tool' and m['content'] for m in seen[1]['messages'])
        if not outside_write:
            assert any('Success' in m.get('content', '') for m in seen[1]['messages'] if m['role'] == 'tool')
    finally:
        h.close()
