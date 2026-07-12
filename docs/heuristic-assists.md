# Heuristic Assists — the catalog

[< Spec Index](index.md) · explanatory overview: [shephard.md](shephard.md) · the why + code pointers: [local-coder-massaging.md](local-coder-massaging.md)

Every assist Shephard applies to keep a small local model (9B-class) + an agent harness doing real agentic coding, in five families. **Name first, one line each** — the "why", thresholds, and code pointers live in [local-coder-massaging.md](local-coder-massaging.md); the conceptual overview in [shephard.md](shephard.md).

- **Nudges** — in-context directives that steer the *model* (it sees them) to break loops and force progress.
- **Massages** — silent repairs of the model's *output* so the *harness* accepts it (the model never knows).
- **Context shaping** — managing what the model sees and how much, so it fits the window and stays grounded.
- **Probes** — Shephard makes its OWN read-only tool calls for ground truth; verify by *doing*, not reading.
- **Reasoned guidance** — the PRIMARY response to a stuck loop: hand the reasoner FRESH ground truth (the repeated failing action + its output, the actual files re-read from disk, the lint probe) and have it author the coder's next step. Fires whenever there's ANY real signal — a repeated action counts even when lint is CLEAN (the action-loop case the old dirty-only gate dropped to a bare nudge); a groundless call (clean probe and no repeated action — a file that merely EXISTS is not signal) is skipped, because reasoning over nothing hallucinates. Canned directives remain only as the reasoner-unavailable fallback.

## Nudges

