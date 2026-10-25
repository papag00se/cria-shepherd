"""Offline native GLiClass single-label decisions and INT4 export checks."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import time

from suite.onejev_probe import append, checked_decision, file_sha, frozen_policy
from suite.training_admit import LABEL_ORDER
from suite.training_run import loading_receipt

MAX_TOKENS = 16384


def as_text(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def render_state(state):
    """The publisher's System One state renderer, not a relevance projection."""
    if state in (None, '', {}, []):
        return ''
    if isinstance(state, str):
        return state
    if isinstance(state, list):
        return '\n'.join(f'- {as_text(item)}' for item in state)
    lines = []
    for key, value in state.items():
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            lines += [f'{key}:'] + [f'- {item}' for item in value]
        else:
            lines.append(f'{key}: {as_text(value)}')
    return '\n'.join(lines)


def prepare_case(pipe, case, policy_hashes, *, reverse=False):
    labels = list(LABEL_ORDER[case['family']])
    if reverse:
        labels.reverse()
    text = render_state(case['complete_input'])
    policy = frozen_policy(case['family'], policy_hashes[case['family']])
    rendered = pipe.prepare_input(text, labels, prompt=policy)
    inputs = pipe.prepare_inputs([text], labels, same_labels=True, prompt=policy)
    # Check the native pipeline against the same complete string with truncation
    # explicitly disabled. A large declared ceiling alone is not a fit proof.
    full = pipe.tokenizer(rendered, truncation=False)['input_ids']
    actual = inputs['input_ids'][0].tolist()
    if actual != full:
        raise ValueError('native pipeline truncated or changed the complete input')
    if len(actual) > MAX_TOKENS:
        raise ValueError(f'full native input exceeds declared {MAX_TOKENS}-token ceiling')
    return inputs, {'id': case['id'], 'labels': labels, 'rendered_input': rendered,
                    'state': case['complete_input'], 'policy': policy,
                    'native_inputs': {k: v.tolist() for k, v in inputs.items()},
                    'tokens': len(actual), 'reasoning': None}


def load_native(snapshot, device='cpu'):
    import torch
    from gliclass import GLiClassModel, ZeroShotClassificationPipeline
    from transformers import AutoTokenizer
    model, info = GLiClassModel.from_pretrained(snapshot, dtype=torch.float32,
        local_files_only=True, output_loading_info=True)
    if info.get('missing_keys') or info.get('unexpected_keys') or info.get('mismatched_keys') or info.get('error_msgs'):
        raise ValueError(f'native loading mismatch: {loading_receipt(info)}')
    model = model.to(device).eval()
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
    pipe = ZeroShotClassificationPipeline(model, tokenizer, max_length=10**9,
        classification_type='single-label', device=device, progress_bar=False).pipe
    return model, pipe, loading_receipt(info)


def session(path):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = 6
    options.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])


def ort_logits(engine, inputs):
    import numpy as np
    feed = {item.name: inputs[item.name].detach().cpu().numpy() for item in engine.get_inputs()}
    output = engine.run(['logits'], feed)[0]
    if output.ndim != 2 or output.shape[0] != 1 or output.shape[1] != 2 or not np.isfinite(output).all():
        raise ValueError(f'expected two finite native label logits, got {output.shape}')
    return output[0]


