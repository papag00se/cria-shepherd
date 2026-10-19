"""1792364269: a real cleanup receipt became unavailable after historical rebuild."""
import base64
import hashlib
import io
import json
import subprocess

import pytest
from cria import assistruntime, loop, probegate, proberun, prompts, wsview
from test_gate_cleanup_finishes_before_coder_resumes import harness_env, run_gate
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog


def page(plan, raw):
    data = raw.encode()
    return '\n'.join([probegate._transport_marker(plan.transport_id),
        'path\t' + base64.b64encode(plan.transport_path.encode()).decode(), 'offset\t0',
        f'total\t{len(data)}', 'sha256\t' + hashlib.sha256(data).hexdigest(),
        'data\t' + base64.b64encode(data).decode(), probegate._transport_marker(plan.transport_id, end=True)])


def history(plan, raw):
    return [{'role': 'assistant', 'tool_calls': [{'id': 'gate', 'type': 'function',
             'function': {'name': 'exec_command', 'arguments': json.dumps({'cmd': plan.script})}}]},
            {'role': 'tool', 'tool_call_id': 'gate', 'content': page(plan, raw)}]


@pytest.mark.parametrize('superseded', [False, True])
def test_real_completed_cleanup_keeps_original_scope_when_rebuilt(tmp_path, monkeypatch, superseded):
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5, profile='rank4-ablation')):
        plan, raw = run_gate(tmp_path, monkeypatch)
        messages = history(plan, raw)
        current = probegate.GatePlan(workspace='/another/workspace') if superseded else None
        rendered = probegate.clean_gate_results(messages, current)
    text = '\n'.join(m.get('content') or '' for m in rendered)
    assert prompts.load('checks_cleanup_unknown') not in text
    assert 'exclusively owned private' in text and 'original workspace, not a copy' in text
    assert 'aux/compiled' in text and 'native build output for output/compiled' in text
    assert (tmp_path / 'output/compiled').read_text() == 'project build artifact'


@pytest.mark.parametrize('scope', ['foreign', 'missing', 'cold'])
def test_unknown_or_foreign_historical_scope_never_authenticates_a_receipt(tmp_path, monkeypatch, scope):
    plan, raw = run_gate(tmp_path, monkeypatch)
    if scope == 'cold':
        probegate._transport_facts.pop(plan.transport_id)
    else:
        raw = raw.replace(json.dumps(str(tmp_path)), json.dumps('/foreign/workspace')) if scope == 'foreign' else raw.replace(
            '"requested_workspace": ' + json.dumps(str(tmp_path)), '"missing_scope": ' + json.dumps(str(tmp_path)))
    text = '\n'.join(m.get('content') or '' for m in probegate.clean_gate_results(history(plan, raw)))
    assert prompts.load('checks_cleanup_unknown') in text
    assert 'reclaimed these' not in text
    assert 'native build output for output/compiled' in text


@pytest.mark.parametrize('workspace_declared', [False, True])
def test_real_bootstrap_without_candidates_retains_its_request_scope(tmp_path, monkeypatch, workspace_declared):
    monkeypatch.setattr(proberun, 'select_completion_probes', lambda root: [])
    plan = probegate.plan_gate(str(tmp_path) if workspace_declared else '')
    result = subprocess.run(['sh', '-c', plan.script], cwd=tmp_path, env=harness_env(tmp_path),
                            capture_output=True, text=True, check=True)
    probegate.interpret_gate(plan, result.stdout)
    assert plan.transport_complete and not plan.candidates
    rendered = probegate.clean_gate_results(history(plan, plan.transport_data.decode()))
    text = '\n'.join(m.get('content') or '' for m in rendered)
    assert prompts.load('checks_cleanup_unknown') not in text
    assert 'original workspace, not a copy' in text and 'aux/' in text


def test_cold_reconstruction_does_not_poison_a_later_trusted_reingestion(tmp_path, monkeypatch):
    plan, raw = run_gate(tmp_path, monkeypatch)
    probegate._transport_facts.pop(plan.transport_id)
    messages = history(plan, raw)
    cold = probegate.clean_gate_results(messages)
    assert prompts.load('checks_cleanup_unknown') in '\n'.join(m.get('content') or '' for m in cold)
    # The cold observer must not register its guessed empty workspace as origin.
    original = probegate.GatePlan(workspace=str(tmp_path), transport_id=plan.transport_id,
                                 transport_required=True, candidates=plan.candidates)
    assert probegate.ingest_transport(original, messages[-1]['content']) == 'complete'
    rendered = probegate.clean_gate_results(messages)
    text = '\n'.join(m.get('content') or '' for m in rendered)
    assert prompts.load('checks_cleanup_unknown') not in text and 'aux/compiled' in text


def test_retry_cannot_overwrite_the_original_scope_with_another_workspace(tmp_path, monkeypatch):
    plan, raw = run_gate(tmp_path, monkeypatch)
    messages = history(plan, raw)
    other = probegate.GatePlan(workspace='/foreign/workspace', transport_id=plan.transport_id,
                              transport_required=True, candidates=plan.candidates)
    probegate.ingest_transport(other, messages[-1]['content'])
    assert probegate.interpret_gate(other, messages[-1]['content']).scope_unknown
    text = '\n'.join(m.get('content') or '' for m in probegate.clean_gate_results(messages))
    assert prompts.load('checks_cleanup_unknown') not in text and 'aux/compiled' in text


def test_real_exact48_driver_final_post_keeps_historical_cleanup_facts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime = assistruntime.AssistRuntime.select(level=5, profile='rank4-ablation')
    with assistruntime.bound(runtime):
        plan, raw = run_gate(tmp_path, monkeypatch)
    driver, session, body = setup_driver()
    driver._ctx.pilot_runtime = runtime
    session.workspace_root = str(tmp_path)
    body['messages'] += history(plan, raw)
    posts = []
    def transport(request, **options):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1],"data":[]}')
        posts.append(json.loads(request.data))
        return io.BytesIO(json.dumps(loop._completion_toolcalls([{'id': 'next', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"source.txt"}'}}])).encode())
    monkeypatch.setattr(driver._ctx.coder_chat.__self__, '_receive_open', transport)
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        driver.drive(body, 'driver-fixture', None, _Rlog())
    finally:
        wsview.unbind(token)
    assert len(posts) == 1
    text = '\n'.join(m.get('content') or '' for m in posts[0]['messages'])
    assert prompts.load('checks_cleanup_unknown') not in text
    assert 'exclusively owned private' in text and 'aux/compiled' in text
    assert 'native build output for output/compiled' in text
    assert not session.plan.items[0].done
