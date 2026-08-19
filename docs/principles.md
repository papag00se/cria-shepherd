# cria — design principles

These rules come from failures traced to exact causes. Evidence lives in [`audits/`](audits/) and memory; mechanisms in [`heuristic-assists.md`](heuristic-assists.md).

**Precedence:** ground truth over judgment; never destroy information the model relies on; fail safe. Convenience never overrides these.

**Charter:** help a small local model succeed at real agentic coding by shaping its context, without creating new ways to mislead it.

---

## A. Stream interventions

### 1. Every assist can become a footgun
A weak model cannot distinguish cria injections from its own reasoning. Every injected string is another possible falsehood. Before adding an assist, ask how it can mislead. Default to removal; additions require strong justification.

**An assist outlives its cause.** Each one was built for a defect that was real at the time. Fix the defect upstream — better context shaping, a truer prompt, a floor that catches it earlier — and the assist keeps firing against a world that no longer needs it, where its only remaining effect is to mislead. So an assist is re-measured against the system it runs in NOW, not the one it was born in. The test is not "was this justified when written" but "does removing it today cost anything". Measure both arms before answering: an assist that fires just as often in the runs that succeed is not what is making them succeed.

### 2. Interventions are additive, regression-only, and cria never AUTHORS work
Intervene only to prevent existing progress from regressing. Deletion, redirection, and blocking a first attempt can trap loops.

Additive does not mean safe: cria must not write plans, actions, or code for the coder. Everything cria injects remains subject to re-derivation; nothing becomes an immutable mandate. Surface facts and steer; let the coder act.

### 3. Silence over noise
Inject only high-confidence, actionable information. Inject nothing on a passing check. Never attach speculative warnings to green results. State a fact or stay silent.

### 4. No fallbacks or mitigations; fix upstream
Do not hide wrong behavior behind a workaround. Fix the cause.

Do not place deterministic fallback logic behind a reasoner. If the trusted reasoner cannot answer, inject nothing.

---

## B. Never destroy information the model relies on

### 5. cria never truncates
Never blindly clip bytes, characters, lines, prompts, evidence, or model output. Window fitting belongs only at the lossless-first context floor.

Allowed:
- **De-duplication:** repeated content may appear once with a pointer to the original.
- **Model-made summary/selection:** a model read the full source and the result is explicitly labeled as a summary.

Everything else that shortens model-visible content is truncation, including head/tail limits, per-line caps, character budgets, and disclosed elisions.

Consequences:
- cria framing does not consume the evidence budget.
- Disclosed truncation is still truncation.
- If cria holds the authoritative object, use it directly instead of shortening a re-rendered copy.

### 5b. cria never states a FALSE FACT about the world
Every factual statement cria makes must be true now and backed by a live check.

Use the authoritative source:
- filesystem for file existence,
- parsed document for document contents,
- tool menu for available tools.

Do not turn internal limits, remembered flags, partial matches, or assumptions into world facts.

Refusals must name something the coder can actually change. Validate that a command is well-formed before judging it.

Preserve provenance:
- tool output is ground truth,
- model summaries are claims,
- never label both the same way.

Saying less is allowed. Saying something the world would contradict is not.

### 6. Never cap output for latency
Do not shorten output for speed. Slow hardware and long waits are acceptable.

Keep answer-window sizing separate from runaway protection. Handle runaways with streaming detection, timeout, and context limits, never a short hard output cap that can cut a file write mid-content.

### 7. cria never pollutes the user's workspace
cria writes only inside its own directory. Workspace artifacts become visible to the coder and contaminate its context.

File access remains bounded to the workspace even under `--yolo`. This is a weak-model backstop, not a security sandbox.

---

## C. Ground truth over judgment

### 8. Deterministic code gathers facts; a reasoner judges
Detectors decide **when** to ask and gather objective evidence. A reasoner decides **what** that evidence means.

If a lexical rule needs tuned thresholds or exception lists, semantic judgment has leaked into deterministic code. Ask the reasoner instead.

Judge prompts must prevent the model from doing the work:
- state that it is a judge,
- restrict its tools,
- forbid implementation thinking.

When a judgment is wrong, inspect the reasoning first. Losing a correct answer and never finding it are different failures.

### 9. Don't fear an extra model call that prevents churn
Use a reasoner whenever it can ground the next action, including more than once within a step. Optimize total model calls, not reasoner calls.

Use one-shot guards so an unhelpful call does not repeat.

Semantic questions belong to reasoners, not keyword lists or proximity windows.

### 10. Verify by doing, not by reading
When possible, obtain ground truth through execution instead of trusting model claims. Exit 0 and self-reports do not prove behavior.

cria owns no executor; it borrows the harness shell.

### 11. Files alone are NEVER signal
Read current disk state, not stale transcript state.

