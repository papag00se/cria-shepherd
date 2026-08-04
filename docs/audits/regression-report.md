# Regression campaign report — 2026-08-03 changes vs the seven passing models

Campaign doc: [docs/regression-goal.md](../regression-goal.md). Truth:
`python3 suite/regression_status.py`. This file is the operator-facing running report — updated
after every finished run.

Baseline: every model below passed 4/4 on the ladder before today's changes (planner setting shown).
Campaign code state starts at `main` (see each row's sha; fixes mid-campaign are recorded here).

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
| qwythos | off | 1 | **4/4** | ada-handles_qwythos_codex_poff_1785826280 | 2e7de81 | exited | 8/8 unit tests, live test, CLI, README — 14.7 min |
| qwythos | off | — | 0/4 | ada-handles_qwythos_codex_poff_1785844343 (VOIDED) | 7ec52ff | milestone-miss-15min | VOIDED (operator, 2026-08-04): ran on the caged plan-off routing; walked as model variance, but the cage taints the row — reruns on current code |
| qwopus | off | 1 | **4/4** | ada-handles_qwopus_codex_poff_1785827212 | 81a4113 | exited | 17/17 unit tests, live test, CLI, README — 48 min |
| qwopus | off | — | 1/4 | ada-handles_qwopus_codex_poff_1785845382 (VOIDED) | 98a4951 | milestone-miss-30min | VOIDED (operator, 2026-08-04): ran on the caged plan-off routing; walked as model variance, but the cage taints the row — reruns on current code |
| ornith | off | — | 0/4 | ada-handles_ornith_codex_poff_1785830161 | 59e710a | milestone-miss-15min | SUPERSEDED by the confirm-applicability fix — walked, cria fault yes; does not count toward 3 |
| ornith | off | 1 | **4/4** | ada-handles_ornith_codex_poff_1785832068 | fbc083c | exited | 8/8 unit tests, live test, CLI, README — 31 min on the fixed code |
| ornith | off | — | 0/4 | ada-handles_ornith_codex_poff_1785847335 (VOIDED) | 1dc813b | milestone-miss-15min | VOIDED (operator, 2026-08-04): ran on the caged plan-off routing; walked as model variance, but the cage taints the row — reruns on current code |
| mellum2 | off | 1 | **3/4** | ada-handles_mellum2_codex_poff_1785833976 | 53f4e97 | exited | walked: cria fault none — live test folded into the unit-test file, not separate; row stands |
| mellum2 | off | — | 1/4 | ada-handles_mellum2_codex_poff_1785848364 (VOIDED) | 134c382 | milestone-miss-30min | VOIDED (operator, 2026-08-04): ran on the caged plan-off routing; walked as model variance, but the cage taints the row — reruns on current code |
| nemotron-elastic | on | — | 1/4 | ada-handles_nemotron-elastic_codex_pon_1785834747 | 086dca6 | milestone-miss-30min | SUPERSEDED by the confirm-refuted-by-disk fix — walked, cria fault yes; does not count toward 3 |
| nemotron-elastic | on | 1 | **3/4** | ada-handles_nemotron-elastic_codex_pon_1785837073 | ecc40f1 | exited | walked: cria fault none — live test demands an argument, exits 1 bare; both fixes fired correctly in-run |
| nemotron-elastic | on | 2 | **3/4** | ada-handles_nemotron-elastic_codex_pon_1785850908 | 7e4b167 | exited | walked: cria fault none — same argument-demanding live test as run 1; refutation guard 2x correct |

## Run stats

Regenerate any time with `python3 suite/regression_stats.py` (`--md` for this table).
steers = times cria injected a directive/redirect; gates = times cria ran or reattached
the repo's own checks. Snapshot as of the last finished run:

| model | state | score | min | calls | coder | tok/s | steers | gates | terminal |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| ternary-bonsai | superseded | 3/4 | 12 | 40 | 12 | 43.7 | 0 | 0 | exited |
| ternary-bonsai | counted | 4/4 | 60 | 69 | 33 | 39.1 | 4 | 11 | budget-killed |
| gemma4 | superseded | 0/4 | 16 | 91 | 65 | 56.9 | 4 | 8 | milestone-miss-15min |
| qwythos | counted | 4/4 | 15 | 116 | 45 | 76.4 | 14 | 14 | exited |
| qwopus | counted | 4/4 | 48 | 232 | 130 | 75.6 | 14 | 31 | exited |
| ornith | superseded | 0/4 | 16 | 114 | 58 | 75.7 | 4 | 14 | milestone-miss-15min |
| ornith | counted | 4/4 | 31 | 237 | 121 | 76.5 | 9 | 25 | exited |
| mellum2 | counted | 3/4 | 9 | 72 | 38 | 170.4 | 7 | 27 | exited |
| nemotron-elastic | superseded | 1/4 | 31 | 156 | 87 | 129.2 | 8 | 42 | milestone-miss-30min |
| nemotron-elastic | counted | 3/4 | 36 | 198 | 111 | 131.4 | 20 | 37 | exited |
| ternary-bonsai | counted | 3/4 | 61 | 44 | 19 | 38.6 | 2 | 4 | milestone-miss-60min |
| gemma4 | superseded | 0/4 | 16 | 131 | 86 | 58.7 | 5 | 10 | milestone-miss-15min |
| qwythos | voided | 0/4 | 16 | 89 | 53 | 77.6 | 8 | 18 | milestone-miss-15min |
| qwopus | voided | 1/4 | 31 | 71 | 38 | 76.4 | 6 | 7 | milestone-miss-30min |
| ornith | voided | 0/4 | 16 | 74 | 43 | 78.4 | 7 | 6 | milestone-miss-15min |
| mellum2 | voided | 1/4 | 31 | 234 | 119 | 167.1 | 25 | 67 | milestone-miss-30min |
| nemotron-elastic | counted | 3/4 | 32 | 200 | 104 | 132.2 | 14 | 35 | exited |
| ternary-bonsai | counted | 4/4 | 60 | 61 | 35 | 41.7 | 2 | 6 | budget-killed |
| gemma4 | superseded | 0/4 | 16 | 61 | 36 | 61.6 | 18 | 8 | milestone-miss-15min |
| gemma4 | superseded | 1/4 | 31 | 247 | 157 | 59.2 | 35 | 31 | milestone-miss-30min |
| gemma4 | superseded | 1/4 | 31 | 227 | 138 | 61.1 | 30 | 18 | milestone-miss-30min |

counted runs: 9 · avg wall 39 min · avg coder calls 71 · full-pass rate 5/9

counted runs: 9 · avg wall 39 min · avg coder calls 71 · full-pass rate 5/9

## Notable events

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
