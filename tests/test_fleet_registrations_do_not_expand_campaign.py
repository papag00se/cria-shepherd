"""Adding Dory must not invalidate, or silently expand, the frozen campaign roster."""
import json

import pytest

from suite import l0_campaign as campaign


class ReachedAssetValidation(RuntimeError):
    pass


@pytest.mark.parametrize('damage', [None, 'missing-role', 'missing-recipe', 'missing-campaign-model', 'schema'])
def test_registered_extras_coexist_with_the_frozen_roster_but_registration_stays_coherent(tmp_path, monkeypatch, damage):
    original_roster = campaign.MODELS
    names = set(original_roster) | {'dory1.0_4b'}
    if damage == 'missing-campaign-model':
        names.remove('phi4')
    config = tmp_path / 'models.toml'
    config.write_text('operational_fleet_schema = ' + ('0' if damage == 'schema' else '1') + '\n' +
                      '\n'.join('[models.' + json.dumps(name) + ']\n' for name in sorted(names)))
    roles = {name: {} for name in names}
    recipes = {name: {} for name in names}
    if damage == 'missing-role':
        roles.pop('dory1.0_4b')
    if damage == 'missing-recipe':
        recipes.pop('dory1.0_4b')
    role_path = tmp_path / 'roles.json'
    role_path.write_text(json.dumps(roles))
    (tmp_path / 'profiles').mkdir()
    (tmp_path / 'profiles/model-recipes.json').write_text(json.dumps(recipes))
    completion = tmp_path / 'completion.json'
    completion.write_text(json.dumps({'models': {}}))
    readiness = tmp_path / 'readiness.json'
    readiness.write_text(json.dumps({'completion_receipt': str(completion), 'models': {}}))
    monkeypatch.setattr(campaign, 'CONFIG', config)
    monkeypatch.setattr(campaign, 'ROLES', role_path)
    monkeypatch.setattr(campaign, 'FLEET', tmp_path)
    monkeypatch.setattr(campaign, 'READINESS', readiness)
    # Readiness and asset bindings have their own contract; isolate registration validation
    # before it reaches machine-specific fingerprints, unit checks or model launches.
    monkeypatch.setattr(campaign, 'validate_readiness', lambda receipt: None)
    def asset_boundary(*args, **kwargs):
        raise ReachedAssetValidation
    monkeypatch.setattr(campaign, 'fingerprint', asset_boundary)
    with pytest.raises(ReachedAssetValidation if damage is None else ValueError):
        campaign.fleet_snapshot()
    assert campaign.MODELS == original_roster
    assert 'dory1.0_4b' not in campaign.MODELS
