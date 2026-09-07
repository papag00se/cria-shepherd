# Battery — the engagement ladder + usefulness

**Two measures live here, and they are NOT the same number — do not compare a cell in one section to a cell in the other.**

1. **Mechanical task-grade (historical, through 2026-09-02).** The per-cell % is the deterministic task grader's "fraction of the task the checker could confirm delivered." These graders were **deliberately removed** on 2026-09-05 (`dd0b604 refactor(suite): remove mechanical task grading`), which blanked this data in the live report. It is restored below, labelled as historical, because it is hard-won measurement across four models × six languages × six rungs — preserved, not resurrected as the current truth.
2. **Holistic usefulness % (current, 2026-09-05 →).** An independent read-only judgment of *how much reusable coding the model wrote that the user no longer has to write* — inferred from the task and the archived workspace, never a checker re-count. This is the live measure.

`[engagement] level = 0..5`, each rung implying every rung below it. `·` = not run. Superseded cells are excluded and re-run.

Legend (mechanical section): 🟢 ≥88% · 🟡 70–87% · 🟠 45–69% · 🔴 <45%. Columns map task→language: ruby=shipping-rates-rb, go=cart-billing-go, python=orders-api-py, java=feed-pipeline-java, node=handles-cli-node, rust=rust-toml-cli.

---

## Section A — Engagement ladder · MECHANICAL task-grade (historical, through 2026-09-02)

### Level 0 — pure proxy — wire translation only — 42%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🟡 85% | 🟢 92% | 🟢 89% | 🟢 100% | 🟢 93% | 🟡 86% | 91% | 2 | 20 |
| qwen35 | 🔴 0% | 🔴 21% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 4% | 1 | 8 |
| ternary-bonsai | 🟠 54% | 🟢 90% | 🟢 89% | 🔴 0% | 🟢 100% | 🟢 98% | 72% | 25 | 67 |
| nemotron-elastic | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 3 | 6 |

### Level 1 — TOOL_CALL_FIXES — dialect and template repair — 36%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🔴 28% | 🟢 92% | 🔴 34% | 🔴 33% | 🔴 6% | 🟠 51% | 41% | 15 | 130 |
| qwen35 | 🟠 55% | 🟢 92% | 🟡 83% | 🟠 62% | 🔴 0% | 🟢 100% | 65% | 14 | 73 |
| ternary-bonsai | 🔴 7% | 🔴 32% | 🟠 61% | 🔴 14% | 🟢 99% | 🔴 11% | 37% | 31 | 53 |
| nemotron-elastic | 🔴 0% | 🔴 6% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 1% | 2 | 5 |

### Level 2 — SIMPLE_TOOLS — cria's tool menu, lowered to shell — 59%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🔴 11% | 🟢 89% | 🟡 81% | 🟡 76% | 🟡 66% | 🟢 100% | 70% | 9 | 71 |
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

### Level 5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner — 82%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4 | 🟡 73% | 🟢 89% | 🟢 92% | 🟢 100% | 🟢 91% | 🟢 100% | 91% | 20 | 74 |
| qwen35 | 🟢 100% | 🟡 63% | 🟡 71% | 🟢 96% | 🟢 93% | 🟢 100% | 87% | 40 | 227 |
| ternary-bonsai | 🟢 100% | 🟢 97% | 🟡 74% | 🟢 100% | 🟢 89% | 🟢 100% | 93% | 48 | 89 |
| nemotron-elastic | 🟠 59% | 🔴 31% | 🟡 76% | 🔴 20% | 🟡 70% | 🟡 84% | 57% | 50 | 180 |

---

## Section B — HOLISTIC usefulness % (current measure, 2026-09-05 →)

All rows are Level 5 (ASSISTS_ENABLED), the current run configuration. Each cell is inferred reusable-coding-saved, judged independently from the archived workspace. `·` = not judged holistically yet.

| model | ruby | go | python | java | node | rust | when / note |
|---|---|---|---|---|---|---|---|
| **ornith15** | 5% | 84% | 85% | 35% | 75% | 95% | 2026-09-05; strong Go/Python/Rust, weak Ruby/Java |
| **gigachat31** (original) | 2% | 1% | 0% | 0% | 0% | 0% | 2026-09-05; pre-fix, Russian developer prompt live |
| **gigachat31** (re-run, cria-side fixes live) | ~2% | ~6% | ~5% | ~2% | ~6% | ~18% | 2026-09-06; gate-transport exemption `a3f82da` + blind-touch grounding `f83fbf6` + listing footer `337b483` + stripped template; every cell checkpoint-stopped |
| **nemotron-elastic** (holistic partial) | · | 10% | · | 10% | · | · | partial re-judgment; paused, replaced by gigachat31 in the active matrix |
| gemma4 / qwen35 / ternary-bonsai | · | · | · | · | · | · | mechanical L5 in Section A; holistic re-judgment not yet run |

### gigachat31 re-run findings (2026-09-06)

Row average ~0.5% → ~6.5% with all three cria-side fixes + stripped template live. **The fixes are confirmed working across all six cells**: 0 `/tmp/cria-gate` denials anywhere (was every gated check), footer `⟦ctx:files⟧` and real `⟦ctx:checks⟧` present throughout, and the model now reads/lists the workspace (never did in the original). Per-cell: shipping ~2% (locked on nonexistent `shipping.rb`), cart ~6% (go.mod decimal dep real; `cart.go` unconverted), orders ~5% (`GET /customers` never landed), feed-java ~2% (confabulated `SupplierFeedImporter.java`), handles ~6% (51-line confabulated `resolver.js`), rust ~18% (126L main.rs + 3 tests on the real files, but 9→14 compile errors — regressing).

The lift is real but uniformly sub-viable: the reasoning-free core still confabulates filenames the footer lists correctly, and cannot turn the now-real check output into a converging fix. **gigachat31 stays quarantined from the coding fleet** — the fixes removed cria's own footguns (so the quarantine is now for the model, not the harness), and every cell tripped the non-strict-relative checkpoint stop.
