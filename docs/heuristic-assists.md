# Heuristic Assists — the catalog

> **Copied from the `codex-local` research vehicle, which remains the source of
> truth.** Re-sync when the catalog there changes. Overview: [shephard.md](shephard.md);
> the "why" + code pointers live in codex-local:
> [local-coder-massaging.md](../../codex-local/docs/spec/local-coder-massaging.md).

[< Spec Index](../../codex-local/docs/spec/index.md) · explanatory overview: [shephard.md](shephard.md) · the why + code pointers: [local-coder-massaging.md](../../codex-local/docs/spec/local-coder-massaging.md)

Every assist Shephard applies to keep a small local model (9B-class) + an agent harness doing real agentic coding, in five families. **Name first, one line each** — the "why", thresholds, and code pointers live in [local-coder-massaging.md](../../codex-local/docs/spec/local-coder-massaging.md); the conceptual overview in [shephard.md](shephard.md).

- **Nudges** — in-context directives that steer the *model* (it sees them) to break loops and force progress.
- **Massages** — silent repairs of the model's *output* so the *harness* accepts it (the model never knows).
- **Context shaping** — managing what the model sees and how much, so it fits the window and stays grounded.
- **Probes** — Shephard makes its OWN read-only tool calls for ground truth; verify by *doing*, not reading.
- **Reasoned guidance** *(mostly forward)* — on a stuck trigger, query the light reasoner for a context-aware redirect.

## Nudges

- **Repetition guard** — same tool + same args 3× → a STOP directive.
- **Forced-diagnosis guard** — same file/goal failing 3× → read the failure before acting.
- **Thrash guard** — same goal via varying commands, still failing (24-call window) → force a diagnosis.
- **Context-reset guard** — a loop ignored past 6× → excise it from context and reframe the task.
- **Rumination guard** — a self-doubt spiral mid-generation → abort the stream and re-prompt.
- **Loop-text guard** — the same assistant preamble 3× (stopword-stripped, stemmed) → re-prompt at turn end.
- **Cyclic-pattern guard** — a 2–4-step tool cycle repeated 3× → block the call and redirect.
- **Dangling-intent guard** — "now I'll do X" then stops with no tool call → re-prompt to actually act.
- **Announce-without-act escalation** — repeated stalling → escalate to "one tool call, no prose."
- **Quality gate** — empty/short/echo/refusal response → re-prompt before spending a verifier call.
- **Completion verifier** — a small model judges "done" claims; only a real Complete ends the turn.
- **Ground-truth gate** — a coder turn ends only if it actually changed files.
- **Tool-call constraint** — a bail/stall retry forces a valid (or specific) tool call at the sampler.
- **Failed-patch → rewrite** — a failed patch pins the file and forces a whole-file write_file rewrite.
- **write_file-default steering** — the prompt makes whole-file write the default; apply_patch Add disabled.
- **Tunnel-vision detector** — N calls with no new well-defined target (footprint stalled) → force a step-back.
- **Read-without-write loop** — 12+ reads with zero writes this turn → `[GATHERING WITHOUT ACTING]`: name what you know, then make the first change.
- **Search-rumination guard** — a re-worded repeat of a search already made this turn → HTTP 400 before the network hit.
- **Fetch exact-repeat guard** — an identical external fetch (url + find + cursor) this turn → HTTP 400; internal hosts exempt.
- **Failing-fetch guard** — N consecutive external fetches with no 2xx → a soft "stop guessing URLs" nudge; localhost exempt.

## Massages

- **write_file → shell base64 (bidirectional)** — `write_file` lowered to `printf … | base64 -d > path` (byte-exact, escaping-proof); the recorded shell call re-presented as `write_file` so the model sees only its own tool.
- **Leaked-call recovery** — tool calls emitted as text (Hermes `<tool_call>` JSON, XML `<function=…>`) → promoted to real calls.
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

## Context shaping

