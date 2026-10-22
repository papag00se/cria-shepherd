# Walk investigator

Main/Sol uses [stage 3](walk-sol.md) to challenge Luna's drafts against original reasoning and context. Check competing passages, prior commitments and chronology. Keep observations separate from inferred influence, and proposals separate from actions. Put corrections in the synthesis; leave initial drafts unchanged. No fix candidate is a valid result.

## Original-guidance continuity

When investigating a possible cria defect:

- **Follow the thinking, not a bug checklist.** Look for misleading context and missed opportunities. Cite the recorded thought/action that supports the suspected influence; suspicious wording alone is not evidence.
- **Check recent fixes for harm as well as benefit.** Which assist was missing, silent, mistimed or wrong? Trace context → thought/action → consequence. If A led to B and C broke, consider correcting A before guarding B or C; removing a harmful intervention may be the right fix.
- **Respect prior intent and shared owners.** Read related code and fix history. Resolve conflicting protections at their shared cause; do not undo earlier fixes or duplicate detection, steering or probes.
- **Apply the [design principles](principles.md).** Ground claims in authoritative facts and delivery at the wire. Keep corrections additive/regression-only and independent of task, language, model and harness. Unexplained thinking is a question, not a defect verdict or model blame.
- **Challenge the proposed fix.** Independently verify subagent claims. Test false positives, false negatives and legitimate nearby cases. Validate at the actual intervention boundary with captured calls and relevant model interactions, repeating as variance warrants. Tests alone do not prove effectiveness; separately unauthorized inference remains outstanding.

For each grounded candidate, state the incident and calls, upstream owner, falsifiable explanation, smallest correction, why existing assists missed it, possible harm, and validation including a fails-before/passes-after regression.

These principles carry forward the original guidance at `69c3e9de`, `ab14571a`, `e5ccbcb8`, `381c3b04` and `01dfec38`; those historical protocols are not alternate instructions.

## Implementation

Walking authorizes no code, configuration, campaign or live changes. Once a candidate and implementation are authorized, follow normal coding, regression, review, commit and deployment policy, including focused tests and `python -m pytest`. Preserve necessary evidence under existing retention policy, without extra approval chains or permanent scratch archives.
