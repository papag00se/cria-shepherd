import copy
import json
import time

import pytest

from suite.training_evaluation import exclusion_index, screen
from suite.training_prepare import sha
from suite.training_seed import canonical_input


def fixture(tmp_path):
    raw = json.dumps({'candidate': 'Inspect the real error.', 'task': 'Build a tide sensor dashboard.', 'captured_at_ns': 30}).encode()
    path = tmp_path / 'source.json'
    path.write_bytes(raw)
    source = {'request': str(path), 'request_sha256': sha(raw)}
    text = 'Inspect the real error.'
    case = {'id': 'new', 'family': 'dictation', 'task': 'tide-dashboard', 'group_id': 'tides',
            'all_sessions': ['new-session'], 'all_run_ids': ['new-run'], 'ancestor_tasks': [],
            'ancestry_complete': True, 'source_kind': 'real_public_candidate',
            'complete_input': {'public_directive': text}, 'input_sha256': sha(canonical_input({'public_directive': text})),
            'candidate_sha256': sha(text.encode()), 'source': {**source, 'pointer': '/candidate', 'decoded_character_span': [0, len(text)], 'utf8_byte_span': [0, len(text)]},
            'task_source': {**source, 'pointer': '/task'}, 'capture_event_source': {**source, 'pointer': '/captured_at_ns'}}
    exclusions = exclusion_index([], [])
    reservation = {'task': case['task'], 'group_id': case['group_id'], 'reserved_at_ns': 20,
                   'task_sha256': sha(b'Build a tide sensor dashboard.'), 'exclusions_sha256': sha(canonical_input(exclusions)),
                   'partition': 'EVAL_PROSPECTIVE_SEALED', 'novelty_reviews': [
                       {'reviewer': who, 'decision': 'INDEPENDENT_SCENARIO', 'reason': 'Complete task and ancestor comparison, not an exact-hash inference.'}
                       for who in ('reviewer-a', 'reviewer-b')]}
    contract = {'collection_start_ns': 10, 'exclusions_sha256': sha(canonical_input(exclusions)),
                'reservations': {case['task']: sha(canonical_input(reservation))}}
    return case, reservation, contract, exclusions


def test_new_complete_case_is_only_intake_eligible_not_gold(tmp_path):
    c, r, k, x = fixture(tmp_path)
    assert screen(c, r, k, x, time.time_ns()) == []
    assert 'label' not in c and 'fresh_unseen_scenario' not in c


@pytest.mark.parametrize('kind,value', [('task', 'old-task'), ('session', 'old-session'), ('run', 'old-run'), ('group', 'old-group')])
def test_ancestor_edges_block_freshness_even_with_a_new_case_name(tmp_path, kind, value):
    c, r, k, x = fixture(tmp_path)
    x[kind].append(value)
    k['exclusions_sha256'] = sha(canonical_input(x))
    r['exclusions_sha256'] = sha(canonical_input(x))
    k['reservations'][c['task']] = sha(canonical_input(r))
    if kind == 'task':
        c['ancestor_tasks'].append(value)
    elif kind == 'session':
        c['all_sessions'].append(value)
    elif kind == 'run':
        c['all_run_ids'].append(value)
    else:
        c['group_id'] = r['group_id'] = value
        k['reservations'][c['task']] = sha(canonical_input(r))
    assert 'KNOWN_ANCESTRY_OR_EXACT_INPUT' in screen(c, r, k, x, time.time_ns())


def test_relabelled_archive_text_is_not_fresh_and_quarantine_sources_are_excluded(tmp_path):
    c, r, k, _ = fixture(tmp_path)
    old = {**copy.deepcopy(c), 'task': 'old', 'partition': 'QUARANTINE'}
    x = exclusion_index([old], [])
    k['exclusions_sha256'] = sha(canonical_input(x))
    r['exclusions_sha256'] = sha(canonical_input(x))
    k['reservations'][c['task']] = sha(canonical_input(r))
    assert 'KNOWN_ANCESTRY_OR_EXACT_INPUT' in screen(c, r, k, x, time.time_ns())


