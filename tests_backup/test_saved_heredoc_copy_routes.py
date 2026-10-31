"""Same P1: a saved stdin source must retain origin when saved under another name."""
import subprocess

import pytest

from test_saved_heredoc_input_routes import WS, outbound, saved

COPIES = [
    'cat < tmp/script > tmp/other',
    'cat tmp/script > tmp/other',
    'cat < tmp/script | cat > tmp/other',
    'cat < tmp/script | tee tmp/other > /dev/null',
]


@pytest.mark.parametrize('copy', COPIES)
@pytest.mark.parametrize('level', ['none', 'read'])
def test_stdin_backed_copy_then_execution_really_writes_outside_and_is_held(tmp_path, copy, level):
    workspace = tmp_path / 'workspace'
    (workspace / 'tmp').mkdir(parents=True)
    command = saved('printf proof > ' + str(tmp_path / 'outside'), copy + '; sh tmp/other')
    result = subprocess.run(['bash', '-c', command], cwd=workspace, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'outside').read_text() == 'proof'
    assert outbound(command, level, str(workspace)) is not None


@pytest.mark.parametrize('copy', COPIES)
@pytest.mark.parametrize('level', ['none', 'read'])
def test_proven_local_copy_execution_and_plain_inspection_remain_available(copy, level):
    assert outbound(saved('printf proof > local', copy + '; sh tmp/other'), level, WS) is None
    assert outbound(saved('/external/literal/data', copy + '; cat tmp/other'), level, WS) is None
    assert outbound(saved('/external/literal/data', copy + '; sh tmp/unrelated'), level, WS) is None


@pytest.mark.parametrize('copy', [
    'cut -c2- < tmp/script > tmp/other',
    'cat < tmp/script | cut -c2- > tmp/other',
    "cat < tmp/script > tmp/other; sed -i 's/^#//' tmp/other",
])
@pytest.mark.parametrize('level', ['none', 'read'])
def test_transformed_saved_outputs_do_not_inherit_old_byte_custody(copy, level):
    assert outbound(saved('#printf proof > ../outside', copy + '; sh tmp/other'), level, WS) is not None


@pytest.mark.parametrize('level', ['none', 'read'])
def test_saved_output_paths_and_execution_use_their_own_cwd(level):
    copy = 'cd sub; cat < ../tmp/script > ../tmp/other; cd ..; sh tmp/other'
    assert outbound(saved('printf proof > local', copy), level, WS) is None
    assert outbound(saved('printf proof > ../outside', copy), level, WS) is not None


@pytest.mark.parametrize('level', ['none', 'read'])
@pytest.mark.parametrize('copy', [
    'sh -c "cat < tmp/script > tmp/other"; sh tmp/other',
    'sh -c "cat < tmp/script | cat > tmp/other"; sh < tmp/other',
])
def test_nested_reader_returns_saved_output_custody_to_the_parent(copy, level):
    assert outbound(saved('printf proof > local', copy), level, WS) is None
    assert outbound(saved('printf proof > ../outside', copy), level, WS) is not None


@pytest.mark.parametrize('nested', [False, True])
def test_saved_stdin_origin_survives_multiple_saves_and_nested_shells(nested):
    route = 'cat < tmp/script > tmp/copy; cat < tmp/copy > tmp/other; sh tmp/other'
    if nested:
        route = 'sh -c "' + route + '"'
    assert outbound(saved('printf proof > local', route), 'none', WS) is None
    assert outbound(saved('printf proof > ../outside', route), 'none', WS) is not None
