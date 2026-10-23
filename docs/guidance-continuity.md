# Guidance continuity: rejected checkpoint, remaining boundary

## Disposition

Reject the persistence implementation checkpointed in `b9f7a5c5`. Restore the pre-checkpoint runtime. This is not a rejection of historical guidance custody in principle, nor a claim that follow-through is solved. No campaign continuation or model experiment is authorized by this investigation.

The checkpoint duplicated a fresh directive immediately as historical text, stored it before final delivery, expired it after three preparations, and cleared it on every step-driver tool call. Reading a prerequisite is a tool call, not proof of a correction. The synthetic driver did not even share that clearing rule. Its inline model-facing strings and arbitrary turn threshold also violated the established prompt and judgment boundaries. The checkpoint tests largely asserted locally assigned state rather than executing either driver; they did not establish persistence or safe retirement.

## Ownership and history

`nudge_reason` is an offer slot owned by the driver, not durable transcript history. The original service implementation in `5996d0c0` already appended its rendered note and immediately cleared the slot. The modularity checkpoint `79df64c3` introduced the current stalled-work state surface; `stalledwork.acknowledge` moves the exact pending object to `last_delivered`. That record acknowledges delivery, not successful implementation or freshness. `10bc361d` made scheduled completion gaps reach the current synthetic coder turn rather than waiting in that slot. None of these transitions establishes that the coder finished the requested correction.

The harness receives the coder reply, not the internally appended input note. Unless retained separately, a later request reconstructed from harness history therefore loses the note. This is independent of compaction. In the selected run017 boundary, the admitted directive reached 0103, the coder inspected a baseline, and 0104 no longer carried it. Selected run019 demonstrates the contrasting path: immediate edits leave public tool history that carries the work forward. These selected boundaries are not complete walks of all runs and do not show that inspection itself was wasteful.

## Offline evaluation

`tests/test_delivered_guidance_persists_across_prerequisite_inspection.py` now drives the real synthetic driver through two final HTTP serializations with fake transport and a returned read result. It exercises both the ordinary round trip and an explicitly historical record retained in incoming transcript history. No workspace command or provider inference runs.

Results: the fresh note appears exactly once; its transient slot empties; the next request lacks that active note; an explicitly retained historical record survives the same read round trip; the original task remains present and the task is not marked done. This establishes that the existing preparation path can carry historical context, not that an automatic replay policy is safe. Both cases fail against the checkpoint runtime because it duplicates the fresh note immediately, and pass after removal. The focused driver and stalled-work binding suite passed 96 tests. The complete offline suite passed 10,826 tests, with 217 skipped and 4,432 subtests passed. The runtime file is byte-identical to `9c80c29e`; no service restart is needed because the rejected checkpoint was never deployed.

## Why not replace it with unconditional historical replay?

Calling an old directive historical avoids claiming that its findings remain current, but does not make its instructions harmless. The record can contain concrete commands, old failure findings or a requirement-relaxing recommendation. A last-note slot silently loses earlier distinct guidance; an accumulating record needs truthful ordering and ordinary reducibility. A pre-call assignment cannot establish delivery after transport failure. A returned tool call establishes neither completion nor supersession. Read-versus-write classification also cannot decide semantic completion.

The evidence supports removing the checkpoint's false custody/compliance claims now. It does not support its retirement rule or an alternative automatic replay rule. A future implementation needs an actual delivery receipt, task-scoped historical provenance, ordinary floor reduction, and explicit replacement/supersession semantics without claiming that arbitrary activity settles guidance. This question remains open rather than being hidden behind a timer. Planner remains OFF; the stopped campaign and historical scores are unchanged.
