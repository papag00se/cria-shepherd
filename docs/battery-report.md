# Battery report

## L0 — Pure proxy — wire translation only — 42%
| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🔴 0% | 🟡 80% | 🔴 2% | 🔴 3% | 🔴 35% | 🟢 95% | 36% | 1 | 24 | 143.5 |
| bonsai2 | 🔴 0% | 🔴 0% | 🟢 90% | 🔴 0% | 🟢 95% | 🟠 55% | 40% | 37 | 510 | 77.5 |
| ornith1.5_9b | 🟢 90% | 🟡 75% | 🟢 90% | 🔴 30% | 🟡 75% | 🟢 100% | 77% | 37 | 130 | 118.1 |
| ling3.0_tiny | 🔴 0% | 🔴 0% | 🟡 65% | 🟠 50% | 🟠 60% | 🟡 80% | 42% | 2 | 47 | 609.7 |
| k2_horizon_7b | 🔴 0% | 🔴 2% | 🟢 90% | 🟠 50% | 🟡 75% | 🟡 85% | 50% | 8 | 81 | 86.9 |
| qwen3.8_9b_distill | 🟡 75% | 🟡 80% | 🟠 50% | 🟡 75% | 🟡 70% | 🟢 95% | 74% | 13 | 248 | 118.2 |
| nemotron-elastic | 🔴 30% | 🔴 0% | 🔴 0% | 🔴 0% | 🟠 55% | 🔴 0% | 14% | 5 | 141 | 169.8 |
| phi4 | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 0 | 1 | 48.1 |
## L1 — TOOL_CALL_FIXES — dialect and template repair — 21%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🔴 28% | 🟢 92% | 🔴 34% | 🔴 33% | 🔴 6% | 🟠 51% | 41% | 15 | 130 | · |
| nemotron-elastic | 🔴 0% | 🔴 6% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 1% | 2 | 5 | · |

## L2 — SIMPLE_TOOLS — cria's tool menu, lowered to shell — 41%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🔴 11% | 🟢 89% | 🟡 81% | 🟡 76% | 🟡 66% | 🟢 100% | 70% | 9 | 71 | · |
| nemotron-elastic | 🔴 0% | 🔴 6% | 🟠 45% | 🔴 0% | 🔴 0% | 🔴 18% | 12% | 4 | 8 | · |

## L3 — CONTEXT_FIXES — floor, trims, dedups, compaction reframing — 50%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🟡 85% | 🟢 88% | 🟡 84% | 🟢 96% | 🟡 78% | 🟡 86% | 86% | 6 | 27 | · |
| nemotron-elastic | 🔴 0% | 🔴 0% | 🟠 50% | 🔴 12% | 🔴 0% | 🔴 15% | 13% | 4 | 7 | · |

## L4 — DONE_REFUSALS_ENABLED — refusing a completion CLAIM — 60%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🟢 100% | 🟡 73% | 🟢 100% | 🟢 100% | 🟢 93% | 🟡 86% | 92% | 10 | 46 | · |
| nemotron-elastic | 🔴 26% | 🔴 28% | 🟠 40% | 🔴 19% | 🟠 40% | 🔴 20% | 29% | 33 | 141 | · |

## L5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner — 54%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🟢 95% | 🟡 85% | 🟡 85% | 🟡 85% | 🟡 75% | 🟢 95% | 87% | 56 | 187 | 71.9 |
| bonsai2 | 🟡 80% | 🟢 95% | 🟡 85% | 🔴 0% | 🟡 80% | 🟢 100% | 73% | 47 | 69 | 60.0 |
| ornith1.5_9b | 🔴 20% | 🟢 90% | 🟡 85% | 🔴 30% | 🟡 85% | 🟢 100% | 68% | 41 | 117 | 105.5 |
| ling3.0_tiny | 🔴 20% | 🟠 55% | 🟡 65% | 🔴 25% | 🟠 60% | 🟢 100% | 54% | 41 | 259 | 205.3 |
| k2_horizon_7b | 🟢 95% | 🟠 60% | 🟠 60% | 🔴 2% | 🟡 78% | 🔴 18% | 52% | 43 | 130 | 59.8 |
| qwen3.8_9b_distill | 🟡 68% | 🟠 52% | 🔴 15% | 🔴 10% | 🟠 62% | 🟡 80% | 48% | 38 | 239 | 134.0 |
| nemotron-elastic | 🔴 30% | 🔴 25% | 🟡 80% | 🔴 35% | 🟡 65% | 🔴 35% | 45% | 43 | 121 | 151.1 |
| phi4 | 🔴 5% | 🔴 5% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 2% | 38 | 207 | 56.2 |

Legend: 🟢 ≥88% · 🟡 ≥63% · 🟠 ≥38% · 🔴 <38%; blank = pending/unjudged. Usefulness: share of requested work delivered as useful code. Percentages are independently judged usefulness; averages include judged zeros, exclude failed/unjudged attempts, and use known metrics only. Average minutes are wall time (including judge waits); partially filled rows have partial coverage. Avg tok/s is the mean of known per-task all-phase generation rates, not wall-time throughput; `·` = unknown timing. Ruby/Go/Python/Java/Node/Rust are the six task columns.
