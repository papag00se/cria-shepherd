# cria — design principles (the doctrine)

Rules paid for by derailed sessions traced to the exact bytes. Each states what to do and what makes it wrong to do otherwise; the runs behind them are in [`audits/`](audits/) and memory, and the mechanisms in [`heuristic-assists.md`](heuristic-assists.md).

**Precedence.** *Ground truth over judgment*, *never destroy information the model relies on*, *fail safe*. Convenience never overrides those three.

**The charter.** A small local model succeeds at real agentic coding on its own, and cria gets it there by shaping the context around it — **without introducing a new way to lie to the model**.

---

## A. What cria may do to the stream

### 1. Every assist can become a footgun
A weak model cannot tell a cria injection from its own reasoning, so a wrong nudge is indistinguishable from a right one and every injected string is a new way to be wrong. Before adding one, ask how it becomes a footgun, and default to not adding it. The bar to ADD is high; the safe direction is REMOVE.

### 2. Interventions are additive and regression-only, and cria never AUTHORS work
A guard may act only when something already working would get worse. Deletion and redirection are the dangerous shapes, and a guard that blocks the first attempt at something can trap the loop forever. Additive is necessary but not sufficient: a prepended plan step is additive and still forbidden, because cria shapes context and does not write the coder's work. Nothing cria writes is exempt from the living re-derivation — a step held out of it is an inescapable mandate — and cria never substitutes its own action for the coder's: surface the fact, steer, and let the coder act.

### 3. Silence over noise
Speak only on a high-confidence, actionable signal. On a passing check, inject nothing: a hedge attached to a green result is unactionable doubt, and a weak model resolves it by breaking working code. State a fact or say nothing.

### 4. No fallbacks, no mitigations — fix upstream
A band-aid over wrong behaviour is forbidden; find the cause. A deterministic fallback behind a reasoner call is the same sin in disguise — it hands the judgment to fuzzy code precisely when the reasoner, which is the thing you trust, would have done better. When the reasoner cannot answer, take the safe null: inject nothing.

---

## B. Never destroy information the model relies on

### 5. cria never truncates
A blind byte, character or line clip is a lie the reader cannot detect, and it does not matter whose prompt it is — the coder's, a judge's, a steer author's. Window-fitting belongs to the one lossless-first place, the context floor.

Two exceptions. **De-duplication**: the same content twice is redundancy, not information, so say it once and point at where it already sits. **A model-made summary or selection**: something read the whole thing and chose, and the result is labelled a summary so no one mistakes it for the source.

Everything else that shortens what a model will read is truncation however it is spelled — a head-and-tail bound, a per-line cap, a character budget, a disclosed elision. Three consequences follow. cria's own framing is never charged to the evidence's budget, because a preamble that eats the head leaves the reader nothing but cria talking. A cut that is disclosed is still a cut. And when cria already holds the authoritative object, it fills the slot from that rather than re-rendering a copy and shortening the copy.

### 5b. cria never states a FALSE FACT about the world
Everything cria says in its own voice — a tool's answer, a refusal, a pointer, a ledger — must be true of the world now, and cria must be able to name the live check behind it. A claim resting on a remembered flag, a partial matcher, or a bound cria imposed on itself is a claim about cria, not the world; when the two can differ, ask the world: the filesystem for whether a file exists, the parsed document for whether a term is in it, the tool menu for whether a name is a tool. A sentence in the indicative with no check behind it — "it was saved to X", "no match", "you already fetched this" — is the shape to hunt.

A refusal must name something the coder can change; one it cannot act on is a false fact about its own environment, and the model will generalise from it and stop investigating. Judge whether a command is even well-formed before judging its contents.

Provenance is part of the fact: a model's own words are never labelled ground truth. Tool output is ground truth, a summary is a claim, and the two must not arrive under the same header. Saying less is always allowed when it is disclosed; asserting what the world would contradict is not.

### 6. Never cap output for latency
cria targets slow boxes where long waits are accepted, so output is never shortened for speed. The window kept free for the answer is a separate setting from the runaway backstop, and runaways are caught by the streaming rumination detector, the timeout and the context size — never by a short hard cap, which truncates a file write mid-content and turns rule 5 on the model's own output.

### 7. cria never pollutes the user's workspace
cria writes only inside its own directory. Anything it leaves in the workspace is found by the coder's `ls`, read, and imitated, so cria's scaffolding becomes the model's context. File access stays bounded to the workspace even under `--yolo` — a backstop for a weak model, not a security sandbox.

