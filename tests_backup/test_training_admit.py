import hashlib
import json

import pytest

from suite.training_admit import assess_real, load_jsonl, model_text, validate_review, verify_disjoint


def case():
    return {'id': 'a', 'family': 'dictation', 'complete_input': {'public_directive': 'Inspect the error.'},
            'partition': 'TRAIN', 'group_id': 'group-a', 'task': 'task-a',
            'all_sessions': ['session-a'], 'all_run_ids': ['run-a'], 'candidate_sha256': 'raw-a'}


def review(label='DESCRIBES', status='REVIEWED'):
    return {'id': 'a', 'family': 'dictation', 'label': label, 'review_status': status,
            'input_sha256': hashlib.sha256(b'{"public_directive":"Inspect the error."}').hexdigest(),
            'support_field': 'public_directive', 'support_start': 0, 'support_end': 7,
            'support_text': 'Inspect', 'reason': 'Names the desired investigation without code.'}


def test_disagreement_is_quarantined_not_majority_or_main_override():
    assert assess_real(case(), review(), review('DICTATES'), True) == ['LABEL_DISAGREEMENT']


def test_unknown_never_becomes_a_supervised_negative_even_if_both_agree():
    assert 'UNRESOLVED_LABEL' in assess_real(case(), review('UNKNOWN'), review('UNKNOWN'), True)


def test_privacy_hold_overrides_label_agreement():
    assert assess_real(case(), review(), review(), False) == ['LOCAL_USE_NOT_APPROVED']


def test_exact_input_and_support_are_validated_not_merely_present():
    r = review()
    validate_review(case(), r)
    r['support_text'] = 'different'
    with pytest.raises(ValueError):
        validate_review(case(), r)
    r = review()
    r['input_sha256'] = 'wrong'
    with pytest.raises(ValueError):
        validate_review(case(), r)


def test_all_connected_identifiers_not_just_primary_source_are_disjoint():
    a = case()
    b = {**case(), 'id': 'b', 'partition': 'DEV', 'group_id': 'group-b', 'task': 'task-b',
         'all_sessions': ['another', 'session-a'], 'all_run_ids': ['run-b'], 'candidate_sha256': 'raw-b'}
    with pytest.raises(ValueError, match='session'):
        verify_disjoint([a, b])


def test_explicit_independent_privacy_hold_cannot_be_overridden_by_other_approval():
    independent = {**review(), 'local_use_approved': False}
    assert 'REVIEWER_LOCAL_USE_HOLD' in assess_real(case(), review(), independent, True)


def test_jsonl_keeps_unicode_line_separators_inside_full_input(tmp_path):
    p = tmp_path / 'review.jsonl'
    p.write_text(json.dumps({'id': 'a', 'text': 'é\u2028whole\u0085text'}, ensure_ascii=False) + '\n')
    assert load_jsonl(p)['a']['text'] == 'é\u2028whole\u0085text'


def test_jsonl_rejects_duplicate_keys_and_partial_record(tmp_path):
    p = tmp_path / 'review.jsonl'
    p.write_text('{"id":"a","id":"b"}\n')
    with pytest.raises(ValueError, match='duplicate'):
        load_jsonl(p)
    p.write_text('{"id":"a"}')
    with pytest.raises(ValueError, match='partial'):
        load_jsonl(p)


def test_native_no_fit_is_not_clipped_or_silently_admitted():
    from suite.training_admit import fit_reason
    a = case()
    measurement = {'id': a['id'], 'input_sha256': review()['input_sha256'],
                   'model_text_sha256': hashlib.sha256(b'Inspect the error.').hexdigest(),
                   'tokens_with_native_special_tokens': 17, 'limit': 16, 'fit': 'NO_FIT'}
    assert fit_reason(a, {'a': measurement}, 16) == 'NATIVE_INPUT_TOO_LARGE'
    assert a['complete_input']['public_directive'] == 'Inspect the error.'
    measurement['fit'] = 'FIT'
    with pytest.raises(ValueError, match='inconsistent'):
        fit_reason(a, {'a': measurement}, 16)


