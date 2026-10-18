"""Shared lowering may clean only resources it exclusively allocated."""
import os
import pathlib
import subprocess
import time

import pytest
from cria import probegate, writeproxy
from test_writeproxy import _call, _CMD_SHELL, _lowered_cmd


def instrument(command, source):
    marker = f"python3 - <<'{writeproxy._HD_PY}'\n"
    assert marker in command
    return command.replace(marker, marker + source + '\n', 1)


def execute(command, workspace, scratch):
    return subprocess.run(['sh', '-c', command], cwd=workspace, capture_output=True, text=True,
                          env={**os.environ, 'TMPDIR': str(scratch)}, timeout=15)


@pytest.mark.parametrize('kind', ['write', 'edit'])
@pytest.mark.parametrize('collision', ['file', 'symlink'])
@pytest.mark.parametrize('replace_fails', [False, True])
def test_whole_write_and_edit_preserve_preexisting_pid_siblings(tmp_path, kind, collision, replace_fails):
    target, victim = tmp_path / 'a.txt', tmp_path / 'unrelated.txt'
    target.write_text('old text')
    victim.write_text('unrelated user work')
    sibling = tmp_path / 'a.txt.4242.tmp-partial'
    if collision == 'file':
        sibling.write_text('unrelated sibling')
    else:
        sibling.symlink_to(victim)
    command = (writeproxy._write_command('a.txt', 'new text') if kind == 'write' else
               writeproxy._edit_command('a.txt', 'old text', 'new text'))
    fault = 'import os; os.getpid=lambda:4242\n'
    if replace_fails:
        fault += "def _broken_replace(*args, **kwargs): raise PermissionError(13,'injected replace failure')\nos.replace=_broken_replace\n"
    result = execute(instrument(command, fault), tmp_path, tmp_path)
    assert victim.read_text() == 'unrelated user work'
    assert sibling.is_symlink() if collision == 'symlink' else sibling.is_file()
    assert sibling.read_text() == ('unrelated user work' if collision == 'symlink' else 'unrelated sibling')
    assert not target.is_symlink()
    assert target.read_text() == ('old text' if replace_fails else 'new text')
    assert (result.returncode != 0) is replace_fails
    assert {p.name for p in tmp_path.iterdir()} == {'a.txt', 'unrelated.txt', sibling.name}


