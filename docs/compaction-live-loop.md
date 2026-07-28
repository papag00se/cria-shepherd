# GOAL: get cria to codex-local parity — the four models COMPLETE the task

## Mission
Get cria-shepherd to the level codex-local reached: the four models — **qwopus, qwythos, ornith,
gemma4** — actually **complete** the Ada Handle Lambda task (working handler + passing unit tests +
a live test that resolves `goose`/`papagoose` + a README), driven headlessly through
`codex-debug exec`. These four did a decent job in codex-local; cria must match that.

**Surviving a long session is a prerequisite, not the point.** The history WILL cross the window; the
measure of success is **task completion at codex-local parity**, not context management in isolation.
But context management is **cria's own job** — cria keeps every request under the model's window
itself (the context floor: window auto-detect + tool-schema budget + oversized-output reduction +
oldest-turn trim), **regardless of which harness is connected**. cria never relies on the harness to
compact — many harnesses can't, and it isn't cria's to configure. Keep looping — diagnose, fix
upstream, restart, re-run — until each model completes the task the way it did in codex-local.
Document every issue and fix. Work as long as it takes; do not stop early.

> **Harness-agnostic — do NOT depend on Codex.** cria is a proxy for *whatever* connects to it
> (Codex today; Claude, Aider, others tomorrow). Earlier sessions worked around a bloated Codex tool
> list by running against an *isolated stripped `CODEX_HOME`* — that was wrong: it made cria's
> survival depend on the user pruning *their* harness config. That crutch is retired. cria handles a
> fat tool list and an unbounded history on its own side. Test against a **realistic** harness config,
> not a hand-stripped one.

## This is a live-systems goal — read before starting
- "Working" is a **behavior observed on a real session**, never "code compiles" or "tests pass."
  codex-local's context management took weeks of live iteration; treat this the same. Never declare
  done from a green test, a clean port, or a single turn.
- **No band-aids.** Every failure has an upstream fix in **cria's own code/config** (`cria/…`,
  `~/.cria/cria.toml`, `~/.config/llama-fleet/models.toml`) — not in the harness's config. Find it.
- Every diagnosis becomes a fix or a written recommendation. Diagnosis alone is unfinished.
- State uncertainty out loud. Do not narrate confidence you have not earned from a real run.

## Definition of Done (per model, observed on real runs)
For each of qwopus, qwythos, ornith, gemma4:

**Primary — completion (this is the goal):**
1. A `codex-debug exec` run of the Workload **completes the task**: a Python Lambda handler that
   resolves an Ada Handle via api.handle.me and returns resolved address + holder address + total
   handles; **unit tests that pass**; a **live test** that resolves `goose` or `papagoose`; and a
   **README**.
2. Completion is **at least as good as the model managed in codex-local** (see Reference oracle).
3. Reproduced at least twice (not a fluke).

**Enabling — cria's context floor must keep long runs alive:**
4. When a session crosses the model's window (~48K), **cria** keeps the request under the window
   itself — the outbound model call **never** returns `HTTP 400` / `exceeds the available context
   size` — by trimming deterministically (oldest turns dropped, oversized tool outputs reduced,
   tool-schema overhead budgeted). This holds for **any** harness and **any** tool-list size, with no
   harness-side compaction and no config surgery. Context overflow must never be the reason a run
   fails to complete. (Verify from the llama journal: zero `exceed` errors; from the cria log:
   `context.floor` events and `context.window` discovery.)

Only when Primary + Enabling hold for all four models is the goal met.

## codex-local is the reference oracle — a delta is a cria bug
Same models, same task. If a model **completed in codex-local but stalls, loops, or fails in cria**,
the difference is in the cria path (the Responses↔Chat translation, the plan loop, routing, config)
or a setting — **not the model**. Use codex-local's behavior as the baseline: if unsure, run the
same task there, compare what its routing does that cria doesn't, and close the gap. This is the
fastest way to avoid re-deriving from scratch what already works — and the antidote to spinning.

## Scope — the four proven models, not the MoE ones
qwopus, qwythos, ornith, gemma4 are the baseline that did decently in codex-local. The MoE models
(e.g. mellum2) have been struggling and are **out of scope** for this goal — do not let them
absorb the loop's time. The target is codex-local parity on these four.

## The Workload (run verbatim via codex-debug exec)
```
I would like you to write a Python Lambda handler that accepts an Ada Handle as input and resolves it to the Cardano address using the Ada Handles API (api.handle.me). The response should include the resolved address, the holder address, and the total Handles the holder possesses. Unit tests are required. Separately, create a live test that resolves the handle `goose` or `papagoose`. When you're done, add a README.
```
This fetches api.handle.me docs (large tool outputs), writes code, and iterates on tests — exactly
the growth that crosses the window and exercises cria's context floor. If one run doesn't cross the
window, extend it (follow-ups, more iterations) until it does. Crossing the window is the whole point.

## The four models
Source of truth for settings: `docs/model-settings.md`, plus `~/.cria/cria.toml` (per-role sampling
+ reasoning) and `~/.config/llama-fleet/models.toml` (launch: ctx/quant/template). Verify each
model's settings match the doc before testing it.
- **qwopus** — Qwen3.5-derived; reasoning on/off clean; temp 0.6 / top_p 0.95 / top_k 20. Start here.
- **qwythos** — Qwen3.5 thinking; same sampling family.
- **ornith** — reasoning model; needs `--reasoning-format deepseek` at launch; agentic temp 0.6.
- **gemma4** — hardest: needs a repeat-penalty or it leaks `<|tool_call>`/`<|channel>` tokens, and
  has emitted a bespoke tool-call format instead of a plan. Expect harness friction; friction is a
  requirement to satisfy, not a reason to drop the model.

