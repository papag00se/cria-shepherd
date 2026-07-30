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

- [x] **Satisfaction/done-critic evidence is unbounded** — the e4564da `_bound_evidence` fix
  covered only the step critic's `_grounded_evidence`; the sibling `_satisfaction_evidence`
  ([loop.py:2355](../../cria/loop.py) → `satisfaction_user {{EVIDENCE}}`, consumed at 1215/2032/2129)
  never got it. Measured: **73.7KB** of "RECENT VERBATIM ACTIONS" in a 78.7KB prompt
  (0183-satisfaction, run 0729T224807). Same self-growing doom-loop mechanism as the critic incident
  (fails closed → re-nudge → evidence grows). *Fix: route through `_bound_evidence`; the judge holds
  read_file/list_dir to drill past the elision.*
- [x] **The step critic's CODER'S SUMMARY slot is unbounded** — `sess.pending_coder_text`
  ([loop.py:1763](../../cria/loop.py)) embeds whatever the coder emitted as text, including a whole
  file when a weak model leaks a giant `edit_file` as prose. Measured: **119KB of leaked edit text
  inside a 151KB critic prompt** (0567-critic, run 0728T000013) — 5× the 24K evidence budget,
  defeating the bound in the *same prompt*. *Fix: hard-bound the slot; collapse a leaked-tool-call
  summary to a one-line fact (the editrecovery.summarize pattern).*
- [x] **Planner gather `exec_command` results bypass the spill** — web_fetch spills at 16K, but
  `curl` through the gather's exec tool returns raw
  ([planner_tools.py:104/134/143](../../cria/planner_tools.py)). Measured: a **944,245-char** curl of
  docs.ada.cx → a 960,600-byte planner prompt (~255K tokens est), sent twice, **no response either
  time** — the model died silently and the gather restarted. This is the 0727-123534 341KB web_fetch
  incident reborn through the feeder that fix didn't cover. *Fix: oversized exec output takes the
  same spill road — scratchpad file + pointer/outline the gather greps with tools it already holds.*
- [x] **The judges' toolless retry passes are lied to** — the reasoning-off retry withholds
  verifytools, but `satisfaction.txt`/`verify.txt` still open with "You have exactly two READ-ONLY
  inspection tools". Rule-5b breach to the retry judge (same class the operator caught in
  `steer_diagnose.txt`). *Fix: a truthful one-line addendum on the toolless pass.*

## Addendum (same day) — operator rulings

- **Binary blobs are banned from every model-facing prompt** (operator: "blobs have no place in
  here at all"). Shipped: a strict shared detector (`content_reduce.looks_binary` — replacement/
  control chars only, so CJK/base64/hexdumps stay text) + a stated-fact stand-in
  (`[binary content: N bytes, PNG image — not shown…]`) wired at four seams: coder-history tool
  results (envelope preserved), judge `read_file`, planner `read_file`, planner exec output —
  which also fixes a latent crash (binary stdout under `text=True` raised before any guard ran).
  `webfetch` already had this contract; now everything does.

## Tier 2 — DEAD by operator ruling (2026-07-30): "we are not trimming or truncating anything"

- ~~Steer author `{{SESSION}}` slot bound~~ — **dead.** No trim. The sanctioned mechanisms remain
  restructuring (list + tools, spill + pointer), never cutting.
- ~~Completion briefing `{{LOG}}` bound~~ and ~~self-compact per-message cap~~ — **dead.** Same
  ruling. If these ever hurt in a capture, the fix shape is spill/list+tools, not a cut.
- ~~`est_tokens` density assumption~~ **WITHDRAWN — the sweep misread this.** The dynamic per-model
  ratio exists (`tokenratio`, asymmetric EWMA fed by real `usage.prompt_tokens`) and the floor uses
  it as its safety factor. The event log proves the estimate CAUGHT the 210K prompt: the floor
  emitted `over_budget: true` (warning) on the exact dead calls — msg 52,637 tokens est against a
  49,152 window, nothing shrinkable — and fired **58×** across the C1 run with nothing consuming
  the signal. Fixed the consumption side instead: the suite now counts `context.floor_over_budget`
  per row. The arithmetic needs no change; the composed-call class is closed by Tier 1's
  self-bounding.
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
