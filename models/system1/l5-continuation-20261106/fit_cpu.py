"""Continue the original two-family native model, on CPU, without touching reserved labels."""
import argparse
import json
import math
import random
import time
from pathlib import Path

import torch
from suite.gliclass_probe import load_frozen_cohorts, load_native, prepare_case
from suite.gliclass_train import freeze_architecturally_inactive, trainable_membership
from suite.onejev_probe import append
from suite.onejev_train import balanced_weights, loss_at_slots, lr_at
from suite.training_updates import LABEL_ORDER, accumulated_update

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / 'train-001'
OUT = ROOT / 'cpu-fit-001'
EPOCHS, ACCUMULATION, LEARNING_RATE, SEED = 1, 16, 5e-6, 17

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT, help='new output directory; never overwrites the retained fit')
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(4)
    torch.manual_seed(SEED)
    contract, prior, _ = load_frozen_cohorts(BASE)
    new = json.loads((ROOT / 'train.json').read_text())
    rows = prior + [{'id': r['id'], 'family': r['family'], 'complete_input': r['complete_input'],
                     'label': r['label'], 'label_id': LABEL_ORDER[r['family']].index(r['label']),
                     'task': 'november-real-policy-boundaries'} for r in new]
    weights = balanced_weights(rows)
    model, pipe, loading = load_native(str(BASE / 'reference'), 'cpu')
    inactive = freeze_architecturally_inactive(model)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model.train()
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=LEARNING_RATE, weight_decay=0, foreach=False)
    trainable_membership(model, optimizer)
    settings = {'starting_checkpoint': str(BASE / 'reference'), 'device': 'cpu', 'precision': 'FP32',
                'epochs': EPOCHS, 'accumulation': ACCUMULATION, 'learning_rate': LEARNING_RATE,
                'seed': SEED, 'prior_train_rows': len(prior), 'new_train_rows': len(new),
                'loading': loading, 'inactive': inactive, 'reserved_labels_used': False}
    (out / 'settings.json').write_text(json.dumps(settings, indent=2) + '\n')
    rng = random.Random(SEED)
    total = EPOCHS * math.ceil(len(rows) / ACCUMULATION)
    start = time.monotonic()
    for epoch in range(EPOCHS):
        order = list(range(len(rows)))
        rng.shuffle(order)
        for offset in range(0, len(order), ACCUMULATION):
            batch = []
            for index in order[offset:offset + ACCUMULATION]:
                row = rows[index]
                inputs, receipt = prepare_case(pipe, row, contract['policy_sha256'], reverse=bool((epoch + index) % 2))
                batch.append({'id': row['id'], 'inputs': inputs, 'target': receipt['labels'].index(row['label'])})
            step = epoch * math.ceil(len(rows) / ACCUMULATION) + offset // ACCUMULATION
            event = accumulated_update(torch, model, optimizer, batch, weights,
                lambda row: model(**row['inputs'], max_num_classes=2).logits[0, :2].float(),
                loss_at_slots, lr_at(step, total, LEARNING_RATE))
            append(out / 'events.jsonl', {'step': step + 1, 'total': total, 'seconds': time.monotonic() - start, **event})
            print(json.dumps({'step': step + 1, 'total': total, **event}), flush=True)
    reference = out / 'reference'
    reference.mkdir()
    model.save_pretrained(reference, safe_serialization=True, max_shard_size='4GB')
    pipe.tokenizer.save_pretrained(reference)
    (out / 'completed.json').write_text(json.dumps({'updates': total, 'seconds': time.monotonic() - start, 'deployed': False}, indent=2) + '\n')

if __name__ == '__main__':
    main()
