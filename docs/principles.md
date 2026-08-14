# cria — design principles (the doctrine)

These are the revelations that turned into rules while building cria. Each one cost real
debugging — a live session where a small model derailed, the cause was traced to the exact
bytes, and the fix generalized into a rule. They are the **why** behind the mechanisms
catalogued in [`heuristic-assists.md`](heuristic-assists.md); read this first.

**Precedence when they conflict.** The foundations win: *ground truth over judgment*,
*never destroy information the model relies on*, and *fail safe*. A rule about convenience,
tidiness, or cleverness never overrides one of those three.

**The one-sentence charter.** A small local model succeeds at real agentic coding on its
own — [`project_9b_agentic_research_goal`] — and cria gets it there by shaping the context
around it. Every principle below is a way of shaping that context **without introducing a
new way to lie to the model**.

---

## A. What cria may do to the stream — the intervention doctrine

### 1. Every assist can become a footgun
**Rule.** cria shapes a fragile model's entire context, so every injected string is a new
input that can mislead as easily as help. Before adding any model-facing assist, ask "how
does this become a footgun?" and default to **not** adding it. The bar to ADD is high; the
safe direction is almost always to REMOVE.
**Why.** A weak model cannot tell a cria injection from its own reasoning — a wrong nudge is
indistinguishable from a right one. Assists are simultaneously the reason cria exists and its
single largest risk surface.
**Embodied.** [`feedback_assists_are_footguns`], [`feedback_no_footgunning`].

### 2. Interventions are additive / regression-only — never block the first fix, never delete correct content
**Rule.** A new guard may refuse or act only when it makes something *already working*
worse. Validate-before-lower refuses only a write that would break a file that currently
parses — a new or already-broken file writes freely. The durable fetch ledger only ever tells
the coder MORE about what it really obtained.
**Why.** The dangerous class of intervention is DELETION or REDIRECTION of a prior; the safe
class is ADDITIVE + RECOVERY. A guard that blocks the *first* attempt at something can trap
the loop forever.
**Corollary (its own rule, learned the hard way).** ADDITIVE is *necessary, not sufficient*.
A prepended plan step is additive and still forbidden: cria does not AUTHOR work, it shapes
context. Two things follow — cria writes no plan step of its own, and nothing cria writes is
exempt from the living re-derivation (a "pinned" step held out of it is an inescapable
mandate, and one burned 485 calls). Likewise cria never SUBSTITUTES its own action for the
coder's: surface the fact, steer, and let the coder act.
**Embodied.** [`project_convergence_fixes_2026_07_18`] (validate-before-lower is
regression-only; subtractive gate framing), [`project_edit_recovery_unify`] (monotonic
policy); `cria/planner.py` + `cria/plan.py` (the retired research-first injection + pin, and
why), `cria/indicators.py` (markers purely additive to output).

### 3. Silence over noise — on a clean signal, say nothing
**Rule.** Speak only on a high-confidence, actionable signal. When a check *passes*, inject
nothing — never a "might still be wrong" doubt-hedge. State a fact or be silent.
**Why.** Unactionable doubt injected onto a passing check told the model to "fix" green
tests ~20× in one session. Noise on a clean signal is pure downside.
**Embodied.** [`feedback_no_doubt_hedge`]; `cria/planner.py` ("silence over noise").

