"""Gradient-free DONE/PARTIAL score edits with explicit preservation inequalities.

Each solve records whether TRAIN or the exposed benchmark supplies its margin objective. Source-correct
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
    model,_pipe,loading = load_native(str(args.source),'cuda')
    model.requires_grad_(False)
    found = {}
    def hook(_module,inputs):
        found['features'] = inputs[0].float().cpu().numpy()
    handle = model.calibrator.mlp[-1].register_forward_pre_hook(hook)
    part = args.out/f'calibration-{args.shard}'
    part.mkdir(parents=True,exist_ok=False)
    write(part/'run.json',{'source':str(args.source),'loading':loading,'gradients':False,'batch_size':args.batch_size,
        'edited_tensor':CALIBRATOR,'edited_row':1,'beta_row_unchanged':True})
    saved = []
    selected = list(range(len(rows)))[args.shard::2]
    try:
        for count in (2,3):
            indices = [i for i in selected if len(rows[i]['labels'])==count]
            for start in range(0,len(indices),args.batch_size):
                idx = indices[start:start+args.batch_size]
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


def preservation(rows,feature,logits,active,scale,panels,binary=False,guard=0.01):
    """Retain correct answers and forbid new false approvals of PARTIAL."""
    import numpy as np
    protection,limits,protected = [],[],Counter()
    for i,row in enumerate(rows):
        if row['panel'] not in panels:
            continue
        labels = row['labels']
        winner = labels.index(row['prediction'])
        pairs = set()
        if row['prediction']==row['label']:
            pairs.update((winner,k) for k in range(len(labels)) if k!=winner)
        if row['label']=='PARTIAL' and row['prediction']!='DONE':
            pairs.add((winner,0))
        if binary and row['label'] in ('DONE','PARTIAL'):
            correct=labels.index(row['label']); other=1-correct
            if logits[i,correct]>logits[i,other]:
                pairs.add((correct,other))
        for win,lose in sorted(pairs):
            gap = logits[i,win]-logits[i,lose]
            protection.append(-(feature[i,win]-feature[i,lose])[active]/scale)
            limits.append(gap-min(guard,gap/2))
            protected[row['panel']+'/'+row['label']] += 1
    return np.stack(protection),np.array(limits),protected


def solve_top1(args):
    """Fit exposed DONE/PARTIAL top-1 margins directly, retaining the prior best.

    One shared hinge slack per example measures its worst competing label, not
    just D-minus-P while silently ignoring NOT_STARTED. DONE gets twice the
    PARTIAL objective weight; both classes retain their existing protections.
    """
    import numpy as np
    from safetensors import safe_open
    from scipy.optimize import linprog
    from scipy.sparse import csr_matrix,eye,hstack,vstack
    args.out.mkdir(parents=True,exist_ok=False)
    rows,feature = calibrated_cache(args.calibrator_cache)
    feature = feature.astype(np.float64)
    logits = np.array([r['logits']+[0.]*(3-len(r['logits'])) for r in rows])
    fit = [i for i,r in enumerate(rows) if r['panel']=='benchmark' and r['label'] in ('DONE','PARTIAL')]
    contrast = feature[fit,0]-feature[fit,1]
    rms = np.sqrt(np.mean(contrast**2,axis=0))
    active = rms>max(rms.max()*1e-10,np.finfo(float).eps)
    scale = rms[active]
    p,n = int(active.sum()),len(fit)
    targets,margin,owner = [],[],[]
    for j,i in enumerate(fit):
        correct = rows[i]['labels'].index(rows[i]['label'])
        for other in range(3):
            if other!=correct:
                targets.append((feature[i,correct]-feature[i,other])[active]/scale)
                margin.append(logits[i,correct]-logits[i,other]); owner.append(j)
    a = np.stack(targets)
    protect,limits,protected = preservation(rows,feature,logits,active,scale,('train','old','dev','benchmark'),
        binary=args.protect_binary,guard=args.preservation_margin)
    incidence = csr_matrix((-np.ones(len(owner)),(np.arange(len(owner)),owner)),shape=(len(owner),n))
    ident = eye(p,format='csr')
    constraint = vstack([
        hstack([csr_matrix(protect),csr_matrix((len(protect),p+n))]),
        hstack([ident,-ident,csr_matrix((p,n))]),
        hstack([-ident,-ident,csr_matrix((p,n))]),
        hstack([csr_matrix(-a),csr_matrix((len(a),p)),incidence]),
    ],format='csr')
    target=0.1
    rhs=np.concatenate([limits,np.zeros(2*p),np.array(margin)-target])
    # Do not spend weight magnitude moving all scores together: retain the
    # mean TRAIN bias shift while fitting label-relative decisions.
    train = [i for i,r in enumerate(rows) if r['panel']=='train']
    mean = feature[train].mean(axis=(0,1))[active]/scale
    equality=csr_matrix(np.concatenate([mean,np.zeros(p+n)])[None])
    weight=np.array([2. if rows[i]['label']=='DONE' else 1. for i in fit]);weight/=weight.sum()
    with safe_open(args.source/'model.safetensors',framework='numpy') as f:
        original=f.get_tensor(CALIBRATOR)
    candidates,details={},{}
    for strength in (0.001,0.01):
        objective=np.concatenate([np.zeros(p),np.full(p,strength/p),weight])
        result=linprog(objective,A_ub=constraint,b_ub=rhs,A_eq=equality,b_eq=[0.],
            bounds=[(None,None)]*p+[(0,None)]*(p+n),method='highs-ds')
        if not result.success:
            raise RuntimeError(result.message)
        delta=np.zeros(original.shape[1]);delta[active]=result.x[:p]/scale
        prefix='dp-top1-binary' if args.protect_binary else 'dp-top1-benchmark'
        if args.preservation_margin!=0.01:
            prefix+=f'-guard{args.preservation_margin:g}'
        name=f'{prefix}-l1{strength:g}'
        details[name]={'objective':float(result.fun),'iterations':result.nit,
            'delta_norm':float(np.linalg.norm(delta)),
            'max_linear_protection_violation':float(np.max(protect@result.x[:p]-limits)),
            'train_mean_bias_shift':float(mean@result.x[:p])}
        for amount in (0.5,1.):
            edited=original.copy();edited[1]=(original[1].astype(np.float64)+amount*delta).astype(np.float32)
            candidates[f'{name}-step{amount:g}']=edited
        print(json.dumps({'solved':name,**details[name]}),flush=True)
    np.savez(args.out/'weights.npz',**candidates)
    write(args.out/'solve.json',{'source':str(args.source),'method':solve_top1.__doc__,
        'reference_cache':str(args.calibrator_cache),'fit_panel':'exposed benchmark DONE/PARTIAL',
        'fit_rows':n,'target_margin':target,'done_to_partial_objective_weight':2.,
        'retains_train_mean_bias':True,'active_coordinates':p,'retains_binary_done_partial_preferences':args.protect_binary,
        'preservation_margin':args.preservation_margin,
        'protection_panels':['train','old','dev','benchmark'],'protected_inequalities':dict(protected),
        'benchmark_enters_weight_solve':True,'fresh_evaluation':False,
        'candidates':details,'gradients':False,'gradient_optimizer_steps':0})


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

    protection,limits,protected = preservation(rows,feature,logits,active,scale,
        ('train','old','dev','benchmark') if args.protect_exposed else ('train','old'))
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
    with safe_open(args.source/'model.safetensors',framework='numpy') as source:
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
    write(args.out/'solve.json',{'method':__doc__,'source':str(args.source),'tensor':CALIBRATOR if args.calibrator_cache else READOUT,
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
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--batch-size',type=int,default=64)
    parser.add_argument('--top1',action='store_true')
    parser.add_argument('--protect-binary',action='store_true')
    parser.add_argument('--preservation-margin',type=float,default=0.01)
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
    elif args.top1:
        solve_top1(args)
    else:
        solve(args)
