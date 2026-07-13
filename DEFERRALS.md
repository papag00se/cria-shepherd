# Deferrals — known-not-done, with the plan

A living ledger so nothing is silently dropped. Each entry says **what**, **why it
isn't done yet**, and the concrete **trigger** (a phase, or a condition) that
resolves it. Close an entry by deleting it in the PR that lands the work.

---

## Cloud routing

### Anthropic **API** — TABLED (not a real path in codex-local)
The Rust vehicle's `provider = "anthropic"` entries do **not** hit the Anthropic
HTTP API. They resolve to `ResolvedRole::ClaudeExec`, which shells out to the
**`claude` CLI** — no `api.anthropic.com`, no `/v1/messages`, no `x-api-key`. So
there is nothing to port on the API side, and cria's OpenAI-compatible cloud
provider deliberately does **not** pretend to speak Anthropic's API. If we ever
want the raw Anthropic API (not the CLI), it's net-new work, not a port.

### Claude-via-CLI escalation — DONE (`cria/claude_cli.py`)
Ported: a `ClaudeCliProvider` (a `cloud.*` role with `kind = "claude_cli"`) that
runs `claude -p … --model … --output-format json [--resume …]` in a cwd, parses the
result, tracks the session for `--resume`, and adapts it to the provider interface
(buffered + fake-streamed). One caveat below.

### Claude-CLI workspace cwd — sourced from config, not per-request
The Claude provider runs `claude` in `[providers.claude].cwd` (or cria's own cwd if
unset) — this is the one place cria *does* run an executor (the escalation), so it
genuinely needs a cwd. That's correct only when cria is co-located with, or
configured for, the workspace.
- **Trigger:** if/when cria must serve multiple workspaces, take the cwd from a
  request header. (The *plan* file no longer needs this — it's created/read via the
  harness's own tools, so cria never needs the workspace path for it.)

### OpenAI-compatible cloud calls — wired, UNVERIFIED against a live provider
The router resolves cloud, picks provider+model, and builds an authed `Upstream`
(Bearer). Because a cloud OpenAI-compatible endpoint is the *same* wire protocol as
the local one, this should just work — but it has only been tested against a fake
upstream, never a real key.
- **Trigger:** the first time `local_only = false` with a provider key set; smoke
  it against the real endpoint and delete this entry.

---

## Harness compatibility

### Anthropic-compatible INBOUND endpoint — for Claude Code as a client
cria is meant to sit behind *any* agent. Today it exposes only the
OpenAI-compatible `/v1/chat/completions`, so every OpenAI-compatible harness
(Codex, Aider, Cline, Roo, …) works. **Claude Code does not** — it speaks the
Anthropic Messages API (`/v1/messages`, redirected via `ANTHROPIC_BASE_URL`). To
support it, cria needs a second inbound endpoint that accepts Anthropic-format
requests, translates them to the internal (OpenAI-ish) shape the pipeline already
uses, and translates the response + stream back.

- **Scope:** system-prompt handling, `content` blocks, `tool_use` / `tool_result`
  mapping, and the Anthropic SSE event types (`message_start`, `content_block_delta`,
  …) vs OpenAI's `chat.completion.chunk`. The indicator inject/strip and routing
  are unaffected — they operate on the internal shape.
- **Note:** distinct from the *outbound* Claude-CLI provider (done). This is cria
  *serving* Claude Code, not cria *calling* Claude.
- **Trigger:** its own phase — sizeable enough to stand alone. Doesn't block the
  planner/loop work, which is harness-agnostic.

## Assists still to port (phase 7)

### Destructive-overwrite guard — TABLED (per operator; owns-no-executors wrinkle)
Refuse a write_file that would replace a good file with a truncated fragment (the
"valid handler → 7-byte stub" data-loss bug). In codex-local this compared the new
content to the EXISTING file's size, which it could read (it owned the executor).
cria owns no executors, so it can't see the existing file — the guard is either
content-only (looks truncated: unbalanced, ends mid-statement, trivially tiny) or
reads the file first via a harness tool round-trip. Deferred at the operator's
request; noted so it isn't lost.

## Loop refinements (phase 6 simplifications, flagged in `cria/loop.py`)

### Live token streaming inside the loop
The loop BUFFERS each coder turn so it can decide tool-calls-vs-done before
responding, then fake-streams the chosen completion. Correct, but the user sees
each step as a block rather than live tokens. Refinement: forward the coder's real
token stream and only intervene (append a keep-alive tool call) at end-of-stream
when it turns out to be a bare "done".

### Strip cria's own file-op tool calls from the coder's view
cria's `.cria/` shell writes land in the harness conversation; the loop's
`_frame_for_item` doesn't yet remove them, so the coder sees them. Filter cria's own
tool calls + their results before framing the step for the coder.

### Cloud coder/reasoner inside the loop
The loop calls the LOCAL upstream for the coder and reasoner. Cloud escalation
(routing/failover) inside the loop is not wired — a stuck step can't yet escalate
to a bigger model. Ties in with the redirect/escalation work.

### Planner INVESTIGATE phase (gather-then-plan) — port of codex-local assist #1
cria's planner is single-shot: one reasoner call → a numbered-list plan (now parses
list OR JSON; the numbered-list ask is what makes Gemma-class models plan at all).
codex-local's `reasoned_guidance.rs` does more — a two-phase **INVESTIGATE-then-PLAN**:
it hands the reasoner READ-ONLY tools (exec_command/read_file/web_fetch/web_search),
lets it inspect the repo + fetch docs, then plans GROUNDED in what it found (real
files, endpoints, conventions — not guesses). Verified live (2026-07): all four
non-MoE models plan fine single-shot, so this is a QUALITY refinement, not a
correctness gap. Porting it means the planner becomes its own harness-run tool loop
before the plan is set (owns-no-executors: the tool calls go to the harness, like
the coder loop). Left for later.

