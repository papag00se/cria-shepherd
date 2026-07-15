# Tool-handling Anomaly Sweep — 2026-07-15

> **RESOLVED 2026-07-15.** All tiers fixed (no deferrals) across commits for Responses
> translation, focus-trim, menu/cheat-sheet coherence, the guard write-class predicates, and
> the writeproxy overhaul (stateless sentinels, edit_file + web-tool synthesis, atomic write).
> Decisions taken: `apply_patch` dropped from the model menu (kept as the edit_file lowering
> target); `web_search` routes to the harness's search tool if present, else a Brave curl.
> Live-verified: the running session advertises `edit_file` + `web_fetch`, `apply_patch` gone;
> write + edit lowering executed byte-exact in a real shell. 645 tests green.


Wide-net, single-pass, parallel scan for **tool mishaps**: anomalies in how cria
curates the tool menu, synthesizes lean tools, translates/lowers tool calls, and
guards them. Sister to the Audit Lens; this catalogues *things that shouldn't exist*,
it does not verify each as a live bug. Spot-check before acting.

## Seed anomalies

1. cria synthesizes `write_file`/`read_file`/`list_dir` but **not `edit_file`** — a
   one-character fix forces a whole-file rewrite the 9B botches (it reproduced the same
   syntax error across writes).
2. cria doesn't synthesize `web_search`/`web_fetch` — when the harness omits them the
   model hand-rolls `curl` via `exec_command` (observed re-fetching the same
   `openapi.json` five times).

Both are the same shape: **the port dropped half the synthetic tool set.** The sweep
asked whether that pattern runs deeper.

## Dimensions swept (5 parallel agents)

1. Synthetic-tool round-trip (advertise → lower → re-present) — `writeproxy.py`
2. Menu ↔ cheat-sheet ↔ schema coherence — `toolmenu.py`, `prompts/`, `contextfloor.py`
3. Responses↔chat tool translation — `responses.py`
4. Tool-call guards & lifecycle — `loop.py`, `massage.py`, `focustrim.py`, `server.py`
5. codex-local port fidelity — cross-ref against `codex-rs/core/src/local_routing.rs`

---

## Tier 1 — bug-class now, small & self-contained (fix-on-sight)

- [ ] **Chunked write can report full success on a partial write.** A `write_file` >64 KB
  is split into N shell calls; if a later chunk fails its result is hidden (`drop`) while
  chunk 0's empty result is reframed as a `write_confirm` — the model is told the whole
  file wrote when only a prefix landed. `writeproxy.py:226,230`. Fix: fail-closed across
  chunks; no success reframe on a partial.
- [ ] **`tool_choice` object-form is passed through un-translated.** Responses' flat
  `{"type":"function","name":"foo"}` is copied verbatim into the chat body, which needs the
  nested `{"type":"function","function":{"name":"foo"}}` — a forced/named tool choice
  silently breaks. `responses.py:81-82`. Fix: nest `name` under `function` (mirror
  `_to_chat_tools`).
- [ ] **Cheat-sheet points at `web_fetch` even when it isn't callable.** The `web_search`
  fragment says "open one in full with web_fetch" whenever search is present, regardless of
  whether `web_fetch` is in the menu — dormant guidance for an uncallable tool.
  `toolmenu.py:124`, `prompts/cheatsheet.txt`. Fix: gate the cross-reference on
  `"web_fetch" in names`.
- [ ] **Gate probe not exempt from focus-trim's *duplicate-collapse*.** We exempted cria's
  ground-truth gate probe from the failure-squash but not from Rule-A dup-collapse, which
  keys on `(name,args)`; two identical gate scripts would collapse. Benign today (fresh
  uuids) but same class as the squash bug. `focustrim.py:124-156`. Fix: skip
  `_GATE_MARKER` calls in `_collapse_duplicates` too.
- [ ] **`read_file` with `start_line` but no `end_line` silently reads the whole file.**
  Only both-bounds-present is special-cased; start-only falls through to `cat`.
  `writeproxy.py:169-172`. Fix: add the open-ended `sed -n 'N,$p'` range.
- [ ] **Function tool with no `parameters` emits a chat tool lacking `parameters`.** Some
  strict llama.cpp templates require the key. `responses.py:136`. Fix: default to
  `{"type":"object","properties":{}}`.
- [ ] **Stale docstring:** `writeproxy.py:17-18` says chunking is "a refinement (flagged in
  DEFERRALS)" but it's implemented. Fix: update the comment.

## Tier 2 — structural, scoped (the coherence work; highest user impact)

Ordered by impact.

- [ ] **Synthesize `edit_file` and wire the existing dead lowering.** `_synthetic_tools`
  advertises only write/read/list; `massage.lower_edit_file` (edit_file→apply_patch) already
  exists but is starved because the model is never offered the tool. `writeproxy.py:45-62,
  111-119`; `massage.py:116-136`. **Highest-impact seed** — the whole-file-rewrite trap.
- [ ] **Re-present write_file statelessly (and extend to read/list).** Re-presentation is
  keyed on an in-memory `TranslationStore` (`writeproxy.py:65-81`); on any restart — which
  the user does constantly — the store is empty and a resumed session's history reverts to
  raw base64 `shell` blobs where the model called `write_file` (the "shell mangled my file"
  loop the mechanism exists to prevent). codex-local instead embeds a stateless
  `# shephard-write:<b64>` sentinel and parses it back. Also: `read_file`/`list_dir` are
  lowered outbound but **never** re-presented inbound at all (`writeproxy.py:150-155`), so
  the model always sees raw `shell`/`cat`/`ls` for its reads. Fix: carry a stateless
  sentinel in the lowered command; re-present all three by parsing it.
