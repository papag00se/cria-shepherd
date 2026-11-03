# Battery report

Updated: 2026-11-03 07:18 PST

## L0 — Pure proxy — wire translation only — 43%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🔴 8% | 🟡 70% | 🔴 30% | 🔴 0% | 🟠 60% | 🔴 35% | 34% | 2 | 43 | 69.5 |
| k2_horizon_7b | 🔴 0% | 🔴 2% | 🟢 90% | 🟠 50% | 🟡 75% | 🟡 85% | 50% | 8 | 81 | 86.9 |
| qwen3.8_9b_distill | 🟠 55% | 🟡 80% | 🟡 80% | 🟡 75% | 🟡 85% | 🟢 88% | 77% | 6 | 108 | 82.9 |
| ornith1.5_9b | 🔴 35% | 🟡 78% | 🟡 78% | 🟠 42% | 🟢 92% | 🟢 92% | 70% | 15 | 138 | 53.9 |
| ling3.0_tiny | 🔴 22% | 🟡 65% | 🟠 58% | 🟠 50% | 🟡 70% | 🟡 85% | 58% | 14 | 434 | 170.5 |
| nemotron-elastic | 🔴 15% | 🔴 0% | 🔴 0% | 🔴 8% | 🟠 50% | 🟠 55% | 21% | 6 | 209 | 58.9 |
| bonsai2 | 🔴 0% | 🟢 90% | 🔴 0% | 🔴 0% | 🔴 0% | 🟢 88% | 30% | 13 | 207 | 23.6 |
| phi4 | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 0 | 1 | 48.1 |

## L1 — TOOL_CALL_FIXES — dialect and template repair — 36%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🔴 0% | 🔴 5% | 🟠 45% | 🟠 50% | 🟠 45% | 🔴 30% | 29% | 2 | 12 | 34.0 |
| qwen3.8_9b_distill | 🟠 50% | 🟡 75% | · | · | · | · | 62% | 3 | 38 | 71.0 |
| ornith1.5_9b | 🔴 0% | 🔴 3% | 🟡 76% | 🔴 0% | 🟡 85% | 🟢 88% | 42% | 13 | 42 | 49.0 |
| ling3.0_tiny | 🔴 15% | 🟡 70% | 🟠 50% | 🔴 15% | 🟡 72% | 🟡 85% | 51% | 12 | 195 | 106.0 |
| nemotron-elastic | 🔴 0% | 🔴 10% | 🔴 12% | 🔴 3% | 🔴 0% | 🔴 3% | 5% | 7 | 18 | 116.3 |
| bonsai2 | 🔴 0% | 🔴 0% | 🟢 88% | 🔴 0% | 🟢 93% | 🟢 88% | 45% | 14 | 24 | 21.8 |

## L2 — SIMPLE_TOOLS — cria's tool menu, lowered to shell — 40%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🔴 15% | 🟡 75% | 🔴 0% | 🔴 0% | 🔴 25% | 🟠 50% | 28% | 1 | 12 | 47.4 |
| ornith1.5_9b | 🟢 92% | 🟡 65% | 🟡 85% | 🔴 0% | 🟡 85% | 🟢 90% | 70% | 13 | 59 | 42.7 |
| ling3.0_tiny | 🔴 25% | 🟠 45% | 🟡 70% | 🔴 35% | 🟡 75% | 🟡 85% | 56% | 19 | 335 | 112.0 |
| nemotron-elastic | 🔴 5% | 🔴 12% | 🔴 25% | 🔴 0% | 🔴 20% | 🟠 60% | 20% | 5 | 14 | 78.0 |
| bonsai2 | 🟢 88% | 🔴 3% | 🟡 85% | 🔴 0% | 🔴 0% | 🔴 0% | 29% | 14 | 26 | 22.6 |

