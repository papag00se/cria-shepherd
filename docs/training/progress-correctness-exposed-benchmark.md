# Direct weight repair on the exposed synthetic benchmark

## Scope changed explicitly

After the initial one-time TEST evaluation and the TRAIN/DEV-only readout experiment, the operator explicitly authorized using the same 600 synthetic examples as an **exposed development benchmark**: improve those results first, then investigate fresh examples later. Evaluation does not automatically train on examples or make a dataset useless. Repeated feedback/selection changes the interpretation, not its mechanical usability.

The work below uses that authorization. The initial solves use TRAIN activations and benchmark selection; the first resumed calibrator solve includes exposed preservation constraints; the latest continuation **directly fits exposed benchmark DONE/PARTIAL margins**. These are different exposure levels, not independent validation. No gradient update, dataset overwrite, deployment, publication or INT4 conversion is made.

All candidates descend from `~/.cria/training/progress-correctness-v2/continuation-20261106T001652Z/epoch-1/`. The current selected lineage is original epoch-1 → 64-value calibrator edit → 113-DONE top-one edit → 124-DONE pairwise edit → 133-DONE physical-penalty top-one edit (benchmark identities use the RTX 3090 measurements). The original epoch-1 encoder and scorer remain unchanged. None composes the preceding 58-value readout edit or the set-aside projector edit. Prior results/checkpoints are retained.

## Operator correction — this is not the requested DONE/PARTIAL repair

The operator corrected the objective: **improve DONE correctness without sacrificing PARTIAL**, not aggregate accuracy or robustness to unrelated helpers. The projector candidate below recognizes only one more true DONE (99→100) while falsely approving eight more PARTIALs (82→90). **It is set aside, not recommended as a successful repair of the requested decision.** Its checkpoint is retained only as experiment provenance; nothing was deployed.

Re-screening all 39 existing edits finds **no improvement in true-DONE recognition while retaining DONE precision, PARTIAL correct count and PARTIAL false-DONE count**. A few protected readout edits retain 99/200 true DONE, increase PARTIAL correct 66→67 and reduce PARTIAL false-DONE 82→80; that is a tiny precision improvement, not meaningful DONE recovery. There was no successful DONE/PARTIAL result to claim from those initial 39 edits; the resumed work below constructs new edits rather than re-ranking them.

Future benchmark selection in `benchmark_repair.py` now uses those DONE/PARTIAL metrics. Macro-F1 and NOT_STARTED improvements cannot compensate for a regression in them. `done-partial-objective-correction.json` records the re-screen of existing outcomes; no new model forward was needed.

## Current selection — operator selects the stronger benchmark winner

**Selected checkpoint:** `~/.cria/training/progress-correctness-v2/done-partial-temperature-20261106T063629Z/aggressive-checkpoint/`, candidate **`dp-top1-binary-physical-l1-target0.05-partialfloor0.005-l10.01-step1`**. Its complete saved-model benchmark is **133 DONE / 99 PARTIAL / 79 PARTIAL false-DONE** on RTX 3090 and **137 / 100 / 79** on RTX 3080. Relative to the preceding 3090 result, that is **nine more correct DONE, eight more correct PARTIAL, unchanged PARTIAL false approvals**.

The initial report held this back under a stricter all-panel/device preservation screen. The operator clarified that improving the exposed benchmark is the priority, then explicitly selected this result: **“I want the latest one. Those are good results.”** That decision supersedes the initial holdback; the measurements do not change. DEV regressions, eight fewer TRAIN DONE answers, numerical sensitivity and exposure remain documented below. This is the current research selection, not deployment or fresh qualification. The previous 124-DONE checkpoint remains intact.

## Latest round — 24 new edits and complete saved-model checks

The operator requested another round of weight manipulation. **Twenty-four new weight candidates were constructed and evaluated**, starting from the verified 124-DONE checkpoint. The stronger physical-penalty alternative is now selected by the operator for its benchmark gains, accepting the recorded collateral trade-offs. The former source remains `done-partial-native-20261106T044008Z/checkpoint/`; its originally reported **RTX 3090** benchmark is **124 DONE / 91 PARTIAL / 79 PARTIAL false-DONE**.

