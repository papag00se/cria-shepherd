# cria — design principles

These rules come from failures traced to exact causes. Evidence lives in [`audits/`](audits/) and memory; mechanisms in [`heuristic-assists.md`](heuristic-assists.md).

**Precedence:** ground truth over judgment; never destroy information the model relies on; fail safe. Convenience never overrides these.

**Charter:** help a small local model succeed at real agentic coding by shaping its context, without creating new ways to mislead it.

---

## A. Stream interventions

### 1. Every assist can become a footgun
A weak model cannot tell cria's injections from its own reasoning, so every injected string is a possible falsehood. Ask how an assist can mislead before adding it; default to removal.

**An assist outlives its cause.** Once its defect is fixed upstream it keeps firing where only misleading is left. Re-measure assists against today's system: not "was this justified" but "does removing it cost anything now". Compare the captured boundary with and without it, including legitimate nearby cases and enough repetitions for variance. Firing in good runs proves no benefit; silence proves no redundancy. Prefer removing a harmful intervention to guarding it.

### 2. Interventions are additive, regression-only, and cria never AUTHORS work
Intervene only to keep existing progress from regressing; deletion, redirection and blocking a first attempt can trap loops. Additive is not safe by itself: cria never writes plans, actions or code for the coder. Everything injected stays open to re-derivation, never an immutable mandate. Surface facts and steer; let the coder act.

