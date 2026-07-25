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
parses — a new or already-broken file writes freely. Additive steps (a prepended research
step) never delete or rewrite an existing one.
**Why.** The dangerous class of intervention is DELETION or REDIRECTION of a prior; the safe
class is ADDITIVE + RECOVERY. A guard that blocks the *first* attempt at something can trap
the loop forever.
**Embodied.** [`project_convergence_fixes_2026_07_18`] (validate-before-lower is
regression-only; subtractive gate framing), [`project_edit_recovery_unify`] (monotonic
policy); `cria/planner.py` (research-first is ADDITIVE, never deletes/rewrites),
`cria/indicators.py` (markers purely additive to output).

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
**Embodied.** [`project_goal_run_2026_07_18`], [`project_unified_steer_author`],
[`project_goal_fabliq_ada_handles`]; `cria/planner.py`, `cria/loop.py`, `cria/config.py`
(pervasive "reasoner judges / code acts").

### 9. Verify by doing, not by reading — cria makes its own read-only probes
**Rule.** If cria can *act*, it gets ground truth on its own terms — it picks the command and
the output format — rather than parsing the model's noisy claim. The syntax floor
(`py_compile` / `node --check`) and the completion gate (run the tests on any "done" claim)
are cria acting for itself. cria owns no executors: it borrows the harness's `shell`.
**Why.** Exit 0 is not proof; a model's self-report is the least trustworthy signal available.
A probe cria runs is deterministic ground truth.
**Embodied.** `docs/shephard.md` ("## Principle: owns no executors"; Probes),
[`heuristic-assists.md`](heuristic-assists.md), [`project_probe_gate_port`];
`cria/loop.py`, `cria/proberun.py`, `cria/probegate.py`, `cria/groundtruth.py`.

