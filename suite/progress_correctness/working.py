"""Continuously maintain authored TRAIN/DEV examples; rerun only changed fixtures.

Supplied modules own GROUPS in the documented snapshot/check format. Historical
pilot artifacts remain separate; this command never opens held-out test data.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import difflib
import importlib
import json
import os
from pathlib import Path
import random
import statistics
import uuid

from cria import prompts
from suite.gliclass_probe import render_state as render_text
from suite.progress_correctness.heldout_adapter import full_diff, run_check
from suite.progress_dataset import LABELS, render_state


def write_jsonl(path: Path, records: list[dict]) -> None:
    temporary = path.with_suffix(path.suffix + '.new')
    with temporary.open('w', encoding='utf-8') as f:
        for item in records:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    os.replace(temporary, path)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def maintain(modules: list[str], out: Path, exclude: set[str], import_batches: list[Path], pilot_path: Path | None,
             spec_paths: list[Path], author_evidence_paths: list[Path], similarity: bool) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    existing = {r['slot']: r for r in load_jsonl(out / 'evidence.jsonl')}
    for batch in import_batches:
        source_rows = {r['id']: r for r in load_jsonl(batch / 'dataset.jsonl')}
        counts = Counter()
        for record in load_jsonl(batch / 'verification.jsonl'):
            row = source_rows[record['id']]
            base = (row['split'], row['family'], row['group'], row['label'])
            occurrence = counts[base]
            counts[base] += 1
            version = 'primary' if occurrence == 0 else f'alternative-{occurrence-1}'
            slot = json.dumps([*base, version], ensure_ascii=False)
            record['slot'] = slot
            record['state'] = render_state(row['requirement'], row['evidence'])
            record['language'] = row['language']
            record['source'] = row['source']
            existing.setdefault(slot, record)
    groupsets = [(module, importlib.import_module(module).GROUPS) for module in modules]
    groupsets += [(str(path), json.loads(path.read_text(encoding='utf-8'))['groups']) for path in spec_paths]
    author_results = {}
    for path in author_evidence_paths:
        for record in load_jsonl(path):
            author_results[(record['family'], record['group'], record['label'])] = record
    current = {}
    reused_checks = run_checks = 0
    changes = []
    repeated_slots = []
    processed_groups = 0
    for origin, groups in groupsets:
        for group in groups:
            split = group.get('split', 'train')
            if f"{split}/{group['group']}" in exclude:
                continue
            paths = set(group['seed_files']) | {name for snap in group['snapshots'].values() for name in snap}
            language = group.get('language') or next((label for suffix, label in (
                ('.rs','Rust'), ('.go','Go'), ('.js','JavaScript'), ('.rb','Ruby'),
                ('.sql','SQL'), ('.sh','Shell'), ('.c','C'))
                if any(p.endswith(suffix) for p in paths)), 'Python')
            language = {'python':'Python', 'javascript':'JavaScript', 'ruby':'Ruby', 'rust':'Rust', 'shell':'Shell', 'c':'C', 'sql':'SQL', 'go':'Go'}.get(language.lower(), language)
            snapshots = [(label, group['snapshots'][label], 'primary') for label in LABELS]
            snapshots += [(v['label'], v['files'], f'alternative-{i}') for i, v in enumerate(group.get('alternatives', []))]
            for label, snapshot, version in snapshots:
                parts = [split, group['family'], group['group'], label, version]
                slot = json.dumps(parts, ensure_ascii=False)
                if slot in current:
                    repeated_slots.append({'slot':slot, 'origin':origin})
                    index = 1
                    slot = json.dumps([*parts, origin, index], ensure_ascii=False)
                    while slot in current:
                        index += 1
                        slot = json.dumps([*parts, origin, index], ensure_ascii=False)
                old = existing.get(slot)
                state = render_state(group['requirement'], full_diff(group['seed_files'], snapshot))
                if old and old['state'] == state:
                    identifier = old['id']
                else:
                    identifier = uuid.uuid4().hex
                    changes.append({'slot': slot, 'old_id': old['id'] if old else None, 'id': identifier})
                authored = author_results.get((group['family'], group['group'], label)) if version == 'primary' else None
                source = old if old and old['snapshot'] == snapshot and old['verifiers'] == group['checks'] else authored
                same_fixture = source and source['snapshot'] == snapshot and source['verifiers'] == group['checks']
                if same_fixture:
                    results = source['results']
                    reused_checks += len(results)
                else:
                    results = {check['name']: run_check(snapshot, check) for check in group['checks']}
                    run_checks += len(results)
                current[slot] = {'slot':slot, 'id':identifier, 'split':split, 'family':group['family'],
                                 'group':group['group'], 'language':language, 'label':label,
                                 'defect':group.get('defect', 'unspecified'),
                                 'source':'synthetic-hand-authored', 'state':state,
                                 'seed_files':group['seed_files'], 'snapshot':snapshot,
                                 'rationale':group['rationale'], 'verifiers':group['checks'], 'results':results}
            # Periodically retain completed checks without rewriting the whole dataset for every group.
            processed_groups += 1
            if processed_groups % 25 == 0:
                checkpoint = {**existing, **current}
                write_jsonl(out / 'evidence.jsonl', list(checkpoint.values()))
    # Omitted sources are retained; explicit exclusions remove them from this view.
    records = [r for r in {**existing, **current}.values()
               if f"{r['split']}/{r['group']}" not in exclude]
    write_jsonl(out / 'evidence.jsonl', records)
    rows = [{'id':r['id'], 'split':r['split'], 'family':r['family'], 'group':r['group'],
             'language':r['language'], 'label':r['label'], 'source':r['source'], 'defect':r['defect'],
             'requirement':r['state']['requirement'], 'evidence':r['state']['workspace_changes']}
            for r in records]
    write_jsonl(out / 'dataset.jsonl', rows)
    blind = [{'id':r['id'], 'policy':prompts.load('offline_onejev_progress')+'\n', 'state':r['state'],
              'rendered_state':render_text(r['state']), 'options':list(LABELS)} for r in records]
    random.SystemRandom().shuffle(blind)
    write_jsonl(out / 'review-blind.jsonl', blind)
    inputs = defaultdict(list)
    for r in records:
        inputs[render_text(r['state'])].append({'id':r['id'], 'split':r['split'], 'label':r['label'], 'family':r['family']})
    pilot = load_jsonl(pilot_path) if pilot_path else []
    prior = defaultdict(list)
    for r in pilot:
        prior[render_text(render_state(r['requirement'], r['evidence']))].append({'id':r['id'], 'label':r['label']})
    pilot_exact = [{'id':r['id'], 'label':r['label'], 'historical':prior[render_text(r['state'])]}
                   for r in records if render_text(r['state']) in prior]
    family_splits = defaultdict(set)
    for r in records:
        family_splits[r['family']].add(r['split'])
    # One best lexical candidate per DEV input. These are leads, not semantic decisions.
    train = [r for r in records if r['split'] == 'train' and r['label'] == 'DONE']
    prior_report_path = out / 'report.json'
    prior_report = json.loads(prior_report_path.read_text(encoding='utf-8')) if prior_report_path.exists() else {}
    near = [] if similarity else prior_report.get('dev_near_train_candidates', [])
    for r in records:
        if not similarity or r['split'] != 'dev' or r['label'] != 'DONE':
            continue
        options = [(difflib.SequenceMatcher(None, render_text(r['state']), render_text(t['state']), autojunk=False).ratio(), t['id']) for t in train]
        options += [(difflib.SequenceMatcher(None, render_text(r['state']), render_text(render_state(t['requirement'], t['evidence'])), autojunk=False).ratio(), t['id']) for t in pilot if t['label'] == 'DONE']
        if options:
            score, candidate = max(options)
            near.append({'dev_id':r['id'], 'train_candidate_id':candidate, 'score':score})
    report = {'rows_by_split':dict(Counter(r['split'] for r in records)),
              'groups_by_split':{s:len({r['group'] for r in records if r['split']==s}) for s in sorted({r['split'] for r in records})},
              'families_by_split':{s:len({r['family'] for r in records if r['split']==s}) for s in sorted({r['split'] for r in records})},
              'labels_by_split':{s:dict(Counter(r['label'] for r in records if r['split']==s)) for s in sorted({r['split'] for r in records})},
              'languages_by_split':{s:dict(Counter(r['language'] for r in records if r['split']==s)) for s in sorted({r['split'] for r in records})},
              'sources_by_split':{s:dict(Counter(r['source'] for r in records if r['split']==s)) for s in sorted({r['split'] for r in records})},
              'defects_by_split':{s:dict(Counter(r['defect'] for r in records if r['split']==s)) for s in sorted({r['split'] for r in records})},
              'rendered_character_medians':{s:{label:statistics.median([len(render_text(r['state'])) for r in records if r['split']==s and r['label']==label]) for label in LABELS if any(r['split']==s and r['label']==label for r in records)} for s in sorted({r['split'] for r in records})},
              'checks_executed_this_run':run_checks, 'checks_reused_this_run':reused_checks,
              'changed_inputs':changes, 'exact_duplicates':[v for v in inputs.values() if len(v)>1],
              'quarantined_group_ids':sorted(exclude), 'repeated_group_slots':repeated_slots, 'exact_matches_to_pilot':pilot_exact,
              'families_in_multiple_splits':{k:sorted(v) for k,v in family_splits.items() if len(v)>1},
              'dev_near_train_candidates':near, 'similarity_measured_this_run':similarity,
              'similarity_note':'Candidates may be from an earlier update when not measured this run; semantic review is required.',
              'status':'author-labelled synthetic; fixture outcomes and lexical similarity do not certify semantic correctness'}
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    if changes:
        with (out / 'changes.jsonl').open('a', encoding='utf-8') as f:
            for change in changes:
                f.write(json.dumps(change, ensure_ascii=False) + '\n')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module', action='append', default=[])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--exclude', action='append', default=[])
    p.add_argument('--import-batch', action='append', default=[], type=Path, help='reuse prior fixture outputs when initializing')
    p.add_argument('--compare-pilot', type=Path, help='reviewed TRAIN pilot JSONL only')
    p.add_argument('--similarity', action='store_true', help='measure cross-split lexical review candidates')
    p.add_argument('--spec', action='append', default=[], type=Path, help='author-private non-TEST group JSON')
    p.add_argument('--author-evidence', action='append', default=[], type=Path, help='matching previously executed author evidence JSONL')
    a = p.parse_args()
    print(json.dumps(maintain(a.module, a.out, set(a.exclude), a.import_batch, a.compare_pilot,
                              a.spec, a.author_evidence, a.similarity), indent=2))
