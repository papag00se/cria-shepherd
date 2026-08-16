# cria live-test report — Ada Handle task, codex-local parity

Companion to [compaction-live-loop.md](compaction-live-loop.md). Goal: the four proven models (qwopus, qwythos, ornith, gemma4) COMPLETE the Ada Handle Lambda task through cria, at codex-local parity. Compaction is the enabler that must not break long runs.

**Workload:** Python Lambda resolving an Ada Handle via api.handle.me → resolved address + holder address + total handles; passing unit tests; a live test resolving `goose`/`papagoose`; a README.

**Definition of Done (per model):** task completes (twice), at ≥ codex-local quality; and when a session crosses ~48K, Codex-triggered compaction routes through the model and succeeds without killing the run.

---

## Environment (as of this run)
- Harness: `codex-debug` (codex-local fork) → cria `:18085` → llama.cpp `:18084` (single 3080, `-np 1`).
- Codex config `~/.codex/config.toml`: `model = "cria"`, `model_context_window = 49152`, `model_auto_compact_token_limit` UNSET, `compact_prompt` carries `<<<LOCAL_COMPACT>>>`.
- cria code live as of 2026-07-07 22:55 restart: verifier fail-closed + reasoning-off retry; `content_reduce.py` ported but NOT wired; trim floor NOT ported.
- Brave key: cria reads `BRAVE_SEARCH_API_KEY` from its own `env_file` (cria-only; never a shared/personal secrets file, never a coded path).
- exec invocation: `codex-debug exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check -C <ws> --json`.

---

## qwopus

### Run 1 — FAILED (turn.failed, EXIT=1) — 2026-07-07 22:57, ~5.5 min
- Workspace: `/tmp/compaction-test/qwopus-1`
- **Outcome:** did NOT complete. Produced `resolve_handle.py` (1.7K) + `test_resolve_handle.py` (14K); NO README, NO separate live test; empty final message.
- **Failure:** `turn.failed = "stream disconnected before completion: HTTP Error 400"`. llama journal: history reached **49603 tokens > 49152 window** → 7-request **400 storm** (all identical
  49603) from 23:01:52–23:01:59 → turn died.
- **Root cause #1 (why it crashed): compaction never fired.** `LOCAL_COMPACT` count in the cria log = **0** — Codex never once attempted a compaction. `model_auto_compact_token_limit` was UNSET (=> i64::MAX => trigger never arms), so the history grew unbounded into the wall.
  - **Fix applied:** `~/.codex/config.toml` → `model_auto_compact_token_limit = 38000` (~77% of the 48K window, so the summarize request still fits). *Verify live next run.*
- **Root cause #2 (why it wouldn't complete anyway): the coder looped.** cria plan loop drafted 1 plan (`loop.start=1, plan.drafted=1`) but **completed ZERO steps** (`step_done=0, step_inc=0`) — the coder never even reached a verify. Agent messages show it cycling: "I'll explore the repository…" → "I'll create the Lambda handler…" → writes `resolve_handle.py` → then "Files already exist from **the previous model's work**. I'll examine them…" → rewrites the same file. It treats its OWN prior output as a stranger's — a context/state problem in how cria frames each step to the coder (the coder isn't seeing its own prior actions coherently). This re-work is what grew the context into the wall.
  - **Status:** OPEN. Diagnose after the compaction fix (re-run may change dynamics; a compacted context might break the "previous model's work" confusion). Reference oracle: qwopus completed this in codex-local, so the loop is a cria-path regression, not a model limit.

