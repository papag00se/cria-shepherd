# Battery — the engagement ladder

**Last updated 2026-08-24 19:13** — newest row `cart-billing-go_gemma4_codex_poff_1787623790`, scored 2026-08-24 19:13.

Tables only. Findings, walks and the retired two-arm campaign: [`battery-history.md`](battery-history.md).
Per-cell judging: [`ladder-progress.md`](ladder-progress.md). Status: `python3 suite/engagement_status.py`.

`[engagement] level = 0..5`, each rung implying every rung below it. `·` = not run. Superseded cells are excluded and re-run.

### Level 0 — pure proxy — wire translation only

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟢 gemma4 | 85% | 92% | 89% | 100% | 93% | 86% | 91% | 2 | 20 |

### Level 1 — TOOL_CALL_FIXES — dialect and template repair

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟠 gemma4 | 28% | 92% | 34% | 33% | 6% | 51% | 41% | 15 | 130 |

### Level 2 — SIMPLE_TOOLS — cria's tool menu, lowered to shell

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟡 gemma4 | 11% | 89% | 81% | 76% | 66% | 100% | 70% | 9 | 71 |

### Level 3 — CONTEXT_FIXES — floor, trims, dedups, compaction reframing

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟡 gemma4 | 85% | 88% | 84% | 96% | 78% | 86% | 86% | 6 | 27 |

### Level 4 — DONE_REFUSALS_ENABLED — refusing a completion CLAIM

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟡 gemma4 | · | 73% | · | · | · | 86% | 80% | 5 | 27 |

### Level 5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| 🟡 gemma4 | 60%ˢ | 100%ˢ | · | · | · | · | 80% | 29 | 122 |


`ˢ` = still scored strictly (all-or-nothing per deliverable); unmarked = judged. The two are not comparable. Per-cell noise on this suite is wide: gemma4's L0 and L1 scored 91 and 41 while five of six cells ran an identical code path.


## Every run

