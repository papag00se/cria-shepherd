"""Source-custody and split regressions for offline annotation preparation."""
import hashlib
import json
import time

import pytest

from suite.training_prepare import extract, partition_rows, choose


def row(task, session, raw, family='retrospective', model='one'):
    return {'id': family + '-' + raw, 'family': family, 'task': task, 'session': session,
            'candidate_sha256': raw, 'run_ids': [task + '-run'], 'coder_model': model}


def test_duplicate_input_across_task_partitions_quarantines_connected_component():
    rows = [row('feed-pipeline-java', 'a', 'same'), row('rust-toml-cli', 'b', 'same')]
    partition_rows(rows)
    assert all(r['partition'] == 'QUARANTINE' for r in rows)
    assert len({r['group_id'] for r in rows}) == 1


def test_shared_session_is_not_allowed_across_partitions():
    rows = [row('feed-pipeline-java', 'same-session', 'a'), row('handles-cli-node', 'same-session', 'b')]
    partition_rows(rows)
    assert {r['partition'] for r in rows} == {'QUARANTINE'}


def test_same_task_never_splits_by_model_or_run():
    a = row('orders-api-py', 'a', 'a')
    b = row('orders-api-py', 'b', 'b', model='two')
    b['run_ids'] = ['another-run']
    partition_rows([a, b])
    assert a['partition'] == b['partition'] == 'TRAIN'
    assert a['group_id'] == b['group_id']


def test_selection_is_label_blind_order_independent_and_not_best_score():
    rows = [row('orders-api-py', str(i), str(i), model=str(i % 3)) for i in range(30)]
    partition_rows(rows)
    first = choose(rows)
    for i, r in enumerate(rows):
        r['historical_label'] = 'PLAN' if i % 2 else 'RETROSPECTIVE'
        r['usefulness'] = 100 - i
    assert choose(list(reversed(rows))) == first
    assert len(first) == 12
    assert {r['coder_model'] for r in rows if r['id'] in first} == {'0', '1', '2'}


def test_complete_unicode_slot_and_both_hashes_are_checked(tmp_path):
    text = 'whole é\n查 input'
    surrounding = 'CANDIDATE:\n' + text + '\nEND'
    path = tmp_path / 'request.json'
    path.write_text(json.dumps({'body': {'messages': [{'content': surrounding}]}}))
    start = len('CANDIDATE:\n')
    record = {'request': str(path), 'request_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'pointer': '/body/messages/0/content', 'decoded_character_span': [start, start + len(text)],
              'utf8_byte_span': [start, start + len(text.encode())],
              'candidate_sha256': hashlib.sha256(text.encode()).hexdigest()}
    assert extract(record, time.time_ns()) == text
    record['utf8_byte_span'][1] -= 1
    with pytest.raises(ValueError, match='mismatch'):
        extract(record, time.time_ns())
    record['request_sha256'] = 'wrong'
    with pytest.raises(ValueError, match='changed'):
        extract(record, time.time_ns())


def test_audit_binding_rejects_changed_join_database_or_cutoff(tmp_path):
    from suite.training_prepare import verify_audit_sources
    custody, database = tmp_path / 'custody.json', tmp_path / 'inventory.sqlite'
    custody.write_text('[]')
    database.write_bytes(b'frozen join data')
    metadata = tmp_path / 'audit.json'
    metadata.write_text(json.dumps({'frozen_cutoff_ns': 123, 'source_head': 'audited', 'scratch_artifacts': [
        {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in (custody, database)]}))
    assert verify_audit_sources(custody, database, 123, metadata)['source_head'] == 'audited'
    database.write_bytes(b'changed join data')
    with pytest.raises(ValueError, match='fingerprint'):
        verify_audit_sources(custody, database, 123, metadata)
    with pytest.raises(ValueError, match='cutoff'):
        verify_audit_sources(custody, database, 124, metadata)


def test_byte_coordinates_must_be_exact_not_silently_clamped(tmp_path):
    text = 'complete candidate'
    path = tmp_path / 'request.json'
    path.write_text(json.dumps({'body': {'messages': [{'content': text}]}}))
    r = {'request': str(path), 'request_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
         'pointer': '/body/messages/0/content', 'decoded_character_span': [0, len(text)],
         'utf8_byte_span': [0, len(text) + 100], 'candidate_sha256': hashlib.sha256(text.encode()).hexdigest()}
    with pytest.raises(ValueError, match='span'):
        extract(r, time.time_ns())


def test_partition_queries_use_the_exact_verified_database_snapshot(tmp_path, monkeypatch):
    import sqlite3
    from suite.training_prepare import prepare

    request = tmp_path / 'request.json'
    text = 'Observed state.'
    request.write_text(json.dumps({'candidate': text}))
    custody = tmp_path / 'custody.json'
    custody.write_text(json.dumps([{'request': str(request), 'family': 'retrospective',
        'request_sha256': hashlib.sha256(request.read_bytes()).hexdigest(), 'pointer': '/candidate',
        'decoded_character_span': [0, len(text)], 'utf8_byte_span': [0, len(text)],
        'candidate_sha256': hashlib.sha256(text.encode()).hexdigest(), 'session': 'session', 'run_ids': ['run']}]))
    database = tmp_path / 'index.sqlite'
    real_connect = sqlite3.connect
    def db_bytes(task):
        db = real_connect(':memory:')
        db.execute('create table captures(path text, paired_public integer, meta text)')
        db.execute('insert into captures values(?,1,?)', (str(request), json.dumps({
            'join_status': 'unique_cell', 'task': task, 'model': 'fixture', 'language': 'Python'})))
        db.commit()
        result = db.serialize()
        db.close()
        return result
    database.write_bytes(db_bytes('orders-api-py'))
    cutoff = time.time_ns()
    metadata = tmp_path / 'audit.json'
    metadata.write_text(json.dumps({'frozen_cutoff_ns': cutoff, 'source_head': 'fixture', 'scratch_artifacts': [
        {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in (custody, database)]}))
    replacement = db_bytes('handles-cli-node')
    def replace_after_verification(*args, **kwargs):
        database.write_bytes(replacement)
        return real_connect(*args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', replace_after_verification)
    rows, _ = prepare(custody, database, cutoff, review_all=True, audit_metadata=metadata)
    assert rows[0]['task'] == 'orders-api-py'
    assert rows[0]['partition'] == 'TRAIN'


def test_quarantined_connected_rows_are_never_selected():
    rows = [row('feed-pipeline-java', 'a', 'same'), row('rust-toml-cli', 'b', 'same')]
    partition_rows(rows)
    assert choose(rows) == set()