def run(root, onejev_root):
    import numpy as np
    import torch
    torch.set_num_threads(6)
    manifest = json.loads((root / 'download.json').read_bytes())
    quantized = json.loads((root / 'quantized.json').read_bytes())
    source_contract = json.loads((onejev_root / 'contract.json').read_bytes())
    train = json.loads((onejev_root / 'train-cases.json').read_bytes())
    held = json.loads((onejev_root / 'held-cases.json').read_bytes())
    for name in ['train-cases.json', 'held-cases.json']:
        path = onejev_root / name
        if file_sha(path) != source_contract['input_sha256'][str(path)]:
            raise ValueError('frozen admitted cases changed')
    if len(train) != 514 or len(held) != 130 or {x['id'] for x in train} & {x['id'] for x in held}:
        raise ValueError('wrong or overlapping cohorts')
    for name, expected in quantized['files'].items():
        if file_sha(root / 'int4' / name) != expected['sha256']:
            raise ValueError('INT4 weight bundle changed')
    out = root / 'baseline'
    out.mkdir()
    contract = {'source_contract_sha256': file_sha(onejev_root / 'contract.json'),
                'cohorts_sha256': {name: file_sha(onejev_root / name) for name in ['train-cases.json', 'held-cases.json']},
                'source_sha256': file_sha(Path(__file__)), 'policy_sha256': source_contract['policy_sha256'],
                'max_tokens': MAX_TOKENS, 'dtype': 'FP32 activations, INT4 constant matrices and embeddings',
                'fidelity': {'rtol': 0.0002, 'atol': 0.0002, 'cases': 'frozen native tiny eight plus longest TRAIN input per head'},
                'quality': 'all 130 historical diagnostics, no label/threshold fitting; not fresh or human gold',
                'quarantines_unchanged': True, 'deployed': False}
    (out / 'contract.json').write_text(json.dumps(contract, indent=2) + '\n')
    model, pipe, loading = load_native(manifest['snapshot'])
    (out / 'loading.json').write_text(json.dumps(loading, indent=2) + '\n')
    prepared = {}
    for case in train + held:
        inputs, receipt = prepare_case(pipe, case, contract['policy_sha256'])
        prepared[case['id']] = inputs, receipt
        append(out / 'native-inputs.jsonl', receipt)
    ids = list(source_contract['tiny_ids'])
    for family in LABEL_ORDER:
        longest = max((x for x in train if x['family'] == family), key=lambda x: prepared[x['id']][1]['tokens'])['id']
        if longest not in ids:
            ids.append(longest)
    (out / 'fidelity-ids.json').write_text(json.dumps(ids, indent=2) + '\n')
    reference = session(root / 'normalized-fp32.onnx')
    for identity in ids:
        inputs, receipt = prepared[identity]
        with torch.no_grad():
            native = model(**inputs, max_num_classes=2).logits[0, :2].float().cpu().numpy()
        exported = ort_logits(reference, inputs)
        append(out / 'fidelity.jsonl', {'id': identity, 'native_logits': native.tolist(),
            'exported_logits': exported.tolist(), 'max_absolute_error': float(np.max(np.abs(native-exported)))})
        np.testing.assert_allclose(exported, native, rtol=contract['fidelity']['rtol'], atol=contract['fidelity']['atol'])
    del reference
    engine = session(root / 'int4/model.onnx')
    groups = defaultdict(lambda: {'count': 0, 'matched': 0, 'target_by_prediction': [[0, 0], [0, 0]]})
    for case in held:
        inputs, receipt = prepared[case['id']]
        started = time.monotonic()
        logits = ort_logits(engine, inputs)
        probabilities = torch.softmax(torch.from_numpy(logits).float(), dim=-1).tolist()
        labels = receipt['labels']
        p = dict(zip(labels, probabilities))
        # Exactly the publisher's single-label API rule: softmax of calibrated
        # model logits, then maximum native label probability; no prose parser.
        answer = {'choice': max(labels, key=p.get), 'probabilities': p}
        prediction, p = checked_decision(answer, case['family'])
        result = {'id': case['id'], 'family': case['family'], 'partition': case['partition'],
                  'reviewed_target': case['label'], 'prediction': prediction, 'probabilities': p,
                  'calibrated_logits': logits.tolist(), 'seconds': time.monotonic()-started}
        append(out / 'results.jsonl', result)
        group = groups[case['partition'] + '/' + case['family']]
        group['count'] += 1
        group['matched'] += prediction == case['label']
        group['target_by_prediction'][labels.index(case['label'])][labels.index(prediction)] += 1
    report = {'groups': dict(groups), 'count': sum(g['count'] for g in groups.values()),
              'matched': sum(g['matched'] for g in groups.values()), 'class_order': LABEL_ORDER,
              'fidelity_passed': True, 'max_native_tokens': max(r['tokens'] for _, r in prepared.values()),
              'complete_weight_bundle_bytes': quantized['complete_bundle_bytes'],
              'results_sha256': file_sha(out / 'results.jsonl'),
              'not_fresh_evaluation_or_human_gold': True, 'quarantines_unchanged': True, 'deployed': False}
    (out / 'completed.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--onejev-root', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    run(args.root, args.onejev_root)


if __name__ == '__main__':
    main()
