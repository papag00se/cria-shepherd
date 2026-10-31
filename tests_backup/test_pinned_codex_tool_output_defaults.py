"""The capability catalog must preserve pinned Codex's pre-catalog output-budget default."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from suite import run
from test_engagement_levels import _Harness
from test_server import _FakeUpstream


@pytest.mark.skipif(not run.RESTORED_CODEX_BINARY.exists(), reason='pinned Codex integration')
@pytest.mark.parametrize('base', [13839, 26438])
def test_capability_catalog_preserves_default_dense_output_and_fits_burst(tmp_path, monkeypatch, base):
    from cria import massage
    # The real server sets process-global engagement policy; restore it at fixture teardown.
    monkeypatch.setattr(massage, '_TOOL_CALL_FIXES', massage._TOOL_CALL_FIXES)
    outputs = {}
    for arm in ('without-catalog', 'with-catalog'):
        state = tmp_path/arm
        state.mkdir()
        workspace, template = state/'workspace', state/'template'
        workspace.mkdir()
        template.mkdir()
        policy = state/'policy.toml'
        policy.write_text('workspace_sandbox=true\n')
        (template/'config.toml').write_text('model_provider="cria"\n[model_providers.cria]\n'
            'name="Local"\nbase_url="http://127.0.0.1:18085/v1"\nwire_api="responses"\n')
        seen, failures, tool_outputs = [], [], []
        def post(handler):
            body = json.loads(handler.rfile.read(int(handler.headers['Content-Length'])))
            seen.append(body)
            if len(seen) == 1:
                names = {t['function']['name'] for t in body.get('tools', []) if t.get('type') == 'function'}
                command = "seq -f '  SKU-%05g: 4326.28' 0 8999"
                if 'exec_command' in names:
                    name, args = 'exec_command', {'cmd': command}
                elif 'shell_command' in names:
                    name, args = 'shell_command', {'command': command}
                else:
                    assert 'shell' in names
                    name, args = 'shell', {'command': ['bash', '-lc', command]}
                message = {'tool_calls': [{'id': 'dense-output', 'type': 'function', 'function': {
                    'name': name, 'arguments': json.dumps(args)}}]}
                usage = {'prompt_tokens': base, 'completion_tokens': 184, 'total_tokens': base+184}
            else:
                result = next(m['content'] for m in reversed(body['messages']) if m['role'] == 'tool')
                tool_outputs.append(result)
                # Scripted adverse tokenizer: a byte costs one token. The measured previous
                # context plus this complete result (including framing) must actually fit.
                actual = base+184+len(result.encode())
                if actual > 49152:
                    failures.append(body)
                    error = json.dumps({'error': {'type': 'exceed_context_size_error',
                        'code': 400, 'message': 'tool result exceeds context',
                        'n_prompt_tokens': actual, 'n_ctx': 49152}}).encode()
                    handler.send_response(400)
                    handler.send_header('Content-Length', str(len(error)))
                    handler.end_headers()
                    handler.wfile.write(error)
                    return
                message = {'content': 'Dense-output round trip completed.'}
                usage = {'prompt_tokens': actual, 'completion_tokens': 20, 'total_tokens': actual+20}
            handler._json(json.dumps({'choices': [{'message': {'role': 'assistant', **message},
                'finish_reason': 'tool_calls' if message.get('tool_calls') else 'stop'}], 'usage': usage}).encode())
        with monkeypatch.context() as patch:
            patch.setattr(_FakeUpstream, 'do_POST', post)
            patch.setattr(run, 'SUITE_CODEX_POLICY', policy)
            patch.setattr(run, 'SUITE_CODEX_HOME', template)
            patch.setattr(run, '_cell_install_root', lambda _: state)
            env = run._codex_env(dict(os.environ), workspace)
            env['TMPDIR'] = str(state)
            h = _Harness(0, False)
            try:
                argv, _ = run.restored_codex_argv(run._codex_argv('Run the local command, then finish.', workspace),
                    'ornith1.5_9b', 49152, h.base+'/v1', Path(env['CODEX_HOME']))
                if arm == 'without-catalog':
                    i = next(i for i, arg in enumerate(argv) if arg.startswith('model_catalog_json='))
                    assert argv[i-1] == '-c'
                    del argv[i-1:i+1]
                result = subprocess.run([*argv[:-1], '--skip-git-repo-check', argv[-1]], cwd=workspace,
                    env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
                assert result.returncode == 0, result.stderr
                assert not failures, 'successful exit cannot conceal overflow or compaction history deletion'
                assert len(seen) == 2 and all(body.get('tools') for body in seen)
                assert 'Reconnecting...' not in result.stderr
                assert len(tool_outputs) == 1
                output = tool_outputs[0]
                assert 'truncated' in output and 'SKU-00000' in output and 'SKU-08999' in output
                assert len(output.encode()) < 11000
                outputs[arm] = output.split('Output:',1)[1]
                assert not any(k.startswith(('context.floor', 'summarize.', 'loop.', 'plan.')) for k in h.kinds())
                # The actual client rollout is the authoritative harness output, not our fake.
                sessions = Path(env['CODEX_HOME'])/'sessions'
                original = [item['payload']['output'] for path in sessions.rglob('rollout-*.jsonl')
                            for item in (json.loads(line) for line in path.read_text().splitlines())
                            if item.get('type') == 'response_item'
                            and item.get('payload',{}).get('type') == 'function_call_output']
                assert original == [output]  # L0 did not add another clip or rewrite the tool voice
            finally:
                h.close()
    assert outputs['without-catalog'] == outputs['with-catalog']
