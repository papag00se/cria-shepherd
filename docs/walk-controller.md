# Walk controller

Follow the [three-stage process](walk-prompt.md). Handle these mechanics outside the analytical prompts. The Walker role uses only [walk-role.md](walk-role.md); it must not require this document, the process overview or investigator guidance. Send the current stage's prompt text with input/output paths, nothing more.

## Prepare

- State the assigned calls or range. Full-run walks cover all available reasoning in order; samples are labeled samples.
- Supply complete recorded reasoning, including available partial traces; label missing material. Use lossless decoding, not clipping or summaries. Size assignments to fit without compaction; use at most ten concurrent Walkers. Record any actual compaction or delivery gap.
- Keep source identities, extraction mappings, input/prompt hashes and initial outputs in one working directory with a small assignment record.
- Withhold context and outcomes in stage 1. After saving the thoughts, provide full searchable same-call context in stage 2. Date any later reveals separately.

`suite/walk.py` prepares lossless navigation material, not stage-1 input: its chunks mix context and responses. Reconstruct context COPY references or use `--full-prompts`.

## Deliver

Save initial thoughts and mappings unchanged. Check delivery, not semantic perfection. Allow one recorded correction for missing delivery; otherwise mark the case incomplete. Do not send interpretation-repair prompts. Main/Sol checks the drafts against originals.

## Report

Distinguish useful drafts from unchecked accuracy. State coverage, familiarity and sampling limits; do not infer comparable difficulty or cost from unlike cases.

For token totals, include Luna, Controller and Main within explicit start/end boundaries. Deduplicate native response IDs; cross-check cumulative totals rather than adding them. For raw Pi records, input includes `input + cacheRead + cacheWrite`; cache is a subset of that total, reasoning a subset of output. Check other providers' conventions. Include real compactions and aborted calls; disclose unknown usage and excluded tails. Label reader-only totals accordingly.

Keep actual call logs and necessary regressions. Follow existing scratch-retention policy; walking grants no historical-data cleanup permission.
