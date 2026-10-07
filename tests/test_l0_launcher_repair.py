import json
from pathlib import Path
import pytest
from cria import responses
from suite import run, l0_campaign as campaign


def test_custom_tool_round_trip_preserves_patch_and_format():
    patch = '*** Begin Patch\n*** Add File: café.txt\n+hello\n*** End Patch\n'
    fmt = {'type': 'grammar', 'syntax': 'lark', 'definition': 'start: /.+/'}
    req = {'model': 'local', 'tools': [{'type': 'custom', 'name': 'apply_patch', 'format': fmt}],
           'input': [{'type': 'custom_tool_call', 'name': 'apply_patch', 'call_id': 'p', 'input': patch},
                     {'type': 'custom_tool_call_output', 'call_id': 'p', 'output': 'Success'}],
           'tool_choice': {'type': 'custom', 'name': 'apply_patch'}}
    body = responses.to_chat_body(req)
    assert fmt['definition'] in body['tools'][0]['function']['parameters']['properties']['input']['description']
    assert json.loads(body['messages'][0]['tool_calls'][0]['function']['arguments']) == {'input': patch}
    assert body['messages'][1] == {'role': 'tool', 'tool_call_id': 'p', 'content': 'Success'}
    assert body['tool_choice']['function']['name'] == 'apply_patch'
    comp = {'choices': [{'message': {'tool_calls': body['messages'][0]['tool_calls']}}]}
    names = responses.custom_tool_names(req)
    result = responses.to_responses_json(comp, 'local', custom_tools=names)
    assert result['output'][0]['type'] == 'custom_tool_call'
    assert result['output'][0]['input'] == patch
    events = list(responses.body_events(comp, 'r', 'local', custom_tools=names))
    completed = json.loads(events[-1].decode().split('data: ', 1)[1])
    assert completed['response']['output'][0]['input'] == patch
    assert any(b'response.custom_tool_call_input.delta' in e for e in events)


def test_custom_output_does_not_guess_from_function_name():
    comp = {'choices': [{'message': {'tool_calls': [{'id': 'p', 'function': {
        'name': 'apply_patch', 'arguments': '{"input":"patch"}'}}]}}]}
    assert responses.to_responses_json(comp, 'local')['output'][0]['type'] == 'function_call'


def test_cell_home_is_exclusive_and_template_does_not_drift(tmp_path, monkeypatch):
    template = tmp_path / 'template'
    template.mkdir()
    (template / 'config.toml').write_text('model="local"\n')
    (template / 'auth.json').write_text('never copy credentials')
    monkeypatch.setattr(run, 'SUITE_CODEX_HOME', template)
    monkeypatch.setattr(run, '_cell_install_root', lambda ws: tmp_path / ws.name)
    before = (template / 'config.toml').read_bytes()
    one = run.cell_codex_home(Path('/one'))
    (one / 'config.toml').write_text('model="local"\n[projects.one]\ntrust_level="trusted"\n')
    two = run.cell_codex_home(Path('/two'))
    assert one != two and (two / 'config.toml').read_bytes() == before
    assert (template / 'config.toml').read_bytes() == before
    assert not (one / 'auth.json').exists()
    with pytest.raises(FileExistsError):
        run.cell_codex_home(Path('/one'))


def test_explicit_repair_preserves_only_completed_current_rows(monkeypatch):
    m = campaign.create_manifest('current', 'a'*40, {})
    m['cells'][0].update(state='done', run_id='first')
    row = {'campaign_id': 'current', 'run_id': 'first', 'model': m['cells'][0]['model'],
           'task': m['cells'][0]['task'], 'revision': 'a'*40, 'fleet_snapshot': {}, 'started': m['created']+1}
    monkeypatch.setattr(campaign, 'valid_row', lambda *_: True)
    monkeypatch.setattr(campaign, 'judgment', lambda *_: {'usefulness_percent': 0})
    campaign.resume_after_repair(m, 'a'*40, 'b'*40, {}, [row])
    assert m['revision'] == 'b'*40
    assert m['preserved_runs'] == {'first': {'revision': 'a'*40, 'model': row['model'], 'task': row['task'], 'fleet_snapshot': {}}}
    assert m['cells'][0]['state'] == 'done'
    assert all(c['state'] == 'pending' for c in m['cells'][1:])