---

## Behavior

### Engagement gate — classified + logged, not yet behavioral
The task/simple/question decision is made and recorded every request, but both
paths still route + proxy identically. The *divergence* — a `question` skips the
plan loop, a `task` engages it — depends on the loop existing.
- **Trigger:** phases 5–6. The gate's output is already in the event stream, so
  wiring the branch is small when the loop lands. (Also then: the retroactive
  escalation — gate said "light" but the model starts an agentic loop → engage.)

---

## Harness compaction (incoming)

### Post-compaction continuation — BUILT (structural), residual gaps recorded
Context: cria must SURVIVE the harness compacting its own conversation (the VS Code
Codex path does this live; the old "Codex compaction never fires" finding was
`codex exec`-specific). Built 2026-07-11, structurally — **no phrase-matching**:
a session's conversation ROOT (first non-env user message) is fingerprinted per
request (`LoopStore.observe_shape`); a changed root under a stable session key =
the harness rewrote the history. Then: a post-`loop.done` rewrite plans a
CONTINUATION (`prompts/plan_rewritten.txt` — summary as record-of-done + current
intent, never stacked with cria's own briefing); a mid-plan rewrite re-issues a
probe whose result the rewrite erased (instead of fail-open passing). The briefing
itself RIDES IN THE CONVERSATION (a `⟦cria:briefing⟧` envelope in the closing
message): the harness stores it, its compactor summarizes from it, cria re-reads it
from history. Server-side state is DETECTION only — shapes + a one-bit `done`
marker (`<log-dir>/loopstate.json`); there is no server-side briefing store.

Hardened after an adversarial review workflow (15 confirmed findings, all fixed
2026-07-11): `session_key` now skips env-context preambles (was colliding every
conversation in a repo onto one `task:` key → false rewrites + briefing leaks);
rewrite detection AND persisted briefings are gated to content-independent `sid:`
keys (a briefing under a task-text hash resurrects for unrelated same-prompt runs —
the plan-cache leak, persisted); a post-compaction turn where the user typed a NEW
ask respects the classifier (a question is proxied, never hijacked into a plan —
only a PURE handoff bypasses it); the rewrite signal is sticky until acted on (a
failed plan attempt doesn't consume it); probe re-issues are capped
(`MAX_PROBE_REISSUES`); `drive` is serialized per session key; store eviction is
LRU-refreshing; the state file tolerates garbage; the planner's negative cache is
frame-aware.

Residual gaps (each with its trigger):
- **`task:`-fallback-keyed sessions deliberately have NO rewrite detection and NO
  persisted briefings** — the key derives from the root, so detection is
  meaningless and briefings would leak across same-prompt conversations.
  - **Trigger:** a harness that sends neither a session header nor prompt_cache_key
    AND needs continuations. Then: mint a server-assigned session cookie.
- **`prompt_cache_key` is trusted as a per-conversation id — a Codex convention.**
  A spec-following client could send a COARSE key (e.g. per-user), making distinct
  conversations share a session → false rewrites (bounded by the pure-handoff +
  classification gates, but still wrong).
  - **Trigger:** a non-Codex Responses harness in the wild. Then: prefer a
    dedicated session header; treat prompt_cache_key as a hint only.
- **A compaction with NO prior briefing and a non-task classification is proxied,
  not continued** (deliberate: don't hijack a compacted question-chat).
  - **Trigger:** observed mis-handling of a real task in this state.
- ~~Live PlanSession does not survive a cria restart~~ — CLOSED 2026-07-12: restarts
  proved routine (7 in one morning; one mid-plan restart re-planned blind and produced
  duplicate near-identical files). Live plans now persist in loopstate.json (durable
  subset: plan + step status + summary; transient turn state reset on resume) and a
  restart RESUMES at the current step — the planner is not consulted.
- **Moment A (the summarize request itself) stays a blind proxy** — it works (the
  local model writes the summary), but cria doesn't label/route it specially.
  - **Trigger:** a harness whose summarize request breaks under the loop's decline
    path, or a need to route compaction to a dedicated role.

---

## Probes / completion gate (ported 2026-07-11 — full multi-ecosystem port)

### What landed
The full codex-local probe subsystem, all five modules + gate wiring, no longer
Python-only: `probediscovery` (9 ecosystems, lockfile→PM mapping, config-file
confidence, tier ranking), `probeclassify` (command-safety classifier +
package-script vetting), `probeparse` (rustc/cargo, tsc, ESLint, pytest, generic
file:line parsers), `proberun` (selection incl. top+top-TEST dedupe, block-nudge +
digest rendering, composed-command transport), `linterprobe`+`groundtruth` (syntax
floor: py_compile → pyflakes escalation, node --check; lint digest, file snapshots),
and `probegate` (cria's seam: compose ONE harness-run script, replay the output
through the ported interpreters). Loop legs: no-tools nudge (once/step), floor+probe
block with exact file:line, critic digest, `loop.gate` truth capture,
`loop.gate_stalled` convergence logging. Upstream quirks preserved and marked.

### Residual gaps (each with its trigger)
- **Acceptance ceiling NOT ported (deliberate conflict):** codex-local accepts a
  stalled completion after 12 re-prompts with an UNRESOLVED banner
  (`unresolved_completion_message`, `keep_reprompting_completion`); cria's operator
  directive is no-cap (a step never advances unverified), so a stall only logs
  `loop.gate_stalled`. — **Trigger:** the operator revisits the no-cap directive.
- **Workspace discovery reads the local disk** (co-located deployment). The seams
  exist (`read_text`/`scan_dir`/`is_dir_on_disk`, injectable Runners) for a
  remote-workspace adapter (inventory-over-harness). — **Trigger:** cria deployed
  away from the workspace host.
- **Per-probe timeout is a constant** (`probegate.COMPLETION_PROBE_TIMEOUT_S=45`,
  floor 60), not a cria.toml knob. — **Trigger:** a repo whose legit suite needs
  more; wire `[tools]`-section keys through server → probegate.
- **TypeScript without a tsconfig has no parse-only tier-0** (tsc needs config;
  node --check rejects TS syntax). — **Trigger:** a TS-without-tsconfig repo in
  practice; candidates: `tsc --noEmit --allowJs` scratch config, or swc/esbuild
  parse if present.
- **JVM/.NET/Elixir tier-0 = their build tools** (mvn/gradle/dotnet/mix) which
  write build artifacts — same cache-writing acceptance as cargo/go upstream.
- **`_extract_cwd` falls back to "."** for the planner's gather; the GATE refuses
  that fallback (would discover cria's own repo) and degrades to a git-only gate.
  Harnesses that never advertise `<cwd>` get no floor/probes. — **Trigger:** such a
  harness matters; then mint an inventory round-trip or a config workspace_root.
  (`LoopContext.workspace_root` already exists for single-workspace deployments.)
- **groundtruth.lint_digest / reasoned-guidance redirect layer** is ported but NOT
  yet wired into any stuck-loop intervention (cria has no coder action-loop
  detectors yet — see the repeat-guards inventory). — **Trigger:** the
  Repetition/Thrash detector port.

---

## Audit-lens findings (2026-07-13) — deferred, LOW severity

A four-lens audit (prompt integrity / wire fidelity / context-budget math / hygiene)
landed 11 fixes across three commits. These remaining findings were rated LOW and are
recorded here so they aren't silently dropped. Each has its trigger.

### Context-budget edges (the estimator is stdlib chars/4, no tokenizer)
- **Image / base64 content parts are token-invisible to the floor estimator**
  (`contextfloor._msg_text` reads only text/content keys of a content-part list). A
  large `data:` image blob contributes 0 to the estimate → a request built around it
  can overflow. — **Trigger:** a multimodal local model actually fed images.
- **CJK / multibyte underestimated on the FIRST request**: `est_tokens = len//4`
  counts code points; CJK tokenizes ~1 token/char, and the learned ratio (capped at
  `tokenratio.MAX_RATIO=3.5`) can't cover ~4× before calibration exists. — **Trigger:**
  a CJK-dense first turn overflowing; add a script-density weight to `est_tokens`.
- **A giant CURRENT user paste is neither reduced nor droppable** → guaranteed
  overflow (`content_reduce` only touches `role==tool`; the last user message is
  protected from dropping). — **Trigger:** a real task whose single ask exceeds the
  window; allow last-resort reduction of an oversized non-tool message.
- **No shed-tools lever**: if the bare tool schema (names/params/enums, all
  descriptions already dropped) alone exceeds budget, the request is surfaced as
  over-budget with no lever to drop whole tools. Surfaced, not silent. — **Trigger:** a
  connector set whose bare schema overflows a small window.

### Wire fidelity (all Codex-insulated; the Responses adapter rebuilds its own shapes)
- **`wrap_stream` emits the `⟦cria⟧ tok/s` content delta AFTER the `finish_reason`
  chunk** (`indicators.py` on `[DONE]`). Nonstandard: a choice is complete once
  `finish_reason` is set. — **Trigger:** a strict SSE reassembler dropping/erroring on
  post-finish content; emit it before the finish chunk or as a usage-style trailer.
- **`writeproxy._repair_double_escaped` rewrites a legit single-line file** whose
  content has a literal `\n` and no real newline (a one-line JSON/regex/.env value) →
  its `\n` becomes a real newline. Bounded to the no-real-newline-anywhere case. —
  **Trigger:** a genuine single-line-with-literal-\n write observed; gate on a stronger
  signal (multiple `\n`, a shebang/`{` lead).
- **`responses.to_chat_body` mints independent ids** for a `function_call` item that
  lacks both `call_id` and `id`, so it no longer correlates with its
  `function_call_output`. Only triggers if a client omits `call_id` (Codex always
  sends it). — **Trigger:** a non-Codex Responses client that omits `call_id`.

### Prompt wording (model-facing; left for the operator's judgment)
- **`step_framing.txt` editorializes** "This plan … may contain mistakes; verify
  before moving on." For a small model this invites second-guessing the very step
  cria is trying to get executed (the rumination guard then has to fight it). —
  **Trigger:** operator decides to de-editorialize; keep the "verify after you change"
  half, drop the "may contain mistakes" invitation.
- **`plan.txt` may emit a step telling the CODER to "search the web"**, but the coder
  in loop mode has no web tool (web/search is planner-only). — **Trigger:** the planner
  INVESTIGATE-phase port (already deferred above), which folds discovered facts into
  concrete steps instead of deferring the lookup to the coder.

### Upstream twin (spec source-of-truth on this machine)
- **`content_reduce`'s ungated plain-text prose-strip** (fixed in cria this pass:
  `cria/content_reduce.py` now gates on prose AND a structural code sniff) mirrors
  `codex-local/codex-rs/routing/src/content_reduce.rs:39`, which still strips
  unconditionally and whose `looks_like_prose` is the same 75%-alpha-or-space test that
  misreads indented code. — **Trigger:** decide whether to sync the guard upstream to
  keep the port and the research vehicle aligned.
