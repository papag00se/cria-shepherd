import copy

import pytest

from suite.training_prepare import sha
from suite.training_seed import canonical_input


def proposal(identity='synthetic-a', batch='train', label='RETROSPECTIVE'):
    family = 'retrospective' if label in {'RETROSPECTIVE', 'PLAN'} else 'dictation'
    field = 'candidate_briefing' if family == 'retrospective' else 'public_directive'
    return {'id': identity, 'group_id': identity, 'family': family,
            'language': 'Go', 'generation_batch': batch, 'parent_real_ids': [],
            'complete_input': {field: 'The diagnostic still reports an unsigned offset. ' + identity},
            'proposed_label': label, 'rationale': 'author-only rationale', 'boundary': 'author-only boundary'}


def review(p, **changes):
    field, text = next(iter(p['complete_input'].items()))
    r = {'id': p['id'], 'family': p['family'], 'input_sha256': sha(canonical_input(p['complete_input'])),
         'label': p['proposed_label'], 'review_status': 'REVIEWED',
         'reason': 'Independent complete-input policy review.', 'local_use_approved': True,
         'support_field': field, 'support_start': 0, 'support_end': len(text), 'support_text': text}
    r.update(changes)
    return r


def admit(ps, a=None, b=None, real=()):
    from suite.gliclass_expand import admit_proposals
    a = a if a is not None else {p['id']: review(p) for p in ps}
    b = b if b is not None else copy.deepcopy(a)
    return admit_proposals(ps, a, b, {'train': 'TRAIN', 'test': 'SYNTHETIC_TEST'}, list(real))


def test_independent_agreement_preserves_reserved_batch_and_native_inputs():
    ps = [proposal('train'), proposal('test', 'test')]
    rows, holds = admit(ps)
    assert not holds
    assert [r['partition'] for r in rows] == ['TRAIN', 'SYNTHETIC_TEST']
    assert [r['complete_input'] for r in rows] == [p['complete_input'] for p in ps]
    assert all(r['task'] == 'synthetic-policy-boundaries' for r in rows)
    assert all('NOT_HUMAN_GOLD' in r['label_provenance'] for r in rows)


@pytest.mark.parametrize('change', [
    {'label': 'UNKNOWN'}, {'label': 'PLAN'}, {'review_status': 'QUARANTINE'},
    {'local_use_approved': False}, {'local_use_approved': None}])
def test_ambiguity_disagreement_and_review_holds_remain_quarantined(change):
    p = proposal()
    rows, holds = admit([p], b={p['id']: review(p, **change)})
    assert rows == []
    assert holds[0]['id'] == p['id'] and holds[0]['reason']


def test_agreeing_reviewers_do_not_silently_relabel_author_disagreement():
    p = proposal()
    other = {p['id']: review(p, label='PLAN')}
    rows, holds = admit([p], other, copy.deepcopy(other))
    assert not rows
    assert 'AUTHOR_REVIEW_DISAGREEMENT' in holds[0]['reason']


def test_blind_review_packet_has_no_target_rationale_ancestry_or_group_cues():
    from suite.gliclass_expand import blind_proposals
    ps = [proposal('a'), proposal('b')]
    for packet in blind_proposals(ps):
        assert set(packet) == {'id', 'family', 'complete_input', 'input_sha256'}
        source = next(p for p in ps if p['id'] == packet['id'])
        assert packet['complete_input'] == source['complete_input']
        assert packet['input_sha256'] == sha(canonical_input(source['complete_input']))


def test_input_hash_or_literal_support_mismatch_stops_admission():
    p = proposal()
    with pytest.raises(ValueError, match='hash mismatch'):
        admit([p], b={p['id']: review(p, input_sha256='altered')})
    with pytest.raises(ValueError, match='support differs'):
        admit([p], b={p['id']: review(p, support_text='fabricated')})


def test_partial_review_coverage_is_not_admission():
    with pytest.raises(ValueError, match='coverage'):
        admit([proposal()], b={})


def test_duplicate_complete_inputs_are_held_not_counted_toward_synthetic_quota():
    a, b = proposal('a'), proposal('b')
    b['complete_input'] = a['complete_input']
    rows, holds = admit([a, b])
    assert not rows and len(holds) == 2
    assert all('DUPLICATE_COMPLETE_INPUT' in h['reason'] for h in holds)


def test_siblings_cannot_cross_generation_partitions():
    a, b = proposal('a'), proposal('b', 'test')
    b['group_id'] = a['group_id']
    with pytest.raises(ValueError, match='sibling group'):
        admit([a, b])


def test_real_derived_synthesis_is_training_only_and_parents_must_be_admitted():
    p = proposal()
    p['parent_real_ids'] = ['real']
    with pytest.raises(ValueError, match='not an admitted'):
        admit([p])
    real = [{'id': 'real', 'partition': 'TRAIN', 'input_sha256': 'other'}]
    assert len(admit([p], real=real)[0]) == 1
    p['generation_batch'] = 'test'
    with pytest.raises(ValueError, match='TRAIN-only'):
        admit([p], real=real)


def test_real_task_metadata_joins_exact_source_without_changing_old_export():
    from suite.gliclass_expand import promote_real_cases
    original = {'id': 'real-go', 'partition': 'DEV', 'task': None, 'label': 'DESCRIBES',
                'complete_input': {'public_directive': 'The compiler reports a float mismatch.'}}
    original['input_sha256'] = sha(canonical_input(original['complete_input']))
    source = dict(original, task='cart-billing-go', programming_language_association='Go')
    promoted = promote_real_cases([original], {'real-go': source})[0]
    assert promoted['task'] == 'cart-billing-go' and promoted['language'] == 'Go'
    assert promoted['partition'] == 'TRAIN' and promoted['previous_partition'] == 'DEV'
    assert promoted['label'] == original['label'] and promoted['complete_input'] == original['complete_input']
    assert original['partition'] == 'DEV' and original['task'] is None
    source['complete_input'] = {'public_directive': 'A different candidate.'}
    with pytest.raises(ValueError, match='identity/input mismatch'):
        promote_real_cases([original], {'real-go': source})