The new round is recorded under `~/.cria/training/progress-correctness-v2/done-partial-temperature-20261106T063629Z/`. No original checkpoint or dataset is overwritten. There are no gradients, backward passes, Torch optimizer steps, added training epochs, helper counterfactuals, input changes, truncation, quantization, deployment or weight publication.

### New constructions, not re-ranking previous edits

1. Four temperature-row perturbations scale the final calibrator's inverse-temperature weight row by 0, 0.5, 1.5 or 2. Its bias and additive-bias output row are initially unchanged. Actual nonlinear inverse temperatures are recomputed on GPU. None alone meets the DONE/PARTIAL objective.
2. Eight compensating bias-row fits use the 0.5 and 1.5 temperature variants as initial points, with actual GPU logits, pairwise target margin 0.05, L1 penalties 0.001/0.01 and half/full steps. Protection still refers to the original 124-DONE model's decisions and gaps, not the perturbed model's changed answers. This separation is implemented in the shared `preservation` function and initial-point options of `done_partial_repair.py`.
3. Four bias-only pairwise fits penalize physical coefficient changes, normalized by the starting bias row's L1 norm, rather than RMS-scaled coefficient changes. Target margin is 0.05; penalties are 0.01/0.1, with half/full steps. No temperature edit is composed into these candidates.
4. Four more physical-penalty fits target both competing labels, including NOT_STARTED, using the same settings. These yield the two saved alternatives below.
5. Four final correction candidates start from the stronger alternative's actual endpoint outputs, retain the original 124-DONE reference, and enlarge PARTIAL and DONE guards to 0.01 and 0.005. Penalties are 0.1/1. Their benchmark PARTIAL false-DONE count is **81**, versus source **79**, for all four; none is promoted. These larger guards require updates of roughly 520,000–602,000 in norm and do not cure FP32 preservation failures.

All numerical fits directly use the exposed benchmark's 400 DONE/PARTIAL labels, plus exposed TRAIN/DEV/benchmark/old preservation constraints. This is numerical supervised fitting, not fresh validation. Sigmoid temperature effects come from actual GPU evaluation; the remaining bias-row solve is conditionally linear in real arithmetic, not a temperature derivative or neural gradient update.

### Saved-model results and accepted trade-offs

The stronger physical-penalty alternative, `dp-top1-binary-physical-l1-target0.05-partialfloor0.005-l10.01-step1`, is saved separately as `aggressive-checkpoint/`. On the **RTX 3090**, the complete reloaded model gives benchmark **133 DONE / 99 PARTIAL / 79 PARTIAL false-DONE**, versus source **124 / 91 / 79**. Its DEV has **121 DONE / 89 PARTIAL / 111 false-DONE**, versus source **124 / 88 / 112**: PARTIAL improves there, but DONE falls. Old-family decisions remain unchanged.

On the **RTX 3080**, the same saved alternative gives benchmark **137 DONE / 100 PARTIAL / 79 PARTIAL false-DONE**. This must be compared with a newly measured **same-device source** result, **124 / 90 / 80**, not silently with the old 3090 counts. The DEV comparison on that card is source **118 DONE / 86 PARTIAL / 114 false-DONE** → alternative **117 / 83 / 117**. **Three fewer correct PARTIALs and three more false approvals caused the initial holdback.** The operator now accepts that documented trade-off in selecting the stronger exposed-benchmark result; this must not be described as uniform PARTIAL preservation. All old-family decisions are unchanged on that card too.

The more conservative alternative, penalty 0.1, is separately saved as `conservative-checkpoint/`. Its complete saved-model benchmark is **127 DONE / 97 PARTIAL / 79 false-DONE** on both cards. But on the RTX 3080 its DEV PARTIAL falls **86 → 85**, and PARTIAL false-DONE rises **114 → 115**. It is not the operator-selected alternative. On the 3090 its DEV PARTIAL counts are unchanged, with one fewer correct DONE. One inherited old retrospective error is corrected on both cards; no correct old-family answer is lost. That old correction cannot buy the PARTIAL regression.

Both saved alternatives also receive complete native TRAIN verification on the **RTX 3080**, matching their same-device endpoint replay exactly. The stronger gives `[[364,634,2],[283,709,8],[1,8,991]]`; the conservative gives `[[364,635,1],[284,709,7],[0,9,991]]`. The source gives `[[372,626,2],[291,700,9],[1,8,991]]`. TRAIN PARTIAL counts improve, but eight fewer DONE answers are recognized. These are additional exposed-data trade-offs, not a uniform DONE-recognition improvement.

