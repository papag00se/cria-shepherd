# Shephard — what it does

> **Copied from the `codex-local` research vehicle, which remains the source of
> truth** — this is the feature catalog to port. Companion specs live there:
> [spec index](../../codex-local/docs/spec/index.md) ·
> [service plan](../../codex-local/docs/spec/nudge-service.md) ·
> [the "why" + code pointers](../../codex-local/docs/spec/local-coder-massaging.md).
> Re-sync this file when the catalog there changes.

[< Spec Index](../../codex-local/docs/spec/index.md) | service plan: [nudge-service.md](../../codex-local/docs/spec/nudge-service.md) | the "why" + code pointers: [local-coder-massaging.md](../../codex-local/docs/spec/local-coder-massaging.md)

> **Shephard** (working name) is the layer that sits between a small local model
> (9B-class) and an agent harness and keeps the two working together to do real
> agentic coding. Everything it does falls into five kinds:
>
> - **Nudges** — in-context directives that steer the *model* (the model sees them).
> - **Massages** — silent repairs of the model's *output* so the *harness* accepts it (the model never knows).
> - **Context shaping** — managing what the model sees and how much, so it fits the window and stays grounded.
> - **Probes** — Shephard makes its OWN read-only tool calls back to the harness to get ground truth, rather than only relaying the model's. Verify by *doing*, not by reading. (The first Probes — the repo-diagnostic completion gate — are **built**; see below.)
> - **Reasoned guidance** *(mostly forward)* — on a stuck trigger, query the light reasoner (grounded by a probe) for a context-aware redirect instead of a canned nudge.

The marketable catalog of every assist — name first, one line each — is in [heuristic-assists.md](heuristic-assists.md); the why + code pointers in [local-coder-massaging.md](../../codex-local/docs/spec/local-coder-massaging.md).

## Principle: Shephard owns no executors
- **What it is** — never touches the workspace; a bidirectional transform on the tool-call stream. Model works with rich tools (`write_file`, `web_fetch`); harness only runs primitives (ideally just `shell`).
- **Outbound** — `write_file` → `printf %s '<base64>' | base64 -d > path` (byte-exact, escaping-proof); `web_fetch` → `curl`. `shell`, not `write_file`, is the one primitive every harness exposes — lowering to it is what ports.
- **Inbound** — re-present the recorded `shell` call + result as the original tool, so the model never sees the shell. Recognized statelessly from a `# shephard-write:<path>` sentinel (survives restarts). The old one-way `write_file → printf` failed by skipping this half.
- **Why it ports** — harness supplies only executors (Rust vehicle: `codex-core`); all intelligence is stream transforms (`codex-routing`).

## Principle: Shephard owns no rendering either
- **The rule** — every tool Shephard exposes must reduce to a primitive the harness already knows how to both *run* and *display*. A custom tool/event is a bet the harness will draw something it was never taught to.
- **Cautionary example** — the fork's custom `local_web_search` (Brave) emitted `WebSearchBegin`/`End`; searches ran and hit the rollout but the TUI never rendered them. Lower to `curl` over `shell` and it shows as an ordinary exec cell — visible everywhere.
- **Preference order** — native structured tool (`text_editor.create`, richest) → native file handler → `shell` (universal, always rendered). Never a Shephard-only tool the harness must be taught to draw.

## Principle: guard state is session-scoped
- **The rule** — anything a guard remembers (searches made this turn, URLs fetched, streaks) belongs to **one session's current turn**, never a process global. It resets on a new user turn (new task = clean slate) and never bleeds between sessions, sub-agents, or forks.
- **In Shepherd** it's just a field on the **session object** — the service already holds per-session state, so there's no keying and no eviction.
- **In this Rust fork** the tool backends are stateless module fns, so we *simulate* it: a map keyed by the harness `conversation_id`, scoped to the turn `sub_id`, capped (`guard_state::SessionTurnStore`). The map is a fork wart, not the design — the seam that makes the port trivial.

## Nudges — steer the model
In-context directives the model sees, to break loops and force progress. The full catalog — the built guards plus the read-mode / research-loop detectors — lives in [/heuristic-assists.md](heuristic-assists.md).

## Massages — repair the output so the harness runs it
Fixing model outputs before sending them back to the agent harness. The full catalog — lives in [heuristic-assists.md](heuristic-assists.md).

## Context shaping — manage what the model sees
Intelligent context manipulation to assist models through their own mishaps. The full catalog — lives in [heuristic-assists.md](heuristic-assists.md).

