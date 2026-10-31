"""Fresh L0 cells require restored evidence and independent judgments, never old scores."""
import json
from pathlib import Path
import pytest
from suite import l0_campaign as campaign
from suite import run, battery_run


def test_official_eight_and_existing_six_tasks():
    from suite.battery_status import TASKS
    assert campaign.TASKS == TASKS
    assert len(campaign.MODELS) == 8
    assert len(set(campaign.MODELS)) == 8
    assert 'gemma4_12b' in campaign.MODELS and 'defiant-fable' not in campaign.MODELS


@pytest.mark.parametrize('name', ['', '../other', 'x/y', 'x y'])
def test_campaign_id_cannot_escape_state_directory(name):
    with pytest.raises(ValueError):
        campaign.campaign_dir(name)


def test_pending_restoration_is_not_ready():
    with pytest.raises(ValueError, match='readiness'):
        campaign.validate_readiness({'state': 'executing_operational_restoration', 'models': {}})


def test_restored_battery_delegates_without_changing_live_arm(monkeypatch):
    import sys
    monkeypatch.setattr(sys, 'argv', ['battery_run.py', '--level', '0', '--model', 'gemma4_12b',
        '--task', campaign.TASKS[0], '--restored-fleet', '--campaign-id', 'today',
        '--campaign-revision', 'a'*40])
    monkeypatch.setattr(battery_run.run_guard, 'other_suite_runners', lambda: [])
    monkeypatch.setattr(campaign, 'validate_revision', lambda value: value)
    monkeypatch.setattr(campaign, 'fleet_snapshot', lambda: {})
    monkeypatch.setattr(battery_run, 'set_level', lambda *_: pytest.fail('must not edit live arm'))
    calls=[]
    monkeypatch.setattr(battery_run, 'sh', lambda *cmd, **kwargs: calls.append(cmd) or 0)
    assert battery_run.main() == 0
    assert len(calls) == 1 and '--restored-fleet' in calls[0]
    assert '--campaign-id' in calls[0]


def test_actual_sampling_comes_from_captures_and_missing_knob_is_invalid(tmp_path):
    req=tmp_path/'0001-proxy.json'
    spec={'temperature': .6, 'top_k': 20}
    req.write_text(json.dumps({'body': {'messages':[], 'model':'bonsai2', **spec}}))
    snapshot={'entries':[{'request':str(req)}]}
    assert campaign.actual_sampling(snapshot, 'bonsai2', spec) == [
        {'request':str(req), 'fields':spec}]
    req.write_text(json.dumps({'body': {'messages':[], 'model':'bonsai2', 'temperature':.6}}))
    with pytest.raises(ValueError, match='sampling'):
        campaign.actual_sampling(snapshot, 'bonsai2', spec)


def test_porcelain_leading_space_does_not_misclassify_document_deletion(monkeypatch):
    from types import SimpleNamespace
    def git(argv,**kwargs):
        if 'rev-parse' in argv: return SimpleNamespace(stdout='a'*40+'\n')
        return SimpleNamespace(stdout=' D docs/audits/preserved-user-deletion.md\n?? tests/new.py\n')
    monkeypatch.setattr(campaign.subprocess,'run',git)
    assert campaign.validate_revision('a'*40)=='a'*40


def test_manifest_has_48_fresh_pending_cells_and_no_historical_credit(monkeypatch):
    manifest=campaign.create_manifest('new','a'*40,{})
    assert len(manifest['cells'])==48
    assert manifest['level']==0 and manifest['planner']=='off'
    campaign.reconcile(manifest,[{'model':campaign.MODELS[0],'task':campaign.TASKS[0],
                                 'usefulness_percent':100,'level':0}])
    assert all(cell['state']=='pending' for cell in manifest['cells'])


def test_interrupted_attempt_is_blocked_and_cannot_auto_retry():
    manifest=campaign.create_manifest('new','a'*40,{})
    manifest['cells'][0]['state']='running'
    campaign.reconcile(manifest,[])
    assert manifest['cells'][0]['state']=='blocked'
    campaign.reconcile(manifest,[])
    assert manifest['cells'][0]['state']=='blocked'


def test_final_usefulness_is_required_before_next_cell(monkeypatch):
    manifest=campaign.create_manifest('new','a'*40,{})
    first=manifest['cells'][0]
    row={'campaign_id':'new','model':first['model'],'task':first['task'],
         'started':manifest['created']+1,'run_id':'one'}
    monkeypatch.setattr(campaign,'valid_row',lambda *_:True)
    monkeypatch.setattr(campaign,'judgment',lambda *_:None)
    campaign.reconcile(manifest,[row])
    assert first['state']=='awaiting-usefulness'
    monkeypatch.setattr(campaign,'judgment',lambda *_:{'usefulness_percent':0,'reason':'unused','evidence':['source']})
    campaign.reconcile(manifest,[row])
    assert first['state']=='done' and manifest['cells'][1]['state']=='pending'
