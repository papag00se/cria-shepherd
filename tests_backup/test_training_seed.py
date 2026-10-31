"""Offline structural checks must reject leaks and broken custody, not invent gold."""
import copy
import json
from pathlib import Path

import pytest

from suite.training_seed import SeedValidationError, validate_seed


def proposal():
    text = 'same documented API'
    return {
        'schema_version': 'synthetic-decision-seed-v1', 'id': 'fixture-base',
        'family': 'searchdirection', 'policy_id': 'searchdirection-research-v1',
        'complete_input': {'previous_query': 'Go library lookup API',
                           'proposed_query': 'lookup API Go library',
                           'question_context': text, 'previous_results_available': True},
        'label': 'SAME_HUNT',
        'support_spans': [{'field': '/question_context', 'start': 0, 'end': len(text),
                          'text': text, 'unit': 'unicode_codepoints', 'bounds': 'zero_based_half_open'}],
        'language': {'programming': ['Go'], 'human': ['en']},
        'task_domain': 'fixture', 'harness_style': 'request', 'group_id': 'fixture-group',
        'variation_type': 'base', 'contrast': {'parent_id': None, 'expected_relation': 'base'},
        'source_kind': 'synthetic',
        'origin': {'method': 'standalone_authored_for_review', 'authoring_batch': 'fixture',
                   'archive_split_lineage': None, 'archive_parent_ids': [],
                   'evaluation_cases_used_as_generation_inputs': False,
                   'author_previously_exposed_to_research_evaluation': True,
                   'semantic_independence_from_prior_research_not_claimed': True},
        'research_refs': ['checklist2020'], 'label_status': 'proposed_independentreview_pending',
        'partition': 'UNASSIGNED_QUARANTINE', 'partition_constraint': 'TRAIN_ONLY_IF_REVIEWED_AND_ADMITTED',
        'fit_status': 'NOT_MEASURED',
        'annotation': {'review_rationale': 'Fixture only, not semantic gold.',
                       'target_fields': {}, 'evidence_scope': 'Complete bounded case.'},
    }


def store(tmp_path, rows):
    path = tmp_path / 'seed.jsonl'
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    return path


def test_real_seed_passes_structural_checks_without_becoming_gold():
    path = Path(__file__).resolve().parents[1] / 'suite/training_data/synthetic_seed.jsonl'
    result = validate_seed(path)
    assert result['records'] > 0
    assert result['semantic_review'] == 'NOT_CERTIFIED'
    assert result['training_admission'] == 'NOT_GRANTED'
    assert result['native_fit'] == 'NOT_MEASURED'


def test_unicode_span_uses_codepoints_not_encoded_bytes(tmp_path):
    r = proposal()
    r['complete_input']['question_context'] = 'é查 API'
    r['support_spans'][0].update(start=1, end=2, text='查')
    validate_seed(store(tmp_path, [r]))
    r['support_spans'][0].update(start=2, end=5)
    with pytest.raises(SeedValidationError, match='span'):
        validate_seed(store(tmp_path, [r]))


def test_whole_long_unicode_input_survives_and_is_not_mistaken_for_jsonl_lines(tmp_path):
    r = proposal()
    r['complete_input']['question_context'] = '查\u2028é' * 70000
    r['support_spans'][0].update(start=0, end=3, text='查\u2028é')
    path = store(tmp_path, [r])
    original = path.read_bytes()
    report = validate_seed(path)
    assert report['source_bytes'] == len(original)
    assert report['native_fit'] == 'NOT_MEASURED'
    assert path.read_bytes() == original


def test_annotation_or_answer_cannot_leak_into_declared_model_fields(tmp_path):
    r = proposal()
    r['complete_input']['review_rationale'] = 'The answer is SAME_HUNT'
    with pytest.raises(SeedValidationError, match='input keys'):
        validate_seed(store(tmp_path, [r]))


@pytest.mark.parametrize('field,value', [('label_status', 'gold'), ('partition', 'TEST'),
                                        ('fit_status', 'FITS'), ('source_kind', 'real')])
def test_structure_cannot_promote_proposals_or_claim_unmeasured_fit(tmp_path, field, value):
    r = proposal()
    r[field] = value
    with pytest.raises(SeedValidationError, match=field):
        validate_seed(store(tmp_path, [r]))


