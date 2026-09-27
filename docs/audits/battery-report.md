# Battery — the engagement ladder

**Last updated 2026-09-27 10:36** — newest row `rust-toml-cli_phi4_codex_pon_1790524267`, finished 2026-09-27 10:32.

Each cell is an inferred usefulness percentage 🟢≥88 🟡≥63 🟠≥38 🔴 below; `·` = not judged. `[engagement] level = 0..5`, each rung implying every rung below it. gemma4 is a FROZEN historical inference row recovered into suite/historical_ladder.json; every other model reads live from results.jsonl, and a fresh live judgment supersedes a frozen cell.

### Level 0 — pure proxy — wire translation only — 48%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🟡 85% | 🟢 92% | 🟢 89% | 🟢 100% | 🟢 93% | 🟡 86% | 91% | 2 | 20 |
| bonsai2 | 🔴 0% | 🟢 88% | 🟢 90% | 🔴 0% | 🟢 88% | 🟢 92% | 60% | 26 | 36 |
| qwen3.8_9b_distill | 🟡 72% | 🟡 82% | · | 🔴 8% | 🟠 52% | 🟡 84% | 60% | 6 | 78 |
| ling3-tiny | 🔴 2% | 🔴 6% | 🟠 50% | 🟠 45% | 🔴 4% | 🟡 78% | 31% | 3 | 128 |
| phi4 | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 0 | 2 |

### Level 1 — TOOL_CALL_FIXES — dialect and template repair — 41%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🔴 28% | 🟢 92% | 🔴 34% | 🔴 33% | 🔴 6% | 🟠 51% | 41% | 15 | 130 |

### Level 2 — SIMPLE_TOOLS — cria's tool menu, lowered to shell — 70%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🔴 11% | 🟢 89% | 🟡 81% | 🟡 76% | 🟡 66% | 🟢 100% | 70% | 9 | 71 |

### Level 3 — CONTEXT_FIXES — floor, trims, dedups, compaction reframing — 86%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🟡 85% | 🟢 88% | 🟡 84% | 🟢 96% | 🟡 78% | 🟡 86% | 86% | 6 | 27 |

### Level 4 — DONE_REFUSALS_ENABLED — refusing a completion CLAIM — 92%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🟢 100% | 🟡 73% | 🟢 100% | 🟢 100% | 🟢 93% | 🟡 86% | 92% | 10 | 46 |

### Level 5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner — 59%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🟡 73% | 🟢 89% | 🟢 92% | 🟢 100% | 🟢 91% | 🟢 100% | 91% | 20 | 74 |
| ornith1.5 | 🟢 95% | 🟡 84% | 🟡 85% | 🟡 70% | 🟡 75% | 🟢 95% | 84% | 60 | 126 |
| bonsai2 | 🟡 85% | 🟢 90% | 🟢 95% | 🟡 85% | 🟢 95% | 🟢 90% | 90% | 59 | 163 |
| qwen3.8_9b_distill | 🟠 45% | · | 🔴 15% | 🔴 10% | 🟠 62% | 🟡 80% | 42% | 30 | 273 |
| ling3-tiny | · | 🔴 10% | 🔴 33% | 🔴 0% | 🔴 28% | 🟡 78% | 30% | 36 | 271 |
| phi4 | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | · | 0% | 33 | 180 |

Retired from the battery (history kept in suite/results/results.jsonl and suite/historical_ladder.json): qwen35, nemotron-elastic, qwen38.

