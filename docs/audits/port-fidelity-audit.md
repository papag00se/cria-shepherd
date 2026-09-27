# cria Port Status & Deferrals — the living ledger

**What this is.** The single living record of the cria (Python) ↔ codex-local (Rust) port: what has LANDED, and what is deliberately DEFERRED (with the concrete trigger that resolves it). It supersedes the original 2026-07-07 fidelity snapshot and **absorbs the old `DEFERRALS.md`**. Point-in-time deep audits (with reason-verdicts and `file:line` evidence) live under `docs/audits/` — most recently `docs/audits/2026-07-15-port-parity-audit.md`. Rule: a de-scope that isn't in THIS file doesn't exist as a decision — it's a silent drop. Close an entry by deleting it in the PR that lands the work.

---

## Recently landed

The 2026-07-15 port-parity pass (see the audit doc) closed the gaps a live Ada-handle session exposed:

- **web_fetch, in-process** — cria fetches + structurally reduces JSON/YAML itself (per-URL cache, `find`/`cursor` navigation, top-level-keys outline, `$ref` inline, browser UA), lowering only the bounded result. A large single-line spec is navigable, not truncated garbage. (`cria/webfetch.py`)
- **fetch/search repeat-gates + stop-guessing nudge** — exact-repeat external fetch/search this session is refused; 3 consecutive non-2xx fetches nudge "stop guessing"; internal hosts exempt.
- **groundtruth wired** — the reasoned redirect now reads the coder's touched files from disk (`groundtruth.file_snapshot`) instead of the stale transcript view.
- **runtime failover + per-role endpoints** — `cria/failover.py` (classify F1–F9 / decide / walk); `upstream.chat` retries the same endpoint once on a transient timeout; a `LocalRole` may name its own `base_url` (roles need not share a host/port); `Router.route_chain` yields the ordered routes.
- **floor synthesis** — the last-resort drop-oldest now replaces dropped turns with a protected `⟦cria:compacted⟧` note recording the files they modified, instead of deleting them.
- **Native `<|tool_call_start|>` sentinel stripping** — `<|tool_call_start|>…<|tool_call_end|>` (whole pairs + orphans) stripped from content, so a supported family's leaked native call can't poison the plan.
- **lint gate is error-class only** — unused-import/never-used advisories no longer block a step.
- **planner web_fetch fixed** — the `_USER_AGENT` NameError that broke every gather fetch.
- **secrets hardening** — `BRAVE_SEARCH_API_KEY` is a hardcoded constant; the env-file loader is allowlist-scoped (never loads a shared file's other secrets); config = `~/.cria/cria.toml` merged with `./cria.toml` (cwd wins), `CRIA_CONFIG` removed.

---

## Deferred — cloud routing

- **OpenAI-compatible cloud calls — wired, UNVERIFIED against a live provider.** Same wire protocol as local, tested only against a fake upstream. — *Trigger:* first `local_only = false` with a real key; smoke it and delete this.
- **Claude-CLI workspace cwd is config-sourced, not per-request.** Correct only when cria is co-located with / configured for the workspace. — *Trigger:* serving multiple workspaces; take cwd from a request header.
- **Anthropic HTTP API — TABLED.** codex-local's `provider = "anthropic"` shells out to the `claude` CLI (done); there is no raw-API path to port. Raw `api.anthropic.com` would be net-new, not a port.

## Deferred — harness compatibility

- **Anthropic-compatible INBOUND endpoint** (so Claude Code can drive cria). Today cria exposes only OpenAI-compatible `/v1/chat/completions`. Needs a second inbound endpoint translating Anthropic Messages requests/streams to the internal shape. — *Trigger:* its own phase; harness-agnostic loop work doesn't block on it.

## Deferred — steering (still unbuilt vs the Rust)

These are the model-facing levers the 2026-07-15 audit confirmed absent (some docs previously implied otherwise):

- **`tool_choice="required"` sampler enforcement** on a no-action retry — `LocalRole` has no `tool_choice`; cria leans on prose nudges + the gate. — *Trigger:* build alongside the no-action escalation.
- **No-action ESCALATION tier** — cria fires one flat LEG0 nudge; the Rust escalates (embed the prior-prose excerpt → "one tool call, no prose", counted to a bail cap). Model-facing only, never human-surfacing. — *Trigger:* a still-chatty model observed burning gate round-trips.
- **Response-quality gate** — no empty/short/echo/refusal/degenerate pre-filter on text-only turns. — *Trigger:* a fleet model whose refusals/echoes reach the gate.
- **Prose-repetition detector** — the same prose diagnosis N× with no tool call trips nothing (guards fingerprint tool_calls only). — *Trigger:* the 18×-prose Ada-handle shape recurs.
- **Course-change reset + context-rebuild excise** — no grace window when the coder pivots on its own; no clean-slate context surgery on a persistent flail. — *Trigger:* after the above land.
- **Reasoner completion critic on the plan-off path** — plan-off verifies "done" with the objective gate only (no critic), so tests-that-didn't-run can pass. Conflicts with "fixes in BOTH paths". —
  *Trigger:* a false plan-off completion observed.
- **`tool_recovery` bare-JSON / `tool_use`-block recovery** (Strategies 1 & 2) — only `<…>`-marker leaks recover; a marker-less JSON tool call is lost. — *Trigger:* a fleet model that emits them.
- **`tool_format` builtin-variant survival** — type-only builtins (`{"type":"web_search"|"local_shell"|…}`) are dropped; latent-HIGH if the shell ever arrives type-only. — *Trigger:* a harness that sends one.
- **`edit_target` `*** Move to:` / `*** Delete File:` / `text_editor`** — guards don't attribute those edits to a file. — *Trigger:* a coder looping via renames or a `text_editor` harness.
- **`feedback` / `codebase_context` classifier learning** — no per-project routing-success profile or project scan fed to the classifier. Plausible de-scope for a harness-agnostic tool. — *Trigger:* a routing-quality plateau.

## Deferred — context floor

- **System-prompt compression** — an oversized incoming system prompt is un-trimmable (system msgs are un-droppable, no compressor) → a loud `over_budget`. — *Trigger:* a harness shipping a huge system prompt on the passthrough path.
- **base64-blob stripper / poll-loop collapse** — not ported. — *Trigger:* those shapes bloating a window in practice.
- Estimator edges (image/base64 token-invisible; CJK undercount; a giant single-user paste is neither reduced nor droppable). — *Trigger:* each surfaced by a real overflowing request.

## Deferred — probes / completion gate

- **Acceptance ceiling NOT ported** (deliberate: operator no-cap directive — a step never advances unverified; a stall only logs `loop.gate_stalled`). — *Trigger:* the operator revisits no-cap.
- **Workspace discovery reads local disk** (co-located deployment); seams exist for a remote-workspace adapter. — *Trigger:* cria deployed away from the workspace host.
- **Per-probe timeout is a constant** (`COMPLETION_PROBE_TIMEOUT_S`), not a toml knob. — *Trigger:* a repo whose legit suite needs more.
- **TypeScript without a tsconfig** has no parse-only tier-0. — *Trigger:* such a repo in practice.
- **`claude_cli` empty output = success**, where the Rust returns Err → failover. — *Trigger:* an empty escalation observed handing back a blank turn.
- **PEP621 / setuptools SCHEMA floor for pyproject.toml** — the config-syntax floor (`_TOML_CHECK`) only catches TOML *syntax*; a file that is valid TOML but broken schema (`[build-backend]` for `[build-system]`, `[project].requires` for `dependencies`, a `[project.scripts]` targeting a nonexistent package) parses clean and is never flagged. This is the small model's DOMINANT pyproject failure (session 20260716T231524). Deferred deliberately: a hand-rolled schema linter fails the assists-are-footguns bar (its assertions could be wrong/incomplete), and `validate_pyproject` is not installed on the box (an always-abstaining probe adds nothing). — *Trigger:* a real ground-truth validator is available (`python -m validate_pyproject`, or parsing the model's own `pip install -e .` metadata errors) so the check stays fact-based, not judgment.
- **Error-persistence detector** — surface a gate finding that recurs unchanged across N gate runs (the model kept re-hitting `smoke_test.py:2` while the loop-breaker fingered the file it kept rewriting). Partly mitigated now that a pytest collection error is localized to file:line. —
  *Trigger:* a recurring-finding spiral observed despite the localized nudge.