def test_complete_assembly_exports_only_native_inputs_and_resolved_labels(tmp_path):
    from suite.training_admit import assemble, load_jsonl
    from tests.test_training_seed import proposal
    from suite.training_seed import canonical_input

    def store(path, rows):
        path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))

    real = {**case(), 'annotation_selected': True, 'input_sha256': review()['input_sha256']}
    store(tmp_path / 'candidates.jsonl', [real])
    (tmp_path / 'partition-before-labels.json').write_text(json.dumps({
        'candidates_file_sha256': hashlib.sha256((tmp_path / 'candidates.jsonl').read_bytes()).hexdigest()}))
    store(tmp_path / 'reviewer-main.jsonl', [review()])
    store(tmp_path / 'reviewer-independent.jsonl', [review()])
    privacy = tmp_path / 'privacy.json'
    privacy.write_text(json.dumps({'decisions': {'a': {'input_sha256': real['input_sha256'], 'approved': True}}}))
    seed = proposal()
    text = 'Observe boundary behavior.'
    seed.update(id='seed-a', family='dictation', policy_id='dictation-research-v1',
                complete_input={'public_directive': text}, label='DESCRIBES',
                support_spans=[{'field': '/public_directive', 'start': 0, 'end': len(text),
                                'text': text, 'unit': 'unicode_codepoints', 'bounds': 'zero_based_half_open'}])
    seed_path = tmp_path / 'seed.jsonl'
    store(seed_path, [seed])
    seed_review_path = tmp_path / 'seed-review.jsonl'
    store(seed_review_path, [{'id': seed['id'], 'input_sha256': hashlib.sha256(canonical_input(seed['complete_input'])).hexdigest(),
                              'label': 'DESCRIBES', 'status': 'LABEL_REVIEWED_ENGLISH_TRAIN_ONLY', 'local_use_approved': True}])
    fit_path = tmp_path / 'fit.json'
    fit_path.write_text(json.dumps({'checkpoint': 'fixture', 'revision': 'fixture', 'limit': 32,
        'tokenizer_sha256': 'fixture', 'config_sha256': 'fixture', 'method': 'fake tokenizer in test only',
        'input_files_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (tmp_path / 'candidates.jsonl', seed_path)},
        'measurements': [{'id': r['id'], 'input_sha256': hashlib.sha256(canonical_input(r['complete_input'])).hexdigest(),
                          'model_text_sha256': hashlib.sha256(r['complete_input']['public_directive'].encode()).hexdigest(),
                          'tokens_with_native_special_tokens': 5, 'limit': 32, 'fit': 'FIT'} for r in (real, seed)]}))
    output = tmp_path / 'assembled'
    manifest = assemble(tmp_path, seed_path, seed_review_path, privacy, output, fit_path)
    assert manifest['counts']['train-real'] == manifest['counts']['train-synthetic'] == 1
    exported = load_jsonl(output / 'train-real.jsonl')['a']
    assert exported['model_text'] == real['complete_input']['public_directive']
    assert exported['label_id'] == 0
    assert not {'reason', 'support_text', 'privacy_reason'} & set(exported)
    # A reviewer flag cannot promote an untranslated proposal into this English-only package.
    seed['language']['human'] = ['fr']
    store(seed_path, [seed])
    fit = json.loads(fit_path.read_text())
    fit['input_files_sha256'][str(seed_path)] = hashlib.sha256(seed_path.read_bytes()).hexdigest()
    fit_path.write_text(json.dumps(fit))
    with pytest.raises(ValueError, match='English-only'):
        assemble(tmp_path, seed_path, seed_review_path, privacy, tmp_path / 'forbidden', fit_path)


def test_native_text_preserves_complete_unicode_and_rejects_unrepresented_evidence():
    a = case()
    a['complete_input'] = {'public_directive': '整段 é\nNo clipping.'}
    assert model_text(a) == '整段 é\nNo clipping.'
    a['complete_input']['attachment'] = 'actual extra evidence'
    with pytest.raises(ValueError, match='unrepresented'):
        model_text(a)
