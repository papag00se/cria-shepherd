# Session handoff — cria live-testing (Ada Handle task, codex-local parity)

Context transfer from a prior working session. Read this + [compaction-live-loop.md](compaction-live-loop.md) (the goal) + [compaction-live-report.md](compaction-live-report.md) (run-by-run findings) before acting.

> ## ⚠ REFRAME (2026-07-08) — read this first; it supersedes the Codex-specific parts below
> **cria is harness-agnostic and manages context on its OWN side.** The earlier "overflow" work below chased Codex-side compaction and, when that failed, worked around a bloated Codex tool list by running against an **isolated stripped `CODEX_HOME`**. That was the wrong axis: it made cria's survival depend on pruning the *harness's* config, and cria won't always front Codex (Claude, Aider, and others will connect too). **That crutch is retired.**
>
> The real fix landed and is live-verified: a **context floor** (`cria/contextfloor.py`, applied at the `Upstream._prep` chokepoint) that keeps every request under the model window itself — window auto-detected from `/props`, budget = `window − reserve − tool_schema_tokens`, oversized tool outputs reduced (`content_reduce`), oldest turns trimmed (system + active turn preserved, no orphaned tool results). Verified: a ~486K-token request → 24K real prompt, **zero** llama `exceed`. Codex-triggered compaction and `model_auto_compact_token_limit` are **dead ends — do not chase them.**
>
> **So when reading below:** treat every "isolated CODEX_HOME / strip the plugins / make Codex
> compact / report usage to trigger auto-compaction" instruction as **historical, not current**. Test against a **realistic** harness config; cria handles the fat tool list and the unbounded history. The still-valid parts: the runbook mechanics (cria restart, Brave key, UTC log gotcha, single GPU slot, throwaway workspaces), the model roster, and codex-local as the quality oracle.
>
> **Correction (2026-07-11):** "Codex compaction never fires" was true of the `codex exec` path
> tested below — it is **NOT true of the VS Code extension path**, which does compact (observed live, repeatedly). *Triggering* harness compaction remains not cria's job, but cria must now SURVIVE an incoming one: it detects a rewritten conversation root structurally (same session key, new root = the harness replaced the history with its summary) and plans a continuation instead of re-planning the summary text as a fresh task. See `LoopStore.observe_shape` / `loop.history_rewritten`.

## Mission
Get **cria-shepherd** (this repo — a stdlib-first, harness-agnostic OpenAI-compatible proxy on `:18085` fronting a local llama.cpp model on `:18084`) to the level **codex-local** reached: the four proven local models — **qwopus, qwythos, ornith, gemma4** — actually **complete** the Ada Handle Lambda task (handler + **passing** unit tests + a working live test resolving `goose`/`papagoose` + README), driven headlessly through `codex-debug exec`. Reproduced twice per model. "Complete" means tests actually pass (ground-truth `pytest`), not that the critic said so.

