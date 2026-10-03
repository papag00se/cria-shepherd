from pathlib import Path
import os
import shutil
import subprocess
import sys
import pytest
from suite import run


def test_only_explicit_machine_policy_changes_suite_launch(tmp_path, monkeypatch):
    policy = tmp_path / 'suite-codex-policy.toml'
    monkeypatch.setattr(run, 'SUITE_CODEX_POLICY', policy)
    assert run._codex_argv('task') == ['codex', 'exec', '--yolo', 'task']
    policy.write_text('workspace_sandbox = true\n')
    argv = run._codex_argv('task')
    assert '--yolo' not in argv
    assert 'default_permissions="cria_suite"' in argv
    assert 'approval_policy="never"' in argv
    import tomllib
    permissions = tomllib.loads(next(arg for arg in argv if arg.startswith('permissions=')))
    fs = permissions['permissions']['cria_suite']['filesystem']
    assert fs == {'/': 'read', ':workspace_roots': 'write'}
    assert argv[-1] == 'task'


@pytest.mark.skipif(not shutil.which('codex'), reason='local Codex sandbox integration')
def test_local_codex_policy_denies_outside_unlink_but_allows_cell_writes(tmp_path, monkeypatch):
    policy = tmp_path / 'policy.toml'
    policy.write_text('workspace_sandbox=true\n')
    monkeypatch.setattr(run, 'SUITE_CODEX_POLICY', policy)
    workspace, state, home = (tmp_path / n for n in ('workspace', 'state', 'codex'))
    for directory in (workspace, state, home):
        directory.mkdir()
    monkeypatch.setattr(run, '_cell_install_root', lambda ws: state)
    outside = tmp_path / 'disposable-sentinel'
    outside.write_text('preserve')
    settings = run._codex_argv('unused', workspace)[2:-1]
    code = '''import pathlib,sys,tempfile
p=pathlib.Path(sys.argv[1])
try: p.unlink()
except PermissionError: pass
except OSError as exc:
    import errno
    assert exc.errno == errno.EROFS, exc
else: raise AssertionError('outside deletion allowed')
pathlib.Path('inside').write_text('ok')
with tempfile.TemporaryFile() as f: f.write(b'ok')
'''
    result = subprocess.run(['codex', 'sandbox', '-P', 'cria_suite', *settings, '-C', str(workspace),
                             '--', sys.executable, '-c', code, str(outside)],
                            env={**os.environ, 'CODEX_HOME': str(home), 'TMPDIR': str(state)},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert outside.read_text() == 'preserve'
    assert (workspace / 'inside').read_text() == 'ok'


def test_broken_local_policy_cannot_revert_to_yolo(tmp_path, monkeypatch):
    policy = tmp_path / 'suite-codex-policy.toml'
    monkeypatch.setattr(run, 'SUITE_CODEX_POLICY', policy)
    policy.write_text('workspace_sandbox = false\n')
    with pytest.raises(ValueError):
        run._codex_argv('task')