### 4. No fallbacks, no mitigations — fix upstream
**Rule.** A band-aid that papers over a wrong behavior is forbidden. Find the real cause and
fix it at its source. A deterministic "fallback" behind a reasoner call is the same sin: it
lets fuzzy code quietly make the judgment when the reasoner is the thing you trust.
**Why.** Fallbacks accrete and hide the real defect; the fuzzy fallback fires exactly when
the reasoner would have done better. The plan-shaping refactor deleted five keyword-regex
classifiers *and* every "unparseable → regex fallback" branch, replacing them with one
reasoner judgment and a **safe null** (drop/inject nothing) when the reasoner can't answer.
**Embodied.** global operator rule ("mitigations, fallbacks, band-aids are the most
disgusting thing"); the `reasoned_noise_indices` conversion in `cria/planner.py`.

---

## B. Never destroy information the model relies on

### 5. Truncation is a footgun — never truncate model-read content
**Rule.** Any blind byte/char/line clip of the model's INPUT is a lie the model cannot
detect. cria never truncates content the coder reads. All window-fitting is delegated to the
**one** lossless-first place — the context floor (auto-detect the real window, bound the tool
schema, reduce oversized outputs losslessly, drop whole oldest turns last). Prefer a labelled
summary over silent loss.
**Why.** "Any and all LLM decisions can be altered by truncation lies." An audit found 115
clip sites, 81 of them model-decision footguns.
**Counter-nuance (its own rule).** Never-truncate governs the *coder's reads*, NOT a prompt
cria *composes* for a judge or steer. Bounding a composed prompt breaks no rule — over-applying
never-truncate to composed prompts is itself a documented footgun.
**Embodied.** [`project_never_truncate`], [`project_context_floor`],
[`project_useless_prompting_sweep`] (the counter-nuance);
`docs/audits/2026-07-17-truncation-audit.md`, `docs/audits/2026-07-20-useless-prompting-anomaly-audit.md`;
`cria/contextfloor.py`, `cria/groundtruth.py`, `cria/content_reduce.py` (all "lossless-first").

### 5b. cria never states a FALSE FACT about the world
**Rule.** Everything cria tells the model in its own voice — a tool's answer, a refusal, a
pointer to a file, a ledger of what was fetched — must be true of the world *now*, and cria
must be able to say what makes it true. A claim built on a remembered flag, a partial matcher,
or a bound cria imposed on itself is a claim about **cria**, not about the world. When the two
can differ, ask the world: the filesystem for whether a file is there, the parsed document for
whether a term is in it, the tool menu for whether a name is a tool.
**Why.** A weak model cannot distinguish a wrong fact from a weak answer. Told a document does
not contain a term, it believes the document and starts inventing; told a file is on disk, it
reads and re-reads a path that was never written. Both were measured in one afternoon:
`find="holder_address|total_handles"` answered "no match" about a 96 KB spec containing both
(the matcher treated a multi-term query as one literal) — 134 calls on one step, zero files;
and a run's FIRST fetch was refused with "already fetched … saved to ./tmp/read-only/…", a path
that existed only in the previous run's workspace (a spill ledger keyed on a session id that two
runs of the same prompt share). In both cases every component behaved as written and the model
behaved correctly on the information it was given.
**The tell.** A sentence cria emits in the imperative or the indicative — "it was saved to X",
"no match", "you already fetched this" — with no live check behind it. Grep for the claim, then
find the thing that would have to be true.
**Counter-nuance.** Saying less is always allowed; a cap or a selection is fine when it is
DISCLOSED (rule 5 governs what may be dropped, rule 3 governs when to stay silent). What is
forbidden is an assertion the world would contradict.
**Embodied.** `86ff556`, `263e510` (find= reinterpretation — and cria never reinterprets a query
that already had an answer), `2845af1` (the spill ledger asks the filesystem), `898ef78` (the
fetch ledger splits 2xx from failures), `96becb0` / `docs/audits/2026-07-26-tool-voice-anomaly-audit.md`
(cria may SELECT a checker's real lines, never SUBSTITUTE its own words).

### 6. Never cap output for latency — bound runaway by rumination / timeout / n_ctx
**Rule.** cria targets slow local boxes where users accept long waits, so output is never
capped for speed. `output_reserve` (the window cria keeps free for the answer) is split from
`max_tokens` (the runaway backstop). Runaways are caught by the streaming rumination detector,
`timeout_seconds`, and n_ctx — never a short hard cap.
**Why.** A short `max_tokens` truncating a `write_file` mid-content created the
infinite-rewrite footgun — a self-inflicted variant of rule #5.
**Embodied.** [`project_output_truncation_footgun`], [`project_output_guards_ported`];
`cria/rumination.py`, `cria/loop.py` (retry budgets).

### 7. cria never pollutes the user's workspace
**Rule.** cria writes only inside its own directory; its plan mirror, scratch, and gather
scratchpads live in cria's dir, never the workspace. File access is bounded to the workspace
even under `--yolo` (a best-effort backstop for a weak model, **not** a security sandbox).
**Why.** Any cria file in the workspace is discoverable by the coder's `ls`, gets `cat`'d, and
is imitated — cria's own artifacts become the model's context.
**Embodied.** [`project_no_workspace_pollution`], [`project_external_dir_permission`];
`cria/dirguard.py` (enforced at the one chokepoint `writeproxy.translate_outbound`).

---

## C. Ground truth over judgment

### 8. Deterministic code gathers facts; a reasoner judges
**Rule.** Cheap deterministic detectors decide *when* and assemble the objective evidence
bundle; a reasoner decides *what*, grounded on that evidence — never on prose intent. Fuzzy
keyword code must never make the call itself. "The reasoner judges; code acts."
**Why.** A keyword regex reading intent out of prose is a guess dressed as logic; a weak model
judges a narrow, evidence-grounded question far more reliably, and catches cases the regex
can't. Every steer detector is a deterministic TRIGGER feeding one reasoned author.
**The tell (learned 2026-07-27).** When you find yourself *tuning* a lexical rule — weighing
"trigger on a bare host vs only on a path", trading false positives against misses, writing the
exception list — that weighing IS the judgment, and you are doing it at authoring time on
imagined cases instead of at runtime on the real one. Stop and split it: let code gather the
concrete discrepancy (this host is named in the plan and was never fetched) and ask the reasoner
one narrow question about that fact (does building this plan require knowing what that host
returns?). The rule that needs an exception list is the rule that should have been a question.
Cost is nil when it matters least: the call only happens when the deterministic half found a
discrepancy, so a task with no such gap never pays for it (rule #9).
**A judge prompt must FENCE the model out of doing the work (measured 2026-07-27).** A draft-time
"does this plan cover the request?" check shipped, answered `{"missing": []}` for a plan that plainly
omitted a deliverable, and was reverted as unreliable. Then its REASONING was read, and it had not
failed the comparison at all: it listed the missing item ("Separate live test that resolves goose or
papagoose"), spotted the gap outright ("It doesn't mention separate test for goose/papagoose"), and
then spent six thousand characters designing the implementation — `requests.get`, mock strategy,
filenames — re-summarised its checklist WITHOUT the item it had already found, and answered "nothing
missing". The prompt opened "Read the request and list what it asks to be produced", which reads as a
task briefing, so it did the task. Adding the fence `satisfaction.txt` already carried — *"You are a
JUDGE, not the coder. You have NO tools... Do not think about HOW any of this would be built"* —
changed the FAILURE MODE, which is what made it shippable: measured over 8 samples each at the role's
own sampling, it catches the real gap 4/8 and raises a false alarm 0/8 (the misses split between
`{"missing": []}` and an unparseable reply, both of which take the safe null). Half the time it saves
a run; the rest of the time it is silent. The original prompt's failure mode was the dangerous one —
naming things the plan visibly contained. **Measure the rate over enough samples to know which mode
you have**: a first pass of 3/3 looked like "fixed" and was luck.
**The lesson is the method, not the fix**: when a judgment comes back wrong, read the model's
reasoning before concluding it cannot do the job. A verdict tells you only that it failed; the
reasoning tells you WHERE — and "it lost the answer it had already found" needs a different fix from
"it never found it". A prompt that describes the work in the imperative invites a weak model to
perform it.
**Embodied.** [`project_goal_run_2026_07_18`], [`project_unified_steer_author`],
[the ada-handles /goal record]; `cria/planner.py`, `cria/loop.py`, `cria/config.py`
(pervasive "reasoner judges / code acts").

### 9. Don't fear an extra model call that prevents churn — a purposeful call is cheap next to a thrashing one
**Rule.** When a deliberate reasoner call would ground the next action, make it — even mid-loop,
even a second one in the same step. Optimize for fewer TOTAL model calls (purposeful + thrashing),
not fewer *reasoner* calls. The cost of one purposeful call is tiny next to the coder churn it
prevents: a re-fetched spec, a failed-edit cascade, a gate loop, a dozen wasted acting turns.
**Why.** cria's entire reasoned-guidance posture spends cheap reasoner calls to spare expensive coder
thrashing — a plan drafted up front, each step judged, a stuck loop authored from fresh ground truth,
the re-derivation noise-judged with a second call. A weak model left to guess churns far more than the
call would have cost. (Bounded by the anti-churn one-shot flags: a call that doesn't move the plan must
not repeat — so "more calls" never means "the same call in a loop".)
**Embodied.** the planner's up-front plan; per-step `_verify` + whole-task `judge_satisfaction`;
`reasoned_noise_indices` (a deliberate 2nd reasoner call on every re-derivation); the reasoned steer
author ([`project_unified_steer_author`] — one authored step per stuck detector); [`feedback_no_fallbacks`]
(ask the reasoner a targeted question rather than guess with fuzzy code).

**COROLLARY — a SINGLE QUESTION is a first-class tool, and it is the correct answer to any question
a regex is being asked to answer semantically.** If deterministic code is reaching for a keyword
list, a verb list, or a proximity window to decide something that is really a *judgment*, that is
principle 8 inverted: fuzzy work done by code that cannot be fuzzy. Ask instead. One focused
yes/no or which-of-these call is not "extra inference" under this principle — it is the cheaper
half of the trade, and it is what stops the alternative, which is a pattern that must be retuned
every time reality produces a sentence it did not anticipate.

*Measured, 2026-08-02.* A rule was added to stop the noise judge deleting deliverable steps, keyed
on `(write|create|add|implement|…)` within 40 characters of a filename. It went through **four
revisions in four runs and produced three distinct false positives**:

| revision | wrongly protected | wrongly missed |
|:--|:--|:--|
| verb anywhere + file anywhere | `"Commit the three files (…), add a .gitignore …"` | — |
| verb adjacent to file | — | `"Write a live test file (e.g., test_live_resolve.py)"` |
| 40-character window | `"Add a requirements.txt entry for requests"` | — |

Each cost a run. The tell was in the diagnosis all along: *the difference between authoring a
deliverable and authoring plumbing is not in the sentence — it is in whether the task asked for it.*
No window over the sentence can recover information the sentence does not contain. One question to
the judge that already exists — "which of these steps produce something the task asked for?" —
answers it directly, and the judge is already being called on that exact list.

**The test for this smell:** if you are tuning a pattern because a real sentence broke it, stop and
ask whether a model call would have been right the first time.

### 10. Verify by doing, not by reading — cria makes its own read-only probes
**Rule.** If cria can *act*, it gets ground truth on its own terms — it picks the command and
the output format — rather than parsing the model's noisy claim. The syntax floor
(`py_compile` / `node --check`) and the completion gate (run the tests on any "done" claim)
are cria acting for itself. cria owns no executors: it borrows the harness's `shell`.
**Why.** Exit 0 is not proof; a model's self-report is the least trustworthy signal available.
A probe cria runs is deterministic ground truth.
**Embodied.** `docs/shephard.md` ("## Principle: owns no executors"; Probes),
[`heuristic-assists.md`](heuristic-assists.md), [`project_probe_gate_port`];
`cria/loop.py`, `cria/proberun.py`, `cria/probegate.py`, `cria/groundtruth.py`.

### 11. Files alone are NEVER signal — only a deterministic anomaly earns a reasoner call
**Rule.** Read disk NOW (never the transcript's stale/truncated file view), and gate the
reasoner call on a *repeated no-op or a dirty lint digest*. Invoking the reasoner merely
because files exist makes it invent objections. A clean floor returns `None` — deliberately no
call.
**Why.** Upstream measured 73% of file-triggered redirects as groundless. A transcript's
file view is exactly the truncated lie rule #5 exists to prevent.
**Embodied.** `cria/groundtruth.py` (module docstring — "the load-bearing rule").

### 12. Surface every metric from the authoritative EVENT — never a re-count or a text-match
**Rule.** Derive counts and signals from the structured event (`upstream.done`, the
intervention emit sites, exit codes, tool-call args) — never by re-counting a finalized
response or matching an English needle in prose.
**Why.** A re-count or prose-match drifts from the real event and silently reports the wrong
number; keying on tool args instead of text also defeats plumbing jitter (`2>&1`, `| head`).
**Embodied.** [`project_turnstats_wrong_signal`], [`project_gate_error_class_filter`]
(key on exit codes, not prose), [`project_repetition_plumbing_jitter`] (fingerprint args);
`cria/turnstats.py`, `cria/probeparse.py`.

---

## D. Fail safe

### 13. Fail closed on completion; fail open only toward "keep working"
**Rule.** An undecidable judge means NOT done. A judge that can't judge must never strip real
results. cria only ever fails *open* in the safe direction — regaining the ability to work, or
continuing to drive — never toward a false "done."
**Why.** The cross-cutting root of every early-exit and false-completion was a **fail-OPEN on
missing ground truth** — an unparseable verdict treated as success.
**Embodied.** [`project_early_exit_sweep`], [`project_false_completion_step_one`];
`docs/audits/2026-07-20-early-exit-anomaly-audit.md`; `cria/loop.py`, `cria/writeproxy.py`
("still fail-CLOSED").

### 14. cria must NEVER end a session by handing back to a human
**Rule.** No human surfacing, no cloud/stronger-model escalation, no "it hit its ceiling."
Any cria turn-end with no tool call reads as "done" to the harness — so cria must not end a
red session at all. Churn-while-trying beats bailing. Re-add any terminator only with explicit
operator permission.
**Why.** The mission is a small model succeeding *on its own*; ending to a human is an
escalation the operator never authorized. The stall-terminator was deleted for exactly this.
**Embodied.** [`project_9b_agentic_research_goal`], [`project_stall_terminator_removed_2026_07_19`],
[`feedback_keep_going`]; `cria/loop.py` (the accept-and-advance cap was removed).

### 15. Measure prevalence before building a heuristic
**Rule.** Base-rate the signal across real `~/.cria/calls` captures before building a
normalizer or detector for it. The "silently defeated 33%" often proves to be one replayed
pathological event.
**Why.** A detector built for a one-off incident is dead weight that can itself misfire — a
5-lens red team *killed* a proposed error-persistence detector on exactly this basis.
**Embodied.** [`project_useless_prompting_sweep`], [`feedback_no_footgunning`],
[`project_convergence_fixes_2026_07_18`].

### 16. Assume cria caused it until proven otherwise
**Rule.** Read what the model ACTUALLY received and what the model reasoned/thought.
Before building machinery to fix a model's apparent mistake, correlate what was
*sent* against what's *on disk*, and run the real tool. When a steer "doesn't work," inspect
the delivered bytes and the model reasoning — the loop can end up "fixing" a footgun cria itself introduced.
**Why.** Multiple derails first blamed on the model were real cria bugs (a steer that never
reached the model, an envelope leak). The reflex must be self-suspicion, not model-blame.
**Embodied.** [`feedback_no_footgunning`], [the ada-handles /goal record] (self-corrected
repeatedly).

---

## E. Stay invisible & stay agnostic

### 17. The model never sees the literal token "cria"
**Rule.** Model-facing markers use the `⟦ctx:…⟧` namespace, never the proper noun "cria".
`⟦cria⟧` (no colon) human-indicator notes are allowed but stripped before the model re-reads.
Refusal text and every injected string obey this.
**Why.** A distinctive proper noun makes the weak model meta-reason about "their cria
mechanism" instead of coding.
**Embodied.** [`feedback_model_never_sees_cria`]; `cria/contextfloor.py`, `cria/indicators.py`
(the strip contract), `cria/dirguard.py`.

### 18. Harness-agnostic — manage context on cria's own side, for any harness
**Rule.** cria never depends on or prunes the harness's config, never shapes output for one
harness's renderer, and matches tools by FAMILY (`SHELL_TOOL_NAMES`), not a literal name.
Fixes land on cria's side and apply to every harness; the retired codex-local fork is a
read-only spec, never a fix target.
**Why.** cria speaks the wire protocol on both sides so it works under any OpenAI-compatible
harness; a harness-specific fix breaks that contract.
**Embodied.** [`feedback_harness_agnostic`], [`project_agnostic_audit_2026_07_23`] (HARNESS
lens), [`feedback_fixes_both_paths`]; `cria/toolmenu.py` (match by family), `cria/contextfloor.py`.

### 19. Cross-model resilience is the mission — a model that breaks is a requirement
**Rule.** Don't recommend the "best" model or bake behavior to how one model surfaces output.
A model that breaks the harness is a resilience *requirement*, not grounds to drop it. Read a
model's reasoning from either the dedicated channel *or* inlined content; match dialect tokens
broadly.
**Why.** The mission is resilience across many small models, each with its own quirks — not
finding one that happens to work.
**Embodied.** [`feedback_cross_model_resilience`], [`project_agnostic_audit_2026_07_23`]
(MODEL lens — `_reasoning_of` content fallback; dialect-marker drift); `cria/reasoning.py`,
`cria/massage.py`.

### 20. Be task and language agnostic
**Rule.** cria is meant to support many of the top languages Run the
three-lens agnostic audit as a repeatable practice.
**Why.** Overfit prompts and detectors silently fail the moment the task, model, or harness
changes — the failure mode agnosticism exists to prevent.
**Embodied.** [`project_agnostic_audit_2026_07_23`]; `tests/test_prompts.py`
(`PromptAgnosticismTests`, dialect-marker sync invariants).

### 21. A weak-model sentinel must be a POSITIVE token, never the negation of its trigger
**Rule.** A magic word the model must emit to veto its own rescue must not be reachable by
negating its own reasoning. Use a positive state-judgment (`ON_TRACK`), never `NOT_STUCK`.
**Why.** A reasoner that concluded "stuck" then emitted the negation sentinel `NOT_STUCK`,
vetoing its own rescue (negation collapse). The sentinel a weak model emits must not be the
lexical negation of the trigger.
**Embodied.** [`project_sentinel_negation_trap`]; `cria/prompts/steer_diagnose.txt`,
`tests/test_prompts.py` (the veto-sentinel-is-positive invariant).

---

### 23b. READ IT. A count is not a reading, and a match is not a meaning
**Rule.** Before you report a number about model behavior, open one of the things you counted and
read it end to end — the whole prompt cria sent, the whole reply, the whole reasoning. Aggregate
after you have read, never instead. A regex over a corpus tells you how often a *string* occurs; it
cannot tell you what happened, and it will confidently tell you the opposite.
**Why.** In one evening, five consecutive measurements of the same subsystem were wrong, each
because something adjacent to cria's real behavior was measured instead of the behavior:

| claimed | actual | the shortcut |
|:--|:--|:--|
| "97% of verdicts unparseable" | 32 parse fine | grepped for a literal key instead of calling cria's own parser |
| "6.5 wasted calls per check" | those were the judge inspecting with its tools | counted calls, never opened one |
| "49 genuinely unreadable" | 46, and a third were recoverable | scored `-confirm` replies against the wrong phase's key |
| "the judge emits a constant" | it was answering correctly on mismatched pairs | hand-wrote prompts instead of replaying captured ones |
| "decomposition is worse" | untestable from that data | both arms saw evidence that could not settle the question |

Every one collapsed the moment a single file was opened. The first *actual* reading — 46 replies,
in full — produced four findings no count had surfaced: a judge calling tools from a different
harness's vocabulary, a read-only judge repeatedly trying to edit code, consecutive retries ruling
opposite ways on identical evidence, and complete verdicts written in prose and discarded.
**The tell.** You are about to write a percentage and you have not opened a single example. Or you
are reaching for `grep -c` on a corpus of model output. Or your scorer re-implements a check cria
already owns — that one has its own entry (rule 12) and this is the same disease at a larger scale.
**Corollary.** "I read them" means the bytes passed in front of you. Thirty-seven seconds for
forty-six files is not reading, and the resulting confidence is the dangerous part, not the error.
**This is what the word WALK means in this project.** A walk is reading every call in a run from
first to last — the whole prompt cria sent and the whole reasoning it produced — not a search
through them, not a sample of them, and not a statistic over them. The distinction is not
pedantic: two walks of one mellum2 run blamed the model, and the third, which actually read the
plan cria sent, found that cria had mandated a JSON-RPC API the task never mentioned, contradicted
itself two steps later by testing REST, and invented the CLI flag that made the deliverable score
zero. Nothing short of reading would have reached that.
**Embodied.** `docs/audits/ladder-walk.md` (the P4 thread, five corrections in sequence);
`suite/replay_logic.py` (replays captured bodies, never invented ones);
`cria/loop.py::verdict_from_reasoning` — the fix that only reading found.


### 24. An invariant that must hold on the WIRE belongs at the wire
**Rule.** If a property must be true of the body the model actually receives — strict role
alternation, no orphan `tool`, no malformed historical tool_call — enforce it at the last point
before serialization (`Upstream._prep`), not at a call site. A transform that runs mid-pipeline is
undone by anything appended downstream, and the next appender will not know it exists.
**Why.** `merge_consecutive_turns` performed the alternation merge inside `Role.apply`. Four call
sites append user-side turns AFTER the role is applied — the plan-off driver (focustrim's
repeat-note), `guard_rumination`, `guard_truncation`, and the streaming proxy, which skips the trim
entirely — so the body went out `…, tool, user` and a Llama-lineage template rejected it six times
in a row, ending nemotron-nano run 1786243834 on an empty workspace. The wire already held two
transforms for exactly this reason (the unconditional orphan-`tool` repair, which the floor's
over-budget-only strip used to miss, and the assistant-side merge); this was the third and it was
in the wrong place. **Ordering two lines per call site is a band-aid per site (#4).** Carry the
role's intent as a cria-internal body hint (the `cria_output_reserve` pattern), consume and strip it
at the wire, and keep it opt-in so every model that does not need it ships a byte-identical body.
**Corollary — fix the path that produced the incident, not the one that resembles it.** The first
fix for the above reordered `server.py`'s proxy path, which made ZERO calls in that run; every one
of the failing calls was phase `coder-s1`. The phase is recorded on every captured body and in every
`upstream.dump` — a census takes one command, and skipping it cost a commit whose message, comment,
test docstring and audit entry all asserted the same wrong path (#23b, at the level of code paths
rather than model output).
**Embodied.** `cria/upstream.py::Upstream._prep` (the three wire normalizations),
`cria/massage.py::merge_for_alternation`, `cria/config.py::Role.apply` (hint only);
`tests/test_alternation_at_the_wire.py`; docs/audits/ladder-walk.md (the nemotron-nano walk).

## F. Conventions that hardened into rules

### 22. Model-facing strings live in prompt files, never inline f-strings
Every string the model reads goes in `cria/prompts/*.txt` (via `prompts.load` / `render` /
`load_map`) so it's tunable without a code change. Flagged by the operator repeatedly.
[`feedback_prompts_in_files`].

### 23. Architectural boundaries (stated as `## Principle:` in [`shephard.md`](shephard.md))
- **Lowers every MODEL-FACING tool to `shell`** — cria is a bidirectional transform on the
  tool-call stream: rich tools (`write_file`, `web_fetch`) become the one primitive every harness
  runs, and the result is re-presented inbound as the original tool. That is what makes cria port
  to any harness, and it is unconditional.
- **…but cria DOES execute, on its own side, for its own ends.** It runs the repo's tests, the
  syntax floor, the linters, the exec-check that starts the delivered program, the planner's
  read-only gathers, and it deletes the litter its own probes create. This is the actor/supervisor
  half `shephard.md` records, and it is deliberate — a probe cria composes for the harness cannot
  clean up after itself (the Codex sandbox hard-rejects an `rm`, which once killed every gate), and
  a check whose result cria must parse is cheaper run directly than round-tripped.
  **The rule is not "cria never runs anything." It is: what the MODEL sees goes through the
  harness; what CRIA needs may be run by cria.** An earlier wording said "never touches the
  workspace", which stopped being true and was left standing — a stale boundary is worse than a
  wide one, because an audit measures against it and a maintainer believes it.
- **What that costs, and the part still owed:** cria's own subprocesses are outside the harness's
  sandbox, and `dirguard` — which has one enforcement point — is used by none of the three direct
  execution sites (`execcheck`, `planner_tools`, `probegate`'s sweep). So "is this safe to run
  here" currently has three implementations that cannot agree. Open.
- **Owns no rendering either** — every tool cria exposes must reduce to a primitive the harness
  already knows how to both *run and display*; never a cria-only tool the harness must be taught
  to draw.
- **Guard state is session-scoped** — anything a guard remembers (searches this turn, URLs
  fetched, streaks) belongs to one session's current turn; it resets on a new user turn and
  never bleeds between sessions, sub-agents, or forks.

---

*The `[[name]]`-style references above point to cria's persistent memory
(`~/.claude/projects/-home-jesse-src-cria-shepherd/memory/`), where the originating incident for
each rule is recorded. The audits under [`audits/`](audits/) hold the full forensic narratives.*
