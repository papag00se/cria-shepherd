"""Gradient-free native readout repair using TRAIN and DEV only.

Collect full, untruncated native activations in independent GPU shards. Construct
closed-form readout edits from TRAIN and check the actual nonlinear calibrator.
No gradient, optimizer, TEST access, quantization, deployment or publication.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import time

from suite.gliclass_probe import load_native, render_state
from suite.onejev_probe import append
from suite.progress_correctness.train import DATA, progress_rows
from suite.progress_loto import BASE, f1_report, labels_for, policy_text
from suite.progress_weight_directions import READOUT, head_predictions, prediction_records

SOURCE = DATA/'continuation-20261106T001652Z/epoch-1'


def write(path, obj):
    path.write_text(json.dumps(obj,indent=2)+'\n')


def gpu():
    import torch
    torch.set_num_threads(2)
    torch.set_grad_enabled(False)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    return torch


def panels():
    train = progress_rows(DATA/'train-3000-candidate.jsonl')
    dev = progress_rows(DATA/'dev-600-candidate.jsonl')
    old = json.loads((BASE/'train-cases.json').read_text())
    return [{**r,'panel':panel} for panel,rows in [('train',train),('dev',dev),('old',old)] for r in rows]


def capture(args):
    import numpy as np
    started = time.monotonic()
    torch = gpu()
    model,pipe,loading = load_native(str(args.source),'cuda')
    model.requires_grad_(False)
    hashes = json.loads((BASE/'contract.json').read_text())['policy_sha256']
    args.out.mkdir(parents=True,exist_ok=True)
    part = args.out/f'shard-{args.shard}'
    part.mkdir(exist_ok=False)
    write(part/'run.json',{'source':str(args.source),'shard':args.shard,'shards':args.shards,
        'device':torch.cuda.get_device_name(0),'visible':os.environ.get('CUDA_VISIBLE_DEVICES'),
        'loading':loading,'precision':'native FP32; no autocast', 'gradients':False})
    rows = panels()[args.shard::args.shards]
    found = {}
    def classes(_module,inputs):
        found['classes'] = inputs[0].float().cpu().numpy()[0]
    def relu(_module,_inputs,output):
        found['relu2'] = output.float().cpu().numpy()[0]
    hooks = [model.model.classes_projector.register_forward_pre_hook(classes),
             model.model.scorer.mlp[3].register_forward_hook(relu)]
    saved = defaultdict(list)
    try:
        for index,row in enumerate(rows):
            labels = list(labels_for(row['family']))
            text = pipe.prepare_input(render_state(row['complete_input']),labels,
                                      prompt=policy_text(row['family'],hashes))
            inputs = pipe.tokenizer(text,truncation=False,return_tensors='pt').to('cuda')
            meta = {**row,'labels':labels,'tokens':int(inputs['input_ids'].shape[1])}
            append(part/'calls.jsonl',{'event':'start','id':row['id'],'panel':row['panel'],
                'rendered_input':text,'input_ids':inputs['input_ids'].tolist(),'tokens':meta['tokens']})
            output = model(**inputs,max_num_classes=len(labels),output_text_embeddings=True)
            result = {**prediction_records(output,[meta])[0], 'panel':row['panel'],
                'group':row.get('group',row.get('group_id')),'task':row.get('task')}
            # Variable label counts are padded only in the saved numeric arrays,
            # never in a model-visible input. Valid entries use result['labels'].
            for key in ('classes','relu2'):
                a = found[key]
                saved[key].append(np.pad(a,((0,3-len(labels)),(0,0))))
            saved['text'].append(output.text_embeddings.float().cpu().numpy()[0])
            append(part/'predictions.jsonl',result)
            append(part/'calls.jsonl',{'event':'result',**result,'reasoning':None})
            if (index+1)%100==0:
                print(json.dumps({'completed':index+1,'total':len(rows),'seconds':time.monotonic()-started}),flush=True)
    finally:
        for hook in hooks:
            hook.remove()
    np.savez(part/'activations.npz',**{key:np.stack(value) for key,value in saved.items()})
    write(part/'completed.json',{'rows':len(rows),'seconds':time.monotonic()-started,
        'gpu_peak_reserved_bytes':torch.cuda.max_memory_reserved()})


def cached(out):
    import numpy as np
    rows, arrays = [], defaultdict(list)
    for part in sorted(out.glob('shard-*')):
        if not (part/'completed.json').exists():
            raise ValueError(f'activation collection incomplete: {part}')
        records = [json.loads(s) for s in (part/'predictions.jsonl').read_text().splitlines()]
        data = np.load(part/'activations.npz')
        rows.extend(records)
        for key in data.files:
            arrays[key].append(data[key])
    if len(rows)!=4436 or len({r['id'] for r in rows})!=4436:
        raise ValueError('expected all 4436 unique TRAIN/DEV/old rows')
    return rows,{key:np.concatenate(v) for key,v in arrays.items()}


def metrics(rows, baseline=None):
    import numpy as np
    reports = {}
    for panel in ('train','dev','old'):
        subset = [r for r in rows if r['panel']==panel]
        for family in sorted({r['family'] for r in subset}):
            part = [r for r in subset if r['family']==family]
            labels = labels_for(family)
            stats = f1_report([r['label'] for r in part],[r['prediction'] for r in part],labels)
            if family=='progress':
                matrix = stats['confusion']
                stats['partial_false_done_rate'] = matrix[1][0]/sum(matrix[1])
                stats['done_recall'] = matrix[0][0]/sum(matrix[0])
                stats['done_partial_accuracy'] = (matrix[0][0]+matrix[1][1])/(sum(matrix[0])+sum(matrix[1]))
                groups = defaultdict(dict)
                for r in part:
                    if r['label'] in ('DONE','PARTIAL'):
                        groups[r['group']][r['label']] = r['logits'][0]-r['logits'][1]
                pairs = [v['DONE']-v['PARTIAL'] for v in groups.values() if len(v)==2]
                stats['paired_done_partial_ordering'] = {'correct':sum(v>0 for v in pairs),
                    'total':len(pairs),'mean_margin_difference':float(np.mean(pairs))}
            if baseline is not None:
                stats['changed_predictions'] = [r['id'] for r in part if r['prediction']!=baseline[r['id']]['prediction']]
                stats['correct_to_wrong'] = sum(baseline[r['id']]['prediction']==r['label'] and r['prediction']!=r['label'] for r in part)
                stats['wrong_to_correct'] = sum(baseline[r['id']]['prediction']!=r['label'] and r['prediction']==r['label'] for r in part)
            reports[panel+'/'+family] = stats
    return reports


def solve(args):
    """Only TRAIN labels/activations enter this closed-form regularized solve.

    Freeze beta solely to build a local linear surrogate. Score every candidate
    using the actual calibrator, which recomputes beta/bias from modified logits.
    Targets: DONE/PARTIAL margin +1/-1, paired separation +2; retain their mean
    logit and retain NOT_STARTED raw scores. Exact old-anchor nullspace protects
    32 old TRAIN cases, while the remaining 804 measure transfer.
    """
    import numpy as np
    from safetensors import safe_open
    rows,data = cached(args.out)
    train = [i for i,r in enumerate(rows) if r['panel']=='train']
    old = [i for i,r in enumerate(rows) if r['panel']=='old']
    with safe_open(args.source/'model.safetensors',framework='numpy') as source:
        w = source.get_tensor(READOUT).astype(np.float64).reshape(-1)
    anchors = []
    for family in ('dictation','retrospective'):
        for label in labels_for(family):
            indices = sorted([i for i in old if rows[i]['family']==family and rows[i]['label']==label],
                             key=lambda i:(rows[i]['tokens'],rows[i]['id']))
            anchors += [indices[j] for j in np.linspace(0,len(indices)-1,8,dtype=int)]
    activation = data['relu2'][anchors,:2].reshape(-1,len(w)).astype(np.float64)
    _,singular,right = np.linalg.svd(activation,full_matrices=True)
    rank = int((singular>np.finfo(np.float64).eps*max(activation.shape)*singular[0]).sum())
    null = right[rank:].T
    features,targets,importance = [],[],[]
    family_counts = defaultdict(int)
    for i in train:
        family_counts[rows[i]['task']] += 1
    pair = defaultdict(dict)
    for i in train:
        row = rows[i]
        h = data['relu2'][i].astype(np.float64)
        beta = np.array(row['inverse_temperatures'])
        cal = np.array(row['logits'])
        weight = 1/family_counts[row['task']]
        if row['label'] in ('DONE','PARTIAL'):
            a = beta[0]*h[0]-beta[1]*h[1]
            target = 1 if row['label']=='DONE' else -1
            features.append(a); targets.append(target-(cal[0]-cal[1])); importance.append(weight)
            features.append((beta[0]*h[0]+beta[1]*h[1])/2); targets.append(0); importance.append(weight)
            features.append(beta[2]*h[2]); targets.append(0); importance.append(weight)
            pair[row['group']][row['label']] = (a,cal[0]-cal[1],weight)
        else:
            for c in range(3):
                features.append(beta[c]*h[c]); targets.append(0); importance.append(weight)
    for group in pair.values():
        done,partial = group['DONE'],group['PARTIAL']
        features.append(done[0]-partial[0]); targets.append(2-(done[1]-partial[1])); importance.append(done[2])
    scale = np.sqrt(np.array(importance)/np.mean(importance))
    x = np.stack(features)*scale[:,None]
    y = np.array(targets)*scale
    candidates = {'baseline':w.astype(np.float32)}
    report = {'method':solve.__doc__,'train_rows':len(train),'train_groups':len(pair),
        'anchor_ids':[rows[i]['id'] for i in anchors],'anchor_rank':rank,
        'null_dimension':null.shape[1],'anchor_singular_values':singular.tolist(),
        'source_weight_norm':float(np.linalg.norm(w)),'candidates':{}}
    # A small declared comparison, not an adaptive DEV search. The unrestricted
    # solutions expose the cost of exact anchor protection rather than hide it.
    for protection,basis in [('protected',null),('unprotected',np.eye(len(w)))]:
        a = x@basis
        covariance = a.T@a
        penalty = np.trace(covariance)/max(1,basis.shape[1])
        for relative in (0.01,0.1,1.0):
            coefficient = np.linalg.solve(covariance+relative*penalty*np.eye(basis.shape[1]),a.T@y)
            edited = (w+basis@coefficient).astype(np.float32)
            name = f'{protection}-ridge-{relative:g}'
            candidates[name] = edited
            delta = edited.astype(np.float64)-w
            report['candidates'][name] = {'relative_ridge':relative,'absolute_ridge':float(relative*penalty),
                'delta_norm':float(np.linalg.norm(delta)),'changed_values':int(np.count_nonzero(delta)),
                'max_anchor_raw_score_shift':float(np.max(np.abs(activation@delta))),
                'weighted_train_surrogate_residual_rms':float(np.sqrt(np.mean((x@delta-y)**2)))}
    np.savez(args.out/'candidate-weights.npz',**candidates)
    write(args.out/'solve.json',report)
    print(json.dumps(report,indent=2),flush=True)


def solve_cv(args):
    """Correct the initial solve's scale mismatch, select strength by TRAIN families.

    Each preservation block is normalized by its Frobenius norm, so large
    NOT_STARTED/old/common-mode activations cannot silently dominate the small
    DONE/PARTIAL contrast. Five family-excluded TRAIN folds choose ridge strength;
    DEV does not enter fitting or hyperparameter choice. This remains a linear
    surrogate, not a gradient update or an assumption of a frozen calibrator.
    """
    import numpy as np
    from safetensors import safe_open
    rows,data = cached(args.out)
    idx = [i for i,r in enumerate(rows) if r['panel']=='train' and r['label'] in ('DONE','PARTIAL')]
    old = [i for i,r in enumerate(rows) if r['panel']=='old']
    ns = [i for i,r in enumerate(rows) if r['panel']=='train' and r['label']=='NOT_STARTED']
    with safe_open(args.source/'model.safetensors',framework='numpy') as source:
        w = source.get_tensor(READOUT).astype(np.float64).reshape(-1)
    h = data['relu2'][idx].astype(np.float64)
    beta = np.array([rows[i]['inverse_temperatures'] for i in idx])
    margin = np.array([rows[i]['logits'][0]-rows[i]['logits'][1] for i in idx])
    x = beta[:,0,None]*h[:,0]-beta[:,1,None]*h[:,1]
    target = np.array([1 if rows[i]['label']=='DONE' else -1 for i in idx])
    y = target-margin
    families = sorted({rows[i]['task'] for i in idx})
    fold_of = {family:i%5 for i,family in enumerate(families)}
    folds = np.array([fold_of[rows[i]['task']] for i in idx])
    counts = defaultdict(int)
    for i in idx:
        counts[rows[i]['task']] += 1
    sample_weight = np.array([1/counts[rows[i]['task']] for i in idx])
    sample_weight /= sample_weight.mean()
    common = (beta[:,0,None]*h[:,0]+beta[:,1,None]*h[:,1])/2
    old_h = data['relu2'][old,:2].reshape(-1,len(w)).astype(np.float64)
    ns_h = data['relu2'][ns].astype(np.float64)
    ns_families = [rows[i]['task'] for i in ns]
    anchor_ids = set(json.loads((args.out/'solve.json').read_text())['anchor_ids'])
    anchor = data['relu2'][[i for i in old if rows[i]['id'] in anchor_ids],:2].reshape(-1,len(w)).astype(np.float64)
    _,singular,right = np.linalg.svd(anchor,full_matrices=True)
    rank = int((singular>np.finfo(float).eps*max(anchor.shape)*singular[0]).sum())
    candidates,report = {},{'method':solve_cv.__doc__,'fold_families':{f:fold_of[f] for f in families},'candidates':{}}
    def fit(selected,basis,protect,relative):
        root = np.sqrt(sample_weight[selected])
        a = (x[selected]@basis)*root[:,None]
        b = y[selected]*root
        norm = np.linalg.norm(a)
        blocks = [a]
        answers = [b]
        selected_families = {rows[idx[i]]['task'] for i in np.flatnonzero(selected)}
        ns_block = ns_h[[family in selected_families for family in ns_families]].reshape(-1,len(w))
        for block in [ns_block,common[selected]] + ([old_h] if protect else []):
            projected = block@basis
            length = np.linalg.norm(projected)
            if length:
                blocks.append(projected*(norm/length)); answers.append(np.zeros(len(projected)))
        a = np.concatenate(blocks); b = np.concatenate(answers)
        # Standardize surviving coordinates rather than punish the dominant
        # class-identity direction's scale as though it were correctness signal.
        std = np.sqrt(np.mean((x[selected]@basis)**2,axis=0))
        valid = std>np.finfo(float).eps*max(1,float(std.max()))
        a = a[:,valid]/std[valid]
        covariance = a.T@a
        penalty = relative*np.trace(covariance)/len(covariance)
        coef = np.linalg.solve(covariance+penalty*np.eye(len(covariance)),a.T@b)
        delta = np.zeros(basis.shape[1]); delta[valid] = coef/std[valid]
        return basis@delta
    for name,basis,protect in [('balanced-soft-old',np.eye(len(w)),True),
                               ('balanced-unprotected',np.eye(len(w)),False),
                               ('balanced-exact-old',right[rank:].T,False)]:
        scores = []
        for relative in (0.0001,0.001,0.01,0.1,1.0):
            oof = np.empty(len(idx))
            for fold in range(5):
                delta = fit(folds!=fold,basis,protect,relative)
                oof[folds==fold] = margin[folds==fold]+x[folds==fold]@delta
            correct = (np.sign(oof)==target)
            scores.append({'relative_ridge':relative,'family_weighted_oof_accuracy':float(np.average(correct,weights=sample_weight)),
                'oof_correct':int(correct.sum()),'count':len(idx)})
        best = max(scores,key=lambda r:(r['family_weighted_oof_accuracy'],r['relative_ridge']))
        delta = fit(np.ones(len(idx),bool),basis,protect,best['relative_ridge'])
        edited = (w+delta).astype(np.float32)
        actual_delta = edited.astype(np.float64)-w
        candidates[name] = edited
        report['candidates'][name] = {'train_cv':scores,'selected_relative_ridge':best['relative_ridge'],
            'delta_norm':float(np.linalg.norm(actual_delta)),'changed_values':int(np.count_nonzero(actual_delta)),
            'max_anchor_raw_shift':float(np.max(np.abs(anchor@actual_delta)))}
    np.savez(args.out/'balanced-weights.npz',**candidates)
    write(args.out/'balanced-solve.json',report)
    print(json.dumps(report,indent=2),flush=True)


def replay(args):
    import numpy as np
    torch = gpu()
    rows,data = cached(args.out)
    model,_pipe,_loading = load_native(str(args.source),'cuda')
    model.requires_grad_(False)
    candidates = np.load(args.out/args.weights)
    summaries = {}
    baseline = {r['id']:r for r in rows}
    for name in candidates.files:
        model.state_dict()[READOUT].copy_(torch.from_numpy(candidates[name].reshape(1,-1)).to('cuda'))
        records = []
        for family in ('progress','dictation','retrospective'):
            indices = [i for i,r in enumerate(rows) if r['family']==family]
            nlabels = len(labels_for(family))
            for start in range(0,len(indices),64):
                idx = indices[start:start+64]
                batch = [rows[i] for i in idx]
                append(args.out/'replay-calls.jsonl',{'event':'start','candidate':name,'ids':[r['id'] for r in batch]})
                result = head_predictions(model,torch,torch.from_numpy(data['text'][idx]).to('cuda'),
                    torch.from_numpy(data['classes'][idx,:nlabels]).to('cuda'),batch)
                for original,prediction in zip(batch,result):
                    rec = {**original,**prediction}
                    records.append(rec)
                    append(args.out/f'{name}-predictions.jsonl',rec)
                append(args.out/'replay-calls.jsonl',{'event':'result','candidate':name,'rows':len(result)})
        summaries[name] = metrics(records,baseline)
        if name=='baseline':
            summaries[name]['replay_fidelity'] = {'changed_predictions':sum(r['prediction']!=baseline[r['id']]['prediction'] for r in records),
                'max_logit_error':max(abs(a-b) for r in records for a,b in zip(r['logits'],baseline[r['id']]['logits']))}
        write(args.out/f'{args.stage}replay-summary.json',summaries)
        print(json.dumps({'candidate':name,'dev':summaries[name]['dev/progress'],
            'old_changes':sum(len(summaries[name]['old/'+f]['changed_predictions']) for f in ('dictation','retrospective'))}),flush=True)


def native(args):
    """Confirm a selected edit through the whole encoder; save it separately."""
    import numpy as np
    torch = gpu()
    model,pipe,_loading = load_native(str(args.source),'cuda')
    model.requires_grad_(False)
    weights = np.load(args.out/args.weights)[args.candidate]
    tensor = model.state_dict()[args.tensor]
    tensor.copy_(torch.from_numpy(weights.reshape(tuple(tensor.shape))).to('cuda'))
    hashes = json.loads((BASE/'contract.json').read_text())['policy_sha256']
    part = args.out/f'{args.confirmation_prefix}{args.shard}'
    part.mkdir(exist_ok=False)
    selected = [r for r in panels() if r['panel'] in ('dev','old')][args.shard::args.shards]
    started = time.monotonic()
    for index,row in enumerate(selected):
        labels = list(labels_for(row['family']))
        text = pipe.prepare_input(render_state(row['complete_input']),labels,prompt=policy_text(row['family'],hashes))
        inputs = pipe.tokenizer(text,truncation=False,return_tensors='pt').to('cuda')
        meta = {**row,'labels':labels,'tokens':int(inputs['input_ids'].shape[1])}
        append(part/'calls.jsonl',{'event':'start','candidate':args.candidate,'id':row['id'],
            'rendered_input':text,'input_ids':inputs['input_ids'].tolist()})
        output = model(**inputs,max_num_classes=len(labels))
        result = {**prediction_records(output,[meta])[0],'panel':row['panel'],
            'group':row.get('group',row.get('group_id'))}
        append(part/'calls.jsonl',{'event':'result',**result,'reasoning':None})
        append(part/'predictions.jsonl',result)
        if (index+1)%100==0:
            print(json.dumps({'completed':index+1,'total':len(selected),'seconds':time.monotonic()-started}),flush=True)
    if args.shard==0:
        checkpoint = args.out/args.checkpoint_name
        model.save_pretrained(checkpoint,safe_serialization=True,max_shard_size='4GB')
        pipe.tokenizer.save_pretrained(checkpoint)
        # Verify every persisted tensor against the original, not just the row
        # whose in-memory assignment we intended to make. No inference here.
        from safetensors import safe_open
        changed = {}
        with safe_open(args.source/'model.safetensors',framework='pt') as source, safe_open(checkpoint/'model.safetensors',framework='pt') as saved:
            if set(source.keys())!=set(saved.keys()):
                raise ValueError('saved checkpoint tensor keys differ from source')
            for key in source.keys():
                a,b = source.get_tensor(key),saved.get_tensor(key)
                if a.shape!=b.shape or a.dtype!=b.dtype:
                    raise ValueError('saved checkpoint tensor metadata differs from source')
                count = int((a!=b).sum())
                if count:
                    changed[key] = count
        if set(changed)!={args.tensor}:
            raise ValueError('unexpected tensor changes when saving edited checkpoint')
        write(checkpoint/'repair.json',{'source':str(args.source),'candidate':args.candidate,
            'weights':args.weights,'changed_values_by_tensor':changed,'gradient_updates':0,
            'construction':args.selection_context,
            'deployed':False,'published':False})
    write(part/'completed.json',{'rows':len(selected),'candidate':args.candidate,
        'seconds':time.monotonic()-started,'gpu_peak_reserved_bytes':torch.cuda.max_memory_reserved()})


def summarize(args):
    rows,_data = cached(args.out)
    source = {r['id']:r for r in rows}
    replayed = {r['id']:r for r in [json.loads(s) for s in (args.out/f'{args.candidate}-predictions.jsonl').read_text().splitlines()]}
    records,resources = [],{}
    for shard in range(args.shards):
        part = args.out/f'native-{shard}'
        resources[str(shard)] = json.loads((part/'completed.json').read_text())
        records.extend(json.loads(s) for s in (part/'predictions.jsonl').read_text().splitlines())
    expected = {r['id'] for r in rows if r['panel'] in ('dev','old')}
    if len(records)!=len(expected) or {r['id'] for r in records}!=expected:
        raise ValueError('native confirmation missing or duplicating inputs')
    difference = {'changed_predictions':[r['id'] for r in records if r['prediction']!=replayed[r['id']]['prediction']],
        'max_logit_error':max(abs(a-b) for r in records for a,b in zip(r['logits'],replayed[r['id']]['logits']))}
    baseline_metrics = metrics(rows)
    # Metrics expects all three panels. TRAIN uses the already recorded actual
    # head replay, not an invented full-native rerun or additional fitting.
    full = records+[r for r in replayed.values() if r['panel']=='train']
    result = {'source':str(args.source),'candidate':args.candidate,
        'checkpoint':str(args.out/'checkpoint'),
        'baseline':baseline_metrics,'candidate_metrics':metrics(full,source),
        'full_native_confirmation':difference,'resources':resources,
        'saved_checkpoint_verification':json.loads((args.out/'checkpoint/repair.json').read_text()),
        'native_rows':len(records),'train_metrics':'actual cached-head replay with real calibrator',
        'test_accessed':False,'gradient_updates':0,'deployed':False,'published':False,
        'selection':'highest DEV macro-F1 among nine TRAIN-constructed readout edits; old-family TRAIN decisions unchanged',
        'limitations':'Exploratory DEV-selected result; old preservation panel is exposed TRAIN replay, not independent certification; no new TEST evaluation or INT4 conversion.'}
    write(args.out/'result.json',result)
    print(json.dumps({k:result[k] for k in ['candidate','checkpoint','full_native_confirmation','native_rows','saved_checkpoint_verification']},indent=2),flush=True)


def reload_check(args):
    """One DEV forward after reloading the actual saved standalone checkpoint."""
    import numpy as np
    torch = gpu()
    model,pipe,loading = load_native(str(args.out/args.checkpoint_name),'cuda')
    model.requires_grad_(False)
    row = next(r for r in panels() if r['panel']=='dev')
    recorded = {r['id']:r for r in [json.loads(s) for s in (args.out/f'{args.candidate}-predictions.jsonl').read_text().splitlines()]}
    labels = list(labels_for(row['family']))
    text = pipe.prepare_input(render_state(row['complete_input']),labels,prompt=policy_text('progress',{}))
    inputs = pipe.tokenizer(text,truncation=False,return_tensors='pt').to('cuda')
    values = model(**inputs,max_num_classes=len(labels)).logits[0].float().cpu().tolist()
    difference = float(np.max(np.abs(np.array(values)-recorded[row['id']]['logits'])))
    report = {'id':row['id'],'rendered_input':text,'logits':values,'reasoning':None,
        'prediction':labels[int(np.argmax(values))], 'cached_head_prediction':recorded[row['id']]['prediction'],
        'maximum_logit_difference':difference,'loading':loading,'source':str(args.out/args.checkpoint_name),
        'test_accessed':False}
    reload_prefix = '' if args.confirmation_prefix=='native-' else args.confirmation_prefix
    write(args.out/f'{reload_prefix}saved-checkpoint-reload.json',report)
    print(json.dumps(report),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['capture','solve','solve-cv','replay','native','summarize','reload'])
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--candidate')
    parser.add_argument('--tensor',default=READOUT)
    parser.add_argument('--confirmation-prefix',default='native-')
    parser.add_argument('--checkpoint-name',default='checkpoint')
    parser.add_argument('--selection-context',default='TRAIN only; DEV selection; consumed TEST excluded')
    parser.add_argument('--weights',default='candidate-weights.npz')
    parser.add_argument('--stage',default='')
    parser.add_argument('--shard',type=int,default=0)
    parser.add_argument('--shards',type=int,default=2)
    args = parser.parse_args()
    {'capture':capture,'solve':solve,'solve-cv':solve_cv,'replay':replay,'native':native,'summarize':summarize,'reload':reload_check}[args.command](args)


if __name__=='__main__':
    main()
