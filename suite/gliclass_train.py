"""One frozen, full-active-graph GLiClass fit on admitted TRAIN only."""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
from pathlib import Path
import random
import time

from suite.gliclass_probe import load_native, prepare_case
from suite.onejev_probe import append, file_sha
from suite.onejev_train import GPU_UUID, balanced_weights, loss_at_slots, lr_at
from suite.training_updates import accumulated_update


def freeze_architecturally_inactive(model):
    # Native uni-encoder forward multiplies logit_scale only inside its
    # normalize_features branch. It is not part of this checkpoint's graph.
    if model.config.architecture_type != 'uni-encoder' or model.config.normalize_features:
        raise ValueError('unqualified native architecture')
    params = dict(model.named_parameters())
    name = 'model.logit_scale'
    if name not in params or params[name].numel() != 1:
        raise ValueError('inactive native scale declaration differs')
    params[name].requires_grad_(False)
    return {name: 'native process_encoder_output uses this scalar only when normalize_features=True; checkpoint=False'}


def trainable_membership(model, optimizer):
    expected = {id(p) for p in model.parameters() if p.requires_grad}
    actual = [id(p) for group in optimizer.param_groups for p in group['params']]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError('optimizer membership is not exact')


def native_logits(torch, model, row):
    with torch.autocast('cuda', dtype=torch.bfloat16):
        logits = model(**row['inputs'], max_num_classes=2).logits[0, :2]
    return logits.float()


def update(torch, model, optimizer, rows, weights, lr):
    return accumulated_update(torch, model, optimizer, rows, weights,
        lambda row: native_logits(torch, model, row), loss_at_slots, lr)


def witness(torch, model):
    params = dict(model.named_parameters())
    layers = [name for name, p in params.items() if '.encoder.layer.' in name and p.ndim == 2]
    if not layers:
        raise ValueError('no native encoder layers')
    names = {'encoder_first': layers[0], 'encoder_last': layers[-1]}
    for branch in ['model.text_projector.', 'model.classes_projector.', 'model.scorer.', 'calibrator.']:
        names[branch] = next(name for name, p in params.items() if name.startswith(branch) and p.ndim == 2)
    return {key: {'name': name, 'values': params[name].detach().reshape(-1)[:8192].cpu().clone()}
            for key, name in names.items()}


def score(torch, model, rows, path):
    model.eval()
    matched = 0
    with torch.no_grad():
        for row in rows:
            logits = native_logits(torch, model, row)
            prediction = int(logits.argmax())
            matched += prediction == row['target']
            append(path, {'id': row['id'], 'target': row['target'], 'labels': row['labels'],
                          'logits': logits.cpu().tolist(), 'prediction': prediction, 'reasoning': None})
    model.train()
    return {'count': len(rows), 'matched': matched, 'precision': 'BF16 native graph, FP32 final logits/loss'}


def load_for_training(torch, snapshot):
    torch.manual_seed(17)
    model, pipe, loading = load_native(snapshot, 'cuda')
    inactive = freeze_architecturally_inactive(model)
    if any(p.dtype != torch.float32 for p in model.parameters()):
        raise ValueError('FP32 master weights required')
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model.train()
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                                  lr=5e-6, weight_decay=0, foreach=False)
    trainable_membership(model, optimizer)
    return model, pipe, optimizer, loading, inactive


