# Analysis

Main/Sol uses this document after the Luna stages in [Walking](walk-prompt.md). Do not give it to Luna. Check competing passages, prior commitments and chronology. Keep observations separate from inferred influence, and proposals separate from actions. Put corrections in the synthesis; leave initial drafts unchanged. No fix candidate is a valid result.

## Challenge the walk

The existing short stage-3 instruction is preserved here instead of in a separate prompt file:

```text
# 3. Sol: challenge and summarize

Recheck the uncertain connections. Search for alternative wording and passages that could challenge the interpretation.

Then summarize:
- What occupied the coder’s attention?
- How did its thinking change?
- What context helps explain those changes?
- What remains unexplained?

Keep observations separate from guesses about influence. If you still find no connection, say where you looked rather than claiming none exists.
```

## Original analysis directives

These are the original directives from `f36e880ade42519c113fa5c0dcbeed80662284c6:docs/walk-prompt.md`, moved without paraphrasing. The walking directives live in Walking. The principles reference below resolves to [docs/principles.md](principles.md).

We're also looking for evidence that the recent fixes are behaving as expected or causing more issues.

Suggestions from subagents are signals and evidence only. Never take them at their word. Double check yourself.

`A` leads to `B` which causes `C` to break. Don't jump to fix `B`. `A` led to `B`, so you should look at `A` to see if you can get `B` in a better state so `C` doesn't break. That is a pattern that I'd like you to keep in mind whenever looking at fixes.

Suggest fixes that comply with the following:

1. Candidate fixes should comply with @docs/principles.md
1. Check those fixes against commit history to ensure we aren't reintroducing previous footguns.
1. Run the fixes through adversarial reasoning.
1. Replay the fixes against the model using real call logs to see if the fix is effective.
1. Do not duplicate similar assist/fix logic. This is similar to the A, B, C thread above. Be aware of other similar assists/fixes in cria, so you can adjust or build on them instead of duplicating assist logic - causing trips and footguns.

## Evaluate candidates

- **Follow the thinking, not a bug checklist.** Look for misleading context and missed opportunities. Cite the recorded thought/action that supports the suspected influence; suspicious wording alone is not evidence.
- **Respect prior intent and shared owners.** Read related code and fix history. Resolve conflicting protections at their shared cause; do not undo earlier fixes or duplicate detection, steering or probes.
- **Apply the design principles.** Ground claims in authoritative facts and delivery at the wire. Keep corrections additive/regression-only and independent of task, language, model and harness. Unexplained thinking is a question, not a defect verdict or model blame.
- **Challenge the proposed fix.** Test false positives, false negatives and legitimate nearby cases. Validate at the actual intervention boundary with captured calls and relevant model interactions, repeating as variance warrants. Tests alone do not prove effectiveness; separately unauthorized inference remains outstanding. The original replay directive above does not itself grant authorization to launch inference.

For each grounded candidate, state the incident and calls, upstream owner, falsifiable explanation, smallest correction, why existing assists missed it, possible harm, and validation including a fails-before/passes-after regression.

## Functional diagnosis

Main/Sol must finish the existing synthesis with a short diagnostic argument for the principal unexplained derailment, not just corrections to reader claims or the final task's defects. Use original calls and existing event/delivery indexes; add no registry or exhaustive ledger.

State the concrete boundary, the relevant assistance actually delivered (or the existing owner's silence/ineligibility), and the observed continuation. Separate what the author received, generated, and actually delivered. Examine assistance even when the coder never quotes it; adjacency alone does not establish influence. Identify a supported correction, a disproved explanation, or an unresolved causal question. If unresolved, name the existing owner and one next source question/test, or why it is deliberately deferred. Do not invent an assist role or cause when the evidence cannot settle it.

A legitimate inspection does not establish adequate assistance, and an inspection instead of an immediate edit does not establish failure. Check the received context's actual visibility and freshness before calling a read redundant. Abort counts/time and landed writes alone establish neither harmful reasoning loss nor useful recovery; inspect the relevant traces and continuation. Evaluate an intervention over the continuation needed to distinguish the proposed cause, not automatically just its first tool call.

**No patch supported; functional diagnosis unresolved** is a valid bounded settlement, not a completed causal explanation. Preserve the concrete next question under its existing owner rather than merely copying an OPEN label. Reruns and normal scratch closure need not wait for every cause to be solved. No fix quota, additional approval gate, universal-benefit proof or weaker evidence/freshness standard follows.

## Implementation

Walking authorizes no code, configuration, campaign or live changes. Once a candidate and implementation are authorized, follow normal coding, regression, review, commit and deployment policy, including focused tests and `python -m pytest`. Preserve necessary evidence under existing retention policy, without extra approval chains or permanent scratch archives.
