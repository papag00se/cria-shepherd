"""Audit metadata must not become invented gold, identity, or partial-file evidence."""
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

from suite.training_archive_audit import (FrozenReadError, read_frozen, capture_metadata,
                                         public_response_metadata, resolve_runs, input_digest, scan)


def test_cutoff_and_no_follow(tmp_path):
    p = tmp_path / 'record.json'
    p.write_text('{}')
    before = p.stat().st_mtime_ns - 1
    try:
        read_frozen(p, before)
    except FrozenReadError as e:
        assert e.reason == 'after_cutoff'
    else:
        assert False, 'a post-cutoff file must not enter the frozen audit'
    link = tmp_path / 'link'
    link.symlink_to(p)
    try:
        read_frozen(link, time.time_ns())
    except FrozenReadError as e:
        assert e.reason == 'symlink_or_nonregular'
    else:
        assert False, 'do not follow archive links outside the declared source'


def test_file_growing_during_read_is_not_a_frozen_record(tmp_path, monkeypatch):
    p = tmp_path / 'capture.json'
    p.write_bytes(b'{}')
    original = os.read
    fired = False
    def growing(fd, n):
        nonlocal fired
        data = original(fd, n)
        if not fired:
            fired = True
            with p.open('ab') as f:
                f.write(b' ')
        return data
    monkeypatch.setattr(os, 'read', growing)
    try:
        read_frozen(p, time.time_ns())
    except FrozenReadError as e:
        assert e.reason == 'changed_during_read'
    else:
        assert False, 'a valid JSON prefix is not a frozen file'


def test_capture_shape_not_filename_and_never_exports_prompt():
    raw = {'seq': 1, 'iso': '2026-01-01T00:00:00Z', 'session': 's', 'turn': 't',
           'phase': 'not-a-reviewed-family', 'body': {'model': 'service-key',
           'messages': [{'role': 'user', 'content': 'PRIVATE TASK CANARY'}]}}
    meta = capture_metadata(raw)
    assert meta['phase'] == 'not-a-reviewed-family'
    assert meta['wire_model'] == 'service-key'
    assert 'PRIVATE TASK CANARY' not in json.dumps(meta)
    assert capture_metadata({'phase': 'steer-code', 'expected_label': 'DICTATES'}) is None


def test_private_reasoning_is_not_a_public_label():
    raw = {'choices': [{'finish_reason': 'stop', 'message': {
        'content': '', 'reasoning_content': 'RETROSPECTIVE PRIVATE CANARY'}}]}
    meta = public_response_metadata(raw)
    assert not meta['has_public_answer']
    assert meta['has_reasoning_channel']
    assert 'PRIVATE CANARY' not in json.dumps(meta)
    raw['choices'][0]['message']['content'] = 'PLAN'
    raw['choices'][0]['finish_reason'] = 'length'
    assert public_response_metadata(raw)['generation_incomplete']


def test_ambiguous_session_never_picks_best_or_last_run():
    runs = [{'run_id': 'a', 'model': 'ornith15', 'task': 'cart-billing-go', 'harness': 'codex', 'revision': 'x'},
            {'run_id': 'b', 'model': 'phi4', 'task': 'orders-api-py', 'harness': 'pi', 'revision': 'y'}]
    assert resolve_runs(runs)['join_status'] == 'ambiguous'
    single = resolve_runs(runs[:1])
    assert single['model'] == 'ornith1.5_9b' and single['language'] == 'Go'
    assert resolve_runs([])['language'] == 'UNKNOWN'
    assert resolve_runs([{'run_id': 'z', 'model': 'new-model', 'task': 'unknown-task'}])['language'] == 'UNKNOWN'


def test_exact_input_dedup_keeps_policy_and_tools_not_model_sampling():
    a = {'model': 'a', 'temperature': 0, 'messages': [{'role': 'user', 'content': 'whole text'}]}
    b = {**a, 'model': 'b', 'temperature': 1}
    assert input_digest(a) == input_digest(b)
    assert input_digest(a) != input_digest({**a, 'messages': [{'role': 'user', 'content': 'other whole text'}]})
    assert input_digest(a) != input_digest({**a, 'tools': [{'type': 'function', 'function': {'name': 'verdict'}}]})


