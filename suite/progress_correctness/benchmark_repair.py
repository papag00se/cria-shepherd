"""Compare existing TRAIN-constructed weight edits on an exposed benchmark.

The operator explicitly authorized reuse of the original synthetic TEST as a
working development benchmark. This is not a fresh blind generalization score.
No label from this benchmark enters the weight solve; its metrics may select an
existing candidate. No gradients, source mutation, deployment or publication.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from suite.gliclass_probe import load_native
from suite.onejev_probe import append
from suite.progress_correctness.repair import SOURCE, cached, gpu, write
from suite.progress_dataset import LABELS
from suite.progress_loto import f1_report
from suite.progress_weight_directions import READOUT, head_predictions


def report(rows, baseline):
    result = f1_report([r['label'] for r in rows],[r['prediction'] for r in rows])
    m = result['confusion']
    result.update(partial_false_done_rate=m[1][0]/sum(m[1]),done_recall=m[0][0]/sum(m[0]),
        not_started_recall=m[2][2]/sum(m[2]),done_partial_accuracy=(m[0][0]+m[1][1])/(sum(m[0])+sum(m[1])),
        done_precision=m[0][0]/sum(row[0] for row in m) if sum(row[0] for row in m) else None,
        correct_to_wrong=sum(baseline[r['id']]['prediction']==r['label'] and r['prediction']!=r['label'] for r in rows),
        wrong_to_correct=sum(baseline[r['id']]['prediction']!=r['label'] and r['prediction']==r['label'] for r in rows))
    return result


def directions(args):
    """Construct a progress-vs-NOT_STARTED adjustment from TRAIN activations.

    The exposed benchmark identifies the error to investigate; no benchmark
    activations/labels enter this solve. Protect the mean DONE/PARTIAL contrast,
    optionally also 32 old TRAIN raw-score margins, then measure real outcomes.
    """
    import numpy as np
    from safetensors import safe_open
    rows,data = cached(args.repair)
    idx = [i for i,r in enumerate(rows) if r['panel']=='train' and r['label'] in ('DONE','PARTIAL')]
    h = data['relu2'][idx].astype(np.float64)
    beta = np.array([rows[i]['inverse_temperatures'] for i in idx])
    progress = ((beta[:,0,None]*h[:,0]+beta[:,1,None]*h[:,1])/2-beta[:,2,None]*h[:,2]).mean(axis=0)
    done_partial = (beta[:,0,None]*h[:,0]-beta[:,1,None]*h[:,1]).mean(axis=0)
    anchors = set(json.loads((args.repair/'solve.json').read_text())['anchor_ids'])
    old = data['relu2'][[i for i,r in enumerate(rows) if r['id'] in anchors],:2].astype(np.float64)
    with safe_open(SOURCE/'model.safetensors',framework='numpy') as source:
        w = source.get_tensor(READOUT).reshape(-1).astype(np.float64)
    candidates,details = {},{}
    for name,protection in [('dp-preserved',done_partial[None]),
        ('old-margin-preserved',np.concatenate([done_partial[None],old[:,0]-old[:,1]]))]:
        _,s,right = np.linalg.svd(protection,full_matrices=False)
        rank = int((s>np.finfo(float).eps*max(protection.shape)*s[0]).sum())
        orthogonal = progress-right[:rank].T@(right[:rank]@progress)
        vector = orthogonal/(progress@orthogonal)
        details[name] = {'protected_rank':rank,'update_norm_per_unit':float(np.linalg.norm(vector)),
            'mean_done_partial_response':float(done_partial@vector),
            'max_protection_residual':float(np.max(np.abs(protection@vector)))}
        for amount in (1,2,4,8,16):
            candidates[f'progress-{name}-{amount}'] = (w+amount*vector).astype(np.float32)
    np.savez(args.capture/'progress-rebalance-weights.npz',**candidates)
    write(args.capture/'progress-rebalance-solve.json',{'method':directions.__doc__,
        'source':str(SOURCE),'train_inputs':len(idx),'directions':details,'amounts':[1,2,4,8,16],
        'benchmark_used_to_construct_direction':False})


def capture_nuisance(args):
    """TRAIN-only counterfactual: same implementation plus unused Python helper."""
    import numpy as np
    import re
    from suite.progress_correctness.repair import panels
    from suite.gliclass_probe import render_state
    from suite.progress_dataset import render_state as progress_state
    from suite.progress_loto import progress_policy
    rows,_data = cached(args.repair)
    original = {r['id']:r for r in rows}
    eligible = []
    for row in panels():
        if row['panel']!='train' or row['label'] not in ('DONE','PARTIAL'):
            continue
        evidence = row['evidence']
        files = re.findall(r'^\+\+\+ b/(.+)$',evidence,re.M)
        hunks = list(re.finditer(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$',evidence,re.M))
        if not files or not files[-1].endswith('.py') or not hunks or '\\ No newline' in evidence:
            continue
        if '__auxiliary_display_text' in evidence:
            continue
        hunk = hunks[-1]
        header = f'@@ -{hunk[1]},{hunk[2] or 1} +{hunk[3]},{int(hunk[4] or 1)+4} @@{hunk[5]}'
        changed = evidence[:hunk.start()]+header+evidence[hunk.end():]
        changed = changed.rstrip('\n')+'\n+\n+\n+def __auxiliary_display_text():\n+    return "Field notes"'
        eligible.append({**row,'counterfactual_evidence':changed})
    selected,groups = [],set()
    for row in sorted(eligible,key=lambda r:(r['task'],r['group'],r['label'])):
        group = row['group']
        if group not in groups and len(groups)>=64:
            continue
        groups.add(group)
        selected.append(row)
    selected = selected[args.shard::2]
    part = args.capture/f'nuisance-{args.shard}'
    part.mkdir(exist_ok=False)
    torch = gpu()
    model,pipe,_loading = load_native(str(SOURCE),'cuda')
    model.requires_grad_(False)
    saved,found = [],{}
    def hook(_module,_inputs,output):
        found['h'] = output.float().cpu().numpy()[0]
    handle = model.model.scorer.mlp[3].register_forward_hook(hook)
    try:
        for row in selected:
            state = progress_state(row['requirement'],row['counterfactual_evidence'])
            text = pipe.prepare_input(render_state(state),list(LABELS),prompt=progress_policy())
            inputs = pipe.tokenizer(text,truncation=False,return_tensors='pt').to('cuda')
            output = model(**inputs,max_num_classes=len(LABELS))
            logits = output.logits[0].float().cpu().tolist()
            result = {'id':row['id'],'group':row['group'],'label':row['label'],'rendered_input':text,
                'logits':logits,'uncalibrated_logits':output.uncalibrated_logits[0].float().cpu().tolist(),
                'prediction':LABELS[int(output.logits[0].argmax())],
                'original_prediction':original[row['id']]['prediction'],
                'input_ids':inputs['input_ids'].tolist(),'reasoning':None}
            append(part/'calls.jsonl',result)
            saved.append(found['h'])
    finally:
        handle.remove()
    np.savez(part/'activations.npz',relu2=np.stack(saved))
    write(part/'completed.json',{'rows':len(selected),'original_label_preserved':'unused auxiliary function added; original implementation unchanged; no fixture rerun',
        'false_not_started':sum(json.loads(s)['prediction']=='NOT_STARTED' for s in (part/'calls.jsonl').read_text().splitlines())})


def nuisance_directions(args):
    """Erase response to TRAIN-only paired nuisance, not benchmark labels."""
    import numpy as np
    from safetensors import safe_open
    rows,data = cached(args.repair)
    index = {r['id']:i for i,r in enumerate(rows)}
    deltas = []
    calls = []
    for shard in range(2):
        part = args.capture/f'nuisance-{shard}'
        current = [json.loads(s) for s in (part/'calls.jsonl').read_text().splitlines()]
        h = np.load(part/'activations.npz')['relu2'].astype(np.float64)
        for row,changed in zip(current,h):
            base = data['relu2'][index[row['id']]].astype(np.float64)
            # The original and the added-helper variant have identical target.
            deltas.append((changed[2]-(changed[0]+changed[1])/2)-(base[2]-(base[0]+base[1])/2))
        calls.extend(current)
    nuisance = np.mean(deltas,axis=0)
    train = [i for i,r in enumerate(rows) if r['panel']=='train' and r['label'] in ('DONE','PARTIAL')]
    done_partial = (data['relu2'][train,0]-data['relu2'][train,1]).mean(axis=0).astype(np.float64)
    anchors = set(json.loads((args.repair/'solve.json').read_text())['anchor_ids'])
    old = data['relu2'][[i for i,r in enumerate(rows) if r['id'] in anchors],:2].astype(np.float64)
    with safe_open(SOURCE/'model.safetensors',framework='numpy') as source:
        w = source.get_tensor(READOUT).reshape(-1).astype(np.float64)
    weights,detail = {},{}
    for name,preserve in [('dp',done_partial[None]),('old-margin',np.concatenate([done_partial[None],old[:,0]-old[:,1]]))]:
        _,s,right = np.linalg.svd(preserve,full_matrices=False)
        rank = int((s>np.finfo(float).eps*max(preserve.shape)*s[0]).sum())
        projected = nuisance-right[:rank].T@(right[:rank]@nuisance)
        vector = projected/(nuisance@projected)
        delta = -(w@nuisance)*vector
        for strength in (0.25,0.5,1.0):
            weights[f'nuisance-{name}-{strength:g}'] = (w+strength*delta).astype(np.float32)
        detail[name] = {'full_delta_norm':float(np.linalg.norm(delta)),
            'source_response_to_nuisance':float(w@nuisance),'protected_rank':rank}
    np.savez(args.capture/'nuisance-weights.npz',**weights)
    write(args.capture/'nuisance-solve.json',{'method':nuisance_directions.__doc__,'pairs':len(calls),
        'not_started_after_helper':sum(r['prediction']=='NOT_STARTED' for r in calls),
        'original_not_started':sum(r['original_prediction']=='NOT_STARTED' for r in calls),'directions':detail})


def nuisance_encoder(args):
    """Observe the encoder before the scorer discards the nuisance contrast."""
    import numpy as np
    torch = gpu()
    model,pipe,_loading = load_native(str(SOURCE),'cuda')
    model.requires_grad_(False)
    found = {}
    def hook(_module,inputs):
        found['classes'] = inputs[0].float().cpu().numpy()[0]
    handle = model.model.classes_projector.register_forward_pre_hook(hook)
    arrays,ids = [],[]
    try:
        for shard in range(2):
            for line in (args.capture/f'nuisance-{shard}/calls.jsonl').read_text().splitlines():
                row = json.loads(line)
                inputs = pipe.tokenizer(row['rendered_input'],truncation=False,return_tensors='pt').to('cuda')
                logits = model(**inputs,max_num_classes=len(LABELS)).logits[0].float().cpu().tolist()
                append(args.capture/'nuisance-encoder-calls.jsonl',{'id':row['id'],'rendered_input':row['rendered_input'],
                    'logits':logits,'prediction':LABELS[int(np.argmax(logits))],'reasoning':None,
                    'previous_prediction':row['prediction']})
                arrays.append(found['classes']);ids.append(row['id'])
    finally:
        handle.remove()
    np.savez(args.capture/'nuisance-encoder.npz',classes=np.stack(arrays))
    write(args.capture/'nuisance-encoder-ids.json',ids)


def projector_directions(args):
    """Erase the TRAIN nuisance direction upstream, in the class projector."""
    import numpy as np
    from safetensors import safe_open
    rows,data = cached(args.repair)
    index = {r['id']:i for i,r in enumerate(rows)}
    ids = json.loads((args.capture/'nuisance-encoder-ids.json').read_text())
    counter = np.load(args.capture/'nuisance-encoder.npz')['classes'].astype(np.float64)
    before = data['classes'][[index[id] for id in ids]].astype(np.float64)
    u = (counter-before).mean(axis=(0,1)); u /= np.linalg.norm(u)
    anchors = set(json.loads((args.repair/'solve.json').read_text())['anchor_ids'])
    old = data['classes'][[i for i,r in enumerate(rows) if r['id'] in anchors],:2].reshape(-1,len(u)).astype(np.float64)
    with safe_open(SOURCE/'model.safetensors',framework='numpy') as source:
        weight = source.get_tensor(args.tensor).astype(np.float64)
    _,s,right = np.linalg.svd(old,full_matrices=False)
    rank = int((s>np.finfo(float).eps*max(old.shape)*s[0]).sum())
    projected = u-right[:rank].T@(right[:rank]@u)
    protected = projected/(u@projected)
    weights,details = {},{}
    for name,v in [('plain',u),('old-protected',protected)]:
        change = np.outer(weight@u,v)
        details[name] = {'full_delta_norm':float(np.linalg.norm(change)),
            'max_old_anchor_linear_shift':float(np.max(np.abs(old@change.T))),
            'dual_norm':float(np.linalg.norm(v))}
        for amount in (0.25,0.5,1.0):
            weights[f'projector-nuisance-{name}-{amount:g}'] = (weight-amount*change).astype(np.float32)
    np.savez(args.capture/'projector-weights.npz',**weights)
    write(args.capture/'projector-solve.json',{'method':projector_directions.__doc__,'train_pairs':len(ids),
        'tensor':args.tensor,'anchor_rank':rank,'source_norm':float(np.linalg.norm(weight)),'directions':details})


def capture_text(args):
    """Gather both sides of paired TRAIN changes along the actual text path."""
    import numpy as np
    from suite.progress_correctness.repair import panels
    from suite.gliclass_probe import render_state
    from suite.progress_loto import progress_policy
    originals = {r['id']:r for r in panels() if r['panel']=='train'}
    part = args.capture/f'text-pairs-{args.shard}'
    part.mkdir(exist_ok=False)
    torch = gpu()
    model,pipe,_loading = load_native(str(SOURCE),'cuda')
    model.requires_grad_(False)
    found,arrays = {},{}
    def save(key):
        def hook(_module,inputs):
            found[key] = inputs[0].float().cpu().numpy()[0]
        return hook
    handles = [model.model.text_projector.linear_1.register_forward_pre_hook(save('pooled')),
        model.model.text_projector.linear_2.register_forward_pre_hook(save('hidden')),
        model.model.classes_projector.register_forward_pre_hook(save('classes'))]
    try:
        counter = [json.loads(s) for s in (args.capture/f'nuisance-{args.shard}/calls.jsonl').read_text().splitlines()]
        for r in counter:
            texts = [('before',pipe.prepare_input(render_state(originals[r['id']]['complete_input']),list(LABELS),prompt=progress_policy())),
                     ('after',r['rendered_input'])]
            for variant,text in texts:
                inputs = pipe.tokenizer(text,truncation=False,return_tensors='pt').to('cuda')
                output = model(**inputs,max_num_classes=len(LABELS),output_text_embeddings=True)
                logits = output.logits[0].float().cpu().tolist()
                rec = {'id':r['id'],'variant':variant,'label':r['label'],'rendered_input':text,
                    'logits':logits,'raw':output.uncalibrated_logits[0].float().cpu().tolist(),
                    'prediction':LABELS[int(np.argmax(logits))],'reasoning':None}
                append(part/'calls.jsonl',rec)
                for key in ('pooled','hidden','classes'):
                    arrays.setdefault(key,[]).append(found[key])
                arrays.setdefault('text',[]).append(output.text_embeddings[0].float().cpu().numpy())
    finally:
        for handle in handles:
            handle.remove()
    np.savez(part/'activations.npz',**{key:np.stack(value) for key,value in arrays.items()})
    write(part/'completed.json',{'inputs':2*len(counter),'pairs':len(counter),
        'normalize_features':model.config.normalize_features,'extract_text_features':model.config.extract_text_features})


def text_hybrids(args):
    """Causal localization, not a deployable intervention or benchmark score."""
    import numpy as np
    records,arrays = [],{}
    for shard in range(2):
        part = args.capture/f'text-pairs-{shard}'
        records.extend(json.loads(s) for s in (part/'calls.jsonl').read_text().splitlines())
        a = np.load(part/'activations.npz')
        for key in a.files:
            arrays.setdefault(key,[]).append(a[key])
    data = {key:np.concatenate(value) for key,value in arrays.items()}
    torch = gpu()
    model,_pipe,_loading = load_native(str(SOURCE),'cuda')
    model.requires_grad_(False)
    summary = {}
    batch = [{**r,'labels':list(LABELS),'tokens':0} for r in records[::2]]
    for name,t,c in [('before',data['text'][::2],data['classes'][::2]),
        ('after',data['text'][1::2],data['classes'][1::2]),
        ('before-text_after-classes',data['text'][::2],data['classes'][1::2]),
        ('after-text_before-classes',data['text'][1::2],data['classes'][::2])]:
        results = head_predictions(model,torch,torch.from_numpy(t).to('cuda'),torch.from_numpy(c).to('cuda'),batch)
        for r in results:
            append(args.capture/'text-hybrid-calls.jsonl',{'hybrid':name,**r,'reasoning':None})
        summary[name] = {'count':len(results),'not_started':sum(r['prediction']=='NOT_STARTED' for r in results),
            'correct':sum(r['prediction']==r['label'] for r in results)}
    write(args.capture/'text-hybrids.json',summary)


def rank3_directions(args):
    """Restore three TRAIN counterfactual class means, protect original inputs.

    K: helper-added mean encoder class keys. R: desired change of first projector
    preactivation back to each original class mean. Project K into the nullspace
    of original TRAIN/old anchor inputs; deltaW = R (K^T P K)^-1 K^T P.
    This keeps the class-specific shifts instead of averaging them away.
    """
    import numpy as np
    from safetensors import safe_open
    rows,data = cached(args.repair)
    index = {r['id']:i for i,r in enumerate(rows)}
    ids = json.loads((args.capture/'nuisance-encoder-ids.json').read_text())
    before = data['classes'][[index[id] for id in ids]].astype(np.float64)
    after = np.load(args.capture/'nuisance-encoder.npz')['classes'].astype(np.float64)
    anchors = set(json.loads((args.repair/'solve.json').read_text())['anchor_ids'])
    extra_ids = set(json.loads((args.capture/'extra-old-anchors.json').read_text())) if args.preserve_not_started else set()
    old = data['classes'][[i for i,r in enumerate(rows) if r['id'] in anchors|extra_ids],:2].reshape(-1,1024).astype(np.float64)
    ns = []
    if args.preserve_not_started:
        families = set()
        for i,row in sorted(enumerate(rows),key=lambda pair:(pair[1].get('task',''),pair[1]['id'])):
            if row['panel']=='train' and row['label']=='NOT_STARTED' and row['task'] not in families:
                ns.append(i); families.add(row['task'])
                if len(ns)==32:
                    break
    negative = data['classes'][ns].reshape(-1,1024).astype(np.float64)
    with safe_open(SOURCE/'model.safetensors',framework='numpy') as source:
        weight = source.get_tensor(args.tensor).astype(np.float64)
    keys = after.mean(axis=0).T
    residual = weight@(before.mean(axis=0).T-keys)
    weights,details = {},{}
    for name,protected in [('all-originals',np.concatenate([before.reshape(-1,1024),old,negative])),
                            ('original-means',np.concatenate([before.mean(axis=0),old,negative]))]:
        _,s,right = np.linalg.svd(protected,full_matrices=False)
        rank = int((s>np.finfo(float).eps*max(protected.shape)*s[0]).sum())
        projected = keys-right[:rank].T@(right[:rank]@keys)
        gram = keys.T@projected
        delta = residual@np.linalg.solve(gram,projected.T)
        details[name] = {'protection_rank':rank,'gram_eigenvalues':np.linalg.eigvalsh(gram).tolist(),
            'delta_norm':float(np.linalg.norm(delta)),
            'protection_max_linear_shift':float(np.max(np.abs(delta@protected.T))),
            'max_key_restoration_residual':float(np.max(np.abs(delta@keys-residual)))}
        for amount in ((0.75,1.0) if args.preserve_not_started else (0.5,1.0)):
            edited = (weight+amount*delta).astype(np.float32)
            tag = 'rank3-ns-protected' if args.preserve_not_started else 'rank3'
            weights[f'projector-{tag}-{name}-{amount:g}'] = edited
    tag = 'rank3-ns-protected' if args.preserve_not_started else 'rank3'
    np.savez(args.capture/f'{tag}-weights.npz',**weights)
    write(args.capture/f'{tag}-solve.json',{'method':rank3_directions.__doc__,'train_pairs':len(ids),
        'tensor':args.tensor,'source_norm':float(np.linalg.norm(weight)),'constructions':details,
        'not_started_train_anchor_ids':[rows[i]['id'] for i in ns],'extra_old_train_anchor_ids':sorted(extra_ids),
        'benchmark_used_for_fitting':False})


def select_done_partial(summaries):
    """Operator objective: improve DONE without sacrificing PARTIAL.

    Both DONE recall and precision must retain the source result. PARTIAL must
    retain correct answers in aggregate and must not incur more false DONE.
    NOT_STARTED/overall accuracy cannot buy a regression on either side.
    """
    baseline = summaries['source_recorded']
    base_matrix = baseline['confusion']
    eligible = []
    for name,stats in summaries.items():
        m = stats['confusion']
        if (m[0][0]>=base_matrix[0][0] and m[1][1]>=base_matrix[1][1]
                and m[1][0]<=base_matrix[1][0] and stats['done_precision']>=baseline['done_precision']):
            eligible.append(name)
    return max(eligible,key=lambda name:(summaries[name]['confusion'][0][0],
        summaries[name]['done_precision'],summaries[name]['confusion'][1][1]))


def run(args):
    import numpy as np
    args.out.mkdir(parents=True,exist_ok=False)
    rows = [json.loads(s) for s in (args.capture/'predictions.jsonl').read_text().splitlines()]
    original = [json.loads(s) for s in args.baseline.read_text().splitlines()]
    baseline = {r['id']:r for r in original}
    if len(rows)!=600 or len(baseline)!=600 or {r['id'] for r in rows}!=set(baseline):
        raise ValueError('benchmark and recorded source baseline differ')
    for row in rows:
        if row['label']!=baseline[row['id']]['label']:
            raise ValueError('benchmark labels differ from original evaluation')
    data = np.load(args.capture/'activations.npz')
    torch = gpu()
    model,_pipe,loading = load_native(str(SOURCE),'cuda')
    model.requires_grad_(False)
    candidates = {}
    paths = [args.extra_weights] if args.extra_weights else [args.repair/name for name in ('candidate-weights.npz','balanced-weights.npz')]
    for path in paths:
        weights = np.load(path)
        candidates.update({key:weights[key] for key in weights.files if key!='baseline'})
    summaries = {'source_recorded':report(original,baseline)}
    write(args.out/'run.json',{'authorization':'operator explicitly authorizes exposed TEST reuse to improve results before fresh evaluation',
        'benchmark_capture':str(args.capture),'recorded_baseline':str(args.baseline),
        'source':str(SOURCE),'loading':loading,'tensor':args.tensor,'weight_sources':[str(path) for path in paths],
        'construction':'TRAIN-only weight solves; benchmark used for diagnosis/comparison/selection',
        'fresh_blind':False,'gradients':False,'deployed':False,'published':False})
    for name,weights in candidates.items():
        tensor = model.state_dict()[args.tensor]
        tensor.copy_(torch.from_numpy(weights.reshape(tuple(tensor.shape))).to('cuda'))
        records = []
        for start in range(0,len(rows),64):
            source = rows[start:start+64]
            batch = [{**r,'task':r['family'],'family':'progress','labels':list(LABELS)} for r in source]
            append(args.out/'calls.jsonl',{'event':'start','candidate':name,'ids':[r['id'] for r in source]})
            outputs = head_predictions(model,torch,torch.from_numpy(data['text'][start:start+64]).to('cuda'),
                torch.from_numpy(data['classes'][start:start+64]).to('cuda'),batch)
            for old,new in zip(source,outputs):
                row = {**old,**new,'benchmark_family':old['family'],'reasoning':None}
                records.append(row)
                append(args.out/f'{name}-predictions.jsonl',row)
            append(args.out/'calls.jsonl',{'event':'result','candidate':name,'rows':len(outputs)})
        summaries[name] = report(records,baseline)
        if args.preservation:
            from suite.progress_correctness.repair import metrics
            source_rows,source_data = cached(args.repair)
            source_by_id = {r['id']:r for r in source_rows}
            preservation = []
            for family in ('progress','dictation','retrospective'):
                idx = [i for i,r in enumerate(source_rows) if r['family']==family]
                count = 3 if family=='progress' else 2
                for offset in range(0,len(idx),64):
                    select = idx[offset:offset+64]
                    source_batch = [source_rows[i] for i in select]
                    append(args.out/'preservation-calls.jsonl',{'event':'start','candidate':name,'ids':[r['id'] for r in source_batch]})
                    result = head_predictions(model,torch,torch.from_numpy(source_data['text'][select]).to('cuda'),
                        torch.from_numpy(source_data['classes'][select,:count]).to('cuda'),source_batch)
                    for old,new in zip(source_batch,result):
                        rec = {**old,**new}
                        preservation.append(rec)
                        append(args.out/f'{name}-preservation.jsonl',rec)
                    append(args.out/'preservation-calls.jsonl',{'event':'result','candidate':name,'rows':len(result)})
            summaries[name]['preservation'] = metrics(preservation,source_by_id)
        if args.preservation and (args.capture/'text-pairs-0/activations.npz').exists():
            controls = {}
            for variant,offset in [('before',0),('after',1)]:
                outputs = []
                for shard in range(2):
                    part = args.capture/f'text-pairs-{shard}'
                    raw = [json.loads(s) for s in (part/'calls.jsonl').read_text().splitlines()]
                    arrays = np.load(part/'activations.npz')
                    batch = [{**r,'tokens':0,'labels':list(LABELS)} for r in raw[offset::2]]
                    result = head_predictions(model,torch,torch.from_numpy(arrays['text'][offset::2]).to('cuda'),
                        torch.from_numpy(arrays['classes'][offset::2]).to('cuda'),batch)
                    outputs.extend(result)
                    for row in result:
                        append(args.out/'nuisance-calls.jsonl',{'candidate':name,'variant':variant,**row})
                controls[variant] = {'count':len(outputs),'not_started':sum(r['prediction']=='NOT_STARTED' for r in outputs),
                    'correct':sum(r['prediction']==r['label'] for r in outputs)}
            summaries[name]['nuisance_control'] = controls
        if name=='balanced-unprotected':
            native = {r['id']:r for r in rows}
            summaries[name]['native_capture_fidelity'] = {
                'changed_predictions':sum(r['prediction']!=native[r['id']]['prediction'] for r in records),
                'max_logit_difference':max(abs(a-b) for r in records for a,b in zip(r['logits'],native[r['id']]['logits']))}
        write(args.out/'summary.json',summaries)
        print(json.dumps({'candidate':name,**summaries[name]}),flush=True)
    # Exposed-benchmark selection, not a fresh test. Overall macro-F1 must not
    # select a NOT_STARTED improvement that sacrifices the requested D/P goal.
    best = select_done_partial(summaries)
    write(args.out/'selected.json',{'candidate':best,
        'criterion':'maximize DONE correct, then DONE precision, then PARTIAL correct; retain source DONE recall/precision and PARTIAL correct/false-DONE counts',
        'fresh_blind':False,'metrics':summaries[best],
        'done_correct_gain':summaries[best]['confusion'][0][0]-summaries['source_recorded']['confusion'][0][0],
        'partial_false_done_change':summaries[best]['confusion'][1][0]-summaries['source_recorded']['confusion'][1][0]})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair',type=Path,required=True)
    parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--extra-weights',type=Path)
    parser.add_argument('--construct-directions',action='store_true')
    parser.add_argument('--capture-nuisance',action='store_true')
    parser.add_argument('--solve-nuisance',action='store_true')
    parser.add_argument('--shard',type=int,default=0)
    parser.add_argument('--tensor',default=READOUT)
    parser.add_argument('--preservation',action='store_true')
    parser.add_argument('--capture-encoder',action='store_true')
    parser.add_argument('--projector-directions',action='store_true')
    parser.add_argument('--capture-text',action='store_true')
    parser.add_argument('--text-hybrids',action='store_true')
    parser.add_argument('--rank3-directions',action='store_true')
    parser.add_argument('--preserve-not-started',action='store_true')
    args=parser.parse_args()
    if args.construct_directions:
        directions(args)
    elif args.capture_nuisance:
        capture_nuisance(args)
    elif args.solve_nuisance:
        nuisance_directions(args)
    elif args.capture_encoder:
        nuisance_encoder(args)
    elif args.projector_directions:
        projector_directions(args)
    elif args.capture_text:
        capture_text(args)
    elif args.text_hybrids:
        text_hybrids(args)
    elif args.rank3_directions:
        rank3_directions(args)
    else:
        run(args)
