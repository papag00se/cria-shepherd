"""Score fixed reserved, ambiguity, exposed real, and earlier control inputs; never changes a model."""
import argparse
import json
import resource
import time
from pathlib import Path

import numpy as np
import torch
from cria.system1 import System1Runtime
from suite.gliclass_probe import load_frozen_cohorts, load_native, ort_logits, prepare_case, session
from suite.onejev_probe import append

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / 'train-001'
BASELINE = ROOT / 'baseline-001/results.jsonl'

def cases():
    result = []
    for line in BASELINE.read_text().splitlines():
        r = json.loads(line)
        result.append({'id': r['id'], 'family': r['family'], 'label': r['target'],
                       'complete_input': r['native_input']['state'], 'scope': r['scope'],
                       'original_native_tokens': r['native_input']['native_inputs']['input_ids'][0]})
    return result

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--fp32', type=Path, help='normalized FP32 ONNX graph for complete-input fidelity')
    args = p.parse_args()
    args.out.mkdir(exist_ok=False)
    torch.set_num_threads(2)
    contract, _, _ = load_frozen_cohorts(BASE)
    model, pipe, loading = load_native(str(args.reference), 'cpu')
    runtime = System1Runtime(args.bundle, threads=2, memory_budget_bytes=8 * 1024**3)
    fp32 = session(args.fp32) if args.fp32 else None
    (args.out / 'settings.json').write_text(json.dumps({'reference': str(args.reference), 'bundle': str(args.bundle),
        'native_loading': loading, 'torch_threads': 2, 'runtime_threads': 2, 'runtime_arena_bytes': 8 * 1024**3,
        'native_dtype': 'FP32', 'runtime': 'CPU INT4', 'reserved_labels_used_for_fit': False}, indent=2) + '\n')
    for r in cases():
        inputs, receipt = prepare_case(pipe, r, contract['policy_sha256'])
        prepared = runtime.prepare(r['family'], r['complete_input'])
        ids = receipt['native_inputs']['input_ids'][0]
        if ids != list(prepared.input_ids) or receipt['rendered_input'] != prepared.rendered_input:
            raise ValueError(f"native/runtime input differs: {r['id']}")
        expected = r['original_native_tokens']
        if ids != expected:
            raise ValueError(f"recorded native input differs: {r['id']}")
        started = time.monotonic()
        with torch.no_grad():
            logits = model(**inputs, max_num_classes=2).logits[0, :2].float().tolist()
        native_s = time.monotonic() - started
        exported = ort_logits(fp32, inputs).tolist() if fp32 else None
        if exported is not None:
            np.testing.assert_allclose(exported, logits, rtol=2e-4, atol=2e-4, err_msg=r['id'])
        result = runtime.infer(r['family'], r['complete_input'])
        labels = receipt['labels']
        record = {'id': r['id'], 'scope': r['scope'], 'family': r['family'], 'target': r['label'],
                  'native_input': receipt, 'native_logits': logits, 'native_prediction': labels[logits.index(max(logits))],
                  'native_seconds': native_s, 'fp32_onnx_logits': exported,
                  'int4_logits': list(result.logits), 'int4_prediction': result.label,
                  'int4_seconds': result.inference_s, 'int4_elapsed_seconds': result.elapsed_s,
                  'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
        append(args.out / 'results.jsonl', record)
        print(json.dumps({'id': r['id'], 'scope': r['scope'], 'native_s': native_s, 'int4_s': result.inference_s}), flush=True)
    (args.out / 'completed.json').write_text(json.dumps({'cases': len(cases()), 'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}, indent=2) + '\n')

if __name__ == '__main__':
    main()