@pytest.mark.parametrize('state', ['running', 'blocked', 'awaiting-usefulness'])
def test_repair_cannot_retry_or_adopt_an_unfinished_attempt(state):
    m = campaign.create_manifest('current', 'a'*40, {})
    m['cells'][0]['state'] = state
    with pytest.raises(ValueError, match='completed'):
        campaign.resume_after_repair(m, 'a'*40, 'b'*40, {}, [])


def test_repair_allows_only_byte_identical_home_config_stat_drift():
    config = str(Path.home() / '.cria/codex-home/config.toml')
    old = {'assets': {config: {'sha256': 'exact', 'size': 10, 'inode': 1},
                      'weights': {'sha256': 'weights', 'inode': 5}}}
    new = {'assets': {config: {'sha256': 'exact', 'size': 10, 'inode': 2},
                      'weights': {'sha256': 'weights', 'inode': 5}}}
    m = campaign.create_manifest('current', 'a'*40, old)
    campaign.resume_after_repair(m, 'a'*40, 'b'*40, new, [])
    assert m['fleet_snapshot'] == new
    new['assets']['weights']['inode'] = 6
    with pytest.raises(ValueError, match='assets'):
        campaign.resume_after_repair(campaign.create_manifest('current', 'a'*40, old),
                                   'a'*40, 'b'*40, new, [])


def test_repair_cannot_retry_pending_cell_with_attempt_metadata():
    m = campaign.create_manifest('current', 'a'*40, {})
    m['cells'][0]['attempted_at'] = 1
    with pytest.raises(ValueError, match='attempt'):
        campaign.resume_after_repair(m, 'a'*40, 'b'*40, {}, [])


def test_preserved_revision_and_snapshot_are_bound_to_exact_fresh_run(tmp_path, monkeypatch):
    from suite import fresh_l5_campaign
    monkeypatch.setattr(fresh_l5_campaign, '_valid_capture_evidence', lambda _: True)
    model, task = campaign.MODELS[0], campaign.TASKS[0]
    knobs = {'temperature': 1.0}
    snapshot = {'roles': {model: {'coder': knobs}}}
    m = campaign.create_manifest('current', 'b'*40, snapshot)
    m['preserved_runs'] = {'first': {'model': model, 'task': task, 'revision': 'a'*40,
                                   'fleet_snapshot': snapshot}}
    (tmp_path / 'workspace').mkdir()
    log = tmp_path / 'harness.log'
    log.write_text('proof')
    req = tmp_path / 'request.json'
    req.write_text(json.dumps({'body': {'model': model, **knobs}}))
    capture = {'entries': [{'request': str(req)}]}
    row = {'campaign_id': 'current', 'run_id': 'first', 'revision': 'a'*40,
           'code_revision': 'a'*40, 'model': model, 'task': task, 'restored_fleet': True,
           'level': 0, 'live_engagement_level': 0, 'planner': 'off', 'planner_enabled': False,
           'planner_phase_count': 0, 'pacing_policy': campaign.POLICY, 'fleet_snapshot': snapshot,
           'capture_snapshot': capture, 'archive': str(tmp_path), 'harness_log': str(log),
           'source_coder_sampling': knobs, 'actual_sent_sampling': campaign.actual_sampling(capture, model, knobs),
           'injected_sampling': [{'fields': knobs}]}
    assert campaign.valid_row(row, m)
    assert not campaign.valid_row({**row, 'run_id': 'historical'}, m)
    assert not campaign.valid_row({**row, 'campaign_id': 'other'}, m)
    assert not campaign.valid_row({**row, 'code_revision': 'c'*40}, m)
    assert not campaign.valid_row({**row, 'task': campaign.TASKS[1]}, m)
