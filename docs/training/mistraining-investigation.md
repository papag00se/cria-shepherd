# Closed mechanical investigation of the rejected 68M experiment

The operator rejected `jhu-clsp/ettin-encoder-68m` as the next candidate on size/capacity grounds. No further matrix or deployment is authorized by this investigation. The results below distinguish a working learning path from useful judgments across tasks; they do not reverse that rejection.

## What actually ran

Private evidence root: `/home/jesse/.cria/training/decision-qualified-v1/mistraining-diagnosis/`.

- Native gradient, optimizer membership, head-routing and forced-head decoding checks on the pinned original encoder.
- Eight previously admitted real TRAIN examples: both labels of both heads across two TRAIN tasks. These are provisional reviewed targets, not human gold.
- Two declared tiny-subset budgets, five and 200 updates, with no best-checkpoint selection. Both use the original optimizer settings, full native inputs, task/family loss weighting, precision and scheduler formula. The subset makes every example's loss weight exactly one. This is an optimization sanity test, not semantic validation.
- A separate inference-only replay of all 514 real TRAIN examples through the original primary final FP32 reference, with BF16 autocast. No DEV, archive diagnostic EVAL or fresh evaluation was scored.

The native probes finished successfully. No worker remains running for them. All original quarantines and source holds remain unchanged.

## Verified facts

The optimizer owns every trainable tensor exactly once. In single-head backward probes, all 116 encoder parameter tensors and both active-head tensors receive finite, nonzero gradients; the inactive head receives no gradients. Forced output biases verify both class IDs through the actual head routing and shared report decoder. Every selected source label ID agrees with the authoritative label order.

The first update intentionally has zero learning rate under the frozen warmup convention and changes no weights. The next update has nonzero learning rates and changes tensors in the encoder and both heads. Comparison of the original final FP32 reference with the correctly seeded initial model also finds changes in all 116 encoder tensors and both tensors of each head. This does not mean every scalar, including unused vocabulary rows, changed.

At five updates the short-budget tiny run matches six of eight reviewed targets: both PLAN examples are missed. In the separately declared 200-update schedule, all eight match at the sampled update 20 and remain matched at sampled updates 50, 100 and 200. Update 20 is the first successful *observed checkpoint*, not a claim about the exact convergence update. The final checkpoint is the qualifying result.

The original final weights are not simply constant majority predictors on their own training data:

- RETROSPECTIVE: 283/310 matched; PLAN: 92/140 matched.
- DESCRIBES: 17/18 matched; DICTATES: 46/46 matched.

These are training-target agreement counts, not held-out accuracy. The severe previously recorded whole-task exclusion results therefore cannot be explained by a wholly frozen encoder, disconnected heads, swapped label IDs, or an optimizer that never updates. Retrospective fitting is still incomplete; the dictation head has a large training-versus-excluded-task gap. The investigation does not establish one causal explanation for those quality problems.

## Weighting

The implementation matches the frozen task/family objective. It is not class balancing. In the original final real-only fit, PLAN contributes 63.38358 of the retrospective head's 257 total loss-weight units, about 24.66%, versus 140/450 raw examples. In the Java-excluded fit, PLAN contributes 12.51393 of 63 units, about 19.86%. DESCRIBES contributes about 27.41% of final dictation weight. Neither minority class disappears from the objective. These facts expose objective/support skew; they do not prove that changing class weights would repair excluded-task judgments.

## Supported pipeline changes

`training_run.training_step` is now the single accumulated-update implementation used by both fitting and the native integrity probes. Tests compare its weighted loss and parameter updates with an independently assembled full-batch calculation, including short batches. Training events now record the learning rates actually used by the update, rather than only the next scheduler values.

The missing pre-matrix learning check was a process defect. A new matrix launch requires `--integrity-receipt`. Qualification binds actual native results and their contract to the recipe and optimization-function fingerprint. Missing, stale, changed, failed-overfit or failed-update evidence is rejected. This is a mechanical preflight, **not quality, freshness, deployment permission, or certification of a different backbone**. The existing receipt was qualified while the executed trainer source still exactly matched its native capture; subsequent launch-gate-only changes leave the bound optimization functions unchanged.

Fail-before/pass-after checks cover launching without preflight and accepting a failed parameter-update flag. The settled investigation suite passed **11,003 tests, 224 skipped**; the isolated Torch checks passed **21 tests**. Source digests are retained with the local test receipt. A prior test run whose source changed during execution is superseded, not represented as the settled pass.

No label, original frozen recipe, class weight, seed selection, production configuration or deployed weight was changed to improve these numbers. Larger candidates require a separate, explicitly frozen experiment.
