"""Compare ANSI-C operands with bash without ever running a destructive command."""
import subprocess

import pytest

from cria import dirguard

WS = '/w/ws'


def bash_arg(word):
    result = subprocess.run(['bash', '-c', "printf '%s' " + word], capture_output=True, check=True)
    return result.stdout


@pytest.mark.parametrize('operand', ["$'/'", r"$'\x2f'", r"$'\057'", r"$'\u002f'", r"$'\x2f\0ignored'"])
def test_root_operand(operand):
    assert bash_arg(operand) == b'/'
    for level in ('none', 'read', 'write'):
        assert dirguard.command_refusal('rm -rf ' + operand, level, WS)


@pytest.mark.parametrize('operand', [r"$'\x2fetc\x2fpasswd'", r"$'\057etc'/$'passwd'", r"$'\u002fetc'/passwd"])
def test_external_read(operand):
    assert bash_arg(operand).startswith(b'/etc')
    assert dirguard.command_refusal('cat ' + operand, 'none', WS)
    assert dirguard.command_refusal('cat ' + operand, 'read', WS) is None


def test_external_write_and_local_controls():
    assert dirguard.command_refusal(r"touch $'\x2ftmp'/outside", 'read', WS)
    for command in [r"cat $'local\x2fname'", r"echo $'\x2f'", r"grep $'\x2fpattern' local", r"echo \$'\x2f'", 'echo "$\'\\x2f\'"', r"echo '$\x2f'", r"rm -rf $'\x2f'tmp", r"rm -rf ${target}$'\x2f'"]:
        assert dirguard.command_refusal(command, 'write', WS) is None, command
    assert dirguard.command_refusal(r"cat $'local\x2fname'", 'none', WS) is None


def test_quotes_and_escapes_are_data_not_syntax():
    for operand in [r"$'a\'b'", r"$'a\\b'", r"$'a\n;rm -rf /'", r"$'\x2fetc\x2fpasswd'local"]:
        assert bash_arg(operand)
        assert dirguard.command_refusal('echo ' + operand, 'write', WS) is None


def test_substitutions_keep_their_own_context():
    assert dirguard.command_refusal(r"echo $(printf ok); rm -rf $'\x2f'", 'write', WS)
    assert dirguard.command_refusal(r"echo $(printf ok); cat $'\x2fetc\x2fpasswd'", 'none', WS)
    assert dirguard.command_refusal(r"rm -rf $(printf tmp)$'\x2f'", 'write', WS)
    assert dirguard.command_refusal(r"echo $(printf ok); echo $'\x2f'", 'write', WS) is None


@pytest.mark.parametrize('operand', [r"$'\c?'", r"$'\cß'", r"$'\c\\'", r"$'\777'", r"$'\u263a'", r"$'a\'b'", r"$'\x24HOME'", r"$'a\n;b'", r"$'\q'", r"$'\x'", r"$'\x2f\0tail'"])
def test_decoded_view_matches_bash_bytes(operand):
    from cria import shellinput
    assert bash_arg(shellinput.decode_ansi_c(operand)) == bash_arg(operand)