**Explicit operator exception — unread existing files.** The operator deliberately chose a process gate: hold a write to an existing non-blank unread file, exempt missing and empty/whitespace-only files, and hide write tools for one coder request after a hold. This is a decision, not an efficacy claim; it is scoped to L5 and the routes and unknown-state limitations in [the mechanism and evidence record](heuristic-assists.md#operator-selected-unread-file-process-gate). Other process gates are not authorized by this exception.

### 3. Silence over noise
Inject only high-confidence, actionable information. Nothing on a passing check, no speculative warnings on green results. State a fact or stay silent.

### 4. No fallbacks or mitigations; fix upstream
Do not hide wrong behavior behind a workaround; fix the cause. Before forbidding an existing behavior or adding an admission requirement, read its documented decision and history, and separate the operator's actual boundary from a stricter preference invented during the investigation. Do not put deterministic fallback logic behind a reasoner: if the trusted reasoner cannot answer, inject nothing.

---

## B. Never destroy information the model relies on

### 5. cria never truncates
Never blindly clip bytes, characters, lines, prompts, evidence or model output. Window fitting happens only at the lossless-first context floor. Allowed: de-duplication (repeated content once, with a pointer to the original) and a model-made summary or selection, labelled as such. Everything else that shortens model-visible content is truncation — head/tail limits, per-line caps, character budgets — and disclosing it does not make it not truncation. cria's own framing does not consume the evidence budget; when cria holds the authoritative object, use it instead of shortening a re-rendered copy.

### 5b. cria never states a FALSE FACT about the world
Every factual statement cria makes must be true now and backed by a live check against the authoritative source: the filesystem for existence, the parsed document for contents, the tool menu for available tools. Internal limits, remembered flags, partial matches and assumptions are not world facts. A refusal names something the coder can change; validate a command is well-formed before judging it. Keep provenance: tool output is ground truth, model summaries are claims, never labelled alike. Saying less is allowed; saying what the world would contradict is not.

### 6. Never cap output for latency
Slow hardware and long waits are acceptable. Keep answer-window sizing separate from runaway protection: runaways are handled by streaming detection, timeouts and context limits, never a short hard cap that can cut a file write mid-content.

### 7. cria never pollutes the user's workspace
cria writes only inside its own directory; workspace artifacts reach the coder and contaminate its context. File access stays bounded to the workspace even under `--yolo` (a weak-model backstop, not a sandbox).

Investigation scratch is temporary: one working directory and the actual findings are enough. Reuse the real checks and findings; do not add approval layers, copied validators, proof registries, duplicate reports, source mirrors or hash/receipt archives. Tests and tools must not depend on disposable investigation output; keep needed inputs as small repository fixtures. Repository changes and real model-call logs are the durable outputs; delete scratch once its fixes are settled.

---

## C. Ground truth over judgment

### 8. Deterministic code gathers facts; a reasoner judges
Detectors decide **when** to ask and gather objective evidence; a reasoner decides **what** it means. A lexical rule that needs tuned thresholds or exception lists is semantic judgment leaking into code — ask the reasoner. Judge prompts state the model is a judge, restrict its tools and forbid implementation thinking. When a judgment is wrong, read the reasoning first: losing a correct answer and never finding it are different failures.

### 9. Don't fear an extra model call that prevents churn
Use a reasoner whenever it can ground the next action, even several times in a step. Optimize total model calls, not reasoner calls. Semantic questions belong to reasoners, not keyword lists or proximity windows. One-shot guards keep an unhelpful call from repeating.

### 10. Verify by doing, not by reading
Get ground truth by execution, not by trusting model claims; exit 0 and self-reports do not prove behavior. cria owns no executor; it borrows the harness shell.

### 11. Files alone are NEVER signal
Read current disk state, not stale transcript state. Trigger reasoning on evidence (repeated no-ops, dirty lint), not on files merely existing. A clean floor produces no intervention.

### 11b. A mechanism must REACH what it is asked about, or abstain
Before trusting a mechanism, confirm it can observe its subject; otherwise it must say it cannot answer, never "nothing found" or "done". Workspace readers cannot judge third-party source, unparsed documents cannot support "no match", code that exits before checking declared runners cannot report "no entry point". A positive conclusion the mechanism could not have observed is invalid.

### 12. Surface every metric from the authoritative EVENT
Derive metrics from structured events — completion records, intervention sites, exit codes, tool arguments — never from final prose or English pattern matching.

### 23b. READ IT — a count is not a reading, and a match is not a meaning
Before any claim about model behavior, read at least one counted example end to end. Regex counts show string occurrence, not behavior; do not replace reading with `grep -c`, or re-implement checks cria already owns. A **walk** follows the selected recorded reasoning chronologically, maps it to the full same-call context, then challenges and diagnoses with an operator-selected model; full-run claims need every call's reasoning, selected-call work is labelled as such. Context is explored by targeted searches and neighborhood reads. The operative process is [walk-prompt.md](walk-prompt.md).

---

## D. Fail safe

### 13. Fail closed on completion; fail open only toward "keep working"
An undecidable completion judgment means **not done**. A failed judge never removes real results or produces a false success; fail open only toward continuing work or restoring the ability to work.

This governs ONE question: whether the coder's task is done. It is not a rule for the suite, campaigns, deployment or bookkeeping: a run that fails or is interrupted is simply rerun, and nothing is blocked because its evidence cannot be proven.

### 14. cria must NEVER end a session by handing back to a human
No escalation to a human, a stronger model or a declared capability ceiling. A cria turn without a tool call reads as completion, so a red session must keep driving. Reintroduce a terminator only with explicit operator permission.

### 15. Measure prevalence before building a heuristic
Measure a suspected pattern across real captures before building a detector; one replayed pathological event is not a systemic problem. Local causal evidence suffices for a local repair: a walk or replay can show one misleading context, harmful refusal or broken transition and test a correction at that boundary. Whole tasks diverge and cannot attribute outcomes to single assists, so state the bounded conclusion and its uncertainty, and do not demand universal benefit proof before accepting a demonstrated repair with regression coverage. Aggregate scores describe delivered work, not the need for any one assist.

### 16. It is always cria's fault. "The model's fault" is not a finding.
**Never write, say or conclude "the model failed", "a model limitation", "a real model result, not our bug", or any variant.** Not because the model is never the proximate cause, but because naming it ends the investigation exactly where cria's reason to exist begins. A 9B-class model derailing is the problem statement, not an explanation.

The attribution is fixed: **whatever the coder did, cria let it happen**; the only question is which assist was absent, silent, mistimed or wrong. Rumination is the rumination steer failing to land. Twelve refused completion claims are twelve chances to redirect the coder into writing code that cria did not take. A coder reading for 22 minutes without writing is a missing nudge. This makes #19 operational: a model that breaks in a new way specifies the next assist. Score the work honestly (usefulness measures delivered code), but never turn a low score into a verdict on the weights.

Before concluding: read what the model received, read what it reasoned, compare that with disk state, run the real tool. Do not build machinery to compensate for a failure cria itself introduced, and never close a finding with a cause outside cria's reach.

**Incident, 2026-09-18 (why this is a ban).** A `shipping-rates-rb` cell scored 5%. Its first 32 minutes went to a broken Ruby gem path — cria's own suite bug — which was found and fixed. The rerun also scored 5%, and the campaign agent wrote "this time it's a real model result, not our bug", hours after reading this principle. The evidence in hand — one write in 30 calls, an 8,240-token rumination abort, twelve blocked completion claims — was a list of cria's assists firing without changing the outcome: the best input for the next assist, filed as a fact about the weights.

---

## E. Stay invisible and agnostic

### 17. The model never sees the literal token "cria"
Model-facing markers use `⟦ctx:…⟧`; human-facing `⟦cria⟧` notes are stripped before the model re-reads them. Internal tokens can be copied into executable commands, so no product name appears anywhere cria composes content the model reads or runs: private artefacts (heredoc delimiters, frame markers, shell variables, temp dirs) use `ctx`-family names (`___CTX_GATE_`, `__CTX_PY_EOF__`, `.ctx-done-`). A history an earlier release lowered is cleaned at the wire, statelessly (`privatenames`: old names renamed inside cria-composed commands and their results only; a declared lowering without a receipt is re-presented as the tool the model made; a survey cria composed alone leaves with its result). `tests/structure` scans every main lowered command, and `tests/server_config/test_server_config_invis_fixture_session.py` scans every upstream body of a whole session and its replay through a restarted server.

### 18. Harness-agnostic
Do not depend on, prune or specialize for harness configuration or rendering. Match tools by family, not literal name; speak the wire protocol on both sides so fixes stay inside cria and work across harnesses.

### 19. Cross-model resilience is the mission — a model that breaks is a requirement
Do not optimize around one model or recommend a preferred one. Read reasoning from dedicated channels or inline content and match dialects broadly; failures on different small models reveal requirements.

### 20. Be task and language agnostic
Do not key prompts, detectors, matchers or remedies to one task's vocabulary, language, model dialect or harness tool names. Run the three-lens audit: **LANG / MODEL / HARNESS**.

### 21. A weak-model sentinel must be a POSITIVE token
A model-emitted veto uses a positive token (`ON_TRACK`), never a negated one (`NOT_STUCK`): negation can invert the model's own conclusion and cancel a needed rescue.

---

## F. Hardened conventions

### 22. Model-facing strings live in prompt files, never inline f-strings
Every model-visible string lives in `cria/prompts/*.txt`, so prompts change without code changes.

### 23. Architectural boundaries
Defined fully under `## Principle:` in [`shephard.md`](shephard.md).
- **Lower every MODEL-FACING tool to `shell`;** rich tools become the harness primitive and are reconstructed inbound as the original tool.
- **cria may execute for its own needs** (tests, syntax checks, linters, exec checks, read-only gathers, cleanup); model-facing execution still goes through the harness.
- **One owner for workspace-boundary checks;** lexical checks for not-yet-existing write targets stay separate from resolved-path checks for paths cria acts on.
- **Own no rendering;** every exposed tool reduces to a primitive the harness can run and display.
- **Guard state is session-scoped;** reset on each user turn, never leak across sessions, sub-agents or forks.

### 23c. Reaching the workstation, the environment or the repo goes through the HARNESS
cria need not be on the coder's machine; the likely deployment is cria beside the model server and the harness on a workstation. `workspace_root` is a path on the HARNESS's filesystem, so `os.path.isdir` on it means something only when co-located.

**Any access to the workstation, environment or repo goes through a harness tool:** cria composes the call, the harness runs it where the files are, cria reads the result. The completion gate is the worked example: `guard_gate_op` builds a shell call, the harness runs the repo's own checks and spools the full result outside the workspace, later calls return checked pages released to the parser only on an exact byte count and SHA-256, and `probegate.clean_gate_results` replaces that plumbing in the model's view with one `⟦ctx:checks⟧` summary (no orphaned turns, no `___CTX_GATE_` scaffolding).

**Three kinds of fact; two travel.** *Message-derived* (tool results, files the coder wrote or read, checks it ran) and *harness-executed* (cria's call, the harness's run) work on any topology — prefer them. *cria-disk* (`os.path.isdir`, `os.walk`, `open()` on a harness path) works only co-located and must be converted.

- **A lexical path check is not disk access.** `dirguard`'s containment test is a string comparison, valid against a remote workspace; never blank it for unreachability, or the bound on the coder's file tools disappears.
- **A mechanism that cannot reach its subject must SAY so.** `os.path.isdir` on a foreign path returns False, so disk-derived guards conclude "nothing there" and go quiet: correct by #11b, catastrophic in aggregate, and invisible from outside (#12).
- **The conversion.** `cria/wsview.py` alone answers "what is in the coder's workspace", filled by a bounded `python3` survey the harness runs, riding on commands cria already sends (lowered `write_file`/`edit_file`/`list_dir`, the completion gate) and stripped from the result before anything, the model included, sees it. `toolpath` likewise asks what the coder's shell resolves. Known exception: `depsurface` reads dependency sources from cria's own caches (`~/.m2`, `~/.cargo`, `~/.gem`, the Go module cache, declared cache roots), right only when co-located; elsewhere it finds nothing and abstains (#11b).
- **Answers are three-valued.** `True`, `False`, `None` (not yet answered). Each caller picks its safe direction: a probe is KEPT when unsure (a dropped check reads like a pass), advice is WITHHELD when unsure (naming a command that may not exist breaks #5b). Never collapse `None` into `False`.
- **No synchronous channel.** cria is an HTTP server the harness drives; it can ask only by putting a command in its reply and reading the answer on the next request. A mid-decision predicate reads what an earlier turn gathered, and an unanswered question is remembered for the next survey. Anything that must run a command inside one request cannot be done at all (the planner's gather shell was replaced by view-backed `list_dir` / `grep_files` / `read_file`).
- **cria never deletes on a filesystem it does not own.** Probe-artifact cleanup is a harness-executed Python program inside the same gate, before evidence and the final survey are returned. It removes only positively owned private auxiliary resources (exclusive allocation credentials, descriptor identities) and reports removals and failures apart from checker output. New workspace files are not proof of probe ownership; concurrent writers and native build outputs survive. Compiler scratch is redirected into private auxiliary storage; source, cwd and build argv are unchanged. Never attach a delayed deletion to a later coder action. External transport spools have their own exactly owned cleanup.

### 24. An invariant that must hold on the WIRE belongs at the wire
A property that must be true of the serialized body (role alternation, no orphan tool messages, no malformed historical tool calls) is enforced at the final pre-serialization boundary, not at call sites. Carry the intent to the wire as an internal hint, apply it there, strip it, and keep it opt-in so unaffected models get byte-identical bodies. Fix the path that produced the incident: captured bodies record their phase, so identify the failing path before changing code, tests or docs.

---

*Rule numbers are cited throughout the code and tests and never change.*
