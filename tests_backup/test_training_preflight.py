import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from suite.training_preflight import require_preflight, validate_native_result, optimization_fingerprint
from suite.training_prepare import sha


def passed_result():
    return {**{name: True for name in ('optimizer_membership_exact', 'decoding_correct',
             'routing_gradients_correct', 'tiny_final_overfit_all_eight', 'all_existing_quarantines_unchanged')},
            'arms': [{'epochs': 200, 'all_groups_update_after_warmup': True, 'checks': [{'step': 200, 'summaries': {
                family: {'count': 4, 'risk_coverage': {'0.5': {'disagreements_with_reviewed_target': 0}}}
                for family in ('retrospective', 'dictation')}}]}]}


def test_matrix_entrypoint_rejects_missing_preflight_before_loading_inputs():
    from suite.training_run import run
    args = SimpleNamespace(root='unused', recipe='unused.json', integrity_receipt=None)
    with pytest.raises(ValueError, match='preflight is required'):
        run(args)


def test_noop_wrong_route_or_failed_overfit_cannot_qualify():
    validate_native_result(passed_result())
    for name in ('optimizer_membership_exact', 'decoding_correct', 'routing_gradients_correct', 'tiny_final_overfit_all_eight'):
        result = passed_result()
        result[name] = False
        with pytest.raises(ValueError, match='preflight incomplete'):
            validate_native_result(result)
    result = passed_result()
    result['arms'][0]['checks'][0]['summaries']['retrospective']['risk_coverage']['0.5']['disagreements_with_reviewed_target'] = 1
    with pytest.raises(ValueError, match='memorize'):
        validate_native_result(result)


def test_successful_memorization_cannot_override_a_missing_parameter_update():
    result = passed_result()
    result['arms'][0]['all_groups_update_after_warmup'] = False
    with pytest.raises(ValueError, match='parameter update'):
        validate_native_result(result)


def test_preflight_is_bound_to_native_evidence_recipe_and_actual_training_math(tmp_path):
    recipe = tmp_path / 'recipe.json'
    recipe.write_text('{}')
    probe = tmp_path / 'probe'
    probe.mkdir()
    contract, result = probe / 'contract.json', probe / 'completed.json'
    contract.write_text('{}')
    result.write_text(json.dumps(passed_result()))
    value = {'schema': 'mechanical-training-preflight-v1', 'recipe_sha256': sha(recipe.read_bytes()),
             'optimization_sha256': optimization_fingerprint(), 'probe_directory': str(probe),
             'native_contract_sha256': sha(contract.read_bytes()), 'native_result_sha256': sha(result.read_bytes())}
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps(value))
    require_preflight(receipt, recipe)
    changed = {**value, 'optimization_sha256': 'wrong'}
    receipt.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match='stale'):
        require_preflight(receipt, recipe)
    receipt.write_text(json.dumps(value))
    result.write_text(json.dumps({**passed_result(), 'decoding_correct': False}))
    with pytest.raises(ValueError, match='evidence changed'):
        require_preflight(receipt, recipe)
