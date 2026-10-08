# Battery — fresh campaign and historical engagement ladder

<!-- fresh-l0-restored-20261007:start -->
## Current fresh campaign — planner-off L0

Campaign **`l0-restored-20261007`**; authoritative state: `~/.cria/suite/_campaigns/l0-restored-20261007/manifest.json`.
**Eleven logical cells judged: nine main finals, shipping replacement, and separately labeled operator-ended feed. Next: Ornith/rust.** Original failed attempts remain unscored and preserved separately; no failure is represented as0% or promoted to natural completion.
Each percentage is the recorded holistic usefulness judgment, not test completion or a model-capability ceiling. Unjudged cells have no percentage; failed attempts retain their evidence outside the score matrix. Every cell must obtain a successful, judged run (0% is valid) before serial execution moves on; infrastructure failures are repaired and rerun, never treated as scores.

| model | ruby | go | python | java | node | rust | avg usefulness | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🔴 0% | 🟡 80% | 🔴 2% | 🔴 3% | 🔴 35% | 🟢 95% | 36% | 1 | 24 |
| ornith1.5_9b | 🟢 90% | 🟡 75% | 🟢 90% | 🔴 30% | 🟡 75% |  | 72% | 45 | 151 |
| bonsai2 |  |  |  |  |  |  | · | · | · |
| nemotron-elastic |  |  |  |  |  |  | · | · | · |
| ling3.0_tiny |  |  |  |  |  |  | · | · | · |
| phi4 |  |  |  |  |  |  | · | · | · |
| k2_horizon_7b |  |  |  |  |  |  | · | · | · |
| qwen3.8_9b_distill |  |  |  |  |  |  | · | · | · |

**Row-average coverage:** gemma4_12b: usefulness6/6, minutes6/6, calls6/6; ornith1.5_9b: usefulness5/5, minutes5/5, calls4/5.
Means use selected independently judged logical cells once; zeros count, pending/unjudged cells and failed originals do not. Missing, non-numeric or invalid metrics are excluded, not fabricated as zero. Minutes are authoritative wall_seconds/60, including judge waits (not active-work minutes); operator-ended measurement basis remains in attempt provenance. A mean with incomplete coverage is a partial known-metric mean.

### Attempt evidence (provenance outside score cells)

| run ID | judgment | delivered work / limitation |
|---|---|---|
| `shipping-rates-rb_gemma4_12b_codex_poff_1791411301` | 0% | Seed unchanged; requested changes absent. |
| `cart-billing-go_gemma4_12b_codex_poff_1791412888` | 80% | Decimal arithmetic, rounding regression, JSON discounts and logging; wrong config location/log semantics, runtime unverified. |
| `orders-api-py_gemma4_12b_codex_poff_1791413132` | 2% | Reusable default-pending schema fragment; bodyless init makes module invalid, remaining API/migration/index/test work absent. |
| `feed-pipeline-java_gemma4_12b_codex_poff_1791413299` | 3% | OpenCSV dependency only; importer unchanged, REVIEW.md absent, runtime unverified. |
| `handles-cli-node_gemma4_12b_codex_poff_1791415541` | 35% | Fetch/output/error branches, Dockerfile and attempted tests; ES-module/require crash, commander dependency violates contract, tests misuse execSync result. |
| `rust-toml-cli_gemma4_12b_codex_poff_1791415702` | 95% | Cargo TOML parser CLI, dotted lookup, error handling, tests and README; build/runtime unverified, strings use TOML formatting. |
| `cart-billing-go_ornith1.5_9b_codex_poff_1791417342` | 75% | Decimal/cents calculations, corrected Subtotal, rounding regression, JSON/fallback discounts and logging; module-mode tests/vet/build pass, but file lookup is cwd-relative, logged subtotal is discounted cents and default vendoring fails. |
| `feed-pipeline-java_ornith1.5_9b_codex_poff_1791419572` | **unscored original failure** | Length-truncated historical tool arguments poisoned Codex compaction/native template parsing; original archive/captures/row retained, never judged. Fresh linked rerun follows the wire repair. |
| `handles-cli-node_ornith1.5_9b_codex_poff_1791437986` | 75% | Natural exited final; independent exact-archive judgment credits fetch/CLI/metadata/tests/Docker, captured four passing tests and container goose lookup; eight-page scan independently returns1instead of2fixture matches, actual arbitrary-holder totals unverified. Authoritative209calls,2458.1wall/1808.1active seconds; not a checkpoint score. |
| `orders-api-py_ornith1.5_9b_codex_poff_1791419168` | 90% | Customer orders/totals, pending status and in-place migration/index, parameterized lookups and real HTTP tests; captured tests/migration probe pass, but URL decoding is absent, custom server DB path ignored and index detection name-based, with these edge cases runtime-unverified. |
| `shipping-rates-rb_ornith1.5_9b_codex_poff_1791418723` | 90% — authorized rerun | Threshold fix, express rates/tests, rate table and gem-backed country inputs; captured repository tests pass, but GB wrongly maps to international and its added test/README reinforce that error. |
| `shipping-rates-rb_ornith1.5_9b_codex_poff_1791415881` | **unscored infrastructure failure** | Native context overflow after cria substituted estimated usage and hid typed rejection; evidence preserved, never retried or judged. |

