# Direct weight repair on the exposed synthetic benchmark

## Scope changed explicitly

After the initial one-time TEST evaluation and the TRAIN/DEV-only readout experiment, the operator explicitly authorized using the same 600 synthetic examples as an **exposed development benchmark**: improve those results first, then investigate fresh examples later. Evaluation does not automatically train on examples or make a dataset useless. Repeated feedback/selection changes the interpretation, not its mechanical usability.

The work below uses that authorization. Benchmark errors guide diagnosis and candidate selection; the numerical weight solves still use **TRAIN** activations, paired TRAIN counterfactuals, and old-family TRAIN preservation inputs. No fresh-blind claim, gradient update, dataset overwrite, deployment, publication or INT4 conversion is made.

Source remains `~/.cria/training/progress-correctness-v2/continuation-20261106T001652Z/epoch-1/`, not the preceding DEV-selected 58-value edit. Prior results/checkpoints are retained.

## Operator correction — this is not the requested DONE/PARTIAL repair

The operator corrected the objective: **improve DONE correctness without sacrificing PARTIAL**, not aggregate accuracy or robustness to unrelated helpers. The projector candidate below recognizes only one more true DONE (99→100) while falsely approving eight more PARTIALs (82→90). **It is set aside, not recommended as a successful repair of the requested decision.** Its checkpoint is retained only as experiment provenance; nothing was deployed.

Re-screening all 39 existing edits finds **no improvement in true-DONE recognition while retaining DONE precision, PARTIAL correct count and PARTIAL false-DONE count**. A few protected readout edits retain 99/200 true DONE, increase PARTIAL correct 66→67 and reduce PARTIAL false-DONE 82→80; that is a tiny precision improvement, not meaningful DONE recovery. There was no successful DONE/PARTIAL result to claim from those initial 39 edits; the resumed work below constructs new edits rather than re-ranking them.

Future benchmark selection in `benchmark_repair.py` now uses those DONE/PARTIAL metrics. Macro-F1 and NOT_STARTED improvements cannot compensate for a regression in them. `done-partial-objective-correction.json` records the re-screen of existing outcomes; no new model forward was needed.

## Resumed DONE/PARTIAL work — a small targeted gain

The operator explicitly directed the investigation to continue with **new edits that recognize more genuinely DONE implementations without sacrificing PARTIAL**. Thirty-six new candidate evaluations were completed, starting from the original trained epoch-1 checkpoint, without any helper-function counterfactuals in the objective or follow-up evaluation:

1. Twelve final-scorer readout edits, constructed by linear programming from TRAIN DONE/PARTIAL margins and paired differences, with inequalities preserving source-correct answers and preventing new false approvals of TRAIN PARTIAL cases. These use a frozen-temperature surrogate; actual calibration is recomputed for evaluation. The best benchmark-compatible setting adds only one DONE and loses one PARTIAL on DEV, so it is not the final choice.
2. Twelve edits to the **bias-output weight row of the calibrator**, constructed from TRAIN constraints alone. This exposes a different, 256-feature decision representation instead of the scorer's 58 active coordinates. It still gives no useful joint benchmark/DEV improvement without collateral effects.
3. Twelve further calibrator-bias edits with **exposed DEV and benchmark examples included in preservation constraints**, while the margin-fitting objective remains TRAIN-only. This is direct use of those examples in the weight solve, not merely selection or fresh validation.

The selected new candidate is `dp-calibration-lp-margin0.05-l10.001-step1`, from `calibration-exposed-protection/`. The actual **reloaded saved checkpoint** scores:

- True DONE recognized: **99/200 → 101/200** (49.5% → 50.5%). Both additions were previously called PARTIAL, not NOT_STARTED.
- PARTIAL correctly recognized: **66/200 → 68/200** (33% → 34%).
- PARTIAL falsely approved DONE: **82/200 → 80/200** (41% → 40%). **No newly false-approved PARTIAL case** and no previously correct benchmark answer is lost.
- DONE precision: **54.70% → 55.49%**. Total false-DONE predictions across PARTIAL and NOT_STARTED fall **82 → 81**. One already-incorrect NOT_STARTED case changes from PARTIAL to DONE; true-NOT_STARTED recall remains 199/200.
- Full native DEV replay: DONE **118 → 123**, PARTIAL **84 → 85**, PARTIAL false-DONE **116 → 115**, and NOT_STARTED **196 → 197**. Correct total is **398 → 405/600**; no previously correct DEV answer is lost. Because DEV entered preservation constraints, this is not independent validation.
- **All 836 old-family TRAIN decisions are unchanged**, including seven inherited errors (829/836 correct). No old-family improvement is invented.