def test_end_to_end_inventory_joins_hashes_pairs_and_malformed_inputs(tmp_path):
    calls = tmp_path / 'calls'
    first = calls / 'session-a'
    second = calls / 'session-b'
    first.mkdir(parents=True)
    second.mkdir()
    archives = tmp_path / 'archives'
    (archives / 'run-a' / 'workspace').mkdir(parents=True)
    long_text = 'RAW_INPUT_CANARY λ\n' * 20000
    body = {'model': 'service-key', 'messages': [{'role': 'user', 'content': long_text}]}
    paths = []
    variants = [
        {'choices': [{'message': {'content': 'PUBLIC_A'}, 'finish_reason': 'stop'}]},
        {'choices': [{'message': {'content': 'PUBLIC_B'}, 'finish_reason': 'stop'}]},
        {'choices': [{'message': {'content': '', 'reasoning_content': 'PRIVATE_ONLY_CANARY'}, 'finish_reason': 'stop'}]},
        {'choices': [{'message': {'content': 'partial'}, 'finish_reason': 'length'}]},
        {'error': {'type': 'upstream_failure'}},
        {'choices': {'not': 'a choice array'}},
        {'choices': [{'message': {'tool_calls': [{'type': 'function', 'function': {'name': 'verdict', 'arguments': '{}'}}]}, 'finish_reason': 'tool_calls'}]},
    ]
    for i, response in enumerate(variants):
        directory = first if i < 2 else second
        request = directory / f'{i:04}-same-phase.json'
        request.write_text(json.dumps({'seq': i, 'session': directory.name, 'turn': str(i),
                                      'iso': '2026-01-01T00:00:00Z', 'phase': 'same-phase', 'body': body}))
        request.with_name(request.stem + '.response.json').write_text(json.dumps(response))
        paths.append(request)
    bad = first / '9999-bad-shape.json'
    bad.write_text(json.dumps({'seq': 9999, 'session': {}, 'turn': 'x', 'iso': 'x',
                               'phase': ['not scalar'], 'body': body}))
    (first / 'foreign-invalid.json').write_text('{unclosed')
    result_rows = [
        {'run_id': 'run-a', 'model': 'ornith15', 'task': 'cart-billing-go', 'harness': 'codex',
         'revision': 'r1', 'capture_dirs': [str(first), str(second)], 'archive': str(archives / 'run-a'),
         'capture_snapshot': {'entries': [{'request': str(paths[0]), 'sha256': hashlib.sha256(paths[0].read_bytes()).hexdigest()}]}},
        {'run_id': 'run-b', 'model': 'phi4', 'task': 'orders-api-py', 'harness': 'pi',
         'revision': 'r2', 'capture_dirs': [str(first)], 'archive': str(archives / 'missing')},
    ]
    results = tmp_path / 'results.jsonl'
    results.write_text('\n'.join(json.dumps(r) for r in result_rows) + '\n')
    summary = tmp_path / 'summary.json'
    database = tmp_path / 'inventory.sqlite'
    scan(calls, results, archives, summary, database, time.time_ns())
    raw_summary = summary.read_text()
    out = json.loads(raw_summary)
    assert out['request_records'] == 7
    assert out['paired_public_candidates'] == 3
    assert out['distinct_full_context_tools_sha256'] == 1
    assert out['distinct_stored_coordinates'] == 7
    assert out['generation_incomplete'] == 1
    assert out['excluded_or_invalid']['invalid_json'] == 1
    assert out['excluded_or_invalid']['malformed_capture_object'] == 1
    assert out['excluded_or_invalid']['malformed_response_object'] == 1
    assert out['archives']['workspace_exists'] == 1
    assert out['archives']['archive_missing'] == 1
    assert 'RAW_INPUT_CANARY' not in raw_summary and 'PRIVATE_ONLY_CANARY' not in raw_summary
    assert all('gold' not in row for row in out['phase_cell_matrix'])
    with sqlite3.connect(database) as db:
        a = json.loads(db.execute('select meta from captures where path=?', (str(paths[0]),)).fetchone()[0])
        b = json.loads(db.execute('select meta from captures where path=?', (str(paths[1]),)).fetchone()[0])
        c = json.loads(db.execute('select meta from captures where path=?', (str(paths[2]),)).fetchone()[0])
        assert a['join_basis'] == 'snapshot_request_sha256' and a['model'] == 'ornith1.5_9b'
        assert a['language'] == 'Go' and a['revision'] == 'r1'
        assert b['join_status'] == 'ambiguous' and b['model'] == 'UNKNOWN'
        assert c['join_basis'] == 'declared_capture_directory' and c['language'] == 'Go'
        assert c['response']['has_reasoning_channel'] and not c['response']['has_public_answer']
        assert a['input_sha256'] == input_digest(body)
        assert a['message_text_utf8_bytes'] == len(long_text.encode())
        assert db.execute('select request_sha from captures where path=?', (str(paths[0]),)).fetchone()[0] == hashlib.sha256(paths[0].read_bytes()).hexdigest()
        assert 'PRIVATE_ONLY_CANARY' not in '\n'.join(r[0] for r in db.execute('select meta from captures'))