**Failure preservation and repair:** `~/.cria/validation/l0-ornith-feed-blocker/` holds the exact result row, manifest and hash receipt linking retained log/archive/captures. Operator now authorizes fixing infrastructure failures and requires a successful, judged run before moving to the next cell; the original failed attempt is never overwritten or scored.

**Ornith/feed checkpoint:** `feed-pipeline-java_ornith1.5_9b_codex_poff_1791419572.015min` recorded **35% / continue**, not a final. OpenCSV dependency, validation/skip reporting and typed aggregation fragments are reusable; nested-method compilation failure, missing CSV wiring/helper, sequential ForkJoin children and shared state remain, with speedup/determinism unverified and REVIEW absent. First30 active minutes protected.

**Ornith/cart progression:** 15-active-minute checkpoint65%/continue, then natural final75%. Subtotal units were corrected after the checkpoint; module-mode test/vet/build results are captured, while a read-only offline dependency check confirms default vendoring is broken.

**Operator-authorized rerun:** Ornith/shipping finished naturally as `shipping-rates-rb_ornith1.5_9b_codex_poff_1791418723`, recorded90%, under distinct cohort `l0-restored-20261007-ornith-shipping-rerun-1` at repaired `115b699d`. The table displays this authorized new judgment, not credit for the original failure, which remains unscored and preserved above. The serial guardian launched shipping only after cart exited, waited for both judgments, and resumed the original main driver; no GPU overlap or historical Ornith reruns.

**Latest feed attempt:** `feed-pipeline-java_ornith1.5_9b_codex_poff_1791422591`, distinct cohort `l0-restored-20261008-ornith-feed-rerun-1`, linked to the exact original failure, at `f1e5f1261928d608bb9f760db0c622819d19de3d`. It ended with a typed native context overflow after a large tool-output burst; **unscored**, not0%, with exact row/captures retained at `~/.cria/validation/l0-ornith-feed-rerun-1-failure/`. Both read-only reviewers converged on restoring the pinned client's default; no next cell launched before a successful replacement judgment. Original main manifest retains8judged/2preserved failures/38pending; the additional failed rerun does not satisfy the successful-cell gate. Heartbeat `0fc734a6` remains active through repairs. Native error reports60964tokens against49152context; previous native reply26438input/184output, and the next requests still carried tools rather than compaction. These are captured protocol facts, not a final usefulness judgment or an established full root-cause finding.

**Active replacement:** `l0-restored-20261008-ornith-feed-rerun-2` at `879ecac87ae44cff34d290d56f04ef4db2fdab1e`, linked to both original and failed replacement attempts. Output policy is the verified pinned default `bytes/10000` (~10KB); the capability catalog had accidentally widened it to~40KB since35cf333c. This is caller-owned default restoration, not L0 server clipping/tool reduction. Compaction85%, native context, sampling and planner-off remain unchanged. Dense-burst pinned-client tests pass; native CPU template/tokenizer checks fit both measured incident baselines. Full5811passed/2skipped/3568subtests, same19historical failures. Guardian waits for successful usefulness judgment before main progression. New rows disclose model-visible historical wire envelopes; no byte-invisibility claim. Existing explicit reasoning effortnone is unchanged, and prior widened-policy judgments retain their original provenance.

