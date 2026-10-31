import hashlib
import json
from pathlib import Path
from suite import l0_campaign as campaign, restored_roles, fresh_l5_campaign


def test_l5_role_config_and_wire_are_bound_to_manifest(tmp_path, monkeypatch):
    model, task, revision = campaign.MODELS[0], campaign.TASKS[0], 'a' * 40
    roles = {r: {'temperature': float(i)} for i, r in
             enumerate(('coder', 'reasoner', 'classifier', 'compactor'))}
    source = Path('cria.example.toml').read_bytes()
    before, active = tmp_path / 'before.toml', tmp_path / 'active.toml'
    before.write_bytes(source)
    active.write_text(restored_roles.render(source.decode(), roles))
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    snapshot = dict(roles={model: roles}, live_config=dict(sha256=digest(before)))
    manifest = campaign.create_manifest('new', revision, snapshot, level=5)
    archive = tmp_path / 'archive'
    (archive / 'workspace').mkdir(parents=True)
    log = tmp_path / 'run.log'
    log.write_text('terminal')
    request = tmp_path / 'coder.json'
    request.write_text(json.dumps(dict(phase='coder-s1', body=dict(model=model, **roles['coder']))))
    capture = dict(entries=[dict(request=str(request))])
    row = dict(campaign_id='new', revision=revision, code_revision=revision, model=model,
               task=task, restored_fleet=True, level=5, live_engagement_level=5,
               planner='off', planner_enabled=False, planner_phase_count=0,
               pacing_policy=campaign.POLICY, fleet_snapshot=snapshot, capture_snapshot=capture,
               archive=str(archive), harness_log=str(log), source_coder_sampling=roles['coder'],
               actual_sent_sampling=campaign.actual_sampling(capture, model, roles['coder'], coder_only=True),
               injected_sampling=[dict(fields=roles['coder'])],
               live_config_snapshot=dict(sha256=digest(active)),
               restored_role_config=dict(before=str(before), active=str(active), roles=roles,
                                         active_sha256=digest(active)))
    monkeypatch.setattr(fresh_l5_campaign, '_valid_capture_evidence', lambda *a, **k: True)
    assert campaign.valid_row(row, manifest)
    assert not campaign.valid_row({**row, 'level': 0}, manifest)
    active.write_text(active.read_text() + '\n[planner_override]\nenabled=true\n')
    assert not campaign.valid_row(row, manifest)
