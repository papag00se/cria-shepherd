"""One separately frozen, offline full OneJev fine-tune; no production integration."""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import json
import math
import os
from pathlib import Path
import random
import time

from suite.onejev_probe import append, file_sha, native_request
from suite.training_admit import LABEL_ORDER
from suite.training_prepare import sha

GPU_UUID = 'GPU-907a7f7a-b541-8208-2bce-e1361e3110d6'


def balanced_weights(rows):
    counts = Counter((r['task'], r['family'], r['label']) for r in rows)
    if any(r['label_id'] != LABEL_ORDER[r['family']].index(r['label']) for r in rows):
        raise ValueError('source label order differs')
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('duplicate source identity')
    return {r['id']: len(rows) / (len(counts) * counts[r['task'], r['family'], r['label']]) for r in rows}


def loss_at_slots(torch, logits, target, weight):
    # Same restricted-slot CE + Brier objective as the official trainer, with
    # explicitly declared task/head/label balancing for this new experiment.
    target_vector = torch.nn.functional.one_hot(torch.tensor(target, device=logits.device), 2).float()
    logp = torch.log_softmax(logits.float(), dim=-1)
    probabilities = logp.exp()
    return weight * (-(target_vector * logp).sum() + ((probabilities - target_vector) ** 2).sum())


def render_case(tokenizer, case, policies, reverse=False):
    from qev.prompt import render_question, build_messages
    request = native_request(case, policies)
    rendered = render_question('decision', request.questions['decision'], order=[1, 0] if reverse else [0, 1])
    prompt = tokenizer.apply_chat_template(build_messages(request.state, rendered.suffix), tokenize=False,
                                           add_generation_prompt=True, enable_thinking=False)
    tokens = tokenizer.encode(prompt, add_special_tokens=False)
    if len(tokens) > 8192:
        raise ValueError('NO_FIT; never clip, split or drop a training input')
    return {'id': case['id'], 'family': case['family'], 'target': rendered.labels.index(case['label']),
            'labels': rendered.labels, 'request': request.model_dump(), 'prompt': prompt, 'tokens': tokens}


def slot_logits(torch, model, tokens, slot_ids):
    ids = torch.tensor([tokens], device='cuda', dtype=torch.long)
    with torch.autocast('cuda', dtype=torch.bfloat16):
        hidden = model.model(input_ids=ids, attention_mask=torch.ones_like(ids), use_cache=False).last_hidden_state[0, -1]
    # Keep the native default FP32 answer readout and the live output weights:
    # detach here would silently freeze the trainable answer slots.
    with torch.autocast('cuda', enabled=False):
        return model.get_output_embeddings().weight.index_select(0, slot_ids).float() @ hidden.float()


def training_step(torch, model, optimizer, encoded, weights, slot_ids, lr):
    from suite.training_updates import accumulated_update
    return accumulated_update(torch, model, optimizer, encoded, weights,
        lambda row: slot_logits(torch, model, row['tokens'], slot_ids), loss_at_slots, lr)


def lr_at(step, total, peak):
    warmup = math.ceil(total * .05)
    if step < warmup:
        return peak * step / warmup
    return peak * .5 * (1 + math.cos(math.pi * (step - warmup) / max(1, total - warmup)))


def load_model(torch, snapshot):
    from transformers import AutoConfig, Qwen3_5ForCausalLM
    torch.manual_seed(17)
    config = AutoConfig.from_pretrained(snapshot, local_files_only=True).get_text_config()
    model, info = Qwen3_5ForCausalLM.from_pretrained(snapshot, config=config, dtype=torch.float32,
        attn_implementation='eager', local_files_only=True, output_loading_info=True)
    if any(info.get(k) for k in ('missing_keys', 'mismatched_keys', 'error_msgs')):
        raise ValueError(f'incomplete native checkpoint: {info}')
    if any(not k.startswith(('visual.', 'model.visual.')) for k in info.get('unexpected_keys', [])):
        raise ValueError(f'unexpected text checkpoint keys: {info}')
    if any(p.dtype != torch.float32 or not p.requires_grad for p in model.parameters()):
        raise ValueError('full FP32 master weights required')
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    from suite.training_run import loading_receipt
    return model.to('cuda').train(), loading_receipt(info)


