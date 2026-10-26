# Analysis

Use an operator-selected model after [Walking](walk-prompt.md). Do not send this document to Luna.

Check original calls, competing passages, chronology and what actually reached the coder. Separate observations from inferred influence, and proposals from actions. Leave Luna's drafts unchanged.

Summarize what occupied the coder's attention, how its thinking changed, what context explains that, and what remains unexplained. For unfound connections, say where you looked.

## Original directives — f36e880a

We're also looking for evidence that the recent fixes are behaving as expected or causing more issues.

Suggestions from subagents are signals and evidence only. Never take them at their word. Double check yourself.

`A` leads to `B` which causes `C` to break. Don't jump to fix `B`. `A` led to `B`, so you should look at `A` to see if you can get `B` in a better state so `C` doesn't break. That is a pattern that I'd like you to keep in mind whenever looking at fixes.

Suggest fixes that comply with the following:

1. Candidate fixes should comply with @docs/principles.md
1. Check those fixes against commit history to ensure we aren't reintroducing previous footguns.
1. Run the fixes through adversarial reasoning.
1. Replay the fixes against the model using real call logs to see if the fix is effective.
1. Do not duplicate similar assist/fix logic. This is similar to the A, B, C thread above. Be aware of other similar assists/fixes in cria, so you can adjust or build on them instead of duplicating assist logic - causing trips and footguns.

## Functional diagnosis

Explain the principal derailment: context → thinking/action → consequence. Trace delivered assistance or the existing owner's silence. Suspicious wording, adjacency, inspection, abort counts and landed writes alone do not establish cause or effective recovery; check visibility, freshness and the relevant continuation.

For each supported fix, name the calls, upstream owner, falsifiable explanation, smallest correction, missed assistance, possible harm and validation. Test legitimate nearby cases and false positives/negatives; require a fails-before/passes-after regression. Apply the [design principles](principles.md), not model blame.

Finding no supported fix is a valid result. If the cause remains unresolved, name its owner and one next source question or test; do not call it explained. This adds no fix quota, approval chain or closure gate.

Implementation, model replays and live changes require separate authorization. Follow normal test, review and [retention policy](../suite/README.md#closed-walk-and-fix-retention).
