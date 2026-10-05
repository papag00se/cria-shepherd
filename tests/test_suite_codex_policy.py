from pathlib import Path
import os
import shutil
import subprocess
import sys
import tomllib
import pytest
from suite import run


def test_missing_policy_refuses_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(run, 'SUITE_CODEX_POLICY', tmp_path / 'missing.toml')
    with pytest.raises(ValueError, match='sandbox policy'):
        run._codex_argv('task', tmp_path)


def test_explicit_machine_policy_grants_only_exact_cell_paths(tmp_path, monkeypatch):
    policy = tmp_path / 'suite-codex-policy.toml'
    monkeypatch.setattr(run, 'SUITE_CODEX_POLICY', policy)
    policy.write_text('workspace_sandbox = true\n')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    state = tmp_path / 'state'
    monkeypatch.setattr(run, '_cell_install_root', lambda ws: state)
    argv = run._codex_argv('task', workspace)
    assert '--yolo' not in argv
    assert 'approval_policy="never"' in argv
    profile = tomllib.loads(next(arg for arg in argv if arg.startswith('default_permissions=')))['default_permissions']
    permissions = tomllib.loads(next(arg for arg in argv if arg.startswith('permissions=')))
    fs = permissions['permissions'][profile]['filesystem']
    assert fs == {'/': 'read', str(workspace): 'write', str(state): 'write'}
    assert argv[-1] == 'task'


@pytest.mark.skipif(not shutil.which('codex'), reason='local Codex sandbox integration')
@pytest.mark.parametrize('inherited_write_grant', [False, True, 'legacy'])
def test_local_codex_policy_denies_outside_unlink_but_allows_cell_writes(tmp_path, monkeypatch, inherited_write_grant):
    policy = tmp_path / 'policy.toml'
    policy.write_text('workspace_sandbox=true\n')
    monkeypatch.setattr(run, 'SUITE_CODEX_POLICY', policy)
    workspace, state, home = (tmp_path / n for n in ('workspace', 'state', 'codex'))
    for directory in (workspace, state, home):
        directory.mkdir()
    monkeypatch.setattr(run, '_cell_install_root', lambda ws: state)
    outside = tmp_path / 'disposable-sentinel'
    outside.write_text('preserve')
    (workspace / 'outside-link').symlink_to(outside)
    if inherited_write_grant == 'legacy':
        (home / 'config.toml').write_text('sandbox_mode="danger-full-access"\napproval_policy="never"\n')
    elif inherited_write_grant:
        import json
        (home / 'config.toml').write_text(
            '[permissions.cria_suite.filesystem]\n' + json.dumps(str(tmp_path)) + '="write"\n')
    settings = run._codex_argv('unused', workspace)[2:-1]
    code = '''import pathlib,sys,tempfile
p=pathlib.Path(sys.argv[1])
for operation in (lambda: p.unlink(), lambda: p.write_text('clobber'),
                  lambda: p.with_name('outside-new').write_text('escape'),
                  lambda: pathlib.Path('outside-link').write_text('escape'),
                  lambda: p.rename(pathlib.Path.cwd() / 'stolen')):
    try: operation()
    except PermissionError: pass
    except OSError as exc:
        import errno
        assert exc.errno in (errno.EROFS, errno.EXDEV), exc
    else: raise AssertionError('outside mutation allowed')
pathlib.Path('inside').write_text('ok')
with tempfile.TemporaryFile() as f: f.write(b'ok')
'''
    profile = tomllib.loads(next(arg for arg in settings if arg.startswith('default_permissions=')))['default_permissions']
    result = subprocess.run(['codex', 'sandbox', '-P', profile, *settings, '-C', str(workspace),
                             '--', sys.executable, '-c', code, str(outside)],
                            env={**os.environ, 'CODEX_HOME': str(home), 'TMPDIR': str(state)},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert outside.read_text() == 'preserve'
    assert (workspace / 'inside').read_text() == 'ok'


@pytest.mark.parametrize('contents', [
    'workspace_sandbox = false\n', 'workspace_sandbox = 1\n',
    'workspace_sandbox = "true"\n', '', '[broken',
    'workspace_sandbox = true\nextra = true\n',
])
def test_broken_local_policy_cannot_revert_to_yolo(tmp_path, monkeypatch, contents):
    policy = tmp_path / 'suite-codex-policy.toml'
    monkeypatch.setattr(run, 'SUITE_CODEX_POLICY', policy)
    policy.write_text(contents)
    with pytest.raises(ValueError):
        run._codex_argv('task', tmp_path)


@pytest.mark.parametrize('workspace', [None, '/', 'relative-cell'])
def test_no_implicit_or_root_workspace_grant(tmp_path, monkeypatch, workspace):
    policy = tmp_path / 'policy.toml'
    policy.write_text('workspace_sandbox=true\n')
    monkeypatch.setattr(run, 'SUITE_CODEX_POLICY', policy)
    with pytest.raises(ValueError, match='workspace'):
        run._codex_argv('task', workspace)
