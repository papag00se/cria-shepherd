# Decision classifier training: tools and methodology

This explains the expanded GLiClass v2 fit and its lineage. It is not a claim of general accuracy or Java task usefulness. Exact results and source/artifact identities are in [expanded v2](gliclass-expanded-v2.md); how the candidate was reached is in [Lineage of candidates](#lineage-of-candidates).

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

The data tooling rejects duplicate/cross-partition IDs, scenarios and exact inputs. The synthetic exclusion inventory included both old qualified and held real/synthetic inputs.

## Training tools

New local research test outputs are written under `~/.cria/test-runs/outputs/research/`. The expanded-v2 native checkpoint, tokenizer, training and held examples, and training contract are in the gitignored repository directory `training/system1-v2/train-001/`. Other historical research artifacts remain at their recorded paths.

- Publisher model: `knowledgator/gliclass-v4-edge`, pinned revision `885af1af8a07edf4ed34df83ca0d995ed8201283`; Apache-2.0.
- Publisher GLiClass SDK, pinned to `6a00f8067648f25aa0f4f477d167c5f391cb4165`, plus Hugging Face Transformers and its native tokenizer.
- PyTorch, on the explicitly approved RTX 3090. The RTX 3080 was not used.
- Repository orchestration: `suite/gliclass_train.py`, `gliclass_probe.py`, `gliclass_export.py`, `gliclass_quantize.py`, and shared `training_updates.py`.
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

V2 completed 636 optimizer updates in about 93 minutes and agreed with all 836 TRAIN labels. That establishes fitting, not generalization. The recipe and model artifacts are recorded separately.

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

## Lineage of candidates

Receipts for each step live privately under `~/.cria/training/` and `~/.cria/experiments/`, with the actual model-call records; the per-step write-ups were retired once v2 shipped, keeping these decisions and numbers. All scores are against reviewed (not human-gold) targets on exposed historical cases unless stated.

1. **Ettin 68M encoder, three seeds, real-only versus real + 11 reviewed synthetics (rejected).** A frozen 24-fit matrix (whole-task-excluded folds, shared encoder with two binary heads, task/family loss weighting) was reproduced exactly from audited traces. Whole-task-excluded predictions were consequentially bad: the prespecified candidate missed **132 of 140 PLAN** briefings and blocked **15 of 18 DESCRIBES** directives as dictation. Java supplied 123 of the 140 PLAN targets; the Java-excluded fold trained on only 17 PLAN examples, so "both labels present in every fold" proved nothing about coverage. A mechanical investigation then showed the learning path was sound (every trainable tensor owned once by the optimizer, finite non-zero gradients, correct label order, an eight-example subset memorized by 200 updates) and the original weights agreed with 283/310 and 92/140 of their own retrospective training targets. The gap was training-versus-excluded-task, not a broken loop. The operator rejected the 68M model on size/capacity grounds; no other cause was established.
2. **OneJev 1.6 0.8B Q4 (untrained, then fine-tuned; insufficient).** The published GGUF is missing tensors for its auxiliary prediction block and fails to load; a clean re-export from the official checkpoint (`--no-mtp`, standard Q4_K_M, 529 MB, an experimental size exception only) matched **13/24** targets untrained. Reading answer-slot probabilities through the model's native typed-choice interface (not generated text) is the correct way to score it. A single frozen full fine-tune on the 514 real TRAIN cases (label-balanced strata, CE + Brier, 12 epochs) reached **120/130** (from 84/130 untrained) but missed 3 of 13 code-prescribing directives and blocked 2 of 5 descriptive ones, which activated the GLiClass follow-up.
3. **GLiClass v4 Edge, native INT4 (adopted).** Untrained INT4 matched **99/130** (native FP32 103/130); the full fine-tune (original pretrained reset, 514 TRAIN cases, seed 17, 12 epochs, final checkpoint only) reached **124/130** at INT4 with a 239,829,455-byte bundle, and the native FP32 reference agreed with all 130 INT4 decisions. Against the then-configured production guards on the same 130 cases the paired result was **unsafe approvals 22 → 3, false blocks 1 → 3, agreement 107 → 124/130**: the gain is on the retrospective-versus-plan decision, and dictation traded one unsafe approval for one extra false block. The earlier verdict "not reliable enough" had no agreed numeric bar or measured baseline; relative evidence replaced it.
4. **GLiClass v2 (this document's subject; shipped as the optional serving provider).** All 644 real cases plus 192 blind-reviewed synthetics, 64 reserved synthetic challenge cases: 54/64 → 64/64 (see [expanded v2](gliclass-expanded-v2.md)).
5. **Key-call replay, ornith1.5_9b / Java.** On the ten admitted guard calls from the three key historical sessions, both v1 and v2 agree 10/10 with the reviewed targets versus the original guards' 4/10: two PLAN leaks that originally passed are blocked and four false blocks removed; the existing command-dictation block was retained. All ten were TRAIN-exposed, no Java task was rerun, and no usefulness change is claimed.

### Lessons and process invariants

- **Fix export failures at the producer.** Quantization lost the shared relative-attention projections behind Identity aliases (a 440 MB partial artifact), raising the opset header alone left older `ReduceMax` attributes illegal (needs semantic conversion), and `Log(Sigmoid(x))` produced NaN at saturation for a trained model (lowered to `-Softplus(-x)`). No tensor, logit or metadata was patched by hand; each has a real-runtime regression, and every external weight shard is hash-checked before conversion. Failed conversion attempts are never counted as scores.
- **Serialize loading facts with the shared helper** (`training_updates.loading_receipt`): Transformers 5 returns sets; two separate trainers stopped before the first update on the same defect.
- **Report the right denominators.** Exposed diagnostics, TRAIN replay and a challenge set are separate quantities; paired synthetic scenarios are not independent samples; an old held set becomes TRAIN exposure the moment it trains a later model.
