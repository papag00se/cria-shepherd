# Shephard — what it does

> **Copied from the `codex-local` research vehicle, which remains the source of
> truth** — this is the feature catalog to port. Companion specs live there:
> [spec index](../../codex-local/docs/spec/index.md) ·
> [service plan](../../codex-local/docs/spec/nudge-service.md) ·
> [the "why" + code pointers](../../codex-local/docs/spec/local-coder-massaging.md).
> Re-sync this file when the catalog there changes.

> **Shephard** (working name) is the layer that sits between a small local model
> (9B-class) and an agent harness and keeps the two working together to do real
> agentic coding. Everything it does falls into three kinds:
>
> - **Nudges** — in-context directives that steer the *model* (the model sees them).
> - **Massages** — silent repairs of the model's *output* so the *harness* accepts it (the model never knows).
> - **Context shaping** — managing what the model sees and how much, so it fits the window and stays grounded.

Name first, one line each. Detail + code pointers in [local-coder-massaging.md](../../codex-local/docs/spec/local-coder-massaging.md).

## Principle: Shephard owns no executors

Shephard never touches the workspace or runs anything. It is a **bidirectional
transform on the message / tool-call stream**: it rewrites the model's call into a
primitive the *harness* already has on the way **out**, and rewrites that
primitive's result back into the model's high-level tool on the way **in** — so the
model always works with rich tools (`write_file`, `edit_file`, `web_fetch`) while
the harness only ever runs its irreducible primitives (ideally just `shell`).

- **Outbound:** `write_file` → `printf %s '<base64>' | base64 -d > path` (base64 is
  byte-exact and immune to the whole shell escaping/quoting/marker bug-class);
  `web_fetch` → `curl`. The agnostic insight: `shell` — not `write_file` — is the
  one primitive *every* harness exposes, so lowering to it is what makes Shephard
  portable; `write_file`-as-a-tool is harness-specific convenience.
- **Inbound:** re-present the recorded `shell` call (and its result) as the
  original tool, so the model never sees the `shell` underneath. (The old one-way
  `write_file → shell printf` failed precisely because it skipped this half — the
  model saw the mangled shell command and panicked.) Recognized statelessly from a
  `# shephard-write:<path>` sentinel, so it survives restarts.
- **Why it ports:** Shephard requires the harness to provide only execution
  primitives (every harness has `shell`/file-IO); all intelligence is stream
  transforms. The Rust vehicle already reflects this — executors live in
  `codex-core` (the harness), the transforms in `codex-routing` (the brain).

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
- **Active-turn compaction** — summarize a long turn's middle when it alone won't fit.
- **Overflow re-trim** — context overflow → re-trim to the server's numbers and retry, no crash.
- **Last-resort drop** — drop oldest messages (always keep the request) as the fit floor.
- **Oversized-output guard** — output over a dynamic ceiling (% of detected window) is losslessly reduced, or omitted with a "re-run narrower / grep / find=" pointer — never a broken or info-stripped fragment.
- **web_fetch navigation** — paginate (`cursor`), `find=` a section, real HTTP status + body.
- **Current-file pin** — live on-disk contents pinned so the model edits the real file.
- **Browser UA** — auto-add a real User-Agent so sites don't block `curl`.
- **Better errors** — patch/network errors rewritten to say what to try next.
