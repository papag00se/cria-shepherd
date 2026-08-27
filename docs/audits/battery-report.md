# Battery — the engagement ladder

**Last updated 2026-08-27 15:05** — newest row `feed-pipeline-java_ternary-bonsai_codex_poff_1787856782`, scored 2026-08-27 13:09.

Tables only. Findings, walks and the retired two-arm campaign: [`battery-history.md`](battery-history.md).
Per-cell judging: [`ladder-progress.md`](ladder-progress.md). Status: `python3 suite/engagement_status.py`.

`[engagement] level = 0..5`, each rung implying every rung below it. `·` = not run. Superseded cells are excluded and re-run.

### Level 0 — pure proxy — wire translation only — 42%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🟡 85%ᵘ | 🟢 92%ᵘ | 🟢 89%ᵘ | 🟢 100%ᵘ | 🟢 93%ᵘ | 🟡 86%ᵘ | 91% | 2 | 20 |
| qwen35 | 🔴 0% | 🔴 21%ᵘ | 🔴 0%ᵘ | 🔴 0% | 🔴 0% | 🔴 0% | 4% | 1 | 8 |
| ternary-bonsai | 🟠 54% | 🟢 90% | 🟢 89% | 🔴 0% | 🟢 100% | 🟢 98% | 72% | 25 | 67 |
| nemotron-elastic | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 3 | 6 |

### Level 1 — TOOL_CALL_FIXES — dialect and template repair — 36%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🔴 28%ᵘ | 🟢 92%ᵘ | 🔴 34%ᵘ | 🔴 33%ᵘ | 🔴 6%ᵘ | 🟠 51%ᵘ | 41% | 15 | 130 |
| qwen35 | 🟠 55% | 🟢 92% | 🟡 83% | 🟠 62% | 🔴 0% | 🟢 100% | 65% | 14 | 73 |
| ternary-bonsai | 🔴 7% | 🔴 32% | 🟠 61% | 🔴 14% | 🟢 99% | 🔴 11% | 37% | 31 | 53 |
| nemotron-elastic | 🔴 0% | 🔴 6% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 1% | 2 | 5 |

### Level 2 — SIMPLE_TOOLS — cria's tool menu, lowered to shell — 59%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🔴 11%ᵘ | 🟢 89%ᵘ | 🟡 81%ᵘ | 🟡 76%ᵘ | 🟡 66%ᵘ | 🟢 100%ᵘ | 70% | 9 | 71 |
| qwen35 | 🟡 76% | 🟢 89% | 🟢 88% | 🟢 100% | 🟡 63% | 🟢 100% | 86% | 6 | 50 |
| ternary-bonsai | 🟢 100% | 🔴 33% | 🟢 100% | 🟢 94% | 🟡 76% | 🔴 11% | 69% | 31 | 82 |
| nemotron-elastic | 🔴 0% | 🔴 6% | 🟠 45% | 🔴 0% | 🔴 0% | 🔴 18% | 12% | 4 | 8 |

### Level 3 — CONTEXT_FIXES — floor, trims, dedups, compaction reframing — 61%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🟡 85% | 🟢 88% | 🟡 84% | 🟢 96% | 🟡 78% | 🟡 86% | 86% | 6 | 27 |
| qwen35 | 🟢 93% | 🟢 100% | 🟡 83% | 🟡 80% | 🟠 58% | 🟡 74% | 81% | 9 | 54 |
| ternary-bonsai | 🔴 1% | 🟡 78% | 🟢 93% | 🟢 99% | 🟢 94% | 🔴 18% | 64% | 30 | 51 |
| nemotron-elastic | 🔴 0% | 🔴 0% | 🟠 50% | 🔴 12% | 🔴 0% | 🔴 15% | 13% | 4 | 7 |

### Level 4 — DONE_REFUSALS_ENABLED — refusing a completion CLAIM — 69%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🟢 100% | 🟡 73% | 🟢 100% | 🟢 100% | 🟢 93% | 🟡 86% | 92% | 10 | 46 |
| qwen35 | 🟡 86% | 🟠 45% | 🟡 79% | 🟢 100% | 🟡 83% | 🟢 100% | 82% | 17 | 140 |
| ternary-bonsai | 🟢 100% | 🟢 97% | 🟡 64% | 🟡 80% | 🟡 76% | 🔴 16% | 72% | 45 | 82 |
| nemotron-elastic | 🔴 26% | 🔴 28% | 🟠 40% | 🔴 19% | 🟠 40% | 🔴 20% | 29% | 33 | 141 |

### Level 5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner — 81%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🟡 73% | 🟢 89% | 🟢 92% | 🟢 100% | 🟢 91% | 🟢 100% | 91% | 20 | 74 |
| qwen35 | 🟢 100% | 🟡 63% | 🟡 71% | 🟢 96% | 🟢 93% | 🟢 100% | 87% | 40 | 227 |
| ternary-bonsai | 🟢 100% | 🟢 97% | 🟡 74% | 🟢 100% | 🟢 89% | 🟢 100% | 93% | 48 | 89 |
| nemotron-elastic | 🔴 27% | 🔴 32% | 🟡 76% | 🔴 28% | 🟡 70% | 🟡 84% | 53% | 47 | 180 |


`ˢ` = still scored strictly (all-or-nothing per deliverable); unmarked = judged. The two are not comparable.

`ᵘ` = the cell ran BEFORE the commit that gated its own rung, so its number cannot speak for that rung. Every gemma4 cell at L0-L2 and two qwen35 L0 cells are marked: the ladder was built in eight commits on 2026-08-24 while cells were being run, and until the last of them the output massage chain had no gate and ran at every level. Their arms differ by mechanisms that fired zero times — three independent replays over the captures agree `massage.apply` changed 0 of 1,615 replies across those runs — so they are repeat samples of one configuration, not a rung comparison.

**One sample per cell.** Repeat runs of the SAME cell in a FIXED configuration have scored 0 and 100 (`ternary-bonsai x cart-billing-go`, and again on `rust-toml-cli`), and `gemma4 x cart-billing-go` spans 40 to 100 over six runs. No difference between two rungs is readable below roughly that spread until the grid carries n>1.

