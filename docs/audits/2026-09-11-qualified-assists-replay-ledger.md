# Qualified assists with no demonstrated Ornith replay benefit

## Purpose and rule

This is a **retention ledger**, not an effectiveness ranking and not a removal queue.  It records the
narrow changes that cleared their own evidence, doctrine, adversarial-review, history, and regression
gauntlets, but for which the named Ornith/feed replay or unchanged cell did **not** demonstrate a
usefulness benefit.  A negative or inconclusive result on one model, captured call, or task does not
establish that the correction is useless for another model, harness, task, or failure shape.

Keep the categories separate:

- **correctness/control-flow evidence** establishes the owner-level invariant and its regressions;
- **exact-call or reconstructed-fixture replay** establishes only the stated response/control-flow
  behavior; and
- **fresh-cell usefulness** establishes only that frozen task/model/harness/settings outcome.  It is
  never a causal estimate for the assist unless a comparative experiment earns that claim.

The entries below are the campaign units with an explicit replay/cell limitation in their primary
audit record.  A shipped repair with no such documented replay outcome is deliberately not added by
inference.

## Retained shipped assists

| Commit | Assist / invariant retained | What cleared the gauntlet | Replay or cell limit | Current disposition |
|---|---|---|---|---|
| `0917b91` | Whole-file reads preserve leading/EOF bytes; failed, denied, or harness-cut reads cannot replace known whole-file bytes. | Raw harness fixtures, baseline-red owner tests, focused/full regression, and independent review. | The early counterfactual calls still followed false compiler/version theories; the unchanged cell ended at 50%.  Neither result demonstrates a preventive usefulness gain. | **Retain as transport correctness.** The model had to receive literal file bytes regardless of that replay's later reasoning. |
| `ec28f2f` | An end-only `read_file` request is lowered as the requested prefix beginning at line 1, rather than as a whole read. | Owner history, baseline-red range tests, focused/full suite, and adversarial review. | In the paired CALL0055 replay both arms continued by inspection and emitted no implementation action.  The later 63% cell is not a causal estimate of this range fix. | **Retain as tool-contract correctness.** A requested bounded prefix must not become an unrequested whole-file refusal. |
| `0593ff0` (landed by `b726276`) | Work-log decoded tool arguments/results preserve literal whitespace and CR/LF boundaries. | Baseline-red literal-field tests, isolated/full suite, source-byte provenance, adversarial review, and durable transport capture. | The changed producer was not a byte-identical historical CALL0115 replay; its replacement summary was rejected for unsupported claims.  The later unchanged cell finished at 20%, which supplies no usefulness benefit evidence. | **Retain as decoded-field correctness.** It does not authorize summary adoption, capacity claims, or an inference that literal preservation helped this Ornith task. |
| `d91666a` | A structural multi-action steer refusal remains distinct from genuine empty/`ON_TRACK` provenance and cannot enter recovery as if it were empty. | Captured incident provenance, baseline-compatible behavioral-red tests, two real author paths, guard seam controls, full suite, and independent review. | The replay is deterministic captured-response control flow, not a fresh model/usefulness test.  The subsequent unchanged cell stalled at 20%; that cell does not establish benefit or harm from this provenance repair. | **Retain as control-flow correctness.** It preserves the existing factual fallback and real empty/`ON_TRACK` recovery. |
| `87d620e` | A typed parsed-context/inner-no-change outcome suppresses only the immediate forced-off compactor retry when normal final wire bytes remain identical. | Two real baseline-red evidence-builder paths, adversarial controls for empty/transient/non-context/changed-wire behavior, history review, full suite, and independent code review. | The reviewed offline fixture differential showed 2 baseline fake sends versus 1 candidate fake send, not endpoint behavior or usefulness.  The fresh unchanged cell reached 8%/continue at 30 minutes and 5%/stalled at 45 minutes; it demonstrated no usefulness benefit. | **Retain as narrow wire correctness.** It must not be generalized into global request deduplication or a capacity/fidelity/usefulness claim. |

## Rejected-but-preserved comparison

`3ebcc6a` (superseded-write-note ordering/wording) is not a current assist.  It is retained here
because it is the important opposite case: an exact-call arm reduced repeated reads (1/8 versus 6/8)
while preserving the notice, but the required unchanged full cell finished at 30%, below the source
run's 35%.  The commit was reverted.  That full-cell result invalidated shipping the intervention; it
does **not** erase the observed causal incident, make the replay fabricated, or prove that every
future wording/order correction of that shape is ineffective.  See
[`2026-09-09-feed-pipeline-ornith15-full-walk.md`](2026-09-09-feed-pipeline-ornith15-full-walk.md).

## Evidence index

- Whole-read fixture/replay and 50% cell boundary:
  [`2026-09-10-whole-read-eof-replay.md`](2026-09-10-whole-read-eof-replay.md)
- End-only owner proof, paired replay, and its limits:
  [`2026-09-10-end-only-read-range.md`](2026-09-10-end-only-read-range.md)
- Literal-boundary proof, replacement-transport boundary, and rejected summary:
  [`2026-09-11-work-log-literal-boundaries.md`](2026-09-11-work-log-literal-boundaries.md)
- Structural-refusal provenance and deterministic control replay:
  [`2026-09-11-steer-structural-refusal-recovery.md`](2026-09-11-steer-structural-refusal-recovery.md)
- Structural-refusal 20% cell limit:
  [`2026-09-11-feed-pipeline-ornith15-structural-steer-cell.md`](2026-09-11-feed-pipeline-ornith15-structural-steer-cell.md)
- Literal-boundary 20% cell limit:
  [`2026-09-11-feed-pipeline-ornith15-literal-boundary-cell.md`](2026-09-11-feed-pipeline-ornith15-literal-boundary-cell.md)
- Caller retry owner controls and offline differential:
  [`2026-09-11-caller-context-noop-retry.md`](2026-09-11-caller-context-noop-retry.md)
- Caller retry's independent 30/45-minute private judgments:
  `/tmp/ornith-feed-caller-context-030-{judgment.json,evidence.md}` and
  `/tmp/ornith-feed-caller-context-045-{judgment.json,evidence.md}`.

## Decision discipline

Do not delete or broaden a retained correction from this ledger because of one unsuccessful replay.
Before revisiting one, state which proposition is being measured: its owner invariant, a particular
captured-call response, or usefulness on a specified fresh cell.  Reuse the narrow regression
contract; keep task/model/harness-specific outcomes as evidence, not as universal verdicts.
