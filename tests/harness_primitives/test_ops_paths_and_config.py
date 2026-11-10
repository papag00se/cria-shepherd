"""How a path the model named becomes ROOT and REL, what an unavailable key or ledger does, and the [harness] table."""
import json
from pathlib import Path

import pytest

from cria import ops, privatepaths, writeproxy
from cria.config import Config, HarnessConfig
from ops_rig import isolated_home  # noqa: F401

SHELL = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}


@pytest.mark.parametrize('path,workspace,expected', [
    ('.', '/w', ('/w', '')), ('src/a.py', '/w', ('/w', 'src/a.py')), ('/w/src', '/w', ('/w', 'src')), ('src/../lib/./b', '/w', ('/w', 'lib/b')),
    ('/etc/hosts', '/w', ('/', 'etc/hosts')), ('/', '/w', ('/', '')), ('/w/../x', '/w', ('/', 'x')),
    ('.', None, ('.', '')), ('src/a', None, ('.', 'src/a')), ('../x', None, ('..', 'x')), ('../../a/b', None, ('../..', 'a/b')), ('/usr/lib', None, ('/', 'usr/lib')),
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
    assert command.startswith('# list_dir .\n/usr/bin/env -i PATH=/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin \\\n  python3 -I -S -c ')
    assert len(command) < 2300 and 'base64' not in command.split("' ")[-1]
    assert lower_list(tmp_path)['id'].startswith('ctx_')


def test_without_a_key_or_a_ledger_a_listing_is_answered_with_a_refusal_never_an_unauthenticated_call(tmp_path):
    privatepaths.CRIA_HOME.mkdir(parents=True)
    (privatepaths.CRIA_HOME / 'ops').symlink_to(tmp_path)           # the ledger directory is a link: it refuses to open
    tool_call = lower_list(tmp_path)
    command = json.loads(tool_call['function']['arguments'])['cmd']
    assert 'list_dir is unavailable' in command and 'python3' not in command.split('\n', 1)[-1] and not tool_call['id'].startswith('ctx_')


def test_without_a_key_or_a_ledger_a_read_is_answered_with_a_refusal_never_an_unauthenticated_call(tmp_path):
    privatepaths.CRIA_HOME.mkdir(parents=True)
    (privatepaths.CRIA_HOME / 'ops').symlink_to(tmp_path)
    call = {'id': 'c', 'type': 'function', 'function': {'name': 'read_file', 'arguments': json.dumps({'path': 'a.py'})}}
    completion = {'choices': [{'message': {'tool_calls': [call]}}]}
    engine = ops.Ops()
    writeproxy.translate_outbound(completion, SHELL, injected={'read_file'}, workspace_root='/w', issue_read=lambda c, a, instead: engine.issue_read(
        's', SHELL, c, a, workspace_root='/w', level='none', instead=instead))
    tool_call = completion['choices'][0]['message']['tool_calls'][0]
    command = json.loads(tool_call['function']['arguments'])['cmd']
    assert 'read_file is unavailable' in command and 'python3' not in command and not tool_call['id'].startswith('ctx_')


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
    assert '/usr/bin/env -i PATH=/opt/tools/bin:/usr/bin ' in json.loads(completion['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['cmd']


@pytest.mark.parametrize('value', ['/usr/bin\n:/bin', '/usr/bin:/b\x07in', '/usr/bin\t', '/usr/\x00bin'])
def test_a_safe_path_with_a_control_character_is_rejected_at_the_config_and_at_the_composer(value):
    """Review (low): such a value passed validation and silently broke every primitive (no frame, every call UNKNOWN)."""
    from cria import harnessprims
    with pytest.raises(ValueError):
        HarnessConfig(safe_path=value)
    with pytest.raises(ValueError):
        harnessprims.compose('ls', 'ab' * 16, [], safe_path=value)


def test_the_symbol_limits_are_config_values_documented_with_defaults_and_recorded_in_the_inventory_operation(tmp_path):
    from cria import inventoryops
    assert (HarnessConfig().symbols_max_file_bytes, HarnessConfig().symbols_max_per_file, HarnessConfig().symbols_max_output_bytes) == (1_048_576, 500, 2_097_152)
    assert inventoryops.DEFAULT_LIMITS == {'file_bytes': 1_048_576, 'symbols': 500, 'output_bytes': 2_097_152}
    for bad in (0, -1, 1.5, '5', True):
        with pytest.raises(ValueError, match='symbols_max_per_file'):
            HarnessConfig(symbols_max_per_file=bad)
    path = tmp_path / 'c.toml'
    path.write_text('[harness]\nsymbols_max_file_bytes = 2000\nsymbols_max_per_file = 7\nsymbols_max_output_bytes = 90000\n')
    limits = inventoryops.limits_of(Config.load(path).harness)
    assert limits == {'file_bytes': 2000, 'symbols': 7, 'output_bytes': 90000}
    engine = ops.Ops(inventory_limits=limits)
    _, calls = engine.issue_inventory('s', SHELL, str(tmp_path))
    assert next(iter(engine.ledger.ops('s').values())).ctx['limits'] == limits and calls
    import tomllib
    example = tomllib.loads((Path(__file__).resolve().parents[2] / 'cria.example.toml').read_text())['harness']            # the documented example is the defaults
    assert inventoryops.limits_of(HarnessConfig(**example)) == inventoryops.DEFAULT_LIMITS
