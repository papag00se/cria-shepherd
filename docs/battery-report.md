# Battery report

Updated: 2026-11-03 21:43 PST

## L0 — Pure proxy — wire translation only — 44%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| ornith1.5_9b | 🔴 35% | 🟡 78% | 🟡 78% | 🟠 42% | 🟢 92% | 🟢 92% | 70% | 15 | 138 | 53.9 |
| k2_horizon_7b | 🟡 82% | 🟡 85% | 🟡 78% | 🟠 60% | 🔴 0% | 🟡 85% | 65% | 11 | 80 | 19.1 |
| qwen3.8_9b_distill | 🟠 55% | 🟡 80% | 🟡 80% | 🟠 55% | 🟡 85% | 🟢 88% | 74% | 6 | 104 | 75.7 |
| gemma4_12b | 🔴 8% | 🟡 65% | 🔴 30% | 🔴 0% | 🟠 60% | 🔴 35% | 33% | 2 | 43 | 71.0 |
| bonsai2 | 🔴 0% | 🟢 90% | 🔴 0% | 🔴 0% | 🔴 0% | 🟢 88% | 30% | 13 | 207 | 23.6 |
| ling3.0_tiny | 🔴 22% | 🟡 65% | 🟠 58% | 🟠 50% | 🟡 70% | 🟡 85% | 58% | 14 | 434 | 170.5 |
| nemotron-elastic | 🔴 15% | 🔴 0% | 🔴 0% | 🔴 8% | 🟠 50% | 🟠 55% | 21% | 6 | 209 | 58.9 |
| phi4 | 🔴 5% | 🔴 0% | 🔴 0% | 🔴 2% | 🔴 0% | 🔴 20% | 4% | 12 | 106 | 36.0 |

## L1 — TOOL_CALL_FIXES — dialect and template repair — 41%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| ornith1.5_9b | 🔴 0% | 🔴 3% | 🟡 76% | 🔴 0% | 🟡 85% | 🟢 88% | 42% | 13 | 42 | 49.0 |
| k2_horizon_7b | 🟡 78% | 🟡 75% | 🟡 72% | 🟠 52% | 🟡 85% | 🟡 85% | 74% | 14 | 100 | 26.7 |
| qwen3.8_9b_distill | 🟠 50% | 🟡 75% | 🟡 80% | 🟠 52% | 🟡 78% | 🟡 85% | 70% | 12 | 133 | 70.1 |
| gemma4_12b | 🔴 0% | 🔴 5% | 🟠 45% | 🟠 50% | 🟠 45% | 🔴 30% | 29% | 2 | 12 | 34.0 |
| bonsai2 | 🔴 0% | 🔴 0% | 🟢 88% | 🔴 0% | 🟢 93% | 🟢 88% | 45% | 14 | 24 | 21.8 |
| ling3.0_tiny | 🔴 15% | 🟡 70% | 🟠 50% | 🔴 15% | 🟡 72% | 🟡 85% | 51% | 12 | 195 | 106.0 |
| nemotron-elastic | 🔴 0% | 🔴 10% | 🔴 12% | 🔴 3% | 🔴 0% | 🔴 3% | 5% | 7 | 18 | 116.3 |
| phi4 | 🔴 8% | · | 🔴 0% | 🔴 2% | 🔴 0% | 🔴 25% | 7% | 9 | 45 | 18.1 |

## L2 — SIMPLE_TOOLS — cria's tool menu, lowered to shell — 45%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| ornith1.5_9b | 🟢 92% | 🟡 65% | 🟡 85% | 🔴 0% | 🟡 85% | 🟢 90% | 70% | 13 | 59 | 42.7 |
| k2_horizon_7b | 🟡 78% | 🟡 72% | 🟡 72% | 🟠 45% | 🟡 75% | 🟡 85% | 71% | 23 | 118 | 34.2 |
| qwen3.8_9b_distill | 🟠 50% | 🟡 78% | 🟡 75% | 🟡 65% | 🟠 60% | 🟡 85% | 69% | 15 | 178 | 61.1 |
| gemma4_12b | 🔴 15% | 🟡 75% | 🔴 0% | 🔴 0% | 🔴 25% | 🟠 50% | 28% | 1 | 12 | 47.4 |
| bonsai2 | 🟢 88% | 🔴 3% | 🟡 85% | 🔴 0% | 🔴 0% | 🔴 0% | 29% | 14 | 26 | 22.6 |
| ling3.0_tiny | 🔴 25% | 🟠 45% | 🟡 70% | 🔴 35% | 🟡 75% | 🟡 85% | 56% | 19 | 335 | 112.0 |
| nemotron-elastic | 🔴 5% | 🔴 12% | 🔴 25% | 🔴 0% | 🔴 20% | 🟠 60% | 20% | 5 | 14 | 78.0 |
| phi4 | 🔴 6% | 🔴 6% | · | 🔴 0% | 🔴 18% | 🟠 45% | 15% | 10 | 49 | 18.5 |

