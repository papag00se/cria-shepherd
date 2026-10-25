"""Admit new synthetic proposals by independent, hash-bound reviews.

This does not label text, resolve disagreement, relax prior quarantines, or run a
model. Generation batches are assigned TRAIN or TEST before authoring. Two blind
reviews plus the author's original label must agree; related groups stay whole.
"""
from __future__ import annotations

from collections import Counter

from suite.training_admit import LABEL_ORDER, assess_real, model_text
from suite.training_prepare import sha
from suite.training_seed import canonical_input


def promote_real_cases(rows, candidates):
    """Join authoritative task metadata without altering old exports or labels."""
    promoted = []
    for row in rows:
        source = candidates[row['id']]
        digest = sha(canonical_input(row['complete_input']))
        if (source['complete_input'] != row['complete_input']
                or source['input_sha256'] != digest or row['input_sha256'] != digest):
            raise ValueError('real source identity/input mismatch')
        if not source['task'] or not source['programming_language_association']:
            raise ValueError('unresolved real task/language metadata')
        promoted.append(dict(row, partition='TRAIN', previous_partition=row['partition'],
                             task=source['task'], language=source['programming_language_association']))
    return promoted


def blind_id(identity):
    return 'blind-' + sha(identity.encode('utf-8'))


def unblind_reviews(proposals, reviews):
    """Restore source identities only AFTER the independent review is complete."""
    mapping = {blind_id(p['id']): p['id'] for p in proposals}
    if len(mapping) != len(proposals) or set(mapping) != set(reviews):
        raise ValueError('incomplete or extraneous blind review coverage')
    if any(identity != r['id'] for identity, r in reviews.items()):
        raise ValueError('blind review identity mismatch')
    return {mapping[identity]: dict(r, id=mapping[identity]) for identity, r in reviews.items()}


def blind_proposals(proposals):
    """Keep labels, rationales, ancestry and proposal ordering out of review."""
    return sorted(({'id': blind_id(p['id']), 'family': p['family'],
                    'complete_input': p['complete_input'],
                    'input_sha256': sha(canonical_input(p['complete_input']))}
                   for p in proposals), key=lambda p: sha(p['id'].encode()))


def admit_proposals(proposals, first, second, batch_partitions, real_cases, *, excluded_input_hashes=()):
    """Return canonical fit rows and held proposals; never majority-vote a hold.

    first/second are keyed review records in training_admit.validate_review's
    schema. Their semantic decisions must have been produced independently.
    Partition assignments and batch identities are explicit producer metadata,
    never inferred from words inside evidence or from a review's label.
    """
    ids = [p['id'] for p in proposals]
    if len(ids) != len(set(ids)) or set(first) != set(ids) or set(second) != set(ids):
        raise ValueError('duplicate proposals or incomplete independent review coverage')
    if any(v not in {'TRAIN', 'SYNTHETIC_TEST'} for v in batch_partitions.values()):
        raise ValueError('invalid preassigned generation batch partition')
    real = {r['id']: r for r in real_cases}
    if len(real) != len(real_cases) or any(r['partition'] != 'TRAIN' for r in real.values()):
        raise ValueError('real parents must be uniquely admitted TRAIN cases')
    group_owners = {}
    digests = Counter(sha(canonical_input(p['complete_input'])) for p in proposals)
    real_digests = {r['input_sha256'] for r in real.values()}
    excluded = set(excluded_input_hashes)
    admitted, quarantine = [], []
    for proposal in proposals:
        identity, family = proposal['id'], proposal['family']
        label = proposal['proposed_label']
        if label not in LABEL_ORDER[family]:
            raise ValueError('invalid author question-specific label')
        text = model_text(proposal)
        expected_field = 'candidate_briefing' if family == 'retrospective' else 'public_directive'
        if set(proposal['complete_input']) != {expected_field}:
            raise ValueError('unqualified synthetic evidence shape')
        partition = batch_partitions[proposal['generation_batch']]
        group = proposal['group_id']
        if group in group_owners and group_owners[group] != partition:
            raise ValueError('synthetic sibling group crosses partitions')
        group_owners[group] = partition
        parents = proposal['parent_real_ids']
        if not isinstance(parents, list) or any(p not in real for p in parents):
            raise ValueError('synthetic parent is not an admitted real TRAIN identity')
        if partition != 'TRAIN' and parents:
            raise ValueError('real-derived synthesis must remain TRAIN-only')
        digest = sha(canonical_input(proposal['complete_input']))
        reasons = assess_real(proposal, first[identity], second[identity], True)
        if any(r.get('local_use_approved') is not True for r in [first[identity], second[identity]]):
            reasons.append('SYNTHETIC_LOCAL_USE_NOT_APPROVED')
        if any(r['label'] != label for r in [first[identity], second[identity]]):
            reasons.append('AUTHOR_REVIEW_DISAGREEMENT')
        if digests[digest] > 1 or digest in real_digests:
            reasons.append('DUPLICATE_COMPLETE_INPUT')
        if digest in excluded:
            reasons.append('EXCLUDED_EXISTING_INPUT')
        if reasons:
            quarantine.append({'id': identity, 'family': family, 'input_sha256': digest,
                               'reason': reasons, 'intended_partition': partition})
            continue
        admitted.append({'id': identity, 'family': family, 'complete_input': proposal['complete_input'],
            'model_text': text, 'input_sha256': digest, 'group_id': group,
            'label': label, 'label_id': LABEL_ORDER[family].index(label), 'partition': partition,
            'task': 'synthetic-policy-boundaries', 'language': proposal['language'],
            'source_kind': 'independently_reviewed_synthetic',
            'label_provenance': 'AUTHOR_PLUS_TWO_BLIND_ISOLATED_ASSISTANT_REVIEWS_NOT_HUMAN_GOLD',
            'generation_batch': proposal['generation_batch'], 'parent_real_ids': parents,
            'fresh_unseen_scenario': False})
    return admitted, quarantine
