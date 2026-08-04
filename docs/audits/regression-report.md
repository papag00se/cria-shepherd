# Regression campaign report — 2026-08-03 changes vs the seven passing models

Campaign doc: [docs/regression-goal.md](../regression-goal.md). Truth:
`python3 suite/regression_status.py`. This file is the operator-facing running report — updated
after every finished run.

Baseline: every model below passed 4/4 on the ladder before today's changes (planner setting shown).
Campaign code state starts at `main` (see each row's sha; fixes mid-campaign are recorded here).

| model | plan | run | score | run_id | sha | terminal | note |
|---|---|---:|---:|---|---|---|---|
| ternary-bonsai | off | — | 3/4 | ada-handles_ternary-bonsai_codex_poff_1785818931 | fd4ca0a | exited | SUPERSEDED by a17a7c1 — walked, cria fault fixed; does not count toward 3 |

## Notable events

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
