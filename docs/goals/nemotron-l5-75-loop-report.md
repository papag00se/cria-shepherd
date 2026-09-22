# nemotron-elastic L5 >75% closure report

Ledger for the goal in `docs/goals/nemotron-l5-75-loop.md`. Maintained by the Supervisor; dated
sections supersede older prose where they conflict.

## Acceptance ledger

| Cell | Latest comparable run | Final usefulness | Status |
|---|---|---:|---|
| shipping-rates-rb | — | — | no comparable baseline yet |
| cart-billing-go | — | — | no comparable baseline yet |
| orders-api-py | — | — | no comparable baseline yet |
| feed-pipeline-java | — | — | no comparable baseline yet |
| handles-cli-node | — | — | no comparable baseline yet |
| rust-toml-cli | — | — | no comparable baseline yet |

Strict closure criterion: every cell's latest comparable L5 final usefulness judgment is >75%.
Comparable means: launched by this campaign at a recorded HEAD with note form
`BATTERY2 L5 nemotron-elastic <short-HEAD> p4`, planner on, completing through canonical
milestone/final judgment. The FROZEN historical ladder row (L5 total 57%: ruby 59, go 31,
python 76, java 20, node 70, rust 84 — `suite/historical_ladder.json`) and all pre-pause
(2026-09-05) results rows are prior-knowledge and walk evidence only, never comparable cells.

## Baseline environment

*(Phase 0 fills this in: HEAD, `git status`, live `~/.cria/cria.toml` summary, `cria.service`
health, served model identity from `:18084/v1/models`, runtime `n_ctx` from `:18084/props`,
capture/archive locations.)*

## Walks and candidate records

*(Per-cell causal findings with exact capture citations. A child report is a lead until the
Supervisor has verified its cited files. Durable segments and finding files live under
`~/.cria/walk-findings/<date>/<cell>/` — never `/tmp`.)*

## Accepted units / replay / reruns

*(One entry per accepted change: causal chain, commit, fails-before/passes-after test, full-suite
result, exact-capture replay evidence, service restart/health, and the comparable rerun(s) it
produced — plus the Bonsai 2 closed-row regression assessment.)*

## Rejected candidates

*(Every rejected candidate with the evidence that rejected it. Rejections are load-bearing:
they stop the next session from re-deriving a dead end.)*
