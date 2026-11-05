"""Run authored TRAIN/DEV project fixtures into an isolated private batch directory.

No test-set import or classifier execution. Candidate labels are proposals.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib
import json
from pathlib import Path
import random
import uuid

from cria import prompts
from suite.gliclass_probe import render_state as render_text
from suite.progress_correctness.heldout_adapter import full_diff, run_check
from suite.progress_dataset import LABELS, render_state


def build(modules: list[str], out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rows, blind, evidence = [], [], []
    rendered_inputs = defaultdict(list)
    for module in modules:
        for group in importlib.import_module(module).GROUPS:
            paths = set(group['seed_files']) | {name for snap in group['snapshots'].values() for name in snap}
            inferred = 'JavaScript' if any(p.endswith('.js') for p in paths) else 'Ruby' if any(p.endswith('.rb') for p in paths) else 'Python'
            language = group.get('language', inferred)
            snapshots = [(label, group['snapshots'][label]) for label in LABELS]
            snapshots += [(variant['label'], variant['files']) for variant in group.get('alternatives', [])]
            for label, snapshot in snapshots:
                identifier = uuid.uuid4().hex
                changes = full_diff(group['seed_files'], snapshot)
                state = render_state(group['requirement'], changes)
                rendered = render_text(state)
                rows.append({'id': identifier, 'split': group.get('split', 'train'), 'family': group['family'],
                             'group': group['group'], 'language': language,
                             'source': 'synthetic-hand-authored', 'label': label,
                             'requirement': group['requirement'], 'evidence': changes})
                blind.append({'id': identifier, 'policy': prompts.load('offline_onejev_progress') + '\n',
                              'state': state, 'rendered_state': rendered, 'options': list(LABELS)})
                evidence.append({'id': identifier, 'split': group.get('split', 'train'), 'family': group['family'],
                                 'group': group['group'], 'label': label, 'seed_files': group['seed_files'],
                                 'snapshot': snapshot, 'rationale': group['rationale'],
                                 'verifiers': group['checks'],
                                 'results': {check['name']: run_check(snapshot, check) for check in group['checks']}})
                rendered_inputs[rendered].append({'id': identifier, 'label': label, 'split': group.get('split', 'train')})
    random.SystemRandom().shuffle(blind)
    for filename, records in [('dataset.jsonl', rows), ('review-blind.jsonl', blind), ('verification.jsonl', evidence)]:
        with (out / filename).open('w', encoding='utf-8') as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
    report = {'rows': len(rows), 'groups': len({(r['split'], r['group']) for r in rows}),
              'families_by_split': {s: len({r['family'] for r in rows if r['split'] == s}) for s in sorted({r['split'] for r in rows})},
              'rows_by_split': dict(Counter(r['split'] for r in rows)),
              'labels_by_split': {s: dict(Counter(r['label'] for r in rows if r['split'] == s)) for s in sorted({r['split'] for r in rows})},
              'languages': dict(Counter(r['language'] for r in rows)),
              'check_results': dict(Counter(f"{r['split']}:{r['label']}:{name}:{result['returncode']}" for r in evidence for name, result in r['results'].items())),
              'exact_duplicates': [items for items in rendered_inputs.values() if len(items) > 1],
              'note': 'Synthetic author proposals; check exits are observations, not label certification.'}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module', action='append', required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(build(a.module, a.out), indent=2))
