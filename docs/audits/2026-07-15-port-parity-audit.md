# cria Port-Parity Audit — cria (Python) vs codex-local (Rust)

**Date:** 2026-07-15. **Method:** anomaly sweep + audit lens, 7 parallel agents, each
diffing a cluster of `codex-rs/routing/src/*.rs` against its cria counterpart for the
"looks ported, capability silently dropped" class. **Seed:** a live Ada-handle session
where the coder fetched `api.handle.me/openapi.json` (a real HTTP 200, 57 KB single-line
JSON), the harness truncated it to an unusable prefix, the model rationalized a "404",
looped, and gave up — because cria's `web_fetch` never got codex-local's structural
JSON/YAML reduction + navigation.

Every HIGH finding here was spot-verified against the cited code by the synthesizer
(not taken on an agent's word). Verification status is marked per row.

---

## The meta-finding (the reason you keep getting surprised)

**There is no single honest source of truth for what's ported.** Three docs disagree:

| Doc | Says | Reality |
|---|---|---|
| `docs/port-fidelity-audit.md` (2026-07-07) | 22 gaps across 3 tiers | **Stale.** Much was ported since (probes, loop detectors, content_reduce core, guards) but the doc was never updated — a reader can't tell done from open. |
| `docs/heuristic-assists.md` | "Quality gate", "Announce-without-act escalation", course-change "(built)" | **Lies.** None of those three exist in cria code. The docs were ported; the code wasn't. |
| `DEFERRALS.md` | tracks *some* gaps with triggers | **Incomplete.** Misses content_reduce navigation, quality, feedback, budget_pressure, curl_ua, YAML, prose-repetition detector, and more — and two of its own entries (INVESTIGATE #94, groundtruth #242) are stale/wrong. |

So a capability could be: dropped in code, claimed-present in one doc, listed-absent in a
second, and unmentioned in the ledger meant to catch it. That is exactly how the
`content_reduce` navigation miss survived — the de-scope lived only in a **code docstring**
(`content_reduce.py:11`: "intentionally NOT ported … stateless by design") and never
reached `DEFERRALS.md`, while `writeproxy` went ahead and advertised `find`/`cursor` to the
model anyway. **This audit supersedes port-fidelity-audit.md and is the new source of truth.**

### Reason-verdict legend
- **SILENT-MISS** — dropped and documented *nowhere* (or only in a code comment that never reached the ledger). Worst class.
- **DOC-LIE** — a doc claims the capability is present/built; the code disagrees.
- **BULLSHIT-EXCUSE** — a rationalization that dropped a working capability ("stateless by design", "harness re-issues to see more").
- **STALE-DEFERRAL** — in DEFERRALS/port-fidelity-audit, but the note is now wrong or was never closed.
- **REAL-DEFERRAL** — tracked with a genuine trigger. Acceptable.
- **LEGIT N/A** — genuinely doesn't apply to cria's architecture (dead-in-source upstream, cloud-only telemetry).

---

## Tier 1 — broken now / trivial, fix on sight

- [x] **`_USER_AGENT` NameError → planner `web_fetch` 100% broken** — `planner_tools.py:219` referenced an undefined `_USER_AGENT`; every gather-loop fetch raised NameError, swallowed by the broad `except`, so the reasoner planned **blind**. *Verdict: SILENT-MISS.* **FIXED** 4f62fbc (use `brave.USER_AGENT`, + invariant test). *Verified: yes (runtime-reproduced).*
- [ ] **`block_nudge_preamble.txt` dropped "You are not done yet."** — the one sentence whose job is to counter a false "done"; `proberun.py` claims these strings are "byte-for-byte with upstream". *Verdict: SILENT-MISS (trivial). Verified: yes.*
- [ ] **Doc-lie corrections** — `heuristic-assists.md` / `indicators.md` present the Quality gate, no-action escalation, and course-change reset as existing. Mark them NOT-BUILT (they become DEFERRALS entries below). *Verdict: DOC-LIE. Verified: yes.*
- [ ] **Retire the stale claims** — `DEFERRALS.md:94` (planner INVESTIGATE "left for later") is stale: the gather-and-plan loop IS built (`planner.py`); `DEFERRALS.md:242` (groundtruth "not yet wired — trigger: the repetition detector port") is stale: the detectors landed 2026-07-12 and groundtruth is *still* unwired; `DEFERRALS.md:306` (synthetic `edit_file` "NOT injected") is stale: it IS injected + lowered to a fail-closed executor (commit 41eedc1). *Verdict: STALE-DEFERRAL. Verified: yes.*
- [ ] **Correct the failover framing in DEFERRALS** — `DEFERRALS.md:34,89` imply the cloud-failover mechanism exists and is merely "unverified against a live provider" / "not wired into the loop". In fact the entire executor (`classify_failure` F1–F9, `decide_action`, retry-same-with-backoff, walk-chain) was **never built** (see Tier 2). The framing understates the gap. *Verdict: STALE-DEFERRAL. Verified: yes (grep — no classify_failure/decide_action anywhere).*

## Tier 2 — real degradations, on-mission, scoped

- [ ] **`web_fetch` structural reduction + navigation dropped** (the seed) — `content_reduce.py` ported the reducer core but dropped `page_from`/`find_in`/`find_json`/`top_level_keys`/`resolve_refs`; `reduce_lossless` is dead code (no caller). `writeproxy._fetch_command` re-implements `find` as `grep -F` (breaks on 1-line JSON, case-sensitive, no quote-strip) and `cursor` as `tail -c` (byte offset, splits UTF-8, **never emits a next-cursor**), and applies **no reduction** (raw HTML soup / raw JSON up to 64 KB). The tool description *promises* the model cursor/find navigation cria cannot deliver. *Verdict: BULLSHIT-EXCUSE ("stateless by design" — contradicted by advertising find/cursor). Verified: yes (deep). Fix: reduce inside the lowered command (harness-side, beats the harness truncation); structural JSON/YAML outline + top-level-keys + structural find + real cursor + status labels.*
- [ ] **YAML structural reduction never built** — `content_reduce.rs:8` explicitly says "the Python port does YAML structurally with pyyaml." It doesn't; no `yaml` import. *Verdict: SILENT-MISS (an assigned TODO). Verified: yes. Fix: folds into the web_fetch reducer, PyYAML with text fallback.*
- [ ] **`quality.rs` response-quality gate unported** — no empty/short/echo/refusal/degenerate-repetition pre-filter on text-only turns. A local model's "I cannot complete this task" / empty / repeated answer passes straight through; on plan-off it's forwarded as "done", elsewhere it burns a full reasoner-critic on garbage. *Verdict: DOC-LIE + SILENT-MISS. Verified: yes.*
- [ ] **`groundtruth.py` orphaned** — a faithful port with **zero callers**; the redirect grounds the reasoner on the probe outcome + recent tool results, never on the files on disk, and skips the `has_signal()` gate (upstream measured 73% of redirects groundless without it). *Verdict: STALE-DEFERRAL. Verified: yes (0 call sites). Fix: wire into `_author_redirect`.*
- [ ] **`tool_choice="required"` enforcement unported** — no `LocalRole.tool_choice`; cria never forces a grammar-constrained tool call on a no-action retry. The sampler-level steering lever for weak models — squarely on-mission. *Verdict: STALE-DEFERRAL (port-fidelity #2). Verified: yes.*
- [ ] **Prose-repetition detector (`loop_detector note_assistant_text`) dropped** — cria's guards iterate only `tool_calls`; a model emitting the same prose diagnosis ~18× with no tool call (the exact Ada-handle shape) trips nothing. The stopword/stem machinery was ported but only for planner search rumination. *Verdict: SILENT-MISS. Verified: yes.*
- [ ] **No-action escalation tier unported** — Rust `continuation_prompt` is two-tier (embed prior-prose excerpt → hard "[NO ACTION — STOP EXPLAINING], single tool call", counted to a bail cap). cria fires one flat static nudge once per step. *Verdict: DOC-LIE (heuristic-assists claims escalation). Verified: yes.*
- [ ] **Reasoner completion critic absent on the plan-off path** — `_drive_direct_coder` verifies "done" with the objective gate only; no reasoner critic → stubbed/mocked behavior and **tests-that-didn't-run** pass as green. Violates the repo's "fixes in BOTH paths" rule. *Verdict: STALE-DEFERRAL (documented at loop.py:1626 but conflicts with policy). Verified: yes.*
- [ ] **`curl_ua.rs` browser-UA injection unported** — coder curls / lowered fetch send `curl/8.x`; Cloudflare/CDN docs return 403 where the browser-UA would 200. *Verdict: SILENT-MISS. Verified: yes.*
- [ ] **Fetch/search repeat-gates absent on the coder path** — `gate_fetch` (exact-repeat HTTP 400 block), guess-streak nudge, `is_internal_url` carve-out; and `gate_search` is planner-only. A coder can loop identical fetches burning ~60s each. *Verdict: SILENT-MISS. Verified: partial (grep). Fix: folds into the web_fetch port.*
- [ ] **`tool_format` builtin-variant survival dropped** — `_to_chat_tools` drops every type-only tool (`{"type":"web_search"|"local_shell"|"image_generation"|"tool_search"}`); the harness's native builtins vanish. Latent HIGH if the shell ever arrives type-only. *Verdict: SILENT-MISS (tested, but unreconciled with source). Verified: partial.*
- [ ] **`tool_recovery` Strategies 1 & 2 unported** — only the `<…>`-leak dialect (Strategy 0) is recovered; a whole-message JSON blob or an Anthropic `tool_use` block (devstral/qwen3-coder) is forwarded as prose → lost tool call → no-action stall. Cross-model resilience = the mission. *Verdict: SILENT-MISS. Verified: partial.*
- [ ] **`edit_target` missing headers + `text_editor`** — path parser recognizes only `Add|Update`, not `*** Move to:` / `*** Delete File:`, and has no `text_editor` entry; guards go blind to renames/deletes/text_editor edits. Two independent path parsers (`loop._path_of_args`, `focustrim._fingerprint`) reintroduce the exact drift `edit_target.rs` unified away. *Verdict: SILENT-MISS. Verified: partial.*
- [ ] **Runtime failover: retry-same-once-on-timeout absent** — `routing.py` does resolve-time chain walking only; a transient local timeout/5xx = a dead turn, no retry (relevant given the shared-GPU flakiness). *Verdict: STALE-DEFERRAL (port-fidelity #14). Verified: partial.*
- [ ] **Reasoner redirect: plan-off canned-only + no `MAX_REDIRECTS_PER_TASK=6` cap** — plan-off gets generic canned steers a 9B ignores; a persistent loop can drive unbounded reasoner redirect calls. *Verdict: mixed (canned documented; cap SILENT-MISS). Verified: partial.*
- [ ] **Runtime failover executor entirely absent** — `routing.py` is resolve-time role preference only; the whole `failover.rs` engine (`classify_failure` F1–F9, `decide_action`, retry-same-with-backoff, rate-limit `retry-after`, retry-once-on-timeout, auth hard-fail, `walk_chain` on a *runtime* failure, `ContextOverflow`→bigger-model) is unbuilt. A configured chain gives **zero** runtime resilience: a 429/503/timeout hard-errors the stream. DEFERRALS frames this as "unverified"/"not wired into the loop" — it was never built at all. *Verdict: STALE-DEFERRAL (partially hidden). Verified: yes (grep — no classify_failure/decide_action). Narrowed by the single-loaded-model posture (local chain has one target), so the load-bearing slice is retry-same-once-on-timeout.*
- [ ] **Context floor deletes old history instead of synthesizing it** — Rust `trim/mod.rs` *replaces* old turns with synthesized state (pinned files, world state, files-modified-this-turn via `state_extract.rs`); cria's `_drop_oldest`/`_drop_protected_overflow` **delete** with no replacement. A long overflowing session loses which-files-were-edited and prior decisions/outputs outright — the model loses the thread. *Verdict: SILENT-MISS. Verified: yes (contextfloor has only `_drop_*`, no synthesis).*
- [ ] **`claude_cli` empty output = success, not failover** — on `claude` exit-0-with-blank/non-JSON, `_parse_claude_json` returns `content=""` as a *successful* completion; Rust returns `Err` → the caller fails over to the next chain model. cria hands the harness a valid **empty assistant turn** (also an empty-assistant-400 hazard) and can't escalate. *Verdict: SILENT-MISS. Verified: yes.*
- [ ] **`massage.py` "ported in full" is an over-claim** — dialects/strategies missing vs `tool_aliases.rs`: **LFM2/fabliq native `<|tool_call_start|>` sentinels not stripped** (a supported model family → raw markers leak into content); **collapsed/crammed-patch recovery** (`expand_collapsed_patch`) absent; **unified-diff git-noise normalization** incomplete (`diff --git`/`index`/`rename` lines survive → `_fix_hunk_lines` mis-prefixes them → a `git diff`-pasted patch corrupts); `R`/`Rscript` aliases missing. *Verdict: SILENT-MISS (LFM2/crammed/R) + one code-comment-disclosed (git-noise). Verified: LFM2 yes, rest agent-reported.*
- [ ] **Planner gather safety gate is MORE permissive than the source + contradicts its own docstring** — `is_gather_safe_command` permits `/tmp` writes/downloads/mutations (`curl -o`, `rm`, `mv`, `tee`…); Rust `is_read_only_command` refuses *any* `>` redirect. The docstring says "Read-only BY CONSTRUCTION". Also `_web_fetch` drops the http/https scheme guard → `urllib` will serve `file:///etc/passwd`. *Verdict: SILENT-MISS (policy divergence, undisclosed). Verified: partial.*

## Tier 3 — bigger, defer with a real trigger

- [ ] **`reasoned_guidance` course-change reset + context-rebuild excise unported** — no `looks_like_restart`/`loop_grace`/`COURSE_CHANGE_GRACE_TURNS`; a model that finally pivots gets re-buried by guards re-deriving from the same loopy window; no clean-slate context surgery on a persistent flail. *Verdict: DOC-LIE (heuristic-assists says "(built)"). Verified: partial. Trigger: after the Tier-2 guard work lands.*
- [ ] **`feedback.rs` routing-learning store unported** — no per-project routing-success profile fed to the classifier. Plausibly a fair de-scope for a harness-agnostic tool, but never written down. *Verdict: SILENT-MISS. Trigger: if routing-quality plateau is observed.*
- [ ] **`codebase_context.rs` classifier project-profile unported** — classifier can't bias on project language/complexity. *Verdict: SILENT-MISS. Trigger: classifier precision matters for the fleet.*

## LOW / informational (recorded, not scheduled)

- `probeparse._error_class_only` finding-filter — deliberate divergence: cria's completion gate is MORE permissive than Rust (drops eslint-warning rows + unused-import/var advisories that Rust gates on). This is the **operator-directed** behavior (2026-07-15: "unused imports are not an error state"), heavily documented in code/memory — but it is NOT noted in DEFERRALS' probe residual-gaps as a loosening of the gate's blocking semantics. *Not a bug; record the divergence.*
- **No system-prompt compression lever** — Rust can bound an oversized system prompt (`trim/mod.rs` head+tail elision, `context_strip` truncate/canned-minimal); cria marks every `system`/`developer` message un-droppable with no compressor → a pathologically large incoming system prompt forces `over_budget` with no lever (loud, not silent). *SILENT-MISS, LOW.*
- **No base64-blob content stripper; no poll-loop collapse** — Rust `context_strip` replaces long base64 lines with `[binary data removed]` and collapses repeated poll messages to `[polled N times]`; cria's `content_reduce`/`focustrim` do neither for those exact shapes. *SILENT-MISS, LOW.*
- **`claude_cli` non-UTF-8 stdout** → uncaught `UnicodeDecodeError` (`text=True` strict decode; Rust uses `from_utf8_lossy`). *LOW robustness.*
- **`probeparse.parse_pycompile` chained-comparison bug** (cria-added code, live on the gate path): `"error" in t.split(":")[0:1] == ["error"]` parses as a chained comparison, making the second disjunct effectively dead → lowercase `error:` compile diagnostics don't attach a message. *Latent bug in cria-only congruence code (not a port gap), LOW.*
- `select_completion_probes` top-FormatCheck edge — unreachable. `GuardStore` clear-all eviction (vs pop-front) → brief synchronized blind spot at the 256 bound. `engine.route_task` context-eligibility filter dropped (huge irreducible request has no escalation route). Classifier dropped inputs (`tools_potential`, recent-counts) — deliberate. Classification failover lane absent. `budget_pressure.rs` unported (cloud-only). *Verdict: LOW / LEGIT N/A.*

## Verified LEGIT N/A (dead in source or telemetry — do NOT port)

`context_strip.rs` (0 callers upstream, superseded by `trim/`), `session_memory.rs` (dead upstream), `prompt_adapt.rs` (dead upstream), `prompt_local.rs` (0-byte asset — cria's `coder_system.txt` exceeds it), `metrics.rs`/`cost_analytics.rs`/`usage.rs` accounting (cloud-cost telemetry; the load-bearing tok/s readout IS ported), `ollama.rs` NDJSON flavor (llama.cpp standardization).

---

## Probe/gate cluster — genuinely well-ported (posture check)

The probe subsystem is the counter-example that proves not everything drifted. Verified at
depth: all ~80 `probeclassify` seeds, every `probediscovery` builder table (confidence /
cost / argv), `probeparse`'s parsers, `linterprobe`, and `groundtruth`'s render logic are
faithful — no parser family, seed, threshold, or ranking weight silently dropped. The
rumination detector is faithful (22 markers, both trigger arms) and wired into BOTH paths.
The Massages/output-repair pipeline, JSON extraction, Responses adapter, and base64
write round-trip are at parity. This is a real port with real strengths; the failures
cluster in **Steering + fetch presentation + the tracking discipline**, not everywhere.

---

## Root-cause discipline (so this stops recurring)

1. **A de-scope that isn't in `DEFERRALS.md` doesn't exist as a decision — it's a silent drop.** A docstring saying "intentionally not ported" is not tracking; it must have a DEFERRALS entry with a trigger, or it will bite live.
2. **If a doc describes a capability, the capability must exist or the doc must say "(not built)".** heuristic-assists.md described three phantom features.
3. **Don't advertise to the model what you didn't build.** `writeproxy` advertised find/cursor navigation the reducer can't back.
4. **Audit docs get a status line or get retired.** port-fidelity-audit.md rotted for 8 days into a misleading snapshot.

## Source transcripts
12 parallel agents (session JSONL `aa317091-…`). Coverage sweep (6): fetch/web/content,
tools/recovery, probe/gate, guards/loop, routing/classify/models, prompting/memory. The
claims-vs-reality agent itself returned empty but had spawned 5 deep claim-verification
children that reported directly (guards/detectors, context-floor+failover, claude_cli+
planner_tools, writeproxy/massage, probe subsystem) — folded in above. Every HIGH and the
highest-impact new claims were spot-verified against the cited code by the synthesizer;
MED/LOW rows marked "agent-reported" where not independently re-verified.
