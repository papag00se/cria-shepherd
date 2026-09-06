# Battery — the engagement ladder

**Last updated 2026-09-05 20:04** — newest row `cart-billing-go_nemotron-elastic_codex_poff_1788661992`, finished 2026-09-05 20:04.

Tables only. Status: `python3 suite/engagement_status.py`.

`[engagement] level = 0..5`, each rung implying every rung below it. `·` = not run. Superseded cells are excluded and re-run.

### Level 0 — pure proxy — wire translation only — —

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | ? | ? | ? | ? | ? | ? | — | 2 | 20 |
| qwen35 | ? | ? | ? | ? | ? | ? | — | 1 | 8 |
| ternary-bonsai | ? | ? | ? | ? | ? | ? | — | 25 | 67 |
| nemotron-elastic | ? | ? | ? | ? | ? | ? | — | 3 | 6 |

### Level 1 — TOOL_CALL_FIXES — dialect and template repair — —

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | ? | ? | ? | ? | ? | ? | — | 15 | 130 |
| qwen35 | ? | ? | ? | ? | ? | ? | — | 14 | 73 |
| ternary-bonsai | ? | ? | ? | ? | ? | ? | — | 31 | 53 |
| nemotron-elastic | ? | ? | ? | ? | ? | ? | — | 2 | 5 |

### Level 2 — SIMPLE_TOOLS — cria's tool menu, lowered to shell — —

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | ? | ? | ? | ? | ? | ? | — | 9 | 71 |
| qwen35 | ? | ? | ? | ? | ? | ? | — | 6 | 50 |
| ternary-bonsai | ? | ? | ? | ? | ? | ? | — | 31 | 82 |
| nemotron-elastic | ? | ? | ? | ? | ? | ? | — | 4 | 8 |

### Level 3 — CONTEXT_FIXES — floor, trims, dedups, compaction reframing — —

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | ? | ? | ? | ? | ? | ? | — | 6 | 27 |
| qwen35 | ? | ? | ? | ? | ? | ? | — | 9 | 54 |
| ternary-bonsai | ? | ? | ? | ? | ? | ? | — | 30 | 51 |
| nemotron-elastic | ? | ? | ? | ? | ? | ? | — | 4 | 7 |

### Level 4 — DONE_REFUSALS_ENABLED — refusing a completion CLAIM — —

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | ? | ? | ? | ? | ? | ? | — | 10 | 46 |
| qwen35 | ? | ? | ? | ? | ? | ? | — | 17 | 140 |
| ternary-bonsai | ? | ? | ? | ? | ? | ? | — | 45 | 82 |
| nemotron-elastic | ? | ? | ? | ? | ? | ? | — | 33 | 141 |

### Level 5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner — —

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | ? | ? | ? | ? | ? | ? | — | 20 | 74 |
| qwen35 | ? | ? | ? | ? | ? | ? | — | 40 | 227 |
| ternary-bonsai | ? | ? | ? | ? | ? | ? | — | 48 | 89 |
| nemotron-elastic | ? | ? | ? | ? | ? | ? | — | 50 | 166 |


Every number is a judgement of how much of the task was actually delivered. `?` = the cell RAN and is waiting on a verdict; `·` = it never ran. A total reading `77% (3/6)` is an average over the judged cells only and cannot speak for the rest of the row.