### What the device controls establish

The old source itself is not bit-invariant across devices: its 3080 benchmark has **90 correct PARTIAL / 80 false-DONE**, versus the originally recorded 3090 **91 / 79**. Those are additional hardware-conditioned observations, not a dataset change or a revision to the original measurement. For the stronger new alternative, cached endpoint replay versus full native 3080 evaluation differs on **29 of 2,036** critical-panel decisions; maximum raw-logit difference is **0.00026702880859375**, maximum calibrated-bias/logit difference **0.15625**. Full 3090 checks reproduce the endpoint benchmark counts constructed from 3090 prefix captures. The earlier exact 5,036-row replay result applied to its recorded per-panel devices, not arbitrary hardware.

Our large fitted coefficients amplify routine numerical differences into changed judgments. The new alternatives' bias-row norms are about **150,463** and **135,188**, versus the original epoch-1 row's approximately **0.219**. They change **199** and **170** FP32 values relative to the 124-DONE source, respectively; their temperature rows and all other 414 tensors remain unchanged. This is evidence about these edits and arithmetic paths, not a semantic-capacity limit, a quantization floor, or an excuse to attribute an incorrect judgment to the weights or hardware.

A complete native counterexample was opened on the same card for source and both alternatives: room allocation assigns available rooms but omits the required `ValueError` when a talk cannot be placed. The source correctly says PARTIAL; both alternatives falsely say DONE. Inputs are identical; raw logits and inverse temperatures are identical within that card; the changed additive biases cause the false approval. The stronger model's DONE win is only about **7.6e-6**. The inverted crop-height formula and a version-only CLI edit were also opened in full as rejected controls. Native reasoning remains `null`.

`evaluate_test.py` and new calibrator captures now record the actual GPU and visibility in their run metadata. Capture metadata describes its actual feature position rather than asserting that every caller leaves the temperature row unchanged. No GPU admission policy or machine resource policy is changed. Actual model computations remain on the authorized GPUs; CPU work is numerical fitting and reporting.

Evidence: all five pairs of candidate-evaluation directories, initial/final fit records, separate saved alternatives, `*-native-benchmark*` runs, `*-native-training/`, device-control and saved-reload calls under the preceding repair root's `temperature-*` directories, opened rejection examples, and consolidated `final-result.json`. Both GPUs are released after the round. Existing focused checks: **10 passed, 2 skipped**, plus compilation and actual native/tensor comparisons. No new automated model-level tests were written. **The stronger 133-DONE checkpoint is selected by explicit operator choice; the 124-DONE source remains intact. Nothing is deployed, quantized or published as weights.**

## Previous continuation — saved-model 124-DONE baseline, with PARTIAL preserved

**Selected at that phase:** `dp-pairwise-partialfloor0.005-l10.001-step1`, saved at `~/.cria/training/progress-correctness-v2/done-partial-native-20261106T044008Z/checkpoint/`. It starts from the preceding 113-DONE `conservative-checkpoint/`, not from the original epoch-1 weights or the earlier projector/readout experiments. The benchmark's 400 DONE/PARTIAL labels directly enter the numerical fit; TRAIN, DEV, benchmark and old-family examples enter preservation. This remains exposed-label optimization, not fresh validation.

The complete **saved checkpoint** was reloaded and evaluated on all 600 benchmark, 600 DEV, 836 old-family and 3,000 TRAIN inputs. No weight assignment or resave occurs in the final DEV/old reload check (`repair native --verify-only`). Authoritative comparison with the preceding saved model:

- Benchmark DONE: **113 → 124/200**; PARTIAL: **85 → 91/200**; PARTIAL falsely approved DONE: **80 → 79/200**. DONE precision **58.25% → 61.08%**. NOT_STARTED stays **199/200**. Confusion: `[[124,52,24],[79,91,30],[0,1,199]]`, **414/600** correct versus 397/600.
- DEV DONE: **123 → 124/200**; PARTIAL: **85 → 88/200**; PARTIAL falsely approved DONE: **115 → 112/200**. Confusion: `[[124,76,0],[112,88,0],[0,3,197]]`, **409/600** versus 405/600.
- **All 836 old-family decisions are unchanged**, including seven inherited errors: dictation **178/178**, retrospective **651/658**, total **829/836**. These are exposed TRAIN cases, not fresh qualification.
- Full-native TRAIN DONE: **367 → 372/1,000**; PARTIAL **688 → 700/1,000**; PARTIAL falsely approved DONE **301 → 291/1,000**; NOT_STARTED **991/1,000** unchanged. These replace earlier head-only TRAIN estimates for this comparison.
- Across the **1,400 true PARTIAL examples** in TRAIN, DEV and benchmark, **no previously correct PARTIAL answer is lost and no new PARTIAL is falsely approved**. This is example-level preservation, not merely compensating aggregate counts.

