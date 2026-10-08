# Battery report

## L0 — 42%

| model | ruby | go | python | java | node | rust | avg usefulness | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🔴 0% | 🟡 80% | 🔴 2% | 🔴 3% | 🔴 35% | 🟢 95% | 36% | 1 | 24 |
| ornith1.5_9b | 🟢 90% | 🟡 75% | 🟢 90% | 🔴 30% | 🟡 75% | 🟢 100% | 77% | 37 | 130 |
| bonsai2 | 🔴 0% | 🔴 0% | 🟢 90% | 🔴 0% | 🟢 95% | 🟠 55% | 40% | 37 | 510 |
| nemotron-elastic | 🔴 30% | 🔴 0% | 🔴 0% | 🔴 0% | 🟠 55% | 🔴 0% | 14% | 5 | 141 |
| ling3.0_tiny | 🔴 0% | 🔴 0% | 🟡 65% | 🟠 50% | 🟠 60% | 🟡 80% | 42% | 2 | 47 |
| phi4 | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 0 | 1 |
| k2_horizon_7b | 🔴 0% | 🔴 2% | 🟢 90% | 🟠 50% | 🟡 75% | 🟡 85% | 50% | 8 | 81 |
| qwen3.8_9b_distill | 🟡 75% | 🟡 80% | 🟠 50% | 🟡 75% | 🟡 70% | 🟢 95% | 74% | 13 | 248 |

## L1 — 21%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🔴 28% | 🟢 92% | 🔴 34% | 🔴 33% | 🔴 6% | 🟠 51% | 41% | 15 | 130 |
| nemotron-elastic | 🔴 0% | 🔴 6% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 1% | 2 | 5 |

## L2 — 41%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🔴 11% | 🟢 89% | 🟡 81% | 🟡 76% | 🟡 66% | 🟢 100% | 70% | 9 | 71 |
| nemotron-elastic | 🔴 0% | 🔴 6% | 🟠 45% | 🔴 0% | 🔴 0% | 🔴 18% | 12% | 4 | 8 |

## L3 — 50%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🟡 85% | 🟢 88% | 🟡 84% | 🟢 96% | 🟡 78% | 🟡 86% | 86% | 6 | 27 |
| nemotron-elastic | 🔴 0% | 🔴 0% | 🟠 50% | 🔴 12% | 🔴 0% | 🔴 15% | 13% | 4 | 7 |

## L4 — 60%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🟢 100% | 🟡 73% | 🟢 100% | 🟢 100% | 🟢 93% | 🟡 86% | 92% | 10 | 46 |
| nemotron-elastic | 🔴 26% | 🔴 28% | 🟠 40% | 🔴 19% | 🟠 40% | 🔴 20% | 29% | 33 | 141 |

## L5 — 42%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🟠 49% | 🟡 74% | 🟡 78% | 🟠 55% | 🟠 62% | 🟢 91% | 68% | 43 | 106 |
| bonsai2 | 🔴 18% | 🔴 0% | 🟡 87% | 🔴 5% | 🟠 59% | 🔴 3% | 29% | 41 | 58 |
| qwen3.8_9b_distill | 🟡 68% | 🟠 52% | 🔴 15% | 🔴 10% | 🟠 62% | 🟡 80% | 48% | 38 | 239 |
| ornith1.5_9b | 🟢 95% | 🟡 84% | 🟡 85% | 🟡 70% | 🟡 75% | 🟢 95% | 84% | 60 | 126 |
| k2_horizon_7b | 🔴 10% | 🟡 80% | 🔴 33% | 🔴 2% | 🟡 78% | 🔴 18% | 37% | 38 | 116 |
| phi4 | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 33 | 180 |
| ling3.0_tiny | 🔴 3% | 🔴 10% | 🔴 33% | 🔴 0% | 🔴 28% | 🟡 78% | 25% | 35 | 261 |

Legend: 🟢 ≥88% · 🟡 ≥63% · 🟠 ≥38% · 🔴 <38%; blank = pending/unjudged. Percentages are independently judged usefulness; averages include judged zeros, exclude failed/unjudged attempts, and use known metrics only. Average minutes are wall time (including judge waits); partially filled rows have partial coverage. Ruby/Go/Python/Java/Node/Rust are the six task columns.
