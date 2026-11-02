# Battery report

Updated: 2026-11-02 15:25 PST

## L0 — Pure proxy — wire translation only — 43%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🟡 85% | 🟢 92% | 🟢 89% | 🟢 100% | 🟢 93% | 🟡 86% | 91% | 2 | 20 | · |
| bonsai2 | 🔴 0% | 🟢 88% | 🟢 90% | 🔴 0% | 🟢 88% | 🟢 92% | 60% | 26 | 36 | 72.1 |
| qwen3.8_9b_distill | 🟡 72% | 🟡 82% | 🔴 22% | 🔴 8% | 🟠 52% | 🟡 84% | 53% | 9 | 108 | 206.4 |
| k2_horizon_7b | 🔴 0% | 🟡 85% | 🟢 90% | 🔴 30% | 🟢 92% | 🟢 95% | 65% | 15 | 63 | 60.0 |
| ling3.0_tiny | 🔴 2% | 🔴 6% | 🟠 50% | 🟠 45% | 🔴 4% | 🟡 78% | 31% | 3 | 128 | 301.1 |
| phi4 | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 0 | 2 | 58.0 |
| nemotron-elastic | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 3 | 6 | · |

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

## L5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner — 53%

| model | ruby | go | python | java | node | rust | avg pct | avg min | avg calls | avg tok/s |
|---|---|---|---|---|---|---|---:|---:|---:|---:|
| gemma4_12b | 🟡 73% | 🟢 89% | 🟢 92% | 🟢 100% | 🟢 91% | 🟢 100% | 91% | 20 | 74 | · |
| bonsai2 | 🟡 85% | 🟢 90% | 🟢 95% | 🟡 85% | 🟢 95% | 🟢 90% | 90% | 59 | 163 | 71.1 |
| ornith1.5_9b | 🟢 95% | 🟡 84% | 🟡 85% | 🟡 70% | 🟡 75% | 🟢 95% | 84% | 60 | 126 | 72.0 |
| qwen3.8_9b_distill | 🟠 45% | 🟠 62% | 🔴 15% | 🔴 10% | 🟠 62% | 🟡 80% | 46% | 32 | 288 | 146.8 |
| k2_horizon_7b | 🔴 10% | 🟡 80% | 🔴 33% | 🔴 2% | 🟡 78% | 🔴 18% | 37% | 38 | 116 | 61.9 |
| ling3.0_tiny | 🔴 3% | 🔴 10% | 🔴 33% | 🔴 0% | 🔴 28% | 🟡 78% | 25% | 35 | 261 | 217.6 |
| phi4 | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 33 | 180 | 71.8 |

Legend: 🟢 ≥88% · 🟡 ≥63% · 🟠 ≥38% · 🔴 <38%; blank = pending/unjudged. Usefulness: share of requested work delivered as useful code. Percentages are independently judged usefulness; averages include judged zeros, exclude failed/unjudged attempts, and use known metrics only. Average minutes are wall time (including judge waits); partially filled rows have partial coverage. Avg tok/s is the mean of known per-task all-phase generation rates, not wall-time throughput; `·` = unknown timing. Ruby/Go/Python/Java/Node/Rust are the six task columns.