**Operator-ended feed attempt:** User stopped `feed-pipeline-java_ornith1.5_9b_codex_poff_1791426897`; guardian and complete descendant tree terminated, with no live descendants verified. Full workspace/captures/logs/manifests and hash index preserved under linked rerun2 `operator-stop-20261008/`. Independently scored **30%** through `suite/usefulness.py` against the exact stopped archive, not a checkpoint: reusable OpenCSV/local accumulation fragments, but production compilation fails, String-path/skip/currency integration is broken and REVIEW.md absent; runtime correctness/determinism/fourfold speedup unverified. This is **operator-ended**, NOT natural completion or infrastructure success. Operator explicitly authorizes recording this disposition, removing the mistakenly imposed campaign hold and resuming the next pending Ornith/handles cell without rerunning feed. Ten logical cells now have independent judgments (eight main +shipping replacement +operator-ended feed disposition); originals and failed replacement1 remain unscored. The stopped runner produced no authoritative terminal call/usage census; those metrics are explicitly unknown, never synthesized. Operator clarified substantive prompt requirements define milestones, with approximately15minutes per requirement, first two protected30minutes;35% completion at45minutes on a five-requirement task warrants ending rather than indefinite continuation for edits.

**Last recorded feed checkpoint (historical, not the independently judged final/cell score; continuation superseded by operator stop):** `feed-pipeline-java_ornith1.5_9b_codex_poff_1791426897.120min` — 30% useful, continue for concrete worker-local Partial/map/counter and post-join merge redesign, not activity or a score threshold. Full current/prior source/seed/changed probes inspected; exact frozen rewrite regresses compilation (duplicated merge fragment outside any method, diagnostics begin at145). Uninitialized Partial slots, unresolved rows/readRows, invalid thread construction and immutable skip-counter mutations prevent integration. String-path compatibility, currency handling, summary skip reporting and REVIEW.md remain absent. Current runtime totals and4x speedup unverified; prior105-minute executable snapshot's demonstrated nondeterministic counts remain preserved, not treated as current execution. Earlier15/30/45/60/75/90/105-minute checkpoints20%/25%/30%/20%/25%/25%/35% remain preserved, not final scores. Judgment wait excluded; no next cell launched.

**Disclosed revision boundaries:** first Gemma/shipping at `f56f2d08fee69788c5d8c6bdea924c3a8a6cf761`; other five Gemma cells and failed Ornith/shipping at `c250b92a18c2c6ec884b008fc55bb34d73e67f5e`; Ornith/cart, orders, original failed feed and successful shipping rerun at `115b699d008990e9738edc5bca5c2152ba408629`; failed feed replacement1 at `f1e5f1261928d608bb9f760db0c622819d19de3d` after lossless historical-argument wire repair and failure-only evidence validation; operator-ended replacement2 at **`879ecac87ae44cff34d290d56f04ef4db2fdab1e`**; untouched cells resume from main after `25760ae5` under requirement-pace judgment policy v2, retaining prior run revisions and unchanged fleet assets after restoring the pinned output default, preserving executable argument bytes and disclosing wire translations. Native template replay proves original500/repaired200; pinned-harness compaction passes; full5796passed/2skipped/3565subtests, same19historical failures. No assists added; planner off, mandatory sandbox, pinned Codex0.159.3, unchanged canonical fleet sampling. First30 active minutes protected; checkpoints every15 active minutes, with semantic continuation thereafter and judgment waits excluded.

