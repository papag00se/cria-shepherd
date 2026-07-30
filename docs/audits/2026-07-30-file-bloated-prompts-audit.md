# Anomaly sweep — file-bloated composed prompts (2026-07-30)

**Seed anomaly.** The steer author's prompt inlined the full bytes of every file the coder touched:
a 57K minified spec the coder `curl`'d to `./api.json` flowed in **twice** (two path spellings) —
115K of a 210,601-char prompt. A composed prompt is two messages, the context floor's last resort
drops whole *turns*, so the oversized composition went to the model as-is (~53K tokens at a 49K
window) and the reasoner died silently four calls in a row (run 0729-gemma4 C1 0062–0065). Fixed by
the list+inspect redesign (`_fresh_disk_facts` lists name/bytes/lines; the author holds the judges'
read-only tools). This sweep hunted every *other* composed prompt with the same disease.

**Dimensions** (4 agents, parallel): inlined file contents · unbounded transcripts/tool results ·
the floor blind spot (what actually bounds each composed call) · redundant paste where the reader
holds tools. Full structured findings: workflow `wf_3f21bf2c-f34` journal (session
`edbb364b-ba10-4a20-b2a6-9f0667c9106d`).

---

## Tier 1 — bug-class now, small fixes

- [ ] **Satisfaction/done-critic evidence is unbounded** — the e4564da `_bound_evidence` fix
  covered only the step critic's `_grounded_evidence`; the sibling `_satisfaction_evidence`
  ([loop.py:2355](../../cria/loop.py) → `satisfaction_user {{EVIDENCE}}`, consumed at 1215/2032/2129)
  never got it. Measured: **73.7KB** of "RECENT VERBATIM ACTIONS" in a 78.7KB prompt
  (0183-satisfaction, run 0729T224807). Same self-growing doom-loop mechanism as the critic incident
  (fails closed → re-nudge → evidence grows). *Fix: route through `_bound_evidence`; the judge holds
  read_file/list_dir to drill past the elision.*
- [ ] **The step critic's CODER'S SUMMARY slot is unbounded** — `sess.pending_coder_text`
  ([loop.py:1763](../../cria/loop.py)) embeds whatever the coder emitted as text, including a whole
  file when a weak model leaks a giant `edit_file` as prose. Measured: **119KB of leaked edit text
  inside a 151KB critic prompt** (0567-critic, run 0728T000013) — 5× the 24K evidence budget,
  defeating the bound in the *same prompt*. *Fix: hard-bound the slot; collapse a leaked-tool-call
  summary to a one-line fact (the editrecovery.summarize pattern).*
- [ ] **Planner gather `exec_command` results bypass the spill** — web_fetch spills at 16K, but
  `curl` through the gather's exec tool returns raw
  ([planner_tools.py:104/134/143](../../cria/planner_tools.py)). Measured: a **944,245-char** curl of
  docs.ada.cx → a 960,600-byte planner prompt (~255K tokens est), sent twice, **no response either
  time** — the model died silently and the gather restarted. This is the 0727-123534 341KB web_fetch
  incident reborn through the feeder that fix didn't cover. *Fix: oversized exec output takes the
  same spill road — scratchpad file + pointer/outline the gather greps with tools it already holds.*
- [ ] **The judges' toolless retry passes are lied to** — the reasoning-off retry withholds
  verifytools, but `satisfaction.txt`/`verify.txt` still open with "You have exactly two READ-ONLY
  inspection tools". Rule-5b breach to the retry judge (same class the operator caught in
  `steer_diagnose.txt`). *Fix: a truthful one-line addendum on the toolless pass.*

## Tier 2 — structural, scoped; decide before building

- **Steer author `{{SESSION}}` slot (~85K in the seed capture)** — three agents re-recommend a
  disclosed recency bound. The operator rejected the blanket 24K session bound on 07-30; the changed
  premise is that the author now holds tools to recover anything elided. **Operator's call** —
  parked, not built.
- **Completion briefing `{{LOG}}` unbounded** ([loop.py:1900](../../cria/loop.py), 68KB measured)
  and **self-compact band admits one giant message whole** (96KB prompt with a 50KB serialized
  heredoc; only ⟦ctx:edit⟧ blobs are headline-collapsed). *Direction: recency-bound the done log;
  per-message digest cap in `selfcompact.serialize`, disclosed.*
- **`est_tokens` density assumption** (~4 chars/token) is how 210K chars read as "fits 49K" —
  dense minified JSON runs ~2.5–3 chars/token. cria already learns real ratios per model
  (`_calibrate`); the floor's arithmetic for *composed* prompts doesn't use them. *Direction:
  density-aware estimate or calibration reuse.*
- **Spill-failure fallback inlines the whole doc** ([planner_tools.py:366](../../cria/planner_tools.py),
  up to 8MB on an OSError) — rare path, deliberately re-opens the hole the spill closed.
  *Direction: bounded head + disclosed failure note instead.*

## Tier 3 — fine as-is, keep an eye

- `verifytools._read_file` whole-file reads: the judge *asked* for those bytes, and the multi-turn
  loop gives the floor real levers (reduce/drop) — a dead call can't happen there.
- `editfail_reports` `{{CUR}}` whole-file inline: load-bearing (rewrite from exact bytes); the
  reasoner-side leak of those blobs is already collapsed.
- Workspace inventory paste beside judge tools: mild redundancy, load-bearing for the coder flavor.
- 14 sites checked clean (bounded or naturally small): classifier user slot, re-anchor summary,
  search-read judge, floor digest, and friends.

## Posture check

The floor is genuinely lossless-first and covers every *multi-turn* shape well; the spill/outline
machinery, the durable fetch ledger, and the per-call capture made every finding above measurable
from disk. The disease is specific: **two-message composed prompts whose slots nothing bounds** —
four instances, all now named, three with same-day fixes.
