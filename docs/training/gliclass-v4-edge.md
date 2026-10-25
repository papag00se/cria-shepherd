# GLiClass v4 Edge: native INT4 experiment and full fine-tune

## Authorization and scope

The operator preapproved clearing and using the RTX 3090. The ordered follow-up is: train/test OneJev first; if insufficient, test four-bit GLiClass v4 Edge; if its initial result is not strong, train it and retest its four-bit export. Do not ask again for GPU approval. Do not touch the RTX 3080 or deploy a candidate.

[Trained OneJev](onejev-finetuning.md) improved to 120/130 historical diagnostic agreement, but its code-prescribing boundary remained weak. That completed result activated this experiment. The same source identities, admitted labels, task partitions and quarantines remain unchanged. No rejected 68M matrix, synthetic augmentation or label release was introduced.

Private experiment root: `/home/jesse/.cria/training/gliclass-v4-edge-v1/`.

## Pinned native implementation

- Checkpoint: `knowledgator/gliclass-v4-edge`, revision `885af1af8a07edf4ed34df83ca0d995ed8201283`, Apache-2.0.
- SDK: Knowledgator/GLiClass commit `6a00f8067648f25aa0f4f477d167c5f391cb4165`.
- The publisher's System One renderer retains every state value. The complete state, frozen decision policy and two native label descriptions enter the official uni-encoder pipeline. The existing `offline_onejev_*` policy filenames are provenance; their semantic bytes are intentionally reused unchanged.
- Native single-label behavior is softmax over the **calibrated model logits**, then the maximum label probability. No generated prose, keyword rules, threshold fitting or private-reasoning targets are involved.
- The native tokenizer is checked against the same complete rendered string with truncation explicitly disabled. The pipeline has a non-truncating ceiling, followed by refusal above 16,384 tokens. All 644 admitted TRAIN/diagnostic inputs fit; the largest is 2,005 native tokens. There is no clipping, chunk voting or passage selection.

## Actual four-bit export

The starting graph is the publisher's FP32 ONNX model. Standard normalization removes Identity aliases, converts Gemm linear layers to MatMul and **semantically converts** the graph to ONNX opset 21. ONNX Runtime then performs symmetric four-bit round-to-nearest weight quantization, block size 128, for supported constant-weight MatMul and Gather operators. Gather axis 1 includes the word embeddings. MatMul accuracy level 1 fixes FP32 activation computation; no internal activation downcast or integer activation quantization is allowed. Other parameters, including required normalization and calibration state, remain accounted for in the serialized graph/data files.

The complete actual graph plus weight-data bundle is **239,672,212 bytes**, below the unchanged 250,000,000-byte weight limit. This is an actual saved artifact, not a parameter-count estimate or linear-only quantization claim. Tokenizer/configuration and eventual stdlib-compatible in-process serving remain separate deliverables and admission checks; this experiment does not certify deployment.

The normalized FP32 graph agrees with the actual native model on all **nine** frozen fidelity inputs: the existing eight TRAIN mechanics examples plus the longest TRAIN input per decision family, deduplicated. Both logits are captured with declared absolute/relative tolerance `2e-4`. The four-bit model then actually loads and evaluates every diagnostic case. Separate lossy-quantization controls on those same nine inputs preserve six native choices and change three; maximum absolute logit drift is 0.6585304141044617. **This is not exact native/Q4 parity**, and the quantization path is part of the measured decision pipeline. It is not evidence that the unquantized checkpoint has the same errors, nor a calibration set or a fresh quality score. Full rendered state, token IDs, input masks, logits, probabilities, source hashes and confusion matrices are retained privately.

### Export regressions caught before quality scoring

- The current ONNX Runtime quantizer requires its optional `onnx-ir`/`onnxscript` dependencies. Provisioning now includes them and tests the real import.
- A presumed optimizer pass name was not available. The exporter uses ONNX Runtime's actual `ONNXModel.replace_gemm_with_matmul` API; a transposed-weight/bias numerical regression preserves the operation.
- Shared relative-attention projections hid behind Identity aliases. Without canonicalizing aliases, static quantization retained FP32 projection weights and yielded a 440 MB partial artifact. A fails-before/passes-after test requires both shared projections to be lowered and numerically execute correctly. The standard Identity-elimination pass fixes the producer graph; no tensors or metadata are patched by hand.
- Gather quantization raises the graph to opset 21. Merely raising that header leaves older ReduceMax `axes` attributes illegal. A fails-before/passes-after real-runtime regression proves semantic version conversion, rather than a metadata override, preserves the reduction and makes the quantized graph executable.

