# Nudges — the catalog

> **Copied from the `codex-local` research vehicle, which remains the source of
> truth.** Re-sync when the catalog there changes. Companion specs live there:
> [spec index](../../codex-local/docs/spec/index.md) ·
> [the "why" + code pointers](../../codex-local/docs/spec/local-coder-massaging.md).

Overview: [shephard.md](shephard.md). In-context directives that steer the *model* (it sees them) to break loops and force real progress. Name first, one line each; detail + code pointers in [local-coder-massaging.md](../../codex-local/docs/spec/local-coder-massaging.md).

## Built

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

## Read-mode / research-loop detectors

All three are **built**. They catch a failure mode the exact-match / same-file guards miss: the model spins in **read / research mode** — searching, fetching, reading forever without ever acting.

*Motivating loop:* `web_search "api.handle.me swagger.yml …"` + `web_fetch raw.githubusercontent.com` dozens of times — every call a variation of the same question, all fetches 404, never a file written.

### Governing rule: reset on a change of APPROACH, not of target

The existing exact-match guards reset on any change of *target* (full query / full URL), so a stream of *different* queries never accumulates. Each detector below instead resets only on a genuinely different *approach*:

| detector | resets on | layer |
|---|---|---|
| read-without-write | a **write** | trim chain (`detect_read_without_write`) |
| same-prefix searches | a **different search prefix** | tool (`local_web_search::format_results`) |
| failing fetches | a **2xx result** | tool (`web_fetch::append_guess_hint`) |

All deterministic — counting ops, comparing a query prefix, reading an HTTP status. No fuzzy inference.

**Why two layers.** Same-prefix and failing-fetch are single-tool signals, so they live *in* that tool's result formatter (co-located, and the nudge rides in the exact output the model reads). Read-without-write is inherently **cross-tool** — it weighs reads of any kind against writes of any kind — so it can't live in one handler; it's a transcript-derived detector in the trim `.or_else()` chain, ordered *after* exact-repeat and tunnel-vision so a tighter loop is claimed first.

### Relation to tunnel-vision

Complementary, not substitutes. Tunnel-vision catches revisiting a **fixed** target set (incl. write loops); read-without-write catches many reads with **zero** writes even when every target differs — the varied loop tunnel-vision misses. Because read-without-write closes that blind spot directly, tunnel-vision's own target-reset is left intact (its low threshold is only safe *because* of that reset).

### 1. Read-without-write loop — *built* (trim chain, threshold 12)

- **Signal:** N read ops (`web_search`, `web_fetch`, `read_file`, `list_dir`, `grep_files`) with **zero writes** (`write_file` / `edit_file` / `apply_patch` / …) among them.
- **Nudge:** `[GATHERING WITHOUT ACTING]` — name what you already know that's enough to make a first change, then make the one concrete edit that moves the task forward.
- **Reset:** any write. The counter is "reads since the last write." High threshold so legitimate exploration isn't nagged.

### 2. Same-prefix search loop — *built* (tool layer, threshold 3)

- **Signal:** N `web_search` calls whose first 4 words match (the model rephrasing one question — same lead-in, varied tail — which the exact-repeat guard can't see).
- **Nudge:** appended to the search result — *"N searches in a row started with '&lt;prefix&gt;' — change your search STRING (new keywords, a different angle), not just the tail."*
- **Reset:** a search whose prefix differs. *(Forward: escalate to a hard block on the warned prefix, like the repeated-call override.)*

### 3. Failing-fetch loop — *built* (tool layer, threshold 3; pre-existing)

- **Signal:** N consecutive `web_fetch` with **no 2xx** — all 4xx/5xx/errors (guessing at URLs that don't exist).
- **Nudge:** appended to the fetch result — *"N fetches in a row failed; if you're guessing URLs, STOP — find the correct one via search or take a different step."*
- **Reset:** a 2xx fetch. *(A single 404 is not nudged — its body may be real content.)*
