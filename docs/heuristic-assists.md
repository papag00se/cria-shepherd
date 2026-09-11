# Heuristic Assists — implemented in cria

A terse index of the assists cria **actually implements** today, in five families. One line each. Design rationale and code pointers live in [local-coder-massaging.md](local-coder-massaging.md); the conceptual overview in [shephard.md](shephard.md); still-unbuilt levers in [port-fidelity-audit.md](audits/port-fidelity-audit.md).

## Nudges — directives/refusals the model sees

- **Repetition guard** — same tool + args 3× in-window → run the repo's checks, then a grounded reasoner redirect (canned fallback).
- **Wheel-spin guard** — same file rewritten 5× in-window → probe + steer.
- **Rumination guard** — a mid-generation self-doubt spiral OR reasoning over the token budget → abort the stream and re-prompt.
- **Output-truncation guard** — a `write_file` cut off at the output-token cap → refuse the partial, steer to incremental `edit_file`.
- **No-tools (LEG0) nudge** — a no-tool-call "done"/prose turn → act-first nudge (once per step), then the gate.
- **Periodic gate** — every 15 acting coder turns → insert the repo's fresh check results as ground truth.
- **Search exact-repeat guard** — an identical/re-worded search this session → HTTP 400 before the network hit.
- **Domain-fetch steer** — a search naming a bare domain → "fetch `https://<domain>` directly" hint.
- **Fetch exact-repeat guard** — an identical external `web_fetch` (url + find + cursor) this session → HTTP 400; internal hosts exempt.
- **Failing-fetch guard** — 3 consecutive non-2xx external fetches → a "stop guessing URLs" nudge; localhost exempt.
- **Shared-install guard** — a package install whose destination is the user/system environment (`pip install`, `npm -g`, `gem`/`cargo`/`go install`, `apt`/`brew`) → refused with the in-project venv route; project-local installs (`npm install`, `composer require`, `cargo add`) pass untouched.
- **Missing-dependency note** — beside the latest real loader/compiler failure, quote the exact unresolved package and distinguish an undeclared dependency from an invalid package name. For Go, the note explicitly withholds `go get` as a remedy until authoritative package source establishes that the import path exists.
- **Dependency refusal events** — preserve session-scoped raw resolver coordinates, tool provenance, and event order across npm/pnpm/Yarn/Bun, pip/uv/Poetry, Cargo, Go, Maven/Gradle, NuGet, Composer, RubyGems/Bundler, and Hex/Mix; a later observable exact success supersedes the current refusal without deleting its history. Exact-name matching only triggers the existing whole-action reasoner judgment; it never vetoes semantically. See [dependency refusal events](refusal-events.md).

## Massages — silent output repair so the harness accepts it

