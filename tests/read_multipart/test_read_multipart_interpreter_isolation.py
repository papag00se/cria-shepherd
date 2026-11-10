"""Harness-side producers must not import code from the repository or Python environment."""
import os
import shutil
import subprocess

import pytest

from cria import denial, editsequence, filecommands, initial_inventory, wsview, writeproxy


def test_persisted_unisolated_release_is_not_reissued():
    command = editsequence._seq_release(('a' * 16, 0, (), (0,)))
    assert editsequence.matches_release(command)
    assert not editsequence.matches_release(command.replace('python3 -I -', 'python3 -', 1))


@pytest.mark.parametrize('route', ['read', 'write', 'edit', 'survey', 'multipart', 'inventory'])
def test_workspace_modules_cannot_run_in_crias_producers(tmp_path, route):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    poison = "open('POISONED', 'a').write('executed\\n')\n"
    for name in ('base64', 'json', 'os', 'sitecustomize', 'usercustomize'):
        (workspace / (name + '.py')).write_text(poison)
    (workspace / 'input.txt').write_text('before\n')
    receipt = 'a' * 16
    with denial.receipt_scope(receipt):
        if route == 'read':
            command = filecommands._read_command({'path': 'input.txt'})
        elif route == 'write':
            command = writeproxy._write_command('output.txt', 'written\n')
        elif route == 'edit':
            command = writeproxy._edit_command('input.txt', 'before', 'after')
        elif route == 'survey':
            command = wsview.survey_command('isolation', cd=str(workspace))
        elif route == 'multipart':
            spec = filecommands.make_multipart_read_spec('c1', 'read_file', '{"path":"input.txt"}', 'a' * 32)
            command = filecommands.build_multipart_page(spec, 0)
        else:
            command = initial_inventory.command(str(workspace), _browse=True)
    env = {**os.environ, 'TMPDIR': str(scratch), 'PYTHONPATH': str(workspace), 'PYTHONUSERBASE': str(workspace)}
    result = subprocess.run(['bash', '-c', command], cwd=workspace, env=env, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert not (workspace / 'POISONED').exists()
    if route == 'write':
        assert (workspace / 'output.txt').read_text() == 'written\n'
    if route == 'edit':
        assert (workspace / 'input.txt').read_text() == 'after\n'


@pytest.mark.parametrize('binary,extension,variable', [('ruby', 'rb', 'RUBYOPT'), ('node', 'js', 'NODE_OPTIONS')])
def test_syntax_checker_does_not_load_environment_hooks(tmp_path, binary, extension, variable):
    if not shutil.which(binary):
        pytest.skip(binary + ' is unavailable')
    hook = tmp_path / ('hook.' + extension)
    if binary == 'ruby':
        hook.write_text("File.write('POISONED', 'executed')\n")
    else:
        hook.write_text("require('fs').writeFileSync('POISONED', 'executed')\n")
    command = writeproxy._write_command('file.' + extension, 'x = 1\n')
    env = {**os.environ, variable: '-r ' + str(hook)}
    result = subprocess.run(['bash', '-c', command], cwd=tmp_path, env=env, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert (tmp_path / ('file.' + extension)).read_text() == 'x = 1\n'
    assert not (tmp_path / 'POISONED').exists()
