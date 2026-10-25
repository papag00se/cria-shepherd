"""Offline training-integrity probes on admitted TRAIN cases, never an evaluation.

No new matrix or deployment. ML dependencies are lazy; the existing fitting step
is the sole optimization implementation. Full native inputs and original labels.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
import os
from pathlib import Path
import random

from suite.training_admit import LABEL_ORDER
from suite.training_calibrate import summarize
from suite.training_prepare import sha
from suite.training_run import (validate_bundle, validate_authorization, make_model, optimizer_groups,
                                learning_rate_factor, loss_weights, training_step, write_json)

GPU_UUID = 'GPU-907a7f7a-b541-8208-2bce-e1361e3110d6'


def parameter_group(name):
    return '.'.join(name.split('.')[:2]) if name.startswith('heads.') else 'encoder'


def optimizer_membership(model, optimizer):
    expected = {id(p): name for name, p in model.named_parameters() if p.requires_grad}
    actual = Counter(id(p) for group in optimizer.param_groups for p in group['params'])
    if set(actual) != set(expected) or any(count != 1 for count in actual.values()):
        raise ValueError('optimizer must own every trainable parameter exactly once')
    return [{'name': expected[id(p)], 'lr': group['lr'], 'weight_decay': group['weight_decay'],
             'elements': p.numel(), 'dtype': str(p.dtype)}
            for group in optimizer.param_groups for p in group['params']]


def gradient_summary(model):
    groups = defaultdict(lambda: {'tensors': 0, 'gradient_tensors': 0, 'nonzero_gradient_tensors': 0,
                                  'squared_norm': 0.0, 'finite': True})
    for name, parameter in model.named_parameters():
        group = groups[parameter_group(name)]
        group['tensors'] += 1
        if parameter.grad is not None:
            gradient = parameter.grad.detach().float()
            group['gradient_tensors'] += 1
            norm = gradient.norm().item()
            group['squared_norm'] += norm ** 2
            group['nonzero_gradient_tensors'] += int(norm != 0)
            group['finite'] &= math.isfinite(norm)
    return {name: {**values, 'norm': math.sqrt(values['squared_norm'])} for name, values in groups.items()}


def parameter_changes(model, before):
    groups = defaultdict(lambda: {'tensors': 0, 'changed_tensors': 0, 'squared_delta': 0.0})
    for name, parameter in model.named_parameters():
        group = groups[parameter_group(name)]
        group['tensors'] += 1
        norm = (parameter.detach() - before[name].to(parameter.device)).float().norm().item()
        group['changed_tensors'] += int(norm != 0)
        group['squared_delta'] += norm ** 2
    return {name: {**values, 'delta_norm': math.sqrt(values['squared_delta'])} for name, values in groups.items()}


def weighted_support(ids, rows, metadata):
    weights = loss_weights(ids, metadata)
    support = defaultdict(lambda: {'examples': 0, 'loss_weight_mass': 0.0})
    for case_id in ids:
        row = rows[case_id]
        key = (metadata[case_id]['task'], row['family'], row['label'])
        support[key]['examples'] += 1
        support[key]['loss_weight_mass'] += weights[case_id]
    return [{'task': task, 'family': family, 'label': label, **values}
            for (task, family, label), values in sorted(support.items())]


def run(args):
    root, recipe_path = Path(args.root), Path(args.recipe)
    recipe, rows, strata, jobs = validate_bundle(root, recipe_path)
    validate_authorization(json.loads((root / 'execution/authorization.json').read_bytes()), sha(recipe_path.read_bytes()), GPU_UUID)
    if os.environ.get('CUDA_VISIBLE_DEVICES') != GPU_UUID:
        raise ValueError('only the authorized 3090 may be visible')
    selected = json.loads(Path(args.cases).read_bytes())
    if len({r['id'] for r in selected}) != 8:
        raise ValueError('expected eight distinct preselected TRAIN inputs')
    for row in selected:
        if row['id'] not in strata['real'] or row != rows[row['id']]:
            raise ValueError('probe may only use byte-bound admitted real TRAIN cases')
        if row['label_id'] != LABEL_ORDER[row['family']].index(row['label']):
            raise ValueError('source label ID differs from the head class order')
    ids = sorted(r['id'] for r in selected)
    if Counter((rows[i]['family'], rows[i]['label_id']) for i in ids) != Counter({(f, c): 2 for f in LABEL_ORDER for c in (0, 1)}):
        raise ValueError('tiny probe needs both classes in both heads')
    output = Path(args.output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_json(output / 'contract.json', {'purpose': 'TRAINING_INTEGRITY_NOT_GENERALIZATION',
               'operator_authorized_investigation': True, 'recipe_sha256': sha(recipe_path.read_bytes()),
               'diagnostic_code_sha256': sha(Path(__file__).read_bytes()),
               'training_code_sha256': sha(Path('suite/training_run.py').read_bytes()),
               'cases_sha256': sha(Path(args.cases).read_bytes()), 'ids': ids,
               'arms': [{'epochs': 5}, {'epochs': 200}],
               'fixed_changes': 'Only tiny balanced TRAIN subset and declared step-budget diagnostic; same native encoder, heads, LR, loss, precision, accumulation division, clipping and linear warmup/decay. No early/best selection.',
               'quarantines_unchanged': True, 'fresh_evaluation': False})
    weights = loss_weights(ids, strata['real'])
    write_json(output / 'weighting.json', {'tiny_weights': weights,
               'prespecified_jobs': [{'name': j['name'], 'training_support': weighted_support(j['train_ids'], rows, strata['real'])}
                                    for j in jobs if j['arm'] == 'real_only' and j['seed'] == 17]})
    os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'
    import torch
    from transformers import AutoModel
    from tokenizers import Tokenizer
    from safetensors.torch import load_file
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    if torch.cuda.device_count() != 1 or torch.cuda.get_device_name(0) != 'NVIDIA GeForce RTX 3090':
        raise ValueError('wrong physical GPU')
    checkpoint = Path(json.loads((root / 'execution/gpu-preflight.json').read_bytes())['checkpoint'])
    if sha(checkpoint.read_bytes()) != recipe['published_checkpoint_sha256']:
        raise ValueError('checkpoint changed')
    tokenizer = Tokenizer.from_file(str(checkpoint.parent / 'tokenizer.json'))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    encoded = {i: tokenizer.encode(rows[i]['model_text']).ids for i in ids}
    if any(len(tokens) > recipe['native_limit'] for tokens in encoded.values()):
        raise ValueError('NO_FIT; no shorter replacement')

    def record(phase, case_id, logits, **extra):
        entry = {'phase': phase, 'id': case_id, 'family': rows[case_id]['family'],
                 'model_text': rows[case_id]['model_text'], 'native_ids': encoded[case_id],
                 'label': rows[case_id]['label'], 'label_id': rows[case_id]['label_id'],
                 'logits': logits.detach().float().cpu().tolist(), 'reasoning': None, **extra}
        with (output / 'calls.jsonl').open('a') as stream:
            stream.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + '\n')

    def fresh():
        random.seed(17)
        torch.manual_seed(17)
        torch.cuda.manual_seed_all(17)
        encoder, loading = AutoModel.from_pretrained(str(checkpoint.parent), local_files_only=True,
                         trust_remote_code=False, weights_only=True, attn_implementation='eager', output_loading_info=True)
        if (loading['missing_keys'] or loading['mismatched_keys'] or loading['error_msgs']
                or any(not key.startswith(('head.', 'decoder.')) for key in loading['unexpected_keys'])):
            raise ValueError('native encoder loading differs')
        encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
        torch.manual_seed(17)
        return make_model(torch, encoder).to('cuda')

    def predict(model, phase, **extra):
        model.eval()
        predictions = []
        with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16):
            for case_id in ids:
                x = torch.tensor([encoded[case_id]], device='cuda')
                logits = model(x, torch.ones_like(x), rows[case_id]['family'])[0]
                record(phase, case_id, logits, **extra)
                predictions.append({'id': case_id, 'family': rows[case_id]['family'],
                                    'label_id': rows[case_id]['label_id'], 'task': strata['real'][case_id]['task'],
                                    'logits': logits.float().cpu().tolist()})
        return predictions

    model = fresh()
    settings = recipe['optimizer']
    optimizer = torch.optim.AdamW(optimizer_groups(torch, model, settings), betas=tuple(settings['betas']), eps=settings['epsilon'])
    membership = optimizer_membership(model, optimizer)
    write_json(output / 'optimizer-membership.json', membership)
    trained_folder = root / 'execution/references-001/real_only-seed17-final'
    expected = json.loads((trained_folder / 'completed.json').read_bytes())['artifacts']['reference_sha256']
    trained_path = trained_folder / 'reference/master.safetensors'
    if sha(trained_path.read_bytes()) != expected:
        raise ValueError('original final reference changed')
    trained = load_file(str(trained_path), device='cpu')
    # Compare the real trained tensors against the correctly seeded pretrained baseline.
    changes = parameter_changes(model, trained)
    write_json(output / 'original-final-versus-initial.json', changes)
    del trained
    head_states = {name: p.detach().clone() for name, p in model.named_parameters() if name.startswith('heads.')}
    decoding = []
    with torch.no_grad():
        for parameter in model.heads.parameters():
            parameter.zero_()
        for family in LABEL_ORDER:
            for target in (0, 1):
                model.heads[family].bias.zero_()
                model.heads[family].bias[target] = 4
                case_id = next(i for i in ids if rows[i]['family'] == family and rows[i]['label_id'] == target)
                model.eval()
                x = torch.tensor([encoded[case_id]], device='cuda')
                with torch.autocast('cuda', dtype=torch.bfloat16):
                    logits = model(x, torch.ones_like(x), family)[0]
                record('forced-head-decoding', case_id, logits)
                native = {'logits': logits.float().cpu().tolist(), 'label_id': target, 'task': strata['real'][case_id]['task']}
                confusion = summarize([native], 1)['confusion_reviewed_target_by_prediction']
                if confusion[target][target] != 1:
                    raise ValueError('label/head/output decoder inversion')
                decoding.append({'family': family, 'target': target, 'label': LABEL_ORDER[family][target], 'confusion': confusion})
        for name, parameter in model.named_parameters():
            if name in head_states:
                parameter.copy_(head_states[name])
    write_json(output / 'head-decoding.json', decoding)
    routes = []
    for family in LABEL_ORDER:
        model.train()
        model.zero_grad(set_to_none=True)
        case_id = next(i for i in ids if rows[i]['family'] == family)
        x = torch.tensor([encoded[case_id]], device='cuda')
        with torch.autocast('cuda', dtype=torch.bfloat16):
            logits = model(x, torch.ones_like(x), family)
            loss = torch.nn.functional.cross_entropy(logits, torch.tensor([rows[case_id]['label_id']], device='cuda'))
        record('routing-gradient', case_id, logits[0])
        loss.backward()
        gradients = gradient_summary(model)
        if not gradients['encoder']['finite'] or gradients['encoder']['norm'] <= 0 or gradients['heads.' + family]['norm'] <= 0:
            raise ValueError('missing active encoder/head gradients')
        if any(values['gradient_tensors'] for name, values in gradients.items() if name.startswith('heads.') and name != 'heads.' + family):
            raise ValueError('wrong head receives loss gradients')
        routes.append({'family': family, 'gradients': gradients})
    write_json(output / 'routing-gradients.json', routes)
    del model, optimizer, head_states
    torch.cuda.empty_cache()

    arm_results = []
    for epochs in (5, 200):
        model = fresh()
        optimizer = torch.optim.AdamW(optimizer_groups(torch, model, settings), betas=tuple(settings['betas']), eps=settings['epsilon'])
        optimizer_membership(model, optimizer)
        scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda step: learning_rate_factor(step, epochs))
        sampler = random.Random(17)
        predict(model, 'initial', arm_epochs=epochs)
        audits, checks = [], []
        for step in range(1, epochs + 1):
            model.train()
            batch = sorted(ids)
            sampler.shuffle(batch)
            audit = step in (1, 2, 5, 20, 50, 100, 200)
            before = {name: p.detach().clone() for name, p in model.named_parameters()} if audit else None
            snapshot = {}

            def observe(phase, **fields):
                if phase == 'forward':
                    record('training', fields['case_id'], fields['logits'][0], arm_epochs=epochs, step=step)
                elif phase == 'backward' and audit:
                    snapshot['gradients'] = gradient_summary(model)
                elif phase == 'updated' and audit:
                    snapshot['parameter_changes'] = parameter_changes(model, before)

            result = training_step(torch, model, optimizer, scheduler, batch, rows, encoded, weights,
                                   settings['gradient_norm_clip'], observe=observe)
            if audit:
                audits.append({'step': step, **result, **snapshot})
                write_json(output / f'arm-{epochs}-updates.json', audits)
            if step in (5, 20, 50, 100, 200):
                predictions = predict(model, 'after-update', arm_epochs=epochs, step=step)
                summaries = {family: summarize([r for r in predictions if r['family'] == family], 1) for family in LABEL_ORDER}
                checks.append({'step': step, 'summaries': summaries})
                print(json.dumps({'arm_epochs': epochs, 'step': step,
                      'confusions': {family: s['confusion_reviewed_target_by_prediction'] for family, s in summaries.items()}}), flush=True)
            if torch.cuda.max_memory_reserved() > 18 * 1024**3:
                raise RuntimeError('resource ceiling exceeded; do not alter precision/input')
        for group in ('encoder', 'heads.retrospective', 'heads.dictation'):
            if audits[1]['parameter_changes'][group]['changed_tensors'] == 0:
                raise ValueError('nonzero-LR optimizer step did not change a required group')
        arm_results.append({'epochs': epochs, 'checks': checks, 'all_groups_update_after_warmup': True})
        del model, optimizer, scheduler, before
        torch.cuda.empty_cache()
    overfit = arm_results[-1]['checks'][-1]['summaries']
    successful = all(s['risk_coverage']['0.5']['disagreements_with_reviewed_target'] == 0 for s in overfit.values())
    write_json(output / 'completed.json', {'optimizer_membership_exact': True, 'decoding_correct': True,
               'routing_gradients_correct': True, 'original_final_parameter_changes': changes,
               'arms': arm_results, 'tiny_final_overfit_all_eight': successful,
               'not_generalization_or_human_gold': True, 'full_matrix_run': False,
               'all_existing_quarantines_unchanged': True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'recipe', 'cases', 'output'):
        parser.add_argument('--' + name, required=True)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
