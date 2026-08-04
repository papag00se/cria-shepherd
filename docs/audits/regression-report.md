# Regression campaign report — 2026-08-03 changes vs the seven passing models

Campaign doc: [docs/regression-goal.md](../regression-goal.md). Truth:
`python3 suite/regression_status.py`. This file is the operator-facing running report — updated
after every finished run.

Baseline: every model below passed 4/4 on the ladder before today's changes (planner setting shown).
Campaign code state starts at `main` (see each row's sha; fixes mid-campaign are recorded here).

## Run stats

Regenerate any time with `python3 suite/regression_stats.py` (`--write` refreshes this
section in place). The model-performance grid covers each model's last 3 runs in any state,
ranked by completion rate, then shortest time, then least assists (current form; the
scoreboard below owns what counts). Per-run: steers = directives/redirects cria injected;
gates = check runs it triggered.

### Model performance (each model's last 3 runs, any state)

| model | last 3 | avg tok/s | 🧭 | 🔁 | 🧪 | 🗜️ | avg min |
|---|---|---:|---:|---:|---:|---:|---:|
| 🟢 ternary-bonsai | ⁴⁄₄ ³⁄₄ ⁴⁄₄ | 39.8 | 3 | 1 | 5 | 3 | 60 |
| 🟡 qwopus | ⁴⁄₄ ¹⁄₄ ⁴⁄₄ | 79.1 | 8 | 4 | 10 | 7 | 28 |
| 🟡 nemotron-elastic | ¹⁄₄ ⁴⁄₄ ⁴⁄₄ | 130.9 | 14 | 7 | 33 | 6 | 33 |
| 🟡 ornith | ⁴⁄₄ ⁰⁄₄ ⁴⁄₄ | 79.9 | 5 | 3 | 9 | 6 | 17 |
| 🟠 qwythos | ⁴⁄₄ ⁰⁄₄ ²⁄₄ | 79.0 | 12 | 3 | 11 | 4 | 15 |
| 🟠 gemma4 | ³⁄₄ ²⁄₄ ¹⁄₄ | 63.4 | 37 | 7 | 12 | 12 | 41 |
| 🔴 mellum2 | ³⁄₄ ¹⁄₄ ⁰⁄₄ | 165.9 | 16 | 1 | 32 | 6 | 19 |

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

counted runs: 14 · avg wall 31 min · avg coder calls 74 · full-pass rate 9/14

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
| qwythos | off | 1 | **4/4** | ada-handles_qwythos_codex_poff_1785826280 | 2e7de81 | exited | 8/8 unit tests, live test, CLI, README — 14.7 min |
| qwythos | off | — | 0/4 | ada-handles_qwythos_codex_poff_1785844343 (VOIDED) | 7ec52ff | milestone-miss-15min | VOIDED (operator, 2026-08-04): ran on the caged plan-off routing; walked as model variance, but the cage taints the row — reruns on current code |
| qwythos | off | 2 | **2/4** | ada-handles_qwythos_codex_poff_1785877469 | 61242fc | exited | walked: cria fault none — reports the stake address as the resolved address (no addr1 in output), no live-test artifact; guess-shape gate re-authored a poisoned step correctly; row STANDS |
| qwopus | off | 1 | **4/4** | ada-handles_qwopus_codex_poff_1785827212 | 81a4113 | exited | 17/17 unit tests, live test, CLI, README — 48 min |
| qwopus | off | — | 1/4 | ada-handles_qwopus_codex_poff_1785845382 (VOIDED) | 98a4951 | milestone-miss-30min | VOIDED (operator, 2026-08-04): ran on the caged plan-off routing; walked as model variance, but the cage taints the row — reruns on current code |
| qwopus | off | 2 | **4/4** | ada-handles_qwopus_codex_poff_1785878574 | 61242fc | exited | 11/11 unit tests, dedicated live-test file (provably live), CLI, README — 5 minutes, 34 calls: the fastest full pass of the campaign |
| ornith | off | — | 0/4 | ada-handles_ornith_codex_poff_1785830161 | 59e710a | milestone-miss-15min | SUPERSEDED by the confirm-applicability fix — walked, cria fault yes; does not count toward 3 |
| ornith | off | 1 | **4/4** | ada-handles_ornith_codex_poff_1785832068 | fbc083c | exited | 8/8 unit tests, live test, CLI, README — 31 min on the fixed code |
| ornith | off | — | 0/4 | ada-handles_ornith_codex_poff_1785847335 (VOIDED) | 1dc813b | milestone-miss-15min | VOIDED (operator, 2026-08-04): ran on the caged plan-off routing; walked as model variance, but the cage taints the row — reruns on current code |
| ornith | off | 2 | **4/4** | ada-handles_ornith_codex_poff_1785878928 | 61242fc | exited | 6/6 unit tests, live point via the README probe (documented command proved live), CLI, README — 4 minutes, 40 calls |
| mellum2 | off | 1 | **3/4** | ada-handles_mellum2_codex_poff_1785833976 | 53f4e97 | exited | walked: cria fault none — live test folded into the unit-test file, not separate; row stands |
| mellum2 | off | — | 1/4 | ada-handles_mellum2_codex_poff_1785848364 (VOIDED) | 134c382 | milestone-miss-30min | VOIDED (operator, 2026-08-04): ran on the caged plan-off routing; walked as model variance, but the cage taints the row — reruns on current code |
| mellum2 | off | — | 0/4 | ada-handles_mellum2_codex_poff_1785880114 | 61242fc | milestone-miss-15min | SUPERSEDED by the typo-callout widening — walked, cria fault yes: dash/underscore workspace typo drew unexplained refusals; MCP-endpoint fixation and unwrap churn are the model's own |
| nemotron-elastic | on | — | 1/4 | ada-handles_nemotron-elastic_codex_pon_1785834747 | 086dca6 | milestone-miss-30min | SUPERSEDED by the confirm-refuted-by-disk fix — walked, cria fault yes; does not count toward 3 |
| nemotron-elastic | on | 1 | **4/4** | ada-handles_nemotron-elastic_codex_pon_1785837073 | ecc40f1 | exited | RESCORED 3/4→4/4 (operator, 2026-08-04): the live test worked with the task's handle as argument; the scorer now honours that shape, as its CLI check always did |
| nemotron-elastic | on | 2 | **4/4** | ada-handles_nemotron-elastic_codex_pon_1785850908 | 7e4b167 | exited | RESCORED 3/4→4/4 (operator, 2026-08-04): same argument-shape rescore as run 1; refutation guard 2x correct in-run |

## Notable events

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

## Final summary

- (campaign in progress)
