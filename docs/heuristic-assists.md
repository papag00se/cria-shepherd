# Heuristic Assists — implemented in cria

A terse index of the assists cria **actually implements** today, in five families. One line each.
Design rationale and code pointers live in [local-coder-massaging.md](local-coder-massaging.md);
the conceptual overview in [shephard.md](shephard.md); still-unbuilt levers in
[port-fidelity-audit.md](port-fidelity-audit.md).

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

## Massages — silent output repair so the harness accepts it

- **write_file / edit_file ↔ shell round-trip** — lowered to a byte-exact base64 heredoc write; the recorded shell call re-presented as the original tool.
- **Leaked-call recovery** — tool calls emitted as text (Hermes `<tool_call>`, XML `<function=…>`, Gemma-fable `<|tool_call>…`) → real calls; Gemma `<|channel>` thinking stripped.
- **LFM2/Fabliq sentinel strip** — native `<|tool_call_start|>…<|tool_call_end|>` pairs + orphans stripped from content.
- **Shell-name rewrite** — `ls`/`cat`/`grep`/`git`/… emitted as tool names → proper `shell` calls (full alias table).
- **exec_command array fix** — `cmd` as `["bash","-lc",…]` → routed to `shell`.
- **Shell-args normalization** — a string command wrapped to `[bash,-lc,cmd]`; a double-wrapped array unwrapped.
- **read_file normalization** — `read_file(path, range)` → a `shell` `cat`/`sed`.
- **edit_file → apply_patch** — a find/replace → a native `apply_patch` Update hunk (when the harness runs apply_patch).
- **Tool-argument normalization** — string→JSON parse, dict passthrough, `{value}` wrap; `{function:{…}}` vs `{name,args}` unified.
- **Fenced-JSON tolerance** — tool args wrapped in ``` fences → extracted.
- **Malformed-JSON repair** — botched `write_file` args (raw newlines/quotes) → path + content recovered.
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
- **Self-compaction** — token-triggered: roll the old transcript middle into a `⟦cria:rollup⟧` reasoner summary, keeping the tail verbatim.
- **Completion compaction** — on `loop.done`, summarize the finished work into a `⟦cria:briefing⟧` envelope that rides in the closing message, so a follow-up resumes on top of it.
- **Overflow re-trim + retry** — a context-overflow error → re-trim to the server's real numbers and retry (no crash).
- **Last-resort drop + state synthesis** — drop oldest droppable turns (strip orphan tool-results) as the fit floor, replacing them with a protected `⟦cria:compacted⟧` note of the files they modified.
- **Anchor protection** — the briefing envelope, gate output, and compacted-state note are never silently trimmed.
- **web_fetch navigation** — cria fetches in-process: structural JSON/YAML reduce, top-level-keys outline, `find=`/`cursor` paging, `$ref` inline, real HTTP status.
- **Browser User-Agent** — cria's fetches send a real browser UA so sites don't block `curl`.
- **Reframed harness preamble** — the harness's AGENTS/env preamble re-presented in cria's clean voice.

## Probes — ground truth by doing

- **Language-aware syntax floor** — `py_compile`/`node --check`/`php -l`/`ruby -c` + a TOML/strict-JSON config floor over disk files → exact `file:line`.
- **Repo probe discovery** — inventory 9 ecosystems (JS/TS, Python, Rust, Go, JVM, .NET, PHP, Ruby, Elixir) → ranked SAFE diagnostic commands.
- **Package-script vetting** — read `package.json`/Make/etc. scripts and reject install/mutate/watch/service bodies before offering them.
- **Safe-command ranking** — confidence → tier (typecheck/build → lint → unit → full → e2e) → value → cost; PM from lockfiles, confidence raised by config files.
- **Command-safety classifier** — unwrap `sudo`/`npx`/`poetry run`/…, reject installers/mutators/watch, identify probe kind.
- **Bounded probe runner** — the harness runs ONE composed script; cria replays the output through the ported parsers, never mutating the workspace.
- **Diagnostic parsers** — rustc/cargo, tsc, ESLint, pytest, and generic `file:line` → structured findings + a one-line summary; **error-class only** (unused-import/style advisories don't block).
- **Ground-truth completion gate** — on a "done" claim, run the floor + top probe + top TEST probe; broken code or failing tests block, and the exact `file:line` becomes the re-prompt.
- **Changed-a-file leg** — a coder turn ends only if it actually modified a file on disk this task.

## Reasoned guidance — the reasoner as the stuck-loop response

- **Reasoner role routing** — a separate cheap local reasoner role, routable with failover (retry-same-on-timeout, chain-walk, per-role endpoints).
- **Plan-first (gather-and-plan)** — on a new task the reasoner is engaged first with a read-only tool subset (`exec_command` read-only, `read_file`, `web_fetch`, `web_search`), loops to inspect the repo + fetch docs, then emits a small-step plan grounded in what it found; pinned atop the coder's context, cached per task.
- **Reasoned redirect** — when a loop guard fires, the reasoner authors the coder's next step from FRESH ground truth: the repeated failing action + its output, the touched files re-read from disk (`groundtruth`), and the dirty-only lint probe; canned directive is the reasoner-unavailable fallback (≤6/task).
- **Completion critic** — one reasoner call reviews the work (task + recent tool outputs + fresh lint/test results, tests-that-didn't-run counted as not-passing) and re-prompts while its flagged issues keep changing, stopping when they repeat.
- **Honest incompletion** — when the gate gives up with issues unresolved, its verdict is written into the turn's FINAL message, not just a log line.
