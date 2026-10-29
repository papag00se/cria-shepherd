"""Bash runs printf only; deletion commands are inert policy inputs."""
import json
import subprocess
import pytest
from cria import cleanupsafety, dirguard, outboundpolicies


def decisions(command, root):
    return (bool(dirguard.root_recursive_delete_refusal(command)),
            bool(outboundpolicies._external_refusal('shell', {},
                {'arguments': json.dumps({'command': command})}, set(), 'write', str(root))),
            cleanupsafety.analyze('example.sh', command, str(root), 'write').blocked)


@pytest.mark.parametrize(('pattern', 'name'), [('-?f', '-rf'), ('--recursiv[e]', '--recursive'),
    ('-[r]f', '-rf'), ('-f?', '-fr'), ('-f[R]', '-fR'), ('--recurs*', '--recursive'),
    ('-"f"?', '-fr')])
def test_glob_option_is_possible_at_all_consumers(tmp_path, pattern, name):
    (tmp_path / name).touch()
    result = subprocess.run(['bash', '--norc', '--noprofile', '-c',
        "printf '<%s>' " + pattern + ' --no-preserve-root /'], cwd=tmp_path,
        capture_output=True, check=True)
    assert result.stdout == ('<' + name + '><--no-preserve-root></>').encode()
    assert decisions('rm ' + pattern + ' --no-preserve-root /', tmp_path) == (True, True, True)


@pytest.mark.parametrize('pattern', ["'-?f'", r'-\?f', "'--recursiv[e]'", r'--recursiv\[e\]',
    '--force*', '--recursiv[x]', '-f[ab]', 'file*', 'literal?'])
def test_quoted_and_nonmatching_options_do_not_invent_recursion(tmp_path, pattern):
    for name in ('-rf', '--recursive', '-fa', '-fx'):
        (tmp_path / name).touch()
    assert decisions('rm ' + pattern + ' /', tmp_path) == (False, False, False)


@pytest.mark.parametrize('pattern', ['-?f', '--recursiv[e]', '-f?', '*'])
def test_option_terminator_prevents_recursion(tmp_path, pattern):
    (tmp_path / '-rf').touch()
    (tmp_path / '--recursive').touch()
    assert decisions('rm -- ' + pattern + ' /', tmp_path) == (False, False, False)


def test_independent_root_and_find_controls(tmp_path):
    assert decisions('rm -- -?f /; rm -rf /', tmp_path) == (True, True, True)
    assert decisions('find / "-del*"', tmp_path) == (False, False, False)


@pytest.mark.parametrize('pattern', ['-?f', '--recursiv[e]'])
def test_possibility_is_truthful_at_cleanup_and_prompt(tmp_path, pattern):
    command='rm '+pattern+' --no-preserve-root /'
    result=cleanupsafety.analyze('example.sh',command,str(tmp_path),'write')
    assert result.blocked
    assert any(f.confidence=='POSSIBLE' and f.rule=='root_uncertain' and not f.targets for f in result.findings)
    assert not any(f.confidence=='PROVEN' and f.rule=='root' for f in result.findings)
    assert cleanupsafety.review('example.sh',command,None,str(tmp_path),permission='write')
    assert 'would recursively delete' not in dirguard.root_recursive_delete_refusal(command)


@pytest.mark.parametrize('command', ['rm < -?f /', 'rm > --recursiv[e] /',
    "rm '--recursiv[e]'* /", 'rm file[[:alpha:]] /', 'rm local[ /'])
def test_operand_roles_and_nonoption_prefixes(tmp_path,command):
    assert decisions(command,tmp_path)==(False,False,False)


@pytest.mark.parametrize('command', ['echo $(rm -?f /)', 'echo `rm --recursiv[e] /`',
    'sudo -n rm -?f /', 'rm -?f /; echo ok', 'echo ok; rm --recursiv[e] /'])
def test_existing_command_scopes_reach_the_matcher(tmp_path,command):
    assert decisions(command,tmp_path)==(True,True,True)