- **Own concise base prompt** — ~20 lines, write_file-first; replaces the harness's ~351-line one.
- **Tool-menu trim** — ~9 curated tools instead of the full ~120.
- **Tool cheat-sheet** — plain-language per-tool usage + examples in the prompt (built-in schemas synthesized).
- **Window auto-detect + derived budget** — read real `n_ctx` from `/props`; budget = window − reserves.
- **Real-token calibration (EWMA)** — learn the model's real chars→token ratio, rise-fast/fall-slow; budget against truth, not chars/4.
- **Token-estimate safety factor** — budget at ~1.8× to cover BPE undercount on code/JSON.
- **Transcript trim** — keep the active turn, collapse older turns, drop stale reads, keep errors.
- **Stale-read detection** — drop reads superseded by later writes; keep the latest per target.
- **Error stickiness** — always preserve any tool output with `success=false`, regardless of age.
- **Active-turn compaction (incremental)** — summarize a long turn's middle; reuse a rolling summary so it isn't re-summarized every overflow (no GPU-pegging storm).
- **Compaction hardening** — per-chunk timeout + fence-strip the extractor so a small compactor can't wedge.
- **Persist via native compaction** — feed the harness honest `total_tokens` + the real probed `n_ctx` so its *own* stock usage-driven compaction fires; no special-casing.
- **Loop-excision inline collapse** — replace an excised loop with ONE coherent marker ("tried N times, unchanged"), never a gap that reads as "I haven't acted yet."
- **System-prompt compression** — bound an oversized incoming system prompt to budget: keep head + tail, elide the middle.
- **Overflow re-trim** — a context-overflow error → re-trim to the server's real numbers and retry, no crash.
- **Last-resort drop** — drop oldest messages (keep the request, strip orphan tool-results) as the fit floor.
- **Oversized-output guard** — output over a dynamic ceiling (% of window) losslessly reduced, or omitted with a "re-run narrower / grep / find=" pointer.
- **Semantic truncation** — never blanket char-truncate; per-tool rules preserve meaning (digits/caps/symbols kept).
- **web_fetch navigation** — paginate (`cursor`, line-snapped), `find=` a section (MIME-aware), real HTTP status + body.
- **Current-file pin** — live on-disk contents pinned so the model edits the real file.
- **Workspace manifest pin** — a disk-derived list of working-dir files re-pinned every request; survives compaction / context-reset / last-resort drop ("don't start over; read these, don't re-create under new names").
- **Guard observability** — loop-guard firings logged (not just queued to the TUI) so a firing guard never looks dead.
- **Browser User-Agent** — auto-add a real User-Agent so sites don't block `curl`.
- **Better errors** — patch/network errors rewritten to say what to try next.

## Probes

- **Language-aware syntax floor** — always-available `py_compile` / `node --check` over disk files → the exact `file:line` for parse errors the model can't localize.
- **Repo probe discovery** — inventory the repo's ecosystems (JS/TS, Python, Rust, Go, JVM, .NET, PHP, Ruby, Elixir) → a ranked list of SAFE diagnostic commands.
- **Package-script vetting** — read `package.json` / Make / etc. scripts and vet each body (reject install/mutate/watch/service) before offering it.
- **Safe-command ranking** — confidence → run-first tier (typecheck/build → lint → unit → full → e2e) → value → cost; package manager chosen from lockfiles.
- **Bounded probe runner** — run the top-ranked safe probes with a hard timeout, deadlock-free capture, never mutating the workspace.
- **Diagnostic parsers** — rustc/cargo, tsc, ESLint, pytest, and generic `file:line` output → structured findings + a one-line summary.
- **Command safety classifier** — unwrap wrappers (`sudo`/`npx`/`poetry run`/…), reject installers/mutators/watch, identify probe kind — never fooled by shell syntax, filenames, or branch names.
- **Ground-truth completion gate** — on a "done" claim, run the syntax floor + top probe; broken code blocks completion and the exact `file:line` becomes the re-prompt.

## Reasoned guidance

- **Reasoner role routing** *(built)* — a separate, cheap local "light reasoner" role, routable with failover, distinct from the coder.
- **Structural stuck-triggers** *(built)* — the tunnel-vision / read-without-write / repeated-failure detectors decide *when* guidance is needed.
- **Reasoner-assisted redirect** *(forward)* — on a stuck trigger, query the reasoner (grounded by a probe) to infer what the model is trying to do and inject a concrete new path, instead of a canned nudge.
- **Escalation ladder** *(forward)* — after K unheeded canned nudges, escalate to the reasoner / a probe / a hard stop — a guard that has fired 50× without effect is not a guard.
