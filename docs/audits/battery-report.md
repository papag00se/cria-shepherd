# Battery — the engagement ladder

**Last updated 2026-08-26 09:40** — newest row `feed-pipeline-java_nemotron-elastic_codex_poff_1787760491`, scored 2026-08-26 09:39.

Tables only. Findings, walks and the retired two-arm campaign: [`battery-history.md`](battery-history.md).
Per-cell judging: [`ladder-progress.md`](ladder-progress.md). Status: `python3 suite/engagement_status.py`.

`[engagement] level = 0..5`, each rung implying every rung below it. `·` = not run. Superseded cells are excluded and re-run.

### Level 0 — pure proxy — wire translation only — 42%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟢 gemma4 | 85% | 92% | 89% | 100% | 93% | 86% | 91% | 2 | 20 |
| 🔴 qwen35 | 0% | 21% | 0% | 0% | 0% | 0% | 4% | 1 | 8 |
| 🟡 ternary-bonsai | 54% | 90% | 89% | 0% | 100% | 98% | 72% | 25 | 67 |
| 🔴 nemotron-elastic | 0% | 0% | 0% | 0% | 0% | 0% | 0% | 3 | 6 |

### Level 1 — TOOL_CALL_FIXES — dialect and template repair — 36%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟠 gemma4 | 28% | 92% | 34% | 33% | 6% | 51% | 41% | 15 | 130 |
| 🟡 qwen35 | 55% | 92% | 83% | 62% | 0% | 100% | 65% | 14 | 73 |
| 🔴 ternary-bonsai | 7% | 32% | 61% | 14% | 99% | 11% | 37% | 31 | 53 |
| 🔴 nemotron-elastic | 0% | 6% | 0% | 0% | 0% | 0% | 1% | 2 | 5 |

### Level 2 — SIMPLE_TOOLS — cria's tool menu, lowered to shell — 59%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟡 gemma4 | 11% | 89% | 81% | 76% | 66% | 100% | 70% | 9 | 71 |
| 🟡 qwen35 | 76% | 89% | 88% | 100% | 63% | 100% | 86% | 6 | 50 |
| 🟡 ternary-bonsai | 100% | 33% | 100% | 94% | 76% | 11% | 69% | 31 | 82 |
| 🔴 nemotron-elastic | 0% | 6% | 45% | 0% | 0% | 18% | 12% | 4 | 8 |

### Level 3 — CONTEXT_FIXES — floor, trims, dedups, compaction reframing — 61%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟡 gemma4 | 85% | 88% | 84% | 96% | 78% | 86% | 86% | 6 | 27 |
| 🟡 qwen35 | 93% | 100% | 83% | 80% | 58% | 74% | 81% | 9 | 54 |
| 🟡 ternary-bonsai | 1% | 78% | 93% | 99% | 94% | 18% | 64% | 30 | 51 |
| 🔴 nemotron-elastic | 0% | 0% | 50% | 12% | 0% | 15% | 13% | 4 | 7 |

### Level 4 — DONE_REFUSALS_ENABLED — refusing a completion CLAIM — 69%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟢 gemma4 | 100% | 73% | 100% | 100% | 93% | 86% | 92% | 10 | 46 |
| 🟡 qwen35 | 86% | 45% | 79% | 100% | 83% | 100% | 82% | 17 | 140 |
| 🟡 ternary-bonsai | 100% | 97% | 64% | 80% | 76% | 16% | 72% | 45 | 82 |
| 🔴 nemotron-elastic | 26% | 28% | 40% | 19% | 40% | 20% | 29% | 33 | 141 |

### Level 5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner — 67%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟡 gemma4 | 73% | 89% | 92% | 100% | 91% | 51% | 83% | 24 | 86 |
| 🟡 qwen35 | 100% | 63% | 29% | 96% | 58% | 100% | 74% | 31 | 172 |
| 🟡 ternary-bonsai | 100% | 97% | 74% | 15% | 89% | 100% | 79% | 40 | 79 |
| 🔴 nemotron-elastic | 8% | 24% | 5% | 22% | · | · | 15% | 31 | 108 |


`ˢ` = still scored strictly (all-or-nothing per deliverable); unmarked = judged. The two are not comparable. Per-cell noise on this suite is wide: gemma4's L0 and L1 scored 91 and 41 while five of six cells ran an identical code path.

