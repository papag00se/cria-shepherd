# Gradient-free repair of the continued native checkpoint

## Outcome

A direct edit to **58 FP32 values in the 128-value final scoring row** improves the selected epoch-1 checkpoint's DEV accuracy from **398/600 (66.33%) to 409/600 (68.17%)** and macro-F1 from **0.66258 to 0.68298**. PARTIAL false-DONE falls from **116/200 (58%) to 88/200 (44%)**, but DONE recall also falls from **118/200 (59%) to 101/200 (50.5%)**. This is a modest DEV improvement with real losses, **not a solved completion detector**.

All **836 old-family TRAIN replay decisions remain unchanged**, including their seven existing errors. The unchanged source gets 178/178 dictation and 651/658 retrospective examples right; the edit has those same scores. This is exposed TRAIN preservation, not independent old-family certification.

The consumed progress TEST was **not read, replayed, scored or used in construction**. No gradient/backward/optimizer update, retraining, INT4 conversion, deployment or publication took place. The checkpoint and original datasets remain separate and unchanged.

## Actual saved artifact

Source: `~/.cria/training/progress-correctness-v2/continuation-20261106T001652Z/epoch-1/`.

New standalone native checkpoint: `~/.cria/training/progress-correctness-v2/gradient-free-repair-20261106T013940Z/checkpoint/`.

The saved `model.safetensors` was compared tensor-by-tensor against the source: identical keys, shapes and dtypes; only `model.scorer.mlp.4.weight` differs, in 58 values. Config/tokenizer are saved with the new checkpoint. An actual reload has no missing/unexpected/mismatched keys and reproduces a complete DEV input's edited decision, with maximum logit difference `8.58306884765625e-06` from cached-head evaluation. `repair.json` records the source and selected candidate. Do **not** apply Astra's earlier checkpoint-specific 74-value edit to this checkpoint.

## Execution and construction

Runner: [`suite/progress_correctness/repair.py`](../../suite/progress_correctness/repair.py). Private experiment output is the parent of the new checkpoint path above.

1. **Parallel collection actually ran on both GPUs**, one process per card. Each captured 2,218 full native FP32 inputs: total 3,000 progress TRAIN, 600 DEV, 836 old-family TRAIN. No clipping or dropping. RTX 3090 capture took 136.84 seconds (peak Torch reserved 6,222,249,984 bytes); RTX 3080 took 124.75 seconds (7,293,894,656 bytes). These timings are the two particular shards, not a controlled single-versus-dual-card speedup measurement.
2. Hooks capture the encoder's class representations, text representation, final ReLU activations, raw/calibrated logits and actual inverse temperatures/biases. Full rendered inputs and token IDs are retained with result events. The original checkpoint is loaded read-only.
3. **Construction uses TRAIN only.** For final ReLU activation `h_c` and source inverse temperature `beta_c`, the local linear response of DONE-minus-PARTIAL is approximated by `a = beta_DONE*h_DONE - beta_PARTIAL*h_PARTIAL`. Solve for a readout change that moves TRAIN margins toward +1 for DONE and −1 for PARTIAL while preserving NOT_STARTED scores and common-mode response. This is supervised closed-form linear fitting, not gradient training and not a claim that the calibrator stays constant.
4. The first six edits compare three regularization strengths with/without exact protection of 32 old TRAIN anchors. Their 64 activation rows have rank 61. Exact preservation leaves a 67-dimensional algebraic nullspace, but many coordinates are inactive. The constrained candidates change no DEV decisions; the unconstrained candidates correct at most two net DEV answers. No unseen-information or theoretical performance-floor conclusion follows.
5. The first objective also lets large NOT_STARTED/common-mode scores dominate the tiny DONE/PARTIAL margin. The corrected construction normalizes each preservation block's Frobenius norm to the contrast block's norm and standardizes surviving coordinates. This is a correction to the solve's scale mismatch, not evidence of a newly learned code representation.
6. Five **TRAIN-family-excluded** folds choose regularization from `{0.0001, 0.001, 0.01, 0.1, 1}` for each of three constructions: exact old anchors, soft old-score preservation, or no old-score constraints. All states of an excluded progress family stay out of its fit, including NOT_STARTED preservation rows. An initial version included all TRAIN NOT_STARTED rows in those zero-change constraints; correcting it changes **none of the three final FP32 weight arrays**, so their already recorded GPU evidence is reused. Original and corrected construction records remain available. DEV/TEST never entered those folds.
7. Every resulting candidate is evaluated with the **real, recomputed calibrator**, not the frozen-temperature surrogate. Baseline cached-head replay matches all 4,436 native decisions; max logit difference is `4.863739013671875e-05`. The selected candidate is `balanced-unprotected`: no exact old-anchor guarantee, but measured preservation of all 836 old TRAIN decisions. The soft-old candidate reaches DEV macro-F1 0.67979; exact-old reaches the unchanged 0.66258. Selection is highest DEV macro-F1 among nine TRAIN-constructed edits, all of which retain the old TRAIN decisions in this run.
8. Selected edit is confirmed through the **complete native encoder on both GPUs** for all 600 DEV and 836 old TRAIN cases. All **1,436 decisions match** cached-head evaluation; max logit difference is `5.435943603515625e-05`. Verification runs take 51.41 seconds (3090, including save/check) and 43.34 seconds (3080). The separate reload check adds one DEV forward, not a TEST pass.