def run(root):
    if (root / 'native-training-inputs.jsonl').exists():
        raise ValueError('existing attempt; preserve it and qualify a distinct run')
    contract = json.loads((root / 'contract.json').read_bytes())
    for name, digest in contract['input_sha256'].items():
        if file_sha(Path(name)) != digest:
            raise ValueError(f'frozen source changed: {name}')
    if os.environ.get('CUDA_VISIBLE_DEVICES') != GPU_UUID or contract['gpu_uuid'] != GPU_UUID:
        raise ValueError('only the approved 3090 may be visible')
    import torch
    if torch.__version__ != '2.8.0+cu128' or torch.cuda.device_count() != 1 or torch.cuda.get_device_name(0) != 'NVIDIA GeForce RTX 3090':
        raise ValueError('wrong GPU/build')
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    rows = json.loads((root / 'train-cases.json').read_bytes())
    if len(rows) != 514 or any(r['partition'] != 'TRAIN' for r in rows):
        raise ValueError('wrong admitted TRAIN cohort')
    weights = balanced_weights(rows)
    model, pipe, optimizer, loading, inactive = load_for_training(torch, contract['snapshot'])
    append(root / 'events.jsonl', {'event': 'loading', 'loading': loading, 'declared_inactive': inactive,
        'active_parameters': sum(p.numel() for p in model.parameters() if p.requires_grad),
        'optimizer_membership_exact': True})
    encoded = {}
    for row in rows:
        for reverse in [False, True]:
            inputs, receipt = prepare_case(pipe, row, contract['policy_sha256'], reverse=reverse)
            append(root / 'native-training-inputs.jsonl', receipt)
            encoded[row['id'], reverse] = {'id': row['id'], 'inputs': inputs,
                'labels': receipt['labels'], 'target': receipt['labels'].index(row['label'])}
    tiny = [encoded[i, False] for i in contract['tiny_ids']]
    before = witness(torch, model)
    for step in range(contract['tiny_updates']):
        event = update(torch, model, optimizer, tiny, {r['id']: 1.0 for r in tiny},
                       lr_at(step, contract['tiny_updates'], 5e-6))
        if step == 0:
            gradients = {name: {'present': p.grad is not None,
                'finite': bool(torch.isfinite(p.grad).all()) if p.grad is not None else False,
                'nonzero': bool(torch.count_nonzero(p.grad)) if p.grad is not None else False}
                for name, p in model.named_parameters() if p.requires_grad}
            (root / 'native-gradient-routing.json').write_text(json.dumps(gradients, indent=2)+'\n')
            # Connected but zero tensors can occur in invariant attention shifts;
            # absence/nonfinite gradients fail. Every functional branch must
            # additionally demonstrate an actual changed witness and memorization.
            if not all(g['present'] and g['finite'] for g in gradients.values()):
                raise ValueError('active native gradient routing failed')
        append(root / 'events.jsonl', {'event': 'tiny_update', 'step': step, **event})
    after = witness(torch, model)
    changes = {key: not torch.equal(value['values'], after[key]['values']) for key, value in before.items()}
    tiny_score = score(torch, model, tiny, root / 'tiny-native-calls.jsonl')
    integrity = {'optimizer_membership_exact': True, 'declared_inactive': inactive,
        'witness_names': {k: v['name'] for k, v in before.items()}, 'witness_changes': changes,
        'tiny_score': tiny_score, 'full_fit_reset_to_pretrained': True}
    (root / 'integrity.json').write_text(json.dumps(integrity, indent=2)+'\n')
    if not all(changes.values()) or tiny_score['matched'] != len(tiny):
        raise ValueError('native learning integrity gate failed; no full fit')
    # Inputs are retained but their tensors have no model/graph references.
    del model, pipe, optimizer, before, after
    gc.collect()
    torch.cuda.empty_cache()
    model, pipe, optimizer, loading, inactive = load_for_training(torch, contract['snapshot'])
    total = contract['epochs'] * math.ceil(len(rows)/contract['accumulation_rows'])
    started = time.monotonic()
    step = 0
    for epoch in range(contract['epochs']):
        order = list(range(len(rows)))
        random.Random(17+epoch).shuffle(order)
        append(root / 'events.jsonl', {'event': 'epoch_start', 'epoch': epoch,
            'row_ids': [rows[i]['id'] for i in order], 'torch_rng': torch.get_rng_state().tolist(),
            'cuda_rng': torch.cuda.get_rng_state().cpu().tolist()})
        for offset in range(0, len(order), contract['accumulation_rows']):
            batch = [encoded[rows[i]['id'], bool((epoch+i)%2)]
                     for i in order[offset:offset+contract['accumulation_rows']]]
            event = update(torch, model, optimizer, batch, weights, lr_at(step, total, 5e-6))
            reserved = torch.cuda.max_memory_reserved()
            if reserved > 22*1024**3:
                raise ValueError('declared GPU allocation exceeded; no substitution')
            append(root / 'events.jsonl', {'event': 'full_update', 'epoch': epoch, 'step': step,
                'rows': [{'id': r['id'], 'target': r['target'], 'labels': r['labels']} for r in batch],
                'gpu_peak_reserved_bytes': reserved, **event})
            print(json.dumps({'epoch': epoch+1, 'step': step+1, 'total_steps': total, **event}), flush=True)
            step += 1
        temporary = root / 'latest.pt.partial'
        torch.save({'model': model.state_dict(), 'optimizer': optimizer.state_dict(), 'next_epoch': epoch+1,
            'step': step, 'torch_rng': torch.get_rng_state(), 'cuda_rng': torch.cuda.get_rng_state()}, temporary)
        temporary.replace(root / 'latest.pt')
    reference = root / 'reference'
    reference.mkdir()
    model.save_pretrained(reference, safe_serialization=True, max_shard_size='4GB')
    pipe.tokenizer.save_pretrained(reference)
    train_score = score(torch, model, [encoded[r['id'], False] for r in rows], root / 'train-native-calls.jsonl')
    (root / 'trained.json').write_text(json.dumps({'completed_epochs': contract['epochs'], 'updates': step,
        'seconds': time.monotonic()-started, 'train_targets': train_score,
        'reference_files_sha256': {p.name: file_sha(p) for p in reference.iterdir() if p.is_file()},
        'quarantines_unchanged': True, 'not_fresh_evaluation_or_human_gold': True, 'deployed': False}, indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    run(args.root)


if __name__ == '__main__':
    main()