Benchmark confusion, truth rows / prediction columns DONE, PARTIAL, NOT_STARTED:

```text
[101,49, 50]
[ 80,68, 52]
[  1, 0,199]
```

### Why this edit is different

The calibrator's final linear layer produces two outputs per label: the inverse-temperature input and an additive bias. Only the second output's **weight row** is edited. Its input `g_k` depends on unchanged text/class representations and unchanged raw scorer logits; its temperature output is unchanged. Therefore, in real arithmetic, the calibrated-score change is **exactly `g_k · delta_w`**, not a derivative or a frozen-temperature approximation. The decision-preservation inequalities are linear in these weights. Every candidate is nevertheless checked with the real native scorer/calibrator.

The numerical solve minimizes TRAIN DONE/PARTIAL hinge-margin shortfall, paired-margin shortfall and a scaled L1 weight-change penalty using SciPy's HiGHS dual-simplex solver (SciPy 1.18.1 in the existing research venv). No gradients, backward pass, Torch optimizer or additional training epochs are used. Two target margins (0.05, 0.2), two regularization settings (0.001, 0.01), and three interpolation strengths (0.25, 0.5, 1) were evaluated per construction. These are numerical weight fits; the exposed inputs explicitly influence the final constraints.

Only **64 saved FP32 values** change, all in the bias-output row of `calibrator.mlp.6.weight`. The temperature row is bit-identical; all other 414 persisted tensors, including the complete encoder, class projector and scorer, are exact to the original epoch-1 checkpoint. Source checkpoints and datasets are untouched, and the saved candidate is separate.

This is a **small local repair, not a completion-correctness breakthrough**. The update norm is **3271.385** versus **0.21875** for the original bias-output row. One newly correct DONE is only about **5.34e-5** above PARTIAL in the full native evaluation, so its numerical fragility must not be hidden. There is no INT4/CPU/fresh-data qualification or deployment.

### Full-model checks and opened examples

The selected candidate was run through the complete encoder on all 600 DEV and 836 old inputs, then reloaded from its saved checkpoint for all 600 benchmark inputs. The **600 benchmark predictions match cached-head evaluation**, maximum logit difference `0.0006103515625`. DEV/old native evaluation differs from cached-head replay on **two DEV examples, both additional correct DONE answers**; maximum logit difference `0.000518798828125`. The reported DEV metrics above are the authoritative full-native results, not the smaller cached-head estimate. Large weights and near ties make these differences material, even though no preservation loss occurred.

All five changed benchmark examples were opened in full: two genuinely complete implementations move PARTIAL→DONE (whole caption-line counting and repeated-language minute totals with zero totals removed); two incomplete implementations move DONE→PARTIAL (a recursive tree leaf counter returning only child count, and frame duration using floor rather than fractional division); one already-wrong NOT_STARTED answer becomes DONE. Native classifiers provide logits and **no textual reasoning**; reasoning remains `null`.

Research runner: `suite/progress_correctness/done_partial_repair.py`. `benchmark_repair.py --skip-nuisance-controls` avoids repeating the unrelated-helper detour. Existing focused tests remain **10 passed, 2 skipped**, plus compilation and actual experiment checks; the new capture/linear-program runner has no automated model-level regression coverage, and no full-suite pass is claimed.

Artifacts: `~/.cria/training/progress-correctness-v2/done-partial-repair-20261106T030026Z/`, including `calibration-{0,1}/`, `calibration-train-fit/`, `calibration-exposed-protection/`, `checkpoint/`, `native-dev-old-confirmation.json`, `final-native-benchmark/`, `opened-benchmark-changes.json` and `final-result.json`. Full native DEV/old calls are in the preceding repair root's `dp-calibration-native-{0,1}/`. Neither the earlier 58-value DEV readout edit nor the set-aside class-projector edit is composed into this candidate. **No deployment or publication.**

## Measured result of the set-aside aggregate-score candidate

Previously selected by aggregate benchmark macro-F1: `projector-rank3-ns-protected-all-originals-1`.

Benchmark score improves from **364/600 (60.67%), macro-F1 0.57640**, to **389/600 (64.83%), macro-F1 0.63694**. It is selected on this exposed benchmark, not qualified on independent fresh data.

Truth rows / prediction columns, DONE, PARTIAL, NOT_STARTED:

