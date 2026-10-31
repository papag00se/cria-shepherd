"""Small edits cannot stand in for a requirement-completion pace assessment."""
import json
from suite import milestones


def verdict():
    return dict(usefulness_percent=35, decision='continue', reason='Some useful edits.',
                material_changes='Worker-local map introduced.', evidence=['Current source inspected.'])


def test_new_checkpoint_rejects_changes_only_judgment(tmp_path, monkeypatch):
    monkeypatch.setattr(milestones, 'ROOT', tmp_path/'reviews')
    ws=tmp_path/'ws'; ws.mkdir()
    task=tmp_path/'task'; task.mkdir(); (task/'prompt.txt').write_text('Implement parsing and deterministic workers.')
    checkpoint=milestones.create('run',45,ws,task)
    assert milestones.parse_for_checkpoint(checkpoint,json.dumps(verdict())) is None


def test_requirement_pace_evidence_preserved_without_numeric_stop_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(milestones, 'ROOT', tmp_path/'reviews')
    ws=tmp_path/'ws'; ws.mkdir()
    task=tmp_path/'task'; task.mkdir(); (task/'prompt.txt').write_text('Implement parsing and deterministic workers.')
    checkpoint=milestones.create('run',45,ws,task)
    v=verdict(); v.update(requirements=[dict(requirement='Parsing',status='completed',evidence='Quoted input verified.'),dict(requirement='Deterministic workers',status='partial',evidence='Row counters race.')],pace_reason='Only parsing delivered after45 active minutes; unfinished worker rewrite does not warrant another interval.',decision='stalled')
    assert milestones.parse_for_checkpoint(checkpoint,json.dumps(v)) == v
    v['decision']='continue'; v['pace_reason']='Specific difficult integration is near completion based on inspected evidence; justified exception to approximate pace.'
    assert milestones.parse_for_checkpoint(checkpoint,json.dumps(v)) == v
    v['requirements'][1]['evidence']=''
    assert milestones.parse_for_checkpoint(checkpoint,json.dumps(v)) is None


def test_legacy_checkpoint_remains_readable(tmp_path):
    assert milestones.parse_for_checkpoint(tmp_path,json.dumps(verdict())) == verdict()
