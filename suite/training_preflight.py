"""Fail-closed mechanical learning preflight for a new offline fitting matrix.

This is not semantic quality, fresh evaluation or deployment admission. The tiny
memorization check cannot replace whole-task validation.
"""
import inspect
import json
from pathlib import Path

from suite.training_prepare import sha


def optimization_fingerprint():
    from suite import training_run as runner
    functions = ('make_model', 'training_step', 'optimizer_groups', 'loss_weights', 'learning_rate_factor')
    sources = {name: inspect.getsource(getattr(runner, name)) for name in functions}
    sources['label_order'] = runner.LABEL_ORDER
    return sha(json.dumps(sources, sort_keys=True).encode())


def validate_native_result(result):
    for name in ('optimizer_membership_exact', 'decoding_correct', 'routing_gradients_correct',
                 'tiny_final_overfit_all_eight', 'all_existing_quarantines_unchanged'):
        if result.get(name) is not True:
            raise ValueError(f'training preflight incomplete: {name}')
    if not result.get('arms') or result['arms'][-1]['epochs'] != 200:
        raise ValueError('training preflight lacks the declared overfit arm')
    if any(arm.get('all_groups_update_after_warmup') is not True for arm in result['arms']):
        raise ValueError('training preflight lacks a required parameter update')
    final = result['arms'][-1]['checks'][-1]
    if final['step'] != 200:
        raise ValueError('training preflight cannot select an early/best checkpoint')
    for family in ('retrospective', 'dictation'):
        summary = final['summaries'][family]
        if summary['count'] != 4 or summary['risk_coverage']['0.5']['disagreements_with_reviewed_target'] != 0:
            raise ValueError('training preflight did not memorize both classes')


def qualify_probe(probe, recipe_path, destination):
    from suite import training_run as runner
    contract_path, result_path = probe / 'contract.json', probe / 'completed.json'
    contract = json.loads(contract_path.read_bytes())
    result = json.loads(result_path.read_bytes())
    validate_native_result(result)
    if contract['training_code_sha256'] != sha(Path(runner.__file__).read_bytes()):
        raise ValueError('qualify while the executed trainer source is still identical')
    recipe_sha = sha(recipe_path.read_bytes())
    if contract['recipe_sha256'] != recipe_sha:
        raise ValueError('training preflight recipe changed')
    receipt = {'schema': 'mechanical-training-preflight-v1', 'recipe_sha256': recipe_sha,
               'optimization_sha256': optimization_fingerprint(), 'probe_directory': str(probe.absolute()),
               'native_contract_sha256': sha(contract_path.read_bytes()),
               'native_result_sha256': sha(result_path.read_bytes()),
               'scope': 'MECHANICAL_TRAINING_ONLY_NOT_GENERALIZATION_OR_DEPLOYMENT'}
    runner.write_json(destination, receipt)
    return receipt


def require_preflight(receipt_path, recipe_path):
    if receipt_path is None:
        raise ValueError('native training preflight is required before another full matrix')
    receipt = json.loads(Path(receipt_path).read_bytes())
    if (receipt.get('schema') != 'mechanical-training-preflight-v1'
            or receipt.get('recipe_sha256') != sha(recipe_path.read_bytes())
            or receipt.get('optimization_sha256') != optimization_fingerprint()):
        raise ValueError('stale or incompatible training preflight')
    probe = Path(receipt['probe_directory'])
    for name, key in (('contract.json', 'native_contract_sha256'), ('completed.json', 'native_result_sha256')):
        if sha((probe / name).read_bytes()) != receipt[key]:
            raise ValueError('native training preflight evidence changed')
    validate_native_result(json.loads((probe / 'completed.json').read_bytes()))
    return receipt
