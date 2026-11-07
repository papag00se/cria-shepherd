# System 1 real-call continuation, November 6

The live candidate is the INT4 `cria/system1_bundle` and the matching native checkpoint is `cpu-fit-001/reference`. The original expanded-v2 checkpoint and frozen 836-row training / 64-row synthetic control cohorts are in `../train-001`. Both safetensors files use Git LFS. `cpu-fit-001` retains the CPU fit settings, 61 update events and completion receipt; its export directory retains the INT4 recipe and quantization report. The serving graph and weights are stored once in `cria/system1_bundle`, not duplicated here. Raw captures, reviewer spools, intermediate FP32 ONNX, local environments, and scratch symlinks are not included. Historical receipts preserve original machine paths and contemporaneous `deployed: false` values; they are provenance, not current configuration.

The frozen `train.json` contains 135 unambiguous real inputs; `reserved.json` contains 21 inputs from two held-out sessions, and the two ambiguity files contain 14 separately assessed cases, none of which was a hard training target. `split.json` records session assignments; exact family/state/policy deduplication and old-cohort checks left `prior_overlap.json` empty. Two duplicate events remain referenced via `source_ids`. These labels are assistant-reviewed, not human gold. The previous 130 real diagnostic cases were already exposed in the expanded-v2 fit; the 64 independently authored synthetic cases are controls, not fresh real evidence. See `RESULTS.md` for exposure and limitations.

The original local `prepare.py` joined real-call records to adjudications, selected whole reserved sessions by SHA-256 of the session ID modulo four, and deduplicated complete inputs. That preparation depends on private capture/reviewer sources and is not distributed. The commands below start from the **frozen, already adjudicated inputs**, not from raw captures. No reviewer rationale, native prediction or private reasoning was used as a model input or training target. `baseline-001` and `candidate-eval-001` are derived per-input evaluation records, not raw call captures; their reasoning fields are null. The additional fresh-input diagnostic used private source/reviewer material which is not published, and therefore is not reproducible from this checkout alone.

## Environment

Run from the repository root, with Git LFS installed and objects downloaded (`git lfs pull`). Use Python 3.13 and a separate environment outside the checkout. The actual run used Torch 2.8.0+cu128 on CPU, transformers 5.20.2, GLiClass commit `6a00f8067648f25aa0f4f477d167c5f391cb4165` (0.1.21), tokenizers 0.23.3, safetensors 0.8.0, NumPy 2.5.4, ONNX 1.23.2, onnxoptimizer 0.4.2 and onnxruntime-gpu 1.31.0. Despite the GPU build, all fitting and export in this recipe use CPU. For example:

```sh
python3.13 -m venv /var/tmp/system1-env
/var/tmp/system1-env/bin/python -m pip install 'torch==2.8.0' --index-url https://download.pytorch.org/whl/cu128
/var/tmp/system1-env/bin/python -m pip install 'transformers==5.20.2' 'tokenizers==0.23.3' 'safetensors==0.8.0' 'numpy==2.5.4' 'onnx==1.23.2' 'onnxoptimizer==0.4.2' 'onnxruntime-gpu==1.31.0' 'accelerate==1.15.0' 'gliclass @ https://github.com/Knowledgator/GLiClass/archive/6a00f8067648f25aa0f4f477d167c5f391cb4165.zip'
```

This identifies the observed direct dependencies, not a complete transitive lock. Different CPUs, library builds or dependency resolution can change floating-point results; the fit is seeded but bit-identical reproduction is not guaranteed. The original base-model training depended on earlier data and research receipts not all distributed here; the retained original checkpoint is the starting point for reproducing **this continuation**, not a claim that the original checkpoint can be rebuilt from scratch offline.

## Fit, export and evaluation

Set `PY` to that environment's Python. All outputs below must be new paths; these commands never replace the retained fit. The fit is intentionally expensive (the recorded run took roughly 2.8 CPU hours and 61 updates). It uses all 836 original training examples plus the 135 new examples, one FP32 epoch, accumulation 16, peak learning rate 5e-6, seed 17 and four Torch threads. Reserved and ambiguous labels are not read for fitting.

```sh
PY=/var/tmp/system1-env/bin/python
D=models/system1/l5-continuation-20261106
PYTHONPATH=. "$PY" "$D/fit_cpu.py" --out /var/tmp/system1-new-fit
# Or export the retained completed native checkpoint without fitting again:
PYTHONPATH=. "$PY" "$D/export_candidate.py" --fit "$D/cpu-fit-001" --out /var/tmp/system1-new-export
PYTHONPATH=. "$PY" "$D/evaluate.py" --reference "$D/cpu-fit-001/reference" --bundle cria/system1_bundle --fp32 /var/tmp/system1-new-export/export-001/normalized-fp32.onnx --out /var/tmp/system1-new-eval
PYTHONPATH=. "$PY" "$D/compare.py" --candidate /var/tmp/system1-new-eval --out /var/tmp/system1-new-comparison.json
# Compare the original retained paired evaluation without another inference:
PYTHONPATH=. "$PY" "$D/compare.py"
```

The export uses `suite/gliclass_export.py`, `suite/gliclass_quantize.py` and `suite/system1_package.py`: native ONNX, normalization, RTN symmetric INT4 block-128 MatMul/Gather, then bundle packaging. The generated intermediate and scratch layout are local outputs, not committed artifacts. It regenerates self-test selection using the 64 synthetic held controls; these labels do not train weights. Evaluation uses the frozen baseline's per-input state, labels and original token IDs, with native/runtime token identity checks; pass the freshly generated FP32 graph to check native/ONNX fidelity, or omit `--fp32` for native/INT4 only. The earlier original bundle is preserved in Git history and on the operator's machine, not required to compare against its retained predictions. Reproduced quantized bytes may differ with tool versions: compare graph and external-weight SHA-256 against `cpu-fit-001/export-001/quantized.json` and `cria/system1_bundle/manifest.json` rather than assuming byte identity.
