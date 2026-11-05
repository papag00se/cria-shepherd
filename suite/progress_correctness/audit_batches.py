"""Collect factual duplicate and structural diagnostics for specified non-TEST batches."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import difflib
import json
from pathlib import Path
import random

from suite.gliclass_probe import render_state as render_text
from suite.progress_dataset import render_state


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch', action='append', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--quarantine', action='append', default=[], help='split/group candidate to leave out, retained in source batch')
    p.add_argument('--compare-pilot', type=Path, help='path to the reviewed TRAIN revision train.jsonl')
    args = p.parse_args()
    rows, packets, evidence = [], {}, []
    for batch in args.batch:
        rows.extend(read_jsonl(batch / 'dataset.jsonl'))
        packets.update({r['id']: r for r in read_jsonl(batch / 'review-blind.jsonl')})
        evidence.extend(read_jsonl(batch / 'verification.jsonl'))
    removed = [r for r in rows if f"{r['split']}/{r['group']}" in args.quarantine]
    rows = [r for r in rows if f"{r['split']}/{r['group']}" not in args.quarantine]
    included = {r['id'] for r in rows}
    evidence = [r for r in evidence if r['id'] in included]
    args.out.mkdir(parents=True, exist_ok=True)
    for split in sorted({r['split'] for r in rows}):
        blind = [packets[r['id']] for r in rows if r['split'] == split]
        random.SystemRandom().shuffle(blind)
        with (args.out / f'{split}-blind.jsonl').open('w', encoding='utf-8') as f:
            for r in blind:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
    inputs = defaultdict(list)
    for r in rows:
        inputs[render_text(render_state(r['requirement'], r['evidence']))].append(
            {'id': r['id'], 'label': r['label'], 'family': r['family'], 'split': r['split']})
    family_splits = defaultdict(set)
    for r in rows:
        family_splits[r['family']].add(r['split'])
    candidates = []
    for i, row in enumerate(rows):
        choices = []
        for other in rows[i+1:]:
            if row['family'] == other['family']:
                continue
            score = difflib.SequenceMatcher(None, row['requirement']+'\n'+row['evidence'],
                                            other['requirement']+'\n'+other['evidence'], autojunk=False).ratio()
            choices.append((score, other))
        if choices:
            score, other = max(choices, key=lambda v: v[0])
            candidates.append({'left': row['id'], 'right': other['id'], 'score': score,
                               'cross_split': row['split'] != other['split']})
    shapes = Counter()
    for row in rows:
        diff = row['evidence']
        label = row['label']
        if not diff:
            shapes[label + ':no-change'] += 1
        if '\n--- a/' in '\n' + diff:
            shapes[label + ':changed-existing-file'] += 1
        if '+++ /dev/null' in diff or 'deleted file:' in diff:
            shapes[label + ':deletion'] += 1
        if '--- /dev/null' in diff or 'empty file added:' in diff:
            shapes[label + ':addition'] += 1
    pilot_candidates = []
    if args.compare_pilot:
        pilot = read_jsonl(args.compare_pilot)
        for row in rows:
            if row['split'] != 'dev':
                continue
            scored = [(difflib.SequenceMatcher(None, row['requirement'] + '\\n' + row['evidence'],
                       other['requirement'] + '\\n' + other['evidence'], autojunk=False).ratio(), other) for other in pilot]
            if scored:
                score, other = max(scored, key=lambda pair: pair[0])
                pilot_candidates.append({'dev_id': row['id'], 'pilot_id': other['id'], 'score': score})
    report = {'rows': len(rows), 'rows_by_split': dict(Counter(r['split'] for r in rows)),
              'groups_by_split': {s: len({r['group'] for r in rows if r['split'] == s}) for s in sorted({r['split'] for r in rows})},
              'families_by_split': {s: len({r['family'] for r in rows if r['split'] == s}) for s in sorted({r['split'] for r in rows})},
              'languages_by_split': {s: dict(Counter(r['language'] for r in rows if r['split'] == s)) for s in sorted({r['split'] for r in rows})},
              'labels_by_split': {s: dict(Counter(r['label'] for r in rows if r['split'] == s)) for s in sorted({r['split'] for r in rows})},
              'checks': sum(len(r['results']) for r in evidence), 'shapes': dict(shapes),
              'quarantined': [{'id': r['id'], 'group': r['group'], 'split': r['split']} for r in removed],
              'exact_duplicates': [v for v in inputs.values() if len(v) > 1],
              'families_in_multiple_splits': {k: sorted(v) for k, v in family_splits.items() if len(v) > 1},
              'similarity_candidates': candidates, 'pilot_similarity_candidates': pilot_candidates,
              'note': 'Similarity is a lexical review candidate, not a semantic verdict; family names alone do not establish independence.'}
    (args.out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'similarity_candidates'}, indent=2))


if __name__ == '__main__':
    main()
