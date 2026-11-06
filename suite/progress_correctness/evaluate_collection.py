"""Score the entire exposed collection from a saved model using concurrent GPU instances.

Uses repair.native's read-only, untruncated full-model inference, not cached heads.
Keep TRAIN, DEV and the exposed benchmark separate in every aggregate report.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

from suite.progress_correctness.repair import evaluation_rows, metrics, write


def totals(rows):
    correct = sum(r['prediction']==r['label'] for r in rows)
    return {'rows':len(rows),'correct':correct,'accuracy':correct/len(rows) if rows else None}


def launch_worker(args, name, device, uuid, assigned):
    ids_file = args.out/f'{name}-input-ids.json'
    write(ids_file,[r['id'] for r in assigned])
    command = [sys.executable,'-m','suite.progress_correctness.repair','native',
        '--source',str(args.source),'--out',str(args.out),'--verify-only',
        '--candidate','operator-selected-full-collection',
        '--evaluation-panels','train','dev','old','benchmark',
        '--input-ids',str(ids_file),'--confirmation-prefix',name+'-',
        '--shard','0','--shards','1']
    env = {**os.environ,'CUDA_VISIBLE_DEVICES':uuid,'OPENBLAS_NUM_THREADS':'2','OMP_NUM_THREADS':'2'}
    with (args.out/f'{name}.log').open('w') as log:
        process = subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT)
    return {'name':name,'gpu':device,'visible':uuid,'assigned_rows':len(assigned),
        'process':process,'pid':process.pid,'directory':name+'-0'}


def run(args):
    started = time.monotonic()
    args.out.mkdir(parents=True,exist_ok=False)
    rows = evaluation_rows(('train','dev','old','benchmark'))
    progress = sorted((r for r in rows if r['family']=='progress'),key=lambda r:r['id'])
    random.Random(17).shuffle(progress)
    old = sorted((r for r in rows if r['panel']=='old'),key=lambda r:r['id'])
    # Earlier full-native peaks: ~4.04 GB for progress; ~6.16 GB including old
    # long inputs. Two progress-only instances fit the 10 GB card. Three mixed
    # instances fit the 24 GB card. No token clipping or input reduction.
    smaller = progress[:2000]
    larger = progress[2000:]+old
    jobs = []
    waves = [[('3090',args.gpu_3090,larger,3),('3080',args.gpu_3080,smaller,2)]] if args.gpu_3090 else [
        [('3080',args.gpu_3080,progress,2)],[('3080',args.gpu_3080,old,1)]]
    for wave_index,wave in enumerate(waves):
        wave_jobs = []
        for device,uuid,pool,instances in wave:
            for index in range(instances):
                name = f'{device}-'+('old-' if wave_index else '')+str(index)
                job = launch_worker(args,name,device,uuid,pool[index::instances])
                jobs.append(job)
                wave_jobs.append(job)
        write(args.out/'run.json',{'checkpoint':str(args.source),'expected_rows':len(rows),
            'panels':dict(Counter(r['panel'] for r in rows)),
            'instances':[{k:v for k,v in j.items() if k!='process'} for j in jobs],
            'full_model':True,'gradient_updates':0,'weight_assignment':False,'checkpoint_saved':False,
            'fresh_validation':False,'input_truncation':False,'deployed':False,'published_weights':False})
        for job in wave_jobs:
            job['returncode'] = job['process'].wait()
    records,resources = [],{}
    for job in jobs:
        code = job['returncode']
        part = args.out/job['directory']
        resources[job['name']] = {'returncode':code,'assigned_rows':job['assigned_rows']}
        if (part/'completed.json').exists():
            resources[job['name']].update(json.loads((part/'completed.json').read_text()))
        if (part/'predictions.jsonl').exists():
            records.extend({**json.loads(line),'worker':job['name'],'gpu':job['gpu']}
                for line in (part/'predictions.jsonl').read_text().splitlines())
    with (args.out/'predictions.jsonl').open('w') as stream:
        for row in records:
            stream.write(json.dumps(row)+'\n')
    expected = {r['id'] for r in rows}
    observed = {r['id'] for r in records}
    report = {'checkpoint':str(args.source),'seconds':time.monotonic()-started,
        'expected_rows':len(rows),'observed_rows':len(records),'unique_rows':len(observed),
        'missing_ids':sorted(expected-observed),'unexpected_ids':sorted(observed-expected),
        'duplicate_rows':len(records)-len(observed),'resources':resources,
        'complete':len(records)==len(expected) and observed==expected and all(r['returncode']==0 for r in resources.values()),
        'training':totals([r for r in records if r['panel'] in ('train','old')]),
        'all_collection':totals(records),'metrics':metrics(records),
        'by_gpu':{device:{'totals':totals([r for r in records if r['gpu']==device]),
            'metrics':metrics([r for r in records if r['gpu']==device])} for device in ('3090','3080')},
        'interpretation':'Read-only resubstitution on exposed records, not generalization. Pooled metrics use the recorded worker hardware; arithmetic is hardware-conditioned.',
        'full_model':True,'gradient_updates':0,'weights_changed':False,'fresh_validation':False,
        'input_truncation':False,'quantized':False,'deployed':False,'published_weights':False}
    write(args.out/'report.json',report)
    print(json.dumps(report,indent=2),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--gpu-3090',help='omit to score on 3080 only: two progress instances, then one old-family instance')
    parser.add_argument('--gpu-3080',required=True)
    run(parser.parse_args())


if __name__=='__main__':
    main()
