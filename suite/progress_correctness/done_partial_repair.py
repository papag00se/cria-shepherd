"""Gradient-free DONE/PARTIAL score edits with explicit preservation inequalities.

The linear program fits TRAIN margins, not aggregate accuracy. Source-correct
DONE/PARTIAL and old decisions, plus PARTIAL cases not currently approved DONE,
are protected. Optional exposed DEV/benchmark protection is disclosed in results.
For a scorer readout edit the constraints use a frozen-beta surrogate. For the
calibrator's bias output row they are exact: its inputs and beta output do not
change. Every candidate is still evaluated with the actual native calibrator.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from suite.progress_correctness.repair import SOURCE, cached, write
from suite.progress_weight_directions import READOUT


CALIBRATOR = 'calibrator.mlp.6.weight'


def capture_calibrator(args):
    """Cache the final calibrator input; changing its bias row is exactly linear."""
    import numpy as np
    from suite.progress_correctness.repair import gpu
    from suite.gliclass_probe import load_native
    from suite.progress_dataset import LABELS
    from suite.progress_weight_directions import head_predictions
    from suite.onejev_probe import append
    rows,data = cached(args.repair)
    original = [json.loads(s) for s in args.baseline.read_text().splitlines()]
    arrays = np.load(args.benchmark_capture/'activations.npz')
    benchmark_rows = [json.loads(s) for s in (args.benchmark_capture/'predictions.jsonl').read_text().splitlines()]
    index = {r['id']:i for i,r in enumerate(benchmark_rows)}
    order = [index[r['id']] for r in original]
    rows += [{**r,'family':'progress','task':r['family'],'labels':list(LABELS),'panel':'benchmark'} for r in original]
    data = {k:np.concatenate([data[k],arrays[k][order]]) for k in ('text','classes')}
    torch = gpu()
    model,_pipe,loading = load_native(str(SOURCE),'cuda')
    model.requires_grad_(False)
    found = {}
    def hook(_module,inputs):
        found['features'] = inputs[0].float().cpu().numpy()
    handle = model.calibrator.mlp[-1].register_forward_pre_hook(hook)
    part = args.out/f'calibration-{args.shard}'
    part.mkdir(parents=True,exist_ok=False)
    write(part/'run.json',{'source':str(SOURCE),'loading':loading,'gradients':False,
        'edited_tensor':CALIBRATOR,'edited_row':1,'beta_row_unchanged':True})
    saved = []
    selected = list(range(len(rows)))[args.shard::2]
    try:
        for count in (2,3):
            indices = [i for i in selected if len(rows[i]['labels'])==count]
            for start in range(0,len(indices),64):
                idx = indices[start:start+64]
                batch = [rows[i] for i in idx]
                append(part/'calls.jsonl',{'event':'start','ids':[r['id'] for r in batch]})
                outputs = head_predictions(model,torch,torch.from_numpy(data['text'][idx]).to('cuda'),
                    torch.from_numpy(data['classes'][idx,:count]).to('cuda'),batch)
                features = found['features']
                for j,(before,after) in enumerate(zip(batch,outputs)):
                    append(part/'predictions.jsonl',{**before,**after})
                    saved.append(np.pad(features[j],((0,3-count),(0,0))))
                append(part/'calls.jsonl',{'event':'result','rows':outputs})
    finally:
        handle.remove()
    np.savez(part/'activations.npz',features=np.stack(saved))
    write(part/'completed.json',{'rows':len(saved),'gpu_peak_reserved_bytes':torch.cuda.max_memory_reserved()})


def calibrated_cache(path):
    import numpy as np
    rows,features = [],[]
    for shard in range(2):
        part = path/f'calibration-{shard}'
        rows.extend(json.loads(s) for s in (part/'predictions.jsonl').read_text().splitlines())
        features.append(np.load(part/'activations.npz')['features'])
    if len(rows)!=5036 or len({r['id'] for r in rows})!=5036:
        raise ValueError('expected 5036 distinct captured inputs')
    return rows,np.concatenate(features)


def solve(args):
    import numpy as np
    from safetensors import safe_open
    from scipy.optimize import linprog
    from scipy.sparse import csr_matrix, eye, hstack, vstack

    args.out.mkdir(parents=True,exist_ok=False)
    if args.calibrator_cache:
        rows,h = calibrated_cache(args.calibrator_cache)
    else:
        rows,data = cached(args.repair)
        h = data['relu2']
    h = h.astype(np.float64)
    beta = np.zeros(h.shape[:2])
    logits = np.zeros(h.shape[:2])
    for i,row in enumerate(rows):
        count = len(row['labels'])
        beta[i,:count] = row['inverse_temperatures']
        logits[i,:count] = row['logits']
    feature = h if args.calibrator_cache else beta[:,:,None]*h
    fit = [i for i,r in enumerate(rows) if r['panel']=='train' and r['label'] in ('DONE','PARTIAL')]
    x = feature[fit,0]-feature[fit,1]
    margin = logits[fit,0]-logits[fit,1]
    sign = np.array([1 if rows[i]['label']=='DONE' else -1 for i in fit])
    scale = np.sqrt(np.mean(x*x,axis=0))
    active = scale>max(scale.max()*1e-10,np.finfo(float).eps)
    scale = scale[active]
    counts = Counter(rows[i]['task'] for i in fit)
    importance = np.array([1/counts[rows[i]['task']] for i in fit])
    importance /= importance.sum()
    groups = defaultdict(dict)
    for j,i in enumerate(fit):
        groups[rows[i]['group']][rows[i]['label']] = j
    pair = [(g['DONE'],g['PARTIAL']) for g in groups.values()]
    pair_x = np.stack([x[d]-x[p] for d,p in pair])
    pair_margin = np.array([margin[d]-margin[p] for d,p in pair])
    a = np.concatenate([sign[:,None]*x,pair_x])[:,active]/scale
    before = np.concatenate([sign*margin,pair_margin])
    importance = np.concatenate([importance,np.array([importance[d]+importance[p] for d,p in pair])])
    importance /= importance.sum()

    protection,limits,protected = [],[],Counter()
    for i,row in enumerate(rows):
        if row['panel'] not in (('train','old','dev','benchmark') if args.protect_exposed else ('train','old')):
            continue
        labels = row['labels']
        winner = labels.index(row['prediction'])
        pairs = set()
        if row['prediction']==row['label']:
            pairs.update((winner,k) for k in range(len(labels)) if k!=winner)
        if row['label']=='PARTIAL' and row['prediction']!='DONE':
            pairs.add((winner,0))
        for win,lose in sorted(pairs):
            gap = logits[i,win]-logits[i,lose]
            protection.append(-(feature[i,win]-feature[i,lose])[active]/scale)
            limits.append(gap-min(0.01,gap/2))
            protected[row['panel']+'/'+row['label']] += 1
    p,n = int(active.sum()),len(a)
    preserve = csr_matrix(np.stack(protection))
    zeros = csr_matrix((len(protection),p+n))
    absolute = eye(p,format='csr')
    constraint = vstack([
        hstack([preserve,zeros]),
        hstack([absolute,-absolute,csr_matrix((p,n))]),
        hstack([-absolute,-absolute,csr_matrix((p,n))]),
        hstack([csr_matrix(-a),csr_matrix((n,p)),-eye(n,format='csr')]),
    ],format='csr')
    with safe_open(SOURCE/'model.safetensors',framework='numpy') as source:
        original = source.get_tensor(CALIBRATOR if args.calibrator_cache else READOUT)
        w = (original[1] if args.calibrator_cache else original.reshape(-1)).astype(np.float64)
    weights,details = {},{}
    for target in (0.05,0.2):
        wanted = np.concatenate([np.full(len(fit),target),np.full(len(pair),2*target)])
        rhs = np.concatenate([limits,np.zeros(2*p),before-wanted])
        for regularization in (0.001,0.01):
            objective = np.concatenate([np.zeros(p),np.full(p,regularization/p),importance])
            result = linprog(objective,A_ub=constraint,b_ub=rhs,
                bounds=[(None,None)]*p+[(0,None)]*(p+n),method='highs-ds')
            if not result.success:
                raise RuntimeError(result.message)
            delta = np.zeros_like(w)
            delta[active] = result.x[:p]/scale
            prefix = 'dp-calibration-lp' if args.calibrator_cache else 'dp-lp'
            name = f'{prefix}-margin{target:g}-l1{regularization:g}'
            details[name] = {'objective':float(result.fun),'iterations':result.nit,
                'full_delta_norm':float(np.linalg.norm(delta)),
                'max_surrogate_protection_violation':float(np.max(preserve@result.x[:p]-limits)),
                'train_signed_margin_before_mean':float(np.mean(sign*margin)),
                'train_signed_margin_after_mean':float(np.mean(sign*(margin+x@delta)))}
            for amount in (0.25,0.5,1.0):
                edited = (w+amount*delta).astype(np.float32)
                if args.calibrator_cache:
                    matrix = original.copy(); matrix[1] = edited
                    edited = matrix
                weights[f'{name}-step{amount:g}'] = edited
    np.savez(args.out/'weights.npz',**weights)
    write(args.out/'solve.json',{'method':__doc__,'source':str(SOURCE),'tensor':CALIBRATOR if args.calibrator_cache else READOUT,
        'calibrator_bias_only':bool(args.calibrator_cache),
        'linear_effect':'exact additive calibrated-logit change' if args.calibrator_cache else 'local frozen-beta surrogate; native calibration may differ',
        'fit_objective':'TRAIN only',
        'protection_panels':['train','old','dev','benchmark'] if args.protect_exposed else ['train','old'],
        'benchmark_enters_weight_solve':bool(args.protect_exposed),
        'benchmark_use':'explicit exposed-benchmark preservation constraints and later selection' if args.protect_exposed else 'selection only; no benchmark labels/activations in solve',
        'fit_rows':len(fit),'paired_groups':len(pair),'active_coordinates':p,
        'protected_inequalities':dict(protected),'candidates':details,
        'gradients':False,'gradient_optimizer_steps':0,'linear_solver':'SciPy HiGHS dual simplex',
        'native_calibrator_must_be_recomputed':True})
    print(json.dumps(details,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--calibrator-cache',type=Path)
    parser.add_argument('--protect-exposed',action='store_true')
    parser.add_argument('--capture-calibrator',action='store_true')
    parser.add_argument('--benchmark-capture',type=Path)
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--shard',type=int,choices=(0,1),default=0)
    args=parser.parse_args()
    if args.capture_calibrator:
        if args.benchmark_capture is None or args.baseline is None:
            parser.error('calibrator capture requires --benchmark-capture and --baseline')
        capture_calibrator(args)
    else:
        solve(args)
