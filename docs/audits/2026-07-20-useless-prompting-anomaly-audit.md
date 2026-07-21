# Anomaly Sweep — useless model-facing prompting (2026-07-20)

**Seed anomaly.** `author_steer` serialized the raw harness `body["messages"]` into the reasoner
prompt, carrying Codex's ~7.8K-token agent system prompt verbatim — 25% of a real 29K-token steer
prompt — even though the coder path (`_frame_for_item`) already strips exactly that. Fixed in commit
`7c656dd` (`_drop_harness_frame`). The seed hinted at a broader class: **tokens cria injects into
model-facing prompts that carry no signal the model acts on** — worse for a small model, where every
wasted or contradictory instruction token has outsized cost.

**Mission.** Catalogue where cria's model-facing prompts (coder request, reasoned steers/critics,
classifier, compactor, tool menu, injected envelopes, static templates) carry waste: harness
passthrough, intra-prompt duplication, template bloat, unbounded evidence, injected decoration.

**Dimensions swept (5 parallel agents).** (1) harness passthrough, (2) intra-prompt duplication,
(3) static template bloat, (4) unbounded evidence inclusion, (5) cria's own injected decoration.

---

## Cross-cutting root (the sweep's through-line)

cria has a deliberate, correct stance — **never truncate content the model asked to READ** (an
undetectable lie), so include generously and let the **context floor** (`contextfloor.py`) trim to the
window. That stance is right for the *coder's own reads*. But it has been **over-applied to prompts cria
COMPOSES for a judge/steer** — where the floor bounds the total but never **de-dupes** or **stubs**, so
redundant + growing content re-crowds every reasoner call. Two concrete failure modes fall out of it:
a byte-equality dedup that silently fails, and the whole session re-serialized on every steer fire.
Composing a judge prompt is *not* the coder's read — bounding it there breaks no rule.

---

## Tier 1 — bug-class or cheap high-value, fix on sight

- [~] **`clean_gate_results` dedup silently defeated by volatile ids — MEASURED RARE, DROPPED 2026-07-20.**
  Dim 2 flagged this HIGH (byte-equality dedup at `probegate.py:244-255` defeated by a jittering
  `MagicMock` id / hex `_patch` address / pytest duration, so a recurring-unchanged failure never
  byte-matches → the block rides un-deduped and the coder re-reads it). **Verified against all 9 real
  session captures (521 bodies, 259 gate-finding blocks):** byte-identical dedup already works (56
  repeat-notes, **0** byte-equal survivors); genuinely-DIFFERENT co-occurring pairs = **70** (the normal
  case, must not merge); volatile-only misses = **6 pairs, all one session (the stuck ternary run), all
  the same single pair replayed across 6 turns** — i.e. **one distinct event in 9 sessions; 8/9 sessions
  had zero.** The normalization would have been correct there (purely `id=`/`0x…`/`N.NNs` diffs) but
  fires ~once per 9 sessions while adding false-merge surface to the 70× more common genuinely-different
  case. Even the safe structured-exact-key variant catches **0** extra cases (no byte-equal survivors).
  **Decision: don't build it** — rarity doesn't justify the machinery or the false-merge risk. If the
  stuck-session bloat ever needs addressing, the lever is the Tier-3 "feed the rollup, not the raw
  growing body" item, not per-token normalization.
- [x] **`coder_system.txt` "# Finishing" contradicts the `task_complete` tool** *(dim 3, HIGH)*.
  **FIXED 2026-07-20.** It said *"a response with no tool call … is the ONLY way to end,"* yet
  `task_complete` is advertised on every coder turn (`_add_completion_tool`, `loop.py:721`). Reworded
  "# Finishing" to name the two equivalent exits (no tool call OR `task_complete`) and reinforce "don't
  end while unverified." 1002 tests.