No quality predictions from a failed or partial export are counted as the four-bit result.

## Completed untrained INT4 result

The fixed 130 cases are **37 DEV plus 93 archive whole-task diagnostics**, not fresh evaluation or human gold. Initial four-bit agreement is **99/130 (76.2%)**: 25/37 DEV and 74/93 archive. Retrospective-versus-plan agreement is 90/112; describes-versus-dictates agreement is 9/18. Twenty retrospective briefings were falsely marked as plans, two plans were missed, three descriptive directives were blocked, and six code-prescribing directives were missed.

An actual disagreement was read in full: complete native state/policy/tokens, calibrated logits and response probabilities, with no generated reasoning. The initial decision pipeline is not sufficient. This activates the already authorized training follow-up; it does not justify relabeling its errors, selecting another threshold or blaming model capacity.

A separate paired native FP32 reference audit also ran all 130 identical inputs: **103/130** agreement, with **122/130** native choices unchanged by INT4. This isolates the complete quantized path from the unquantized checkpoint: quantization changes some decisions, but the native untrained path is also insufficient. No reference result changes the training recipe, targets or quantization settings.

Authoritative private receipts: `baseline/completed.json`, `baseline/results.jsonl`, `baseline/native-inputs.jsonl`, `baseline/fidelity.jsonl`, `baseline/quantization-fidelity.json{,l}`, `baseline/native-fp32-{completed.json,results.jsonl}`, `quantized.json` and `int4/recipe.json`.

## Frozen training follow-up

Qualified training root: `train-001/`. The recipe and all consumed source files, native checkpoint/tokenizer/SDK files, input exports and policy bytes are bound in its immutable `contract.json`.

- One full active-graph fit from the original pretrained weights, not the four-bit inference artifact or a new randomly initialized head.
- Exactly 514 admitted real TRAIN cases; the 130 diagnostic targets never enter updates. No synthetic data, new admissions or partition changes.
- Seed 17, 12 fixed epochs, final checkpoint only. AdamW, peak learning rate `5e-6`, 5% warmup/cosine, zero weight decay, `foreach=False`, clip norm 1. The first used learning rate is zero.
- Microbatch one full native example, accumulate 16 using the actual short-batch divisor. Task/head/label strata receive equal total weight, `N/(K*n)`.
- Cross-entropy plus Brier, weight 1, over the two native calibrated logits. Option order alternates by epoch and sorted source-row index, with matching target remapping.
- FP32 master parameters; BF16 autocast through the native encoder, scorer and calibrator; FP32 final logits/loss. This differs explicitly from OneJev's FP32 answer-slot readout. No TF32, hidden precision/input/batch substitutions or held-out calibration.
- Native dropout 0.3 remains active during training; evaluation disables it. Gradient checkpointing is non-reentrant; GPU peak reservation must stay within 22 GiB.
- The one native `model.logit_scale` scalar is declared structurally inactive: this checkpoint has `normalize_features=False`, and the native uni-encoder uses that scalar only in the enabled normalization branch. It is explicitly excluded, not silently frozen after observing missing gradients. Every other native parameter, including the calibrator, must belong to the optimizer exactly once.
- Before the full fit, eight native TRAIN examples must be learned through the same loss/update path. Every active parameter must have a present finite gradient, and actual changed witnesses must cover first/last encoder layers, text/class projectors, scorer and calibrator. Connected zero gradient tensors are recorded rather than misclassified as disconnected paths. The full fit must reload the original checkpoint afterward.

The actual 3090 learning gate passed: **8/8 native tiny targets learned**, exact active optimizer membership, present finite active gradients and changed witnesses in all six required branches. The original pretrained checkpoint was reloaded and the fixed full fit completed: **12 epochs, 396 updates, 4,479.21 seconds**, with peak reserved GPU memory 16,613,638,144 bytes, below the 22 GiB ceiling. The final BF16 native TRAIN check matched **513/514** targets. These are mechanics/training checks, not held-task results. The frozen training sources are preserved at commit `3a035a1c`; later export/integrity corrections did not retrain or change the final weights.

The final source-bound full `python -m pytest` run passed **11,023 tests, 238 skipped**; the final native CPU toolchain run passed **24 focused tests, one skipped** (`tests/test_gliclass*.py`, `tests/test_training_updates.py`, `tests/test_onejev_train.py`). The actual standard full-model ONNX export was also smoke-tested from the original pretrained weights against eight native TRAIN inputs. That compiler check is not a quality score. Dynamic-sequence export is tested independently with genuinely longer and shorter complete inputs.