Full verdicts and archived workspaces remain under `~/.cria/suite/`; repair evidence: `~/.cria/validation/l0-ornith-context-repair/FINDING.md`. Historical scores below are **not credit for this fresh campaign**. This current section is updated after each newly completed cell, including unscored failures.
**Preserved Ornith/handles checkpoint (not its independently judged final75%):** `handles-cli-node_ornith1.5_9b_codex_poff_1791437986.030min` — **65% useful / continue**. Since full15-minute snapshot: metadata repaired to valid dependency-free JSON, broken stdout-buffer/forced-exit shutdown removed, Dockerfile/.gitignore and usage documentation added. Fetch migration and container definition are substantive delivered requirements near the approximate first-half-hour allowance, not an extension for minor edits. Offline help passes; independent synthetic execution proves8-page cap undercounts a holder with another match on page9 (1returned versus2fixture total). CLI tests unchanged; live API correctness/end-to-end execution and image runtime unverified. Earlier15-minute40%report retained. Judge/maintenance wait excluded; no next cell launched.

<!-- fresh-l0-restored-20261007:end -->

## Historical engagement ladder — retained, not the current campaign

**Last updated 2026-10-05 11:02** — newest row `cart-billing-go_defiant-fable_codex_poff_1790855379`, finished 2026-10-01 05:30.
**Report code revision `cab43fb0`; inference anchor remains `f79cc6146470281b5909cf605b27afca1177e2d1`.**

Each cell is an inferred usefulness percentage 🟢≥88 🟡≥63 🟠≥38 🔴 below; `·` = not judged. `[engagement] level = 0..5`, each rung implying every rung below it. Model rows use the [official project names](model-names.md). Gemma4/QAT share the single `gemma4_12b` row: frozen history remains for unreplaced cells and the latest live judgment supersedes its matching cell. Historical model keys, run IDs and executable aliases retain their original provenance.

### Level 0 — pure proxy — wire translation only — 43%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🟡 85% | 🟢 92% | 🟢 89% | 🟢 100% | 🟢 93% | 🟡 86% | 91% | 2 | 20 |
| bonsai2 | 🔴 0% | 🟢 88% | 🟢 90% | 🔴 0% | 🟢 88% | 🟢 92% | 60% | 26 | 36 |
| qwen3.8_9b_distill | 🟡 72% | 🟡 82% | 🔴 22% | 🔴 8% | 🟠 52% | 🟡 84% | 53% | 9 | 108 |
| k2_horizon_7b | 🔴 0% | 🟡 85% | 🟢 90% | 🔴 30% | 🟢 92% | 🟢 95% | 65% | 15 | 63 |
| phi4 | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 0 | 2 |
| ling3.0_tiny | 🔴 2% | 🔴 6% | 🟠 50% | 🟠 45% | 🔴 4% | 🟡 78% | 31% | 3 | 128 |
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

### Level 5 — ASSISTS_ENABLED — steers, periodic gates, detectors, planner — 42%

| model | ruby | go | python | java | node | rust | total | avg min | avg calls |
|---|---|---|---|---|---|---|---:|---:|---:|
| gemma4_12b | 🟠 49% | 🟡 74% | 🟡 78% | 🟠 55% | 🟠 62% | 🟢 91% | 68% | 43 | 106 |
| bonsai2 | 🔴 18% | 🔴 0% | 🟡 87% | 🔴 5% | 🟠 59% | 🔴 3% | 29% | 41 | 58 |
| qwen3.8_9b_distill | 🟡 68% | 🟠 52% | 🔴 15% | 🔴 10% | 🟠 62% | 🟡 80% | 48% | 38 | 239 |
| ornith1.5_9b | 🟢 95% | 🟡 84% | 🟡 85% | 🟡 70% | 🟡 75% | 🟢 95% | 84% | 60 | 126 |
| k2_horizon_7b | 🔴 10% | 🟡 80% | 🔴 33% | 🔴 2% | 🟡 78% | 🔴 18% | 37% | 38 | 116 |
| phi4 | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 🔴 0% | 0% | 33 | 180 |
| ling3.0_tiny | 🔴 3% | 🔴 10% | 🔴 33% | 🔴 0% | 🔴 28% | 🟡 78% | 25% | 35 | 261 |

Retired from the battery (history kept in suite/results/results.jsonl and suite/historical_ladder.json): qwen35, qwen38.

