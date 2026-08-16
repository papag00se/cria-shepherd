# cria — design principles (the doctrine)

Rules paid for by derailed sessions traced to the exact bytes. Enough here to *apply* a rule and to not *misapply* it; the narratives are in [`audits/`](audits/) and memory, the mechanisms in [`heuristic-assists.md`](heuristic-assists.md).

**Precedence.** *Ground truth over judgment*, *never destroy information the model relies on*, *fail safe*. Convenience never overrides those three.

**The charter.** A small local model succeeds at real agentic coding on its own, and cria gets it there by shaping the context around it — **without introducing a new way to lie to the model**.

---

## A. What cria may do to the stream

### 1. Every assist can become a footgun
A weak model cannot tell a cria injection from its own reasoning, so a wrong nudge is indistinguishable from a right one. Ask "how does this become a footgun?" and default to **not** adding it. The bar to ADD is high; the safe direction is REMOVE.

### 2. Interventions are additive / regression-only
A guard may act only when something *already working* would get worse. DELETION and REDIRECTION are the dangerous classes, and one that blocks the *first* attempt can trap the loop forever.
**Corollary (its own rule).** ADDITIVE is necessary, not sufficient. A prepended plan step is additive and still forbidden: **cria does not AUTHOR work, it shapes context.** Nothing cria writes is exempt from the living re-derivation — one "pinned" step burned 485 calls — and cria never substitutes its own action for the coder's.

### 3. Silence over noise
Speak only on a high-confidence, actionable signal. When a check *passes*, inject nothing — never a "might still be wrong" hedge. Doubt on a passing check told a model to "fix" green tests ~20× in one session.

### 4. No fallbacks, no mitigations — fix upstream
A band-aid papering over wrong behaviour is forbidden. A deterministic fallback behind a reasoner call is the same sin: fuzzy code makes the judgment when the reasoner is the thing you trust, and it fires exactly when the reasoner would have done better. When the reasoner can't answer, take the **safe null**.

---

## B. Never destroy information the model relies on

### 5. cria never truncates
A blind byte/char/line clip is a lie the reader cannot detect, and it does not matter whose prompt it is — the coder's, a judge's, a steer author's. All window-fitting goes to the one lossless-first place, the context floor.
**Two exceptions.**
- **De-duplication.** The same content twice is redundancy, not information: say it once, or point at where it already sits.
- **A model-made summary or selection.** Something read the whole thing and chose. Label the result a summary so nobody mistakes it for the source.

Anything else that shortens what a model will read is truncation however it is spelled — a head+tail bound, a per-line cap, a 400-char clip. A gate result clipped to 200 characters a side lost the failing test's NAME to cria's own preamble, and the steer then named a different test.

