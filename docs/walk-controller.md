# Walk controller

Route through [the official entrypoint](walk-prompt.md); do not append this operational guidance to analytical prompts.

## Prepare and deliver

Select the calls/range explicitly. A full-run walk covers all available recorded reasoning in call order; a selected-call walk must not claim full-run coverage. Deliver each selected reasoning unit completely, including available partial reasoning from aborted calls; label missing recordings. Use lossless reversible representation if needed, not clipping or summaries. Size assignments before launch so the reasoning fits; record actual compactions/aborts rather than quietly claiming uninterrupted reading.

Freeze source identity, extraction provenance and source/prompt hashes before reading, then freeze original thought and mapping outputs separately, including errors. One working directory and a small assignment record suffice. Stage 1 withholds context, current response actions and later outcomes. After thoughts are frozen, stage 2 makes the entire same-invocation context searchable, without requiring every context word to be read. Exact references must resolve to originals. `suite/walk.py` remains a lossless preparation/navigation utility, not a reader protocol: its mixed prompt/response chunks must NOT be given as stage-1 reasoning-only input. Reversible COPY references can reconstruct context; `--full-prompts` avoids reference reuse. No fullhex, co-retention or atomic audit gate is required.

Verify bounded delivery/access, not semantic perfection. Preserve initial outputs unchanged; at most one correction of an actual missing delivery per case, recorded separately. Do not ask Luna to repair interpretations or iterate toward a ledger score. If access remains blocked, report the incomplete case. Sol corrects interpretations in synthesis, not by editing reader originals.

Later reveals must be dated and labeled separately: distinguish what was available at the selected call from later source versions, actions, results or investigator discoveries. Never silently backfill an earlier belief with future evidence.

## Synthesize and report

Pass originals and initial outputs to Sol under [investigator guidance](walk-investigator.md). Successful drafting plus Sol challenge is the process, not unattended Luna accuracy. The offline held-out experiment supports that bounded use, not equal-difficulty or cost superiority.

If reporting full-workflow cost, include Controller/Main and Luna preparation, reading, challenge and reporting within explicit boundaries. Deduplicate native response IDs; cumulative totals cross-check rather than add. Normalize Pi usage: cached input is a subset of input and reasoning output a subset of output; identify other cache conventions before combining. Include actual compactions and aborted calls, unknown consumption and excluded tails; reader-only usage must be labeled reader-only. Use native records, not a new accounting framework.

Preserve actual model-call logs and necessary repository regressions. Existing retention policy governs settled scratch; this process does not authorize historical external-data cleanup.
