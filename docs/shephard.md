# Shephard — what it does

> **Copied from the `codex-local` research vehicle, which remains the source of
> truth** — this is the feature catalog to port. Companion specs live there:
> [spec index](../../codex-local/docs/spec/index.md) ·
> [service plan](../../codex-local/docs/spec/nudge-service.md) ·
> [the "why" + code pointers](../../codex-local/docs/spec/local-coder-massaging.md).
> Re-sync this file when the catalog there changes.

> **Shephard** (working name) is the layer that sits between a small local model
> (9B-class) and an agent harness and keeps the two working together to do real
> agentic coding. Everything it does falls into four kinds:
>
> - **Nudges** — in-context directives that steer the *model* (the model sees them).
> - **Massages** — silent repairs of the model's *output* so the *harness* accepts it (the model never knows).
> - **Context shaping** — managing what the model sees and how much, so it fits the window and stays grounded.
> - **Probes** *(forward)* — Shephard makes its OWN tool calls back to the harness to get ground truth, rather than only relaying the model's. Verify by *doing*, not by reading. (See below — not yet built.)

Name first, one line each. Detail + code pointers in [local-coder-massaging.md](../../codex-local/docs/spec/local-coder-massaging.md).

## Principle: Shephard owns no executors
- **What it is** — never touches the workspace; a bidirectional transform on the tool-call stream. Model works with rich tools (`write_file`, `web_fetch`); harness only runs primitives (ideally just `shell`).
- **Outbound** — `write_file` → `printf %s '<base64>' | base64 -d > path` (byte-exact, escaping-proof); `web_fetch` → `curl`. `shell`, not `write_file`, is the one primitive every harness exposes — lowering to it is what ports.
- **Inbound** — re-present the recorded `shell` call + result as the original tool, so the model never sees the shell. Recognized statelessly from a `# shephard-write:<path>` sentinel (survives restarts). The old one-way `write_file → printf` failed by skipping this half.
- **Why it ports** — harness supplies only executors (Rust vehicle: `codex-core`); all intelligence is stream transforms (`codex-routing`).

## Principle: Shephard owns no rendering either
- **The rule** — every tool Shephard exposes must reduce to a primitive the harness already knows how to both *run* and *display*. A custom tool/event is a bet the harness will draw something it was never taught to.
- **Cautionary example** — the fork's custom `local_web_search` (Brave) emitted `WebSearchBegin`/`End`; searches ran and hit the rollout but the TUI never rendered them. Lower to `curl` over `shell` and it shows as an ordinary exec cell — visible everywhere.
- **Preference order** — native structured tool (`text_editor.create`, richest) → native file handler → `shell` (universal, always rendered). Never a Shephard-only tool the harness must be taught to draw.

## Nudges — steer the model
- **Repetition guard** — same tool + same args 3×; injects a STOP directive.
- **Forced-diagnosis guard** — same file/goal failing repeatedly; make it read the failure before acting.
- **Thrash guard** — same goal via varying commands, still failing; force a diagnosis.
- **Context-reset guard** — loop ignored past threshold; excise it from context and reframe the task.
- **Rumination guard** — self-doubt spiral mid-generation; abort the stream and re-prompt.
- **Loop-text guard** — same assistant preamble repeated; re-prompt at turn end.
- **Cyclic-pattern guard** — patch→test→cat cycle; block the call and redirect.
- **Dangling-intent guard** — "now I'll do X" then stops; re-prompt to actually act.
- **Announce-without-act escalation** — repeated stalling escalates to "one tool call, no prose."
- **Quality gate** — empty/short/echo/refusal response; re-prompt before spending a verifier call.
- **Completion verifier** — judge "done" claims; only a real Complete ends the turn.
- **Ground-truth gate** — a coder turn ends only if it actually changed files.
- **Tool-call constraint** — bail/stall retry forces a valid (or specific) tool call at the sampler.
- **Failed-patch → rewrite** — failed patch pins the file and forces a whole-file write_file rewrite.
- **write_file-default steering** — prompt makes whole-file write the default; apply_patch/diff disabled.
- **Tunnel-vision detector** — N calls with no new well-defined target (footprint stopped expanding); forces a step-back. Catches circling a fixed target set (incl. re-editing one file).
- **Read-mode loop detectors** *(forward)* — read-without-write, same-prefix-search, failing-fetch; catch circling in *read* space where tunnel-vision can't. Detail: [nudges.md](../../codex-local/docs/spec/nudges.md).

