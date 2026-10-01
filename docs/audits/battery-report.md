# Battery — the engagement ladder

**Last updated 2026-10-01 00:06** — newest row `cart-billing-go_bonsai2_codex_poff_1790836181`, finished 2026-10-01 00:04.
**Report code revision `13e07673`; inference anchor remains `f79cc6146470281b5909cf605b27afca1177e2d1`.**

Each cell is an inferred usefulness percentage 🟢≥88 🟡≥63 🟠≥38 🔴 below; `·` = not judged. `[engagement] level = 0..5`, each rung implying every rung below it. Model rows use the [official project names](../model-names.md). Gemma4/QAT share the single `gemma4_12b` row: frozen history remains for unreplaced cells and the latest live judgment supersedes its matching cell. Historical model keys, run IDs and executable aliases retain their original provenance.

### Level 0 — pure proxy — wire translation only — 43%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🟡 85% | 🟢 92% | 🟢 89% | 🟢 100% | 🟢 93% | 🟡 86% | 91% | 2 | 20 |
| bonsai2 | 🔴 0% | 🟢 88% | 🟢 90% | 🔴 0% | 🟢 88% | 🟢 92% | 60% | 26 | 36 |
| k2_horizon_7b | 🔴 0% | 🟡 85% | 🟢 90% | 🔴 30% | 🟢 92% | 🟢 95% | 65% | 15 | 63 |
| phi4 | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 0 | 2 |
| ling3.0_tiny | 🔴 2% | 🔴 6% | 🟠 50% | 🟠 45% | 🔴 4% | 🟡 78% | 31% | 3 | 128 |
| qwen3.8_9b_distill | 🟡 72% | 🟡 82% | 🔴 22% | 🔴 8% | 🟠 52% | 🟡 84% | 53% | 9 | 108 |
| nemotron-elastic | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 3 | 6 |

### Level 1 — TOOL_CALL_FIXES — dialect and template repair — 21%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🔴 28% | 🟢 92% | 🔴 34% | 🔴 33% | 🔴 6% | 🟠 51% | 41% | 15 | 130 |
| nemotron-elastic | 🔴 0% | 🔴 6% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 1% | 2 | 5 |

### Level 2 — SIMPLE_TOOLS — cria's tool menu, lowered to shell — 41%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🔴 11% | 🟢 89% | 🟡 81% | 🟡 76% | 🟡 66% | 🟢 100% | 70% | 9 | 71 |
| nemotron-elastic | 🔴 0% | 🔴 6% | 🟠 45% | 🔴 0% | 🔴 0% | 🔴 18% | 12% | 4 | 8 |

### Level 3 — CONTEXT_FIXES — floor, trims, dedups, compaction reframing — 50%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🟡 85% | 🟢 88% | 🟡 84% | 🟢 96% | 🟡 78% | 🟡 86% | 86% | 6 | 27 |
| nemotron-elastic | 🔴 0% | 🔴 0% | 🟠 50% | 🔴 12% | 🔴 0% | 🔴 15% | 13% | 4 | 7 |

### Level 4 — DONE_REFUSALS_ENABLED — refusing a completion CLAIM — 60%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🟢 100% | 🟡 73% | 🟢 100% | 🟢 100% | 🟢 93% | 🟡 86% | 92% | 10 | 46 |
| nemotron-elastic | 🔴 26% | 🔴 28% | 🟠 40% | 🔴 19% | 🟠 40% | 🔴 20% | 29% | 33 | 141 |

### Level 5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner — 46%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🟠 49% | 🟡 74% | 🟡 78% | 🟠 55% | 🟠 62% | 🟢 91% | 68% | 43 | 106 |
| bonsai2 | 🔴 18% | 🔴 0% | 🟢 95% | 🟡 85% | 🟢 95% | 🟢 90% | 64% | 45 | 106 |
| ornith1.5_9b | 🟢 95% | 🟡 84% | 🟡 85% | 🟡 70% | 🟡 75% | 🟢 95% | 84% | 60 | 126 |
| k2_horizon_7b | 🔴 10% | 🟡 80% | 🔴 33% | 🔴 2% | 🟡 78% | 🔴 18% | 37% | 38 | 116 |
| phi4 | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 33 | 180 |
| ling3.0_tiny | 🔴 3% | 🔴 10% | 🔴 33% | 🔴 0% | 🔴 28% | 🟡 78% | 25% | 35 | 261 |
| qwen3.8_9b_distill | 🟠 45% | 🟠 62% | 🔴 15% | 🔴 10% | 🟠 62% | 🟡 80% | 46% | 32 | 288 |

Retired from the battery (history kept in suite/results/results.jsonl and suite/historical_ladder.json): qwen35, qwen38.

