# First GPU experiment: completed, not admitted

The authorized provisional experiment and its fully traced reproduction have completed on the RTX 3090. **Cria has not yet produced dependable replacement judgments.** The task-excluded checks expose consequential errors; neither aggregate agreement nor fitting calibration temperatures makes these guards ready to use.

## Execution and artifacts

- Pinned `jhu-clsp/ettin-encoder-68m`, revision `ac19ae4bc51093b31c475665ac872a936d056cc2`; complete native inputs, unchanged frozen examples and hyperparameters.
- Initial 24-fit matrix retained as unreleased evidence. The corrected, audited 24-fit reproduction matched all **18 OOF-logit files** and **six final serving-weight files** exactly. Initial/per-epoch RNG snapshots and actual batch/order receipts are present for the audited execution. This does not invent snapshots for the initial execution or claim its unretained FP32 states were compared.
- Six final comparison artifacts, each one shared encoder plus both heads, **136,309,856 bytes**. They are alternatives, not an ensemble. The prespecified candidate remains real-only seed 17; no best-seed selection.
- Its separately retained FP32 reference is **272,599,312 bytes** and is not part of a serving bundle. Proposed serving weights are below 250,000,000 bytes; a complete stdlib-compatible production bundle, operator parity, RSS and latency are **not certified**.
- Audited fitting took **2,372.36 seconds**, including per-fit model loading, OOF prediction and serialization. Provisioning and the initial matrix are additional, not included in that duration.
- Largest recorded training-step reserved-allocator high water: **4,043,309,056 bytes**; host high-water observation: **2,374,488,064 bytes**. These are not certified whole-process/NVML/export/serving peaks. The earlier 1.5 GB observation was specifically a first-step PyTorch allocator reading.
- Sequential output tree: **3,340,330,227 apparent bytes**, within the output-only 6 GiB reservation. Separately measured environments: GPU **7,038,379,699 bytes**, CPU preflight **1,065,139,287 bytes**; environment provisioning is outside that reservation.
- Full tests: **10,998 passed, 220 skipped**. Isolated Torch/offline checks: **53 passed**, including the mechanics that the base environment skips without Torch.

The GPU worker has exited and released the 3090. The prior 3090 model container remains stopped; the separate 3080 inference process was left running. No classifier was deployed; no runtime/campaign/planner configuration was changed.

## What the focused judgments actually did

Below are **real whole-task-excluded TRAIN predictions**, pooled across the three known original tasks. Targets are agreeing provisional assistant reviews, not human gold. This is neither a fresh population benchmark nor final-model DEV/diagnostic scoring. Temperature fitting uses these same OOF predictions and cannot change their argmax decisions.

| Training arm | Seed | Missed PLAN / 140 | Falsely blocked RETROSPECTIVE / 310 | Missed DICTATES / 46 | Falsely blocked DESCRIBES / 18 |
|---|---:|---:|---:|---:|---:|
| Real only | 17 | 132 | 11 | 2 | 15 |
| Real only | 29 | 140 | 4 | 5 | 14 |
| Real only | 43 | 128 | 11 | 3 | 14 |
| Real + 11 reviewed synthetic | 17 | 132 | 21 | 1 | 14 |
| Real + 11 reviewed synthetic | 29 | 139 | 6 | 10 | 11 |
| Real + 11 reviewed synthetic | 43 | 137 | 1 | 6 | 14 |

The prespecified candidate's checks missed **132 of 140 reviewed plans** and incorrectly treated **15 of 18 reviewed descriptions/quotations as dictated implementation**. These are precisely consequential errors for the intended guards, not a success obscured by a strict metric.

A complete native retrospective call was inspected: a briefing included explicit instructions to implement/run performance tests, create threading tests, and write documentation. The reviewed target was PLAN; the native logits favored RETROSPECTIVE. A complete dictation call was also inspected: a quoted real filesystem error was followed by a full Java benchmark and a verbatim creation command; the reviewed DICTATES target and native prediction agreed. Neither classifier generated a reasoning text; no private reasoning was a feature or target.

Label support is strongly task-skewed: Java contributes **123 of the 140 PLAN targets**. The Java-excluded primary fit trains on only **17 PLAN and 74 RETROSPECTIVE examples**. Both labels being present in each fold was not evidence of adequate semantic/scenario coverage. This is an observed coverage warning, not proof of a single causal explanation for all errors. The training objective, task/label coverage and actual learning behavior need investigation before a separately frozen follow-up; do not add keyword rules, train on held ambiguity, or tune thresholds after inspecting these outcomes.

## Remaining boundaries

All 12 prescribed per-head/arm/seed temperature panels, task-macro/pooled reliability, Brier and risk/coverage outputs are retained, with **3,084 full native public input/output call records**. No deployment threshold was selected.

**DEV scoring: 0. Archived diagnostic scoring: 0. Fresh evaluation: 0.** The existing 37 DEV and 93 diagnostic inputs remain unscored by this execution. The 94 real holds, 61 withheld synthetic proposals, missing candidate slots and source holds have not been released or converted into semantic labels. No performance claim on new sessions, human gold, CPU serving parity, or improvement to the running coder follows from these results.

Machine-readable results and exact hashes: [`gpu-result.json`](gpu-result.json). Local native evidence: `~/.cria/training/decision-qualified-v1/execution/{references-001,calibration-audited-v1}/`. Recipe and input hashes remain unchanged. [Execution boundaries and driver corrections](gpu-execution.md) distinguish the initial trace gap from the audited reproduction.
