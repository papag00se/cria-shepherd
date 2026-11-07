"""Export one completed continuation through the native ONNX/INT4 and bundle owners."""
import argparse
import json
from pathlib import Path

import torch
from suite.gliclass_export import export_native_graph
from suite.gliclass_probe import load_frozen_cohorts, load_native, ort_logits, prepare_case, session
from suite.gliclass_quantize import quantize
from suite.onejev_probe import append, file_sha
from suite.system1_package import build_bundle

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / 'train-001'
FIT = ROOT / 'cpu-fit-001'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fit', type=Path, default=FIT, help='completed native fit directory')
    parser.add_argument('--out', type=Path, required=True, help='new export output directory')
    args = parser.parse_args()
    fit = args.fit.resolve()
    if not (fit / 'completed.json').is_file():
        raise RuntimeError('fit has not completed')
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    out = root / 'export-001'
    out.mkdir()
    snap = out / 'native-reference'
    snap.mkdir()
    reference = fit / 'reference'
    for p in reference.iterdir():
        (snap / p.name).symlink_to(p.resolve())
    torch.set_num_threads(4)
    contract, prior, held = load_frozen_cohorts(BASE)
    model, pipe, loading = load_native(str(reference), 'cpu')
    inputs, _ = prepare_case(pipe, prior[0], contract['policy_sha256'])
    folder = snap / 'onnx'
    folder.mkdir()
    graph = folder / 'model.onnx'
    export_native_graph(torch, model, inputs, graph, classes=2)
    manifest = {'snapshot': str(snap.resolve()), 'source_kind': 'trained_native_export',
                'native_loading': loading, 'classes': 2,
                'files': {str(p.relative_to(snap)): {'bytes': p.stat().st_size, 'sha256': file_sha(p)}
                          for p in snap.rglob('*') if p.is_file()}}
    (out / 'download.json').write_text(json.dumps(manifest, indent=2) + '\n')
    del model
    quantize(out)
    engine = session(out / 'int4/model.onnx')
    assessment = root / 'assessment/v2'
    assessment.mkdir(parents=True)
    for row in held:
        inputs, receipt = prepare_case(pipe, row, contract['policy_sha256'])
        logits = ort_logits(engine, inputs).tolist()
        labels = receipt['labels']
        append(assessment / 'results.jsonl', {'id': row['id'], 'family': row['family'], 'native_input': receipt,
               'int4_prediction': labels[logits.index(max(logits))], 'int4_logits': logits})
    # The existing bundler expects its documented train-001/assessment layout.
    layout = root / 'package-root'
    (layout / 'train-001').mkdir(parents=True)
    (layout / 'assessment').mkdir()
    (layout / 'train-001/reference').symlink_to(reference.resolve())
    (layout / 'train-001/export-001').symlink_to(out.resolve())
    (layout / 'assessment/v2').symlink_to(assessment.resolve())
    bundle = build_bundle(root / 'bundle', training_root=layout)
    (out / 'completed.json').write_text(json.dumps({'bundle': str(bundle), 'deployed': False}, indent=2) + '\n')
    print('bundle', bundle, flush=True)

if __name__ == '__main__':
    main()