| task | language | model | arm | score | min | calls | tok/s | terminal |
|---|---|---|---|---:|---:|---:|---:|---|
| shipping-rates-rb | ruby | gemma4 | BASE | 87% | 10 | 105 | 58.1 | exited |
| shipping-rates-rb | ruby | gemma4 | CRIA | 52% | 46 | 204 | 58.6 | milestone-miss-45min |
| shipping-rates-rb | ruby | qwen35 | BASE | 98% | 9 | 103 | 72.9 | exited |
| shipping-rates-rb | ruby | qwen35 | CRIA | 62% | 46 | 363 | 79.4 | milestone-miss-45min |
| shipping-rates-rb | ruby | ternary-bonsai | BASE | 62% | 31 | 71 | 37.3 | milestone-miss-30min |
| shipping-rates-rb | ruby | ternary-bonsai | CRIA | 100% | 52 | 110 | 42.7 | exited |
| shipping-rates-rb | ruby | nemotron-elastic | BASE | 0% | 0 | 6 | 136.6 | crashed-early |
| shipping-rates-rb | ruby | nemotron-elastic | CRIA | 9% | 31 | 133 | 128.4 | milestone-miss-30min |
| cart-billing-go | go | gemma4 | BASE | 95% | 2 | 13 | 60.5 | exited |
| cart-billing-go | go | gemma4 | CRIA | 96% | 8 | 36 | 57.5 | exited |
| cart-billing-go | go | qwen35 | BASE | 69% | 4 | 46 | 75.1 | exited |
| cart-billing-go | go | qwen35 | CRIA | 89% | 16 | 94 | 79.3 | exited |
| cart-billing-go | go | ternary-bonsai | BASE | 100% | 20 | 56 | 41.5 | exited |
| cart-billing-go | go | ternary-bonsai | CRIA | 89% | 28 | 65 | 42.3 | exited |
| cart-billing-go | go | nemotron-elastic | BASE | 13% | 4 | 26 | 128.8 | exited |
| cart-billing-go | go | nemotron-elastic | CRIA | 37% | 31 | 91 | 129.7 | milestone-miss-30min |
| orders-api-py | python | gemma4 | BASE | 90% | 3 | 15 | 59.6 | exited |
| orders-api-py | python | gemma4 | CRIA | 100% | 38 | 49 | 57.2 | exited |
| orders-api-py | python | qwen35 | BASE | 89% | 17 | 70 | 71.4 | exited |
| orders-api-py | python | qwen35 | CRIA | 83% | 46 | 214 | 78.2 | milestone-miss-45min |
| orders-api-py | python | ternary-bonsai | BASE | 86% | 46 | 52 | 36.9 | exited |
| orders-api-py | python | ternary-bonsai | CRIA | 66% | 46 | 58 | 40.7 | milestone-miss-45min |
| orders-api-py | python | nemotron-elastic | BASE | 39% | 4 | 14 | 127.3 | exited |
| orders-api-py | python | nemotron-elastic | CRIA | 8% | 31 | 108 | 130.6 | milestone-miss-30min |
| feed-pipeline-java | java | gemma4 | BASE | 93% | 4 | 20 | 58.9 | exited |
| feed-pipeline-java | java | gemma4 | CRIA | 96% | 5 | 25 | 61.1 | exited |
| feed-pipeline-java | java | qwen35 | BASE | 51% | 25 | 132 | 71.4 | exited |
| feed-pipeline-java | java | qwen35 | CRIA | 45% | 31 | 169 | 80.7 | milestone-miss-30min |
| feed-pipeline-java | java | ternary-bonsai | BASE | 29% | 16 | 33 | 40.9 | milestone-miss-15min |
| feed-pipeline-java | java | ternary-bonsai | CRIA | 96% | 76 | 113 | 36.1 | budget-killed |
| feed-pipeline-java | java | nemotron-elastic | BASE | 0% | 0 | 5 | 135.0 | crashed-early |
| feed-pipeline-java | java | nemotron-elastic | CRIA | 28% | 31 | 61 | 131.3 | milestone-miss-30min |
| handles-cli-node | node | gemma4 | BASE | 69% | 1 | 13 | 60.2 | exited |
| handles-cli-node | node | gemma4 | CRIA | 61% | 3 | 25 | 61.0 | exited |
| handles-cli-node | node | qwen35 | BASE | 80% | 6 | 77 | 73.2 | exited |
| handles-cli-node | node | qwen35 | CRIA | 83% | 15 | 94 | 81.3 | exited |
| handles-cli-node | node | ternary-bonsai | BASE | 100% | 8 | 30 | 42.4 | exited |
| handles-cli-node | node | ternary-bonsai | CRIA | 94% | 60 | 118 | 39.0 | budget-killed |
| handles-cli-node | node | nemotron-elastic | BASE | 0% | 1 | 2 | 133.9 | crashed-early |
| handles-cli-node | node | nemotron-elastic | CRIA | 28% | 31 | 100 | 132.7 | milestone-miss-30min |
| rust-toml-cli | rust | gemma4 | BASE | 78% | 1 | 7 | 60.3 | crashed-early |
| rust-toml-cli | rust | gemma4 | CRIA | 86% | 3 | 19 | 63.5 | exited |
| rust-toml-cli | rust | qwen35 | BASE | 96% | 4 | 38 | 75.2 | exited |
| rust-toml-cli | rust | qwen35 | CRIA | 99% | 2 | 31 | 82.8 | exited |
| rust-toml-cli | rust | ternary-bonsai | BASE | 99% | 51 | 21 | 40.4 | exited |
| rust-toml-cli | rust | ternary-bonsai | CRIA | 19% | 31 | 27 | 38.4 | milestone-miss-30min |
| rust-toml-cli | rust | nemotron-elastic | BASE | 16% | 2 | 6 | 131.5 | exited |
| rust-toml-cli | rust | nemotron-elastic | CRIA | 26% | 46 | 161 | 132.5 | milestone-miss-45min |