The accumulated optimizer update is shared with OneJev; existing independent derivative and one/three/sixteen-row parameter-update tests still cover that common path. New native encoder preparation, complete-input refusal, inactive-parameter and calibrator-membership tests are separate from the actual GPU learning gate.

## Completed trained INT4 result

The final native reference was exported, checked against all nine fixed native fidelity cases, quantized with the unchanged INT4 RTN/block-128/FP32-activation recipe and actually evaluated on the identical 130 diagnostics.

| Pipeline | All diagnostics | DEV | Archive diagnostics | Retrospective / plan | Describes / dictates |
|---|---:|---:|---:|---:|---:|
| Initial INT4 | 99/130 | 25/37 | 74/93 | 90/112 | 9/18 |
| Trained INT4 | **124/130 (95.4%)** | **36/37** | **88/93** | **109/112** | **15/18** |

The trained bundle is **239,829,455 bytes**, including both actual graph and weight-data files, below the unchanged weight limit. The trained native FP32 reference independently matches **124/130** reviewed targets and agrees with **all 130** INT4 decisions. This is measured decision parity on these inputs, not exact logit parity or a universal guarantee. Training materially improved the native pipeline (103→124/130) as well as its measured four-bit artifact (99→124/130).

Remaining reviewed disagreements: **one missed plan, two falsely blocked retrospectives, two missed code-prescribing directives and one falsely blocked descriptive directive**. Complete native packets were inspected, including a Rust briefing prescribing `Value::Number` wrapping that was accepted as retrospective (probability 0.999687), and a directive prescribing a `typeof fetch` check that was accepted as descriptive (probability 0.999997). High confidence does not make these decisions safe. No labels, thresholds, checkpoints or admissions were changed in response.

### Trained-export failure and qualified correction

The first trained conversion (`export-001/`, `finalize.exit=1`) stopped at FP32/native fidelity, before quality scoring. A real trained case had finite native calibrated logits `[6.748744, -6.862788]` but ONNX logits `[NaN, NaN]`. The legacy Torch exporter lowers the native stable `log_sigmoid(x)` as `Log(Sigmoid(x))`; near saturation this destroys the calibration entropy's numerical stability. The original-weight smoke test did not exercise that trained range.

The fix is at the local export producer: a scoped supported symbolic lowering emits the **same native operation** as `-Softplus(-x)` using standard ONNX operators. It does not alter the SDK, learned tensors, inputs, logits after evaluation or quantization settings. A real-runtime regression reproduces the original failure, tests the actual failing range plus non-saturated and ±1,000 logits, rejects nonfinite results and compares native values at the existing `2e-4` fidelity bound. Non-saturated controls prevent zero-filling from passing. `export-002/` then passed the original nine-case full-native fidelity gate and completed all 130 tests; the first failed attempt is not counted as a score.

Each explicit conversion attempt now owns a separate source graph and links to the same hash-verified final native reference files; it cannot overwrite a frozen earlier conversion or duplicate multi-GB weights. The artifact guard also hashes **every** native manifest file, including external tensor-data shards and tokenizer/native weights, before conversion or evaluation. A fails-before/passes-after actual external-weight mutation test proves that changing a shard while retaining the ONNX header is rejected before creating an INT4 artifact. Future full-fit reset-completion events are emitted only after the original native checkpoint actually reloads, not as an advance claim in the tiny-check receipt.

Authoritative private receipts: `train-001/trained.json`, `training-source.json`, `comparison.json`, `inspected-trained-{dictation,retrospective,missed-plan}.json`, and `export-002/{quantized.json,int4/recipe.json,trained/{completed.json,results.jsonl,native-inputs.jsonl,fidelity.jsonl,native-fp32-completed.json,native-fp32-results.jsonl}}`. Original training contract, partitions and model-call evidence remain unchanged. After the fixes passed full/native regression checks, the redundant rolling optimizer, original-weight smoke graph and failed conversion weight dumps were retired; qualified native/INT4 artifacts and actual model-call records remain.

**Outcome:** the authorized ordered experiment is complete. The [subsequent paired current-guard assessment](current-guard-comparison.md) establishes a relative improvement on these two historical semantic decisions: unsafe approvals fall from 22 to 3, at the cost of false blocks rising from 1 to 3. The earlier absolute “not reliable enough” judgment had no agreed numerical threshold or measured current-code baseline; it is superseded by this explicit comparison and tradeoff, not by a perfection requirement. This is not yet full-session or runtime admission certification. These are exposed historical diagnostics, with only 18 dictation-family cases and **zero fresh human-gold cases/groups**. Stdlib-compatible in-process serving, RSS/latency certification and fresh evaluation remain separate admission gates. No candidate was deployed and no production service was changed.
