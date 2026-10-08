import sys
import json
import pytest
from suite import l0_campaign as campaign, battery_run


def test_l5_manifest_and_cell_command_are_planner_off():
    manifest = campaign.create_manifest('l5-restored', 'a' * 40, {}, level=5)
    assert manifest['level'] == 5 and manifest['planner'] == 'off'
    assert len(manifest['cells']) == 48
    command = campaign.cell_command(manifest, manifest['cells'][0])
    assert command[command.index('--level') + 1] == '5'
    assert '--restored-fleet' in command and '--fresh-l5' not in command
    assert '--planner' not in command  # launcher default is off


def test_restored_l5_battery_uses_canonical_path_without_legacy_swap(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['battery_run.py', '--level', '5', '--model',
        'gemma4_12b', '--task', 'shipping-rates-rb', '--restored-fleet'])
    monkeypatch.setattr(battery_run.run_guard, 'other_suite_runners', lambda: [])
    levels = []
    monkeypatch.setattr(campaign, 'fleet_snapshot', lambda *, level=0: levels.append(level) or {})
    commands = []
    monkeypatch.setattr(battery_run, 'sh', lambda *args, **kwargs: commands.append(args) or 0)
    assert battery_run.main() == 0
    assert levels == [5]
    command = commands[0]
    assert command[command.index('--level') + 1] == '5'
    assert '--restored-fleet' in command


def test_l5_sampling_checks_coder_wire_without_mistaking_judges_for_coder(tmp_path):
    coder = tmp_path / 'coder.json'
    judge = tmp_path / 'judge.json'
    knobs = {'temperature': 1.0, 'top_k': 64}
    coder.write_text(json.dumps(dict(phase='coder-s1', body=dict(model='gemma4_12b', **knobs))))
    judge.write_text(json.dumps(dict(phase='classifier', body=dict(model='gemma4_12b', temperature=0.0))))
    snapshot = dict(entries=[dict(request=str(coder)), dict(request=str(judge))])
    with pytest.raises(ValueError):
        campaign.actual_sampling(snapshot, 'gemma4_12b', knobs)
    assert len(campaign.actual_sampling(snapshot, 'gemma4_12b', knobs, coder_only=True)) == 1
    coder.write_text(json.dumps(dict(phase='coder-s1', body=dict(model='gemma4_12b', temperature=0.0))))
    with pytest.raises(ValueError):
        campaign.actual_sampling(snapshot, 'gemma4_12b', knobs, coder_only=True)
