"""Offline GLiClass INT4 export using supported ONNX Runtime weight operators."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path

from suite.onejev_probe import file_sha


def inventory(model):
    import onnx
    return {'operators': dict(Counter(n.op_type for n in model.graph.node)),
            'opsets': {o.domain: o.version for o in model.opset_import},
            'inputs': [v.name for v in model.graph.input], 'outputs': [v.name for v in model.graph.output],
            'initializer_elements': sum(math.prod(t.dims) for t in model.graph.initializer),
            'floating_matrix_initializers': [{'name': t.name, 'shape': list(t.dims)} for t in model.graph.initializer
                if len(t.dims) >= 2 and t.data_type in (onnx.TensorProto.FLOAT, onnx.TensorProto.FLOAT16, onnx.TensorProto.BFLOAT16)]}


def normalize_linear_layers(model):
    import onnxoptimizer
    from onnxruntime.quantization.onnx_model import ONNXModel
    # The published graph shares relative-attention projections through Identity
    # aliases. Static MatMul quantization otherwise retains their FP32 originals.
    model = onnxoptimizer.optimize(model, ['eliminate_identity'])
    normalized = ONNXModel(model)
    normalized.replace_gemm_with_matmul()
    normalized.clean_initializers()
    if any(n.op_type == 'Gemm' for n in model.graph.node):
        raise ValueError('Gemm normalization incomplete')
    import onnx
    # GatherBlockQuantized requires opset 21. The quantizer raises the header
    # without migrating older operators (e.g. ReduceMax's axes attribute).
    # Run the standard semantic version conversion before that wire change.
    return onnx.version_converter.convert_version(normalized.model, 21)


def validate_native_manifest(root):
    manifest = json.loads((root / 'download.json').read_bytes())
    snapshot = Path(manifest['snapshot'])
    for name, expected in manifest['files'].items():
        path = snapshot / name
        if path.stat().st_size != expected['bytes'] or file_sha(path) != expected['sha256']:
            raise ValueError(f'frozen native artifact changed: {name}')
    return manifest


def quantize(root):
    manifest = validate_native_manifest(root)
    import onnx
    import onnxruntime
    from onnxruntime.quantization.matmul_nbits_quantizer import DefaultWeightOnlyQuantConfig, MatMulNBitsQuantizer
    from onnxruntime.quantization.quant_utils import QuantFormat
    source = Path(manifest['snapshot']) / 'onnx/model.onnx'
    expected = manifest['files']['onnx/model.onnx']
    out = root / 'int4'
    out.mkdir()
    recipe = {'source_sha256': expected['sha256'], 'bits': 4, 'block_size': 128, 'symmetric': True,
              'operators': ['MatMul', 'Gather'], 'axes': {'MatMul': 0, 'Gather': 1}, 'accuracy_level': 1,
              'activation_compute': 'FP32; no internal input quantization/downcast',
              'algorithm': 'RTN; no task calibration data', 'format': 'QOperator',
              'onnx_version': onnx.__version__, 'onnxruntime_version': onnxruntime.__version__,
              'preprocessing': 'standard eliminate_identity, ONNXModel.replace_gemm_with_matmul, semantic ONNX opset 21 conversion; native-vs-export fidelity remains required',
              'source_module_sha256': file_sha(Path(__file__))}
    (out / 'recipe.json').write_text(json.dumps(recipe, indent=2) + '\n')
    model = onnx.load(source)
    before = inventory(model)
    # Gemm is a linear layer too. Normalize it through the standard graph pass
    # rather than leaving its learned weights unquantized or editing tensors.
    model = normalize_linear_layers(model)
    normalized = root / 'normalized-fp32.onnx'
    onnx.save_model(model, normalized)
    normal = inventory(model)
    config = DefaultWeightOnlyQuantConfig(block_size=128, is_symmetric=True, accuracy_level=1,
        quant_format=QuantFormat.QOperator, op_types_to_quantize=('MatMul', 'Gather'),
        quant_axes=(('MatMul', 0), ('Gather', 1)), bits=4)
    quantizer = MatMulNBitsQuantizer(model, algo_config=config)
    quantizer.process()
    path = out / 'model.onnx'
    quantizer.model.save_model_to_file(str(path), True)
    after = inventory(quantizer.model.model)
    if not after['operators'].get('MatMulNBits') or not after['operators'].get('GatherBlockQuantized'):
        raise ValueError('both linear and embedding quantization required')
    files = [p for p in out.iterdir() if p.is_file() and p.name != 'recipe.json']
    result = {'source': expected, 'normalized_fp32_sha256': file_sha(normalized),
              'before': before, 'normalized': normal, 'after': after,
              'files': {p.name: {'bytes': p.stat().st_size, 'sha256': file_sha(p)} for p in files},
              'complete_bundle_bytes': sum(p.stat().st_size for p in files),
              'not_a_quality_or_runtime_admission': True}
    (root / 'quantized.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'complete_bundle_bytes': result['complete_bundle_bytes'], 'operators': after['operators']}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    quantize(args.root)


if __name__ == '__main__':
    main()
