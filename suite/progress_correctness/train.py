"""Continue a saved classifier on complete synthetic TRAIN plus old-family replay.

Reuses the established full-active-graph objective, label permutations and GPU
implementation. Save every epoch independently. Optional asynchronous scoring
uses the exposed collection on another GPU, without changing training labels or
implicitly promoting an epoch. No quantization, deployment or weight publication.
"""
from __future__ import annotations

import argparse
from collections import Counter
import itertools
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time

from suite.gliclass_train import load_for_training
from suite.onejev_probe import append
from suite.onejev_train import loss_at_slots, lr_at
from suite.progress_dataset import render_state
from suite.progress_loto import (BASE, _setup_torch, _logits, encode, f1_report,
    group_weights, labels_for, score_rows, token_lengths)
from suite.training_updates import accumulated_update

DATA = Path('~/.cria/training/progress-correctness-v2').expanduser()
SOURCE = Path('~/.cria/training/progress-v1/weight-study-20261104/int4-repair/checkpoint').expanduser()


def progress_rows(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [{**r, 'task': r['family'], 'family': 'progress',
             'complete_input': render_state(r['requirement'], r['evidence'])} for r in rows]


def evaluate(torch, model, pipe, rows, hashes, path):
    records = score_rows(torch, model, pipe, rows, hashes, path)
    labels = labels_for(rows[0]['family'])
    return f1_report([r['label'] for r in records], [r['prediction'] for r in records], labels)


def external_evaluation(args, checkpoint, name, previous):
    """Pipeline read-only full-collection scoring onto the other GPU."""
    if previous is not None:
        append(args.out/'events.jsonl',{'event':'evaluation_process_complete','returncode':previous.wait()})
    destination = args.out/f'{name}-evaluation'
    with (args.out/f'{name}-evaluation.log').open('w') as stream:
        process = subprocess.Popen([sys.executable,'-m','suite.progress_correctness.evaluate_collection',
            '--source',str(checkpoint),'--out',str(destination),'--gpu-3080',args.eval_gpu],
            env={**os.environ,'OPENBLAS_NUM_THREADS':'2','OMP_NUM_THREADS':'2'},
            stdout=stream,stderr=subprocess.STDOUT)
    append(args.out/'events.jsonl',{'event':'evaluation_started','checkpoint':str(checkpoint),
        'destination':str(destination),'pid':process.pid,'gpu':args.eval_gpu})
    return process


def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    log = args.out / 'events.jsonl'
    torch = _setup_torch(False)
    started = time.monotonic()
    train = progress_rows(args.train)
    dev = progress_rows(args.dev)
    replay = json.loads((BASE / 'train-cases.json').read_text())
    hashes = json.loads((BASE / 'contract.json').read_text())['policy_sha256']
    rows = train + replay
    config = {'source_checkpoint': str(args.source), 'train': str(args.train), 'dev': str(args.dev),
        'progress_train_rows': len(train), 'old_train_replay_rows': len(replay), 'dev_rows': len(dev),
        'train_labels': dict(Counter(r['label'] for r in train)), 'epochs': args.epochs,
        'peak_learning_rate': args.lr, 'gradient_accumulation_rows': args.accumulation,
        'microbatch': 1, 'optimizer': 'AdamW; FP32 master parameters/states; foreach=False; weight_decay=0',
        'precision': ('native FP32 graph' if args.precision=='fp32' else 'BF16 autocast native graph')+'; FP32 CE+Brier objective',
        'checkpointing': 'non-reentrant gradient checkpointing; established monotone gather backward',
        'weighting': 'existing task/family/label group balancing', 'seed': 17,
        'input_handling': 'complete native rendering, no clipping or dropping',
        'test_opened': False, 'exposed_benchmark_evaluated':bool(args.eval_gpu),
        'evaluation_gpu':args.eval_gpu,'optimizer_checkpoints':args.optimizer_checkpoints,
        'deployed': False, 'published': False}
    (args.out / 'run.json').write_text(json.dumps(config, indent=2) + '\n')
    model, pipe, optimizer, loading, inactive = load_for_training(torch, str(args.source))
    # Confirm that the requested readout is present before any update.
    from safetensors import safe_open
    with safe_open(args.source / 'model.safetensors', framework='pt', device='cpu') as weights:
        expected = weights.get_tensor('model.scorer.mlp.4.weight')
    if not torch.equal(model.state_dict()['model.scorer.mlp.4.weight'].cpu(), expected):
        raise RuntimeError('loaded scoring row differs from the requested repaired checkpoint')
    lengths = token_lengths(pipe, rows + dev, hashes, args.out / 'token-lengths.json')
    append(log, {'event': 'loaded', 'loading': loading, 'inactive': inactive,
        'source_readout_exact': True, 'maximum_tokens': max(lengths.values()),
        'train_tokens': sum(lengths[r['id']] for r in rows), 'seconds': time.monotonic()-started})
    print(json.dumps({'event':'loaded', 'maximum_tokens':max(lengths.values()), **config}), flush=True)
    # A bounded, explicitly TRAIN-only preservation panel, not fresh validation.
    old_panel = []
    for family in ('dictation', 'retrospective'):
        for label in labels_for(family):
            old_panel += sorted([r for r in replay if r['family']==family and r['label']==label], key=lambda r:r['id'])[:16]
    evaluation_process = None
    if args.eval_gpu:
        evaluation_process = external_evaluation(args,args.source,'baseline',None)
        baseline = {'external_evaluation':str(args.out/'baseline-evaluation')}
    else:
        baseline = {'dev': evaluate(torch, model, pipe, dev, hashes, args.out / 'baseline-dev.jsonl')}
        for family in ('dictation', 'retrospective'):
            baseline[family] = evaluate(torch, model, pipe, [r for r in old_panel if r['family']==family], hashes, args.out / f'baseline-{family}-train.jsonl')
    (args.out / 'baseline.json').write_text(json.dumps(baseline, indent=2)+'\n')
    print(json.dumps({'event':'baseline', **baseline}), flush=True)
    weights = group_weights(rows)
    total = args.epochs * math.ceil(len(rows)/args.accumulation)
    rng = random.Random(17)
    step = 0
    best = None
    for epoch in range(args.epochs):
        order = list(rows)
        rng.shuffle(order)
        append(log, {'event':'epoch_start','epoch':epoch+1,'rows':len(order)})
        for offset in range(0, len(order), args.accumulation):
            batch = []
            for i, row in enumerate(order[offset:offset+args.accumulation]):
                options = list(itertools.permutations(labels_for(row['family'])))
                labels = options[(epoch*7+offset+i)%len(options)]
                inputs = encode(pipe, row, hashes, labels)
                batch.append({'id':row['id'], 'inputs':inputs, 'target':labels.index(row['label']), 'classes':len(labels)})
            event = accumulated_update(torch, model, optimizer, batch, weights,
                lambda row: _logits(torch, model, row['inputs'], row['classes'],precision=args.precision), loss_at_slots,
                lr_at(step, total, args.lr))
            step += 1
            if step % 10 == 0 or offset+args.accumulation >= len(order):
                event.update(event='update', epoch=epoch+1, step=step, total_steps=total,
                    seconds=time.monotonic()-started, gpu_peak_reserved_bytes=torch.cuda.max_memory_reserved())
                append(log, event)
                print(json.dumps(event), flush=True)
        checkpoint = args.out / f'epoch-{epoch+1}'
        model.save_pretrained(checkpoint, safe_serialization=True, max_shard_size='4GB')
        pipe.tokenizer.save_pretrained(checkpoint)
        optimizer_path = args.out/('latest-optimizer.pt' if args.optimizer_checkpoints=='rolling' else f'epoch-{epoch+1}-optimizer.pt')
        temporary = optimizer_path.with_suffix('.pt.partial')
        torch.save({'optimizer':optimizer.state_dict(),'epoch':epoch+1,'step':step,
                    'python_rng':rng.getstate(),'torch_rng':torch.get_rng_state(),
                    'cuda_rng':torch.cuda.get_rng_state_all()}, temporary)
        temporary.replace(optimizer_path)
        if args.eval_gpu:
            evaluation_process = external_evaluation(args,checkpoint,f'epoch-{epoch+1}',evaluation_process)
            metrics = {'external_evaluation':str(args.out/f'epoch-{epoch+1}-evaluation')}
        else:
            metrics = {'dev':evaluate(torch, model, pipe, dev, hashes, args.out/f'epoch-{epoch+1}-dev.jsonl')}
            for family in ('dictation','retrospective'):
                panel = [r for r in old_panel if r['family']==family]
                metrics[family] = evaluate(torch, model, pipe, panel, hashes, args.out/f'epoch-{epoch+1}-{family}-train.jsonl')
        report = {'event':'epoch_complete','epoch':epoch+1,'checkpoint':str(checkpoint), 'metrics':metrics,
                  'seconds':time.monotonic()-started,'step':step}
        (args.out/f'epoch-{epoch+1}-report.json').write_text(json.dumps(report,indent=2)+'\n')
        append(log, report)
        print(json.dumps(report), flush=True)
        if not args.eval_gpu:
            if best is None or metrics['dev']['macro_f1'] > best['metrics']['dev']['macro_f1']:
                best = report
            (args.out/'selected.json').write_text(json.dumps({'selection':f'highest DEV macro-F1 among fixed {args.epochs}-epoch run', **best},indent=2)+'\n')
    if evaluation_process is not None:
        append(log,{'event':'evaluation_process_complete','returncode':evaluation_process.wait()})
    append(log, {'event':'completed','epochs':args.epochs,'steps':step,'seconds':time.monotonic()-started,
        'selected_checkpoint':best['checkpoint'] if best else None,
        'selection':'all epochs retained for class-wise comparison; existing research selection unchanged' if args.eval_gpu else 'highest DEV macro-F1'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--train',type=Path,default=DATA/'train-3000-candidate.jsonl')
    parser.add_argument('--dev',type=Path,default=DATA/'dev-600-candidate.jsonl')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--epochs',type=int,default=2)
    parser.add_argument('--lr',type=float,default=5e-6)
    parser.add_argument('--accumulation',type=int,default=8)
    parser.add_argument('--precision',choices=['bf16','fp32'],default='bf16')
    parser.add_argument('--eval-gpu',help='GPU UUID for asynchronous full-collection native FP32 scoring')
    parser.add_argument('--optimizer-checkpoints',choices=['all','rolling'],default='all')
    run(parser.parse_args())

if __name__=='__main__':
    main()
