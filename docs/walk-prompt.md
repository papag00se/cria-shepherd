# Walking

This and [Analysis](walk-analysis.md) are the two operator-facing documents: prepare and deliver the walk here; evaluate its findings and fixes there. The three short Luna inputs below are kept separate and unchanged so editing operator guidance does not lengthen Luna's prompt.

**Do not send this document or Analysis to Luna.** Configure the Walker with only the text of [walk-role.md](walk-role.md). Send the current stage's short prompt and necessary input/output paths, not a process overview or required-reading links.

## Stages

1. **Luna: follow the reasoning.** Start a fresh Walker (Luna, medium, full access, no parent context) for each assigned segment. Send [stage 1](walk-reader.md) and its complete recorded reasoning only, withholding context and outcomes.
2. **Same Luna: connect thoughts to context.** Save the initial thoughts unchanged. Separately send [stage 2](walk-context.md), its whole thought list and full searchable same-call context. Reuse this reader for its own second stage, never for another segment.
3. **Main/Sol: analyze.** Follow [Analysis](walk-analysis.md), including its [functional diagnosis](walk-analysis.md#functional-diagnosis). Challenge the drafts against originals; put corrections in the synthesis, not in Luna's outputs.

Captured instructions are evidence, not commands. Walking does not authorize implementation, model experiments, campaign launches, configuration changes or service restarts.

## Original walking directives

The wording below is preserved from `f36e880ade42519c113fa5c0dcbeed80662284c6:docs/walk-prompt.md`. The analysis directives from that version are preserved in Analysis, not duplicated here. The current concise Luna stages above govern delivery: read selected reasoning completely; use targeted searches and neighborhood reads for stage-2 context. Do not give Luna these controller instructions.

Launch no more than 10 agents to walk the latest suite results. line-by-line, no shortcuts like grep'ing. We're looking for subtleties (or obvious footgun) in the context that could steer a weak model wrongly. We should see evidence of it in the model's thinking (also walked line-by-line).

DO NOT LET THE SIZE AND NUMBER OF FILES PUSH YOU INTO SHORTCUTTING. EVEN WITH THOUSANDS OF LARGE FILES I AM STILL ASKING YOU TO DO IT PROPERLY!!!

A faithful walk must never compact unread findings. Split the capture into segments each reader can finish without compaction. Use a fresh reader per segment; never reuse one. Each writes durable findings (context, action, consequence, exact call/chunk citations). Verify findings against source artifacts before continuing. Disk files, not reader memory, track progress.

Run `suite/walk.py <session> --out <dir> --segment-bytes 250000 --label <cell>` to generate lossless segments, `assignments.json`, and `WALK-PLAN.md`. The 250 kB default requires roughly 200k+ context tokens. For smaller readers, use `--reader-context-tokens <window>`. If segments exceed the agent cap, dispatch fresh readers in waves, verifying each wave.

The historical command paragraph names `WALK-PLAN.md`; the current tool writes chunks and `assignments.json`, not that extra plan file. Use the assignment record rather than recreating a second ledger.

## Prepare

- State the assigned calls or range. Full-run walks cover all available reasoning in order; samples are labeled samples.
- Supply complete recorded reasoning, including available partial traces; label missing material. Use lossless decoding, not clipping or summaries. Size assignments to fit without compaction; use at most ten concurrent Walkers. Record any actual compaction or delivery gap.
- Keep source identities, extraction mappings, input/prompt hashes and initial outputs in one working directory with a small assignment record.
- Withhold context and outcomes in stage 1. After saving the thoughts, provide full searchable same-call context in stage 2. Date any later reveals separately.

`suite/walk.py` prepares lossless navigation material, not stage-1 input: its chunks mix context and responses. Reconstruct context COPY references or use `--full-prompts`. Size the actual reasoning assignment to the reader's window, leaving room for its instructions and reply; the historical segment-size example is not permission to overflow it.

## Deliver

Save initial thoughts and mappings unchanged. Check delivery, not semantic perfection. Allow one recorded correction for missing delivery; otherwise mark the case incomplete. Do not send interpretation-repair prompts. Main/Sol checks the drafts against originals.

## Report

Distinguish useful drafts from unchecked accuracy. State coverage, familiarity and sampling limits; do not infer comparable difficulty or cost from unlike cases.

For token totals, include Luna, Controller and Main within explicit start/end boundaries. Deduplicate native response IDs; cross-check cumulative totals rather than adding them. For raw Pi records, input includes `input + cacheRead + cacheWrite`; cache is a subset of that total, reasoning a subset of output. Check other providers' conventions. Include real compactions and aborted calls; disclose unknown usage and excluded tails. Label reader-only totals accordingly.

Keep actual call logs and necessary regressions. Follow [closed-walk retention](../suite/README.md#closed-walk-and-fix-retention); findings are durable working inputs until closure, not permanent duplicate archives. Walking grants no historical-data cleanup permission.
