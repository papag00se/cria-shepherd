"""Export the fixed trained native GLiClass graph, then run the same INT4 test."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

from suite.gliclass_probe import load_native, prepare_case, run as probe
from suite.gliclass_quantize import quantize
from suite.onejev_probe import file_sha


def export_native_graph(torch, model, inputs, source):
    class NativeGraph(torch.nn.Module):
        def __init__(self, native):
            super().__init__()
            self.native = native
        def forward(self, input_ids, attention_mask):
            return self.native(input_ids=input_ids, attention_mask=attention_mask, max_num_classes=2).logits

    def stable_log_sigmoid(graph, value):
        # The legacy exporter's Log(Sigmoid(x)) loses the native operator's
        # stability at saturated logits. Calibration entropy then becomes NaN.
        # Lower the SAME native operation as -Softplus(-x), at the producer;
        # never replace nonfinite outputs or change learned tensors afterward.
        return graph.op('Neg', graph.op('Softplus', graph.op('Neg', value)))

    torch.onnx.register_custom_op_symbolic('aten::log_sigmoid', stable_log_sigmoid, 17)
    try:
        with torch.no_grad():
            torch.onnx.export(NativeGraph(model).eval(), (inputs['input_ids'], inputs['attention_mask']), str(source),
                input_names=['input_ids', 'attention_mask'], output_names=['logits'], opset_version=17,
                dynamic_axes={'input_ids': {0: 'batch_size', 1: 'seq_len'},
                              'attention_mask': {0: 'batch_size', 1: 'seq_len'}, 'logits': {0: 'batch_size'}},
                dynamo=False, external_data=False, do_constant_folding=True)
    finally:
        torch.onnx.unregister_custom_op_symbolic('aten::log_sigmoid', 17)


def run(training_root, experiment_root, onejev_root, export_name='export-001'):
    import torch
    torch.set_num_threads(6)
    completed = json.loads((training_root / 'trained.json').read_bytes())
    if completed['completed_epochs'] != 12:
        raise ValueError('only the frozen final checkpoint is eligible')
    snapshot = training_root / 'reference'
    for name, digest in completed['reference_files_sha256'].items():
        if file_sha(snapshot / name) != digest:
            raise ValueError('trained native checkpoint changed')
    if Path(export_name).name != export_name:
        raise ValueError('export attempt must be one directory name')
    out = training_root / export_name
    out.mkdir()
    # Separate conversion attempts must not mutate a previously frozen export
    # or copy multi-GB native weights. Each gets its own graph plus immutable
    # links to the exact final native reference files.
    export_snapshot = out / 'native-reference'
    export_snapshot.mkdir()
    for name in completed['reference_files_sha256']:
        (export_snapshot / name).symlink_to((snapshot / name).absolute())
    model, pipe, loading = load_native(str(snapshot))
    contract = json.loads((training_root / 'contract.json').read_bytes())
    train = json.loads((training_root / 'train-cases.json').read_bytes())
    first = next(r for r in train if r['id'] == contract['tiny_ids'][0])
    inputs, receipt = prepare_case(pipe, first, contract['policy_sha256'])

    folder = export_snapshot / 'onnx'
    folder.mkdir()
    source = folder / 'model.onnx'
    export_native_graph(torch, model, inputs, source)
    manifest = {'repo': 'offline-finetuned/knowledgator-gliclass-v4-edge',
        'revision': contract['revision'], 'source_kind': 'trained_native_export', 'snapshot': str(export_snapshot),
        'trained_receipt_sha256': file_sha(training_root / 'trained.json'),
        'export_source_sha256': file_sha(Path(__file__)), 'native_loading': loading,
        'export': 'full official native calibrated forward, two native labels, dynamic complete token sequence, Torch ONNX opset17 with numerically faithful log_sigmoid=-Softplus(-x) lowering; no tensor surgery',
        'files': {str(p.relative_to(export_snapshot)): {'bytes': p.stat().st_size, 'sha256': file_sha(p)}
                  for p in export_snapshot.rglob('*') if p.is_file()}}
    (out / 'download.json').write_text(json.dumps(manifest, indent=2)+'\n')
    quantize(out)
    # The unchanged inference runner is deliberately reused. Its original local
    # output-folder name is renamed only after successful completion; it makes
    # no untrained-model claim in its report or model calls.
    probe(out, onejev_root)
    (out / 'baseline').rename(out / 'trained')
    baseline = json.loads((experiment_root / 'baseline/completed.json').read_bytes())
    trained = json.loads((out / 'trained/completed.json').read_bytes())
    report = {'baseline': baseline, 'trained': trained, 'trained_reference': str(snapshot),
        'trained_manifest_sha256': file_sha(out / 'download.json'),
        'same_frozen_cases': True, 'final_checkpoint_only': True,
        'not_fresh_evaluation_or_human_gold': True, 'quarantines_unchanged': True, 'deployed': False}
    (training_root / 'comparison.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--training-root', type=Path, required=True)
    p.add_argument('--experiment-root', type=Path, required=True)
    p.add_argument('--onejev-root', type=Path, required=True)
    p.add_argument('--export-name', default='export-001')
    args = p.parse_args()
    os.umask(0o077)
    run(args.training_root, args.experiment_root, args.onejev_root, args.export_name)


if __name__ == '__main__':
    main()