- [x] **Env-context / AGENTS-`<INSTRUCTIONS>` user block still leaks into the steer reasoner**
  *(dim 1, MED — the seed's residual)*. **FIXED 2026-07-20.** `_drop_harness_frame` dropped `system`/
  `developer` roles but kept Codex's `<environment_context>` + `# AGENTS.md <INSTRUCTIONS>…` **user**
  block verbatim (~290 tok/steer). Now maps the coder path's `reframe_preamble` over each kept turn, so
  the reasoner sees cria's clean cwd/shell/date voice instead of raw XML. 1002 tests.
- [ ] **Dead render kwarg** *(dim 3, LOW)*. `redirect_canned` is rendered with `repeat_n=…`
  (`loop.py:2077`, `:2332`) but the template has no `{{REPEAT_N}}` slot (silently dropped). Drop the
  kwarg at both sites. *(deferred — trivial, no behavior change)*
- [ ] **Confirm the seed fix is live.** A capture (`0051-reasoner.prompt.txt`) still showed the ~30K
  harness preamble (dim 4, LOW #5) — but that capture predates the `7c656dd` deploy (cria not yet
  restarted). Verify post-restart that the steer session is actually frame-stripped; no code change
  expected.

## Tier 2 — structural cleanup, scoped

- [ ] **Tool/editing guidance is triplicated into every coder turn** *(dim 3 HIGH + dim 5 MED, ~1.5 KB/
  turn)*. The prefer-a-tool-over-shell rule appears ~5× (`coder_system.txt` "# Tools" + `cheatsheet.txt`
  header/footer/shell-entry) and the edit_file-VERBATIM/write-whole-file policy appears in
  `coder_system.txt`, `cheatsheet.txt`, AND `tool_descs.txt`. **Fix:** delete `coder_system` "# Tools"
  (covered by the cheatsheet header), cut "# Editing files" to the one non-mechanical rule (don't
  rewrite a whole file for a one-line change), drop the cheatsheet footer + its duplicated edit policy —
  let the schemas own mechanics. Re-test the coder path after.
- [ ] **Already-seen web_search / web_fetch blobs ride into every downstream reasoner call**
  *(dim 4, HIGH #2)*. `writeproxy.py:410-419` keeps every Brave result (no display slice); a `19 results`
  block (~1.6K tok) + a `swagger.json` fetch (~2.5K tok) re-serialize into ALL ~15 reasoner prompts
  (~60K tok/session repeated). **Fix (compose-side only, never touches coder reads):** in the
  critic/steer serialization, replace an already-seen web result/fetch tool output with a one-line stub
  (`web_fetch(swagger.json) → 10KB JSON, keys: …`); the coder's live turn keeps the full body.
- [ ] **A churned file's contents appear 2–3× in one reasoner prompt** *(dim 2, MED #3)*. Stale
  `write_file` content arg in the transcript + inside the traceback + the authoritative
  `_fresh_disk_facts` on-disk render. **Fix:** in the reasoner serialize, elide `write_file` CONTENT
  args for files `_fresh_disk_facts` already renders (keep "wrote X", drop stale bytes — disk is
  authoritative, zero signal lost).
- [ ] **Step framing duplicated verbatim in system AND user turn** *(dim 2, MED #4, planned path only)*.
  `_item_prompt` output goes in both the system message (`loop.py:1733`) and the replacing user turn
  (`:1739`). **Fix:** keep the floor-protected system copy; make the user turn a short pointer.
- [ ] **Template micro-dupes** *(dim 3, MED)*. `selfcompact_summary.txt` states the
  "identifiers may still be renamed" caution 3× (intro + bullet 1 + rule 3) — state once. The 6-rule
  DO-NOT-GUESS block is duplicated in `coder_system.txt` and `plan.txt`, and the planner's copy carries
  a VALIDATE/"linting" rule nonsensical for a role that "DO NOT CODE" — trim the planner's copy.

## Tier 3 — bigger / needs a design call

- [ ] **The ENTIRE session is re-serialized into every steer/critic fire** *(dim 4, HIGH #1 — biggest
  token leverage, but brushes a design decision)*. `author_steer` re-pays the whole transcript verbatim
  on every repetition/wheel-spin/thrash/flail trigger; it grows unboundedly (23 session lines at call
  0013 → 85 at 0051). The `author_steer` docstring **deliberately** hands "the real session rather than
  a curated slice" because a past curation made a steer hallucinate a path. **Direction:** feed the
  steer author the already-computed `⟦ctx:rollup⟧` self-compacted view (built for the coder, designed
  to be near-lossless) instead of the raw full body — but this needs the same care as the harness-frame
  drop: prove it removes only redundancy, not facts the reasoner needs. Tiered here for that reason.
- [ ] **Critic evidence includes all coder tool outputs / whole files in full** *(dim 4, MED #3/#4)*.
  `_coder_evidence`/`_work_log` (`loop.py:1453-1471, 2629-2643`) concatenate every tool result verbatim
  for `_verify`/satisfaction; `_fresh_disk_facts` includes whole files (cap 200K tok,
  `groundtruth.py:44`). **Direction:** bound only *re-included READ payloads* (a region/diff around the
  churn carries the stuck-signal); keep genuine command/test output full. Brushes never-truncate — keep
  the cap as the safety valve; treat as judgment, not fix-on-sight.

## Posture — what's RIGHT (don't re-flag)

- **No `⟦cria⟧` leak; the strip contract is sound.** Steers reach the model as `⟦ctx:steer⟧`,
  edit-recovery as `⟦ctx:edit⟧`; human `⟦cria⟧`/MARKER lines ride only in completion content and are
  removed inbound (`indicators.py:62-93`). (dim 5)
- **Most critics build clean fresh bodies** — verified no harness frame reaches the classifier
  (`classify.py:57`), `judge_satisfaction`/`_done_critic_reason`/`_satisfaction_verdict`, `summarize`,
  both compactor serialize paths (already `_frame_for_item`-reframed), or `_reasoned_reanchor` (root
  task only). The seed leak was **localized** to the steer path. (dim 1)
- **`reframe_preamble`, `write_confirm`, the exec-envelope strip, and `editrecovery.compose` are tight**
  — minimal facts, no prose; the model of what the cheatsheet should aspire to. (dim 5)
- **Many templates are lean and single-purpose** — `classify`, `nudge`, `leg0_nudge*`,
  `gate_fail_steer`, the guards, `verify`, the digest maps, both `preamble_*`. `satisfaction.txt`'s
  repeated "emit NO tool call" is justified defense against a documented gemma failure, not bloat;
  `steer_diagnose.txt` is long but every clause is load-bearing anti-hallucination grounding. (dim 3)
- **The over-inclusion is downstream REUSE, not the coder's reads** — `represent_inbound` and the
  coder's live tool turns keep full bodies correctly; the waste is re-serializing them into judge
  prompts. The never-truncate-reads rule is intact. (dim 4)

Net: this is a healthy prompt architecture with waste concentrated in **two localized places** — the
`coder_system`+cheatsheet concatenation (static dupes) and the steer/critic serialization path (the
gate-dedup bug + growing/repeated evidence). Not systemic rot.

---

*Source transcripts (this session's JSONL): agent task IDs a03567a64b01a931c (harness passthrough),
a74acf3acc25a8f80 (duplication), ac4f258c2c659cc1a (template bloat), a5be21042921956db (unbounded
evidence), a267fe6a0ccdc9f5a (injected decoration). Seed fix: commit 7c656dd.*