---

## C. Ground truth over judgment

### 8. Deterministic code gathers facts; a reasoner judges
Cheap deterministic detectors decide *when* and assemble the objective evidence; a reasoner decides *what*, grounded on that evidence and never on prose intent. Every steer detector is a trigger feeding one reasoned author.

Tuning a lexical rule is the giveaway. Trading false positives against misses, or writing the exception list, IS the judgment — performed at authoring time against imagined sentences instead of at runtime against the real one. The rule that needs an exception list is the rule that should have been a question.

A judge prompt must fence the model out of doing the work. A prompt that describes the task in the imperative invites a weak model to perform it, and a model that starts building stops comparing — it will find the gap, design the fix, and then answer that nothing is missing. State that it is a judge, that it has no tools, and that it must not think about how anything would be built. When a judgment comes back wrong, read the model's reasoning before concluding it cannot do the job: "it lost the answer it had already found" needs a different fix from "it never found it".

### 9. Don't fear an extra model call that prevents churn
When a deliberate reasoner call would ground the next action, make it — mid-loop, or twice in one step. Optimise for fewer total model calls, not fewer reasoner calls: one purposeful call is small against the coder churn it prevents. The bound is the one-shot flag — a call that does not move the plan must not repeat.

A single question is a first-class tool and the right answer to anything a regex is being asked to decide semantically. When code reaches for a keyword list or a proximity window to settle a question of meaning, the information it needs is usually not in the sentence at all, and no window over the sentence recovers it.

### 10. Verify by doing, not by reading
Where cria can act, it takes ground truth on its own terms — its command, its output format — rather than parsing the model's claim, because exit 0 is not proof and a self-report is the least trustworthy signal available. cria owns no executors: it borrows the harness's shell.

### 11. Files alone are NEVER signal
Read disk now, never the transcript's stale view of it, and gate the reasoner call on a repeated no-op or a dirty lint digest. Calling the reasoner because files exist makes it invent objections; a clean floor returns nothing, deliberately.

### 11b. A mechanism must REACH what it is asked about, or abstain
Before trusting a check, a probe or a research step, establish what it can actually see. One whose reach does not cover the claim it must settle has to say it cannot answer — never "nothing found", never "done". Silent under-reach is indistinguishable from a clean result and worse than having no mechanism, because it closes the question. A workspace-scoped reader cannot settle anything about a third-party library; a matcher that never parsed the document cannot report no match; a branch that returns before consulting the project's declared runners cannot report no entry point. Any positive result a mechanism had no way to obtain is this defect.

### 12. Surface every metric from the authoritative EVENT
Derive counts and signals from the structured event — the completion record, the intervention emit sites, exit codes, tool-call arguments — never by re-counting a finalised response or matching an English needle in prose. A re-count drifts from the event and reports the wrong number in silence, and keying on arguments rather than text also survives plumbing jitter like `2>&1` or `| head`.

### 23b. READ IT — a count is not a reading, and a match is not a meaning
Before reporting a number about model behaviour, open one of the things counted and read it end to end; aggregate after reading, never instead. A regex over a corpus reports how often a string occurs, which is not what happened and is frequently its opposite. Writing a percentage without having opened an example, reaching for `grep -c` on model output, or re-implementing in a scorer a check cria already owns are all the same error.

Reading means the bytes passed in front of you, at the speed a person reads. Skimming a corpus and calling it read produces a confidence that is more dangerous than the error it hides.

**A WALK is reading every call in a run from first to last** — the whole prompt cria sent and the whole reasoning it produced. Not a search through them, not a sample of them, not a statistic over them. This distinction decides whether a failure gets blamed on the model or traced to the context cria built.

---

## D. Fail safe

### 13. Fail closed on completion; fail open only toward "keep working"
An undecidable judge means NOT done, and a judge that cannot judge must never strip real results. cria fails open only toward regaining the ability to work or continuing to drive, never toward a false "done" — an unparseable verdict read as success is the root of every early exit.

### 14. cria must NEVER end a session by handing back to a human
No human surfacing, no escalation to a stronger model, no declaring a ceiling. Any cria turn that ends without a tool call reads as "done" to the harness, so cria must not end a red session at all. Churn while trying beats bailing out. Re-add a terminator only with explicit operator permission.

