# Decision classifier training: tools and methodology

This explains the expanded GLiClass v2 fit and its lineage. It is not a claim of general accuracy or Java task usefulness. Exact results and source/artifact identities are in [expanded v2](gliclass-expanded-v2.md), [the original GLiClass experiment](gliclass-v4-edge.md) and [the Java guard replay](ornith-java-system1-replay.md).

## What was learned

Two existing semantic guard questions, with complete policy and public input:

- A session briefing: **RETROSPECTIVE** state versus an operative **PLAN** for the future coding agent.
- A proposed public directive: **DESCRIBES** observed reality or a required outcome versus **DICTATES** unverified code or an exact command to copy.

These do not judge whether a briefing is true, whether it preserves the task, whether code compiles or whether work is complete. Those remain independent checks. Neither private model reasoning nor hidden reasoning traces were training targets.

## Data and review

The original qualified real corpus admitted 644 examples. Original v1 training used 514, with the other 130 reserved as development/historical diagnostics. The authorized v2 expansion moved **all 644 real cases into TRAIN**, adding Go, Node and Rust to the previous Java/Python/Ruby training coverage. It did not rewrite v1's original results or claim v2's exposed 130 cases remained independent tests.

Three authors proposed 192 training synthetics, balanced over the four labels. A separate test-only author proposed 64 more, without seeing the real/training examples or model predictions. The examples deliberately vary domains and language contexts, operative instructions versus quotations, and paired boundaries; paired examples share scenarios and are not independent situations.

Two isolated `pi/anthropic/claude-sonnet-5-5` reviewers independently read all 256 complete proposed inputs. Opaque IDs hid author/batch/group identities; the packets omitted author labels, rationales, ancestry and the other reviewer's answers. Admission required agreement between the author and both reviewers, valid evidence spans and allowed provenance. All 256 passed. The resulting fit had **836 TRAIN examples (644 real + 192 synthetic)** and **64 reserved synthetic TEST examples**. Old quarantined examples were not released or resurrected under new IDs.

These are assistant-reviewed labels, **not human gold**. The test set has only 32 paired scenario groups and shared generation/policy/review factors. Perfect performance on it is bounded evidence, not universal reliability.

The data tooling hashes the complete inputs and source captures, checks admission and partition membership, rejects duplicate/cross-partition IDs, scenarios and exact inputs, and binds the frozen cohorts and code to the run contract. The synthetic exclusion inventory included both old qualified and held real/synthetic inputs.

## Training tools

- Publisher model: `knowledgator/gliclass-v4-edge`, pinned revision `885af1af8a07edf4ed34df83ca0d995ed8201283`; Apache-2.0.
- Publisher GLiClass SDK, pinned to `6a00f8067648f25aa0f4f477d167c5f391cb4165`, plus Hugging Face Transformers and its native tokenizer.
- PyTorch, on the explicitly approved RTX 3090. The RTX 3080 was not used.
- Repository orchestration: `suite/gliclass_train.py`, `gliclass_probe.py`, `gliclass_export.py`, `gliclass_quantize.py`, `gliclass_expand.py`, and shared `training_updates.py`.
- Independent semantic reviewers ran through **Pi**, not the Claude provider. Earlier Claude-provider authentication failures are preserved; they were not successful reviews.

Inputs were rendered through the native GLiClass pipeline with the complete policy and state, full token IDs and explicit label order. No head/tail clipping, chunk voting or private-reasoning targets were used. Label-order alternation during fitting avoids making an option's position its identity.

## Frozen fit recipe and checks

V2 started afresh from the publisher's pretrained weights, **not** from the previous fitted classifier. The recipe was fixed before test inference:

- One seed (17), one fit, final epoch only; no checkpoint/seed competition or held-label tuning.
- Twelve epochs; learning rate `5e-6`; 5% warm-up then cosine decay.
- AdamW, no weight decay, gradient clipping at 1.
- One complete example per microbatch; accumulate 16, dividing a short final update by its actual example count.
- Task/question/label-balanced cross-entropy plus Brier loss (a penalty on incorrect predicted probabilities). Synthetics share one pooled task stratum; each pair is not granted a separate task weight.
- FP32 master parameters, BF16 native computation, FP32 loss, no TF32, dropout 0.3 and non-reentrant gradient checkpointing.

Before the real fit, an eight-case learning check verified that the training path could learn. The weights were then reset to pretrained before the authorized full fit. Gradient and actual parameter-update witnesses checked the active branches; inactive `logit_scale` was excluded because this configuration does not normalize features. Realized update counts and numerical-finiteness checks come from execution, not merely a loop claiming to have run.

V2 completed 636 optimizer updates in about 93 minutes and agreed with all 836 TRAIN labels. That establishes fitting, not generalization. The successful reset, complete inputs, exact recipe, source hashes and model artifacts are recorded separately.

## Export and quantization tools

The trained native model was exported to ONNX. ONNX Runtime executes the **actual saved CPU INT4 graph**, not a floating model with a four-bit size estimate.

Quantization is symmetric round-to-nearest, block size 128, on supported constant MatMul/Gather weights, with floating activations. It is post-training weight quantization, not training the model in four-bit arithmetic; no task calibration set was fitted. The graph plus external weight data totals **239,829,455 bytes**, below the 250,000,000-byte weight budget. Tokenizer files, executable libraries and process memory are separate quantities.

Export problems were repaired at their producers: standard graph/operator normalization and numerically stable `Log(Sigmoid(x))` lowering to `-Softplus(-x)`. No learned tensor or output-logit patch concealed a failure. Real ONNX Runtime regressions reproduce those incidents. Native FP32, exported FP32 and saved INT4 outputs were compared on the unchanged complete-input contract; native/export floating-logit tolerances remained `rtol=atol=0.0002`.

## What the results establish

On the reserved synthetic challenge, actual CPU INT4 decisions improved **54/64 (v1) to 64/64 (v2)**: eight unsafe approvals and two false blocks became correct. The 130 former real diagnostic examples also scored 130/130, but were now all TRAIN-exposed and must never be added to that independent denominator. V2 changed both real-language coverage and synthetic training, so this is not a synthetic-only ablation.

On ten exact-source admitted historical `ornith1.5_9b / Java` guard calls, both fitted versions give 10/10 reviewed agreement, versus the historical guard decisions' 4/10. Two PLAN leaks are blocked and four RETROSPECTIVE false blocks removed. All ten were TRAIN examples. This did not rerun Java, establish implementation improvement or raise a usefulness score.

The ordinary repository regression suite uses fake upstreams without GPU/network; real native/export tests additionally exercise installed PyTorch/ONNX/ONNX Runtime. The final expanded-data regression run recorded 11,047 passes and 238 skips; its native-focused run recorded 41 passes. Those are historical training-run receipts, not a claim about a later integration's tests.

## Production is a separate stage

Training required PyTorch/Transformers/GLiClass; production need not. The operator subsequently approved optional CPU-only, in-process `onnxruntime` and `tokenizers` dependencies to connect the fitted artifact to the two guard seats. [Serving and rollout](../system1.md) documents that separate runtime, its admission checks and activation. Installing a trained file alone is not deployment, and a replay of fixed guard inputs is not a full coding cell.
