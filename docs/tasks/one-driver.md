# The two drivers were never merged — only relocated

**Status:** open. This is the next structural task, and it is the root of ten defects fixed on
2026-08-02 alone.

## What happened

The route-unify (2026-07-18) made a planner-off session into a synthetic one-step plan carried by the
same `PlanSession`, entering through one `Loop.drive`. That unified the **plan shape** and the
**entry point**. It did not unify the **driver**. `_drive_locked` still forks:

- `_work` → `_work_item` — the plan-ON step driver
- `_drive_single_item` — described in the code as *"the relocated plan-off path"*

Relocated into the same file, not merged. Every mechanism must therefore be added twice, and the
file's own comments describe the two as siblings to be kept in sync — which is the failure mode, not
a mitigation of it.

## The evidence

Ten mechanisms were found live on one path and missing from its twin in a single day. Each cost real
run time before it was found:

| mechanism | had it | missing from |
|:--|:--|:--|
| durable fetch ledger (`_fetched_facts_anchor`) | `_work_item` | `_drive_single_item` — **0 of 166 prompts** carried it |
| live-execution check, before the verdict | `_reopen_if_unsatisfied` | `_periodic_satisfaction`, then `_done_critic_reason` |
| compaction truncation retry | `loop.summarize` | `server._harden_compaction_reply` |
| fetch facts in the judge's evidence | `_grounded_evidence` | `_satisfaction_evidence` |
| research facts for the plan judges | — | all three call sites |
| numbered `read_file` | `verifytools` (crew) | `writeproxy` (coder) |

Three of those misses were introduced the same day they were fixed, by fixing one path.

## What is actually shared

Measured by reading both functions. The pre-completion half is the same job written twice:

`_frame_for_item` · workspace inventory · `_fetched_facts_anchor` · self-compaction · `focustrim.trim`
· `guard_intervene` · `guard_periodic_gate` · `_coder_turn` · `_periodic_satisfaction`

**This half should be ONE function.** Every miss in the table above is in it.

## What is genuinely different — do not force these together

`_work_item` ends by asking *"is this STEP done"* (`_gate_op` → `_verify` → `_advance` /
`_renudge_or_replan`). `_drive_single_item` ends by asking *"is the TASK done"* (`_gate_single_done`
→ `_done_critic_reason` / `guard_gate_verdict`), and carries `_judge_search_reads`,
`_reasoned_reanchor` and the `guard_probe_*` family.

Those are different questions and two answers is correct. What is NOT correct is that they compose
their evidence separately — that is how `_satisfaction_evidence` came to promise *"the durable fetch
facts below are complete and unaffected"* and then append none.

## The shape of the work

1. Extract the shared pre-coder half into one `_framed_turn(sess, body, rlog, *, step, total)`.
   Both drivers call it. A one-step synthetic plan passes `step=1, total=1`.
2. Give the completion judges ONE evidence composer, the way the compaction request got one owner.
3. Collapse the three `judge_satisfaction` call sites to one helper that every caller routes through,
   so "which callers exist" stops being something a walk has to discover.
4. A test that asserts the two drivers reference the same shared helper — the same shape as the
   existing `test_both_place_it_in_the_protected_head`, but covering the whole shared half rather
   than one mechanism at a time.

## Why it was not done on 2026-08-02

~250 lines of merge, attempted on the last of a context window, is how a refactor passes its tests
and breaks a run. The per-mechanism fixes shipped are correct and tested; this removes the reason
they kept being needed.
