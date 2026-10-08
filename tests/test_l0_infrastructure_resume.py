"""Explicit repair resume must consume, never retry/score, the infrastructure-failed slot."""
import copy
import json

import pytest
from suite import l0_campaign as campaign
from suite import fresh_l5_campaign


def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(fresh_l5_campaign, '_valid_capture_evidence', lambda _: True)
    model, task = campaign.MODELS[1], campaign.TASKS[0]
    knobs = {'temperature': .6}
    snapshot = {'roles': {model: {'coder': knobs}}}
    manifest = campaign.create_manifest('current', 'a'*40, snapshot)
    cell = next(c for c in manifest['cells'] if (c['model'], c['task']) == (model, task))
    cell.update(state='blocked', attempted_at=manifest['created']+1)
    (tmp_path / 'workspace').mkdir()
    log = tmp_path / 'harness.log'
    log.write_text('HTTP400')
    req = tmp_path / 'request.json'
    req.write_text(json.dumps({'body': {'model': model, **knobs}}))
    capture = {'entries': [{'request': str(req)}]}
    row = {'campaign_id': 'current', 'run_id': 'failed', 'revision': 'a'*40,
           'code_revision': 'a'*40, 'model': model, 'task': task, 'restored_fleet': True,
           'level': 0, 'live_engagement_level': 0, 'planner': 'off', 'planner_enabled': False,
           'planner_phase_count': 0, 'pacing_policy': campaign.POLICY, 'fleet_snapshot': snapshot,
           'capture_snapshot': capture, 'archive': str(tmp_path), 'harness_log': str(log),
           'source_coder_sampling': knobs, 'actual_sent_sampling': campaign.actual_sampling(capture, model, knobs),
           'injected_sampling': [{'fields': knobs}], 'started': manifest['created']+2,
           'terminal': 'harness-error'}
    monkeypatch.setattr(campaign, 'judgment', lambda _: pytest.fail('failed cell must never be judged'))
    return manifest, cell, row, snapshot


def test_repair_preserves_failed_slot_without_score_retry_or_result_mutation(tmp_path, monkeypatch):
    manifest, cell, row, snapshot = fixture(tmp_path, monkeypatch)
    before = copy.deepcopy(row)
    campaign.resume_after_repair(manifest, 'a'*40, 'b'*40, snapshot, [row], failed_run_id='failed')
    assert row == before
    assert cell['state'] == 'infrastructure-failed'
    assert cell['run_id'] == 'failed' and 'judgment' not in cell
    assert not campaign.valid_row(row, manifest)
    campaign.reconcile(manifest, [row])
    assert cell['state'] == 'infrastructure-failed'
    pending = [c for c in manifest['cells'] if c['state'] == 'pending']
    assert cell not in pending and len(pending) == 47
    assert manifest['preserved_runs']['failed']['revision'] == 'a'*40
    assert manifest['repair_history'][-1]['unscored_failed_run_id'] == 'failed'
    row['note'] = 'tampered'
    campaign.reconcile(manifest, [row])
    assert cell['state'] == 'blocked'


@pytest.mark.parametrize('change', ['duplicate', 'other_campaign', 'old', 'natural', 'wrong_revision',
                                     'wrong_run_id', 'wrong_state', 'missing_archive', 'lost_workspace'])
def test_repair_refuses_unproven_or_unrelated_failure(tmp_path, monkeypatch, change):
    manifest, cell, row, snapshot = fixture(tmp_path, monkeypatch)
    rows = [row]
    if change == 'duplicate': rows.append(copy.deepcopy(row))
    elif change == 'other_campaign': row['campaign_id'] = 'other'
    elif change == 'old': row['started'] = manifest['created']-1
    elif change == 'natural': row['terminal'] = 'model-done'
    elif change == 'wrong_revision': row['revision'] = 'c'*40
    elif change == 'wrong_run_id': row['run_id'] = 'unrelated'
    elif change == 'wrong_state': cell['state'] = 'running'
    elif change == 'missing_archive': row['archive'] = str(tmp_path / 'missing')
    elif change == 'lost_workspace': row['workspace_lost'] = True
    before = copy.deepcopy(manifest)
    with pytest.raises(ValueError):
        campaign.resume_after_repair(manifest, 'a'*40, 'b'*40, snapshot, rows, failed_run_id='failed')
    assert manifest == before


def test_second_repair_retains_first_failure_and_new_attempt_separately(tmp_path, monkeypatch):
    manifest, cell, row, snapshot = fixture(tmp_path, monkeypatch)
    campaign.resume_after_repair(manifest, 'a'*40, 'b'*40, snapshot, [row], failed_run_id='failed')
    saved = copy.deepcopy(manifest['preserved_runs']['failed'])
    second = next(c for c in manifest['cells'] if c['model'] == cell['model']
                  and c['task'] == campaign.TASKS[3])
    second.update(state='blocked', attempted_at=manifest['created']+3)
    newer = {**row, 'run_id': 'second-failed', 'task': second['task'],
             'revision': 'b'*40, 'code_revision': 'b'*40, 'started': manifest['created']+4}
    rows = copy.deepcopy([row, newer])
    campaign.resume_after_repair(manifest, 'b'*40, 'c'*40, snapshot, rows,
                                 failed_run_id='second-failed')
    assert manifest['preserved_runs']['failed'] == saved
    assert cell['state'] == second['state'] == 'infrastructure-failed'
    assert rows == [row, newer]
    campaign.reconcile(manifest, rows)
    assert cell['state'] == second['state'] == 'infrastructure-failed'
    assert not any('judgment' in c for c in (cell, second))


@pytest.mark.parametrize('change', ['missing', 'mutated', 'duplicate'])
def test_second_repair_refuses_changed_prior_failure(tmp_path, monkeypatch, change):
    manifest, cell, row, snapshot = fixture(tmp_path, monkeypatch)
    campaign.resume_after_repair(manifest, 'a'*40, 'b'*40, snapshot, [row], failed_run_id='failed')
    rows = [row]
    if change == 'missing': rows = []
    elif change == 'mutated': row['note'] = 'changed'
    else: rows.append(copy.deepcopy(row))
    before = copy.deepcopy(manifest)
    with pytest.raises(ValueError, match='preserved infrastructure failure changed'):
        campaign.resume_after_repair(manifest, 'b'*40, 'c'*40, snapshot, rows)
    assert manifest == before


def test_reconcile_rejects_disappeared_failure_instead_of_relaunching(tmp_path, monkeypatch):
    manifest, cell, row, snapshot = fixture(tmp_path, monkeypatch)
    campaign.resume_after_repair(manifest, 'a'*40, 'b'*40, snapshot, [row], failed_run_id='failed')
    campaign.reconcile(manifest, [])
    assert cell['state'] == 'blocked'
