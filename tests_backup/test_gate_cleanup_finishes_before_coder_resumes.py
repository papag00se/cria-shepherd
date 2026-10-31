"""Only positively allocated private scratch can be reclaimed by a gate.

Keep the original concurrent-writer, late-content and root/ancestor replacement
oracles. Project build output is NOT owned merely because a check created it.
"""
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import uuid

import pytest
from cria import denial, assistruntime, gatecleanup, loop, probediscovery, probegate, proberun, writeproxy, wsview
from tests.gatefixture import gate_page, completed
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog


@pytest.fixture(autouse=True)
def exact_profile():
    runtime = assistruntime.AssistRuntime.select(level=5, profile='rank4-ablation')
    with assistruntime.bound(runtime):
        yield runtime


def harness_env(workspace):
    parent = workspace.parent / (workspace.name + '-harness')
    parent.mkdir(exist_ok=True)
    return {**os.environ, 'TMPDIR': str(parent)}


BUILD = ("import os; from pathlib import Path; p=Path('output'); p.mkdir(exist_ok=True); "
         "(p/'compiled').write_text('project build artifact'); "
         "(Path(os.environ['CTX_PROBE_AUX'])/'compiled').write_text('private compiler scratch'); "
         "print('native build output for output/compiled')")


def run_gate(tmp_path, monkeypatch, *, working_dir=None, program=None):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / 'source.txt').write_text('source\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'source.txt'], check=True)
    build = probediscovery.ProbeCandidate(probediscovery.ProbeKind.BuildCheck,
        [sys.executable, '-c', program or BUILD], working_dir or tmp_path, 100, 100,
        probediscovery.ProbeCost.Moderate, False, False, False, 'fixture native build')
    monkeypatch.setattr(proberun, 'select_completion_probes', lambda root: [build])
    plan = probegate.plan_gate(str(tmp_path))
    result = subprocess.run(['sh', '-c', plan.script], cwd=tmp_path, env=harness_env(tmp_path),
                            capture_output=True, text=True, check=True)
    probegate.interpret_gate(plan, gate_page(plan, result.stdout))
    assert plan.transport_complete, result.stdout + result.stderr
    return plan, plan.transport_data.decode('utf-8')


def auxiliary(plan):
    return Path(plan.transport_path).parent / 'aux'


def removal_record(raw):
    record = gatecleanup.report(probegate.split_sections(wsview.strip_survey(raw)[0])[probegate.LITTER_REMOVED_SECTION])
    assert record is not None
    return record


def test_gate_reclaims_its_artifact_before_returning(tmp_path, monkeypatch):
    plan, raw = run_gate(tmp_path, monkeypatch)
    assert 'native build output' in raw
    assert (tmp_path / 'source.txt').read_text() == 'source\n'
    assert not auxiliary(plan).exists(), 'actual private cleanup must finish before return'
    assert (tmp_path / 'output/compiled').read_text() == 'project build artifact'
    removed, failed = removal_record(raw)
    assert 'aux/compiled' in removed and 'aux/' in removed and not failed
    assert not any(path.startswith('output') for path in removed)


@pytest.mark.parametrize('refused', [False, True])
def test_later_read_or_refusal_cannot_delete_new_coder_content(tmp_path, monkeypatch, refused):
    run_gate(tmp_path, monkeypatch)
    output = tmp_path / 'output'
    (output / 'coder.txt').write_text('new coder work\n')
    response = {'choices': [{'message': {'tool_calls': [{'id': 'read', 'type': 'function',
        'function': {'name': 'list_dir', 'arguments': '{"path":"."}'}}]}}]}
    if refused:
        response['choices'][0]['message']['tool_calls'][0]['function'] = {
            'name': 'edit_file', 'arguments': '{"path":"source.txt","old_string":"","new_string":"replacement"}'}
    token = wsview.bind(wsview.View(str(tmp_path), 'cleanup-lifecycle'))
    try:
        writeproxy.translate_outbound(response, {'name': 'shell', 'parameters': {}},
            injected={'list_dir', 'edit_file'}, session='cleanup-lifecycle', workspace_root=str(tmp_path))
    finally:
        wsview.unbind(token)
    call = response['choices'][0]['message']['tool_calls'][0]
    command = json.loads(call['function']['arguments'])['command']
    result = subprocess.run(['sh', '-c', command], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == (1 if refused else 0)
    if refused:
        assert 'Nothing was changed' in result.stdout
    assert (output / 'coder.txt').read_text() == 'new coder work\n'
    assert (output / 'compiled').read_text() == 'project build artifact'


def test_nested_probe_does_not_rebase_cleanup_ownership(tmp_path, monkeypatch):
    nested = tmp_path / 'sub'
    nested.mkdir()
    (nested / 'kept.txt').write_text('preexisting untracked work\n')
    plan, _ = run_gate(tmp_path, monkeypatch, working_dir=nested)
    assert (nested / 'kept.txt').read_text() == 'preexisting untracked work\n'
    assert (nested / 'output/compiled').read_text() == 'project build artifact'
    assert not auxiliary(plan).exists()


def test_preexisting_empty_directory_and_untracked_content_survive(tmp_path, monkeypatch):
    output = tmp_path / 'output'
    output.mkdir()
    (tmp_path / 'draft.txt').write_text('keep exact content\n')
    plan, _ = run_gate(tmp_path, monkeypatch)
    assert output.is_dir() and (output / 'compiled').is_file()
    assert (tmp_path / 'draft.txt').read_text() == 'keep exact content\n'
    assert not auxiliary(plan).exists()


def test_coder_created_artifact_before_gate_is_not_probe_litter(tmp_path, monkeypatch):
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'compiled').write_text('coder compiled this first\n')
    plan, raw = run_gate(tmp_path, monkeypatch, program="print('native build output: already up to date')")
    assert (output / 'compiled').read_text() == 'coder compiled this first\n'
    assert 'output/compiled' not in removal_record(raw)[0]
    assert 'not project build outputs' in probegate.clean_gate_output(raw, completed(plan, raw))


def test_final_survey_observes_post_cleanup_state(tmp_path, monkeypatch):
    view = wsview.View(str(tmp_path), 'cleanup-survey')
    token = wsview.bind(view)
    try:
        plan, raw = run_gate(tmp_path, monkeypatch)
        assert view.isfile('output/compiled') is True
        assert view.isfile('source.txt') is True
        assert not auxiliary(plan).exists()
    finally:
        wsview.unbind(token)
    cleaned = probegate.clean_gate_output(raw, completed(plan, raw))
    assert 'native build output for output/compiled' in cleaned
    assert 'checks-cleanup' in cleaned
    assert 'exclusively owned private' in cleaned
    assert 'original workspace, not a copy' in cleaned


def allocated_resource(tmp_path):
    """Use the ACTUAL shared allocation program, never forge an ownership hint."""
    parent = Path(harness_env(tmp_path)['TMPDIR'])
    token = uuid.uuid4().hex
    program = gatecleanup.OPERATIONS_PROGRAM + '''
parent,token=sys.argv[1:3]
context=_gate_namespace(token,parent,create=True)
os.mkdir('aux',0o700,dir_fd=context['fd'])
identity=_owned_id(os.stat('aux',dir_fd=context['fd'],follow_symlinks=False))
print(json.dumps(dict(parent=parent,token=token,root=context['root'],aux_identity=identity)))
_owned_close(context)
'''
    result = subprocess.run([sys.executable, '-c', program, str(parent), token], capture_output=True, text=True)
    if result.returncode:
        pytest.fail(result.stderr)
    return json.loads(result.stdout)


def private_aux(resource):
    return Path(resource['parent']) / (gatecleanup.PRIVATE_PREFIX + resource['token']) / 'aux'


def finish_cleanup(resource, prefix=''):
    program = prefix + gatecleanup.OPERATIONS_PROGRAM + '''
resource=json.load(sys.stdin)
try:
    context=_gate_namespace(resource['token'],resource['parent'])
    try:
        if context['root']!=resource['root']: raise ValueError('namespace_identity_changed')
        context['aux_identity']=resource['aux_identity']
        print(json.dumps(_gate_aux_cleanup(context)))
    finally: _owned_close(context)
except (OSError,ValueError) as error:
    print(json.dumps(dict(removed=[],failed=[dict(path='',error=str(error))])))
'''
    result = subprocess.run([sys.executable, '-c', program], input=json.dumps(resource), capture_output=True, text=True)
    if result.returncode:
        pytest.fail(result.stderr)
    record = gatecleanup.report(result.stdout)
    assert record is not None
    return record, result.stdout


def test_failed_removal_is_reported_as_failure_not_completed_work(tmp_path):
    resource = allocated_resource(tmp_path)
    artifact = private_aux(resource) / 'artifact'
    artifact.write_text('generated')
    prefix = "import os\ndef denied(*a,**k): raise PermissionError('injected filesystem denial')\nos.unlink=denied\n"
    (removed, failed), report = finish_cleanup(resource, prefix)
    assert removed == []
    assert any(item['error'] == 'injected filesystem denial' for item in failed)
    assert artifact.read_text() == 'generated'
    # the worker's record names the workspace it was requested for (the unit program above prints only the cleanup half)
    report = json.dumps({**json.loads(report), 'requested_workspace': str(tmp_path)}) + '\n'
    raw = (f'{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\nNATIVE RESULT\nEXIT:0\n'
           f'{probegate.SECTION_PREFIX}{probegate.LITTER_REMOVED_SECTION}{probegate.SECTION_SUFFIX}\n{report}')
    cleaned = probegate.clean_gate_output(raw, completed(probegate.GatePlan(str(tmp_path)), raw))
    assert 'NATIVE RESULT' in cleaned and 'injected filesystem denial' in cleaned
    assert 'reclaimed these' not in cleaned


def test_cleanup_never_recursively_removes_late_directory_content(tmp_path):
    resource = allocated_resource(tmp_path)
    project = tmp_path / 'output'
    project.mkdir()
    (project / 'compiled').write_text('native project artifact')
    (private_aux(resource) / 'private-temp').write_text('owned')
    # Arrives at the cleanup boundary, not in a protected pre-check snapshot.
    prefix = f"from pathlib import Path\nPath({str(project / 'coder.txt')!r}).write_text('keep me')\n"
    (removed, failed), _ = finish_cleanup(resource, prefix)
    assert 'aux/private-temp' in removed and not failed
    assert (project / 'compiled').read_text() == 'native project artifact'
    assert (project / 'coder.txt').read_text() == 'keep me'


def test_filenames_and_empty_directories_are_measured_without_line_splitting(tmp_path):
    resource = allocated_resource(tmp_path)
    aux = private_aux(resource)
    name = 'sp ace\nquoted-"-雪.txt'
    (aux / name).write_text('artifact')
    (aux / 'empty/nested').mkdir(parents=True)
    (removed, failed), _ = finish_cleanup(resource)
    assert set(removed) == {'aux/' + name, 'aux/empty/nested/', 'aux/empty/', 'aux/'}
    assert not failed and not aux.exists()


def test_ownership_snapshot_cannot_be_reused_in_another_workspace(tmp_path, monkeypatch):
    left, right = tmp_path / 'left', tmp_path / 'right'
    left.mkdir(); right.mkdir()
    plan, _ = run_gate(left, monkeypatch)
    precious = right / 'keep.txt'
    precious.write_text('unrelated workspace')
    # Reusing a token does not authorize a different command/workspace request.
    guard = probegate._gate_launch_guard(plan.transport_id, str(right), ['printf UNAUTHORIZED'], ':', 0)
    script = '__cria_gate_file=' + shlex.quote(plan.transport_path) + '\n' + '\n'.join(guard)
    result = subprocess.run(['sh', '-c', script], env=harness_env(left), capture_output=True, text=True, check=True)
    other = probegate.GatePlan(workspace=str(right), transport_id=plan.transport_id, transport_required=True)
    outcome = probegate.interpret_gate(other, gate_page(other, result.stdout))
    assert outcome.transport_unknown and 'transport_request_changed' in other.transport_error
    assert precious.read_text() == 'unrelated workspace'


def test_names_only_snapshot_cannot_authorize_cleanup(tmp_path):
    resource = allocated_resource(tmp_path)
    aux = private_aux(resource)
    precious = aux / 'keep.txt'
    precious.write_text('ownership has not been established')
    (aux.parent / '.owner').unlink()  # Names and a token alone are not a capability.
    (removed, failed), _ = finish_cleanup(resource)
    assert not removed and failed
    assert precious.read_text() == 'ownership has not been established'


@pytest.mark.parametrize('replacement', ['root', 'ancestor'])
def test_private_directory_replacement_cannot_inherit_cleanup_ownership(tmp_path, replacement):
    resource = allocated_resource(tmp_path)
    aux = private_aux(resource)
    replaced = aux.parent if replacement == 'root' else aux
    moved = replaced.with_name(replaced.name + '-original')
    replaced.rename(moved)
    replaced.mkdir(mode=0o700)
    precious = replaced / 'preexisting-user-work'
    precious.write_text('unrelated replacement content')
    (removed, failed), _ = finish_cleanup(resource)
    assert precious.read_text() == 'unrelated replacement content'
    assert removed == [] and failed
    assert moved.exists()


def paused_gate(tmp_path, monkeypatch, actor, *, nested=False):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    cwd = workspace / 'sub' if nested else workspace
    cwd.mkdir(exist_ok=True)
    (cwd / 'old').write_text('original user content')
    state = tmp_path / 'state'
    state.mkdir()
    ready, release = state / 'ready', state / 'release'
    program = ("from pathlib import Path; import time; "
               f"ready=Path({str(ready)!r}); release=Path({str(release)!r}); "
               "ready.write_text('probe running'); start=time.monotonic()\n"
               "while not release.exists() and time.monotonic()-start<10: time.sleep(.01)\n"
               "print('native probe completed')")
    subprocess.run(['git', 'init', '-q', str(workspace)], check=True)
    candidate = probediscovery.ProbeCandidate(probediscovery.ProbeKind.BuildCheck,
        [sys.executable, '-c', program], cwd, 100, 100,
        probediscovery.ProbeCost.Moderate, False, False, False, 'concurrent probe')
    monkeypatch.setattr(proberun, 'select_completion_probes', lambda root: [candidate])
    plan = probegate.plan_gate(str(workspace))
    gate = subprocess.Popen(['sh', '-c', plan.script], cwd=workspace, env=harness_env(workspace),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.exists()
        created = actor(workspace)
    finally:
        release.write_text('done')
        output, errors = gate.communicate(timeout=15)
    assert gate.returncode == 0, errors
    outcome = probegate.interpret_gate(plan, gate_page(plan, output))
    assert plan.transport_complete
    return workspace, created, plan, outcome


def test_another_supported_writer_during_a_gate_keeps_its_work(tmp_path, monkeypatch):
    def actor(workspace):
        with denial.receipt_scope('0123456789abcdef'):
            command = writeproxy._write_command('report.txt', 'other session work')
        writer = subprocess.run(['sh', '-c', command],
                                cwd=workspace, capture_output=True, text=True, check=True)
        assert writer.stdout
        path = workspace / 'report.txt'
        assert path.read_text() == 'other session work'
        return path
    _, report, _, outcome = paused_gate(tmp_path, monkeypatch, actor)
    assert report.read_text() == 'other session work'
    assert not probegate.gate_is_partial(outcome)


@pytest.mark.parametrize('replacement', ['root', 'ancestor'])
def test_directory_replacement_cannot_inherit_cleanup_ownership(tmp_path, monkeypatch, replacement):
    def actor(workspace):
        replaced = workspace if replacement == 'root' else workspace / 'sub'
        moved = tmp_path / 'original'
        replaced.rename(moved)
        replaced.mkdir()
        precious = replaced / 'preexisting-user-work'
        precious.write_text('unrelated replacement content')
        return precious, moved
    _, (precious, moved), plan, outcome = paused_gate(tmp_path, monkeypatch, actor, nested=True)
    assert precious.read_text() == 'unrelated replacement content'
    assert (moved / ('sub/old' if replacement == 'root' else 'old')).read_text() == 'original user content'
    assert not auxiliary(plan).exists()
    assert outcome.scope_unknown and probegate.gate_is_partial(outcome)
    assert outcome.report.results[0].exit_code == 0  # Preserve the actual checker result, qualify its scope.


def test_actual_python_floor_keeps_original_source_and_private_bytecode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'source.py'
    source.write_text('value = 1\n')
    inode = source.stat().st_ino
    token = wsview.bind(wsview.DirectView(str(tmp_path)))
    try:
        floor = next(c for c in probediscovery.syntax_floor_candidates(tmp_path) if c.private_python_cache)
    finally:
        wsview.unbind(token)
    inspect = ("import os; from pathlib import Path; "
               "print('privatecache=%s sourcecache=%s' % "
               "(any(Path(os.environ['CTX_PROBE_AUX']).rglob('*.pyc')),Path('__pycache__').exists()))")
    observer = probediscovery.ProbeCandidate(probediscovery.ProbeKind.BuildCheck,
        [sys.executable, '-c', inspect], tmp_path, 100, 100, probediscovery.ProbeCost.Cheap,
        False, False, False, 'observe actual compiler scratch')
    monkeypatch.setattr(proberun, 'select_completion_probes', lambda root: [floor, observer])
    plan = probegate.plan_gate(str(tmp_path))
    result = subprocess.run(['sh', '-c', plan.script], cwd=tmp_path, env=harness_env(tmp_path),
                            capture_output=True, text=True, check=True)
    outcome = probegate.interpret_gate(plan, gate_page(plan, result.stdout))
    assert plan.transport_complete and not probegate.gate_is_partial(outcome)
    assert 'privatecache=True sourcecache=False' in plan.transport_data.decode()
    assert source.read_text() == 'value = 1\n' and source.stat().st_ino == inode
    assert not (tmp_path / '__pycache__').exists()
    assert not auxiliary(plan).exists()
    assert all(r.exit_code == 0 for r in outcome.report.results)


@pytest.mark.parametrize('synthetic', [False, True])
def test_real_driver_serializes_native_evidence_and_settled_cleanup(tmp_path, monkeypatch, exact_profile, synthetic):
    plan, raw = run_gate(tmp_path, monkeypatch)
    driver, session, body = setup_driver()
    session.synthetic = session.plan_off = synthetic
    session.workspace_root = str(tmp_path)
    session.gate_plan = plan
    driver._ctx.pilot_runtime = exact_profile
    body['messages'] += [
        {'role': 'assistant', 'tool_calls': [{'id': 'gate', 'type': 'function',
         'function': {'name': 'shell', 'arguments': json.dumps({'command': plan.script})}}]},
        {'role': 'tool', 'tool_call_id': 'gate', 'content': raw},
        {'role': 'user', 'content': 'Continue the original task.'}]
    posts = []
    def transport(request, **options):
        if not request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(b'{"tokens":[1]}')
        assert assistruntime.current() == exact_profile
        posts.append(json.loads(request.data))
        return io.BytesIO(json.dumps(loop._completion_toolcalls([{'id': 'next', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"source.txt"}'}}])).encode())
    monkeypatch.setattr(driver._ctx.coder_chat.__self__, '_receive_open', transport)
    driver.drive(body, 'driver-fixture', None, _Rlog())
    assert len(posts) == 1
    text = json.dumps(posts[0], ensure_ascii=False)
    assert 'native build output for output/compiled' in text
    assert 'checks-cleanup' in text and 'not project build outputs' in text
    assert 'os.unlink' not in text
    assert not auxiliary(plan).exists()
    assert (tmp_path / 'output/compiled').read_text() == 'project build artifact'
