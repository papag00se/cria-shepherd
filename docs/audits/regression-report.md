# Regression campaign report — 2026-08-03 changes vs the seven passing models

Campaign doc: [docs/regression-goal.md](../regression-goal.md). Truth:
`python3 suite/regression_status.py`. This file is the operator-facing running report — updated
after every finished run.

Baseline: every model below passed 4/4 on the ladder before today's changes (planner setting shown).
Campaign code state starts at `main` (see each row's sha; fixes mid-campaign are recorded here).

## Run stats

Regenerate any time with `python3 suite/regression_stats.py` (`--write` refreshes this
section in place). The model-performance grid covers each model's last 3 STANDING runs —
voided/superseded rows are cria evidence, not model form — ranked by completion rate, then
shortest time, then least assists. Per-run: steers = directives/redirects cria injected;
gates = check runs it triggered.

### Model performance (each model's last 3 STANDING runs — voided/superseded excluded)

| model | last 3 | avg tok/s | avg min | avg calls | 🧭 | 🔁 | 🧪 | 🗜️ |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 🟢 ornith · 9B q6 | ⁴⁄₄ ⁴⁄₄ ⁴⁄₄ | 81.3 | 17 | 124 | 5 | 4 | 9 | 6 |
| 🟢 qwopus · 9B q6 | ⁴⁄₄ ⁴⁄₄ ⁴⁄₄ | 81.4 | 23 | 114 | 9 | 4 | 11 | 5 |
| 🟢 ternary-bonsai · 27B q2_0 | ⁴⁄₄ ³⁄₄ ⁴⁄₄ | 39.8 | 60 | 58 | 3 | 1 | 5 | 3 |
| 🟡 qwythos · 9B q6 | ⁴⁄₄ ²⁄₄ ⁴⁄₄ | 80.5 | 13 | 95 | 12 | 2 | 7 | 4 |
| 🟡 nemotron-elastic · 12B-A2B q4km | ⁴⁄₄ ⁴⁄₄ ²⁄₄ | 134.6 | 38 | 205 | 19 | 6 | 32 | 8 |
| 🟡 mellum2 · 12B-MoE q4 | ³⁄₄ ⁴⁄₄ ²⁄₄ | 174.6 | 8 | 76 | 9 | 2 | 14 | 2 |
| 🔴 gemma4 · 12B q4km | ²⁄₄ ¹⁄₄ ¹⁄₄ | 63.1 | 31 | 250 | 30 | 6 | 10 | 9 |

assists per run: 🧭 steers · 🔁 loops broken · 🧪 check runs · 🗜️ context work

### Per-run detail

| model | state | score | min | calls | coder | tok/s | steers | gates | terminal |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| ternary-bonsai | superseded | 3/4 | 12 | 40 | 12 | 43.7 | 0 | 0 | exited |
| ternary-bonsai | counted | 4/4 | 60 | 69 | 33 | 39.1 | 4 | 9 | budget-killed |
| gemma4 | superseded | 0/4 | 16 | 91 | 65 | 56.9 | 4 | 4 | milestone-miss-15min |
| qwythos | counted | 4/4 | 15 | 116 | 45 | 76.4 | 14 | 12 | exited |
| qwopus | counted | 4/4 | 48 | 232 | 130 | 75.6 | 14 | 23 | exited |
| ornith | superseded | 0/4 | 16 | 114 | 58 | 75.7 | 4 | 11 | milestone-miss-15min |
| ornith | counted | 4/4 | 31 | 237 | 121 | 76.5 | 9 | 18 | exited |
| mellum2 | counted | 3/4 | 9 | 72 | 38 | 170.4 | 7 | 26 | exited |
| nemotron-elastic | superseded | 1/4 | 31 | 156 | 87 | 129.2 | 8 | 38 | milestone-miss-30min |
| nemotron-elastic | counted | 4/4 | 36 | 198 | 111 | 131.4 | 20 | 31 | exited |
| ternary-bonsai | counted | 3/4 | 61 | 44 | 19 | 38.6 | 2 | 3 | milestone-miss-60min |
| gemma4 | superseded | 0/4 | 16 | 131 | 86 | 58.7 | 5 | 5 | milestone-miss-15min |
| qwythos | voided | 0/4 | 16 | 89 | 53 | 77.6 | 8 | 15 | milestone-miss-15min |
| qwopus | voided | 1/4 | 31 | 71 | 38 | 76.4 | 6 | 5 | milestone-miss-30min |
| ornith | voided | 0/4 | 16 | 74 | 43 | 78.4 | 7 | 4 | milestone-miss-15min |
| mellum2 | voided | 1/4 | 31 | 234 | 119 | 167.1 | 25 | 62 | milestone-miss-30min |
| nemotron-elastic | counted | 4/4 | 32 | 200 | 104 | 132.2 | 14 | 29 | exited |
| ternary-bonsai | counted | 4/4 | 60 | 61 | 35 | 41.7 | 2 | 4 | budget-killed |
| gemma4 | superseded | 0/4 | 16 | 61 | 36 | 61.6 | 18 | 4 | milestone-miss-15min |
| gemma4 | superseded | 1/4 | 31 | 247 | 157 | 59.2 | 35 | 21 | milestone-miss-30min |
| gemma4 | superseded | 1/4 | 31 | 227 | 138 | 61.1 | 30 | 10 | milestone-miss-30min |
| gemma4 | superseded | 3/4 | 61 | 492 | 251 | 63.4 | 54 | 16 | milestone-miss-60min |
| gemma4 | counted | 2/4 | 31 | 310 | 147 | 64.1 | 24 | 11 | milestone-miss-30min |
| gemma4 | counted | 1/4 | 31 | 202 | 137 | 62.6 | 32 | 9 | milestone-miss-30min |
| qwythos | counted | 2/4 | 15 | 112 | 68 | 83.1 | 13 | 6 | exited |
| qwopus | counted | 4/4 | 5 | 34 | 17 | 85.4 | 3 | 3 | exited |
| ornith | counted | 4/4 | 4 | 40 | 24 | 84.9 | 0 | 4 | exited |
| mellum2 | superseded | 0/4 | 16 | 107 | 70 | 160.1 | 16 | 9 | milestone-miss-15min |
| mellum2 | counted | 4/4 | 6 | 81 | 51 | 176.3 | 14 | 6 | exited |
| gemma4 | counted | 1/4 | 31 | 238 | 127 | 62.5 | 33 | 11 | milestone-miss-30min |
| qwythos | counted | 4/4 | 9 | 58 | 31 | 81.9 | 9 | 4 | exited |
| qwopus | counted | 4/4 | 15 | 75 | 46 | 83.2 | 11 | 7 | exited |
| ornith | counted | 4/4 | 17 | 94 | 51 | 82.5 | 5 | 4 | exited |
| mellum2 | counted | 2/4 | 8 | 76 | 49 | 177.1 | 7 | 9 | exited |
| nemotron-elastic | counted | 2/4 | 46 | 218 | 115 | 140.1 | 22 | 36 | milestone-miss-45min |

counted runs: 21 · avg wall 27 min · avg coder calls 71 · full-pass rate 13/21

## Scoreboard (every run; counted rows bold)

| model | plan | run | score | run_id | sha | terminal | note |
|---|---|---:|---:|---|---|---|---|
| ternary-bonsai | off | — | 3/4 | ada-handles_ternary-bonsai_codex_poff_1785818931 | fd4ca0a | exited | SUPERSEDED by a17a7c1 — walked, cria fault fixed; does not count toward 3 |
| ternary-bonsai | off | 1 | **4/4** | ada-handles_ternary-bonsai_codex_poff_1785821049 | a17a7c1 | budget-killed | 9/9 unit tests, provably-live test, working CLI, README |
| ternary-bonsai | off | 2 | **3/4** | ada-handles_ternary-bonsai_codex_poff_1785839400 | ccf601b | milestone-miss-60min | walked: cria fault none — 2 mock-fixture tests red, killed mid-fix at the hour wall; row stands |
| ternary-bonsai | off | 3 | **4/4** | ada-handles_ternary-bonsai_codex_poff_1785852998 | fae111a | budget-killed | 7/7 tests, live test, CLI, README — ternary closes 4/4, 3/4, 4/4 |
| gemma4 | off | 1 | **0/4** | ada-handles_gemma4_codex_poff_1785824758 (SUPERSEDED by the hand-back fix) | ca75dd9 | milestone-miss-15min | walked: cria fault none — model edit-spiral on one file; row stands |
| gemma4 | off | 2 | **0/4** | ada-handles_gemma4_codex_poff_1785843217 (SUPERSEDED by the hand-back fix) | 2ab7dcb | milestone-miss-15min | walked: cria fault none-to-fix — 70-call f-string spiral; false-camelCase steer counter-evidence recorded to open-threads |
| gemma4 | off | — | 0/4 | ada-handles_gemma4_codex_poff_1785860144 | 90e684b | milestone-miss-15min | SUPERSEDED by the guess-shape + phantom-path fixes (55df703) — walked, cria fault yes: the authored step invented a route/auth, a steer fabricated a path |
| gemma4 | off | — | 1/4 | ada-handles_gemma4_codex_poff_1785861503 | 55df703 | milestone-miss-30min | SUPERSEDED by the reading-step-clearance fix (36e2861) — walked, cria fault yes: the reading step was unclearable, the hand-back never fired |
| gemma4 | off | — | 1/4 | ada-handles_gemma4_codex_poff_1785866157 | 36e2861 | milestone-miss-30min | SUPERSEDED by the steer false-fact fixes (61242fc) — walked, cria fault yes: steers cited phantom line numbers and an invented API key |
| gemma4 | off | — | 3/4 | ada-handles_gemma4_codex_poff_1785869053 | 61242fc | milestone-miss-60min | SUPERSEDED by the case-typo refusal fix — walked, cria fault yes: 50+ refusals never named a one-letter case typo of the workspace; best gemma4 campaign score, new steer guards fired 4x correctly |
| gemma4 | off | 1 | **2/4** | ada-handles_gemma4_codex_poff_1785873072 | 61242fc | milestone-miss-30min | walked: cria fault none — row STANDS; RESCORED 1/4→2/4 (operator, 2026-08-04): the README-probe scorer found its documented live command and proved it live; the true-facts steer that starved /holders remains in the observe ledger |
| gemma4 | off | 2 | **1/4** | ada-handles_gemma4_codex_poff_1785875123 | 61242fc | milestone-miss-30min | walked: cria fault none — handler/handle typo warfare, self-typo'd handle, self-blinding pass/fail pipe; false-citation guard withheld 5 fabricated steers; row STANDS |
| gemma4 | off | 3 | **1/4** | ada-handles_gemma4_codex_poff_1785881741 | 878c1b1 | milestone-miss-30min | walked: cria fault none-to-fix — delivered dictations seeded the dismantling (self.client rewrite, invalid signature prescription); gemma4 closes 2,1,1 NOT STABLE; per-role DICTATES knob recommended |
| qwythos | off | 1 | **4/4** | ada-handles_qwythos_codex_poff_1785826280 | 2e7de81 | exited | 8/8 unit tests, live test, CLI, README — 14.7 min |
| qwythos | off | — | 0/4 | ada-handles_qwythos_codex_poff_1785844343 (VOIDED) | 7ec52ff | milestone-miss-15min | VOIDED (operator, 2026-08-04): ran on the caged plan-off routing; walked as model variance, but the cage taints the row — reruns on current code |
| qwythos | off | 2 | **2/4** | ada-handles_qwythos_codex_poff_1785877469 | 61242fc | exited | walked: cria fault none — reports the stake address as the resolved address (no addr1 in output), no live-test artifact; guess-shape gate re-authored a poisoned step correctly; row STANDS |
| qwythos | off | 3 | **4/4** | ada-handles_qwythos_codex_poff_1785884041 | 878c1b1 | exited | 9/9 tests, working live_test.sh, CLI, README — 9 min; RESCORED 3/4→4/4 (scorer's live glob was *.py-only; the shell live test ran green in-session); qwythos closes 4,2,4 |
| qwopus | off | 1 | **4/4** | ada-handles_qwopus_codex_poff_1785827212 | 81a4113 | exited | 17/17 unit tests, live test, CLI, README — 48 min |
| qwopus | off | — | 1/4 | ada-handles_qwopus_codex_poff_1785845382 (VOIDED) | 98a4951 | milestone-miss-30min | VOIDED (operator, 2026-08-04): ran on the caged plan-off routing; walked as model variance, but the cage taints the row — reruns on current code |
| qwopus | off | 2 | **4/4** | ada-handles_qwopus_codex_poff_1785878574 | 61242fc | exited | 11/11 unit tests, dedicated live-test file (provably live), CLI, README — 5 minutes, 34 calls: the fastest full pass of the campaign |
| qwopus | off | 3 | **4/4** | ada-handles_qwopus_codex_poff_1785885328 | 878c1b1+ | exited | full pass — qwopus closes STABLE 3/3, the campaign's first perfect record |
| ornith | off | — | 0/4 | ada-handles_ornith_codex_poff_1785830161 | 59e710a | milestone-miss-15min | SUPERSEDED by the confirm-applicability fix — walked, cria fault yes; does not count toward 3 |
| ornith | off | 1 | **4/4** | ada-handles_ornith_codex_poff_1785832068 | fbc083c | exited | 8/8 unit tests, live test, CLI, README — 31 min on the fixed code |
| ornith | off | — | 0/4 | ada-handles_ornith_codex_poff_1785847335 (VOIDED) | 1dc813b | milestone-miss-15min | VOIDED (operator, 2026-08-04): ran on the caged plan-off routing; walked as model variance, but the cage taints the row — reruns on current code |
| ornith | off | 2 | **4/4** | ada-handles_ornith_codex_poff_1785878928 | 61242fc | exited | 6/6 unit tests, live point via the README probe (documented command proved live), CLI, README — 4 minutes, 40 calls |
| ornith | off | 3 | **4/4** | ada-handles_ornith_codex_poff_1785886460 | 878c1b1+ | exited | full pass — ornith closes STABLE 3/3, the second perfect record |
| mellum2 | off | 1 | **3/4** | ada-handles_mellum2_codex_poff_1785833976 | 53f4e97 | exited | walked: cria fault none — live test folded into the unit-test file, not separate; row stands |
| mellum2 | off | — | 1/4 | ada-handles_mellum2_codex_poff_1785848364 (VOIDED) | 134c382 | milestone-miss-30min | VOIDED (operator, 2026-08-04): ran on the caged plan-off routing; walked as model variance, but the cage taints the row — reruns on current code |
| mellum2 | off | — | 0/4 | ada-handles_mellum2_codex_poff_1785880114 | 61242fc | milestone-miss-15min | SUPERSEDED by the typo-callout widening — walked, cria fault yes: dash/underscore workspace typo drew unexplained refusals; MCP-endpoint fixation and unwrap churn are the model's own |
| mellum2 | off | 2 | **4/4** | ada-handles_mellum2_codex_poff_1785881344 | 878c1b1+ | exited | 3/3 unit tests, dedicated live-test file (real resolution), CLI, README — 6 minutes, 81 calls, first run on the widened typo callout |
| mellum2 | off | 3 | **2/4** | ada-handles_mellum2_codex_poff_1785887600 | 878c1b1+ | exited | walked: cria fault none — MCP fixation + a 45-call jsonrpc:'2.0' blindness; CLI shipped address-only and its own judge approved it; mellum2 closes 3,4,2 NOT STABLE |
| nemotron-elastic | on | — | 1/4 | ada-handles_nemotron-elastic_codex_pon_1785834747 | 086dca6 | milestone-miss-30min | SUPERSEDED by the confirm-refuted-by-disk fix — walked, cria fault yes; does not count toward 3 |
| nemotron-elastic | on | 1 | **4/4** | ada-handles_nemotron-elastic_codex_pon_1785837073 | ecc40f1 | exited | RESCORED 3/4→4/4 (operator, 2026-08-04): the live test worked with the task's handle as argument; the scorer now honours that shape, as its CLI check always did |
| nemotron-elastic | on | 2 | **4/4** | ada-handles_nemotron-elastic_codex_pon_1785850908 | 7e4b167 | exited | RESCORED 3/4→4/4 (operator, 2026-08-04): same argument-shape rescore as run 1; refutation guard 2x correct in-run |
| nemotron-elastic | on | 3 | **2/4** | ada-handles_nemotron-elastic_codex_pon_1785888803 | 878c1b1+ | milestone-miss-45min | walked: cria fault none — a replan-invented invalid-handle ValueError requirement met an API that returns 200 for unknown handles; 10 rumination aborts; nemotron closes 4,4,2 |

## Notable events
- **2026-08-05 — nemotron planner-OFF standing complete: 4, 2, 4 (510 s / 370 s / 310 s;
  52 / 44 / 42 calls) vs planner-on's counted 4, 4, 2 (1,934–3,624 s; 155–291 calls).** Same
  score band at roughly a quarter of the wall clock. The 2/4 was walked (suite/walk.py, 44
  calls): a fused native-syntax double call mis-split, cria wrote the leaked protocol tags as a
  FILE named `tests`, and every later test write died on a raw FileExistsError traceback until
  the coder declared done — **cria fault, fixed** (parent-blocked plain-cause refusal +
  fused-debris content refusal, tests first). With that hole closed, planner-off's failure was
  plumbing, not the model. Recommendation: planner-off as the default lane for the strong
  cohort is now evidenced — same scores, ~4× cheaper, and it structurally removes the
  replan-invention channel that caused planner-on's own 2/4.
- **2026-08-05 — nemotron planner-OFF, first ever (operator ask): 4/4 in 510 s / 52 calls,
  clean exit.** Planner-on's best full pass took 1,934 s / 200 calls; its worst counted run
  (2/4) was caused BY a planner-side channel (the replan-invented ValueError requirement).
  One run, but ~4× faster with the same perfect score — strong evidence the planner path is
  not earning its keep on the strong cohort. Next: two more poff runs for a 3-row standing
  before any retire decision.
- **2026-08-04 — gemma4 sampling sweep (post-walk):** 10 settings × 50 real captured prompts
  replayed against live gemma4 (suite/replay.py; tables in
  docs/audits/2026-08-04-gemma4-sampling-sweep-*.txt). Tool-call well-formedness ≈100% at every
  setting (the run-killing malformed calls are ~2%/call — below this sample's floor). Judge
  verdict parseability: card 8/20 ties for best; every cooler temp scores ≤ card; the
  most-constrained cell (t0.7 + top_p .90 + top_k 20) collapses to 3/20. Ruling: keep card
  sampling; "temp too high" is not the lever — invention texture is weights-owned (seen at
  temp 0, 0.2, and 1.0 alike).

- **2026-08-04 ~19:35 — FOLLOW-UP EXPERIMENT 2: gemma4 planner-ON (card sampling) — 0/4 at the
  15-min wall, the day's worst gemma4 result.** Run ada-handles_gemma4_codex_pon_1785896127
  (GEMMA-RESAMPLE-PON; shadowed live). Prediction confirmed: planner-on multiplies self-judging
  channels, and a hallucination-prone model poisons itself through them — a step critic invented
  a `python_http_retry` package under a phantom site-packages path and the coder ABSORBED it into
  real imports; step 1 was gold-plated with unrequested retries/HTTP-2 and never finished; 52
  editrecovery escalations in 127 calls (worst thrash ratio of the day); no README, no tests.
  CONFIGURATION VERDICT for gemma4: card sampling + planner OFF is final (temp0 campaign 2/4-1/4-1/4;
  temp1 plan-off 1/4 with green-at-minute-6; temp1 plan-on 0/4). Remaining gap is the weights:
  malformed edit-call structure, write-time fabrication, self-judge contamination. Config table
  exhausted; levers left are the per-role steer-trust knob and the publisher's v3.
- **2026-08-04 ~19:20 — FOLLOW-UP EXPERIMENT: gemma4 re-measure on card sampling (temp 1.0) — score
  unchanged (1/4), failure texture transformed.** Run ada-handles_gemma4_codex_poff_1785893473
  (note GEMMA-RESAMPLE, not a campaign row; shadowed live by the operator's request). Wire-level
  verified temp 1.0/top_p 0.95/top_k 64/rep_pen 1.1. Results: green tests by minute 6 (fastest
  gemma4 ever); one-glyph mutations still occur (htpbx, resolved_ur1, cardana) but SELF-CORRECT
  within 1-2 calls instead of compounding — the deterministic mutation engine is gone. Died at
  the 30-min wall at 1/4 anyway: an unforced src/-layout refactor broke its own imports, and the
  walk's headline finding is that the model's KNOWLEDGE was right (it named the exact fix in its
  reasoning) while its EDIT CALLS kept emitting malformed argument structure and stale
  old_strings — a temperature-independent weights problem. Plus write-time fabrication
  ([tool.pudupatch], poetry-tools==0.4.25, a mutated write target `test_wallet.__spec__.py` it CREATED at call 0037,
  deleted mid-run, then chased as a half-remembered ghost for ~15 calls — operator caught the
  earlier "never existed" claim as wrong; a stray `__init__.py'` (trailing quote IN the
  filename) also landed on disk from a malformed shell quote). Verdict: keep the card sampling (strictly better behavior), but gemma4's
  ceiling on this task is the model, not the config. The improved workspace refusal visibly
  worked (its first write aimed at /home/jesse/Documents; the named-root message redirected it
  in one call).
- **2026-08-04 ~15:55 — gemma4 closes NOT STABLE (2/4, 1/4, 1/4), and the dictated-code
  re-measure has its answer.** All three counted runs reached a working state inside 15
  minutes and dismantled it during restructuring. The observe-only ledger now shows the
  cohort split cleanly: dictated steers carried the strong cohort's ladder passes, and seeded
  the destruction of three consecutive gemma4 runs (a typo'd handle, a ratified self-blinding
  pipe, and a rewrite implanting an unassigned self.client — plus one prescription that was
  invalid Python). RECOMMENDATION awaiting ruling: make DICTATES delivery a per-role knob —
  delivered for strong models, dropped or paraphrased for gemma4-class weak-obedient ones.
- **2026-08-04 ~14:00 — operator ruling: the scorer gained a README-guided live probe; one
  row improves.** When every deterministic live-test branch fails, the scorer now spends ONE
  inference call (evidence: the README; tools: read-only, workspace-bounded) asking what live
  command the project documents — then EXECUTION judges, under the unchanged provably-live
  rule (markers or clean-exit with network, failure without). The model proposes; ground
  truth decides. Rescore sweep of all 16 failed attempts: exactly one improves — gemma4's
  counted run 1785873072 rises 1/4→2/4 (its README documented `python verify.py`, which
  resolves live). mellum2 run 1's downward drift (a test pinning a live on-chain count)
  remains excluded — recorded at-run-time scores never drop retroactively.
- **2026-08-04 ~13:45 — gemma4 banks its first counted run (1/4); cria fault: none.** No
  case-typo spiral recurred; leaked judge tool-calls (including one that would have
  overwritten a file) were contained and never executed. The scoring loss traces to a
  factually-TRUE steer that told the coder to stop making two lookups — starving the
  task-required total-handles field — plus the model's own typo churn and invented packaging
  config. Nothing to fix without API-spec overfit; the steer is logged as the strongest
  counter-example in the steer-quality observe ledger. The row stands.
- **2026-08-04 ~13:10 — operator ruling: the live-test scorer honours a handle argument;
  nemotron's two 3/4s rescore to 4/4.** Its live test always did a real resolution — it just
  wanted the handle on the command line, a shape the scorer's own CLI check already tries.
  verify.py now retries a usage-failing live file with the task's handle. Both archived
  workspaces re-verified at 4/4 (sole change: the live point). A full-archive rescore sweep
  found no other run whose score the fix changes; one unrelated drift noted (mellum2 run 1's
  unit test asserts a live on-chain count that has since changed — its recorded, at-run-time
  row stands). nemotron-elastic now sits at 4/4, 4/4 with one run to go.
- **2026-08-04 ~12:55 — gemma4 hit 3/4 (its campaign best), and the walk found a one-letter
  trap.** Run 1785869053: the fix stack held (clean research, hand-back, working resolver, 3/3
  unit tests, working CLI, README; only the live check missed — the model named its live tests
  undiscoverably). The new steer guards fired four times correctly. But the middle hour drowned
  in a loop cria could have ended at its first firing: the coder typed its own workspace with
  ONE capital letter 106 times, and the workspace refusal printed both paths side by side
  without saying they differ only in letter case. Fixed: the refusal now names a case typo
  outright. Row superseded; gemma4 reruns.
- **2026-08-04 ~12:05 — operator ruling: the four caged-routing pass-2 failures are VOIDED.**
  qwythos (0/4), qwopus (1/4), ornith (0/4) and mellum2 (1/4) all ran their second pass on the
  code that caged plan-off behind "do only step 1 of N" framing. Each was walked as model
  variance at the time, but the cage was in the routing those runs actually executed — the rows
  cannot separate model wobble from the since-fixed bug. All four rerun on current code; each
  model now needs two more counted runs. nemotron-elastic's pass-2 stands (planner-on — the cage
  was a plan-off defect).
- **2026-08-04 ~11:50 — gemma4's uncaged run proved the fix stack, then cria's steer channel
  helped bury it.** Run 1785866157: cleanest opening of the campaign (real spec fetched, reading
  step cleared, hand-back fired, working resolver with passing LIVE tests by call 83). The
  completion was correctly refused — the tests weren't pytest-discoverable, exactly what the
  scorer requires — but during the 144-call restructuring spiral that followed, delivered steers
  cited line numbers past every file's real length five times ("line 245" in a 64-line file) and
  one invented an API key to argue the task-required live test should stay mocked. Both are
  doctrine-5b false facts with the ground truth sitting in the author's own prompt. Fixed
  (61242fc): the false-citation guard now reads bare/from/at line references, and an
  auth-requirement claim absent from the task triggers one gather-then-ask STANDS/REFUTED call.
  Row superseded; gemma4 reruns.
- **2026-08-04 ~10:55 — machine crash voided gemma4's in-flight run.** Run 1785863660 (the first
  on the fully-uncaged code) died with the whole box; no score, no verify, not a cria fault and
  not a counted row. The box came back with cria and the model server healthy; run 1785866157
  replaces it on the same commit (36e2861).
- **2026-08-04 ~10:20 — the referendum run answered, and the answer was "there was a second bug."**
  gemma4 on the uncaged code still went 0/4 — but the walk found the poison at call one: cria's own
  research-step author invented a route, a version prefix, and an authentication requirement out of
  thin air, and the step-quality gate couldn't see any of the three shapes. A rescue steer then
  fabricated a filesystem path. Both gaps fixed (guess-shape refusal on authored steps; phantom
  system paths withhold a steer); the row is superseded and gemma4 reruns. Separately: fabliq and
  zaya1 are fully retired from every living surface, and the provenance audit's retunes
  (dictation delivered, flail cap resets on movement, one second look) are live and visibly firing.
- **2026-08-04 ~08:45 — the operator-requested 48-hour footgun audit found the campaign's biggest
  bug in the campaign's own premise.** The plan-off rewiring that this campaign was built to test
  had quietly replaced "here is your task" with "do only step 1 of N, then stop" — and hid the
  later steps. gemma4 (deterministic sampling) is the proof: both 0/4s spent every coding turn
  pinned on step 1 with the README unreachable. Fixed: plan-off now does its research step, then
  gets the raw task back, and replans can never split the user's task. gemma4's two failed rows
  are superseded; it reruns on the fixed code. The audit also hardened tonight's three campaign
  fixes (one critical overreach in the missing-file veto guard, rebuilt as ask-the-reasoner per
  the no-fuzzy-determinism principle). Full record: 2026-08-04-48h-footgun-audit.md. OPEN
  QUESTION for the operator: qwythos/qwopus/ornith/mellum2's pass-2 failures also ran on the
  caged routing (walked as model variance at temp 0.6) — void and rerun them too, or let the rows
  stand?
- **2026-08-04 ~03:40 — third cria fault found and fixed (nemotron-elastic run 1).** The
  double-checker vetoed approved steps three times by claiming files were missing — once naming the
  exact path of a file that existed, without ever looking. Cria now checks the disk itself: a veto
  built on a "missing" file that actually exists is overturned on the spot. Also recorded (for the
  standing design thread, not built): the model-as-planner kept regenerating a step demanding
  fields from an endpoint that doesn't have them — cria's own fetched schema disproves it — and
  that step ate half the run through seven correct rejections.
- **2026-08-04 ~02:20 — second cria fault found and fixed (ornith run 1).** The model finished
  its research in 2 minutes and cria's own verification machinery then ate 6 of the 15: the step
  critic approved the research step three times, and the read-only double-checker vetoed each one
  by demanding files a research step never promises. Measured across all history: on steps that
  promise no file, that double-check is a coin flip (155 pass / 158 block) — pure noise with veto
  power. Fix: the double-check now runs only where there is something on disk it could actually
  check (or the repo's checks are failing). Full suite green (2345), cria restarted, the failed
  row superseded; ornith reruns on the fixed code.
- **2026-08-04 ~00:15 — gemma4 run 1 is a real regression signal, not a cria bug.** 0/4 at the
  15-minute check. The model built a near-working file in 3 minutes, then spent 12 minutes breaking
  and re-breaking it with inexact edits — deleting its own tests a minute before the check. Every
  cria guard fired where designed; the walk found no fixable fault. Watch item: the new plan
  routing kept the model pinned on "fix the file" while a README (which alone clears the 15-min
  floor) sat unstarted in a later step. If runs 2/3 die the same way, that pattern becomes the
  finding.

- **2026-08-03 ~23:25 — the fix proved itself on its first run.** ternary-bonsai run 1 on `a17a7c1`
  scored 4/4. The same early-finish attempt from the walked run happened again — the replanner tried
  to declare everything done — but this time cria refused it and ran the repo's checks (twice) before
  letting the session end. The run used the full hour (`budget-killed`) instead of exiting at 12
  minutes with broken tests.

- **2026-08-03 ~22:20 — cria fault found and fixed on the first campaign run.** The run scored 3/4
  (unit tests red: the model wrote its test file blind with three bugs and no one ever ran pytest).
  The walk showed the session ended on the say-so of three model judges while cria's own
  deterministic check gate never ran once — the one completion route without the ground-truth
  backstop, and today's plan-off rerouting put every plan-off run on it. Fix `a17a7c1`: a session
  can no longer finish without cria running the repo's checks first; failing checks reopen the work
  with the real findings. Fail-before test added, full suite green (2335), cria restarted 22:23,
  the failed row marked superseded. Full walk: [ladder-walk.md](ladder-walk.md#ada-handles_ternary-bonsai_codex_poff_1785818931).

## Final summary (campaign complete, 2026-08-04 ~18:15)

**Question asked:** did the 2026-08-03 changes regress the seven models that had passed the
ladder 4/4? **Answer: the campaign became as much an audit of cria as of the models — five cria
faults and three scorer blind spots were found and fixed along the way, and on the final code
two models are perfectly stable, five are not.**

| model | counted runs | verdict | one-line cause (from the walks) |
|---|---|---|---|
| qwopus · 9B q6 | 4/4, 4/4, 4/4 | **stable 3/3** | — |
| ornith · 9B q6 | 4/4, 4/4, 4/4 | **stable 3/3** | — |
| ternary-bonsai · 27B q2_0 | 4/4, 3/4, 4/4 | NOT STABLE 2/3 | run 2 died mid-fix of two mock-fixture tests at the hour wall — slow decode, not confusion |
| nemotron-elastic · 12B-A2B | 4/4, 4/4, 2/4 | NOT STABLE 2/3 | run 3: a replan-invented "invalid handle must raise ValueError" requirement met an API that returns 200 for unknown handles — 25-minute tarpit |
| qwythos · 9B q6 | 4/4, 2/4, 4/4 | NOT STABLE 2/3 | run 2 shipped the stake address as the "resolved address" and no live-test artifact — semantics, not process |
| mellum2 · 12B-MoE q4 | 3/4, 4/4, 2/4 | NOT STABLE 1/3 | swagger-first habit lands it on the MCP endpoint (twice); run 3 burned 45 calls on jsonrpc:"2.0" and shipped an address-only CLI its own judge approved |
| gemma4 · 12B q4km | 2/4, 1/4, 1/4 | NOT STABLE 0/3 | reaches a working state inside 15 min EVERY run, then dismantles it — post-campaign audit found OUR sampling misconfig (greedy + rep-penalty = identifier mutation); card sampling now applied, re-measure recommended |

**Cria faults found by the walks and fixed mid-campaign** (each superseded the run that exposed it):
completion-without-gates (a17a7c1) · confirm-brake coin-flip on artifact-free steps (fbc083c) ·
false missing-file vetoes → gather-then-ask disk refutation (ecc40f1+) · plan-off step cage +
unclearable reading step (ef0b771 fixes → 36e2861) · authored-step guess shapes + phantom paths
(55df703) · steer false line-citations + invented auth requirement (61242fc) · workspace-typo
refusal blind to case then dash/underscore (both widened).

**Scorer fairness fixes** (operator-directed, applied to both verifiers via _liveprobe):
handle-argument retry (nemotron 3/4→4/4 ×2) · README-guided live probe (gemma4 1/4→2/4;
ornith's run-2 live point) · *.sh live tests (qwythos 3/4→4/4).

**Standing recommendations:** (1) rerun gemma4 ×3 on the card sampling (temp 1.0) — its failure
signature matches the misconfig exactly; (2) per-role DICTATES knob — dictated steers carried
the strong cohort and seeded three consecutive gemma4 destructions; (3) the planner-on replan
channel can invent requirements — nemotron's only campaign failure came from one.