```text
Source             Selected
[99,51, 50]       [100,82, 18]
[82,66, 52]       [ 90,92, 18]
[ 0, 1,199]       [  0, 3,197]
```

DONE recall **49.5% → 50.0%**, PARTIAL recall **33.0% → 46.0%**, NOT_STARTED recall **99.5% → 98.5%**. DONE/PARTIAL-only accuracy rises **165/400 (41.25%) → 192/400 (48%)**. False-DONE on PARTIAL gets worse, **82/200 (41%) → 90/200 (45%)**; DONE precision falls **54.70% → 52.63%**. This is not a reliable completion-approval detector.

Original DEV accuracy changes **398/600 → 394/600** (66.33% → 65.67%). No previously correct old-family TRAIN answer is lost: one inherited retrospective error is corrected, so old TRAIN correctness changes **829/836 → 830/836**. A preliminary status message incorrectly said all old decisions were unchanged; there is **one beneficial change**, not zero changes.

## Causal finding and localization

The original 58-readout-value DEV winner scores **359/600 (59.83%)** on the exposed benchmark, worse than its source. Checking the actual examples reveals implementations of the requirement called NOT_STARTED when they also add unrelated work.

A TRAIN-only counterfactual experiment keeps 128 existing DONE/PARTIAL implementations from 64 Python requirement groups intact and appends an unused top-level helper to the same Python file. Full unified-diff hunk counts are adjusted; source datasets are not rewritten. No fixture rerun was done for these counterfactuals: label invariance rests on the original code being unchanged and the new helper being unused, not a fabricated verifier result.

**NOT_STARTED predictions jump from 1/128 to 126/128** after the helper is added. Correct answers fall from 76/128 to 2/128. One complete opened example implements exact integer aircraft weight/moment checks correctly; the added helper merely returns `"Field notes"`, yet the answer becomes NOT_STARTED.

A crossed-representation replay with the real scorer and calibrator localizes the effect:

- Original text + original class representations: NOT_STARTED 1/128, correct 76/128.
- Helper text + helper class representations: NOT_STARTED 126/128, correct 2/128.
- **Original text + helper class representations:** NOT_STARTED 126/128, correct 2/128.
- **Helper text + original class representations:** NOT_STARTED 1/128, correct 76/128.

These hybrids are causal diagnostics, not naturally encoded examples or serving transformations. They refute our initial text-path suspicion. The helper-related error follows the **class-representation path**. The actual checkpoint has `normalize_features=false`, `extract_text_features=false`, `pooling_strategy=first`; no active L2 normalization is assumed. Existing head replay had already matched native outputs; inspecting the config corrected an inaccurate interpretation, not a hidden score-replay defect.

The three class-specific mean shifts have norms about 43.22, 43.21, 45.41; their singular values are 70.34, 29.01, 2.72. Erasing only the average shift across labels misses a substantial label-dependent component. Two independent Pi advisors (Terra and Sonnet) were engaged for analysis. The useful shared recommendation was to run the crossed-representation diagnostic before choosing an intervention; the actual GPU result corrected our text-path suspicion. Sonnet additionally wrote and removed scratch scripts and performed unrequested CPU learned-head/ridge checks despite the analysis-only/no-code instruction. Those computations and their numerical/theoretical claims are **excluded** from the construction and outcome evidence. No repository or experiment files were changed by the reviewers. A reviewer-reported logit mismatch compared the original epoch-1 head against a capture of the different 58-readout-value checkpoint; those are expected to differ. Exact checkpoint names and the native fidelity checks resolve that comparison without another baseline rerun.

## Direct weight construction

The edit changes `model.classes_projector.linear_1.weight`, the 1024×1024 matrix immediately after the encoder class representations, rather than the final scoring row. All other saved tensors, including the readout and calibrator, are unchanged.

For 128 TRAIN original/helper pairs:

- `K` has the three mean helper-added encoder class representations as columns.
- Desired first-projector-layer changes are `R = W (mean_original_classes - K)`.
- Protect original TRAIN class inputs, old-family TRAIN anchors, and representative true-NOT_STARTED TRAIN inputs. Let `P` project onto their orthogonal complement.
- Solve the rank-three update **`deltaW = R (Kᵀ P K)⁻¹ Kᵀ P`**, then cast the edited matrix to FP32.

