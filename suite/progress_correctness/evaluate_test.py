"""One authorized, read-only held-out score of the already-selected native model.

No training, checkpoint selection, quantization, publication or deployment.
Predictions are persisted once per input before aggregate reporting.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import time

from suite.gliclass_probe import load_native
from suite.onejev_probe import append
from suite.progress_correctness.heldout_adapter import full_diff
from suite.progress_dataset import LABELS, render_state
from suite.progress_loto import _setup_torch, f1_report


def run(checkpoint, test, out):
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    blind = [json.loads(s) for s in (test/'review-blind.jsonl').read_text().splitlines()]
    evidence = [json.loads(s) for s in (test/'private-evidence.jsonl').read_text().splitlines()]
    actual = {r['id']: r for r in evidence}
    if len(blind)!=600 or len(actual)!=600 or {r['id'] for r in blind} != set(actual):
        raise ValueError('expected matching unique 600-row held-out inputs and actual author labels')
    if Counter(r['label'] for r in evidence) != {label:200 for label in LABELS}:
        raise ValueError('held-out labels do not match expected balanced classes')
    groups = defaultdict(list)
    for r in evidence:
        groups[r['group']].append(r['label'])
    if len(groups)!=200 or any(Counter(v)!=Counter(LABELS) for v in groups.values()):
        raise ValueError('expected 200 complete three-state requirement groups')
    # Match actual evidence to classifier-visible inputs. Never derive labels
    # from row ordering, filenames or the blind packet's shuffle.
    for row in blind:
        truth = actual[row['id']]
        if row['state'] != render_state(row['state']['requirement'], full_diff(truth['seed_files'], truth['snapshot'])):
            raise ValueError('blind input and actual labeled snapshot differ')
        if list(row['options']) != list(LABELS):
            raise ValueError('unexpected native label order')
    config = {'checkpoint':str(checkpoint), 'test':str(test), 'inputs':len(blind),
        'label_source':'author-private evidence joined to blind IDs and verified against full snapshot diff',
        'precision':'native FP32 eval; no autocast', 'training':False, 'deployed':False,
        'tuning':False, 'per_input_evaluations':1,
        'provenance':json.loads((test/'provenance.json').read_text())}
    (out/'evaluation.json').write_text(json.dumps(config,indent=2)+'\n')
    torch = _setup_torch(False)
    model, pipe, _ = load_native(str(checkpoint),'cuda')
    model.eval()
    model.requires_grad_(False)
    predictions = []
    with torch.inference_mode():
        for i, row in enumerate(blind):
            truth = actual[row['id']]
            text = pipe.prepare_input(row['rendered_state'], list(LABELS), prompt=row['policy'])
            inputs = pipe.tokenizer(text, truncation=False, return_tensors='pt').to('cuda')
            append(out/'calls.jsonl', {'event':'start','id':row['id'],'rendered_input':text,
                'input_ids':inputs['input_ids'].tolist(),'tokens':inputs['input_ids'].shape[1]})
            values = model(**inputs,max_num_classes=len(LABELS)).logits.float()
            if tuple(values.shape)!=(1,len(LABELS)) or not torch.isfinite(values).all():
                raise ValueError('invalid native calibrated logits')
            logits = values[0].cpu().tolist()
            result = {'id':row['id'],'group':truth['group'],'family':truth['family'],
                'label':truth['label'],'prediction':LABELS[int(values[0].argmax())],
                'logits':logits,'tokens':inputs['input_ids'].shape[1],'reasoning':None}
            append(out/'calls.jsonl', {'event':'result',**result})
            append(out/'predictions.jsonl', result)
            predictions.append(result)
            if (i+1)%100==0:
                print(json.dumps({'completed':i+1,'total':len(blind),'seconds':time.monotonic()-started}),flush=True)
    report = f1_report([r['label'] for r in predictions],[r['prediction'] for r in predictions])
    report['per_class'] = {}
    matrix = report['confusion']
    for i,label in enumerate(LABELS):
        correct = matrix[i][i]
        predicted = sum(row[i] for row in matrix)
        report['per_class'][label] = {'true_count':sum(matrix[i]),'predicted_count':predicted,
            'correct':correct,'recall':correct/sum(matrix[i]),
            'precision':correct/predicted if predicted else None,'f1':report['per_label_f1'][label]}
    report['false_done'] = {'partial_count':matrix[1][0], 'partial_rate':matrix[1][0]/sum(matrix[1]),
        'not_started_count':matrix[2][0], 'not_started_rate':matrix[2][0]/sum(matrix[2]),
        'combined_count':matrix[1][0]+matrix[2][0],
        'combined_rate_among_non_done':(matrix[1][0]+matrix[2][0])/(sum(matrix[1])+sum(matrix[2]))}
    report.update(checkpoint=str(checkpoint),seconds=time.monotonic()-started,
        successful_evaluations_per_input=dict(Counter(Counter(r['id'] for r in predictions).values())),
        group_count=len(groups),family_id_count=len({r['family'] for r in evidence}),
        gpu_peak_reserved_bytes=torch.cuda.max_memory_reserved(),
        limitations='Synthetic author-labeled TEST, not real-world gold; family IDs alone do not prove independence; not independently semantically reviewed. Native FP32 only, not INT4 qualification.')
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--test',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    run(args.checkpoint,args.test,args.out)