## L3 — CONTEXT_FIXES — floor, trims, dedups, compaction reframing — 42%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| ornith1.5_9b | 🔴 5% | 🟡 82% | 🟡 78% | 🔴 0% | 🟡 85% | 🟢 88% | 56% | 15 | 71 | 45.3 |
| gemma4_12b | 🔴 20% | 🟡 72% | 🟠 62% | 🟠 52% | 🟡 68% | 🟡 70% | 57% | 8 | 41 | 27.8 |
| bonsai2 | 🔴 3% | 🔴 3% | 🟡 75% | 🔴 0% | 🟠 55% | 🟡 85% | 37% | 15 | 42 | 31.8 |
| ling3.0_tiny | 🟠 55% | 🔴 28% | 🟡 65% | 🟠 38% | 🟡 75% | 🟢 88% | 58% | 13 | 174 | 156.6 |
| nemotron-elastic | 🔴 3% | 🔴 25% | 🔴 0% | 🔴 35% | 🔴 0% | 🔴 30% | 16% | 6 | 16 | 84.8 |
| phi4 | · | 🔴 5% | 🔴 0% | · | · | · | 2% | 11 | 26 | · |

## L4 — DONE_REFUSALS_ENABLED — refusing a completion CLAIM — 55%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| ornith1.5_9b | 🟢 88% | 🟡 82% | 🟠 55% | 🔴 0% | 🟡 85% | 🟢 88% | 66% | 21 | 92 | 46.2 |
| gemma4_12b | 🟠 40% | 🟡 82% | 🟡 72% | 🟠 60% | 🟡 68% | 🟡 85% | 68% | 24 | 77 | 25.2 |
| bonsai2 | 🟢 88% | 🔴 3% | 🟡 78% | 🔴 0% | 🟡 80% | 🟡 87% | 56% | 21 | 41 | 34.4 |
| ling3.0_tiny | 🔴 12% | 🟠 40% | 🟠 55% | 🔴 30% | 🟡 75% | 🟡 85% | 50% | 22 | 199 | 105.4 |
| nemotron-elastic | 🟠 40% | 🔴 18% | 🔴 28% | 🔴 22% | 🟠 55% | 🟠 60% | 37% | 23 | 62 | 65.8 |

## L5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner — 50%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| ornith1.5_9b | 🟡 75% | 🟠 60% | 🟡 80% | 🟠 45% | 🟡 82% | 🟢 88% | 72% | 21 | 74 | 55.1 |
| k2_horizon_7b | 🟢 95% | 🟠 60% | 🟠 60% | 🔴 35% | 🟡 70% | 🟢 90% | 68% | 43 | 132 | 57.0 |
| qwen3.8_9b_distill | 🟡 70% | 🟡 80% | 🟠 60% | 🟠 40% | 🟠 60% | 🟢 95% | 68% | 34 | 201 | 113.3 |
| gemma4_12b | 🔴 22% | 🟡 85% | 🟡 78% | 🟠 62% | 🟡 70% | 🟡 85% | 67% | 18 | 45 | 25.6 |
| bonsai2 | 🔴 4% | 🔴 3% | 🟡 78% | 🔴 4% | 🟡 80% | 🟡 87% | 43% | 18 | 36 | 26.8 |
| ling3.0_tiny | 🔴 20% | 🔴 20% | 🟡 70% | 🔴 6% | 🟡 70% | 🟡 70% | 43% | 18 | 115 | 131.4 |
| nemotron-elastic | 🔴 20% | 🔴 28% | 🟡 72% | 🔴 28% | 🟠 45% | 🔴 20% | 36% | 17 | 82 | 76.7 |
| phi4 | 🔴 5% | 🔴 5% | 🔴 0% | 🔴 4% | 🔴 0% | 🔴 0% | 2% | 37 | 188 | 56.5 |

Legend: 🟢 ≥88% · 🟡 ≥63% · 🟠 ≥38% · 🔴 <38%; blank = pending/unjudged. Usefulness: share of requested work delivered as useful code. Percentages are independently judged usefulness; averages include judged zeros, exclude failed/unjudged attempts, and use known metrics only. Average minutes are wall time (including judge waits); partially filled rows have partial coverage. Avg tok/s is the mean of known per-task all-phase generation rates, not wall-time throughput; `·` = unknown timing. Ruby/Go/Python/Java/Node/Rust are the six task columns.
