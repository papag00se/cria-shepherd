# OneJev 1.6 0.8B Q4: completed bounded replay

## Scope and outcome

The operator explicitly accepted a larger Q4 OneJev experiment. That is an exception to the weight-size target **for this experiment only**, not a change to production admission. No training, production integration, quarantine release, or further rejected 68M matrix occurred.

The completed text-only Q4 replay matched **13 of 24 provisional reviewed targets**. This is an exposed, balanced TRAIN diagnostic, not fresh accuracy, human gold, or evidence that the larger candidate is deployment-ready. The experiment verifies that native typed-decision probabilities can be obtained; it does not establish a suitable guard.

No existing OneJev worker was running when this work started. The experiment used an isolated environment, six CPU threads, and a temporary loopback-only llama.cpp child. Both GPUs were excluded from these processes. The child was terminated after the replay. The subsequent two reference controls also finished.

## Artifact and compatibility investigation

Primary sources:

- [Official model and Apache-2.0 license](https://huggingface.co/OmniJev/OneJev1.6-0.8B).
- [Official supported GGUF decision interface](https://github.com/OmniJev/OneJev), pinned at `0b9e163f8114f94a40598c59b0bac473ff446f3c`.
- [Published third-party GGUF files](https://huggingface.co/mradermacher/OneJev1.6-0.8B-GGUF/tree/main), pinned at `74d2d1a64836edfd866293008c7265ed32b95f4d`.

The downloaded published `Q4_K_M` artifact is **529,297,920 bytes**, SHA-256 `3d0dcaf32647b0ed14d1e20d6bf81d8dd88a4e93bb1c56f3c993d341e0cf874a`. Its digest and size match the publisher's LFS metadata. Inspection finds 320 tensors and a `qwen35` architecture. It declares 25 blocks, including one auxiliary next-token-prediction block, but contains tensor layers only 0–23. The native loader stops before inference with `tensor 'blk.24.attn_norm.weight' not found`. No predictions or scores are attributed to that failed artifact.

Rather than editing metadata or fabricating missing tensors, the experiment obtained the official checkpoint at `c89933c277629b707895bff752c61d2b0664c85e` and used the existing converter's supported `--no-mtp --outtype f16` options, followed by its standard `Q4_K_M` quantizer. Converter/runtime source commit: `8345f333951c661d166b00e6f9362e553768f292`. No external source code was edited. No vision projector is needed for the text-only task.

The working re-export is **529,296,960 bytes**, SHA-256 `a22db794e13a8ecbe2e491ea2362eec2c76f91436cef272e237f9e0d208d1055`. It correctly declares 24 main blocks and no auxiliary block. It is a separate, explicitly identified artifact, **not a bit-identical repair** of the published file: direct comparison finds 263 of 320 tensor payloads identical and 57 different. The following results belong to this freshly converted and quantized artifact only.

## Frozen test and native interface

Before inference, the cohort was frozen to the first two sorted admitted real TRAIN IDs per task, head and reviewed label: three existing TRAIN tasks, four labels, two cases per cell, 24 cases total. Selection did not inspect OneJev outputs. All original real/synthetic quarantines and source holds remain unchanged. DEV, archive diagnostic EVAL and fresh evaluation remain unscored by this experiment.

The official `qev.llamacpp.LlamaCppEngine` supplies the decision probabilities. Its actual question type is `choice`; class order is `[RETROSPECTIVE, PLAN]` or `[DESCRIBES, DICTATES]`. The official SDK verifies single-token answer slots and equality of HF-versus-GGUF tokenization. It reads next-token option-slot scores and normalizes them over the declared options. This is **not classification by generated answer prose**. The one-token completion is a backend scoring operation; no reasoning is requested or scored.

The frozen adapter files are `cria/prompts/offline_onejev_retrospective.txt` and `cria/prompts/offline_onejev_dictation.txt`. They preserve the original semantic rules while replacing single-word generation instructions and inline input delimiters with the native typed-choice framing. The whole original `complete_input` is supplied as state. These are transport adaptations, not byte-identical original judge requests. Their hashes and the full rendered requests are retained.

There is no task-fitted calibration, prompt search, option-order averaging, threshold fitting or post-hoc variant selection. SDK defaults are frozen: `qev-labels-v2`, one option order, temperature 1. Complete native inputs fit an 8,192-token experimental limit; oversized inputs would stop, not be shortened or split. Context shifting is disabled. Full requests, rendered prompts, native tokens, probability-interface responses and backend wire exchanges were saved.

The runner also corrects a readiness integration mismatch: the current native server announces `listening on http://...`, rather than requiring the obsolete `server is listening` prefix. A regression verifies the actual endpoint-specific readiness signal. Canonical prompt loading preserves the already frozen transport bytes and rejects drift.

After the probe, a fail-before/pass-after regression corrected prediction bookkeeping to use the SDK's authoritative `choice`, rather than recomputing an argmax from probabilities that the SDK rounds to six decimals. A near-tie can round both displayed probabilities to 0.5 without changing the SDK's unrounded winner. All 24 captured native choices were checked against the existing reports: every prediction and probability is unchanged. The canonical loader was also checked byte-for-byte against every captured request; no new inference or changed prompt was used to improve the result.

## Actual reviewed-target agreement

Rows below describe targets and predictions; these are not human-gold accuracy claims.

- RETROSPECTIVE targets: 1 predicted RETROSPECTIVE, 5 predicted PLAN.
- PLAN targets: 0 predicted RETROSPECTIVE, 6 predicted PLAN.
- DESCRIBES targets: 3 predicted DESCRIBES, 3 predicted DICTATES.
- DICTATES targets: 3 predicted DESCRIBES, 3 predicted DICTATES.

Thus retrospective/plan agreement is **7/12**, dictation agreement **6/12**, and combined agreement **13/24**. This small, balanced subset cannot be compared directly to the old full-cohort task-exclusion scores.

Complete disagreement examples were inspected, not just aggregate counts:

- A briefing restates the original imperative task, describes implemented changes and identifies unverified requirements. Its reviewed target is RETROSPECTIVE, while Q4 returns PLAN with probability **0.642201**.
- A directive describes catching a named CSV-validation exception around an existing reader loop, handling it like an existing exception and skipping malformed rows. Its reviewed target is DESCRIBES, while Q4 returns DICTATES with probability **0.752414**. The full native directive remains in the private capture rather than being republished here.

The briefing example exposes a question-scope issue worth adjudicating: original-task restatement versus new instructions. The directive exposes the boundary between naming an existing call and supplying copyable implementation. Neither disagreement automatically proves a reviewed label wrong; no target was changed or newly admitted to make the score improve. Question/policy/label applicability remains an investigation question, not a settled causal explanation.

## Two unquantized backend controls

After the Q4 replay, the first disagreement per head was selected solely for two diagnostic controls, not for a new benchmark or model selection. The original checkpoint was loaded through the official CPU FP32 decision engine. Exact rendered-prompt equality was asserted before inference.

Both controls retain the same disagreeing class:

- Briefing: FP32 PLAN **0.659566**, versus Q4 **0.642201**.
- Directive: FP32 DICTATES **0.784827**, versus Q4 **0.752414**.

Quantization is therefore not the sole explanation for those two disagreements. This does not certify full-cohort numerical parity or rule out quantization effects elsewhere. The official CPU reference kernels were used; no training or calibration was performed.

## Validation

The settled `python -m pytest` run passed **11,013 tests, 224 skipped**, with source digests checked unchanged at completion. The focused probe tests passed **10 tests**. The native-choice rounding regression was demonstrated failing before the correction and passing afterward. Probability validation rejects wrong heads, nonfinite/out-of-range/non-normalized values and inconsistent native choices. No new inference was needed for the bookkeeping correction: every captured native prediction and policy byte was verified unchanged.

Aggregate machine-readable evidence is in [onejev-q4-result.json](onejev-q4-result.json). Full case text remains private.

## Evidence and boundaries

Private evidence root: `/home/jesse/.cria/experiments/onejev16-q4-v1/`.

- `contract.json`, `cases.json`, `artifacts.json`, `gguf-inspection.json`: pre-output cohort, adapter and initial artifact custody.
- `compatibility-inspection.json`, `tensor-payload-comparison.json`: measured published-versus-re-export distinction.
- `reexport/artifacts.json`, `reexport/execution.json`, `reexport/engine.json`: actual working artifact and backend identity.
- `reexport/calls.jsonl`, `reexport/wire.jsonl`, `reexport/results.jsonl`, `reexport/completed.json`: complete native calls, wire responses and authoritative result records.
- `reference-control-contract.json`, `reference-controls.jsonl`: explicitly post-hoc, two-case FP32 controls.

The setup/build/import diagnostics are not model-quality findings. Actual model calls and required custody remain distinct from disposable setup scratch. A public card's advertised calibrated probabilities do not establish calibration for these questions. This experiment does not establish CPU production memory/latency, an in-process stdlib-compatible deployment, a complete deployment bundle, fresh generalization, or permission to exceed 250 MB in production.
