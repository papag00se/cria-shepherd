"""Actual sandboxed client decision: private consumption must not force compaction.

All HTTP endpoints are CPU-only local fixtures. No native model, GPU, live
service, global home, benchmark workspace or machine policy is modified.
"""
import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess

import pytest
from cria import assistprofiles, assistruntime, config, loop, prompts, server
from suite import run
from test_engagement_levels import _Harness
from test_server import _CLASSIFY_JSON, _FakeUpstream, _compaction_validation_verdict


@pytest.mark.skipif(not run.RESTORED_CODEX_BINARY.exists(), reason='pinned Codex integration')
@pytest.mark.parametrize('mode', ['old-consumption', 'continuing-context', 'large-public'])
def test_pinned_client_compacts_for_retained_context_not_private_consumption(tmp_path, monkeypatch, mode):
    legacy = mode == 'old-consumption'
    large_public = mode == 'large-public'
    native = {'prompt_tokens': 13734, 'completion_tokens': 32467, 'total_tokens': 46201,
              'prompt_tokens_details': {'cached_tokens': 13004}}
    calls, wire, upstream_phases = [], [], []
    def drive(self, body, key, classification, rlog, *, pasted_delivery=None):
        assert assistruntime.current().profile == 'rank4-ablation'
        assert not set(assistruntime.current().selected).intersection(assistprofiles.RANK4_ABLATION_DISABLED)
        calls.append(copy.deepcopy(body))
        if len(calls) == 1:
            message = {'role': 'assistant',
                       'content': ('Public evidence.\n' * 8000 if large_public
                                   else 'Checking the environment before making changes.'),
                       'reasoning_content': '' if large_public else 'Private implementation deliberation.\n' * 3600,
                       'tool_calls': [{'id': 'context-proof', 'type': 'function', 'function': {
                           'name': 'exec_command', 'arguments': '{"cmd":"echo context-proof"}'}}]}
            usage = copy.deepcopy(native)
        else:
            message = {'role': 'assistant', 'content': 'Done: context-proof.'}
            usage = {'prompt_tokens': 500, 'completion_tokens': 20, 'total_tokens': 520}
        return {'choices': [{'message': message,
                 'finish_reason': 'tool_calls' if message.get('tool_calls') else 'stop'}], 'usage': usage}
    monkeypatch.setattr(loop.Loop, 'drive', drive)
    def summary(handler):
        body = json.loads(handler.rfile.read(int(handler.headers['Content-Length'])))
        assert not body.get('tools'), 'coding must use the scripted driver'
        system = body['messages'][0]['content']
        # The profile keeps L1 classification and L3 harness-memory handoff. Their
        # judges need real fixture answers; summary prose makes recognition abstain
        # and classification retry/fall back, misrouting compaction into the driver.
        if system == prompts.load('classify'):
            upstream_phases.append('classifier')
            handler._json(_CLASSIFY_JSON)
            return
        verdict = _compaction_validation_verdict(system)
        if 'ASKING FOR A SUMMARY OF THE CONVERSATION SO FAR' in system:
            upstream_phases.append('compaction-recognize')
            content = 'YES'
        elif verdict:
            upstream_phases.append('compaction-validate')
            content = verdict
        else:
            assert system == prompts.load('selfcompact_summary')
            upstream_phases.append('summary')
            content = 'The task requested echo context-proof. The echo succeeded.'
        handler._json(json.dumps({'choices': [{'message': {'role': 'assistant',
            'content': content},
            'finish_reason': 'stop'}], 'usage': {
                'prompt_tokens': 500, 'completion_tokens': 20, 'total_tokens': 520}}).encode())
    monkeypatch.setattr(_FakeUpstream, 'do_POST', summary)
    if legacy:
        # The exact former producer contract, retained solely as the client-decision control.
        def old_report(completion, ctx_tokens, rlog, **kwargs):
            consumed = (completion.get('usage') or {}).get('completion_tokens') or 0
            completion['usage'] = {'prompt_tokens': ctx_tokens, 'completion_tokens': consumed,
                                   'total_tokens': ctx_tokens + consumed}
        monkeypatch.setattr(server, '_report_context_usage', old_report)
    original_init = server.CriaServer.__init__
    def exact_server(instance, cfg, log, upstream):
        cfg = replace(cfg, assists=config.AssistConfig(profile='rank4-ablation'),
                      indicators=config.IndicatorsConfig(enabled=True))
        return original_init(instance, cfg, log, upstream)
    monkeypatch.setattr(server.CriaServer, '__init__', exact_server)
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
    harness = _Harness(5, False)
    original_write = server.CriaHandler._raw_write
    def capture(handler, raw):
        if handler.server is harness.cria:
            wire.append(raw)
        return original_write(handler, raw)
    monkeypatch.setattr(server.CriaHandler, '_raw_write', capture)
    try:
        assert harness.cria.cfg.assists.profile == 'rank4-ablation'
        assert set(harness.cria.pilot_runtime.selected).isdisjoint(assistprofiles.RANK4_ABLATION_DISABLED)
        assert not harness.cria.cfg.planner.enabled
        fake_provider = f'http://127.0.0.1:{harness.fake.server_address[1]}'
        assert harness.cria.cfg.upstream.base_url == fake_provider
        assert all(backend.base_url == fake_provider
                   for backend in harness.cria.cfg.routing.backends.values())
        task = ('Run echo context-proof, then finish. Retain this reference until the echo returns:\n'
                + 'REFERENCE evidence stays available.\n' * 700)
        argv, _ = run.restored_codex_argv(run._codex_argv(task, workspace),
            'ornith1.5_9b', 49152, harness.base + '/v1', Path(env['CODEX_HOME']))
        assert any('model_providers.cria.base_url=' in arg and harness.base + '/v1' in arg for arg in argv)
        result = subprocess.run([*argv[:-1], '--skip-git-repo-check', argv[-1]], cwd=workspace,
            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45)
        assert result.returncode == 0, result.stderr
        events = [json.loads(line[6:]) for line in b''.join(wire).decode().splitlines()
                  if line.startswith('data: ')]
        replies = [event['response'] for event in events if event.get('type') == 'response.completed']
        assert replies and len(calls) == 2
        assert upstream_phases.count('classifier') == 1
        assert upstream_phases.count('summary') == int(legacy or large_public)
        assert upstream_phases.count('compaction-recognize') == int(legacy or large_public)
        usage = replies[0]['usage']
        trigger = int(49152 * .85)
        if legacy or large_public:
            assert usage['total_tokens'] >= trigger
        else:
            assert usage['total_tokens'] < trigger
            assert 'context-proof' in json.dumps(calls[1]['messages'])
            assert any(m.get('role') == 'tool' and 'context-proof' in str(m.get('content'))
                       for m in calls[1]['messages'])
        if not legacy:
            assert usage['native_usage'] == native
            assert usage['context_estimate']['estimated'] is True
        records = [json.loads(line) for path in Path(env['CODEX_HOME']).rglob('rollout-*.jsonl')
                   for line in path.read_text().splitlines() if line.strip()]
        assert any(record.get('type') == 'compacted' for record in records) is (legacy or large_public)
        assert any(item.get('type') == 'reasoning' for item in replies[0]['output']) is (not large_public)
        assert 'context-proof' in result.stdout or 'context-proof' in result.stderr
        harness.kinds()  # Settle the handler's final bookkeeping before reading its events.
        requests = [event for event in map(json.loads, Path(harness.log.path).read_text().splitlines())
                    if event.get('kind') == 'request.recv']
        assert requests
        assert all(event['assist_profile'] == 'rank4-ablation'
                   and set(event['pilot_assists']) == set(harness.cria.pilot_runtime.selected)
                   for event in requests)
    finally:
        harness.close()
