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
| gemma4 | off | 1 | **0/4** | ada-handles_gemma4_codex_poff_1785824758 | ca75dd9 | milestone-miss-15min | walked: cria fault none — model edit-spiral on one file; row stands |
| qwythos | off | 1 | **4/4** | ada-handles_qwythos_codex_poff_1785826280 | 2e7de81 | exited | 8/8 unit tests, live test, CLI, README — 14.7 min |

## Notable events

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