## L3 — CONTEXT_FIXES — floor, trims, dedups, compaction reframing — 37%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🔴 0% | 🔴 8% | 🔴 0% | 🔴 35% | 🔴 0% | 🔴 25% | 11% | 1 | 6 | 36.9 |
| ornith1.5_9b | 🔴 3% | 🟡 75% | 🟢 88% | 🔴 0% | 🟡 85% | 🟢 88% | 56% | 17 | 80 | 47.4 |
| ling3.0_tiny | 🟠 55% | 🔴 28% | 🟡 65% | · | 🟡 75% | 🟢 88% | 62% | 13 | 194 | 138.2 |
| nemotron-elastic | 🔴 3% | 🔴 0% | 🔴 18% | 🔴 35% | 🔴 0% | 🔴 30% | 14% | 6 | 15 | 80.8 |
| bonsai2 | 🔴 3% | 🔴 0% | 🟢 88% | 🔴 0% | 🟢 92% | 🟢 88% | 45% | 13 | 26 | 22.6 |

## L4 — DONE_REFUSALS_ENABLED — refusing a completion CLAIM — 49%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🟡 65% | 🟡 82% | 🟠 55% | 🔴 8% | 🟡 70% | 🟡 65% | 58% | 24 | 77 | 28.6 |
| ornith1.5_9b | 🔴 2% | 🟡 85% | 🟡 85% | 🔴 33% | 🟡 85% | 🟢 90% | 63% | 17 | 79 | 47.4 |
| ling3.0_tiny | 🔴 12% | 🟠 40% | 🟠 55% | 🔴 30% | 🟡 75% | 🟡 85% | 50% | 22 | 199 | 105.4 |
| nemotron-elastic | 🟠 40% | 🔴 18% | 🔴 28% | 🔴 22% | 🟠 55% | 🟠 60% | 37% | 23 | 62 | 65.8 |
| bonsai2 | 🔴 3% | 🔴 0% | 🟠 62% | 🔴 0% | 🟡 82% | 🟢 88% | 39% | 16 | 34 | 18.1 |

## L5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner — 47%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🟡 85% | 🟢 88% | 🟡 82% | 🟠 62% | 🟡 78% | 🟡 85% | 80% | 18 | 69 | 44.9 |
| k2_horizon_7b | 🟢 95% | 🟠 60% | 🟠 60% | 🔴 35% | 🟡 70% | 🟢 90% | 68% | 43 | 132 | 57.0 |
| qwen3.8_9b_distill | 🟡 70% | 🟡 80% | 🟠 60% | 🟠 40% | 🟠 60% | 🟢 95% | 68% | 34 | 201 | 113.3 |
| ornith1.5_9b | 🔴 0% | 🔴 25% | 🟡 85% | 🔴 4% | 🟡 82% | 🟢 90% | 48% | 18 | 62 | 54.8 |
| ling3.0_tiny | 🔴 20% | 🔴 20% | 🟡 70% | 🔴 6% | 🟡 70% | 🟡 70% | 43% | 18 | 115 | 131.4 |
| nemotron-elastic | 🔴 20% | 🔴 28% | 🟡 72% | 🔴 28% | 🟠 45% | 🔴 20% | 36% | 17 | 82 | 76.7 |
| bonsai2 | 🔴 3% | 🔴 3% | 🔴 0% | 🔴 0% | 🟡 82% | 🟢 88% | 29% | 14 | 26 | 20.4 |
| phi4 | 🔴 5% | 🔴 5% | 🔴 0% | 🔴 4% | 🔴 0% | 🔴 0% | 2% | 37 | 188 | 56.5 |

Legend: 🟢 ≥88% · 🟡 ≥63% · 🟠 ≥38% · 🔴 <38%; blank = pending/unjudged. Usefulness: share of requested work delivered as useful code. Percentages are independently judged usefulness; averages include judged zeros, exclude failed/unjudged attempts, and use known metrics only. Average minutes are wall time (including judge waits); partially filled rows have partial coverage. Avg tok/s is the mean of known per-task all-phase generation rates, not wall-time throughput; `·` = unknown timing. Ruby/Go/Python/Java/Node/Rust are the six task columns.
