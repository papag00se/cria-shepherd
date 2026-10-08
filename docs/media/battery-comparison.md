# L0 standing / L5 best recorded

**Metric: holistically inferred usefulness, not deterministic task scores or pass rates.**

L0 retains the standing snapshot. L5 selects the highest retained final judgment per model/task, including historical runs and frozen inference summaries. It is not one campaign, expected performance, a new run or a fresh re-audit of every capture.

Phi-4 is temporarily omitted from the displayed roster; its original data is retained. Averages reflect the displayed roster, not a new run. Ornith L0 remains unknown: [retained-history search and unsupported draft row](ornith-l0-search.md).

## L0 — 50% standing overall average (50.0% before rounding)

36 judged cells. Equal weight per observed cell, not per model. Missing cells excluded; observed zeros included.

| Model | ruby | go | python | java | node | rust | Row average |
|---|---:|---:|---:|---:|---:|---:|---:|
| gemma4_12b | 85% | 92% | 89% | 100% | 93% | 86% | 91% |
| bonsai2 | 0% | 88% | 90% | 0% | 88% | 92% | 60% |
| ornith1.5_9b | — | — | — | — | — | — | — |
| k2_horizon_7b | 0% | 85% | 90% | 30% | 92% | 95% | 65% |
| ling3.0_tiny | 2% | 6% | 50% | 45% | 4% | 78% | 31% |
| qwen3.8_9b_distill | 72% | 82% | 22% | 8% | 52% | 84% | 53% |
| nemotron-elastic | 0% | 0% | 0% | 0% | 0% | 0% | 0% |

## L5 — 62% mean of cell maxima (62.3% before rounding)

42 judged cells. Equal weight per observed cell, not per model. Missing cells excluded; observed zeros included.

| Model | ruby | go | python | java | node | rust | Row average |
|---|---:|---:|---:|---:|---:|---:|---:|
| gemma4_12b | 73% | 89% | 92% | 100% | 91% | 100% | 91% |
| bonsai2 | 85% | 90% | 95% | 85% | 95% | 90% | 90% |
| ornith1.5_9b | 95% | 84% | 85% | 70% | 75% | 95% | 84% |
| k2_horizon_7b | 10% | 80% | 33% | 2% | 78% | 18% | 37% |
| ling3.0_tiny | 3% | 10% | 33% | 0% | 28% | 78% | 25% |
| qwen3.8_9b_distill | 68% | 62% | 15% | 10% | 62% | 80% | 50% |
| nemotron-elastic | 59% | 50% | 76% | 20% | 70% | 84% | 60% |

## Reading the comparison

Restricting both grids to the same available model/task **labels** gives 36 cells: L0 standing **50.0%**, L5 selected maxima **58.7%**. These are **not controlled experimental pairs**: only L5 is maximized across history.

Selecting historical maxima is intentionally optimistic and does not establish typical performance or a causal improvement. Investigate missing, mistimed or incorrect cria assists; do not turn low usefulness into a verdict on model weights.

Rosters, run dates, source revisions, model variants and planner settings differ. The historical L5 label included planner experiments; planning is currently off by default. Gemma4/QAT share one official identity: unreplaced cells keep frozen stock-model history. Do not read the resulting row as one unchanged model configuration. Defiant-Fable is merged into qwen3.8_9b_distill per the owner's identity correction; original IDs are preserved.

Some recent full captures are unavailable in the source checkout. Reported values are preserved, not independently re-judged here. A new controlled, planner-off campaign is needed before claiming an assist uplift.

## Sources

Reporting snapshot: **2026-10-04 22:57 PDT**. This is the report's export timestamp, not the date of every underlying run.

L5 best-recorded export: **2026-10-04 22:58 PDT**.

[L5 cell-by-cell sources and retained-history scope](battery-l5-best.json) · [Original standing reporting output](battery-report-snapshot.md) · [Display data and source checksums](battery-data.json) · [Capture/reproduction notes](README.md#battery-snapshot)
