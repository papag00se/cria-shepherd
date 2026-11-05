"""Offline GLiClass INT4 export using supported ONNX Runtime weight operators."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path

from suite.onejev_probe import file_sha


def set_matrix(model, node, value, *, block_size=None):
    """One owner for replacing a float or symmetric Q4 MatMul weight."""
    from onnx import numpy_helper
    from onnxruntime.quantization.matmul_nbits_quantizer import DefaultWeightOnlyQuantConfig, DefaultWeightOnlyQuantizer
    weights = {t.name: t for t in model.graph.initializer}
    if node.op_type == "MatMul":
        weights[node.input[1]].CopyFrom(numpy_helper.from_array(value, node.input[1]))
        return None
    if node.op_type != "MatMulNBits" or len(node.input) != 3:
        raise ValueError("Only float or symmetric INT4 MatMul weights are supported")
    attributes = {a.name: a.i for a in node.attribute}
    block_size = block_size or attributes["block_size"]
    config = DefaultWeightOnlyQuantConfig(block_size=block_size, is_symmetric=True, accuracy_level=1, bits=4)
    packed, scales, _ = DefaultWeightOnlyQuantizer(config).qbits_block_quant(value)
    for name, array in ((node.input[1], packed), (node.input[2], scales)):
        weights[name].CopyFrom(numpy_helper.from_array(array, name))
    next(a for a in node.attribute if a.name == "block_size").i = block_size
    return packed, scales


def check_exact_readout(packed, scales, value):
    import numpy as np
    nibbles = np.stack((packed & 15, packed >> 4), axis=-1).reshape(*packed.shape[:2], -1)
    restored = ((nibbles.astype(np.float32) - 8) * scales[..., None]).reshape(1, -1)[:, :value.shape[0]]
    error = float(np.max(np.abs(restored.T - value)))
    if error != 0:
        raise ValueError(f"Readout is not exactly representable: {error}")


def equalize_readout(model, source):
    """Positive ReLU-channel rescaling makes the scalar readout exactly INT4.

    For each channel choose t=-8 or +7 (zero stays zero), s=w/t > 0.
    Replace A[:,j], b[j], w[j] by s*A[:,j], s*b[j], t. Since ReLU(s*x)
    equals s*ReLU(x), the full-precision function is unchanged. No data,
    labels, gradients, loss fitting or coefficient search enters this operation.
    """
    import numpy as np
    from onnx import numpy_helper
    original = {t.name: t for t in source.graph.initializer}
    destination = {t.name: t for t in model.graph.initializer}
    nodes = {tuple(n.output): n for n in model.graph.node}
    linears = {i: next(n for n in source.graph.node if n.name.endswith(f"/scorer/mlp/mlp.{i}/MatMul")) for i in (2, 4)}
    bias = next(n for n in source.graph.node if n.name.endswith("/scorer/mlp/mlp.2/Add")).input[0]
    w = numpy_helper.to_array(original[linears[4].input[1]]).astype(np.float64)
    target = np.where(w < 0, -8., np.where(w > 0, 7., 0.))
    scale = np.divide(w, target, out=np.ones_like(w), where=target != 0).reshape(-1)
    changes = []
    for i, value in ((2, numpy_helper.to_array(original[linears[2].input[1]]).astype(np.float64) * scale), (4, target)):
        value = value.astype(np.float32)
        node = nodes[tuple(linears[i].output)]
        quantized = set_matrix(model, node, value)
        if i == 4 and quantized is not None:
            check_exact_readout(*quantized, value)
        changes.append({"tensor": linears[i].input[1], "elements": value.size})
    b = (numpy_helper.to_array(original[bias]).astype(np.float64) * scale).astype(np.float32)
    destination[bias].CopyFrom(numpy_helper.from_array(b, bias))
    changes.append({"tensor": bias, "elements": b.size})
    return {"operation": equalize_readout.__doc__, "channel_scale": scale.tolist(),
            "readout_values": target.reshape(-1).tolist(), "tensors": changes,
            "full_precision_function_preserved_algebraically": True}


def quantize_relative_table(model):
    """Quantize the positional table that feeds LayerNorm rather than Gather.

    A full-row Gather makes the standard supported Q4 lookup operator applicable.
    Its output replaces the floating initializer at every original consumer.
    This changes quantization, not the FP32 architecture or label-dependent logic.
    """
    import numpy as np
    from onnx import helper, numpy_helper
    from onnxruntime.quantization.matmul_nbits_quantizer import DefaultWeightOnlyQuantConfig, DefaultWeightOnlyQuantizer
    tensor = next(t for t in model.graph.initializer if t.name.endswith("encoder.rel_embeddings.weight"))
    indices, output = tensor.name + "_rows", tensor.name + "_decoded"
    model.graph.initializer.append(numpy_helper.from_array(np.arange(tensor.dims[0], dtype=np.int64), indices))
    gather = helper.make_node("Gather", [tensor.name, indices], [output], axis=0, name="/encoder_model/rel_embeddings/Gather")
    config = DefaultWeightOnlyQuantConfig(block_size=128, is_symmetric=True, accuracy_level=1, bits=4)
    replacement = DefaultWeightOnlyQuantizer(config).quantize_gather(gather, [model.graph])
    for node in model.graph.node:
        for i, name in enumerate(node.input):
            if name == tensor.name:
                node.input[i] = output
    model.graph.node.insert(0, replacement[0])
    return {"tensor": tensor.name, "shape": list(tensor.dims), "block_size": 128, "quantize_axis": 1,
            "operation": "symmetric Q4 full-row Gather before the original positional LayerNorm"}


def inventory(model):
    import onnx
    scales = {n.input[2] for n in model.graph.node if n.op_type in ('MatMulNBits', 'GatherBlockQuantized')}
    floating = [{'name': t.name, 'shape': list(t.dims)} for t in model.graph.initializer
                if len(t.dims) >= 2 and t.data_type in (onnx.TensorProto.FLOAT, onnx.TensorProto.FLOAT16, onnx.TensorProto.BFLOAT16)]
    return {'remaining_floating_weight_matrices': [t for t in floating if t['name'] not in scales],
            'operators': dict(Counter(n.op_type for n in model.graph.node)),
            'opsets': {o.domain: o.version for o in model.opset_import},
            'inputs': [v.name for v in model.graph.input], 'outputs': [v.name for v in model.graph.output],
            'initializer_elements': sum(math.prod(t.dims) for t in model.graph.initializer),
            'floating_matrix_initializers': floating}


def normalize_linear_layers(model):
    import copy
    import tempfile
    import onnx
    import onnxoptimizer
    from onnx.external_data_helper import load_external_data_for_model, load_external_data_for_tensor, uses_external_data
    from onnxruntime.quantization.onnx_model import ONNXModel

    def materialize_gemm_weights(graph, parents):
        scope = {**parents, **{tensor.name: tensor for tensor in graph.initializer}}
        for node in graph.node:
            # ORT's Gemm normalization transposes constant B in place. Only
            # those matrices need their values during the graph-only passes.
            if node.op_type == 'Gemm' and node.input[1] in scope:
                tensor = scope[node.input[1]]
                if uses_external_data(tensor):
                    load_external_data_for_tensor(tensor, folder)
            for attr in node.attribute:
                if attr.type == onnx.AttributeProto.GRAPH:
                    materialize_gemm_weights(attr.g, scope)
                elif attr.type == onnx.AttributeProto.GRAPHS:
                    for subgraph in attr.graphs:
                        materialize_gemm_weights(subgraph, scope)

    # The optimizer and version converter each serialize/copy the whole proto.
    # Carry external weight references through those graph-only transformations
    # instead of making several simultaneous copies of a multi-GB checkpoint.
    # Externalization mutates TensorProtos. Keep the caller's source usable;
    # one private copy is bounded, unlike every C++ pass copying all weights.
    model = copy.deepcopy(model)
    with tempfile.TemporaryDirectory(prefix='gliclass-normalize-', dir=os.environ.get('TMPDIR', '/var/tmp')) as folder:
        onnx.save_model(model, Path(folder) / 'graph.onnx', save_as_external_data=True,
                        all_tensors_to_one_file=True, location='weights.data', size_threshold=0)
        # Eliminate aliases of shared relative-attention projections, or their
        # FP32 originals survive static MatMul quantization.
        model = onnxoptimizer.optimize(model, ['eliminate_identity'])
        materialize_gemm_weights(model.graph, {})
        normalized = ONNXModel(model)
        normalized.replace_gemm_with_matmul()
        normalized.clean_initializers()
        if any(n.op_type == 'Gemm' for n in model.graph.node):
            raise ValueError('Gemm normalization incomplete')
        # GatherBlockQuantized needs opset 21; migrate operator semantics rather
        # than merely changing the header (e.g. ReduceMax's axes attribute).
        converted = onnx.version_converter.convert_version(normalized.model, 21)
        load_external_data_for_model(converted, folder)
        return converted


def validate_native_manifest(root):
    manifest = json.loads((root / 'download.json').read_bytes())
    snapshot = Path(manifest['snapshot'])
    for name, expected in manifest['files'].items():
        path = snapshot / name
        if path.stat().st_size != expected['bytes'] or file_sha(path) != expected['sha256']:
            raise ValueError(f'frozen native artifact changed: {name}')
    return manifest


def quantize(root, *, matrix_block=128, equalize=False, relative_int4=False):
    manifest = validate_native_manifest(root)
    import onnx
    import onnxruntime
    from onnxruntime.quantization.matmul_nbits_quantizer import DefaultWeightOnlyQuantConfig, MatMulNBitsQuantizer
    from onnxruntime.quantization.quant_utils import QuantFormat
    source = Path(manifest['snapshot']) / 'onnx/model.onnx'
    expected = manifest['files']['onnx/model.onnx']
    out = root / 'int4'
    out.mkdir()
    recipe = {'source_sha256': expected['sha256'], 'bits': 4, 'block_size': matrix_block, 'symmetric': True,
              'block_sizes': {'MatMul': matrix_block, 'Gather': 128},
              'equalize_readout': equalize, 'relative_position_int4': relative_int4,
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
    balancing = equalize_readout(model, model) if equalize else None
    normalized = root / 'normalized-fp32.onnx'
    onnx.save_model(model, normalized)
    normal = inventory(model)
    if relative_int4:
        quantize_relative_table(model)
    passes = [(('MatMul', 'Gather'), 128)] if matrix_block == 128 else [(('MatMul',), matrix_block), (('Gather',), 128)]
    for operators, block in passes:
        config = DefaultWeightOnlyQuantConfig(block_size=block, is_symmetric=True, accuracy_level=1,
            quant_format=QuantFormat.QOperator, op_types_to_quantize=operators,
            quant_axes=(('MatMul', 0), ('Gather', 1)), bits=4)
        quantizer = MatMulNBitsQuantizer(model, algo_config=config)
        quantizer.process()
        model = quantizer.model.model
    if balancing:
        import numpy as np
        weights = {t.name: t for t in model.graph.initializer}
        node = next(n for n in model.graph.node if n.name.endswith('/scorer/mlp/mlp.4/MatMul_Q4'))
        check_exact_readout(onnx.numpy_helper.to_array(weights[node.input[1]]),
                            onnx.numpy_helper.to_array(weights[node.input[2]]),
                            np.array(balancing['readout_values'], dtype=np.float32).reshape(-1, 1))
    path = out / 'model.onnx'
    # Preserve the producer's dependency order. ORT's ONNXModel saver re-sorts
    # only explicit edges, moving If nodes ahead of values their subgraphs capture.
    # Its quantization pass itself retains the valid native node ordering.
    onnx.save_model(quantizer.model.model, path, save_as_external_data=True,
                    all_tensors_to_one_file=True, location='model.onnx.data')
    onnx.checker.check_model(str(path))
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
    parser.add_argument('--matrix-block', type=int, choices=[16, 32, 64, 128], default=128)
    parser.add_argument('--equalize-readout', action='store_true')
    parser.add_argument('--relative-int4', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    quantize(args.root, matrix_block=args.matrix_block, equalize=args.equalize_readout, relative_int4=args.relative_int4)


if __name__ == '__main__':
    main()