### 15. Measure prevalence before building a heuristic
Base-rate the signal across real captures first. A pattern that looks systemic is often one pathological event replayed, and a detector built for a one-off is dead weight that can misfire on its own.

### 16. Assume cria caused it until proven otherwise
Read what the model actually received and what it actually reasoned; correlate what was sent against what is on disk, and run the real tool. Do that before building machinery to fix the model's apparent mistake, or the machinery ends up compensating for a footgun cria introduced.

---

## E. Stay invisible & stay agnostic

### 17. The model never sees the literal token "cria"
Model-facing markers use the `⟦ctx:…⟧` namespace, never the proper noun, which invites a weak model to reason about the mechanism instead of the code. Human-facing `⟦cria⟧` notes are stripped before the model re-reads.

A leaked internal token is not untidy, it is dangerous, because the model copies what it sees. An idiom lifted out of cria's own plumbing and pasted into the coder's commands carries cria's semantics with it — a capture wrapper that always exits clean will report success over a failed build. So the rule extends to any string the harness will EXECUTE, not just one it displays, and it is not satisfied by checking a handful of marker names: check for the token everywhere cria composes something the model can read or run.

### 18. Harness-agnostic
cria never depends on or prunes the harness's config, never shapes output for one renderer, and matches tools by family rather than literal name. It speaks the wire protocol on both sides, so a fix lands on cria's side and applies to every harness; a harness-specific fix breaks that contract.

### 19. Cross-model resilience is the mission — a model that breaks is a requirement
Never recommend the "best" model or bake behaviour to how one model surfaces its output. Read reasoning from the dedicated channel or from inlined content, and match dialect tokens broadly. The goal is resilience across many small models, not finding one that happens to work.

### 20. Be task and language agnostic
cria must work across the top languages, models and harnesses without knowing which it is on. No prompt, detector, matcher or remedy may key on one task's vocabulary, one model's dialect, or one harness's tool names — an overfit detector fails silently the moment any of the three changes, and silence is what makes it expensive. Run the three-lens audit (LANG / MODEL / HARNESS) as a repeatable practice.

### 21. A weak-model sentinel must be a POSITIVE token
A magic word the model emits to veto its own rescue must not be reachable by negating its own reasoning. `ON_TRACK`, never `NOT_STUCK`: a reasoner that concludes it is stuck will emit the negation and cancel the rescue it just justified.

---

## F. Conventions that hardened into rules

### 24. An invariant that must hold on the WIRE belongs at the wire
If a property must be true of the body the model receives — role alternation, no orphan tool message, no malformed historical tool call — enforce it at the last point before serialization, not at a call site. A transform that runs mid-pipeline is undone by anything appended downstream, and the next person to append will not know it exists. Ordering two lines at each call site is a band-aid per site. Carry the intent as an internal body hint, consume and strip it at the wire, and keep it opt-in so a model that does not need it ships a byte-identical body.

Fix the path that produced the incident, not the one that resembles it. Every captured body records its phase, so a census of which path actually made the failing calls takes one command — and skipping it produces a fix, a comment, a test and an audit entry that all confidently name the wrong path.

### 22. Model-facing strings live in prompt files, never inline f-strings
Every string the model reads goes in `cria/prompts/*.txt` so it is tunable without a code change.

### 23. Architectural boundaries
Stated in full as `## Principle:` in [`shephard.md`](shephard.md).

- **Lowers every MODEL-FACING tool to `shell`.** Rich tools become the one primitive every harness runs and are re-presented inbound as the original tool. Unconditional; it is what makes cria port anywhere.
- **But cria DOES execute, on its own side, for its own ends** — tests, the syntax floor, linters, the exec-check, read-only gathers, and deleting its own probe litter, which a probe composed for the harness cannot do for itself. The rule is not that cria never runs anything; it is that what the MODEL sees goes through the harness, and what CRIA needs may be run by cria. A boundary that has stopped being true is worse than a wide one, because audits measure against it.
- **One owner for "is this path inside the workspace".** The lexical answer must serve a write target that does not exist yet; the resolved answer must serve a path cria is about to act on. Both are correct for their own caller, which is exactly why they need distinct names — without them the site that most needs one picks neither.
- **Owns no rendering.** Every tool cria exposes must reduce to a primitive the harness can already run *and* display.
- **Guard state is session-scoped.** Anything a guard remembers resets on a new user turn and never bleeds between sessions, sub-agents or forks.

---

*Rule numbers are cited throughout the code and tests — they never change.*
