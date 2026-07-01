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

## Forward — read-mode / research-loop detectors

Not yet built. They catch a failure mode the built detectors miss: the model spins in **read / research mode** — searching, fetching, reading forever without ever acting.

*Motivating loop:* `web_search "api.handle.me swagger.yml …"` + `web_fetch raw.githubusercontent.com` dozens of times — every call a variation of the same question, all fetches 404, never a file written.

### Governing rule: reset on a change of APPROACH, not of target

`detect_tunnel_vision` resets on any new target, so a stream of *different* queries kept resetting it and it never fired. The fix, for every detector below — the counter resets only on a genuinely different *approach*:

| detector | resets on |
|---|---|
| read-without-write | a **write** |
| same-prefix searches | a **different search prefix** |
| failing fetches | a **2xx result** |

All deterministic — counting ops, comparing a query prefix, reading an HTTP status. No fuzzy inference.

### Relation to tunnel-vision `NEW`

Complementary, not substitutes. Tunnel-vision catches revisiting a **fixed** target set (incl. write loops); read-without-write catches many reads with **zero** writes even when every target differs — the varied loop tunnel-vision misses. #1 is the additive one; #2/#3 are narrower cases between them.

### 1. Read-without-write loop `NEW`

- **Signal:** N read ops (`web_search`, `web_fetch`, `read_file`, `list_dir`, grep) with **zero writes** (`write_file` / `edit_file` / `apply_patch`) among them.
- **Nudge:** *"You seem to be looking for answers you aren't finding. Try something else or take a different approach."*
- **Reset:** any write. The counter is "reads since the last write."

### 2. Same-prefix search loop (nudge → hard block)

- **Signal:** N `web_search` calls whose first `X` words match (`X` ≈ 3–5, tunable).
- **Nudge:** *"Your search isn't yielding results. Change your search string — your next search starting with '&lt;X&gt;' will be denied."*
- **Enforcement (massage):** if the prefix repeats after the warning, **block the call** — return the denial as the tool result.
- **Reset:** a search whose prefix differs from the warned one.

### 3. Failing-fetch loop

- **Signal:** N `web_fetch` calls with **no 2xx** — all 4xx/5xx/errors (guessing at URLs that don't exist).
- **Nudge:** *"You seem to be guessing at what to fetch. Try searching instead."*
- **Reset:** a 2xx fetch.
