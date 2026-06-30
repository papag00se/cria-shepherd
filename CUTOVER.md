# llama-shepherd — Cutover Kickoff

> A brief for the agent/engineer beginning the port. Read this, then the three spec
> docs it points to, before writing code.

## What you're building

**Shepherd** — a standalone, harness-agnostic service that sits between a small local
model (9B-class; today `Ornith-1.0-9B` on llama.cpp at `127.0.0.1:18084`) and any
OpenAI-compatible agent harness, and makes the pair do **real agentic coding**.

It is the production **Python** form of the **"Shephard"** research built inside the
Rust fork at `../codex-local`. The driving goal: *make a 9B do agentic coding on its
own via a smarter harness — no human surfacing, no cloud. "It's just a 9B" is not an
acceptable answer; the harness is the answer.*

## Source of truth — read these first

The Rust fork (`../codex-local`) is the **research vehicle**; the **specs are the
deliverable**. Port from them, not by guessing:

1. [`docs/shephard.md`](docs/shephard.md) — the **catalog**: every Nudge / Massage /
   Context-shaping move, one line each. This is the feature list to port. (Copied
   in-repo from `../codex-local/docs/spec/shephard.md`, which stays the source of
   truth — re-sync when it changes.)
2. `../codex-local/docs/spec/nudge-service.md` — the **service architecture**:
   OpenAI-compatible streaming boundary, heartbeats, session header, file-pinning,
   what stays in the harness.
3. `../codex-local/docs/spec/local-coder-massaging.md` — the **why + code pointers**
   for every intervention; the reference when porting a specific behavior.
4. Reference impl: `../codex-local/codex-rs/routing/` (`codex-routing` crate = the
   brain) and `../codex-local/codex-rs/core/src/local_routing.rs` (the loop driver).

## The shape (the spine)

- **Nudges** — in-context directives that steer the *model* (it sees them).
- **Massages** — silent repairs of the model's *output* so the harness accepts it
  (the model never knows). **Bidirectional:** rewrite the call to a harness primitive
  outbound, re-present the result as the original tool inbound.
- **Context-shaping** — manage what the model sees and how much.

**Core principle — Shepherd owns no executors.** It is a transform on the
message/tool-call stream. The harness keeps tool *execution* + the workspace. `shell`
is the one primitive every harness has; rich tools face the model, `shell` faces the
harness.

## The service boundary (from nudge-service.md)

- OpenAI-compatible `/v1/chat/completions` **streaming** endpoint; the harness points
  its model client at Shepherd and gets better completions, knowing nothing of the
  nudging.
- Shepherd does all massaging internally and returns final completions **with tool
  calls**; the harness runs the tools and sends results back next turn.
- **Heartbeat-keepalive SSE** (the loop runs minutes → idle-timeout, not
  total-timeout). Stream heartbeats/reasoning during the loop; commit only the final
  accepted completion as content.
- `X-Nudge-Session-Id` header for the few stateful bits (classifier cache, `/stats`);
  stateless fallback when absent.
- **Indicators** (chosen route, model, guards fired, context moves) are surfaced as
  out-of-band telemetry, **never in the model's context** and trivially stripped
  before the upstream call — see [`docs/indicators.md`](docs/indicators.md).
- **Harness pre-pins file contents** into the transcript, so the service isn't locked
  to co-location.
- Config (models, failover chains, budgets, temperatures) lives in the **service**.

## Compaction — persist, don't reinvent (a key decision)

The Rust vehicle does **transient** compaction every turn (re-summarizing a growing
turn from scratch — a GPU-pegging "storm"). For a **local-only** service the right
model is to **persist**: summarize once, write it back.

Compaction is always **trigger → summarize → persist**, and the split decides whether
Shepherd is stateful:
- **Harness has native compaction (Codex-grade):** *tap it.* Configure its trigger at
  the **real local window** + hand it the prompt; the harness persists. Shepherd =
  **trigger + shape, not do.** (Codex knobs: `model_context_window`,
  `model_auto_compact_token_limit`, `compact_prompt`.)
- **Bare harness (no native compaction):** Shepherd does it, and to persist it must
  hold **session state** (the conversation, keyed by `X-Nudge-Session-Id`).