The selected update norm is **142.1433**, versus a source readout norm **31.6206**. That large change is a numerical/quantization concern, not a reason to describe the edit as tiny just because few values changed. No INT4 equivalence claim is made.

## DEV detail

Truth rows and prediction columns are ordered DONE, PARTIAL, NOT_STARTED:

```text
Source             Edited
[118, 82,  0]      [101, 99,  0]
[116, 84,  0]      [ 88,112,  0]
[  0,  4,196]      [  0,  4,196]
```

- DONE/PARTIAL-only correctness: **202/400 (50.5%) → 213/400 (53.25%)**.
- Paired correct-versus-partial margin ordering: **108/200 → 118/200**. This goes beyond a single common preference shift, but is still a small exploratory DEV result, not independent proof of semantic generalization.
- NOT_STARTED recall stays **196/200 (98%)**.
- DEV edits correct **63** prior wrong decisions and spoil **52** prior correct decisions: net **+11**, not 63 unqualified repairs.
- Selected edit TRAIN accuracy is **2,061/3,000 (68.7%)**, versus source **2,025/3,000 (67.5%)**. These are actual cached-head outputs with the true calibrator, not the approximate linear objective's scores.

`opened-dev-changes.json` includes complete actual inputs/responses for both a genuine repair and a regression. The conference selection implementation filters eligibility but omits the required sort; its false DONE becomes PARTIAL. A separate correct half-open schedule-overlap implementation changes from DONE to PARTIAL. Both were read end to end. Classifier outputs carry logits and no textual reasoning (`reasoning: null`).

## Evidence and limits

Authoritative files under the private experiment directory:

- `shard-{0,1}/{run.json,calls.jsonl,predictions.jsonl,activations.npz,completed.json}`: full capture and GPU resource measurements.
- `solve.json`, `candidate-weights.npz`: original six TRAIN-only constructions.
- `balanced-solve.json`, `balanced-weights.npz`, `cv-fold-correction.json`: corrected scale-balanced TRAIN-fold constructions and the unchanged-weight comparison after fold correction; initial records retained separately.
- `replay-summary.json`, `balanced-replay-summary.json`, per-candidate prediction files and `replay-calls.jsonl`: baseline and candidate actual-head results.
- `native-{0,1}/`: full-model confirmation of the selected edit.
- `result.json`: complete source/candidate metrics and native fidelity; `saved-checkpoint-reload.json`: actual standalone checkpoint reload.
- `checkpoint/repair.json`: saved tensor comparison and provenance.

No new automated tests were added to this experimental runner. Existing progress-data tests pass (10 passed, two skipped); compilation, exact saved-tensor checks, full native replay equivalence and one saved-checkpoint reload were executed. This is not a full repository-suite pass. No serving behavior changed and no live service restart was necessary.

The result is DEV-selected across multiple attempts, uses synthetic correlated groups and exposed old TRAIN, and is unqualified for deployment. No fresh progress evaluation remains in this workstream; the already consumed TEST is not silently reused. This experiment establishes a bounded native DEV improvement, not a general-purpose correctness repair or a comparison proving parity with Astra.