- **write_file / edit_file ↔ shell round-trip** — lowered to a byte-exact base64 heredoc write; the recorded shell call re-presented as the original tool.
- **Leaked-call recovery** — tool calls emitted as text (Hermes `<tool_call>`, XML `<function=…>`, Gemma-fable `<|tool_call>…`) → real calls; Gemma `<|channel>` thinking stripped.
- **Native tool-call sentinel strip** — `<|tool_call_start|>…<|tool_call_end|>` pairs + orphans stripped from content (templates that leak their own call sentinels).
- **Reasoning-channel call recovery** — a COMPLETE call the model left in `reasoning_content` (the one channel llama.cpp's parser never reads) → a real call. Only when the turn is already lost (no text, no `tool_calls`), the call is terminal and unfenced, every argument is a literal the model typed, and the name + required args are on the request's own menu. Measured 2026-08-03: 80 lost replies across 127 sessions, 68 recovered; the worst-affected model lost 10.7% of its coder turns this way.
- **Shell-name rewrite** — `ls`/`cat`/`grep`/`git`/… emitted as tool names → proper `shell` calls (full alias table).
- **exec_command array fix** — `cmd` as `["bash","-lc",…]` → routed to `shell`.
- **Shell-args normalization** — a string command wrapped to `[bash,-lc,cmd]`; a double-wrapped array unwrapped.
- **read_file normalization** — `read_file(path, range)` → a `shell` `cat`/`sed`.
- **edit_file → apply_patch** — a find/replace → a native `apply_patch` Update hunk (when the harness runs apply_patch).
- **Tool-argument normalization** — string→JSON parse, dict passthrough, `{value}` wrap; `{function:{…}}` vs `{name,args}` unified.
- **Fenced-JSON tolerance** — tool args wrapped in ``` fences → extracted.
- **Malformed-JSON repair** — botched `write_file` args (raw newlines/quotes) → path + content recovered.
- **Missing-content refusal** — a `write_file` whose required `content` is absent or null → refused, not lowered as an empty write (the byte-exact write truncated a working file to zero and reported success); an intentional empty string still writes. Sibling of the `new_string` refusal on the edit path.
- **Double-escaped-newline repair** — a file written as one physical line with literal `\n` → decoded.
- **apply_patch normalize** — unified diff → native; missing `+`/`-`/space prefixes repaired; hunk headers collapsed; multiple wrappers merged; a pure Add-File patch → a whole-file write.
- **Malformed-tool-call recovery** (re-prompt) — an unparseable `<tool_call>` → re-prompted to re-issue cleanly, steering multi-line work to `write_file`.
- **Failed-patch → rewrite** (re-prompt) — a failed apply_patch forces a whole-file `write_file`, released the instant the truncation guard fires.

## Context shaping — what the model sees and how much

- **Own concise coder prompt** — cria's `coder_system.txt` leads, replacing the harness's bloated system prompt.
- **Tool-menu focus** — curate to the coding-essential tools; synthesize lean `read_file`/`list_dir`/`write_file`/`edit_file`/`web_fetch`/`web_search`.
- **Tool cheat-sheet** — plain-language per-tool usage generated from the live menu, carried into cria's system message.
- **Window auto-detect + derived budget** — read real `n_ctx` from `/props`; budget = window − output reserve.
- **Real-token calibration** — a rise-fast/fall-slow EWMA learns the model's chars→token ratio (≈1.8× → 3.5×) so the budget is against truth, not chars/4.
- **content_reduce** — MIME-aware lossless-first reduction of an oversized tool output (HTML→text, JSON minify) before it blows the window.
- **Self-compaction** — token-triggered: roll the old transcript middle into a retrospective `⟦ctx:rollup⟧`, keeping the tail verbatim and giving the writer the pinned original task. Three independent fail-closed judgments require exact `RETROSPECTIVE`, `PRESERVES`, and `FAITHFUL` verdicts for no forward plan, full task scope, and fidelity to transcript/disk/check facts (including decisive negative evidence). Rejection retains verbatim history and suppresses a retry until a new token band accumulates. Rare rollup refolds pass through the same gate.
- **Reducible internal evidence** — compactor, briefing-validator, and steer-author transcripts ride as independently reducible evidence turns between a small introduction and the final active question. With no pressure their bytes are unchanged; under pressure the single context floor can fold/drop whole evidence blocks with its existing labelled stand-in instead of knowingly sending an irreducible oversized two-message body. The inspecting author's task/current-facts/question packet uses the existing exact wire pin, so a later forced-answer closer cannot make it droppable. This restores answer capacity and retention; it does not establish better reasoner judgment.
- **Completion compaction** — on `loop.done`, summarize the finished work into a `⟦ctx:briefing⟧` envelope that rides in the closing message, so a follow-up resumes on top of it.
- **Overflow re-trim + retry** — a context-overflow error → re-trim to the server's real numbers and retry only when re-preparation changes the body; a byte-identical body is never resent to a known rejection. The immediate forced-off compactor retry carries typed inner no-change provenance and is suppressed only when normal post-`_prep` bytes are still identical; changed-wire, empty, transient, and non-context outcomes retain their ordinary retries.
- **Last-resort drop + state synthesis** — drop oldest droppable turns (strip orphan tool-results) as the fit floor, replacing them with a protected `⟦ctx:compacted⟧` note of the files they modified. The loop carries the exact session-pinned root task to this final wire boundary, so an untagged environment banner cannot be mistaken for the task and protected in its place.
- **Anchor protection** — the briefing envelope, gate output, pinned task, current facts, and compacted-state note are never silently trimmed. On the single-item path refreshed facts follow historical rollups so authority and recency agree.
- **Rejected-draft provenance** — a large write/edit payload that validation refused is removed from the live tool argument but preserved verbatim in the refusal result under `⟦ctx:rejected-candidate⟧`; it is explicitly a rejected draft that never reached disk, not current file content.
- **web_fetch navigation** — cria fetches in-process: structural JSON/YAML reduce, top-level-keys outline, `find=`/`cursor` paging, `$ref` inline, real HTTP status.
- **Browser User-Agent** — cria's fetches send a real browser UA so sites don't block `curl`.
- **Reframed harness preamble** — the harness's AGENTS/env preamble re-presented in cria's clean voice.

## Probes — ground truth by doing

- **Language-aware syntax floor** — `py_compile`/`node --check`/`php -l`/`ruby -c` + a TOML/strict-JSON config floor over disk files → exact `file:line`.
- **Repo probe discovery** — inventory 9 ecosystems (JS/TS, Python, Rust, Go, JVM, .NET, PHP, Ruby, Elixir) → ranked SAFE diagnostic commands. Every workspace-survey tree record, including folded-directory drain records, shares one byte bound; exhaustion closes an accepted `complete=0` survey rather than producing a count-mismatched partial inventory.
- **Package-script vetting** — read `package.json`/Make/etc. scripts and reject install/mutate/watch/service bodies before offering them.
- **Safe-command ranking** — confidence → tier (typecheck/build → lint → unit → full → e2e) → value → cost; PM from lockfiles, confidence raised by config files.
- **Command-safety classifier** — unwrap `sudo`/`npx`/`poetry run`/…, reject installers/mutators/watch, identify probe kind.
- **Timeout-bounded, lossless probe runner** — the harness runs ONE composed script into a temporary spool outside the workspace, returns it in checked pages over ordinary asynchronous tool turns, and cria replays bytes through the existing parsers only after the declared size and SHA-256 verify. Incomplete transport is `UNKNOWN`, never clean; cria never opens the remote path.
- **Diagnostic parsers** — rustc/cargo, tsc, ESLint, pytest, and generic `file:line` → structured findings + a one-line summary; **error-class only** (unused-import/style advisories don't block).
- **Ground-truth completion gate** — on a "done" claim, run the floor + top probe + top TEST probe; broken code or failing tests block, and the exact `file:line` becomes the re-prompt. A first gate that only bootstraps the workspace survey is not fresh evidence: cria plans one new gate from that survey before completion. An already-surveyed workspace with no applicable probe, or a harness with no shell, keeps the bounded safe exit.
- **Build/source/test participation evidence** — one three-valued schema reads the actual gate event plus `wsview` manifest/config declarations through adapters for all nine discovery ecosystems; exact supporting tool lines reach completion judges, and unsupported source/test reach stays unknown rather than becoming pass/zero.
- **Changed-a-file leg** — a coder turn ends only if it actually modified a file on disk this task.

## Reasoned guidance — the reasoner as the stuck-loop response

- **Reasoner role routing** — a separate cheap local reasoner role, routable with failover (retry-same-on-timeout, chain-walk, per-role endpoints).
- **Plan-first (gather-and-plan)** — on a new task the reasoner is engaged first with a read-only tool subset (`list_dir`, `grep_files`, `read_file`, `web_fetch`, `web_search`), loops to inspect the repo + fetch docs, then emits a small-step plan grounded in what it found; pinned atop the coder's context, cached per task. The repo tools answer from the workspace view (`cria/wsview.py`), not from cria's own disk; there is no shell here at all.
- **Reasoned redirect** — when a loop guard fires, the reasoner authors exactly one next action (or `ON_TRACK`) from FRESH ground truth: the repeated failing action + its output, the pinned task, the touched files as the harness last reported them (`groundtruth`, via the workspace view), and the dirty-only lint probe. Checker evidence stays in its exact, separately marked ground-truth channel; the author never quotes or paraphrases it into the action. Before delivery, one focused whole-action judgment receives that action and the current diagnostic as separate inputs, plus exact refused coordinates and the same task/workspace evidence as the author; there is no second lexical per-token veto over incidental filenames. A write after the cited gate withholds the now-stale action; the raw checker result or canned directive is the reasoner-unavailable fallback (≤6/task).
- **Completion critic** — one reasoner call reviews the work (task + recent tool outputs + fresh lint/test results, tests-that-didn't-run counted as not-passing) and re-prompts while its flagged issues keep changing, stopping when they repeat. A negative verdict keeps completion fail-closed, but its coder-facing diagnosis has a typed claim kind, an exact task quote, and an exact quote from one named current evidence source. Code verifies those quotes and all workspace state through `wsview`; a task-named file's proven absence is deterministic, while other task/evidence relationships get at most one focused `SUPPORTED` / `UNSUPPORTED` / `UNDECIDABLE` judgment. Unsupported or undecidable prose is suppressed without turning the verdict into approval. Missing a whole file and missing required content inside an existing file are distinct types, and a requested report's documented risks are not silently promoted into requirements.
- **Honest incompletion** — when the gate gives up with issues unresolved, its verdict is written into the turn's FINAL message, not just a log line.