- [ ] **Synthesize `web_search`/`web_fetch` and lower them.** Seed 2. web_fetch → `curl`
  (with the `find`/`cursor` slicing cria already documents); web_search → the harness's
  search tool or a Brave `curl` using the existing key. `writeproxy.py:45-62`.
- [ ] **Stop exposing `apply_patch` to the model.** codex-local deliberately omits
  `apply_patch` from the local menu (a 9B can't produce matching diff context) and keeps it
  only as the *translation target*; cria re-adds it to the focused menu and the cheat-sheet,
  reintroducing the failure mode. `toolmenu.py:30,41`, `prompts/cheatsheet.txt:13`.
  *Needs a decision — see Open questions.*
- [ ] **Port the `local_web_search`→`web_search` rename (`native_tool_name`).** When the
  harness ships Brave's `local_web_search`, cria keeps that raw name in the menu while the
  cheat-sheet describes `web_search` — a menu/hint mismatch. codex-local renames on
  presentation and maps back on dispatch. `toolmenu.py:32-33,43`. Latent (no web tool in
  observed sessions) but wrong.
- [ ] **Add cheat-sheet fragments for the four undocumented kept tools.** `view_image`,
  `update_plan`, `request_permissions`, `write_stdin` are in the focus set but get no usage
  line (no arg shapes for a weak model). codex-local's `build_tool_hint` describes all of
  them. `toolmenu.py:93-135`, `prompts/cheatsheet.txt`.
- [ ] **Teach the wheel-spin tracker about shell-native writes.** `guard_track_write_streak`
  counts a rewrite only via `_write_path` (named write tools); a model rewriting one file
  through the raw `shell` (`tee`/heredoc/`> file`) with varying content escapes both the
  streak guard and the repetition guard (each varying shell write reads as progress). The
  repetition path already recognizes shell writes (`_is_progress`/`_command_text`) — reuse
  it. `loop.py:1425,1307-1311`.

## Tier 3 — larger, defer until the area is touched

- [ ] **Unify the two write-class predicates.** Repetition uses a loose substring regex
  `write|edit|patch|create|replace` (`loop.py:88`); the streak/truncation guards use an exact
  `_WRITE_TOOLS` set (`loop.py:117-118`). A route can match one and not the other. Derive both
  from one shared predicate.
- [ ] **Derive cheat-sheet arg shapes from the live schema.** `list_dir` is advertised as
  `{"path":…}` but a harness-native `list_dir` uses `{"dir_path":…}` (absolute); the
  hardcoded shapes drift from the real `parameters`. Generalize so the hint reads arg names
  off each tool's schema. `prompts/cheatsheet.txt:11`, `toolmenu.py`.
- [ ] **Chunking redesign.** `_CHUNK_BYTES` is applied on `str` indices, not bytes
  (`writeproxy.py:37,240`); chunks are non-atomic appends. Make it byte-correct and atomic,
  or single-command like codex-local.
- [ ] **plan-off probe-reissue parity.** The loop re-issues a guard probe whose result a
  compaction erased (`loop.py:598-606`); the plan-off path just downgrades to a canned steer.
  Mirror the reissue. (Parity gap, low frequency.)
- [ ] Carry `strict` and unknown function-level fields through `_to_chat_tools`
  (`responses.py:133`); default a missing `function_call_output` `call_id` / orphan-drop
  instead of leaving `None` (`responses.py:67`); thread `banner` into `to_responses_json` for
  buffered/streaming parity (`responses.py:314`).

## Open questions (need a decision before acting)

- **`apply_patch`:** remove it from the model-facing menu (match codex-local) or keep it?
  It's load-bearing as the *lowering target* for `edit_file` either way.
- **`web_search` backend:** synthesize against the harness's own search tool when present,
  or always go straight to a Brave `curl`? Affects whether the rename matters.

## Posture check — what's right

The tool system is fundamentally sound; the anomalies are **port-omissions and drift, not
a broken core.** Verified-clean during the sweep:

- Tool-call **id pairing** is correct (unique uuids round-trip through the Responses
  adapter; `_read_tool_result` matches on them; no index-accumulation collisions).
- **Empty-assistant handling** correctly preserves tool-only assistants (a `content:null`
  tool-call turn is never mis-dropped; parallel calls merge cleanly).
- **contextfloor tool-schema bounding is non-lossy** — it only truncates `description`
  strings (valid JSON), never drops `name`/`parameters`/`required`/`enum`.
- **Leaked-tool-call recovery** is sound and idempotent; the **guard round-trip**
  (intervention → probe → steer) and guard ordering are consistent across both drivers.
- The **shared-mechanism design holds**: guards, prompts, context-shaping, and upstream are
  one implementation feeding both the loop and plan-off paths.

This is a working system that accumulated port-debt in one area (the synthetic tool set and
its round-trip), not a dumpster.

## Provenance

Five parallel dimension agents (round-trip, coherence, Responses translation, guards,
port-fidelity); transcripts in this session's task journal. Findings deduped and tiered by
effort-vs-impact.
