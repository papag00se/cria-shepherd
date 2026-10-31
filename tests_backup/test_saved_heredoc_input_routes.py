"""P1: saved literal input must retain ownership when later routed to execution."""
import json
import subprocess

import pytest

from cria import dirguard
from cria.outboundpolicies import _external_refusal


ROUTES = ['sh < tmp/script', 'cat tmp/script | sh']
WS = '/home/jesse/src/project'


def outbound(command, level, workspace):
    fn = {'name': 'shell', 'arguments': json.dumps({'command': ['bash', '-lc', command]})}
    return _external_refusal('shell', {}, fn, set(), level, workspace)


def saved(body, consumer):
    return "cat > tmp/script <<'EOF'\n" + body + '\nEOF\n' + consumer


@pytest.mark.parametrize('consumer', ROUTES)
@pytest.mark.parametrize('level', ['none', 'read'])
@pytest.mark.parametrize('absolute', [False, True])
def test_actual_saved_input_routes_write_outside_and_are_refused(tmp_path, consumer, level, absolute):
    workspace = tmp_path / 'workspace'
    (workspace / 'tmp').mkdir(parents=True)
    target = str(tmp_path / 'outside') if absolute else '../outside'
    command = saved('printf proof > ' + target, consumer)
    # Controlled native proof, never the campaign/benchmark workspace.
    result = subprocess.run(['bash', '-c', command], cwd=workspace, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'outside').read_text() == 'proof'
    assert outbound(command, level, str(workspace)) is not None
    assert dirguard.command_refusal(command, level, str(workspace)) is not None


@pytest.mark.parametrize('consumer', ROUTES + ['cat < tmp/script | sh', 'cat tmp/script | cat | sh'])
@pytest.mark.parametrize('level', ['none', 'read'])
@pytest.mark.parametrize('body', ['printf proof > local', 'cat tmp/local'])
def test_local_or_read_only_saved_execution_remains_available(consumer, level, body):
    assert outbound(saved(body, consumer), level, WS) is None


@pytest.mark.parametrize('consumer', ROUTES + ['cat tmp/script | wc -c', 'wc -c < tmp/script'])
@pytest.mark.parametrize('level', ['none', 'read'])
def test_plain_inspection_is_not_execution(consumer, level):
    body = '/external/literal/example'
    command = saved(body, consumer)
    refusal = outbound(command, level, WS)
    if consumer in ROUTES:
        assert refusal is not None
    else:
        assert refusal is None


@pytest.mark.parametrize('consumer', ['sh < ../tmp/script', 'cat ../tmp/script | sh'])
@pytest.mark.parametrize('level', ['none', 'read'])
def test_saved_input_is_judged_at_the_consumer_cwd(consumer, level):
    prefix = 'mkdir -p sub\n'
    # Consumer runs inside sub: ../local stays in the workspace, ../../outside does not.
    assert outbound(prefix + saved('printf proof > ../local', 'cd sub; ' + consumer), level, WS) is None
    assert outbound(prefix + saved('printf proof > ../../outside', 'cd sub; ' + consumer), level, WS) is not None


@pytest.mark.parametrize('consumer', [
    "cat tmp/script | cut -c2- | sh",
    "cut -c2- < tmp/script | sh",
    "sh < tmp/script",
])
@pytest.mark.parametrize('level', ['none', 'read'])
def test_transformed_or_modified_saved_bytes_are_not_assumed_current(consumer, level):
    mutation = "sed -i 's/^#//' tmp/script; " if consumer.startswith('sh ') else ''
    assert outbound(saved('#printf proof > ../outside', mutation + consumer), level, WS) is not None


@pytest.mark.parametrize('consumer', ['sh < "$INPUT"', 'cat "$INPUT" | sh'])
def test_undecidable_executable_input_custody_is_held(consumer):
    assert outbound(saved('printf proof > ../outside', consumer), 'none', WS) is not None


@pytest.mark.parametrize('consumer', ROUTES)
def test_read_permission_still_allows_executed_external_reads(consumer):
    command = saved('cat /external/example', consumer)
    assert outbound(command, 'read', WS) is None
    assert outbound(command, 'none', WS) is not None


@pytest.mark.parametrize('consumer', ROUTES)
def test_nested_saved_input_keeps_cwd_and_changed_byte_custody(consumer):
    # Inner execution must return its cwd, not the outer shell invocation's cwd.
    nested = "sh -c 'cd sub; " + consumer.replace('tmp/script', '../tmp/script') + "'"
    assert outbound(saved('printf proof > ../local', nested), 'none', WS) is None
    assert outbound(saved('printf proof > ../../outside', nested), 'none', WS) is not None
    mutated = 'sh -c "sed -i \'s/^#//\' tmp/script; ' + consumer + '"'
    assert outbound(saved('#printf proof > ../outside', mutated), 'none', WS) is not None


@pytest.mark.parametrize('consumer', ROUTES)
def test_nested_consumer_can_return_to_the_project_cwd(consumer):
    nested = 'cd sub; sh -c "cd ..; ' + consumer + '"'
    assert outbound(saved('printf proof > local', nested), 'none', WS) is None
    assert outbound(saved('printf proof > ../outside', nested), 'none', WS) is not None


@pytest.mark.parametrize('consumer', ROUTES)
def test_local_execution_really_stays_inside_the_controlled_fixture(tmp_path, consumer):
    workspace = tmp_path / 'workspace'
    (workspace / 'tmp').mkdir(parents=True)
    command = saved('printf proof > inside', consumer)
    assert outbound(command, 'none', str(workspace)) is None
    result = subprocess.run(['bash', '-c', command], cwd=workspace, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (workspace / 'inside').read_text() == 'proof'
    assert not (tmp_path / 'inside').exists()


def test_unrelated_literal_stdin_and_unrelated_script_remain_unrelated():
    command = saved('/external/literal/example', 'sh < tmp/unrelated')
    assert outbound(command, 'none', WS) is None
    assert outbound(saved('/external/literal/example', 'cat tmp/script | wc -c; sh tmp/unrelated'), 'none', WS) is None