def test_claimed_eval_generation_or_invented_archive_ancestry_rejected(tmp_path):
    for key, value in [('evaluation_cases_used_as_generation_inputs', True),
                       ('archive_parent_ids', ['held-out-case']), ('archive_split_lineage', 'TRAIN')]:
        r = proposal()
        r['origin'][key] = value
        with pytest.raises(SeedValidationError, match='origin'):
            validate_seed(store(tmp_path, [r]))


def test_missing_foreign_parent_and_false_relations_are_rejected(tmp_path):
    a = proposal()
    b = copy.deepcopy(a)
    b.update(id='fixture-child', variation_type='paraphrase')
    b['complete_input']['proposed_query'] = 'the same lookup API'
    b['contrast'] = {'parent_id': 'missing', 'expected_relation': 'label_invariant'}
    with pytest.raises(SeedValidationError, match='parent'):
        validate_seed(store(tmp_path, [a, b]))
    b['contrast']['parent_id'] = a['id']
    b['group_id'] = 'foreign'
    with pytest.raises(SeedValidationError, match='group'):
        validate_seed(store(tmp_path, [a, b]))
    b['group_id'] = a['group_id']
    b['contrast']['expected_relation'] = 'label_changing'
    with pytest.raises(SeedValidationError, match='relation'):
        validate_seed(store(tmp_path, [a, b]))
    b['contrast']['expected_relation'] = 'label_invariant'
    assert validate_seed(store(tmp_path, [a, b]))['records'] == 2


def test_ancestry_cycle_is_rejected_even_when_each_relation_matches(tmp_path):
    a = proposal()
    b = copy.deepcopy(a)
    b['id'] = 'fixture-child'
    b['complete_input']['proposed_query'] = 'a different wording of lookup API'
    a['contrast'] = {'parent_id': b['id'], 'expected_relation': 'label_invariant'}
    b['contrast'] = {'parent_id': a['id'], 'expected_relation': 'label_invariant'}
    with pytest.raises(SeedValidationError, match='cyclic'):
        validate_seed(store(tmp_path, [a, b]))


def test_duplicate_ids_and_identical_family_inputs_are_not_independent_rows(tmp_path):
    a = proposal()
    b = copy.deepcopy(a)
    with pytest.raises(SeedValidationError, match='duplicate id'):
        validate_seed(store(tmp_path, [a, b]))
    b['id'] = 'copy'
    with pytest.raises(SeedValidationError, match='duplicate.*input'):
        validate_seed(store(tmp_path, [a, b]))


def test_positive_output_quote_must_be_literal_original_task_and_subject(tmp_path):
    r = proposal()
    r.update(family='requiredoutput', policy_id='requiredoutput-research-v1', label='REQUIRED_OUTPUT')
    r['complete_input'] = {'original_task': 'Write out.txt.', 'subject': 'out.txt'}
    r['support_spans'] = [{'field': '/original_task', 'start': 0, 'end': 13, 'text': 'Write out.txt',
                           'unit': 'unicode_codepoints', 'bounds': 'zero_based_half_open'}]
    validate_seed(store(tmp_path, [r]))
    r['complete_input']['subject'] = 'else.txt'
    with pytest.raises(SeedValidationError, match='subject'):
        validate_seed(store(tmp_path, [r]))


def test_exact_form_booleans_are_not_byte_counts_and_need_supported_target(tmp_path):
    r = proposal()
    r.update(family='exactform', policy_id='exactform-research-v1', label='EXACT_FILE_FORM')
    r['complete_input'] = {'original_task': 'Write a.dat with exactly 4 bytes.', 'subject': 'a.dat'}
    r['support_spans'] = [{'field': '/original_task', 'start': 0, 'end': len('Write a.dat with exactly 4 bytes'),
                          'text': 'Write a.dat with exactly 4 bytes',
                          'unit': 'unicode_codepoints', 'bounds': 'zero_based_half_open'}]
    r['annotation']['target_fields'] = {'bytes': 4, 'ends_with_line_break': None}
    validate_seed(store(tmp_path, [r]))
    r['annotation']['target_fields']['bytes'] = True
    with pytest.raises(SeedValidationError, match='target'):
        validate_seed(store(tmp_path, [r]))


def test_no_partial_json_duplicate_keys_or_nonfinite_numbers(tmp_path):
    path = store(tmp_path, [proposal()])
    text = path.read_text()
    for bad in [text.rstrip('\n'), '{"id":"a","id":"b"}\n', '{"x":NaN}\n', text + '\n']:
        path.write_text(bad)
        with pytest.raises(SeedValidationError):
            validate_seed(path)