DONE preservation is not universal: benchmark has **14 newly correct DONE and three formerly correct DONE regressions**, for net +11. Seven corrections were formerly PARTIAL and seven NOT_STARTED. Five PARTIAL corrections were formerly NOT_STARTED; one, the missing daily-temperature floor, was formerly DONE. DEV has seven fixes and three losses; TRAIN has 22 fixes and five losses. No correct PARTIAL is among these losses. A complete preorder/postorder tree implementation is a genuine DONE→PARTIAL regression, not relabeled or excused as noise.

### Repairing numerical replay before fitting

Earlier cached-head reconstruction differed materially from full forwards near ties. This continuation captures the **exact final-calibrator input and raw logits from full, untruncated, single-example native forwards**. Encoder, scorer, calibrator prefix and temperature row remain unchanged, so those inputs can be reused while editing the final bias-output row. Replay invokes the actual calibrator on GPU; it is not a separately implemented scoring formula. Source replay reproduces all **5,036** native decisions and logits exactly. The selected edit's endpoint replay also matches all **5,036** complete-model outputs exactly, maximum logit difference **0.0**. The separate saved DEV/old reload matches the earlier edited in-memory run on all **1,436** outputs, maximum difference **0.0**.

GPU setup now installs the same existing gather implementation centrally in `repair.gpu()`, rather than selecting different implementations in different evaluators. The benchmark evaluator uses the shared prediction-record owner to retain actual raw logits, inverse temperatures and calibration biases as well as calibrated logits. No input, policy, label order or token content was changed or shortened.

### Objective, controls and remaining limits

Twelve new weight candidates were constructed and evaluated. The first eight use DONE-versus-PARTIAL hinge margins, DONE objective weight 2, target margin 0.1, L1 penalties 0.001/0.01 and half/full steps. Both constructions preserve existing top-one and correct binary score preferences; one adds an absolute **0.005** guard for currently non-approved PARTIAL examples. The latter produces the selected full-step, lower-penalty edit. SciPy HiGHS dual simplex performs the direct numerical fitting; there are no gradients, backward passes, Torch optimizer steps or additional neural-training epochs.

After the leading edit's full-native confirmation, four further candidates start from its actual recorded outputs and also enlarge DONE guard gaps to 0.005. Their endpoint benchmark false-PARTIAL approvals are **80, 80, 82 and 84**, all worse than the selected candidate's **79**, so none replaces it. Larger true-DONE counts do not buy additional false approvals. The same cached prefix remains valid because only the downstream bias row changes; reference-output overlays retain input/gold metadata from the original captures.

Ignoring NOT_STARTED only as a diagnostic on the same three-label forwards, DONE/PARTIAL score preferences improve from `[[127,73],[96,104]]` to `[[138,62],[89,111]]`. Both classes improve this time. This is **not** a separate native two-label evaluation, a proof of a general semantic separator, or fresh generalization.

The selected checkpoint changes **183 FP32 values** relative to the preceding model, **212** relative to original epoch-1, all in the bias-output row of `calibrator.mlp.6.weight`. The temperature row and all other **414 persisted tensors** remain unchanged. Update norm is **108,395.459** relative to the preceding model and **108,257.281** relative to original epoch-1, whose row norm is about **0.219**. The smallest benchmark DONE winning margin is **3.0517578125e-5**. Exact replay does not remove this severe numerical-conditioning concern: real-arithmetic linear constraints can still be violated by the eventual FP32 dot product. Larger guards did not guarantee preservation in the rejected cohort.

