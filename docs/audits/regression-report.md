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
| gemma4 | off | 1 | **0/4** | ada-handles_gemma4_codex_poff_1785824758 | ca75dd9 | milestone-miss-15min | walked: cria fault none — model edit-spiral on one file; row stands |
| qwythos | off | 1 | **4/4** | ada-handles_qwythos_codex_poff_1785826280 | 2e7de81 | exited | 8/8 unit tests, live test, CLI, README — 14.7 min |
| qwopus | off | 1 | **4/4** | ada-handles_qwopus_codex_poff_1785827212 | 81a4113 | exited | 17/17 unit tests, live test, CLI, README — 48 min |
| ornith | off | — | 0/4 | ada-handles_ornith_codex_poff_1785830161 | 59e710a | milestone-miss-15min | SUPERSEDED by the confirm-applicability fix — walked, cria fault yes; does not count toward 3 |
| ornith | off | 1 | **4/4** | ada-handles_ornith_codex_poff_1785832068 | fbc083c | exited | 8/8 unit tests, live test, CLI, README — 31 min on the fixed code |
| mellum2 | off | 1 | **3/4** | ada-handles_mellum2_codex_poff_1785833976 | 53f4e97 | exited | walked: cria fault none — live test folded into the unit-test file, not separate; row stands |
| nemotron-elastic | on | — | 1/4 | ada-handles_nemotron-elastic_codex_pon_1785834747 | 086dca6 | milestone-miss-30min | SUPERSEDED by the confirm-refuted-by-disk fix — walked, cria fault yes; does not count toward 3 |
| nemotron-elastic | on | 1 | **3/4** | ada-handles_nemotron-elastic_codex_pon_1785837073 | ecc40f1 | exited | walked: cria fault none — live test demands an argument, exits 1 bare; both fixes fired correctly in-run |

## Notable events

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