### 10. Files alone are NEVER signal — only a deterministic anomaly earns a reasoner call
**Rule.** Read disk NOW (never the transcript's stale/truncated file view), and gate the
reasoner call on a *repeated no-op or a dirty lint digest*. Invoking the reasoner merely
because files exist makes it invent objections. A clean floor returns `None` — deliberately no
call.
**Why.** Upstream measured 73% of file-triggered redirects as groundless. A transcript's
file view is exactly the truncated lie rule #5 exists to prevent.
**Embodied.** `cria/groundtruth.py` (module docstring — "the load-bearing rule").

### 11. Surface every metric from the authoritative EVENT — never a re-count or a text-match
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

### 12. Fail closed on completion; fail open only toward "keep working"
**Rule.** An undecidable judge means NOT done. A judge that can't judge must never strip real
results. cria only ever fails *open* in the safe direction — regaining the ability to work, or
continuing to drive — never toward a false "done."
**Why.** The cross-cutting root of every early-exit and false-completion was a **fail-OPEN on
missing ground truth** — an unparseable verdict treated as success.
**Embodied.** [`project_early_exit_sweep`], [`project_false_completion_step_one`];
`docs/audits/2026-07-20-early-exit-anomaly-audit.md`; `cria/loop.py`, `cria/writeproxy.py`
("still fail-CLOSED").

### 13. cria must NEVER end a session by handing back to a human
**Rule.** No human surfacing, no cloud/stronger-model escalation, no "it hit its ceiling."
Any cria turn-end with no tool call reads as "done" to the harness — so cria must not end a
red session at all. Churn-while-trying beats bailing. Re-add any terminator only with explicit
operator permission.
**Why.** The mission is a small model succeeding *on its own*; ending to a human is an
escalation the operator never authorized. The stall-terminator was deleted for exactly this.
**Embodied.** [`project_9b_agentic_research_goal`], [`project_stall_terminator_removed_2026_07_19`],
[`feedback_keep_going`]; `cria/loop.py` (the accept-and-advance cap was removed).

### 14. Measure prevalence before building a heuristic
**Rule.** Base-rate the signal across real `~/.cria/calls` captures before building a
normalizer or detector for it. The "silently defeated 33%" often proves to be one replayed
pathological event.
**Why.** A detector built for a one-off incident is dead weight that can itself misfire — a
5-lens red team *killed* a proposed error-persistence detector on exactly this basis.
**Embodied.** [`project_useless_prompting_sweep`], [`feedback_no_footgunning`],
[`project_convergence_fixes_2026_07_18`].

### 15. Assume cria caused it until proven otherwise — read what the model ACTUALLY received
**Rule.** Before building machinery to fix a model's apparent mistake, correlate what was
*sent* against what's *on disk*, and run the real tool. When a steer "doesn't work," inspect
the delivered bytes — the loop can end up "fixing" a footgun cria itself introduced.
**Why.** Multiple derails first blamed on the model were real cria bugs (a steer that never
reached the model, an envelope leak). The reflex must be self-suspicion, not model-blame.
**Embodied.** [`feedback_no_footgunning`], [`project_goal_fabliq_ada_handles`] (self-corrected
repeatedly).

---

## E. Stay invisible & stay agnostic

### 16. The model never sees the literal token "cria"
**Rule.** Model-facing markers use the `⟦ctx:…⟧` namespace, never the proper noun "cria".
`⟦cria⟧` (no colon) human-indicator notes are allowed but stripped before the model re-reads.
Refusal text and every injected string obey this.
**Why.** A distinctive proper noun makes the weak model meta-reason about "their cria
mechanism" instead of coding.
**Embodied.** [`feedback_model_never_sees_cria`]; `cria/contextfloor.py`, `cria/indicators.py`
(the strip contract), `cria/dirguard.py`.

### 17. Harness-agnostic — manage context on cria's own side, for any harness
**Rule.** cria never depends on or prunes the harness's config, never shapes output for one
harness's renderer, and matches tools by FAMILY (`SHELL_TOOL_NAMES`), not a literal name.
Fixes land on cria's side and apply to every harness; the retired codex-local fork is a
read-only spec, never a fix target.
**Why.** cria speaks the wire protocol on both sides so it works under any OpenAI-compatible
harness; a harness-specific fix breaks that contract.
**Embodied.** [`feedback_harness_agnostic`], [`project_agnostic_audit_2026_07_23`] (HARNESS
lens), [`feedback_fixes_both_paths`]; `cria/toolmenu.py` (match by family), `cria/contextfloor.py`.

### 18. Cross-model resilience is the mission — a model that breaks is a requirement
**Rule.** Don't recommend the "best" model or bake behavior to how one model surfaces output.
A model that breaks the harness is a resilience *requirement*, not grounds to drop it. Read a
model's reasoning from either the dedicated channel *or* inlined content; match dialect tokens
broadly.
**Why.** The mission is resilience across many small models, each with its own quirks — not
finding one that happens to work.
**Embodied.** [`feedback_cross_model_resilience`], [`project_agnostic_audit_2026_07_23`]
(MODEL lens — `_reasoning_of` content fallback; dialect-marker drift); `cria/reasoning.py`,
`cria/massage.py`.

### 19. De-overfit assists from the single dev task (the LANG / MODEL / HARNESS audit)
**Rule.** cria was tuned for weeks against one prompt and one model; prompts and detectors
must be generalized off "browse an API spec" and off one model's token dialect. Run the
three-lens agnostic audit as a repeatable practice.
**Why.** Overfit prompts and detectors silently fail the moment the task, model, or harness
changes — the failure mode agnosticism exists to prevent.
**Embodied.** [`project_agnostic_audit_2026_07_23`]; `tests/test_prompts.py`
(`PromptAgnosticismTests`, dialect-marker sync invariants).

### 20. A weak-model sentinel must be a POSITIVE token, never the negation of its trigger
**Rule.** A magic word the model must emit to veto its own rescue must not be reachable by
negating its own reasoning. Use a positive state-judgment (`ON_TRACK`), never `NOT_STUCK`.
**Why.** A reasoner that concluded "stuck" then emitted the negation sentinel `NOT_STUCK`,
vetoing its own rescue (negation collapse). The sentinel a weak model emits must not be the
lexical negation of the trigger.
**Embodied.** [`project_sentinel_negation_trap`]; `cria/prompts/steer_diagnose.txt`,
`tests/test_prompts.py` (the veto-sentinel-is-positive invariant).

---

## F. Conventions that hardened into rules

### 21. Model-facing strings live in prompt files, never inline f-strings
Every string the model reads goes in `cria/prompts/*.txt` (via `prompts.load` / `render` /
`load_map`) so it's tunable without a code change. Flagged by the operator repeatedly.
[`feedback_prompts_in_files`].

### 22. Architectural boundaries (stated as `## Principle:` in [`shephard.md`](shephard.md))
- **Owns no executors** — cria is a bidirectional transform on the tool-call stream; it never
  touches the workspace, and lowers rich tools (`write_file`, `web_fetch`) to the one primitive
  every harness runs (`shell`), re-presenting the result inbound.
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