Trigger reasoning on evidence such as repeated no-ops or dirty lint results, not merely because files exist. A clean floor should produce no intervention.

### 11b. A mechanism must REACH what it is asked about, or abstain
Before trusting a mechanism, verify that it can observe the thing it is judging.

If its reach is insufficient, it must say it cannot answer. Never convert lack of visibility into "nothing found" or "done."

Examples:
- workspace readers cannot judge third-party source,
- unparsed documents cannot support "no match",
- code that exits before checking declared runners cannot report "no entry point."

Any positive conclusion that the mechanism could not have observed is invalid.

### 12. Surface every metric from the authoritative EVENT
Derive metrics from structured events: completion records, intervention sites, exit codes, and tool arguments.

Do not reconstruct metrics from final prose or English-pattern matching.

### 23b. READ IT — a count is not a reading, and a match is not a meaning
Before making claims about model behavior, read at least one counted example end to end.

Regex counts show string occurrence, not behavior. Do not replace reading with `grep -c`, aggregate scoring, or duplicate checks that cria already owns.

A **WALK** means reading every call in a run from first to last: the full prompt cria sent and the full reasoning returned. Search, sampling, and statistics are not a WALK.

---

## D. Fail safe

### 13. Fail closed on completion; fail open only toward "keep working"
An undecidable completion judgment means **not done**.

A failed judge must never remove real results or produce a false success. Fail open only toward continuing work or restoring the ability to work.

### 14. cria must NEVER end a session by handing back to a human
Do not escalate to a human, stronger model, or declared capability ceiling.

A cria turn without a tool call is interpreted as completion, so a red session must continue driving. Reintroduce a terminator only with explicit operator permission.

### 15. Measure prevalence before building a heuristic
Measure a suspected pattern across real captures before building a detector. One replayed pathological event is not evidence of a systemic problem.

### 16. Assume cria caused it until proven otherwise
Before blaming the model:
1. read what the model received,
2. read what it reasoned,
3. compare that context with disk state,
4. run the real tool.

Do not build machinery to compensate for a failure cria itself introduced.

---

## E. Stay invisible and agnostic

### 17. The model never sees the literal token "cria"
Use `⟦ctx:…⟧` for model-facing markers. Strip human-facing `⟦cria⟧` notes before the model re-reads them.

Internal tokens and harness idioms can be copied into executable commands, so prevent leakage anywhere cria composes content the model may read or run.

### 18. Harness-agnostic
Do not depend on, prune, or specialize for harness configuration or rendering.

Match tools by family, not literal name. Speak the wire protocol on both sides so fixes remain inside cria and apply across harnesses.

### 19. Cross-model resilience is the mission — a model that breaks is a requirement
Do not optimize around one model or recommend a preferred model.

Read reasoning from dedicated channels or inline content, and match dialects broadly. Failures on different small models reveal requirements.

### 20. Be task and language agnostic
Do not key prompts, detectors, matchers, or remedies to one task's vocabulary, language, model dialect, or harness tool names.

Run the three-lens audit: **LANG / MODEL / HARNESS**.

### 21. A weak-model sentinel must be a POSITIVE token
A model-emitted veto must use a positive token such as `ON_TRACK`, never a negated token such as `NOT_STUCK`. Negation can invert the model's own conclusion and cancel a needed rescue.

---

## F. Hardened conventions

### 22. Model-facing strings live in prompt files, never inline f-strings
Put every model-visible string in `cria/prompts/*.txt` so prompts can change without code changes.

### 23. Architectural boundaries
Defined fully under `## Principle:` in [`shephard.md`](shephard.md).

- **Lower every MODEL-FACING tool to `shell`.** Rich tools become the common harness primitive and are reconstructed inbound as their original tool.
- **cria may execute for its own needs.** Tests, syntax checks, linters, exec checks, read-only gathers, and cleanup may run on cria's side. Model-facing execution still goes through the harness.
- **One owner for workspace-boundary checks.** Keep lexical checks for not-yet-existing write targets separate from resolved-path checks for paths cria will act on.
- **Own no rendering.** Every exposed tool must reduce to a primitive the harness can execute and display.
- **Guard state is session-scoped.** Reset guard memory on each user turn; never leak it across sessions, sub-agents, or forks.

### 24. An invariant that must hold on the WIRE belongs at the wire
If a property must be true of the serialized model body, enforce it at the final pre-serialization boundary.

Examples:
- role alternation,
- no orphan tool messages,
- no malformed historical tool calls.

Do not enforce wire invariants independently at call sites. Carry internal intent to the wire, apply it there, strip the hint, and keep the transform opt-in so unaffected models receive byte-identical bodies.

Fix the path that produced the incident. Captured bodies record their phase; identify the actual failing path before changing code, tests, comments, or audits.
---

*Rule numbers are cited throughout the code and tests and never change.*