### Run 2 — FAILED (turn.failed) — auto-compact limit armed at 38000
- Workspace: `/tmp/compaction-test/qwopus-2`
- **Outcome:** same failure — context climbed to 48632, `exceed` overflow, 400 storm, turn died. Setting `model_auto_compact_token_limit = 38000` did NOT fire compaction (`LOCAL_COMPACT` still 0).
- **Diagnosis (the real bug):** traced Codex's trigger — [`openai_models.rs:303`](../../codex-local/codex-rs/protocol/src/openai_models.rs#L303) derives the limit as `min(config, 90% of window)` = 38000 (a real number, not i64::MAX). It's compared at [`codex.rs:6280`](../../codex-local/codex-rs/core/src/codex.rs#L6280) against `get_total_token_usage()`, which Codex populates **from the usage in cria's API responses** ([`client.rs:1650`](../../codex-local/codex-rs/core/src/client.rs#L1650)). cria was reporting the *internal call's* usage — the framed coder's, or **nothing (0)** on synthesized probe/file-op/ step-done turns. So Codex's token accounting never reflected its real ~46K history → trigger never armed → history grew into the wall. (`_frame_for_item` keeps the full history, so the coder call IS big, but most plan-loop turns return synthesized completions with no usage.)
  - **Fix applied (cria):** `server.py` `_report_context_usage` + `_incoming_ctx_tokens` — cria now reports `input_tokens` = the estimated size of the INCOMING request (Codex's real context) on EVERY response, logged as `usage.context_reported`. This is the truthful signal that drives Codex's auto-compaction. 227 tests pass. *Verify live: run 3.*

### Run 3 — FAILED — usage-reporting fix (report conversation only)
- cria now emits `usage.context_reported`, but reporting only the conversation (~8–12K) kept Codex below the 38000 limit while the MODEL call was ~46K → no compaction, overflow. Revealed a ~30K gap between Codex's conversation and the model call.

### Run 4 — FAILED — report msg + tools (the real model-call size)
- cria reports the full model-call size. Codex was told **42287 → 49056** (well above the 38000 limit) and **STILL never compacted** (`msg` climbed monotonically, no drop, `LOCAL_COMPACT=0`).
- **KEY FINDING: Codex's exec/Responses path does not drive auto-compaction from reported usage.** The "inform Codex → it compacts" mechanism (which worked in codex-local via *in-process* token accounting) does not work for an *external* proxy over the Responses API in exec mode. Reporting truthful usage is necessary but NOT sufficient — cria cannot make Codex compact this way.

### Run 5 — diagnostic — the overhead is irrelevant tools
- `ctx.estimate`: **127 tools = 34,057 tokens** — ~70% of the 49152 window — dominated by the **gmail + github MCP connector tools** (`mcp__codex_apps__gmail_*`, `..._github_*`) plus `spawn_agent`. These come from `[plugins."gmail@openai-curated"]` / `[plugins."github@openai-curated"]` enabled in `~/.codex/config.toml`. Useless for a local coding task; they leave only ~15K for the actual conversation, so it overflows in a handful of turns.

### Run 6 — the `-c` plugin override did NOT work
- `-c 'plugins."...".enabled=false'` left tools at 127/34K — those tools come from the MCP connector (`codex_apps`), not a simple plugin flag. Killed.

### Run 7 — BREAKTHROUGH — isolated clean CODEX_HOME (no plugins) → tools 34K→5.7K
- Pointed the test at `CODEX_HOME=/tmp/compaction-test/codex-home` with a minimal config (cria provider + window/compact settings only; NO plugins/mcp/connectors). Result: **14 tools = 5,706 tokens** (was 127 / 34,057). The remaining tools are the real ones (`exec_command`, `web_fetch`, `local_web_search`, `spawn_agent`/`supervisor`).
- Run 7 climbed to ~30K context with **`exceed=0`** — ~28K of window reclaimed; the task finally has room. (Outcome (complete vs loop-to-overflow) recorded below.)

### Run 7 — result: SESSION COMPLETED (no overflow), but OUTPUT QUALITY FAILS
- `turn.completed`, EXIT=0, ~24 min, `exceed=0`. Produced handler + unit tests + live test + README; critic reported "all 7 steps verified." **First session to complete without overflowing.**
- **BUT ground-truth `pytest`: 8 failed, 20 passed, 3 errors.** qwopus wrote broken test mocks (`TypeError: … not MagicMock`), the live test has collection errors, and it created TWO parallel handlers (`handler.py` + `src/handle_resolver.py`). So it does NOT meet the DoD ("tests that pass").
- **Verification gap exposed:** the cria critic marked step 5 ("create unit tests") done because the files exist and the probe (`compileall`) only checks SYNTAX — it never RAN the tests. A test-step's ground-truth probe should execute the tests, so the critic catches failing tests instead of passing on "files created." (Next lever.)

### THE HEADLINE
The overflow saga was **not** a compaction problem. It was **34K of irrelevant gmail/github MCP tool schemas** (from `~/.codex/config.toml` plugins) eating 70% of the local model's 48K window. Codex-triggered compaction is a red herring for cria — it does not fire over the exec/Responses path regardless. The real levers are: **(1) don't load irrelevant tools** (isolated CODEX_HOME, or cria strips tool schemas), and if a task legitimately outgrows the window, **(2) the cria-side trim floor** — NOT Codex compaction.

### Fixes landed this session (cria)
- `server.py` `_report_context_usage` / `_incoming_ctx_tokens`: report Codex its real model-call size as `usage.input_tokens` (msg + tools), logged as `usage.context_reported` + `ctx.estimate`. Truthful, but insufficient alone (Codex won't compact over this path).
- **Open direction:** since Codex won't compact from cria, the deterministic fix is cria-side — (a) strip irrelevant tools / reduce overhead, and (b) the **trim floor** (keep the model call under the window). Compaction-via-Codex is not the lever here.

---

# Session 2 (2026-07-08) — parity resolved, ground-truth probe now RUNS tests

## PARITY QUESTION — RESOLVED: stripping the plugins is a correction, not a goalpost move
The open question from session 1 ("does the isolated no-plugins CODEX_HOME match codex-local, or move the goalpost?") is answered by codex-local's own proven test config, [`.codex-multi/config.toml`](../../codex-local/.codex-multi/config.toml):
- It is a **per-working-directory config** that explicitly *"Does not affect ~/.codex/config.toml"* and carries **zero plugins / MCP / connectors** (grepped: NONE). The four models were proven under THIS config.
- So the 34K of gmail/github MCP tool schemas that swamped session-1's runs came **only** from the user's *personal* `~/.codex/config.toml` (their day-to-day gmail/github connectors), which the cria test accidentally inherited. codex-local never loaded them.
- **Verdict:** the isolated clean CODEX_HOME (5.7K tools) **restores** codex-local's real environment. It is honest parity, not a cheat. **[SUPERSEDED — see the REFRAME section below: the isolated CODEX_HOME is retired entirely; cria now manages context on its own side for any harness, so no harness-config pruning is needed at all.]**
- Secondary note (not blocking): `.codex-multi` set `trim_budget = 65536` per role and pointed at a LAN qwopus endpoint; cria's qwopus is loaded at `n_ctx = 49152`. The window is smaller, but session 1 proved the task fits in ~30K once the tool bloat is gone, so 48K is not the binding constraint for this workload. codex-local's supervisor also had `verification_command = "pytest tests/"` (commented) and a `test_runner` role — i.e. running the tests as ground truth is codex-local's own design, which the probe change below mirrors.

## Config alignment to the reference oracle (`~/.cria/cria.toml`)
codex-local's `.codex-multi/config.toml` runs per-role reasoning: **classifier off, light_reasoner on, light_coder OFF, compactor off**. cria was shipping **every role reasoning ON** (an untested opinion in `docs/model-settings.md` line 96, "also what coding wants"). Aligned cria.toml to the proven config:
- `classifier` on→**off**, `coder` on→**off**, `compactor` on→**off**; `reasoner` stays **on** (drives the planner + the step critic). Reasoning-off is clean on qwopus (native-off model). A tool-use coder acts more reliably and grows context slower without a `<think>` block per turn.

## THE FIX — the ground-truth probe now RUNS the unit tests (`cria/loop.py`)
Session 1's headline hole: the critic marked "create unit tests" DONE because the files existed and the probe (`compileall`) only **syntax-checked** — qwopus-7 shipped **8 failing mocks** as "done".
- `_PROBE_COMMAND` now adds a **test floor**: after the syntax floor it runs `pytest -q --tb=short -rfE` (excluding `*live*`/`*integration*`/`*e2e*` — the live test needs the real API and would make a deterministic floor flaky; it's a separate deliverable judged on the coder's own run). Reports `PROBE_TESTS=<rc>`; pytest exit 5 (no tests yet) maps to 0 so early steps don't wedge; any other nonzero (failures, collection/import errors, timeout) fails the probe.
- `_probe_passed` now fails on a nonzero `PROBE_EXIT` **or** `PROBE_TESTS`.
- On a failed probe the coder is handed the **tail** of the output (`_clip_tail`, 1400 chars) — the pytest short-summary + failing traceback land at the tail; the old 1st-600-chars head clip missed them.
- Validated against the qwopus-7 fixture: whole-suite `pytest` = `8 failed, 20 passed, 3 errors`; the new probe reports `PROBE_EXIT=0 PROBE_TESTS=1` and excludes the 3 live-test collection errors. Benign cases confirmed: no-tests→pass, green→pass, live-only→ignored, broken-import→fail. 228 unit tests pass (added `test_failing_unit_tests_nudge_coder_and_skip_critic`).

## qwopus Run 8 — parity config + test-running probe — 2026-07-08 (IN PROGRESS)
- Workspace: `/tmp/compaction-test/qwopus-8`; coder reasoning OFF (tried as codex-local parity); probe runs pytest.
- **Killed — coder redo-spin on step 2.** Trace (`exec.jsonl`): the coder did step 1 correctly (scaffolding: `mkdir src/handlers tests`, `__init__.py`, `lambda_function.py`, `requirements.txt`), then on step 2 ("implement the Handles API client") **re-ran step 1's exact scaffolding** — "I'll initialize the project structure" → `mkdir …` → loop — never touching step 2's goal. Context climbed ~+122 tok/cycle. This is session-1's OPEN "Root cause #2" (coder redoes prior work).
- **Root cause:** cria's `_frame_for_item` keeps the step instruction where the original task was (near the TOP of a long history); a reasoning-OFF model continues the most-recent *pattern* (scaffolding) instead of re-reading the buried step-2 instruction. A/B test confirmed qwopus tool-calls fine reasoning off **and** on for a clean minimal request — so it's the framing × long history, not reasoning-off per se. Reasoning-ON **masks** it (the model thinks first and breaks the pattern), which is why run 7 completed.
- **Action:** reverted coder to reasoning ON (the proven cria config; run 7 completed with it). The framing fix that would let reasoning-off work — **anchor the current step at the END of the framed conversation** ("steps 1..k done; the scaffolding exists; do ONLY step k+1") — is an OPEN item (recommended, not yet done). NOTE: the floor was NOT yet live for run 8; the spin was killed manually before it overflowed.

---

# Session 2 (cont.) — REFRAME: cria owns context management (harness-agnostic)

**User direction (2026-07-08):** stop asking the user to prune their Codex config; cria must manage context on its OWN side regardless of what connects — it won't always be Codex (Claude, Aider, and other harnesses will connect). Excise the Codex dependency from code, docs, and memory.

## The isolated CODEX_HOME crutch is RETIRED
Session-1's whole "strip the 34K gmail/github tools via an isolated `CODEX_HOME`" line was the wrong axis: it made cria's survival depend on the *harness's* config. cria now handles a fat tool list and an unbounded history itself. No harness-config surgery, for any harness.

## LANDED — the context floor (`cria/contextfloor.py`), live-verified
Harness-agnostic, applied at the single outbound chokepoint (`Upstream._prep`), on `{messages,tools}`. Window **discovered** from the server's `/props` (`context.window`, `n_ctx=49152`) — not a constant. Then four levers (cheapest first):
1. **Bound the tool SCHEMA** (`_compress_tools`): when it exceeds `MAX_TOOL_FRACTION` (0.5) of the budget, truncate the free-text *descriptions* (function + parameter) until it fits — every tool stays callable (name/params intact). THE real fix for "34K gmail/github tools" (67% of window, otherwise irreducible).
2. **Tool-aware message budget**: `window − reserve − tool_schema_tokens` (chars/4 × 1.3 safety).
3. **Bound oversized tool OUTPUTS** (`content_reduce`, now wired), largest first.
4. **Drop oldest turns** (system + active turn preserved; `_strip_orphan_tools` prevents an orphaned `tool` result). `over_budget` (warning) surfaces when even all four can't fit.
- **Live proof #1 (oversized conversation):** a **486,190-est-token** request → `msg_after=27037`, `turns_dropped=34`; real llama prompt **24,069**; **ZERO** `exceed`; HTTP 200.
- **Live proof #2 (realistic Codex config, 127 tools / 34,057 tok):** **qwopus-9** (before tool bounding) **OVERFLOWED** — `request (49255) exceeds 49152` 400-storm; the 34K schema + 16K protected system/active-turn can't be dropped, exposing that the floor MUST bound the tool schema too. **qwopus-10** (with tool bounding): `tool_tokens 34057→11478, tools_compressed=127`, `over_budget=False`, max real prompt **24,404**, **ZERO** `exceed`, run progressed — the harness-agnostic win, with the user's REAL `~/.codex/config.toml` and no CODEX_HOME surgery.
- `cria/contextfloor.py`, `cria/upstream.py`; 9 tests in `tests/test_contextfloor.py`; full suite 237 pass.

## De-Codex (code + docs)
- `server.py` `_report_context_usage` / `_incoming_ctx_tokens`: kept as **honest token accounting for any harness**; removed the dead "inflate usage to drive Codex auto-compaction" intent (finding #2 proved it never fired, and the floor makes it moot).
- `loop.py` `_is_env_context`, `planner.py` `_extract_cwd`: reframed as harness-agnostic with Codex's `<environment_context>` as one *recognized* convention (graceful fallback to first-user-message / `.`).
- `responses.py` (Responses↔Chat adapter) **kept** — it's one pluggable adapter, the only wired driver; "excise the dependency" = remove Codex-specific *assumptions/hacks*, not the adapter.
- Docs reframed: `compaction-live-loop.md` (DoD enabling criterion now "cria's floor holds the window"), `session-handoff.md` (REFRAME banner; runbook no longer strips CODEX_HOME), `README.md` (context-shaping bullet).

## Coder framing — root cause found (via capture) and FIXED
Per-call capture ([logging] capture_calls; `cria/callcapture.py` writes the exact body + rendered prompt per model call to `~/.cria/calls/<session>/NNNN-<phase>.{json,prompt.txt}`) revealed the real cause of the redo-loop — and it wasn't just "step instruction buried." The coder's request OPENED with **Codex's full agent system prompt: message[0], 7,827 tokens = 33% of the request** ("You are a coding agent running in the Codex CLI…"), forwarded verbatim. A conflicting mandate: the harness tells the model to be a fully autonomous agent (plan, apply_patch, finish the whole task) while cria drives it one step at a time via a 77-token framing buried at ~49%. The loud prompt wins → re-scaffold / redo.
- **Fix (LANDED):** `_frame_for_item` now DROPS every incoming `system`/`developer` message and leads with cria's own concise coder system prompt (`cria/prompts/coder_system.txt`: "do ONLY this step, don't redo earlier steps, act don't narrate" + minimal tool guidance). Harness-agnostic (cria owns the system slot when orchestrating; no Codex fingerprinting). Kept: the user's AGENTS.md, env, work history, tools. Safe to drop Codex's tool how-to — cria re-supplies it (cheatsheet + writeproxy).
- **Verified live:** a fresh coder call's message[0] is now cria's 197-token prompt (Codex boilerplate absent), AGENTS.md kept, request **~23K → ~12.5K tokens**, zero overflow. 243 tests pass.
- **NOT yet confirmed:** that this CURES the redo-loop end to end — needs a full completion run watched via the capture (does the coder now advance step→step). See [[project_cria_owns_system_prompt]].

## Open items
- **Confirm the redo-loop cure**: a full completion run against the realistic config, watched via the capture; qwopus complete with GROUND-TRUTH passing pytest (the probe runs tests), reproduce twice, then qwythos/ornith/gemma4.
- Raw **proxy path** (non-orchestrated requests) still forwards the harness system prompt — a separate decision (there cria isn't orchestrating, so replacing it is less clearly right).

---

## qwythos
_(pending qwopus)_

## ornith
_(pending)_

## gemma4
_(pending)_