@pytest.mark.parametrize('collision', ['file', 'symlink'])
def test_helper_install_does_not_claim_a_preexisting_pid_sibling(tmp_path, collision):
    victim = tmp_path / 'notes.txt'
    victim.write_text('user notes')
    helper = tmp_path / probegate._helper_name()
    # The collision is created by the fixture, before production installation,
    # using this shell's actual PID. It is not an installer-owned resource.
    beside = '"' + str(helper) + '.$$"'
    setup = (f'printf %s unrelated > {beside}' if collision == 'file' else
             f'ln -s "{victim}" {beside}')
    script = setup + '\n' + probegate._helper_install_leg()
    proc = subprocess.Popen(['sh', '-c', script], env={**os.environ, 'TMPDIR': str(tmp_path)},
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    output, errors = proc.communicate(timeout=15)
    sibling = pathlib.Path(str(helper) + f'.{proc.pid}')
    assert proc.returncode == 0, errors
    assert victim.read_text() == 'user notes'
    assert sibling.is_symlink() if collision == 'symlink' else sibling.is_file()
    assert sibling.read_text() == ('user notes' if collision == 'symlink' else 'unrelated')
    assert helper.read_text() == probegate._helper_source()


def test_refused_batch_commands_cannot_truncate_foreign_completion_names(tmp_path, monkeypatch):
    workspace, scratch = tmp_path / 'workspace', tmp_path / 'scratch'
    workspace.mkdir(); scratch.mkdir()
    (workspace / 'a.txt').write_text('actual text')
    original = writeproxy._edit_sequence
    observed = {}
    def sequence(*args):
        result = original(*args)
        observed.update(result)
        return result
    monkeypatch.setattr(writeproxy, '_edit_sequence', sequence)
    completion = _call('edit_file', {'path': 'a.txt', 'old_string': 'missing', 'new_string': None})
    completion['choices'][0]['message']['tool_calls'] += _call('edit_file', {
        'path': 'a.txt', 'old_string': 'also missing', 'new_string': None}, cid='c2')['choices'][0]['message']['tool_calls']
    writeproxy.translate_outbound(completion, _CMD_SHELL, injected={'edit_file'})
    group = scratch / (writeproxy.EDIT_SEQ_DIR + observed[0][0])
    group.mkdir()
    (group / '0').write_text('unrelated numbered file')
    for call in completion['choices'][0]['message']['tool_calls']:
        one = {'choices': [{'message': {'tool_calls': [call]}}]}
        execute(_lowered_cmd(one), workspace, scratch)
    assert (group / '0').read_text() == 'unrelated numbered file'
    assert (workspace / 'a.txt').read_text() == 'actual text'


def batch_sequences():
    calls = []
    for index in range(2):
        calls += _call('edit_file', {'path': 'a.txt', 'old_string': 'missing', 'new_string': 'replacement'},
                       cid=str(index))['choices'][0]['message']['tool_calls']
    return writeproxy._edit_sequence(calls, {'edit_file'})


def test_two_nonmatching_edits_never_sweep_unrelated_old_directories(tmp_path):
    workspace, scratch = tmp_path / 'workspace', tmp_path / 'scratch'
    workspace.mkdir(); scratch.mkdir()
    (workspace / 'a.txt').write_text('actual text')
    notes = scratch / (writeproxy.EDIT_SEQ_DIR + 'notes')
    notes.mkdir()
    (notes / 'keep.txt').write_text('unrelated user notes')
    os.utime(notes, (time.time() - 7200,) * 2)
    sequences = batch_sequences()
    for index in range(2):
        command = writeproxy._edit_command('a.txt', 'missing text', 'replacement', seq=sequences[index])
        assert execute(command, workspace, scratch).returncode != 0
    assert (workspace / 'a.txt').read_text() == 'actual text'
    assert (notes / 'keep.txt').read_text() == 'unrelated user notes'


def test_batch_release_never_recursively_removes_unknown_group_contents(tmp_path):
    workspace, scratch = tmp_path / 'workspace', tmp_path / 'scratch'
    workspace.mkdir(); scratch.mkdir()
    (workspace / 'a.txt').write_text('actual text')
    sequences = batch_sequences()
    first = writeproxy._edit_command('a.txt', 'missing', 'replacement', seq=sequences[0])
    assert execute(first, workspace, scratch).returncode != 0
    group = scratch / (writeproxy.EDIT_SEQ_DIR + sequences[0][0])
    (group / 'notes.txt').write_text('not a completion marker')
    last = writeproxy._edit_command('a.txt', 'missing', 'replacement', seq=sequences[1])
    assert execute(last, workspace, scratch).returncode != 0
    assert (group / 'notes.txt').read_text() == 'not a completion marker'


def test_a_preexisting_batch_group_is_not_owned_by_its_name(tmp_path):
    workspace, scratch = tmp_path / 'workspace', tmp_path / 'scratch'
    workspace.mkdir(); scratch.mkdir()
    (workspace / 'a.txt').write_text('actual text')
    sequences = batch_sequences()
    group = scratch / (writeproxy.EDIT_SEQ_DIR + sequences[0][0])
    group.mkdir()
    (group / '0').write_text('unrelated numbered file')
    (group / 'notes.txt').write_text('unrelated notes')
    for index in range(2):
        command = writeproxy._edit_command('a.txt', 'missing', 'replacement', seq=sequences[index])
        assert execute(command, workspace, scratch).returncode != 0
    assert (group / '0').read_text() == 'unrelated numbered file'
    assert (group / 'notes.txt').read_text() == 'unrelated notes'
