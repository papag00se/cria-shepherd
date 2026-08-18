# Finish and re-measure — progress

**Status file for [`docs/goals/finish-and-remeasure.md`](../goals/finish-and-remeasure.md).** Updated as each item lands and as each cell finishes, never batched.

Started at `721fa51`. `cria.service` is on an OLDER commit — two fixes are committed and not yet live.

## Step 1 — the three open items

| item | evidence it needs | state |
|---|---|---|
| 1a periodic step check shares a counter with the gate | walk one planner-ON run; does `coder_turns` pass through 12 on a cycle where the check could have fired and didn't | open |
| 1b ecosystem discovery is manifest-only | a walked run where the gate's silence let a wrong answer through | open |
| 1c the gate re-runs the suite in the live workspace | a design that does not copy the world | open |

## Step 2 — the two cells

| cell | last score | this pass |
|---|---|---|
| shipping-rates-rb × ternary-bonsai | 0/5 | not run |
| shipping-rates-rb × gemma4 | 1/5 | not run |

## Step 3 — walk

Findings go to `docs/audits/finish-and-remeasure-walk.md`. Not started.

## Step 4 — fix to 100%

Nothing yet. A 100% needs a second run at the same commit to count — the noise floor at identical code is 25 points.

## Step 5 — full suite

Not started.

## Log

- `721fa51` — goal opened. Seven fixes landed this session; the two ruby cells and three plumbing items remain.