## Per-model loop (one model at a time — single GPU slot, `-np 1`)
1. **Confirm the slot is free.** Do NOT swap or infer while a session is live: check the cria log's
   last event is >120s old (`tail ~/.cria/logs/cria-$(date +%Y%m%d).jsonl`).
2. **Swap the model** with the established mechanism (systemd service / `llama-fleet <model>` —
   confirm which is live; one model at a time). Verify: `curl -s 127.0.0.1:18084/props`.
3. **Set sampling/reasoning** in `~/.cria/cria.toml` per docs/model-settings.md.
4. **Restart cria** (see Runbook) so config + latest code are live.
5. **Fresh throwaway workspace** — a new empty dir per run (e.g. `/tmp/compaction-test/<model>-<n>/`).
   Never reuse a real project; the task writes files. (A local model once ran `find . -delete` —
   throwaway dirs only.)
6. **Run the Workload headlessly:** `codex-debug exec` in the workspace (confirm exact flags with
   `codex-debug exec --help`). Tee output to a log.
7. **Watch the context floor live** (see Observability).
8. **Diagnose + fix** each failure at its upstream source; restart; re-run. Loop until Done holds
   for this model, twice.
9. **Record** findings in the Report as you go, then move to the next model.

## Observability — how to know the context floor held
- cria log (`~/.cria/logs/cria-YYYYMMDD.jsonl`):
  - `context.window` — the model window cria discovered from the server's `/props` (e.g.
    `n_ctx=49152`). Emitted once per upstream client.
  - `context.floor` — emitted whenever cria trimmed a request to fit: `msg_before`/`msg_after`
    (estimate before/after), `turns_dropped`, `outputs_reduced`, `tool_tokens`, `over_budget`. This
    is the floor doing its job; a large `msg_before` with a much smaller `msg_after` = it held.
  - `ctx.estimate` — the incoming request's msg-vs-tools token breakdown (observability; also what
    cria reports back as honest usage).
- llama journal: `journalctl -u 'llama-*' -f | grep -iE 'exceed|context size'` — **ZERO** on success.
  The floor guarantees this; a single `exceed` is a floor bug to fix, not a harness-config issue.

## Operational runbook
- **Brave web_search key**: cria reads `BRAVE_SEARCH_API_KEY` from ITS OWN env file — the
  `env_file` path in `~/.cria/cria.toml` (e.g. `~/.cria/.env`), which holds ONLY cria's own keys.
  cria loads only its allowlisted vars, so it never pulls anything else out of that file. Populate
  it once by copying the value from wherever you keep your secrets — a manual step; NEVER point
  cria at a shared/personal secrets file and NEVER code that path here. Never print or commit the key.
- **Restart cria** (from the cria-shepherd repo dir): kill the python3 procs whose
  `/proc/*/cmdline` contains `cria` (do NOT `pkill -f "python3 -m cria"` — it self-matches the
  launch shell and exits 144), then:
  `setsid nohup python3 -m cria > ~/.cria/cria.out 2>&1 < /dev/null &`
  cria auto-finds `~/.cria/cria.toml` and loads the Brave key from its configured `env_file` —
  no key on the command line.
- **Harness config**: cria needs **nothing special** from the harness — no context-window tuning,
  no compaction settings, no stripped/isolated config. Point the harness at cria's `/v1` and drive
  it with a realistic config. cria discovers the model window and enforces it itself.
- **Single GPU slot**: the 3080 serves :18084 AND renders Blender — contention can look like server
  flakiness; check the GPU before blaming code.

## Context management — LANDED (cria-side, harness-agnostic)
The deterministic "request always fits the window" guarantee is **built and live-verified**:
1. **Context floor** (`cria/contextfloor.py`, applied at the `Upstream._prep` chokepoint) — window
   auto-detected from `/props`; **bounds the tool SCHEMA** (truncates verbose tool descriptions when
   the schema exceeds half the budget — every tool stays callable); budget = `window − reserve −
   tool_schema_tokens`; oversized tool outputs reduced (`content_reduce`); oldest turns trimmed
   (system + active turn preserved, no orphaned tool results). Verified TWICE: a ~486K-token request
   → 24K real prompt; AND the user's REAL `~/.codex/config.toml` (127 tools / 34K schema) →
   compressed to 11.5K, max real prompt 24K, zero llama `exceed`. No CODEX_HOME surgery.
2. This **replaced** the Codex-compaction chase and the isolated-`CODEX_HOME` crutch entirely —
   cria no longer relies on any harness to compact.

## Remaining levers for COMPLETION (verify against real behavior — NOT the answer)
- Per-model settings (gemma rep-penalty; ornith `--reasoning-format deepseek`) → garbage turns that
  never converge.
- The coder framing weakness: with reasoning-off the coder can re-run an earlier step's work (it
  continues the most-recent pattern instead of the buried step instruction). reasoning-on masks it;
  the real fix is to anchor the current step at the END of the framed conversation. See the Report.
Confirm each from logs before acting; assume nothing.

## Deliverable — the Report (update continuously)
Maintain `docs/compaction-live-report.md`. Per model: whether the context floor held (no overflow)
across the run, the sessions run, every issue (with log evidence), its root cause, the fix applied
(file + change), and recommended fixes for anything unresolved. Also capture how each model did on
the actual Ada Handle task — did it produce working code/tests/README, or where did it break.

## Guardrails
- Live-verified or it isn't done. No overconfidence; let real runs close items.
- Upstream fixes only — no mitigations/fallbacks/band-aids.
- One model on the slot at a time; never infer to :18084 while a session is live.
- Ask before any destructive/mass operation; fresh throwaway workspaces only.
- Never print or commit the Brave key.
