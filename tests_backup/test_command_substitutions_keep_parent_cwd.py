"""A command substitution's cwd cannot leak into its parent's write ownership."""
import subprocess

import pytest

from test_saved_heredoc_input_routes import outbound

COPY_SCOPES = [
    'value=$(cat tmp/script > tmp/other); sh tmp/other',
    'value="$(cat tmp/script > tmp/other)"; sh tmp/other',
    'value=$(cd sub; cat ../tmp/script > ../tmp/other); sh tmp/other',
    'value=$(cat tmp/script > tmp/copy)$(cat tmp/copy > tmp/other); sh tmp/other',
    'value=$(inner=$(cat tmp/script > tmp/other)); sh tmp/other',
    'sh tmp/other "$(cat tmp/script > tmp/other)"',
    "value=$(sh -c 'cat tmp/script > tmp/other'); sh tmp/other",
]


def saved_script(body, consumer):
    return "cat > tmp/script <<'EOF'\n" + body + '\nEOF\n' + consumer


LOCAL = [
    'value=$(printf value); printf proof > tmp/output',
    'export value=$(cat tmp/input); printf "%s" "$value" > tmp/output',
    'value=$(cd ..; printf value); printf proof > tmp/output',
    'first=$(cd ..); second=$(printf value); printf proof > tmp/output',
    'value=$(printf "%s" "$(printf value)"); printf proof > tmp/output',
    "value=$(printf '%s' ')'); printf proof > tmp/output",
    "value='$(printf proof > ../outside)'; printf proof > tmp/output",
    "value=$(printf '%s' '$(printf proof > ../outside)'); printf proof > tmp/output",
    'value=`cd ..; printf value`; printf proof > tmp/output',
    'cd sub; value=$(cd ../..); printf proof > ../tmp/output',
    'for i in 1 2; do start=$(printf value); printf proof > tmp/output; done',
    'value=$(\ncd ..\nprintf value\n); printf proof > tmp/output',
    'for i in 1 2; do start=$(printf value); printf proof > tmp/output 2>&1; done',
    'value=$(printf value); printf proof >| tmp/output',
    'value=$(printf value); printf proof &>tmp/output',
    "cat > tmp/script <<'EOF'\nprintf proof > tmp/output\nEOF\nvalue=$(printf value); sh tmp/script",
    "value=$(printf value); sh <<'EOF'\nprintf proof > tmp/output\nEOF",
    "value=$(printf value); cat <<'EOF' | sh\nprintf proof > tmp/output\nEOF",
    *(saved_script('printf proof > tmp/output', consumer) for consumer in COPY_SCOPES),
]


@pytest.mark.parametrize('level', ['none', 'read'])
@pytest.mark.parametrize('command', LOCAL)
def test_literal_parent_local_writes_still_run_after_substitutions(tmp_path, level, command):
    workspace = tmp_path / 'workspace'
    (workspace / 'tmp').mkdir(parents=True)
    (workspace / 'sub').mkdir()
    (workspace / 'tmp/input').write_text('proof')
    result = subprocess.run(['bash', '-c', command], cwd=workspace, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (workspace / 'tmp/output').read_text() == 'proof'
    assert outbound(command, level, str(workspace)) is None


ESCAPES = [
    'value=$(printf value); printf proof > ../outside',
    'value=$(printf value); printf proof > ../outside 2>&1',
    'value=$(printf value); printf proof >| ../outside',
    'value=$(printf value); printf proof &>../outside',
    "cat > tmp/script <<'EOF'\nprintf proof > ../outside\nEOF\nvalue=$(printf value); sh tmp/script",
    "value=$(printf value); sh <<'EOF'\nprintf proof > ../outside\nEOF",
    "value=$(printf value); cat <<'EOF' | sh\nprintf proof > ../outside\nEOF",
    'value=$(printf proof > ../outside); printf proof > tmp/output',
    'first=$(cd ..); second=$(printf proof > ../outside)',
    'cd ..; value=$(cd workspace); printf proof > outside',
    'cd sub; value=$(cd ../..); printf proof > ../../outside',
    'value=`printf proof > ../outside`; printf proof > tmp/output',
    '(cd ..; printf proof > outside); printf proof > tmp/output',
    "value=$(sh <<'EOF'\nprintf proof > ../outside\nEOF\n); printf proof > tmp/output",
    *(saved_script('printf proof > ../outside', consumer) for consumer in COPY_SCOPES),
    saved_script('printf proof > LOCAL/outside',
                 "value=$(sed 's|LOCAL/|../|' tmp/script > tmp/other); sh tmp/other"),
    saved_script('printf proof > tmp/output',
                 'value=$(printf "%s\\n" "printf proof > ../outside" > tmp/script); sh tmp/script'),
    saved_script('printf proof > "$1"',
                 'value=$(printf ../outside); sh tmp/script "$value"'),
]


@pytest.mark.parametrize('level', ['none', 'read'])
@pytest.mark.parametrize('command', ESCAPES)
def test_child_execution_parent_cwd_and_saved_script_escapes_remain_held(tmp_path, level, command):
    workspace = tmp_path / 'workspace'
    (workspace / 'tmp').mkdir(parents=True)
    (workspace / 'sub').mkdir()
    assert outbound(command, level, str(workspace)) is not None
    result = subprocess.run(['bash', '-c', command], cwd=workspace, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'outside').read_text() == 'proof'


@pytest.mark.parametrize('level', ['none', 'read'])
@pytest.mark.parametrize('command', [
    'value=$(printf value); printf proof > "$value"',
    'printf proof > $(printf tmp/output)',
    'value=$(printf value; printf proof > tmp/output',
    saved_script('printf proof > tmp/output', 'sh "$unknown" tmp/script'),
    saved_script('printf proof > tmp/output', 'sh -s tmp/script "$unknown"'),
])
def test_unknown_or_malformed_write_custody_is_not_a_literal_target_exemption(level, command):
    assert outbound(command, level, '/project') is not None