Opened complete native examples include correct letterbox-bar calculation (PARTIAL→DONE), accumulation missing the nonnegative daily floor (DONE→PARTIAL), the tree-traversal regression, TRAIN rainfall aggregation with the wet-station function still missing (NOT_STARTED→PARTIAL), and a correct DEV building/status filter (PARTIAL→DONE). Native reasoning is `null`; no textual explanation is invented.

Artifacts under `done-partial-native-20261106T044008Z/`: source `calibration-{0,1}/`, `source-endpoint-fidelity.json`, the two `pairwise-floor*` fits and evaluations, `both-floor-fit/` and its four rejected evaluations, separate `checkpoint/`, saved-model `final-native-benchmark/`, `native-training-confirmation/`, `saved-dev-old-verification.json`, opened examples and consolidated `final-result.json`. Final saved DEV/old inputs/results are in the preceding repair root's `dp-saved-endpoint-verification-0/`; its run metadata records the checkpoint path, no weight assignment, no checkpoint save and clean loading keys.

Existing focused checks: **10 passed, 2 skipped**, plus compilation, actual native comparisons and saved-tensor comparisons. No new tests were written; there is still no automated model-level regression suite for this fitting/capture path, and no full-suite pass is claimed. **Selected for this exposed DONE/PARTIAL objective only. FP32 only; no quantization, CPU qualification, fresh validation, deployment or weight publication. Originals and previous checkpoints are untouched.**

## Previous top-one continuation — a larger verified DONE-recognition gain

The operator asked to continue improving the results. Twelve new calibrator-bias weight candidates were constructed and evaluated, using the exposed benchmark's 400 DONE/PARTIAL examples **directly in the fitting objective**, rather than only in preservation or selection. No helper counterfactuals, input changes, dropped inputs, gradients, backward passes or additional neural-training epochs are involved.

The selected candidate is **`dp-top1-benchmark-l10.01-step1`**, saved separately at `~/.cria/training/progress-correctness-v2/done-partial-top1-20261106T033639Z/conservative-checkpoint/`. Actual **complete-model, saved-checkpoint evaluation**, compared with the preceding 64-value candidate:

- DONE correct: **101 → 113/200**, recall **50.5% → 56.5%**.
- PARTIAL correct: **68 → 85/200**, recall **34% → 42.5%**.
- PARTIAL falsely approved DONE: **80 → 80/200**. No newly false-approved PARTIAL benchmark example; no previously correct benchmark answer is lost.
- DONE precision: **55.49% → 58.25%**. The one inherited false-DONE on NOT_STARTED remains; NOT_STARTED correct stays **199/200**.
- Benchmark total: **368 → 397/600**. This aggregate does not replace the class-specific objective.
- Full native DEV confusion is unchanged: `[[123,77,0],[115,85,0],[0,3,197]]`, **405/600**. One previously correct DONE becomes PARTIAL and another DONE is corrected; unchanged totals do **not** mean all DEV decisions are unchanged.
- **All 836 old-family TRAIN decisions are unchanged**, including the seven inherited errors, **829/836 correct**. This is not fresh old-family qualification.

Relative to the original epoch-1 benchmark result, DONE is **99 → 113**, PARTIAL **66 → 85**, and PARTIAL false-DONE **82 → 80**. The new benchmark confusion is `[[113,59,28],[80,85,35],[1,0,199]]`.

### Construction and what improved

The new objective has one shared hinge slack per example against **both** competing labels, so it targets actual top-1 decisions rather than DONE-minus-PARTIAL while ignoring NOT_STARTED. DONE examples receive twice the PARTIAL objective weight. Target margin is 0.1. The same linear additive-bias edit preserves source-correct decisions and prevents new PARTIAL approvals in the real-arithmetic construction; an equality also retains the mean TRAIN bias contribution. SciPy HiGHS dual simplex fits two L1 penalties (0.001, 0.01), with half/full steps: four candidates per construction.

Three constructions were completed: ordinary top-1 fitting; additional preservation of existing DONE/PARTIAL score preferences even when NOT_STARTED dominates; and that preference protection with a larger 0.05 preservation buffer. TRAIN, DEV, benchmark and old examples enter preservation. The benchmark labels also enter the objective. This is **direct numerical supervised weight fitting on exposed examples**, not merely evaluating or selecting TRAIN-derived weights.

