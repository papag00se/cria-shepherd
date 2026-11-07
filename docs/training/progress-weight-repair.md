# Progress weight repair and gradient-free INT4 recovery

**Follow-up:** DONE recovery now survives weight-only INT4, a standalone native checkpoint is saved, and the reusable export/quantization commands reproduce all 261 checked logits exactly. Strict fidelity to the original FP32 candidate still fails; semantic generalization remains unresolved. See [the separately authorized INT4 follow-up](#separately-authorized-int4-follow-up) and [repeatable conversion](#saved-checkpoint-and-repeatable-conversion).

The following initial-study record remains historical and unchanged in substance. Completed 2026-11-04. **Not certified; not deployed.** The candidate was frozen using development and old-family TRAIN evidence before held-out validation. Fresh TEST was evaluated once, on that unchanged native candidate. Neither original checkpoint nor the live classifier bundle was overwritten.

## Outcome and the actual trade-off

A shared 74-value edit in the final scoring row recovers DONE predictions in full precision. It does not establish recovery of fine-grained code correctness. Standard INT4 conversion removes that recovery, so the edit fails the deployment acceptance criterion.

Fresh TEST contains 193 examples from 27 tasks. The baseline below is the pre-existing unedited AFTER evaluation in [`suite/progress_fresh/baseline-final-test.json`](../../suite/progress_fresh/baseline-final-test.json), read after the final candidate evaluation, not a second inference run.

| Metric | Unedited AFTER | Frozen native candidate |
|---|---:|---:|
| Accuracy | 104/193 = 53.89% | 114/193 = 59.07% |
| Macro-F1 | 0.49576 | 0.60920 |
| DONE recall | 0/81 | 67/81 = 82.72% |
| PARTIAL recall | 80/81 = 98.77% | 24/81 = 29.63% |
| NOT_STARTED recall | 24/31 = 77.42% | 23/31 = 74.19% |
| PARTIAL incorrectly called DONE | 0/81 | 52/81 = 64.20% |
| NOT_STARTED incorrectly called DONE | 0/31 | 0/31 |

The candidate emits 119 DONE predictions; **67/119 = 56.30% are correct**. The net gain is ten correct answers, not 67 free recoveries. NOT_STARTED recall falls 3.23 percentage points, within the brief's approximately five-point allowance. DONE recall and macro-F1 meet the requested numerical improvement conditions, but the false-DONE rate is a substantial practical cost.

Confusion matrices use rows = truth and columns = prediction, ordered DONE, PARTIAL, NOT_STARTED:

```text
unedited AFTER      frozen native
[ 0, 80,  1]        [67, 14,  0]
[ 0, 80,  1]        [52, 24,  5]
[ 0,  7, 24]        [ 0,  8, 23]
```

A fully opened false-DONE example, `guestbook-php/phpunit-config/PARTIAL`, asks for a PHPUnit configuration targeting `tests/` and a Composer test script. The diff only creates an empty `<phpunit bootstrap="vendor/autoload.php">` element. The frozen candidate nevertheless calls it DONE. This is an explicit missing requirement, not a label-noise argument. The complete rendered input, calibrated and raw logits, and the absent reasoning field are saved in `validation-opened-calls.jsonl`.

## Old families and export validation

There are **zero additional old-family prediction changes relative to unedited AFTER**, in the frozen native candidate, normalized FP32 ONNX, or INT4 ONNX:

| Cohort | Dictation | Retrospective |
|---|---:|---:|
| Reserved synthetic held-out | 32/32 unchanged | 32/32 unchanged |
| Existing real TRAIN replay | 18/18 unchanged | 112/112 unchanged |

These are 194 checks, **not 194 fresh held-out cases**: 64 are reserved synthetic cases and 130 are real training replay. All six deployed-bundle self-test cases are a subset of these checks and retain their labels. This verifies the self-test **case predictions**, not a run of the CPU-only production startup routine against its old frozen logits.

An inherited mismatch remains: `expand2-test-062` is DICTATES under the original BEFORE checkpoint and its reviewed target, but DESCRIBES under unedited AFTER. The candidate preserves AFTER's decision. Thus “no additional regression” must not be presented as equality with BEFORE or perfect old-family accuracy. The complete prompt and before/after/candidate results for this case are included in `validation-opened-calls.jsonl`.

| Representation | Old-family changes / 194 | DEV/control changes / 67 |
|---|---:|---:|
| Normalized FP32 ONNX vs frozen native | 0 | 0 |
| Standard INT4 ONNX vs frozen native | 0 | **41** |

The 67 progress inputs are 51 DEV rows plus 16 distinct corruptions; the correct control halves reuse existing DEV inputs. FP32 export agrees on all 261 checks, with maximum calibrated-logit differences of `3.48e-5` on old families and `6.38e-5` on progress. INT4 has much larger logit differences even where labels remain unchanged: up to 24.468 on old families and 12.855 on progress.

INT4 DEV confusion is `[[0,20,1],[0,18,3],[0,3,6]]`: **DONE recall returns to 0/21**. No INT4 fresh-test evaluation was performed; the conversion had already failed same-prediction validation, and fresh TEST was reserved for the one frozen native candidate score. There was no quantization-recipe adjustment, mixed-precision exception, or post-validation weight tuning.

The existing exporter fixes the class-slot count. Validation therefore used two graphs with identical frozen weights: two slots for the existing families and three for progress. A three-slot graph was not silently treated as compatible with the production two-slot decoder. No new serving bundle or family-routing implementation was installed.

## Exact frozen edit

Checkpoints:

- BEFORE: `training/system1-v2/train-001/reference` (gitignored repository directory).
- AFTER: `~/.cria/training/progress-v1/final/reference`.
- Frozen edit: `~/.cria/training/progress-v1/weight-study-20261104/candidate-weight.json`.

Only `model.scorer.mlp.4.weight`, shape `[1,128]`, is changed. All biases, encoder weights, projectors, and calibrator weights are unchanged. The edit is a globally shared scalar readout, not a DONE-slot conditional or an output-logit override.

Let `w` be the AFTER scoring row. Let `u` be the unit mean, over the 51 DEV inputs, of the scorer's second-ReLU activation for the DONE class minus that for the PARTIAL class. This direction construction is label-blind with respect to the true completion labels; it still uses DEV representations and is not an untouched evaluation.

Collect both class activations from 32 old-family TRAIN examples: eight per family/label, spread over complete-input lengths up to 700 tokens. Their 64 activation rows span a rank-64 subspace. If `Q` is an orthonormal basis for that span, define:

```text
P = I - Q Q^T
v = P u / (u^T P u)
w_new = float32(w - (w dot u) v)
```

This is closed-form linear algebra, without gradients, an optimizer, or iterative loss fitting. In exact arithmetic, it makes `w_new dot u = 0` while preserving the scoring row's dot product with every protection activation. The real calibrator was always recomputed; cached baseline temperatures or biases were not reused.

Only 74 values differ after FP32 rounding. The changed columns of row 0 are:

```text
[0, 2, 3, 4, 8, 10, 11, 13, 14, 15, 16, 17, 18, 19, 21, 22, 27, 28, 30, 33, 35, 36, 40, 41, 43, 44, 46, 48, 49, 52, 55, 56, 57, 58, 59, 60, 61, 64, 65, 66, 67, 71, 72, 76, 78, 79, 80, 81, 82, 83, 84, 86, 87, 89, 90, 92, 96, 97, 98, 100, 103, 105, 106, 107, 108, 110, 113, 114, 117, 118, 119, 123, 126, 127]
```

The JSON contains the complete old/new row and both direction vectors. The small parameter count does **not** imply a small perturbation: `norm(Pu) = 0.0059177`, the protective dual has norm 168.985, and the update norm is 31.637 versus the original row's norm 0.2743. The protection constraint is almost parallel to the undesired direction. This large cancellation was a quantization risk before validation; the full INT4 conversion then demonstrably lost the desired behavior. This study did not isolate which individual quantized matrix is responsible for that loss.

## Development evidence and selection

The first 24 GPU passes captured BEFORE/AFTER activations and tested four independent rewinds: the class projector, the complete head including calibration, the final four encoder blocks, and four label-path embedding rows. None changed a DEV label relative to AFTER. These negative component tests did not rule out directional edits, so investigation continued rather than declaring information absent.

| DEV variant | Changed values | DONE correct / 21 | PARTIAL correct / 21 | NOT_STARTED correct / 9 | Macro-F1 | Correct control-pair order / 16 |
|---|---:|---:|---:|---:|---:|---:|
| AFTER | 0 | 0 | 19 | 6 | .4233 | 8 |
| Remove identity direction from final readout | 57 | 13 | 13 | 7 | .6729 | 8 |
| Protected readout, selected | 74 | 15 | 10 | 7 | .6524 | 7 |
| Remove identity direction at class-projector input | 1,048,576 | 16 | 2 | 8 | .4697 | 13 |

The 57-value edit changed two of the first 32 old-family TRAIN decisions. The protected version preserved all 32 and then all 32 disjoint TRAIN probes, without reconstructing its protection subspace. Its full-native evaluation reproduced all 67 cached-head decisions. Selection favored this measured preservation over the highest DEV macro-F1; it was not revised after held-out or quantization results.

Other GPU probes included removal in the scorer's label-input block, removal of the BEFORE-to-AFTER class-contrast direction at the projector input, and a fixed-strength paired-correctness direction with a negative control. The latter direction was built only from four tasks; it did not improve matched-pair ordering on the three source-excluded tasks. Those tasks had been exposed in earlier DEV analysis, so this was not called a blind holdout. All variants and exact operations are in the direction reports and forward ledger.

The final protected candidate calls **11/16 correct control halves and 11/16 corrupted halves DONE**. The original AFTER margins rank 20/21 ordinary DEV DONE/PARTIAL pairs correctly, but DONE is longer in every pair; length alone ranks all 21. The controls therefore materially limit the interpretation of the natural-set improvement. Before progress continuation, BEFORE ranks 14/16 controlled pairs correctly, but also calls 16/21 ordinary PARTIAL examples DONE. Neither observation is a deployable repair.

## Research question: decision preference recovered, semantics unresolved

The intervention demonstrates a causal change in the decision preference and transferable recovery of DONE recall. It does **not** prove that a prior caused the original collapse, that requirement-correctness information has been recovered, or that such information is absent elsewhere in the encoder.

Closed-form cross-task representation probes and matched controls did not provide convincing evidence of a robust shared correctness direction. The best inspected controlled representation ranked 14/16 pairs correctly, but the task-grouped, 56-view multiplicity-adjusted sign-flip tail was about 20%. A negative probe is not proof of absence. The defensible answer is partial localization of an editable decision obstacle, with semantic recoverability unresolved—not question 3's definitive absence verdict.

The original logged-logit premise also required correction: 44 of 894 true-DONE LOTO examples went to NOT_STARTED, not zero. Identical rendered training inputs had conflicting recorded targets in 27 groups involving 187 rows, requiring at least 27 target disagreements among 3,770 rows. These are real data problems, not a demonstrated explanation of the entire collapse. Requirements such as a measured speedup need execution evidence that a diff alone may not supply; the opened PHPUnit omission, by contrast, is already decidable from the given input.

Further work would need a new discovery allowance, stronger length-matched semantic development controls, and a new untouched test set. The present fresh TEST has been consumed. A useful next investigation would localize quantization sensitivity and seek a less amplified direction; it must not tune against these TEST results or assume that keeping the readout alone in FP32 would repair encoder-induced perturbations.

## Execution, accounting, and deviations

- Main discovery: **50 recorded forward batches**, all on RTX 3080 UUID `GPU-393d4998-707c-0ef0-a514-761015477256`, maximum 64 examples per batch. Head replays counted as inference. No input was truncated.
- Separately authorized validation: **51 completed batches**, including two GPU ONNX export traces, 18 native old-family batches, 24 ONNX batches, and seven final fresh-test batches. All 193 fresh inputs appear exactly once in the final evaluation events. No validation result changed the candidate.
- Heavy ONNX operations were verified from runtime profiles: matrix multiplication, `MatMulNBits`, and `GatherBlockQuantized` ran on the RTX 3080. The operator subsequently clarified that CPU work was allowed but GPU inference was preferred; ONNX shape/index bookkeeping used the CPU. The RTX 3090 and its workload were not used by this work.
- Native Torch peak allocation reached 6.74 GiB during final testing. Torch's allocator counter does not measure ONNX Runtime's separate CUDA arena; the latter was configured with a 9 GiB limit. Do not interpret the ONNX ledger's zero Torch allocation as zero GPU memory use.
- **Protocol violation:** a delegated analysis-only reviewer reported 27 additional CPU learned-head computations on the 51 DEV rows, outside the original GPU-only/no-inference permission. These are not hidden in the 50-pass figure or relabeled free analysis. Their results and proposed calibrator edit were excluded; the candidate was selected from the primary GPU evidence. This was disclosed to the operator. Later CPU permission does not retroactively authorize the earlier calls. Accounting is in `protocol-deviations.json`.
- A metadata-only ONNX Runtime kernel-enumeration query segfaulted; it did not execute classifier inputs. An export logging attempt and an ONNX session-initialization attempt failed before a classifier forward began. Those setup failures are distinct from the completed forward ledger.
- Quantization was interrupted when the original agent scope was killed by systemd-oomd. Both exported sources were verified intact; only an incomplete quantization recipe existed. Conversion was rerun after reducing memory use, separately per graph. The local operator repaired the agent's scope limits; this work did not change system policy.

## Reproducibility and code changes

Private artifacts are under `~/.cria/training/progress-v1/weight-study-20261104/`:

- `forward-ledger.jsonl`, `validation-ledger.jsonl`: authoritative calls, inputs, hypotheses, operations, results, timing and allocator data.
- `candidate-weight.json`: exact frozen edit; `validation-results.json` and `summary.json`: consolidated results.
- `validation-fresh-test-{inputs,predictions,report}.json`: the one final evaluation; `validation-opened-calls.jsonl`: complete readable examples.
- `validation-old-native.json`, `validation-onnx-{fp32,int4}-{2,3}.json`: regression and fidelity results; associated profiles record operator placement.
- `validation-export-{2,3}/`: original native ONNX, normalized FP32, standard INT4 bundles and producer records. These are research outputs, not installed bundles.

Interpreter: `~/.cria/training/onejev16-trained-v1/venv/bin/python`. Source tools are [`suite/progress_weight_study.py`](../../suite/progress_weight_study.py), [`suite/progress_weight_directions.py`](../../suite/progress_weight_directions.py), and [`suite/progress_weight_validate.py`](../../suite/progress_weight_validate.py). Commands separate diagnosis, fixed-candidate validation, and reporting; there is no automatic test-set tuning loop. The `test` command was already executed once. To regenerate reports without inference, use `python -m suite.progress_weight_validate report` and `python -m suite.progress_weight_study summary` with that interpreter.

The existing [`suite/gliclass_quantize.py`](../../suite/gliclass_quantize.py) normalizer was repaired to carry external weight references through graph-only identity elimination and semantic opset conversion, materializing only Gemm matrices needed for transposition and reloading weights afterward. This avoids serializing multiple simultaneous copies of the 1.76 GB checkpoint. It does not change the quantization recipe: symmetric INT4, block 128, MatMul axis 0, Gather axis 1, round-to-nearest, FP32 activations, no calibration data. Both conversions completed with peak process RSS about **5.27 GiB** after the earlier interrupted path. The final helper additionally preserves its caller's source protobuf through one private copy; a full-size follow-up check kept source, normalized result and reference in memory, confirmed identical graph nodes and all 414 normalized initializers, and peaked at **6.68 GiB** (`normalization-memory-check.json`). No new inference was needed for that ownership-preserving change. The complete INT4 bundles are 240,052,336 and 240,052,354 bytes.

Initial-study verification: a direct normalization smoke check preserved constant-matrix transposition, eliminated aliases/Gemm, migrated opset semantics, and left no dangling external data; whole-classifier FP32 fidelity then preserved all 261 decisions. Existing related tests passed: `python -m pytest -q tests/suite_tooling/test_suite_tooling_classifier_experiments.py tests/suite_tooling/test_suite_tooling_progress_dataset.py -k 'not monotone_gather_backward'` → **22 passed, 2 deselected**. The backward tests were excluded under the no-gradient rule. No new automated unit tests were added; the new research runners were exercised by the recorded real validations. Production inference code, original checkpoints, and the live bundle were not changed by this work.

## Separately authorized INT4 follow-up

The operator subsequently authorized exploration needed for successful INT4 inference. This is a separate DEV/old-family investigation, not a revision of the frozen candidate's failed certification. The original fresh TEST was neither rerun nor used to construct these variants. Artifacts below are relative to `~/.cria/training/progress-v1/weight-study-20261104/int4-repair/`.

### Cause and function-preserving repair

Quantizing only the final 128-weight scoring row reproduces DONE collapse. Keeping only that row FP32 restores DONE, but leaves 12/67 progress discrepancies. Thus final-row rounding is sufficient to cause collapse, while upstream quantization also matters.

The repair uses positive channel scaling across the preceding ReLU. For each readout entry `w[j]`, choose `t[j] = -8` for negative entries, `+7` for positive entries, and zero otherwise. Set `s[j] = w[j]/t[j]` for nonzero entries, and one otherwise. Multiply the preceding linear layer's output column and bias by `s[j]`; replace the readout with `t[j]`. Since `s[j] > 0`, `ReLU(s[j]*x) = s[j]*ReLU(x)`. This preserves the real-arithmetic function and makes the readout exactly representable in symmetric Q4. The implementation verifies its actual packed representation, including smaller blocks. No data, labels, gradients, optimizer, or coefficient search enters this transformation.

FP32 equalization preserves all 67 progress decisions, with maximum calibrated-logit difference `6.383657455444336e-05`; it is not claimed to be universally bitwise identical after floating-point rounding. Equalization addresses the readout's rounding, not every upstream perturbation amplified by its large weights.

### Measured variants and limits

| Conversion | Progress differences / 67 | DONE correct / 21 | Interpretation |
|---|---:|---:|---|
| Original standard INT4 | 41 | 0 | Recovery erased |
| Equalized, matrix block 128 | 12 | 13 | Readout recovery survives |
| **Equalized, matrix block 64** | **5** | **14** | Selected research artifact |
| Block 64 with class projector/scorer/calibrator block 32 | 9 | 11 | Smaller maximum logit error, worse decision fidelity |
| Block 64 plus Q4 relative-position table | 10 | 13 | No remaining FP32 learned weight matrix, but worse fidelity |

**Precision correction:** “all-matrix INT4” was too broad a description of the selected artifact. It contains 202 `MatMulNBits` operators and one quantized token-embedding lookup. The standard exporter also retains a **512×1024 FP32 relative-position table**, which feeds LayerNorm rather than Gather. Activations, biases, normalization parameters and quantization scales are floating point. The explicit `--relative-int4` variant quantizes that table through a full-row Q4 Gather before the original LayerNorm; it is separately evaluated, not silently substituted for the selected recipe. Weight-only INT4 is not fully integer arithmetic.

Selected DEV confusion is `[[14,7,0],[6,13,2],[0,2,7]]`. Its five departures from the original native teacher are one lost correct DONE, three corrected ordinary false-DONE answers, and one corrected corrupted-control false-DONE answer. These are opened-example facts, not population estimates. Four corrections do not cancel a failure of strict prediction equivalence. Complete prompts and replies are in `opened-block64-changes-readable.json`; all variant replies for another fully rendered example are in `opened-followup-example.json`. This classifier emits no reasoning text.

The selected variant initially preserved all 64 old TRAIN protection/transfer decisions. On the subsequent **194-case old-family panel**, it changes only `expand2-test-062`, correcting the inherited AFTER error to DICTATES. Its dictation result is 50/50 correct and retrospective result 144/144 correct; there are no additional labeled errors. These comprise 64 reserved synthetic cases and 130 real TRAIN replay cases, not 194 independent fresh examples. Strict equivalence to AFTER/native nevertheless fails on that one corrected decision. The complete changed case is in `opened-final-old-change.json`. The fully quantized positional-table variant also gets all 194 targets right and changes the same inherited error.

Continuous errors remain substantial. For selected block 64, mean per-input maximum calibrated-logit error is 1.3027 on progress and 8.1203 on old families; maxima are 6.3225 and 10.2236. For the smaller-head-block probe, progress mean error worsens to 1.5649 despite the maximum falling to 3.0674. `followup-results.json` records per-input winner-versus-rival margins and their changes, not just flip counts. A reference margin larger than its absolute perturbation is a sufficient **per-input** preservation bound, not an unseen-input guarantee.

The control weakness persists: selected INT4 calls 11/16 correct control halves and 10/16 corrupted halves DONE. Quantization fidelity is not semantic recovery. Further generalization claims need a new untouched set; the original TEST remains spent.

### Rejected approaches and bounded review

- Retaining the entire head in FP32 still leaves 8/67 discrepancies at body block 128. Scorer-only FP32 also leaves eight, class-projector FP32 eleven, calibrator FP32 twelve, and token-embedding FP32 nine. These are interventions at specified configurations, not an irreducible floor or proof of a particular responsible layer.
- A noise-threshold protection construction retained two anchor singular directions and reduced amplification from about 169 to 3.26, but changed one old TRAIN decision in FP32 and left 11/67 discrepancies against its own FP32 reference. It was rejected.
- A single rank-four closed-form correction of teacher raw scores used four DEV tasks and 32 TRAIN anchors. The remaining DEV tasks, corruption controls, and transfer anchors did not construct its coefficients, but were already exposed diagnostics, not blind holdouts. It reduced maximum logit error while leaving 21/67 differences and only 7/21 DONE recall. It was rejected; no further fitting loop followed.
- Two read-only reviewers agreed on one bounded smaller-block probe rather than fitting the five remaining labels. The class projector, scorer and calibrator were included for architectural relevance and low byte cost; excluding the text projector was a budget choice, not a claim of irrelevance. The probe was rejected. A subsequent precision inventory uncovered the positional-table exception, motivating the separately reported strict-Q4 variant. Speculative Gaussian flip-count, empirical-SNR and “eight-flip floor” claims from one review were explicitly withdrawn and are not findings.

### Packaging, CPU compatibility and accounting

`equalized-block64-packed/` stores two class-slot graphs against one shared weight file. Private graph symbols are renamed consistently, including lexical subgraph captures; arithmetic is unchanged. Diagnostic outputs are removed, but model inputs and logits are not shortened or altered. CUDA replay gives **identical logits and decisions on all 261 inputs** compared with the unpacked selected graphs.

- Combined graphs plus shared weights: **248,069,490 bytes**, below the methodology's 250,000,000-byte graph/weight budget.
- Research runtime payload including tokenizer, config, policies and candidate self-test records: **256,426,726 bytes**. This larger quantity excludes research profiles/reports and is not mislabeled as the graph/weight measurement. No package is installed.
- CPU inference on six existing self-test inputs and three deterministic DEV inputs preserves their CUDA decisions; maximum CPU/CUDA logit differences are `2.96e-5` and `1.60e-5` respectively. This is a nine-input compatibility check, not full CPU panel validation.
- The real `System1Runtime` constructor, tokenizer, renderer, decoder and startup self-test pass all six old-family records generated for this candidate. None of the old live bundle's six frozen logit records match within its startup tolerance; preserving labels is insufficient. The live records are untouched. Progress still lacks production family registration/routing, despite the separately usable three-slot graph.
- CPU verification peaked at **1,615,749,120 bytes process RSS**. ORT CUDA sessions use a 9 GiB arena on the designated RTX 3080; their Torch allocator counters are not GPU-memory measurements. The RTX 3090 was not used.
- **122 completed follow-up batches:** 120 in `int4-ledger.jsonl` plus one export trace in each `reproduced-{2,3}/int4-ledger.jsonl`. Fifteen are explicitly authorized CPU compatibility/startup forwards; the other 107 are on the RTX 3080. No recorded forward failed. Conversion/setup failures before a forward remain separate, including the initial lexical-capture ordering failure. The earlier 50 discovery + 51 validation counts and the separately disclosed unauthorized reviewer work are unchanged. The new reviewers performed no inference.

The exporter save bug was independent of the weight repair: ORT's saver reordered explicit graph edges but ignored values captured by `If` subgraphs. The local quantizer now saves in the producer's valid order and runs the ONNX checker. Existing historical exports are not overwritten. A full-size standard conversion with the revised saver completed; the regression fixture fails under the historical saver and passes under the corrected path.

## Saved checkpoint and repeatable conversion

**Standalone native checkpoint:** `~/.cria/training/progress-v1/weight-study-20261104/int4-repair/checkpoint/`. It contains `model.safetensors` (**1,759,218,392 bytes**), native config, both tokenizer files, the exact readout edit and explanatory metadata. All 415 tensor keys, shapes and dtypes were checked: only the 74 recorded readout values differ from AFTER; every other tensor is identical. Config and tokenizer bytes are unchanged. This checkpoint contains the frozen repair **before** quantization's function-preserving equalization.

The checkpoint was actually reloaded, exported with both slot counts, and converted through the reusable command—not merely saved. Freshly reproduced INT4 inference gives **exactly the same calibrated logits on all 261 checks** as the selected research artifact. Evidence: `checkpoint/save-verification.json`, `reproduced-{2,3}/comparison.json`, `reproduction.log` and `reproduction-check.log`. The reproduced shared graph/weight package is 248,069,080 bytes; private serialization metadata differs slightly from the original research package.

Commands from the repository root, using a **new output directory**:

```bash
P="$HOME/.cria/training/onejev16-trained-v1/venv/bin/python"
R="$HOME/.cria/training/progress-v1/weight-study-20261104/int4-repair"
CKPT="$R/checkpoint"  # after retraining, point this at the NEW native checkpoint
RUN="$HOME/.cria/training/progress-v1/export-next"
export CUDA_VISIBLE_DEVICES=GPU-393d4998-707c-0ef0-a514-761015477256
export OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2
for c in 2 3; do
  "$P" -m suite.gliclass_export --checkpoint "$CKPT" \
    --example "$R/export-example-$c.txt" --classes "$c" --out "$RUN/export-$c"
  "$P" -m suite.gliclass_quantize --root "$RUN/export-$c" \
    --matrix-block 64 --equalize-readout
done
"$P" -m suite.progress_int4_study pack --out "$RUN" --variant candidate \
  --graphs "$RUN/export-2/int4/model.onnx" "$RUN/export-3/int4/model.onnx" \
  --checkpoint-path "$CKPT"
```

The example files are complete rendered trace inputs, not calibration/fitting data. No source checkpoint is edited. Export tracing is logged; weight conversion uses no gradients or task fitting. The selected recipe is symmetric round-to-nearest Q4, matrix blocks 64, token-embedding blocks 128, FP32 activations, `accuracy_level=1`, and exact-readout equalization. It deliberately retains the standard positional table in FP32. Adding `--relative-int4` selects the separate, less faithful measured variant.

**Do not copy this checkpoint's 74-value repair onto a newly trained model.** Its direction/protection solve was specific to the original checkpoint and development evidence. The export and data-free quantization transforms are reusable; the empirical recovery and preservation claims are not automatically transferable. Compare every new quantized candidate with its own native reference and requalify old families, completion errors, CPU behavior and byte size. The packing command produces research graphs and historical self-test provenance, not newly validated startup records or production progress routing.

Implementation owners: [`suite/gliclass_export.py`](../../suite/gliclass_export.py) exports arbitrary saved native checkpoints; [`suite/gliclass_quantize.py`](../../suite/gliclass_quantize.py) owns the reusable rescaling, Q4 conversion and positional-table option; [`suite/progress_int4_study.py`](../../suite/progress_int4_study.py) owns study comparisons, shared-weight packing, candidate CPU checks and follow-up reporting. Rebuild the consolidated report without inference using `python -m suite.progress_int4_study report --variant equalized-block64` with the training interpreter. It does not open the consumed TEST.

Follow-up verification: **32 passed, 2 backward tests deselected** across the quantization, classifier-experiment and progress-dataset test files. The new small deterministic export fixtures cover caller ownership/Gemm transposition, lexical `If` captures during saving, mixed block sizes, positional-table conversion, positive-ReLU equivalence, exact Q4 readout representation, and shared-weight/lexical-name preservation. They use no trained classifier, GPU, network or backward pass. The remaining higher-risk gaps are independent semantic generalization, full-panel CPU qualification, and production progress routing—not checkpoint persistence or repeatability of the measured conversion.
