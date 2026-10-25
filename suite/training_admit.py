"""Assemble a local-only, provisional two-question dataset from explicit reviews.

No semantic keyword labeling, model execution, training or GPU access. Disagreement,
UNKNOWN, missing approval and non-active synthetic questions stay quarantined.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from suite.training_prepare import FAMILIES, sha
from suite.training_seed import canonical_input, reject_constant, unique_object, validate_seed

LABEL_ORDER = {'retrospective': ['RETROSPECTIVE', 'PLAN'], 'dictation': ['DESCRIBES', 'DICTATES']}
LABELS = {family: set(labels) for family, labels in LABEL_ORDER.items()}


def load_jsonl(path):
    text = path.read_text(encoding='utf-8')
    if not text.endswith('\n'):
        raise ValueError(f'partial final JSONL record: {path}')
    rows = [json.loads(line, object_pairs_hook=unique_object, parse_constant=reject_constant)
            for line in text[:-1].split('\n')]
    keyed = {r['id']: r for r in rows}
    if len(keyed) != len(rows):
        raise ValueError(f'duplicate IDs: {path}')
    return keyed


def validate_review(case, review):
    if review['id'] != case['id'] or review['family'] != case['family']:
        raise ValueError('review identity mismatch')
    if review['input_sha256'] != sha(canonical_input(case['complete_input'])):
        raise ValueError('review input hash mismatch')
    if review['label'] not in LABELS[case['family']] | {'UNKNOWN'}:
        raise ValueError('invalid question-specific label')
    if review['review_status'] not in {'REVIEWED', 'QUARANTINE'} or not review['reason'].strip():
        raise ValueError('invalid review status/reason')
    text = case['complete_input'][review['support_field']]
    start, end = review['support_start'], review['support_end']
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        raise ValueError('invalid review support bounds')
    if text[start:end] != review['support_text']:
        raise ValueError('review support differs from full input')


def assess_real(case, main, independent, local_use_approved):
    validate_review(case, main)
    validate_review(case, independent)
    reasons = []
    if main['label'] != independent['label']:
        reasons.append('LABEL_DISAGREEMENT')
    if 'UNKNOWN' in (main['label'], independent['label']):
        reasons.append('UNRESOLVED_LABEL')
    if any(r['review_status'] == 'QUARANTINE' for r in (main, independent)):
        reasons.append('REVIEWER_HOLD')
    if any('local_use_approved' in r and r['local_use_approved'] is not True for r in (main, independent)):
        reasons.append('REVIEWER_LOCAL_USE_HOLD')
    if local_use_approved is not True:
        reasons.append('LOCAL_USE_NOT_APPROVED')
    return reasons


def model_text(case):
    field = FAMILIES[case['family']][0]
    value = case['complete_input'][field]
    if not isinstance(value, str) or not value:
        raise ValueError('missing complete native text')
    # Optional null references carry no supplied text. The question is about the
    # entire candidate itself, not the content of an absent external reference.
    if any(v is not None for k, v in case['complete_input'].items() if k != field):
        raise ValueError('unrepresented additional evidence: freeze a new adapter')
    return value


def verify_disjoint(cases):
    owners = {}
    for case in cases:
        nodes = [('group', case['group_id']), ('task', case['task']),
                 ('raw', case['candidate_sha256']),
                 *[('session', v) for v in case['all_sessions']],
                 *[('run', v) for v in case['all_run_ids']]]
        for kind, value in nodes:
            key = kind, value
            if key in owners and owners[key] != case['partition']:
                raise ValueError(f'{kind} crosses partitions: {value}')
            owners[key] = case['partition']


def fit_reason(case, measurements, limit):
    measurement = measurements[case['id']]
    if (measurement['input_sha256'] != sha(canonical_input(case['complete_input']))
            or measurement['model_text_sha256'] != sha(model_text(case).encode('utf-8'))):
        raise ValueError('native measurement input mismatch')
    count = measurement['tokens_with_native_special_tokens']
    if type(count) is not int or count <= 0 or measurement['limit'] != limit:
        raise ValueError('invalid native token count/limit')
    expected = 'FIT' if count <= limit else 'NO_FIT'
    if measurement['fit'] != expected:
        raise ValueError('inconsistent native fit verdict')
    return None if expected == 'FIT' else 'NATIVE_INPUT_TOO_LARGE'


def write_jsonl(path, rows):
    path.write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in rows), encoding='utf-8')
    path.chmod(0o600)


def assemble(root, seed_path, seed_review_path, privacy_path, output, fit_path):
    frozen = json.loads((root / 'partition-before-labels.json').read_text())
    if sha((root / 'candidates.jsonl').read_bytes()) != frozen['candidates_file_sha256']:
        raise ValueError('prelabel candidates changed')
    candidates = load_jsonl(root / 'candidates.jsonl')
    selected = {k: v for k, v in candidates.items() if v['annotation_selected']}
    main = load_jsonl(root / 'reviewer-main.jsonl')
    independent = load_jsonl(root / 'reviewer-independent.jsonl')
    privacy = json.loads(privacy_path.read_text())
    if set(main) != set(selected) or set(independent) != set(selected) or set(privacy['decisions']) != set(selected):
        raise ValueError('incomplete or extraneous review coverage')
    verify_disjoint(list(candidates.values()))
    validate_seed(seed_path)
    seed = load_jsonl(seed_path)
    seed_reviews = load_jsonl(seed_review_path)
    if set(seed) != set(seed_reviews):
        raise ValueError('incomplete seed review coverage')
    native_fit = json.loads(fit_path.read_text())
    measurements = {r['id']: r for r in native_fit['measurements']}
    expected_fit_ids = set(candidates) | {r['id'] for r in seed.values() if r['family'] in FAMILIES}
    if len(measurements) != len(native_fit['measurements']) or set(measurements) != expected_fit_ids:
        raise ValueError('incomplete or duplicate native fit coverage')
    for path in (root / 'candidates.jsonl', seed_path):
        if native_fit['input_files_sha256'][str(path.absolute())] != sha(path.read_bytes()):
            raise ValueError('native fit source file changed')
    exports = {name: [] for name in ('train-real', 'train-synthetic', 'dev-real', 'eval-diagnostic-real')}
    quarantine = []
    for case in candidates.values():
        if not case['annotation_selected']:
            quarantine.append({'id': case['id'], 'family': case['family'], 'reason': case.get('quarantine_reason', 'UNREVIEWED')})
            continue
        decision = privacy['decisions'][case['id']]
        if decision['input_sha256'] != case['input_sha256']:
            raise ValueError('local-use approval input mismatch')
        reasons = assess_real(case, main[case['id']], independent[case['id']], decision['approved'])
        no_fit = fit_reason(case, measurements, native_fit['limit'])
        if no_fit:
            reasons.append(no_fit)
        if reasons:
            quarantine.append({'id': case['id'], 'family': case['family'], 'reason': reasons})
            continue
        split = {'TRAIN': 'train-real', 'DEV': 'dev-real', 'EVAL_DIAGNOSTIC': 'eval-diagnostic-real'}[case['partition']]
        exports[split].append({
            'id': case['id'], 'family': case['family'], 'complete_input': case['complete_input'],
            'model_text': model_text(case), 'input_sha256': case['input_sha256'],
            'label': main[case['id']]['label'], 'label_id': LABEL_ORDER[case['family']].index(main[case['id']]['label']),
            'group_id': case['group_id'],
            'source_kind': 'real_public_candidate', 'fresh_unseen_scenario': False,
            'label_provenance': 'TWO_ISOLATED_ASSISTANT_REVIEWS_AGREE_NOT_HUMAN_GOLD',
        })
    seed_statuses = Counter()
    for case in seed.values():
        review = seed_reviews[case['id']]
        if review['input_sha256'] != sha(canonical_input(case['complete_input'])):
            raise ValueError('seed review input hash mismatch')
        if review['label'] != case['label']:
            raise ValueError('unresolved seed author/reviewer disagreement')
        seed_statuses[review['status']] += 1
        if review['status'] != 'LABEL_REVIEWED_ENGLISH_TRAIN_ONLY' or case['family'] not in FAMILIES:
            quarantine.append({'id': case['id'], 'family': case['family'], 'reason': review['status'] if case['family'] in FAMILIES else ['OUTSIDE_ACTIVE_QUESTIONS', review['status']]})
            continue
        if (case['label'] not in LABELS[case['family']]
                or case['language']['human'] != ['en']
                or case['annotation'].get('admission_blocker')
                or review['local_use_approved'] is not True):
            raise ValueError('seed review contradicts local English-only resolved-label admission scope')
        no_fit = fit_reason(case, measurements, native_fit['limit'])
        if no_fit:
            quarantine.append({'id': case['id'], 'family': case['family'], 'reason': no_fit})
            continue
        exports['train-synthetic'].append({
            'id': case['id'], 'family': case['family'], 'complete_input': case['complete_input'],
            'model_text': model_text(case), 'input_sha256': review['input_sha256'],
            'label': review['label'], 'label_id': LABEL_ORDER[case['family']].index(review['label']),
            'group_id': case['group_id'],
            'source_kind': 'standalone_synthetic_training_only', 'fresh_unseen_scenario': False,
            'label_provenance': 'AUTHOR_PROPOSAL_PLUS_MAIN_BLIND_REVIEW_NOT_HUMAN_GOLD',
        })
    real_raw = {model_text(r) for r in candidates.values()}
    if any(r['model_text'] in real_raw for r in exports['train-synthetic']):
        raise ValueError('synthetic input duplicates a real partition')
    output.mkdir(mode=0o700, exist_ok=False)
    for name, rows in exports.items():
        write_jsonl(output / (name + '.jsonl'), rows)
    write_jsonl(output / 'quarantine.jsonl', quarantine)
    manifest = {
        'schema': 'decision-pilot-reviewed-local-v1',
        'scope': 'retrospective and dictation; experimental labeled data, not production authority',
        'training_permissions': 'NO_TRAINING_OR_GPU_CLEARANCE_GRANTED',
        'fresh_real_evaluation': 'UNAVAILABLE; known archive task-heldout diagnostics only',
        'privacy_scope': 'Main complete-input review approved indicated cases for local diagnostic use only; no external release or universal privacy/legal certification',
        'native_fit': {k: native_fit[k] for k in ('checkpoint', 'revision', 'limit', 'tokenizer_sha256', 'config_sha256')},
        'native_fit_method': native_fit['method'], 'label_order': LABEL_ORDER,
        'frozen_partition_sha256': sha((root / 'partition-before-labels.json').read_bytes()),
        'input_artifacts_sha256': {str(p): sha(p.read_bytes()) for p in [root / 'reviewer-main.jsonl', root / 'reviewer-independent.jsonl', seed_path, seed_review_path, privacy_path, fit_path]},
        'file_sha256': {p.name: sha(p.read_bytes()) for p in sorted(output.glob('*.jsonl'))},
        'counts': {name: len(rows) for name, rows in exports.items()},
        'class_counts': {name: dict(Counter(r['family'] + '/' + r['label'] for r in rows)) for name, rows in exports.items()},
        'seed_review_status_counts': dict(seed_statuses),
        'selected_real_quarantine': sum(1 for r in quarantine if r['id'] in selected),
        'all_distinct_input_quarantine_or_inactive': len(quarantine),
        'limits': ['Only six reviewed scenario families; no population accuracy claim.',
                   'Same-model isolated label reviews can share errors; no human gold certification.',
                   'Unjoined ancestry and missing candidates are ineligible, not semantic UNKNOWN training targets.',
                   'No archive-derived augmentation; no calibration/tuning against diagnostic evaluation.',
                   'All other target questions remain inactive; adding cross-family training requires repartitioning its graph.'],
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--seed', type=Path, default=Path('suite/training_data/synthetic_seed.jsonl'))
    parser.add_argument('--seed-review', type=Path, required=True)
    parser.add_argument('--privacy', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-fit', type=Path, required=True, help='Complete pinned tokenizer-only measurements; never truncate NO_FIT inputs')
    args = parser.parse_args()
    manifest = assemble(args.root, args.seed.absolute(), args.seed_review, args.privacy, args.output, args.native_fit)
    print(json.dumps(manifest['counts'], indent=2))


if __name__ == '__main__':
    main()
