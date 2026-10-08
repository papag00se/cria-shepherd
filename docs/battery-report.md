# Battery report

## L0 — Pure proxy — wire translation only — 42%

| model | ruby | go | python | java | node | rust | avg usefulness | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| ornith1.5_9b | 🟢 90% | 🟡 75% | 🟢 90% | 🔴 30% | 🟡 75% | 🟢 100% | 77% | 37 | 130 | 118.1 |
| gemma4_12b | 🔴 0% | 🟡 80% | 🔴 2% | 🔴 3% | 🔴 35% | 🟢 95% | 36% | 1 | 24 | 143.5 |
| qwen3.8_9b_distill | 🟡 75% | 🟡 80% | 🟠 50% | 🟡 75% | 🟡 70% | 🟢 95% | 74% | 13 | 248 | 118.2 |
| k2_horizon_7b | 🔴 0% | 🔴 2% | 🟢 90% | 🟠 50% | 🟡 75% | 🟡 85% | 50% | 8 | 81 | 86.9 |
| bonsai2 | 🔴 0% | 🔴 0% | 🟢 90% | 🔴 0% | 🟢 95% | 🟠 55% | 40% | 37 | 510 | 77.5 |
| ling3.0_tiny | 🔴 0% | 🔴 0% | 🟡 65% | 🟠 50% | 🟠 60% | 🟡 80% | 42% | 2 | 47 | 609.7 |
| phi4 | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 0 | 1 | 48.1 |
| nemotron-elastic | 🔴 30% | 🔴 0% | 🔴 0% | 🔴 0% | 🟠 55% | 🔴 0% | 14% | 5 | 141 | 169.8 |

## L1 — TOOL_CALL_FIXES — dialect and template repair — 21%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🔴 28% | 🟢 92% | 🔴 34% | 🔴 33% | 🔴 6% | 🟠 51% | 41% | 15 | 130 | · |
| nemotron-elastic | 🔴 0% | 🔴 6% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 1% | 2 | 5 | · |

## L2 — SIMPLE_TOOLS — cria's tool menu, lowered to shell — 41%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🔴 11% | 🟢 89% | 🟡 81% | 🟡 76% | 🟡 66% | 🟢 100% | 70% | 9 | 71 | · |
| nemotron-elastic | 🔴 0% | 🔴 6% | 🟠 45% | 🔴 0% | 🔴 0% | 🔴 18% | 12% | 4 | 8 | · |

## L3 — CONTEXT_FIXES — floor, trims, dedups, compaction reframing — 50%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🟡 85% | 🟢 88% | 🟡 84% | 🟢 96% | 🟡 78% | 🟡 86% | 86% | 6 | 27 | · |
| nemotron-elastic | 🔴 0% | 🔴 0% | 🟠 50% | 🔴 12% | 🔴 0% | 🔴 15% | 13% | 4 | 7 | · |

## L4 — DONE_REFUSALS_ENABLED — refusing a completion CLAIM — 60%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🟢 100% | 🟡 73% | 🟢 100% | 🟢 100% | 🟢 93% | 🟡 86% | 92% | 10 | 46 | · |
| nemotron-elastic | 🔴 26% | 🔴 28% | 🟠 40% | 🔴 19% | 🟠 40% | 🔴 20% | 29% | 33 | 141 | · |

## L5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner — 43%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| ornith1.5_9b | 🟢 95% | 🟡 84% | 🟡 85% | 🟡 70% | 🟡 75% | 🟢 95% | 84% | 60 | 126 | 72.0 |
| gemma4_12b | 🟢 95% | 🟡 85% | 🟡 78% | 🟠 55% | 🟠 62% | 🟢 91% | 78% | 49 | 131 | 66.1 |
| qwen3.8_9b_distill | 🟡 68% | 🟠 52% | 🔴 15% | 🔴 10% | 🟠 62% | 🟡 80% | 48% | 38 | 239 | 134.0 |
| k2_horizon_7b | 🔴 10% | 🟡 80% | 🔴 33% | 🔴 2% | 🟡 78% | 🔴 18% | 37% | 38 | 116 | 61.9 |
| bonsai2 | 🔴 18% | 🔴 0% | 🟡 87% | 🔴 5% | 🟠 59% | 🔴 3% | 29% | 41 | 58 | 69.3 |
| ling3.0_tiny | 🔴 3% | 🔴 10% | 🔴 33% | 🔴 0% | 🔴 28% | 🟡 78% | 25% | 35 | 261 | 217.6 |
| phi4 | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 33 | 180 | 71.8 |

Legend: 🟢 ≥88% · 🟡 ≥63% · 🟠 ≥38% · 🔴 <38%; blank = pending/unjudged. Percentages are independently judged usefulness; averages include judged zeros, exclude failed/unjudged attempts, and use known metrics only. Average minutes are wall time (including judge waits); partially filled rows have partial coverage. Avg tok/s is the mean of known per-task all-phase generation rates, not wall-time throughput; `·` = unknown timing. Ruby/Go/Python/Java/Node/Rust are the six task columns.
