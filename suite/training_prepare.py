"""Offline public-candidate extraction and task-group partitioning; never runs models.

The output is an annotation workload, not automatically admitted training data.
Historical teacher replies/private reasoning are deliberately not read or exported.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from suite.training_archive_audit import read_frozen
from suite.training_seed import canonical_input


TASK_PARTITIONS = {
    'feed-pipeline-java': 'TRAIN',
    'orders-api-py': 'TRAIN',
    'shipping-rates-rb': 'TRAIN',
    'cart-billing-go': 'DEV',
    'handles-cli-node': 'EVAL_DIAGNOSTIC',
    'rust-toml-cli': 'EVAL_DIAGNOSTIC',
}
FAMILIES = {'retrospective': ('candidate_briefing', 12), 'dictation': ('public_directive', 8)}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _audit_inputs(custody, database, cutoff_ns, metadata_path):
    metadata_raw = read_frozen(metadata_path, time.time_ns())
    metadata = json.loads(metadata_raw)
    if cutoff_ns != metadata['frozen_cutoff_ns']:
        raise ValueError('cutoff differs from published audit')
    expected = {Path(r['path']).absolute(): r['sha256'] for r in metadata['scratch_artifacts']}
    snapshots = {path: read_frozen(path, time.time_ns()) for path in (custody, database)}
    for path, raw in snapshots.items():
        if sha(raw) != expected.get(path.absolute()):
            raise ValueError(f'audit source fingerprint mismatch: {path}')
    binding = {'metadata_sha256': sha(metadata_raw), 'source_head': metadata['source_head'],
               'custody_sha256': expected[custody.absolute()], 'database_sha256': expected[database.absolute()]}
    return binding, snapshots[custody], snapshots[database]


def verify_audit_sources(custody, database, cutoff_ns, metadata_path):
    return _audit_inputs(custody, database, cutoff_ns, metadata_path)[0]


def source_value(record, cutoff_ns):
    """Read a hash-bound whole source and resolve its literal JSON pointer."""
    raw = read_frozen(Path(record['request']), cutoff_ns)
    if sha(raw) != record['request_sha256']:
        raise ValueError('source request hash changed')
    value = json.loads(raw)
    for token in record['pointer'].split('/')[1:]:
        token = token.replace('~1', '/').replace('~0', '~')
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def extract(record, cutoff_ns):
    value = source_value(record, cutoff_ns)
    if not isinstance(value, str):
        raise ValueError('candidate slot is not text')
    start, end = record['decoded_character_span']
    if not (type(start) is int and type(end) is int and 0 <= start < end <= len(value)):
        raise ValueError('invalid complete-slot bounds')
    candidate = value[start:end]
    a, b = record['utf8_byte_span']
    if (type(a) is not int or type(b) is not int
            or a != len(value[:start].encode('utf-8')) or b != len(value[:end].encode('utf-8'))):
        raise ValueError('candidate byte/span mismatch')
    if value.encode('utf-8')[a:b] != candidate.encode('utf-8') or sha(candidate.encode('utf-8')) != record['candidate_sha256']:
        raise ValueError('candidate byte/span/hash mismatch')
    return candidate


class Groups:
    def __init__(self):
        self.parents = {}

    def find(self, node):
        self.parents.setdefault(node, node)
        if self.parents[node] != node:
            self.parents[node] = self.find(self.parents[node])
        return self.parents[node]

    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parents[max(a, b)] = min(a, b)


def group_rows(rows):
    """Keep full task families plus repeated public inputs/sessions/runs together.

    This is scoped to the selected semantic questions. Unrelated generic policy
    text or membership in a multi-cell campaign is not a shared-example edge.
    """
    groups = Groups()
    for r in rows:
        root = 'task:' + r['task']
        for node in ['session:' + r['session'], 'raw:' + r['candidate_sha256'],
                     *['run:' + run for run in r['run_ids']]]:
            groups.join(root, node)
    for r in rows:
        r['group_id'] = groups.find('task:' + r['task'])
    return rows


def partition_rows(rows):
    group_rows(rows)
    by_group = defaultdict(set)
    for r in rows:
        by_group[r['group_id']].add(TASK_PARTITIONS[r['task']])
    for r in rows:
        if len(by_group[r['group_id']]) != 1:
            r['partition'] = 'QUARANTINE'
            r['quarantine_reason'] = 'CONNECTED_TASKS_CROSS_FROZEN_PARTITIONS'
        else:
            r['partition'] = next(iter(by_group[r['group_id']]))
    return rows


def choose(rows):
    """Freeze a bounded pilot workload before labels; round-robin coder provenance.

    All unselected rows remain explicitly unreviewed, not discarded or relabeled.
    No historical answer, usefulness score or classifier confidence is consulted.
    """
    cells = defaultdict(list)
    for r in rows:
        if r['partition'] != 'QUARANTINE':
            cells[(r['family'], r['task'])].append(r)
    selected = set()
    for (family, task), cell in sorted(cells.items()):
        models = defaultdict(list)
        for r in sorted(cell, key=lambda r: r['id']):
            models[r['coder_model']].append(r)
        limit = FAMILIES[family][1]
        while models and limit:
            for model in sorted(list(models)):
                if not limit:
                    break
                selected.add(models[model].pop(0)['id'])
                limit -= 1
                if not models[model]:
                    del models[model]
    return selected


def prepare(custody_path, database, cutoff_ns, *, review_all=False, audit_metadata=None):
    audit_metadata = audit_metadata or Path(__file__).resolve().parents[1] / 'docs/training/archive-audit-metadata.json'
    audit_binding, custody_bytes, database_bytes = _audit_inputs(custody_path, database, cutoff_ns, audit_metadata)
    custody = json.loads(custody_bytes)
    # Query the verified bytes, not a path that can change after fingerprinting.
    # deserialize is stdlib SQLite (Python >=3.11); no copied archive or writable source.
    db = sqlite3.connect(':memory:')
    db.deserialize(database_bytes)
    db.execute('pragma query_only=on')
    candidates, rejected = [], []
    for r in custody:
        if r['family'] not in FAMILIES:
            continue
        found = db.execute('select paired_public,meta from captures where path=?', (r['request'],)).fetchone()
        reason = None
        if not found:
            reason = 'MISSING_FROZEN_NATIVE_RECORD'
            meta = {}
        else:
            meta = json.loads(found[1])
            if not found[0]:
                reason = 'NO_NONABORTED_NOMINAL_PUBLIC_PAIR'
            elif meta['join_status'] != 'unique_cell' or meta['task'] not in TASK_PARTITIONS:
                reason = 'UNRESOLVED_TASK_LINEAGE'
        if reason:
            rejected.append({'family': r['family'], 'source': r['request'], 'reason': reason})
            continue
        try:
            text = extract(r, cutoff_ns)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            rejected.append({'family': r['family'], 'source': r['request'], 'reason': type(exc).__name__ + ':' + str(exc)})
            continue
        key = FAMILIES[r['family']][0]
        candidates.append({
            'id': r['family'] + '-' + r['candidate_sha256'], 'family': r['family'],
            'complete_input': {key: text}, 'candidate_sha256': r['candidate_sha256'],
            'input_sha256': sha(canonical_input({key: text})), 'task': meta['task'],
            'coder_model': meta['model'], 'programming_language_association': meta['language'],
            'session': r['session'], 'run_ids': r['run_ids'],
            'source': {k: r[k] for k in ('request', 'request_sha256', 'pointer', 'decoded_character_span', 'utf8_byte_span')},
            'label_status': 'UNREVIEWED', 'native_fit': 'NOT_MEASURED',
            'fresh_unseen_scenario': False,
        })
    db.close()
    partition_rows(candidates)
    # Group before dedup, so repeated inputs cannot erase a session/task edge.
    unique = {}
    for row in sorted(candidates, key=lambda r: r['source']['request']):
        if row['id'] not in unique:
            unique[row['id']] = {**row, 'all_sources': [], 'all_run_ids': [], 'all_sessions': [], 'all_coder_models': []}
        keep = unique[row['id']]
        keep['all_sources'].append(row['source'])
        for target, values in [('all_run_ids', row['run_ids']), ('all_sessions', [row['session']]), ('all_coder_models', [row['coder_model']])]:
            keep[target] = sorted(set(keep[target]) | set(values))
    rows = list(unique.values())
    selected = ({r['id'] for r in rows if r['partition'] != 'QUARANTINE'}
                if review_all else choose(rows))
    for row in rows:
        row['annotation_selected'] = row['id'] in selected
        if not row['annotation_selected'] and row['partition'] != 'QUARANTINE':
            row['quarantine_reason'] = 'UNREVIEWED_OUTSIDE_FROZEN_PILOT_WORKLOAD'
    manifest = {
        'schema': 'decision-pilot-prelabel-partition-v1', 'custody_sha256': sha(custody_bytes),
        'cutoff_ns': cutoff_ns, 'task_partitions': TASK_PARTITIONS, 'audit_binding': audit_binding,
        'selection': ('All known-lineage complete unique candidates; no label, score or length selection.' if review_all else 'Before labels; per-task coder round-robin by full candidate hash. Pilot caps retrospective12, dictation8 per task.') + ' Full task families and exact input/session/run components stay together.',
        'scope': 'First two question families only; no cross-family training from other archive questions.',
        'evaluation_status': 'KNOWN_ARCHIVE_TASK_HELDOUT_DIAGNOSTIC_NOT_FRESH_TRAFFIC',
        'independent_lineage_certification': 'NOT_GRANTED',
        'counts': {'eligible_stored_inputs_before_exact_dedup': len(candidates), 'distinct_target_inputs': len(rows), 'selected_for_annotation': len(selected), 'rejected_inputs': len(rejected)},
        'selected_partition_counts': dict(Counter(r['partition'] for r in rows if r['annotation_selected'])),
        'group_partitions': {r['group_id']: r['partition'] for r in rows},
        'rejected': rejected,
    }
    return rows, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--custody', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--cutoff-ns', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--all-known-lineage', action='store_true', help='Review every eligible unique input, not only the initial pilot workload')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows, manifest = prepare(args.custody, args.database, args.cutoff_ns, review_all=args.all_known_lineage)
    (args.output / 'candidates.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    workload = [{'id': r['id'], 'family': r['family'], 'complete_input': r['complete_input']} for r in rows if r['annotation_selected']]
    (args.output / 'blind-workload.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in workload), encoding='utf-8')
    manifest['candidates_file_sha256'] = sha((args.output / 'candidates.jsonl').read_bytes())
    manifest['blind_workload_sha256'] = sha((args.output / 'blind-workload.jsonl').read_bytes())
    (args.output / 'partition-before-labels.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest['counts'], indent=2))


if __name__ == '__main__':
    main()