In-context directives the model SEES. Five are **loop detectors whose primary response is now [reasoned guidance](#reasoned-guidance)** — Repetition, Thrash, Context-reset, Tunnel-vision, and Read-without-write; the canned `[MARKER]` text below is only the reasoner-unavailable fallback, and they reappear under Reasoned guidance as triggers (not a second mechanism).

- **Repetition guard** — same tool + same args 3× → a grounded reasoner redirect authored from the repeated call + its actual output (the `[STOP — REPETITION DETECTED]` directive is now the reasoner-unavailable fallback).
- **Thrash guard** — same goal via varying commands, still failing (24-call window, productivity-gated) → force a diagnosis. (A former same-file-failing-3× guard was removed — it never earned its keep; interleaved partial successes reset its streak.)
- **Context-reset guard (reasoned excise)** — a repeat-loop past 4× → excise its own calls+outputs from context (collapsed to ONE marker that keeps the last result/error), then the reasoner rebuilds a SMALL clean working context from FRESH ground truth — the touched files re-read from disk, the repeated failure, and the ONE next step — replacing the canned reframe that used to point back at the now-stale transcript. Falls back to the canned excise when the reasoner is unavailable. Fires early on purpose: a weak model ignores the "stop" nudge, and leaving the repeated calls in its context lets it copy the pattern back out — so the context is cleaned before the loop bloats to 6+ copies.
- **Rumination guard** — a mid-generation self-doubt spiral OR a reasoning run that overruns the token budget aborts the stream and re-prompts. Example: 48,882 reasoning tokens against an 8,192-token budget aborts even with zero doubt-markers.
- **Loop-text guard** — the same assistant preamble 3× (stopword-stripped, stemmed) → re-prompt at turn end.
- **Cyclic-pattern guard** — a 2–4-step tool cycle repeated 3× → block the call and redirect.
- **Dangling-intent guard** — "now I'll do X" then stops with no tool call → re-prompt to actually act.
- **Announce-without-act escalation** — repeated stalling → escalate to "one tool call, no prose."
- **Quality gate** — empty/short/echo/refusal response → re-prompt before spending a verifier call.
- **Tool-call constraint** — a bail/stall retry forces a valid (or specific) tool call at the sampler.
- **write_file-default steering** — the prompt makes whole-file write the default; apply_patch Add disabled.
- **Tunnel-vision detector** — a write or edit always counts as progress and clears the streak, so only passive revisits (re-reading, re-fetching, or re-searching the same target while reaching nothing new) accumulate toward the forced step-back. Example: ten `web_fetch`s of the same URL fire it, but fifteen `write_file`s to `lambda_handler.py` do not.
- **Read-without-write loop** — 12+ reads with zero writes this turn → `[GATHERING WITHOUT ACTING]`: name what you know, then make the first change.
- **Search-rumination guard** — a re-worded repeat of a search already made this turn → HTTP 400 before the network hit.
- **Domain-fetch steer** — a search query that names a bare domain (`api.handle.me`, not a source filename) → the first result gets a "fetch `https://<domain>` directly and parse it" hint, and a *repeat* domain search's 400 carries the same steer. Redirects a coder that circles a domain in web_search toward actually curling it.
- **Fetch exact-repeat guard** — an identical external fetch (url + find + cursor) this turn → HTTP 400; internal hosts exempt.
- **Failing-fetch guard** — N consecutive external fetches with no 2xx → a soft "stop guessing URLs" nudge; localhost exempt.

## Massages

- **write_file → shell base64 (bidirectional)** — `write_file` lowered to `printf … | base64 -d > path` (byte-exact, escaping-proof); the recorded shell call re-presented as `write_file` so the model sees only its own tool.
- **Leaked-call recovery** — tool calls emitted as text (Hermes `<tool_call>` JSON, XML `<function=…>`, Gemma-fable `<|tool_call>call:NAME{k:<|"|>v<|"|>}<tool_call|>`) → promoted to real calls; the Gemma path also strips its `<|channel>thought…` wrapper from reasoner prose.
- **Shell-name rewrite** — `ls`/`cat`/`grep`/`git` emitted as tool names → proper `shell` calls.
- **exec_command array fix** — `cmd` given as `["bash","-lc",…]` → routed to `shell` (else it execs a `[`).
- **Shell-args normalization** — a string command wrapped to `[bash,-lc,cmd]`; a double-wrapped array unwrapped to the inner command.
- **edit_file → apply_patch** — an `edit_file`/`str_replace` find-replace → a native `apply_patch` Update hunk.
- **read_file normalization** — a `read_file(path, range)` → a `shell` `cat`/`sed`.
- **Malformed-JSON repair** — botched `write_file` args (raw newlines/quotes) → path + content recovered.
- **Tool-argument normalization** — string→JSON parse, dict passthrough, else wrapped `{value}`; alternate call shapes (`{function:{…}}` vs `{name,args}`) unified.
- **Fenced-JSON tolerance** — tool args / control-model JSON wrapped in ``` fences → extracted.
- **apply_patch normalize** — unified diff → native; missing `+`/`-`/space prefixes repaired; end marker added.
- **apply_patch hunk-header normalize** — `@@ -L,N +L,N @@` line-numbers collapsed, anchor text preserved.
- **apply_patch wrapper collapse** — multiple `*** Begin/End Patch` wrappers (one per file) → one wrapper.
- **apply_patch Add-File block fix** — Add-File blocks with stray `@@`/`-` lines stripped to `+` content only.
- **apply_patch Add → write_file** — a pure file-creating patch → a robust whole-file write.

### Recovery re-prompts

Unlike the silent massages above, these fire a corrective re-prompt the model SEES after a specific tool output fails mechanically — grouped here because they handle the same "bad output" concern, not because they're silent.

- **Malformed-tool-call recovery** — an unparseable `<tool_call>` (bad quote/newline escaping in a multi-line command) is re-prompted to re-issue cleanly, steering multi-line work to `write_file`. Example: a `shell` call whose heredoc broke the JSON is bounced back for a clean write_file.
- **Failed-patch → rewrite** — a failed apply_patch forces a whole-file `write_file` (no size gate) so the model can't keep re-patching a stale file, and that force is released the instant the output-truncation guard fires so the incremental-edit remedy can take over. Example: after "patch failed to apply" the next turn is locked to `write_file`, but once that write truncates at the token cap the lock drops so the model can append the rest with `edit_file`.
- **Output-truncation guard** — a `write_file` cut off at the output-token cap (`done_reason`/`finish_reason == "length"`) is aborted rather than silently saved as a broken partial, and re-prompted to build the file in small pieces with `edit_file`. Example: a 1,446-byte handler truncated mid-function is steered to append the rest incrementally instead of rewriting the whole file into the same cap.

## Safety guards (hard tool-boundary refusals)

A *mechanical* refusal at the tool boundary — the one class of intervention that reliably stops a weak model, since it holds even under `--yolo` / danger-full-access where steering text does not. Narrow by design: it refuses only a shape that is never a legitimate intent and lets ordinary work through. (Note: guarding against *intentional* destruction — a model that "starts fresh" with `rm -rf .` / `find . -delete` — is deliberately NOT done here (a shell blocklist was prototyped this cycle and removed); a per-command blocklist is whack-a-mole, endlessly incomplete against `python -c "shutil.rmtree('.')"`, `mv * …`, `>`, `dd`, etc. The real protection is a **recoverable workspace** — the task repo is a git repo, so any wipe is a `git checkout` away — not a growing list of forbidden commands.)

- **Destructive-overwrite guard** — a `write_file` that would replace a substantial file (≥200 B) with an empty, tiny (<30 B), or truncated fragment is refused and the original left intact, catching the token-truncated write that silently clobbers good code while a complete smaller refactor still lands. Example: overwriting a 600-byte handler with a 7-byte `def h():` stub is rejected, but replacing it with a complete shorter rewrite goes through.

## Context shaping

- **Own concise base prompt** — ~20 lines, write_file-first; replaces the harness's ~351-line one.
- **Tool-menu trim** — ~9 curated tools instead of the full ~120.
- **Tool cheat-sheet** — plain-language per-tool usage + examples in the prompt (built-in schemas synthesized).
- **Window auto-detect + derived budget** — read real `n_ctx` from `/props`; budget = window − reserves.
- **Real-token calibration** — learn the model's real chars→token ratio via a rise-fast/fall-slow EWMA (~1.8× initial, up to 3.5×); budget against truth, not chars/4, covering BPE undercount on code/JSON.
- **Transcript pass-through** — every turn renders VERBATIM (no per-turn collapse/fold, no stale-read drop, no output supersession); only the *current* turn's reasoning is kept (older reasoning dropped). Reads, errors, and outputs survive intact because nothing is elided — the LLM summary carries older context. Loop-excision still removes a *detected loop's* own calls.
- **Model-generated compaction** — on overflow (incoming or outgoing) or a harness compaction call: chunk the history, have the compactor LLM summarize EACH chunk in free-form prose, then one final unifying pass. The model summarizes what it sees — no deterministic state-extraction schema. Replaces the old extract→merge→refine pipeline ([compaction-reference.md](compaction-reference.md), now historical).
- **Verbatim recent tail** — all steps since the last summary pass through exact (never summarized), so the freshest opaque values (addresses, hashes, IDs) survive intact even when older mentions were summarized.
- **Post-compaction opaque-string warning** — the handoff is labelled post-compaction so a resuming model treats *summarized* high-entropy strings as suspect and re-verifies them, instead of trying to regex-pin every opaque type.
- **Boilerplate strip** — the ~3K-token Codex developer boilerplate (permissions/apps/skills) is dropped before summarizing (it demonstrably derails the summarizer) and from the verbatim render.
- **Active-turn compaction (incremental)** — summarize a long turn's middle; reuse a rolling summary keyed by content hash so it isn't re-summarized every overflow (no GPU-pegging storm).
- **Compaction hardening** — per-chunk timeout + `<think>`-strip on the summarizer so a small compactor can't wedge a turn.
- **Persist via native compaction** — feed the harness honest `total_tokens` + the real probed `n_ctx` so its *own* stock usage-driven compaction fires; no special-casing.
- **Loop-excision inline collapse** — replace an excised loop with ONE coherent marker ("tried N times, unchanged"), never a gap that reads as "I haven't acted yet."
- **System-prompt compression** — bound an oversized incoming system prompt to budget: keep head + tail, elide the middle.
- **Overflow re-trim** — a context-overflow error → re-trim to the server's real numbers and retry, no crash.
- **Last-resort drop** — drop oldest messages (keep the request, strip orphan tool-results) as the fit floor.
- **Oversized-output guard** — output over a dynamic ceiling (% of window) losslessly reduced, or omitted with a "re-run narrower / grep / find=" pointer.
- **Semantic truncation** — never blanket char-truncate; per-tool rules preserve meaning (digits/caps/symbols kept).
- **web_fetch navigation** — paginate (`cursor`, line-snapped), `find=` a section (MIME-aware), real HTTP status + body.
- **Guard observability** — loop-guard firings logged (not just queued to the TUI) so a firing guard never looks dead.
- **Browser User-Agent** — auto-add a real User-Agent so sites don't block `curl`.
- **Better errors** — patch/network errors rewritten to say what to try next.

## Probes

- **Language-aware syntax floor** — always-available `py_compile` / `node --check` over disk files → the exact `file:line` for parse errors the model can't localize.
- **Repo probe discovery** — inventory the repo's ecosystems (JS/TS, Python, Rust, Go, JVM, .NET, PHP, Ruby, Elixir) → a ranked list of SAFE diagnostic commands.
- **Package-script vetting** — read `package.json` / Make / etc. scripts and vet each body (reject install/mutate/watch/service) before offering it.
- **Safe-command ranking** — confidence → run-first tier (typecheck/build → lint → unit → full → e2e) → value → cost; package manager chosen from lockfiles, tool confidence raised by config files (`tsconfig.json`, `ruff.toml`, `mypy.ini`, …).
- **Config/glue probes** — `shellcheck` (shell), `actionlint` (CI workflows), `terraform validate` (infra), anchored at the repo root.
- **Bounded probe runner** — run the top-ranked safe probes with a hard timeout, deadlock-free capture, never mutating the workspace.
- **Diagnostic parsers** — rustc/cargo, tsc, ESLint, pytest, and generic `file:line` output → structured findings + a one-line summary.
- **Command safety classifier** — unwrap wrappers (`sudo`/`npx`/`poetry run`/…), reject installers/mutators/watch, identify probe kind — never fooled by shell syntax, filenames, or branch names.
- **Ground-truth completion gate** — on a "done" claim, run the syntax floor + the top probe **AND the top test probe** (discovery ranks typecheck/lint above tests, so a top-1-only run green-lit a repo whose tests failed — a false completion sailed through that way); broken code or failing tests block completion and the exact `file:line` becomes the re-prompt. The gate now also logs a truth-capture line (probes run, findings, floor-clean) so a passing gate is auditable, not silent.
- **Completion gating** — a coder's no-tool-call "done" turn is accepted only if it (a) changed files this task, (b) its code passes the repo's own diagnostics, and (c) the reasoner completion critic finds the work done. Example: a turn that wrote nothing, or whose `py_compile` fails, or whose critic flags a shortcut, is re-prompted instead of completing (the old small-model text-shape "verifier" was removed for false-negativing on finished work and trapping a done coder in a done→"you did nothing"→`ls` loop).
- **Ground-truth gate** — the (a) leg of that gate: a coder turn ends only if it actually changed a file on disk this task. Example: a turn that only ran `cat`/`ls` then claimed done is re-prompted to make a real change.

## Reasoned guidance

- **Reasoner role routing** *(built)* — a separate, cheap local "light reasoner" role, routable with failover, distinct from the coder.
- **Structural stuck-triggers** *(built)* — the tunnel-vision / read-without-write / repeated-failure detectors decide *when* guidance is needed.
- **Plan-first** *(built)* — on a new user task the reasoner is engaged FIRST to draft a short small-step plan (small steps, one thing at a time), pinned at the top of the coder's context for the whole turn. Cached per task → one gather-and-plan pass per turn, not per step. The planner **GATHERS before it plans**: it's given a READ-ONLY tool subset (`exec_command` read-only-enforced, `read_file`, `web_fetch`, `web_search`) and loops — inspect the working dir, read files, fetch docs/search — until it emits a plan **grounded in what it actually found**, not assumptions. Read-only by construction (a write/mutate command is refused — building is the coder's job); no cap on gather calls (it self-terminates by producing the plan, with a repeated-call stuck guard). Leaked dialects (Gemma's `<|tool_call>…`) are recovered by the shared parser, so quirky reasoners gather too.
- **Completion critic** *(built)* — one reasoner call reviews the actual work (task + recent tool outputs + the fresh lint/test probe results, with tests that DID NOT RUN counted as not-passing) for shortcuts, false-success, and unmet requirements, then re-prompts while its flagged issues keep CHANGING (the model is converging) and stops when they repeat (stuck) or hit a generous ceiling. Example: a suite that fails to import is flagged as not-passing and re-prompted, but a coder that re-emits byte-identical broken code twice is cut off after ~2 tries.
- **Honest incompletion** *(built)* — when the completion gate gives up (the model stalled or hit the re-prompt ceiling) with issues still unresolved, its verdict is written into the turn's FINAL message rather than only a TUI nudge, so a stuck run reports itself unfinished instead of returning a clean-looking completion. Example: a run whose tests never passed now ends with `⚠️ Stopping with UNRESOLVED issues: tests fail — name 'context' is not defined` instead of an empty `task_complete`.
- **Loop → ground truth → reasoned guidance** *(built)* — the canned loop directives are soft prompt text a 9B ignores. So when ANY of the five loop guards fires (repetition / forced-diagnosis / tunnel-vision / context-reset / read-without-write), the response is **detect → gather ground truth → reason**. One shared gatherer (`ground_truth::GroundTruth`) assembles the FRESH signal: the repeated failing action + its actual output (surfaced from the loop detector), the files the model touched this turn re-read from disk, and the dirty-only lint/syntax probe. The reasoner is called whenever there is ANY real signal (`has_signal()`) and authors the coder's next instruction from it:
  - **action-loop** (clean lint) → the *repeated action* is the ground truth: "you keep running `cat` on a directory and getting 'Is a directory' — use `ls`", or "this search returns the same result — stop and write the code". This is exactly the case the old dirty-lint-only gate dropped to a bare nudge.
  - **dirty lint** (a real `file:line`) → name the exact file:line and the one targeted fix (don't rewrite blind).
  - **no signal at all** (clean lint AND no repeated action) → the reasoner is NOT called: a groundless reasoner hallucinates (observed live: it told a coder to "add the X-API-Key header" for what was actually a runtime `TypeError`), so the detector's canned directive stands. (We never ground on a one-off *past* failing output either — a later action may have fixed it, the stale-signal footgun — but an ACTIVE repeat proves its output is current.)
  
  Fallbacks in order: reasoner output → the raw dirty-lint `file:line` → the detector's canned directive. Bounded (≤6/task).
- **Context rebuild on flail (excise)** *(built)* — the TOP escalation (a loop past the excision threshold): after the loop's own turns are excised from context, instead of a canned reframe pointing back at the now-STALE transcript, the reasoner rebuilds a SMALL (~150-word; 4 labeled parts: task / real state / why stuck / one next step) clean working context from the same fresh ground truth (repeated action + files re-read from disk). Supersedes the generic redirect that turn; falls back to the canned excise when the reasoner is unavailable.
- **Course-change reset** *(built)* — when a loop guard fired this turn yet the coder returns a real tool call, the pivot is honored (loop nudges paused for a short grace window, redirect budget reset) only if the action is objectively NEW — its edit's path+content fingerprint wasn't already tried this turn — and the reasoner confirms a genuine, non-restart change of course. Example: re-writing `lambda_handler.py` with byte-identical content is rejected before any reasoner call, while a different version that fixes the API path earns the grace window.
- **Escalation ladder** *(forward)* — after K unheeded canned nudges, escalate to the reasoner / a probe / a hard stop — a guard that has fired 50× without effect is not a guard.