## codex-local is the prior successful experimentation — use it as the reference oracle
`/home/jesse/src/codex-local` is the Rust research vehicle where the Shephard/compaction/trim/ content-reduce logic was originally built and proven. Same models, same task worked there. If a model completes there but not in cria, the delta is in the cria path/config, not the model. Key reference files there:
- `codex-rs/routing/src/content_reduce.rs` — source of cria's `content_reduce.py` port (pure, MIME-aware output reducer). Ported; NOT yet wired into cria's request path.
- `codex-rs/routing/src/trim/` (`mod.rs` `enforce_token_budget`, `items.rs`, `render.rs`) — the deterministic "request always fits the window" **trim floor**. NOT yet ported to cria. This is the real fix for a task that legitimately outgrows the window.
- `codex-rs/routing/src/compaction/` — the bespoke LLM summarizer pipeline. **Do NOT port** (it's the reinvention; the harness owns compaction). codex-local was itself deleting it.
- `codex-rs/protocol/src/openai_models.rs:303` `auto_compact_token_limit()` — the trigger derivation (90% of context_window, clamped by config).
- `codex-rs/core/src/codex.rs:5968/6280` — the auto-compact check; `client.rs:1650` parses response usage. (Relevant to why Codex compaction does NOT work over cria — see findings.)
- `docs/spec/compaction-reference.md`, `docs/spec/content-reduce.md`, `docs/spec/heuristic-assists.md` — the authoritative design specs (the deliverable).
- Memory (codex-local project): `/home/jesse/.claude/projects/-home-jesse-src-codex-local/memory/` — MEMORY.md indexes durable facts (a fresh cria-shepherd session will NOT auto-load these; read them if useful).

## The hard-won findings from the prior session (the headline)
1. **The "overflow / compaction" problem was NOT compaction. It was tool overhead.** Codex was sending **127 tools = ~34,057 tokens (70% of the 48K window)** every request — almost all the **gmail + github MCP connector tools** (`mcp__codex_apps__gmail_*`/`_github_*`) from the plugins enabled in `~/.codex/config.toml`. That left ~15K for the task, so it overflowed in a few turns.
2. **Codex-triggered compaction does NOT fire over cria's exec/Responses path.** cria was made to report Codex its true context size; even when told **49056 (well past the limit), Codex never compacted**. codex-local drove compaction *in-process*; an external proxy can't via the API. So "make Codex compact" is a dead end for cria — don't chase it.
3. **Fix that worked:** run codex against an **isolated `CODEX_HOME`** with a minimal config (cria provider + window settings, NO plugins/mcp/connectors) → **14 tools, ~5.7K** → ~43K of room. With that, **qwopus completed the whole session, no overflow** (first success).
4. **But completion quality failed:** ground-truth `pytest` on qwopus's output = **8 failed, 20 passed, 3 errors** (broken test mocks; two parallel handlers). The cria critic passed the "create tests" step because files exist and the probe only **syntax-checks** — it never RAN the tests. So the "success" was hollow. **Next lever: make the ground-truth probe run the tests on a test step**, so the critic catches failing tests and re-nudges the coder to fix them.

## Current goal state: 0 of 4 models actually done
- **qwopus:** session completes (overflow solved), but tests fail → NOT done.
- **qwythos / ornith / gemma4:** not started.
- **OPEN parity question:** does stripping the gmail/github plugins match codex-local, or move the goalpost? Confirm whether codex-local loaded those plugins before calling anything "parity."

## cria fixes landed this session (in this repo)
- `cria/server.py` — `_report_context_usage` + `_incoming_ctx_tokens`: report Codex the real model-call size (messages + tools) as `usage.input_tokens`, logged as `usage.context_reported` + `ctx.estimate` (with per-tool breakdown `top_tools`). Truthful, but does NOT make Codex compact (see finding #2). Keep for observability; it's how the 34K-tools overhead was found.
- `cria/loop.py` — the step critic (`_verify`/`_verdict`) now **fails CLOSED** on an unparseable verdict (was fail-open → silent false "done") with a **reasoning-off retry** (a reasoning model under the token cap can burn its budget thinking and never emit the JSON verdict).
- `cria/content_reduce.py` — NEW, ported from codex-local (pure output reducer). NOT wired yet.
- 227 unit tests pass.

## Key cria-shepherd files
- `cria/loop.py` — the plan loop: draft plan → frame step for coder (`_frame_for_item`, keeps full history) → coder acts → ground-truth probe (`_probe_op`, currently syntax-only `compileall`) → critic (`_verify`) → advance/renudge.
- `cria/server.py` — request handlers (`_handle_responses` is Codex's path), `_produce_completion`, usage reporting.
- `cria/config.py` — `LocalRole` (per-role model/sampling/reasoning applied per request).
- `~/.cria/cria.toml` — live config (per-role blocks; currently all qwopus, reasoning on).
- `docs/model-settings.md` — per-model recommended sampling + reasoning on/off reality (source of truth for the 8 models).

## Operational runbook (gotchas that cost time)
- **Harness:** `codex-debug` (symlink → codex-local fork `target/debug/codex`) → cria `:18085` → llama.cpp `:18084`. Single RTX 3080, `-np 1` (one model, one request at a time; also renders Blender — contention looks like flakiness).
- **Run the task headlessly:** `codex-debug exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check -C <fresh-workspace> --json -o <ws>/last-message.txt "$(cat task.txt)"`. Use a **realistic** harness config (the user's real `~/.codex/config.toml` is fine — cria's context floor absorbs its full tool list; do NOT hand-strip an isolated `CODEX_HOME`, that crutch is retired — see the REFRAME banner). codex-debug is just one driver; any OpenAI/Responses harness works.
- **Fresh throwaway workspace per run** (a local model once ran `find . -delete`). Verify tests with real `pytest` afterward — the critic's word is not proof.
- **cria restart** (from repo dir; loads code + config): kill python3 procs whose `/proc/*/cmdline` has `-m cria` (NOT `pkill -f "python3 -m cria"` — self-matches, exit 144), then `setsid nohup python3 -m cria > ~/.cria/cria.out 2>&1 < /dev/null &` (cria loads the Brave key from its configured `env_file` itself — no key on the command line).
- **Brave key** (cria web_search): cria reads `BRAVE_SEARCH_API_KEY` from its own `env_file` (`~/.cria/cria.toml` → e.g. `~/.cria/.env`, cria-only). Populate that file once from your own secrets store — a manual step; never point cria at a shared/personal env file, never code that path. Never print/commit the key.
- **LOG FILE GOTCHA:** cria names its log by **UTC** date — read `~/.cria/logs/cria-$(date -u +%Y%m%d).jsonl`, NOT `$(date +%Y%m%d)` (local date can be a day behind and points at a stale file). It's line-buffered/real-time.
- **Model swap:** systemd (`systemctl` on the `llama-<model>` service) / `llama-fleet <model>` reading `~/.config/llama-fleet/models.toml`; one at a time; verify with `curl -s 127.0.0.1:18084/props`. Never swap/infer while a session is live (check the cria log's last event is >120s old).
- **Observe a run:** watch the llama journal for `n_tokens` (real model-call size) and `exceeds the available context` (overflow); watch the cria log for `ctx.estimate` / `usage.context_reported`.

## Recommended next steps
1. Refocus on the GOAL (a model completing the task with passing tests), not the overflow plumbing.
2. Make the ground-truth probe RUN the tests on a test step so the critic catches failing tests.
3. Re-run qwopus for a genuine pass (tests green), reproduce twice, THEN move to qwythos/ornith/gemma4.
4. Resolve the parity question (plugins) so the environment is honest.
5. If a task legitimately outgrows the window even with clean tools, port the codex-local **trim floor** (not Codex compaction).