## Probes — Shephard acts for itself *(the first Probes are BUILT)*

Everything above is a *transform on the stream*. Probes are different: Shephard makes
its **own** read-only tool calls back to the harness — not to relay the model's, but for
its own supervisory purposes — and reads the result on **its** terms.

**Why it matters.** It dissolves the recurring wall "the harness can't judge X without
parsing the model's noisy output or *being* a model." If Shephard can **act**, it gets
**ground truth deterministically** — it picks the command *and* the output format.
**Verify by *doing*, not by reading.** The eval showed why this is the highest-value
move: weak local models rewrote a whole file 9× chasing an `IndentationError` they
couldn't localize — the exact `file:line` a probe hands over is what they couldn't
generate for themselves.

**Built — the repo-diagnostic probe system + ground-truth completion gate:**
- **Language-aware syntax floor** — `py_compile` / `node --check` over the files on disk,
  always available, giving the exact `file:line` for parse errors (`linter_probe`).
- **Repo probe discovery** — inventory the repo's ecosystems (JS/TS, Python, Rust, Go,
  JVM, .NET, PHP, Ruby, Elixir) → a RANKED list of SAFE diagnostic commands
  (typecheck/build/lint before tests), the package manager chosen from lockfiles, and
  `package.json`/Make scripts vetted (install/mutate/watch/service rejected) before they're
  offered (`probe_discovery`, `probe_classifier`).
- **Bounded runner + parsers** — run the top-ranked safe probes with a hard timeout,
  capture without deadlock, parse rustc/tsc/ESLint/pytest/generic output into `file:line`
  findings (`probe_run`, `probe_parse`).
- **Ground-truth completion gate** — on a "done" claim, Shephard runs the syntax floor +
  the top probe ITSELF and ends the turn only if the code passes; a real diagnosis becomes
  the re-prompt (the exact line to fix), so the model stops rewriting whole files blind
  (`probe_run::completion_block_nudge`, wired in `local_routing.rs`).
- Detection is **disk-based, never prompt-based** — Shephard lints what the model actually
  wrote; whether the chosen language honors the task (incl. "don't use Python") is a
  *reasoning* call left to the completion verifier, not a keyword match.

**Forward — more supervisory probes on the same substrate:**
- **Active grounding on a stuck/tunnel-vision trigger** — the structural detector says
  *when* (footprint stalled); a probe gets the *truth* (re-read the live file, run the
  failing check) and feeds fresh verified state into the nudge, so the model can't work
  from stale context.
- **Environment probing** — code-bug vs environment (curl the real endpoint to see if a
  4xx is the code or a missing header), instead of guessing.
- **On-demand fresh-state pin / pre-flight checks.**
- **Open protocol question** — a *private* call→result round-trip the model (and ideally
  the user's UI) never sees.

**Guardrails** (these calls EXECUTE): read-only / idempotent only (never mutate the
workspace); triggered, not constant (a "done" claim, a stuck trigger — each probe is real
work on the box); hidden from the model's context so they never accrete in the transcript.

**Architecturally consistent with "owns no executors":** Shephard still owns none — it
**borrows the harness's** executors for its own supervisory ends, which makes it an
**actor / supervisor**, not merely a stream transform.

## Reasoner-assisted redirect *(forward — speculative, captured so it isn't lost)*

The deterministic guards detect a stuck pattern and fire a **fixed** nudge. This is
the smarter successor: on the same structural trigger, escalate to the **light
reasoner** (a separate, cheap local role) to (1) infer what the coder is actually
*trying to do* from its recent transcript, and (2) propose a concrete new path — then
inject that as the nudge, instead of a canned message.

- **Structural detector says WHEN** (loop / tunnel-vision / read-without-write /
  repeated failure); the reasoner supplies a **context-aware WHAT**.
- **Kin to Probes.** Probes get *ground truth* by acting; this gets a *redirect* by
  reasoning. Best combined — probe for the real state, hand it to the reasoner, and
  let it suggest the path grounded in fact so it can't invent a dead end.
- **Guardrails, like probes:** only on a confirmed stuck signal (a real model call,
  not every turn); the reasoner is itself a small local model, so ground it with
  probe truth rather than trusting its guess.
- **Status:** may or may not earn its keep — same open question as Probes. Noted now
  because the pattern-triggers it would ride on (the detectors) already exist.