## Deferred — loop refinements & behavior

- **Live token streaming inside the loop** — the loop buffers each coder turn then fake-streams it.
  *Refinement:* forward the real token stream, intervene only at end-of-stream.
- **Strip cria's own `.cria/` tool calls from the coder's view** in `_frame_for_item`.
- **Planner INVESTIGATE two-phase depth** — the gather-and-plan loop IS built; the deeper investigate/plan split is a quality refinement, not a correctness gap.
- **Engagement gate is classified + logged, not yet behavioral** (question vs task both route identically). — *Trigger:* the divergence is wired when the loop needs it.
- **Guards on a plain streaming (`/v1/chat/completions`) plan-off client** — the direct-coder+guards branch lives on the buffered/Responses path. — *Trigger:* a streaming non-Responses coding harness.
- Harness-compaction residuals (`task:`-keyed sessions have no rewrite detection / persisted briefing; `prompt_cache_key` trusted as a per-conversation id; a plan-off turn-end briefing is not emitted). — *Triggers:* recorded per entry in `docs/audits/2026-07-15-session-audit-lens.md`.

## Deferred — LOW / wire-fidelity (each recorded so it isn't re-discovered)

`wrap_stream` emits the tok/s delta after the finish chunk; `_repair_double_escaped` can rewrite a legit single-line-with-literal-`\n` file; `responses.to_chat_body` mints ids for a `function_call` lacking `call_id`; `step_framing.txt` editorializes "may contain mistakes". Full detail + triggers in `docs/audits/2026-07-13-*` and the 2026-07-15 audit.