### 5b. cria never states a FALSE FACT about the world
Everything cria says in its own voice — a tool's answer, a refusal, a pointer, a ledger — must be true of the world *now*, and cria must be able to say what makes it true. A claim built on a remembered flag, a partial matcher, or a bound cria imposed on itself is about **cria**, not the world; when they can differ, ask the world.
**The tell.** A sentence in the imperative or indicative — "it was saved to X", "no match", "you already fetched this" — with no live check behind it.
**Counter-nuance.** Saying less is always allowed, and a selection is fine when disclosed (#5). Forbidden is an assertion the world would contradict.
**Corollary — a refusal the model cannot ACT on is a false fact about its own environment.** A stray `/bin/bash` in a malformed call got `go mod download` refused ten times with advice there was no way to follow, and the coder concluded its toolchain was sandboxed off. **Judge the SHAPE before the tokens**, and name something the coder can change.
**Corollary — provenance is part of the fact.** Never label a model's own words as ground truth: a tool-less summary invented a file the task never mentions, reached the completion judge under a `(ground truth)` header, and the coder built it despite noticing.

### 6. Never cap output for latency
`output_reserve` (window kept free for the answer) is split from `max_tokens` (runaway backstop); runaways are caught by the rumination detector, `timeout_seconds` and n_ctx, never a short hard cap. A short `max_tokens` truncating a `write_file` mid-content created the infinite-rewrite footgun — a self-inflicted #5.

### 7. cria never pollutes the user's workspace
cria writes only inside its own directory: any cria file in the workspace is found by the coder's `ls`, `cat`'d, and imitated. File access is bounded to the workspace even under `--yolo` — a backstop for a weak model, **not** a security sandbox.

---

## C. Ground truth over judgment

### 8. Deterministic code gathers facts; a reasoner judges
Cheap deterministic detectors decide *when* and assemble the evidence; a reasoner decides *what*, grounded on that evidence, never on prose intent. Every steer detector is a TRIGGER feeding one reasoned author.
**The tell.** *Tuning* a lexical rule — trading false positives against misses, writing the exception list — IS the judgment, done at authoring time on imagined cases instead of at runtime on the real one. **The rule that needs an exception list is the rule that should have been a question.**
**A judge prompt must FENCE the model out of doing the work.** A coverage check answered `{"missing": []}` about a plan that plainly omitted a deliverable; its reasoning shows it *found* the gap, then designed the implementation at length and re-summarised its checklist without the item — because the prompt opened like a task briefing. The fence (*"You are a JUDGE, not the coder. You have NO tools… Do not think about HOW any of this would be built"*) moved the failure mode from *naming things the plan contained* to *silence*.
**The lesson is the method.** When a judgment comes back wrong, **read the reasoning before concluding the model cannot do the job**: "it lost the answer it had already found" needs a different fix from "it never found it".

### 9. Don't fear an extra model call that prevents churn
When a deliberate reasoner call would ground the next action, make it — even mid-loop, even twice in a step. Optimise for fewer TOTAL calls (purposeful + thrashing), not fewer *reasoner* calls. Bounded by the one-shot flags: a call that doesn't move the plan must not repeat.
**Corollary — a SINGLE QUESTION is a first-class tool**, and the right answer to anything a regex is being asked to decide semantically. A rule keyed on a verb near a filename took four revisions and three false positives, each costing a run: *the difference between a deliverable and plumbing is not in the sentence — it is whether the task asked for it.*

### 10. Verify by doing, not by reading
If cria can *act*, it gets ground truth on its own terms — its command, its output format — rather than parsing the model's claim, because exit 0 is not proof and a self-report is the least trustworthy signal available. cria owns no executors: it borrows the harness's `shell`.

### 11. Files alone are NEVER signal
Read disk NOW, never the transcript's stale file view, and gate the reasoner call on a *repeated no-op or a dirty lint digest*; a clean floor returns `None`, deliberately no call. Invoking the reasoner because files exist makes it invent objections — 73% of file-triggered redirects measured groundless.

### 11b. A mechanism must REACH what it is asked about, or abstain
Ask what a check, probe or research step can actually see. One whose reach does not cover the claim it must settle has to answer "cannot answer" — never "nothing found", never "done" — because silent under-reach is indistinguishable from a clean result and closes the question. The research step, whose job is to make the coder read a real *external* source, has a workspace-scoped reader: asked for a third-party library it settled for a local file and returned DONE, and the coder rebuilt that API from memory over 107 calls with zero fetches.
**The tell.** A *positive* result the mechanism had no way to obtain — "no external source needed" from a reader that cannot reach outside, "no match" from a matcher that never parsed the document, "no entry point" from a branch that returned before consulting the project's declared runners.

### 12. Surface every metric from the authoritative EVENT
Derive counts and signals from the structured event (`upstream.done`, emit sites, exit codes, tool-call args) — never by re-counting a finalized response or matching an English needle in prose. A re-count drifts and silently reports the wrong number; keying on tool args also defeats plumbing jitter (`2>&1`, `| head`).

### 23b. READ IT — a count is not a reading, and a match is not a meaning
Before reporting a number about model behaviour, open one of the things you counted and read it end to end; aggregate *after* reading, never instead. Five consecutive measurements of one subsystem were wrong in one evening, and every one collapsed the moment a single file was opened.
**The tell.** You are about to write a percentage and have not opened an example; or you are reaching for `grep -c` on model output; or your scorer re-implements a check cria already owns (#12 at larger scale). "I read them" means the bytes passed in front of you.
**This is what WALK means here.** Reading every call in a run first to last — the whole prompt cria sent and the whole reasoning it produced. Not a search, not a sample, not a statistic. Two walks of one run blamed the model; the third, which read the plan, found cria had mandated an API the task never mentioned.

---

## D. Fail safe

### 13. Fail closed on completion; fail open only toward "keep working"
An undecidable judge means NOT done, and a judge that can't judge must never strip real results. cria fails *open* only toward regaining the ability to work — never toward a false "done". The root of every early-exit was a fail-OPEN on missing ground truth.

### 14. cria must NEVER end a session by handing back to a human
No human surfacing, no escalation to a stronger model, no "it hit its ceiling". Any turn-end with no tool call reads as "done" to the harness, so cria must not end a red session at all. Churn-while-trying beats bailing; re-add a terminator only with explicit operator permission.

### 15. Measure prevalence before building a heuristic
Base-rate it across real `~/.cria/calls` captures first — the "silently defeated 33%" often proves to be one replayed pathological event, and a detector built for a one-off is dead weight that can itself misfire.

### 16. Assume cria caused it until proven otherwise
Read what the model ACTUALLY received and what it reasoned; correlate what was *sent* against what's *on disk*, and run the real tool, before building machinery to fix its apparent mistake. Multiple derails first blamed on the model were cria bugs — a steer that never reached it, an envelope leak.

---

## E. Stay invisible & stay agnostic

### 17. The model never sees the literal token "cria"
Model-facing markers use the `⟦ctx:…⟧` namespace, never the proper noun, which makes a weak model meta-reason about "their cria mechanism" instead of coding. `⟦cria⟧` (no colon) human notes are allowed but stripped before the model re-reads.
**The second why, and it is worse — the model COPIES what leaks.** The gate shell's capture variables `__cria_out` / `__cria_ec` / `__cria_n` reached the coder 98 times in one prompt and it wrote them into its OWN commands. That wrapper ends in a successful `printf`, so the result came back reading `Process exited with code 0` directly above the wrapper's own `EXIT:1` for a failed build. A leaked idiom is not untidy; it is a false-success generator (#5b). **The tell:** any cria-internal token in a string the harness will EXECUTE, not merely display — and checking the markers is not enough, since a guard test on three variable names passed while ninety-eight other occurrences shipped every turn.

### 18. Harness-agnostic
cria never depends on or prunes the harness's config, never shapes output for one renderer, and matches tools by FAMILY (`SHELL_TOOL_NAMES`), not a literal name. It speaks the wire protocol on both sides, so fixes land on cria's side and apply everywhere.

### 19. Cross-model resilience is the mission — a model that breaks is a requirement
Don't recommend the "best" model or bake behaviour to how one surfaces output. Read reasoning from the dedicated channel *or* inlined content, and match dialect tokens broadly. The mission is resilience across many small models, not finding one that happens to work.

### 20. Be task and language agnostic
cria must work across the top languages, models and harnesses without knowing which it is on. No prompt, detector, matcher or remedy may be keyed to one task's vocabulary, one model's dialect, or one harness's tool names — overfit detectors fail silently the moment any of the three changes. Run the three-lens audit (LANG / MODEL / HARNESS) as a repeatable practice.

### 21. A weak-model sentinel must be a POSITIVE token
A magic word the model emits to veto its own rescue must not be reachable by negating its own reasoning: use `ON_TRACK`, never `NOT_STUCK`. A reasoner that concluded "stuck" emitted `NOT_STUCK` and vetoed its own rescue — negation collapse.

---

## F. Conventions that hardened into rules

### 24. An invariant that must hold on the WIRE belongs at the wire
If a property must be true of the body the model receives — role alternation, no orphan `tool`, no malformed historical tool_call — enforce it at the last point before serialization (`Upstream._prep`), not at a call site: a mid-pipeline transform is undone by anything appended downstream, and the next appender won't know it exists. The alternation merge lived in `Role.apply` while four call sites append user-side turns *after* it, so a body went out `…, tool, user`, a template rejected it six times running, and the run ended empty.
**Corollary — fix the path that produced the incident, not the one that resembles it.** The first fix reordered a path that made ZERO calls in that run; the phase is on every captured body, so the census that would have shown it takes one command.

### 22. Model-facing strings live in prompt files, never inline f-strings
Every string the model reads goes in `cria/prompts/*.txt` (via `prompts.load` / `render` / `load_map`) so it is tunable without a code change.

### 23. Architectural boundaries
Stated in full as `## Principle:` in [`shephard.md`](shephard.md); the five, and the two that carry a correction worth repeating:
- **Lowers every MODEL-FACING tool to `shell`** — unconditional, and what makes cria port anywhere.
- **…but cria DOES execute, on its own side, for its own ends** — tests, syntax floor, linters, exec-check, read-only gathers, and deleting its own probe litter. **The rule is not "cria never runs anything"; it is: what the MODEL sees goes through the harness, what CRIA needs may be run by cria.** An earlier wording said "never touches the workspace", stopped being true, and was left standing — a stale boundary is worse than a wide one, because audits measure against it.
- **One owner for "is this path inside the workspace".** `is_external` is LEXICAL (it must answer for a write target that doesn't exist yet); `escapes_workspace` is the companion for a path cria is about to ACT on. Three implementations once disagreed, and the trap was that two were right for their own caller — so the site that most needed a name for the distinction picked neither.
- **Owns no rendering** — every exposed tool reduces to a primitive the harness can already run *and* display.
- **Guard state is session-scoped** — it resets on a new user turn and never bleeds between sessions, sub-agents or forks.

---

*Rule numbers are cited throughout the code and tests — they never change. `[[name]]` references point to cria's memory, which holds each rule's originating incident.*