def witness(torch, model, slots):
    params = dict(model.named_parameters())
    layers = [name for name in params if '.layers.' in name]
    names = [layers[0], layers[-1]]
    return {'slots': model.get_output_embeddings().weight.index_select(0, slots).detach().cpu().clone(),
            **{name: params[name].detach().cpu().clone() for name in names}}


def score(torch, model, encoded, slots, path):
    model.eval()
    correct = 0
    with torch.no_grad():
        for row in encoded:
            logits = slot_logits(torch, model, row['tokens'], slots)
            prediction = int(logits.argmax())
            correct += prediction == row['target']
            append(path, {'id': row['id'], 'target': row['target'], 'labels': row['labels'],
                'logits': logits.float().cpu().tolist(), 'prediction': prediction, 'reasoning': None})
    model.train()
    return {'count': len(encoded), 'matched': correct}


def run(root):
    if (root / 'native-training-inputs.jsonl').exists():
        raise ValueError('existing run; preserve it and qualify a distinct run instead of duplicating training')
    contract = json.loads((root / 'contract.json').read_bytes())
    if os.environ.get('CUDA_VISIBLE_DEVICES') != GPU_UUID or contract['gpu_uuid'] != GPU_UUID:
        raise ValueError('only the authorized 3090 may be visible')
    for name, digest in contract['input_sha256'].items():
        if file_sha(Path(name)) != digest:
            raise ValueError(f'frozen training input changed: {name}')
    if sha(Path(__file__).read_bytes()) != contract['trainer_sha256']:
        raise ValueError('trainer changed after recipe freeze')
    import torch
    from transformers import AutoTokenizer
    if torch.__version__ != '2.8.0+cu128' or torch.cuda.device_count() != 1 or torch.cuda.get_device_name(0) != 'NVIDIA GeForce RTX 3090':
        raise ValueError('wrong GPU/build')
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    snapshot = contract['snapshot']
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
    slot_ids = [tokenizer.encode(letter, add_special_tokens=False) for letter in ('A', 'B')]
    if any(len(ids) != 1 for ids in slot_ids) or slot_ids[0] == slot_ids[1]:
        raise ValueError('native answer slots are not distinct single tokens')
    slots = torch.tensor([ids[0] for ids in slot_ids], device='cuda')
    rows = json.loads((root / 'train-cases.json').read_bytes())
    weights = balanced_weights(rows)
    encoded = {(r['id'], reverse): render_case(tokenizer, r, contract['policy_sha256'], reverse)
               for r in rows for reverse in (False, True)}
    for row in encoded.values():
        append(root / 'native-training-inputs.jsonl', row)
    tiny_ids = contract['tiny_ids']
    tiny = [encoded[i, False] for i in tiny_ids]
    model, info = load_model(torch, snapshot)
    append(root / 'events.jsonl', {'event': 'loading', 'info': info, 'trainable_parameters': sum(p.numel() for p in model.parameters())})
    optimizer = torch.optim.AdamW(model.parameters(), lr=5e-6, weight_decay=0, foreach=False)
    membership = [id(p) for group in optimizer.param_groups for p in group['params']]
    expected = [id(p) for p in model.parameters() if p.requires_grad]
    if len(membership) != len(set(membership)) or set(membership) != set(expected):
        raise ValueError('optimizer membership is not exact')
    before = witness(torch, model, slots)
    for step in range(contract['tiny_updates']):
        event = training_step(torch, model, optimizer, tiny, {i: 1.0 for i in tiny_ids}, slots,
                              lr_at(step, contract['tiny_updates'], 5e-6))
        if step == 0:
            gradients = {name: {'present': p.grad is not None,
                'finite': bool(torch.isfinite(p.grad).all()) if p.grad is not None else False,
                'nonzero': bool(torch.count_nonzero(p.grad)) if p.grad is not None else False}
                for name, p in model.named_parameters()}
            (root / 'native-gradient-routing.json').write_text(json.dumps(gradients, indent=2) + '\n')
            if not all(x['present'] and x['finite'] and x['nonzero'] for x in gradients.values()):
                raise ValueError('native gradient routing failed')
        append(root / 'events.jsonl', {'event': 'tiny_update', 'step': step, **event})
    after = witness(torch, model, slots)
    changed = {name: not torch.equal(value, after[name]) for name, value in before.items()}
    changed['each_native_slot_row'] = all(not torch.equal(before['slots'][i], after['slots'][i]) for i in range(2))
    tiny_score = score(torch, model, tiny, slots, root / 'tiny-native-calls.jsonl')
    receipt = {'optimizer_membership_exact': True, 'witness_updates': changed, 'tiny_score': tiny_score,
               'trainer_sha256': contract['trainer_sha256'], 'tiny_updates': contract['tiny_updates']}
    (root / 'integrity.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if not all(changed.values()) or tiny_score['matched'] != len(tiny):
        raise ValueError('native learning preflight failed; no full fit authorized without repair')
    del model, optimizer, before, after
    gc.collect()
    torch.cuda.empty_cache()
    # The tiny probe must not initialize the real fit.
    model, info = load_model(torch, snapshot)
    optimizer = torch.optim.AdamW(model.parameters(), lr=5e-6, weight_decay=0, foreach=False)
    total = contract['epochs'] * math.ceil(len(rows) / contract['accumulation_rows'])
    step = 0
    started = time.monotonic()
    for epoch in range(contract['epochs']):
        order = list(range(len(rows)))
        random.Random(17 + epoch).shuffle(order)
        append(root / 'events.jsonl', {'event': 'epoch_start', 'epoch': epoch,
            'row_ids': [rows[i]['id'] for i in order], 'torch_rng': torch.get_rng_state().tolist(),
            'cuda_rng': torch.cuda.get_rng_state().cpu().tolist()})
        for offset in range(0, len(order), contract['accumulation_rows']):
            batch = [encoded[rows[i]['id'], bool((epoch + i) % 2)] for i in order[offset:offset + contract['accumulation_rows']]]
            event = training_step(torch, model, optimizer, batch, weights, slots, lr_at(step, total, 5e-6))
            reserved = torch.cuda.max_memory_reserved()
            if reserved > 22 * 1024**3:
                raise ValueError('declared 22 GiB training allocation exceeded')
            append(root / 'events.jsonl', {'event': 'full_update', 'epoch': epoch, 'step': step,
                'rows': [{'id': r['id'], 'target': r['target'], 'labels': r['labels']} for r in batch],
                'gpu_peak_reserved_bytes': reserved, **event})
            print(json.dumps({'epoch': epoch + 1, 'step': step + 1, 'total_steps': total, **event}), flush=True)
            step += 1
        checkpoint = root / 'latest.pt'
        temporary = root / 'latest.pt.partial'
        torch.save({'model': model.state_dict(), 'optimizer': optimizer.state_dict(), 'next_epoch': epoch + 1,
                    'step': step, 'torch_rng': torch.get_rng_state(), 'cuda_rng': torch.cuda.get_rng_state()}, temporary)
        temporary.replace(checkpoint)
    reference = root / 'reference'
    reference.mkdir()
    model.config.use_cache = True
    model.save_pretrained(reference, safe_serialization=True, max_shard_size='4GB')
    tokenizer.save_pretrained(reference)
    trained_score = score(torch, model, [encoded[r['id'], False] for r in rows], slots, root / 'train-native-calls.jsonl')
    result = {'completed_epochs': contract['epochs'], 'updates': step, 'seconds': time.monotonic() - started,
        'train_targets': trained_score, 'reference_files_sha256': {p.name: file_sha(p) for p in reference.iterdir() if p.is_file()},
        'quarantines_unchanged': True, 'deployed': False, 'not_fresh_evaluation_or_human_gold': True}
    (root / 'trained.json').write_text(json.dumps(result, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    run(args.root)


if __name__ == '__main__':
    main()
