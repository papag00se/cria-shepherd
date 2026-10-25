"""Frozen input authority, not a historical sample count, owns a fit's scope."""
import json

import pytest

from suite.onejev_probe import file_sha


def freeze(root, train, held):
    for name, rows in [('train-cases.json', train), ('held-cases.json', held)]:
        (root / name).write_text(json.dumps(rows))
    contract = {'train_count': len(train), 'held_count': len(held),
                'input_sha256': {str(root / name): file_sha(root / name)
                                 for name in ['train-cases.json', 'held-cases.json']}}
    (root / 'contract.json').write_text(json.dumps(contract))
    return contract


def row(identity, partition='TRAIN', group=None, digest=None):
    return {'id': identity, 'partition': partition, 'group_id': group or identity,
            'input_sha256': digest or identity}


def test_expanded_frozen_train_and_reserved_test_are_admitted_without_fixed_514_limit(tmp_path):
    from suite.gliclass_probe import load_frozen_cohorts
    train = [row(f'real-{i}') for i in range(644)] + [row(f'synthetic-{i}') for i in range(110)]
    held = [row('new-independent-scenario', 'SYNTHETIC_TEST')]
    contract = freeze(tmp_path, train, held)
    assert load_frozen_cohorts(tmp_path) == (contract, train, held)


@pytest.mark.parametrize('violation', ['id', 'group', 'input', 'partition', 'duplicate'])
def test_training_exposure_cannot_masquerade_as_held_evaluation(tmp_path, violation):
    from suite.gliclass_probe import load_frozen_cohorts
    train, held = [row('real')], [row('held', 'SYNTHETIC_TEST')]
    if violation == 'id':
        held[0]['id'] = 'real'
    elif violation == 'group':
        held[0]['group_id'] = 'real'
    elif violation == 'input':
        held[0]['input_sha256'] = 'real'
    elif violation == 'partition':
        held[0]['partition'] = 'TRAIN'
    else:
        train.append(dict(train[0]))
    freeze(tmp_path, train, held)
    with pytest.raises(ValueError, match='cohort'):
        load_frozen_cohorts(tmp_path)


@pytest.mark.parametrize('mutation', ['bytes', 'count'])
def test_declared_cohort_is_frozen_not_recounted_after_mutation(tmp_path, mutation):
    from suite.gliclass_probe import load_frozen_cohorts
    contract = freeze(tmp_path, [row('real')], [row('held', 'SYNTHETIC_TEST')])
    if mutation == 'bytes':
        (tmp_path / 'train-cases.json').write_text(json.dumps([row('replacement')]))
    else:
        contract['train_count'] += 1
        (tmp_path / 'contract.json').write_text(json.dumps(contract))
    with pytest.raises(ValueError, match='changed|cohort'):
        load_frozen_cohorts(tmp_path)