**Window-reporting is the universal lever.** Harnesses learn the window from their
**config/registry, not the server** — so they're blind to a small local model until
told. Shepherd knows it (probe `/props`); report it (config the operator sets, or
expose it on `/v1/models`). This also makes the harness's **context-% gauge** honest
(gauge = real usage ÷ real window; Shepherd reports the real usage in the response).

## Stack — vanilla Python, low-to-no dependencies

**Standard library first.** The whole service fits in the stdlib; reach for a
dependency only when stdlib genuinely can't do the job, and justify it in the PR.
No FastAPI / Starlette / httpx / pydantic unless a concrete need forces it.

- **HTTP + SSE endpoint:** `http.server.ThreadingHTTPServer`. Stream SSE by writing
  and flushing chunks to `wfile`; one thread per request. A localhost/LAN, single-user
  service does not need async machinery or a web framework.
- **Upstream llama.cpp calls:** `urllib.request` / `http.client` — read the upstream
  SSE line by line and forward.
- **JSON:** `json`. Token estimates / trim / calibration: pure Python.
- Heartbeats during dead time (classify/trim with no upstream bytes flowing): a small
  timer thread or periodic flush from the request thread.

Keep it boring and dependency-light.

## Port order

1. **First cut:** the SSE server skeleton + upstream llama.cpp client + heartbeat
   keepalive. Prove an end-to-end passthrough completion works.
2. **Context-shaping** (biggest reliability wins, mostly pure functions): window
   auto-detect (`/props`), real-token calibration, transcript trim, oversized-output
   guard.
3. **Massages:** leaked-call recovery, malformed-JSON repair, the bidirectional
   `write_file → shell` massage, tool-name aliases.
4. **Nudges:** repetition / forced-diagnosis / context-reset guards, quality gate,
   completion verifier, tool-call constraint.
5. **Loop driver** (bail / rumination / overflow retry) extracted from
   `local_routing.rs`.

Port the **pure logic first** (trim, calibration, signatures, content-reduce) — it's
mechanical and already well-tested in Rust. Save the loop driver + streaming for last.

## Lineage — this session (2026-06-29)

This repo is kicked off from codex-local session
`9b0db794-ff29-470c-9934-90172df66967`. What that session built — and the port should
carry over:

- **Real-token calibration.** The chars/4 estimate runs ~3× low on dense code/JSON.
  Learn the real ratio per model over the **full** prompt (incl. tool schemas),
  **rise-fast/fall-slow** EWMA, and **reserve tool schemas in real tokens**. (Fixed
  the recurring context overflows.)
- **Oversized-output guard.** Bound any tool output over a % of the detected window:
  lossless reduce (JSON minify / HTML→text), or **omit with a "re-run narrower /
  grep / find=" pointer** — never a broken or info-stripped fragment (drop > elide).
- **`write_file → shell base64` bidirectional massage** — the key portability proof.
  `shell` is the agnostic primitive (**not** `write_file`, which is harness-specific
  convenience). The model emits `write_file`; Shepherd lowers it to
  `printf '<b64>' | base64 -d > path` (byte-exact, escaping-proof); **inbound** it
  re-presents the recorded shell call as `write_file` so the model only ever sees its
  own tool. This is THE pattern for "owns no executors." (base64 over heredoc:
  immune to the whole shell escaping/quoting/marker bug-class.)
- **Compaction hardening.** A small local compactor can **wedge in a repetition loop**
  and freeze the turn (observed: one chunk generating 8+ min, pegging the box) → a
  **60s per-chunk timeout** + **fence-strip** the extractor (small models wrap JSON
  in ` ```json `).

**Known constraints to carry in:** the local model wraps JSON in ` ```json ` fences
(strip first, breaks every JSON parser); leaks tool calls in the XML-function dialect
(`<tool_call><function=…>`); the box is a **GPU** (RTX 3080, shared with Blender) —
**prefill/first-token is the bottleneck**, not generation.

## Your task

Stand up the first cut (port order #1), then work down the catalog. Treat the specs
in `../codex-local/docs/spec/` as the source of truth; update them if the port reveals
something the research didn't.