The selected protection set includes all 384 original class vectors from the 128 paired examples, both class vectors of 33 old TRAIN cases, and all three class vectors of 32 true-NOT_STARTED TRAIN cases (one per selected family). One old anchor was added after a preceding candidate regressed on that exposed TRAIN case. Protection rank is **546**, leaving space for the three-key repair. Eigenvalues of `Kᵀ P K` are approximately **0.05492, 1.16988, 2.98862**. Float64 construction residuals are about `9.36e-12` on protected inputs and `2.86e-12` on the three target means; the actual saved model is FP32 and is checked separately.

The first full-step three-key candidates restored progress but also lost true NOT_STARTED answers. Adding actual TRAIN NOT_STARTED protection addresses that measured collateral damage, rather than simply increasing a preference for progress. All 128 original paired TRAIN answers remain unchanged; helper-added NOT_STARTED answers drop **126 → 5**, with correct helper-added answers **2 → 60**. This fixes much of the demonstrated sensitivity without pretending every resulting DONE/PARTIAL answer is correct.

Update norm is **260.9622**, versus source projector weight norm **31.5687**. The constructed update is low rank, but **all 1,048,576 FP32 matrix values change** after it is folded into the checkpoint. This is not the earlier tiny final-row edit, and its large norm is a material INT4/numerical concern. No quantization fidelity claim transfers from Astra's earlier checkpoint.

## Comparisons and cost

All model evaluation uses native FP32, the canonical label order, full untruncated inputs and the actual recomputed calibrator. Cached encoder representations avoid running the whole encoder for every candidate.

The exposed-benchmark comparison covers 39 distinct edits: nine pre-existing TRAIN-derived readout edits; ten progress/NOT_STARTED readout shifts; six helper-nuisance readout erasures; six single-direction class-projector erasures; four three-key repairs; and four three-key repairs with NOT_STARTED protection. Most do not improve the benchmark. They are retained rather than omitted from the outcome.

The initial single-direction readout/class-projector attempts were ineffective. The useful change came after paired counterfactuals, the crossed-representation diagnosis, and preservation of real NOT_STARTED inputs—not from the number of coefficient trials. The newly exposed benchmark informs those experiment choices and the final selection, so this is openly adaptive benchmark optimization.

Actual execution and artifacts live under:

`~/.cria/training/progress-correctness-v2/gradient-free-repair-20261106T013940Z/exposed-test-benchmark-20261106T020606Z/`

- Original repaired-model native benchmark capture: `report.json`, `calls.jsonl`, `activations.npz`.
- Initial comparisons: `candidates/`, `progress-candidates/`, `nuisance-candidates/`, `projector-candidates/`.
- TRAIN counterfactual captures: `nuisance-{0,1}/`, `nuisance-encoder*`, `text-pairs-{0,1}/`.
- Causal localization: `text-hybrids.json`, `text-hybrid-calls.jsonl`.
- Three-key construction/results: `rank3-*` and `rank3-ns-protected-*`.
- Final separately saved native checkpoint: `checkpoint/` and its `repair.json` tensor-by-tensor verification.
- Full native DEV/old-family verification is in the parent directory's `benchmark-native-{0,1}/`; all **1,436 decisions match cached-head evaluation**, maximum logit difference `4.76837158203125e-05`.
- `final-native-benchmark/` records a full evaluation of the actual reloaded saved checkpoint, not merely a cached-head estimate: **389/600, macro-F1 0.63694**, all 600 predictions identical to the cached-head candidate, maximum logit difference `4.100799560546875e-05`. Runtime was 26.60 seconds.
- `final-result.json` joins the actual native benchmark and DEV/old-family evidence, with exact checkpoint provenance and collateral metrics. `opened-final-changes.json` contains a full genuine correction (complete quadratic Bezier implementation plus unrelated helper, NOT_STARTED → DONE) and a genuine regression (only a Ruby label constant changed, NOT_STARTED → PARTIAL); both were opened end to end.

Runner: `suite/progress_correctness/benchmark_repair.py`; existing `evaluate_test.py` optionally captures activations, and `repair.py native` accepts the chosen tensor/checkpoint output path. The inference/capture runners still have no automated model-level coverage. After the operator corrected the objective, the existing metrics test was extended to reject the actual aggregate-score trade-off and prefer DONE improvement without PARTIAL sacrifice. It fails under the preceding macro-F1 selection policy and passes with the corrected selector. Focused tests: **10 passed, 2 skipped**. Compilation, native equivalence and exact saved-tensor comparisons are additional evidence, not a full-suite pass.

Fresh evaluation is a later question, not an approval gate invented for this work. The current result's scope is improvement of these exposed examples plus measured collateral effects on DEV and old TRAIN. No deployment or publication is authorized.
