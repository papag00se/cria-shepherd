"""Pinned harness: measured usage compacts; typed overflow stops without blind retries."""
import json
import os
import subprocess
from pathlib import Path

import pytest
from suite import run
from test_engagement_levels import _Harness
from test_server import _FakeUpstream


@pytest.mark.skipif(not run.RESTORED_CODEX_BINARY.exists(), reason='pinned Codex integration')
@pytest.mark.parametrize('trigger', ['usage', 'overflow'])
def test_pinned_codex_owns_context_recovery_at_l0(tmp_path, monkeypatch, trigger):
    from cria import massage
    monkeypatch.setattr(massage, '_TOOL_CALL_FIXES', massage._TOOL_CALL_FIXES)
    seen, compactions = [], []
    rejected = False
    def post(handler):
        nonlocal rejected
        body = json.loads(handler.rfile.read(int(handler.headers['Content-Length'])))
        seen.append(body)
        if not body.get('tools'):
            compactions.append(body)
            message = {'content': 'The user requested a local echo. The echo command succeeded. No files changed.'}
            usage = {'prompt_tokens': 500, 'completion_tokens': 20, 'total_tokens': 520}
        elif len(seen) == 1:
            message = {'tool_calls': [{'id': 'echo-proof', 'type': 'function', 'function': {
                'name': 'exec_command', 'arguments': json.dumps({'cmd': 'echo context-proof'})}}]}
            prompt = 48614 if trigger == 'usage' else 500
            usage = {'prompt_tokens': prompt, 'completion_tokens': 20, 'total_tokens': prompt + 20}
        elif trigger == 'overflow' and not rejected:
            rejected = True
            raw = json.dumps({'error': {'message': 'request exceeds context',
                'type': 'exceed_context_size_error', 'code': 400,
                'n_prompt_tokens': 49348, 'n_ctx': 49152}}).encode()
            handler.send_response(400)
            handler.send_header('Content-Length', str(len(raw)))
            handler.end_headers()
            handler.wfile.write(raw)
            return
        else:
            message = {'content': 'Done: context-proof.'}
            usage = {'prompt_tokens': 500, 'completion_tokens': 20, 'total_tokens': 520}
        handler._json(json.dumps({'choices': [{'message': {'role': 'assistant', **message},
            'finish_reason': 'tool_calls' if message.get('tool_calls') else 'stop'}], 'usage': usage}).encode())
    monkeypatch.setattr(_FakeUpstream, 'do_POST', post)
    policy = tmp_path / 'policy.toml'
    policy.write_text('workspace_sandbox=true\n')
    monkeypatch.setattr(run, 'SUITE_CODEX_POLICY', policy)
    template = tmp_path / 'template'
    template.mkdir()
    (template / 'config.toml').write_text('model_provider="cria"\n[model_providers.cria]\n'
        'name="Local"\nbase_url="http://127.0.0.1:18085/v1"\nwire_api="responses"\n')
    monkeypatch.setattr(run, 'SUITE_CODEX_HOME', template)
    workspace, state = tmp_path / 'workspace', tmp_path / 'state'
    workspace.mkdir()
    state.mkdir()
    monkeypatch.setattr(run, '_cell_install_root', lambda _: state)
    env = run._codex_env(dict(os.environ), workspace)
    env['TMPDIR'] = str(state)
    h = _Harness(0, False)
    try:
        argv, _ = run.restored_codex_argv(run._codex_argv('Run echo context-proof, then finish.', workspace),
            'ornith1.5_9b', 49152, h.base + '/v1', Path(env['CODEX_HOME']))
        result = subprocess.run([*argv[:-1], '--skip-git-repo-check', argv[-1]], cwd=workspace,
            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        assert seen[0].get('tools')
        assert seen[-1].get('tools')
        assert not any(k.startswith(('context.floor', 'summarize.', 'loop.', 'plan.')) for k in h.kinds())
        if trigger == 'usage':
            assert result.returncode == 0, result.stderr
            assert len(compactions) == 1, result.stderr
        else:
            # Codex0.159.3 does not repair an already-rejected context; it exits safely.
            # Recovery therefore depends on accurate usage BEFORE reaching that rejection.
            assert result.returncode == 1, result.stderr
            assert 'context window' in result.stderr
            assert rejected and len(seen) == 2 and not compactions
            assert 'Reconnecting...' not in result.stderr
    finally:
        h.close()
