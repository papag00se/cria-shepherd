# Battery — the engagement ladder

**Last updated 2026-09-24 05:01** — newest row `shipping-rates-rb_nemotron-elastic_codex_pon_1790246809`, finished 2026-09-24 05:00.

Each cell is an inferred usefulness percentage 🟢≥88 🟡≥63 🟠≥38 🔴 below; `·` = not judged. `[engagement] level = 0..5`, each rung implying every rung below it. gemma4 / qwen35 / nemotron-elastic are FROZEN historical inference rows recovered into suite/historical_ladder.json; every other model reads live from results.jsonl, and a fresh live judgment supersedes a frozen cell.

### Level 0 — pure proxy — wire translation only — 50%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🟡 85% | 🟢 92% | 🟢 89% | 🟢 100% | 🟢 93% | 🟡 86% | 91% | 2 | 20 |
| qwen35 | 🔴 0% | 🔴 21% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 4% | 1 | 8 |
| nemotron-elastic | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 3 | 6 |
| qwen38 | 🟢 90% | 🟢 100% | 🟢 100% | 🟢 98% | 🟢 98% | 🟢 100% | 98% | 14 | · |
| ternary-bonsai-2 | 🔴 0% | 🟢 88% | 🟢 90% | 🔴 0% | 🟢 88% | 🟢 92% | 60% | 26 | 36 |

### Level 1 — TOOL_CALL_FIXES — dialect and template repair — 52%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🔴 28% | 🟢 92% | 🔴 34% | 🔴 33% | 🔴 6% | 🟠 51% | 41% | 15 | 130 |
| qwen35 | 🟠 55% | 🟢 92% | 🟡 83% | 🟠 62% | 🔴 0% | 🟢 100% | 65% | 14 | 73 |
| nemotron-elastic | 🔴 0% | 🔴 6% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 1% | 2 | 5 |
| qwen38 | 🟢 100% | 🟢 100% | 🟢 100% | 🟢 98% | 🟢 98% | 🟢 100% | 99% | 8 | · |

### Level 2 — SIMPLE_TOOLS — cria's tool menu, lowered to shell — 67%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🔴 11% | 🟢 89% | 🟡 81% | 🟡 76% | 🟡 66% | 🟢 100% | 70% | 9 | 71 |
| qwen35 | 🟡 76% | 🟢 89% | 🟢 88% | 🟢 100% | 🟡 63% | 🟢 100% | 86% | 6 | 50 |
| nemotron-elastic | 🔴 0% | 🔴 6% | 🟠 45% | 🔴 0% | 🔴 0% | 🔴 18% | 12% | 4 | 8 |
| qwen38 | 🟢 100% | 🟢 100% | 🟢 100% | 🟢 98% | 🟢 98% | 🟢 100% | 99% | 12 | · |

### Level 3 — CONTEXT_FIXES — floor, trims, dedups, compaction reframing — 69%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🟡 85% | 🟢 88% | 🟡 84% | 🟢 96% | 🟡 78% | 🟡 86% | 86% | 6 | 27 |
| qwen35 | 🟢 93% | 🟢 100% | 🟡 83% | 🟡 80% | 🟠 58% | 🟡 74% | 81% | 9 | 54 |
| nemotron-elastic | 🔴 0% | 🔴 0% | 🟠 50% | 🔴 12% | 🔴 0% | 🔴 15% | 13% | 4 | 7 |
| qwen38 | 🟢 100% | 🟢 100% | 🟢 100% | 🟡 78% | 🟢 98% | 🟢 100% | 96% | 13 | · |

### Level 4 — DONE_REFUSALS_ENABLED — refusing a completion CLAIM — 75%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🟢 100% | 🟡 73% | 🟢 100% | 🟢 100% | 🟢 93% | 🟡 86% | 92% | 10 | 46 |
| qwen35 | 🟡 86% | 🟠 45% | 🟡 79% | 🟢 100% | 🟡 83% | 🟢 100% | 82% | 17 | 140 |
| nemotron-elastic | 🔴 26% | 🔴 28% | 🟠 40% | 🔴 19% | 🟠 40% | 🔴 20% | 29% | 33 | 141 |
| qwen38 | 🟢 100% | 🟢 100% | 🟢 100% | 🟡 85% | 🟢 98% | 🟢 100% | 97% | 29 | · |

### Level 5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner — 82%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🟡 73% | 🟢 89% | 🟢 92% | 🟢 100% | 🟢 91% | 🟢 100% | 91% | 20 | 74 |
| qwen35 | 🟢 100% | 🟡 63% | 🟡 71% | 🟢 96% | 🟢 93% | 🟢 100% | 87% | 40 | 227 |
| nemotron-elastic | 🔴 30% | 🔴 31% | 🟡 76% | 🔴 20% | 🟡 70% | 🔴 20% | 41% | 40 | 375 |
| ornith15 | 🟢 95% | 🟡 84% | 🟡 85% | 🟡 70% | 🟡 75% | 🟢 95% | 84% | 60 | 126 |
| qwen38 | 🟢 100% | 🟢 100% | 🟢 100% | 🟡 85% | 🟢 98% | 🟢 100% | 97% | 24 | · |
| ternary-bonsai-2 | 🟡 85% | 🟢 90% | 🟢 95% | 🟡 85% | 🟢 95% | 🟢 90% | 90% | 59 | 163 |