## Massages — repair the output so the harness runs it
- **write_file → shell base64 (bidirectional)** — model's `write_file` lowered to `printf … | base64 -d > path` (the agent-agnostic shell substrate, escaping-proof); inbound the recorded shell call is re-presented as `write_file` so the model only sees its own tool.
- **Leaked-call recovery** — tool calls emitted as text (Hermes/XML/fenced JSON) → promoted to real calls.
- **Shell-name rewrite** — `ls`/`cat`/`grep` emitted as tool names → proper `shell` calls.
- **exec_command array fix** — `cmd` given as `["bash","-lc",…]` → routed to `shell` (else execs a `[`).
- **Malformed-JSON repair** — botched write_file args (raw newlines/quotes) → path+content recovered.
- **apply_patch normalize** — unified-diff → native; add missing `+`/`-`/space prefixes + end markers.
- **apply_patch Add → write_file** — a file-creating patch → robust whole-file write.
- **Fenced-JSON tolerance** — control-model JSON wrapped in ``` fences → extracted.

## Context shaping — manage what the model sees
- **Own concise base prompt** — ~25 lines, write_file-first; replaces the harness's ~351-line one.
- **Tool-menu trim** — show ~10 curated tools instead of the full ~120.
- **Tool cheat-sheet** — plain-language per-tool usage + examples in the prompt.
- **Window auto-detect + derived budget** — read real `n_ctx` from `/props`; budget = window − reserves.
- **Real-token calibration** — learn the model's real chars→token ratio over the FULL prompt (incl. tool schemas), rise-fast/fall-slow EWMA; reserve schemas in real tokens; budget against truth, not chars/4.
- **Transcript trim** — keep active turn, summarize older turns, drop stale reads, sticky errors.
- **Active-turn compaction (incremental)** — summarize a long turn's middle; reuse a rolling summary for the unchanged prefix and only re-compact the new tail, so a growing turn isn't re-summarized from scratch every overflow (the GPU-pegging "storm").
- **Compaction hardening** — per-chunk timeout (a small compactor can wedge in a loop and freeze the turn) + fence-strip the extractor (it wraps JSON in ```` ```json ````).
- **Persist via native compaction** — for a local-only harness, tap its NATIVE compaction (Codex: `model_context_window` + `model_auto_compact_token_limit` + `compact_prompt`) so the summary is written back ONCE, instead of re-doing transient compaction every turn. The harness owns persistence; Shephard supplies the real window + the prompt.
- **Loop-excision inline collapse** — when a loop is excised, replace it with ONE coherent marker ("tried N times, result unchanged, don't repeat"), never a gap that reads as "I haven't acted yet".
- **Guard observability** — loop-guard firings (repetition / forced-diagnosis / context-reset) are logged, not just queued to the TUI, so the logs don't make a firing guard look dead.
- **Overflow re-trim** — context overflow → re-trim to the server's numbers and retry, no crash.
- **Last-resort drop** — drop oldest messages (always keep the request, strip orphan tool-results) as the fit floor.
- **Oversized-output guard** — output over a dynamic ceiling (% of detected window) is losslessly reduced, or omitted with a "re-run narrower / grep / find=" pointer — never a broken or info-stripped fragment.
- **web_fetch navigation** — paginate (`cursor`), `find=` a section, real HTTP status + body.
- **Current-file pin** — live on-disk contents pinned so the model edits the real file.
- **Browser UA** — auto-add a real User-Agent so sites don't block `curl`.
- **Better errors** — patch/network errors rewritten to say what to try next.

## Probes — Shephard acts for itself *(forward — not yet built)*

Everything above is a *transform on the stream*. Probes are different: Shephard
makes its **own** tool calls back to the harness — not to relay the model's, but for
its own supervisory purposes — and reads the result on **its** terms.

**Why it matters.** It dissolves the recurring wall "the harness can't judge X
without parsing the model's noisy output or *being* a model." If Shephard can
**act**, it gets **ground truth deterministically** — it picks the command *and* the
output format. **Verify by *doing*, not by reading.**

**Doors it opens** (all things we hit in practice):
- **Ground-truth completion gate** — on a "done" claim, Shephard runs the test
  ITSELF (`pytest --exit-code` etc.) and ends the turn only if it really passes —
  instead of trusting the claim or parsing the model's transcript.
- **Active grounding on a stuck/tunnel-vision trigger** — the structural detector
  says *when* (footprint stalled); the probe gets the *truth*: re-read the live file,
  run the failing check, and feed fresh verified state into the nudge ("step back —
  here's the actual state I just checked"), so the model can't work from stale context.
- **Environment probing** — code-bug vs environment (e.g. curl the real endpoint to
  see if a 4xx is the code or a missing header), instead of guessing.
- **On-demand fresh-state pin / pre-flight checks.**

**Pairs with the tunnel-vision detector** (a content-blind structural signal:
*N tool calls with no new well-defined `path`/`url` target* → the model's footprint
stopped expanding). That signal decides *when* to probe; the probe supplies the *what*.

**Guardrails** (these calls EXECUTE):
- **Read-only / idempotent only** — run tests, read files, `git status`, `curl`;
  never let a probe mutate the workspace.
- **Triggered, not constant** — only on a "done" claim, a stuck trigger, a
  suspected-stale moment. Each probe is real work on the box.
- **Hidden from the model's context** — probes go through the strip/indicator channel
  so they never accrete in the transcript.

**Open protocol question:** can Shephard do a *private* call→result round-trip the
model (and ideally the user's UI) never sees? It controls the model's view in the
bidirectional model; whether the harness's UI/record shows it is per-harness.

**Architecturally consistent with "owns no executors":** Shephard still owns none —
it **borrows the harness's** executors, now for its own supervisory ends, not just to
relay the model. That makes Shephard an **actor / supervisor**, not merely a stream
transform. The first concrete use is almost certainly the ground-truth completion gate.