Eleven of the twelve additional correct DONE answers were formerly NOT_STARTED; one was formerly PARTIAL. All seventeen additional correct PARTIAL answers were formerly NOT_STARTED. Eleven further genuine DONE examples move NOT_STARTED→PARTIAL and remain wrong. Thus the measured gain is real three-label DONE recognition, **not a demonstrated clean improvement of DONE-versus-PARTIAL discrimination in isolation**. As a diagnostic, taking the larger of the existing DONE/PARTIAL scores while ignoring NOT_STARTED changes truth-row confusion `[[104,96],[83,117]] → [[127,73],[96,104]]`: DONE preference improves but PARTIAL preference worsens. This is not a separate two-label native evaluation; the model still receives all three labels. The actual three-label PARTIAL count and false approvals do not regress, but that masking dependence must not be sold as robust semantic separation.

TRAIN head-only replay changes `[[370,624,6],[302,683,15],[1,9,990]] → [[368,629,3],[302,687,11],[1,8,991]]`: two fewer correct TRAIN DONE, four more PARTIAL, unchanged PARTIAL false-DONE. No full-native TRAIN rerun or broad generalization improvement is claimed.

### Native checks rejected the more aggressive edits

The weaker-penalty candidate initially gives cached-head **125 DONE / 89 PARTIAL / 80 PARTIAL false-DONE**, but the complete saved model produces **81** false-DONE PARTIALs. It is **not accepted**, despite its larger DONE count. A preference-protected, larger-buffer candidate gives native benchmark **110 DONE / 94 PARTIAL / 78 false-DONE PARTIAL**, but native DEV PARTIAL falls **85 → 82**, with false-DONE **115 → 118**. It is also set aside. Both artifacts and all comparisons are retained.

The selected higher-penalty edit still has material numerical sensitivity: cached-head and full-native evaluation differ on **five of 2,036** benchmark/DEV/old decisions, maximum calibrated-logit difference **0.009033203125**. Three benchmark differences merely exchange wrong NOT_STARTED and PARTIAL answers; two DEV differences exchange a DONE fix and loss. Reported results above are full-native, not an assertion of exact head fidelity. The original reference cache itself differs from the previous saved-model results on one near-tie benchmark answer.

The saved matrix differs from the previous candidate at **103 FP32 values**, and from original epoch-1 at **132 values**, all in the bias-output row of `calibrator.mlp.6.weight`. The temperature row and all other 414 tensors are unchanged. Update norm relative to the preceding candidate is **6449.248**; total change from original epoch-1 is **7220.454**, versus the original row norm about **0.219**. A newly correct straight-alpha compositing implementation wins DONE by only about **0.000317**. Larger gains do not remove the numerical/quantization concern.

Three changed native examples were opened in full: correct adjacent-stage transitions (NOT_STARTED→DONE), correct straight-alpha foreground-over-background compositing including zero alpha (PARTIAL→DONE), and an inverted crop-aspect formula (NOT_STARTED→PARTIAL). Inputs remain complete and unchanged; native reasoning is `null`.

Artifacts in `done-partial-top1-20261106T033639Z/`: `calibration-{0,1}/`, `reference-fidelity.json`, `fit/`, `binary-protected-fit/`, `binary-margin-fit/`, the paired evaluation directories for all twelve candidates, separately saved `checkpoint/` (rejected aggressive), `conservative-checkpoint/` (selected) and `robust-checkpoint/` (rejected DEV trade-off), their native benchmark outputs, `conservative-native-dev-old.json`, `opened-native-changes.json`, and `final-result.json`. Full native DEV/old calls are in the preceding repair root's `dp-top1-{conservative,robust}-native-0/` and `dp-top1-native-{0,1}/`.

The evaluator's inherited 3090-only setup rejected the first 3080 launch before any forward. It now reuses the repair workstream's shared GPU setup, retaining the same gather implementation, and the authorized 3080 rerun completed all 600 inputs. The failed launch is retained separately, not counted as an evaluation. No GPU admission policy elsewhere or machine resource policy changed.

Existing focused checks: **10 passed, 2 skipped**, plus compilation and actual native/tensor comparisons. No new tests were written; the numerical/capture runner still has no automated model-level regression coverage, and no full-suite pass is claimed. **FP32 only: no quantization, CPU qualification, fresh evaluation, deployment or weight publication.**

## Earlier resumed DONE/PARTIAL work — a small targeted gain

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
