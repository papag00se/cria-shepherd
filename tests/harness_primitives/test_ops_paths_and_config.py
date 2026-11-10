"""How a path the model named becomes ROOT and REL, what an unavailable key or ledger does, and the [harness] table."""
import json

import pytest

from cria import ops, privatepaths, writeproxy
from cria.config import Config, HarnessConfig
from ops_rig import isolated_home  # noqa: F401

SHELL = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}


@pytest.mark.parametrize('path,workspace,expected', [
    ('.', '/w', ('/w', '')), ('src/a.py', '/w', ('/w', 'src/a.py')), ('/w/src', '/w', ('/w', 'src')), ('src/../lib/./b', '/w', ('/w', 'lib/b')),
    ('/etc/hosts', '/w', ('/etc', 'hosts')), ('/', '/w', ('/', '')), ('/w/../x', '/w', ('/', 'x')),
    ('.', None, ('.', '')), ('src/a', None, ('.', 'src/a')), ('../x', None, ('..', 'x')), ('../../a/b', None, ('../..', 'a/b')), ('/usr/lib', None, ('/usr', 'lib')),
    ('~/x', '/w', ('/w', '~/x'))])
def test_a_path_becomes_a_root_cria_chose_and_a_relative_remainder_with_no_dot_or_dotdot(path, workspace, expected):
    assert ops.split(path, workspace) == expected
    root, rel = ops.split(path, workspace)
    assert not {'.', '..', ''} & set(rel.split('/')) or rel == ''


def lower_list(tmp_path, monkeypatch=None, **kw):
    call = {'id': 'c', 'type': 'function', 'function': {'name': 'list_dir', 'arguments': json.dumps({'path': '.'})}}
    completion = {'choices': [{'message': {'tool_calls': [call]}}]}
    engine = ops.Ops()
    writeproxy.translate_outbound(completion, SHELL, injected={'list_dir'}, workspace_root='/w',
                                  issue_list_dir=lambda c, a: engine.issue_list_dir('s', SHELL, c, a, workspace_root='/w', level='none'), **kw)
    return completion['choices'][0]['message']['tool_calls'][0]


def test_a_listing_lowers_to_one_primitive_call_whose_command_is_the_fixed_stub_and_whose_id_is_a_mac(tmp_path):
    command = json.loads(lower_list(tmp_path)['function']['arguments'])['cmd']
    assert command.startswith('# list_dir .\nenv -i PATH=/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin \\\n  python3 -I -S -c ')
    assert len(command) < 2300 and 'base64' not in command.split("' ")[-1]
    assert lower_list(tmp_path)['id'].startswith('ctx_')


def test_without_a_key_or_a_ledger_a_listing_is_answered_with_a_refusal_never_an_unauthenticated_call(tmp_path):
    privatepaths.CRIA_HOME.mkdir(parents=True)
    (privatepaths.CRIA_HOME / 'ops').symlink_to(tmp_path)           # the ledger directory is a link: it refuses to open
    tool_call = lower_list(tmp_path)
    command = json.loads(tool_call['function']['arguments'])['cmd']
    assert 'list_dir is unavailable' in command and 'python3' not in command.split('\n', 1)[-1] and not tool_call['id'].startswith('ctx_')


def test_the_harness_table_takes_only_absolute_system_directories(tmp_path):
    assert HarnessConfig().safe_path == '/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin'
    for bad in ('bin:/usr/bin', '', '/usr/bin:', "/usr/b'in", '/usr/bin :/bin'):
        with pytest.raises(ValueError):
            HarnessConfig(safe_path=bad)
    path = tmp_path / 'c.toml'
    path.write_text('[harness]\nsafe_path = "/opt/tools/bin:/usr/bin"\n')
    assert Config.load(path).harness.safe_path == '/opt/tools/bin:/usr/bin'
    path.write_text('[harness]\nsafe_pth = "/usr/bin"\n')
    with pytest.raises(ValueError, match='safe_pth'):
        Config.load(path)


def test_a_configured_safe_path_is_what_the_composed_command_and_the_candidate_safety_check_use(tmp_path):
    completion = {'choices': [{'message': {'tool_calls': [{'id': 'c', 'type': 'function', 'function': {'name': 'list_dir', 'arguments': '{}'}}]}}]}
    engine = ops.Ops(safe_path='/opt/tools/bin:/usr/bin')
    writeproxy.translate_outbound(completion, SHELL, injected={'list_dir'}, workspace_root='/w',
                                  issue_list_dir=lambda c, a: engine.issue_list_dir('s', SHELL, c, a, workspace_root='/w', level='none'))
    assert 'env -i PATH=/opt/tools/bin:/usr/bin ' in json.loads(completion['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['cmd']
