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

All **built**. They catch a failure mode the exact-match / same-file guards miss: the model spins in **read / research mode** — searching, fetching, reading — instead of acting.

*Motivating loop:* `web_search "api.handle.me …"` re-worded dozens of ways + `web_fetch …/swagger.json` re-issued over and over — every call a variation of one hunt, the model burning ~60s of inference per redundant call.

### State is session-scoped

The search/fetch guards remember what's been done **this turn**, keyed by the harness `conversation_id` and reset on a new `sub_id` (a new user turn = a new task). In this Rust fork that's a `conversation_id`-keyed map (`guard_state::SessionTurnStore`, capped at 32 sessions); in Shepherd it's just a field on the session object. See [shephard.md](shephard.md), *"guard state is session-scoped"*.

### 1. Read-without-write loop — *built* (trim chain, threshold 12)

- **Signal:** N read ops (`web_search`, `web_fetch`, `read_file`, `list_dir`, `grep_files`) with **zero writes** (`write_file` / `edit_file` / `apply_patch` / …) among them.
- **Nudge:** `[GATHERING WITHOUT ACTING]` — name what you already know that's enough to make a first change, then make it.
- **Reset:** any write. Cross-tool, so it lives in the trim `.or_else()` chain, ordered *after* exact-repeat and tunnel-vision so a tighter loop is claimed first. High threshold so legitimate exploration isn't nagged.

### 2. Search-rumination — *built* (tool layer, `local_web_search::gate_search`)

- **Signal:** a new search is essentially one already made this turn. Each query is normalized (lowercase, drop stopwords, light-stem, keep `.`/`_`/`-` tokens like `api.handle.me` whole — reusing `loop_detector`'s `STOPWORDS`+`stem`), then compared by word-set: **overlap ≥ 5 → same**, or **both ≤ 5 words AND identical sets → same**, else different. Catches re-wording ("resolve a handle on api.handle.me" ≈ "api.handle.me get_handle endpoint") that a prefix match can't.
- **Action — HTTP 400 on the *first* repeat.** Refused before the network hit, returned as `HTTP 400 Bad Request · web_search "…"` + *"You've searched this before. Make a major change to your search, or try something else."* Results don't change turn-to-turn, so a repeat is pure wasted inference — the previous result was already the right one.
- **Reset:** the per-turn memory clears on a new user turn.

### 3a. Fetch exact-repeat — *built* (tool layer, `web_fetch::gate_fetch`)

- **Signal:** an **external** fetch of the *identical* `(url, find, cursor)` already made this turn — a pure no-op re-request.
- **Action — HTTP 400** before the network: `HTTP 400 Bad Request · web_fetch <url>` + *"You already fetched this exact request … Use what you have, or fetch something different."* Navigating the same doc with a **different** `find`/`cursor` is not a repeat, so it proceeds (and `DOC_CACHE` serves it).
- **Internal hosts are never blocked** (`localhost` / `127.*` / `::1` / `10.*` / `192.168.*` / `172.16–31.*` / `*.local`) — the model may be polling its own dev server.

### 3b. Failing-fetch (URL-roulette) — *built* (tool layer, `web_fetch::append_guess_hint`)

- **Signal:** N consecutive **external** `web_fetch` with **no 2xx** — guessing at URLs that don't exist.
- **Nudge:** appended to the result — *"N fetches in a row failed; if you're guessing URLs, stop — find the right one via search, or take a different step."* Soft (a 404 body may be real content).
- **Localhost is exempt entirely** — a dev server that's momentarily down (refused/5xx) is the model waiting for its *own* server, not guessing, so it's never nagged.

### Relation to tunnel-vision

Complementary. Tunnel-vision catches revisiting a **fixed** target set (incl. write loops); read-without-write catches many reads with **zero** writes even when every target differs. The search/fetch guards above are the *focused* first line — they 400 the specific repeat before the generic detectors ever fire.
