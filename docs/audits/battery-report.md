# Battery — the engagement ladder

**Last updated 2026-08-24 21:34** — newest row `orders-api-py_qwen35_codex_poff_1787631060`, scored 2026-08-24 21:28.

Tables only. Findings, walks and the retired two-arm campaign: [`battery-history.md`](battery-history.md).
Per-cell judging: [`ladder-progress.md`](ladder-progress.md). Status: `python3 suite/engagement_status.py`.

`[engagement] level = 0..5`, each rung implying every rung below it. `·` = not run. Superseded cells are excluded and re-run.

### Level 0 — pure proxy — wire translation only

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟢 gemma4 | 85% | 92% | 89% | 100% | 93% | 86% | 91% | 2 | 20 |
| 🔴 qwen35 | · | 21% | 0% | 0% | 0% | 0% | 4% | 1 | 10 |
| ternary-bonsai | · | · | · | · | · | · | · | — | — |
| nemotron-elastic | · | · | · | · | · | · | · | — | — |

### Level 1 — TOOL_CALL_FIXES — dialect and template repair

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟠 gemma4 | 28% | 92% | 34% | 33% | 6% | 51% | 41% | 15 | 130 |
| 🟡 qwen35 | 55% | 92% | 83% | · | · | · | 77% | 11 | 78 |
| ternary-bonsai | · | · | · | · | · | · | · | — | — |
| nemotron-elastic | · | · | · | · | · | · | · | — | — |

### Level 2 — SIMPLE_TOOLS — cria's tool menu, lowered to shell

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟡 gemma4 | 11% | 89% | 81% | 76% | 66% | 100% | 70% | 9 | 71 |
| qwen35 | · | · | · | · | · | · | · | — | — |
| ternary-bonsai | · | · | · | · | · | · | · | — | — |
| nemotron-elastic | · | · | · | · | · | · | · | — | — |

### Level 3 — CONTEXT_FIXES — floor, trims, dedups, compaction reframing

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟡 gemma4 | 85% | 88% | 84% | 96% | 78% | 86% | 86% | 6 | 27 |
| qwen35 | · | · | · | · | · | · | · | — | — |
| ternary-bonsai | · | · | · | · | · | · | · | — | — |
| nemotron-elastic | · | · | · | · | · | · | · | — | — |

### Level 4 — DONE_REFUSALS_ENABLED — refusing a completion CLAIM

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟡 gemma4 | · | 73% | · | · | · | 86% | 80% | 5 | 27 |
| qwen35 | · | · | · | · | · | · | · | — | — |
| ternary-bonsai | · | · | · | · | · | · | · | — | — |
| nemotron-elastic | · | · | · | · | · | · | · | — | — |

### Level 5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟡 gemma4 | 73% | 89% | 92% | 100% | 91% | 51% | 83% | 24 | 86 |
| qwen35 | · | · | · | · | · | · | · | — | — |
| ternary-bonsai | · | · | · | · | · | · | · | — | — |
| nemotron-elastic | · | · | · | · | · | · | · | — | — |


`ˢ` = still scored strictly (all-or-nothing per deliverable); unmarked = judged. 