def test_renaming_task_metadata_does_not_make_the_same_complete_task_new(tmp_path):
    c, r, k, x = fixture(tmp_path)
    x = exclusion_index([], [], task_texts=['Build a tide sensor dashboard.'])
    k['exclusions_sha256'] = sha(canonical_input(x))
    r['exclusions_sha256'] = sha(canonical_input(x))
    k['reservations'][c['task']] = sha(canonical_input(r))
    assert 'KNOWN_ANCESTRY_OR_EXACT_INPUT' in screen(c, r, k, x, time.time_ns())


def test_a_reservation_cannot_replace_the_master_contract_exclusions(tmp_path):
    c, r, k, x = fixture(tmp_path)
    k['exclusions_sha256'] = sha(canonical_input({**x, 'task': ['known-task']}))
    # The reservation and supplied index still agree; the MASTER freeze does not.
    with pytest.raises(ValueError, match='binding'):
        screen(c, r, k, x, time.time_ns())


def test_source_timestamp_and_precollection_reservation_are_required(tmp_path):
    c, r, k, x = fixture(tmp_path)
    r['reserved_at_ns'] = 31
    k['reservations'][c['task']] = sha(canonical_input(r))
    assert 'NOT_PROSPECTIVE_AFTER_RESERVATION' in screen(c, r, k, x, time.time_ns())
    c, r, k, x = fixture(tmp_path)
    c['capture_event_source']['request_sha256'] = 'wrong'
    with pytest.raises(ValueError, match='hash'):
        screen(c, r, k, x, time.time_ns())


def test_unknown_lineage_single_reviewer_or_label_exposure_never_passes(tmp_path):
    c, r, k, x = fixture(tmp_path)
    c['ancestry_complete'] = False
    assert 'UNRESOLVED_ANCESTRY' in screen(c, r, k, x, time.time_ns())
    c, r, k, x = fixture(tmp_path)
    r['novelty_reviews'][1]['reviewer'] = 'reviewer-a'
    k['reservations'][c['task']] = sha(canonical_input(r))
    assert 'NOVELTY_NOT_INDEPENDENTLY_REVIEWED' in screen(c, r, k, x, time.time_ns())
    c['label'] = 'DESCRIBES'
    with pytest.raises(ValueError, match='blinded'):
        screen(c, r, k, x, time.time_ns())


@pytest.mark.parametrize('field', ['all_sessions', 'all_run_ids', 'ancestor_tasks'])
def test_blank_identifiers_are_unknown_lineage_not_new_ancestry(tmp_path, field):
    c, r, k, x = fixture(tmp_path)
    c[field] = ['']
    with pytest.raises(ValueError, match='lineage'):
        screen(c, r, k, x, time.time_ns())


@pytest.mark.parametrize('field', ['teacher_output', 'assistant_reasoning', 'unreviewed_note'])
def test_unrecognized_annotation_channels_cannot_bypass_blind_intake(tmp_path, field):
    c, r, k, x = fixture(tmp_path)
    c[field] = 'Hidden annotation must never reach a blinded reviewer.'
    with pytest.raises(ValueError, match='blinded'):
        screen(c, r, k, x, time.time_ns())


def test_a_valid_hash_for_a_selected_passage_is_not_a_complete_native_candidate(tmp_path):
    c, r, k, x = fixture(tmp_path)
    text = 'Inspect'
    c['complete_input'] = {'public_directive': text}
    c['input_sha256'] = sha(canonical_input(c['complete_input']))
    c['candidate_sha256'] = sha(text.encode())
    c['source']['decoded_character_span'] = [0, len(text)]
    c['source']['utf8_byte_span'] = [0, len(text)]
    with pytest.raises(ValueError, match='whole native candidate slot'):
        screen(c, r, k, x, time.time_ns())


def test_unknown_extra_input_cannot_be_dropped_from_a_complete_packet(tmp_path):
    c, r, k, x = fixture(tmp_path)
    c['complete_input']['additional_evidence'] = 'Must not disappear.'
    with pytest.raises(ValueError, match='additional evidence'):
        screen(c, r, k, x, time.time_ns())
