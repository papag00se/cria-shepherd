# GOAL: lift every nemotron-elastic L5 battery cell above 75%

## Mission

Make `nemotron-elastic` useful on the L5 task battery. First establish a **fresh comparable
baseline row** (the model has been paused since 2026-09-05 and every existing row predates the
Responses repairs, the planner survey bootstrap, and the review-remediation work), then run a
disciplined **walk → candidate → adversarial check → exact-capture replay → implement → validate →
rerun** loop until every cell in the latest comparable L5 row is **strictly above 75%**. A 75%
result is not sufficient.

**The unit of iteration is the whole row, never a single cell** (see [Row cadence](#row-cadence)):
run every open cell at one HEAD, walk the whole row, land the fixes the row justifies, then run
the next row. A cell that closes (>75%) is done and is not run again. Cross-cell evidence from one HEAD is the signal that selects fixes; a single-cell
run/walk/fix cycle chases per-cell noise and cannot tell a shared cause from a local one.

This is cria's responsibility. A low score is evidence that an assist, the wire path, environment
parity, or the measurement loop allowed a bad outcome. Do not characterize any result as an
inherent limitation of a 12B mamba-hybrid or end the investigation there. "Weakest of the laddered
models" is a historical observation, not a verdict — the Bonsai 2 campaign took a model from a
44% row to 90% by fixing cria, and that is the template here.

This goal is intentionally long-running. Do not stop after an audit, a plausible patch, green unit
tests, a single improved cell, or a progress report. Continue until the definition of done is
observed, unless every remaining action is truly externally blocked.

## The model

- **`nemotron-elastic`** — NVIDIA Nemotron-Elastic 12B-A2B, mamba-hybrid architecture, its own
  permissive chat template (no Llama alternation guards; do not confuse it with the retired
  `nemotron-nano`, an unrelated Llama-3.1 derivative that llama.cpp cannot serve).
- Service: `llama-nemotron-elastic.service` (installed, currently disabled). One model fits on
  the GPU at a time; swap with `scripts/swap_and_test.sh` semantics (stop all `llama-*.service`,
  start the target, wait for `/v1/models` on `:18084`) or let the suite runner own the standard
  model start. cria caches the loaded model id — restart `cria.service` after a swap.
- Confirm the served runtime context from `:18084/props` at baseline; do not assume trained
  context.
- Paused 2026-09-05 with 184 result rows. Its recovered inference ladder is FROZEN in
  `suite/historical_ladder.json` (L5 total 57%: ruby 59, go 31, python 76, java 20, node 70,
  rust 84). It was extensively walked in `docs/audits/battery-pair-walk.md`. All of this is
  **walk evidence and prior-knowledge only** — none of it is a comparable cell.

## Phase 0 — establish the valid baseline row

There is no comparable starting row. Produce one before any candidate work:

1. Verify environment per the loop's baseline step (HEAD, live `~/.cria/cria.toml`, service
   health, served model identity, `/props`, suite records).
2. Run all six L5 cells (`shipping-rates-rb`, `cart-billing-go`, `orders-api-py`,
   `feed-pipeline-java`, `handles-cli-node`, `rust-toml-cli`) at current HEAD with the exact
   note form `BATTERY2 L5 nemotron-elastic <short-HEAD> p4`, planner on, GPU-serialized.
3. Record the row in the report ledger. Cells already >75% at baseline are closed immediately;
   the rest are the open set the loop works.

A run whose note deviates from the required form, that dies mid-flight, or that ran against a
degraded environment is evidence only, never a comparable cell — record it and relaunch.

## Non-negotiable doctrine

Read and obey, in full, before touching behavior:

1. `AGENTS.md`
2. `docs/principles.md`
3. `docs/heuristic-assists.md`
4. `README.md`
5. `docs/shephard.md`
6. `docs/walk-prompt.md`
7. `docs/task-battery.md`

Consequences:

- Ground truth is an executed check or the authoritative structured event, never a coder claim or
  a line count.
- Read every selected capture from first prompt to final reply/reasoning. Do not substitute
  counts, `grep`, snippets, or a model summary for a walk.
- Deterministic logic detects and gathers facts; a reasoner makes semantic judgments. Do not add
  keyword lists, task/language rules, proximity windows, or canned remedies to settle a judgment.
- Never truncate model-visible information; never replace a tool's real output with invented
  wording.
- Fix the upstream cause in cria. Do not paper it over in Codex configuration, task prompts,
  benchmark-specific hooks, suite scoring, or a fallback that silently changes behavior.
- **Model-agnosticism cuts both ways**: a fix for nemotron-elastic must not regress the closed
  Bonsai 2 row. A candidate that reacts to this model's identity, template quirks, or vocabulary
  is not a candidate; find the model-agnostic upstream boundary. If a shared change could
  invalidate a closed Bonsai 2 cell's acceptance evidence, say so in the candidate record.
- Every behavior change needs a fails-before/passes-after test, `python -m pytest`, a commit and
  push, then `sudo systemctl restart cria.service` and a live health check.
- The model must not see the literal token `cria`; model-facing text belongs in
  `cria/prompts/*.txt`.
- Preserve user work and existing dirty files.
- Work directly on `main`. Do not create, switch to, or leave work on any other branch; commit
  and push each accepted unit to `main`.

## Supervisor operating model

This run is launched as the **Supervisor** role in the Paseo Role Orchestrator. Use its
`launch_role` tool for every child; do not use generic child creation. The configured child roles
are:

- **Coder** — owns one bounded, coherent implementation/validation unit. Use it for a read-only
  capture walk only when its assignment explicitly forbids edits, and for a surviving
  implementation candidate only after the Supervisor has selected the candidate.
- **Reviewer** — independent review after an integrated candidate exists. It must not edit.
- **General Purpose** — only if neither specialist fits.

The plugin gives delegated children no parent context by default. Each child prompt must be
self-contained: exact run id/capture paths, objective, scope, required reading method,
constraints, expected artifact, and whether it is read-only. For a single walk, launch no more
than ten children per wave; a child report is a lead, not a finding, until you have reconciled it
against the actual files/captures yourself.

**Partition every walk into compaction-safe segments before delegating.** Run
`python3 suite/walk.py <capture_dir> --out <dir> --segment-bytes 250000 --label <cell>` per open
cell (resolve `<capture_dir>` from the run's `capture_dir` field in
`suite/results/results.jsonl`). One fresh walker per segment — never continue a walker onto a
second segment. Verify each segment's finding file cites real chunks/calls before assigning the
next.

Keep a finite top-level ledger in `docs/goals/nemotron-l5-75-loop-report.md`: per-cell current
score/status, causal findings, rejected candidates with reasons, accepted changes/tests/commits,
replays, exact reruns, and the evidence that closed each cell.

## Operational rules carried forward from the Bonsai 2 campaign (each one was paid for)

- **All durable artifacts live outside `/tmp`.** Walk segments and finding files go under
  `~/.cria/walk-findings/<date>/<cell>/`; a reboot destroyed an entire walk's evidence when it
  lived in `/tmp`.
- **Launch every battery run detached in the BACKGROUND** (`suite/run.py` blocks at milestone
  checkpoints waiting for judgments; a foreground supervisor deadlocks against it). Capture the
  run id and log, then END your turn.
- **Queues must be crash-survivable and failure-visible**: `systemd-run` units **without
  `--collect`** (a collected failed unit evaporates with its evidence), health probes that
  retry through a restarting `cria.service` instead of dying on one refused connection (a
  single-shot `curl` race killed a whole serialized chain), and no `set -e` chain where one
  transient kill strands every downstream cell.
- **NON-NEGOTIABLE! Exactly ONE recurring 10-minute Paseo heartbeat per in-flight run** (`create_heartbeat`),
  with no one-shot/max-run expiry. Its prompt is a mandatory reporting procedure: inspect the
  live workspace and current checks; make a fresh holistic usefulness judgment percentage for the work
  presently on disk - this is a must and cannot be skipped FOR ANY REASON; then post the user report in the exact form
  `usefulness=<N>%` and `material changes since the previous report: <facts|none>`.
  `pending`, “no usefulness judgment happened”, the last comparable cell score, process liveness,
  or a bare “still active” are **not** substitutes for that fresh percentage; the prior comparable
  score may be extra context only. Record canonical milestone verdicts via `suite/milestones.py`
  when due, record final usefulness via `suite/usefulness.py` immediately on termination, and
  delete the heartbeat only after that terminal packet and report are recorded. The Supervisor
  personally issues every heartbeat-triggered report; it may not delegate that obligation or let
  other work defer it. Never create a second concurrent heartbeat — duplicate heartbeats caused
  verdict-staleness churn in the completion gate.
- Record final usefulness via `suite/usefulness.py`, refresh the battery report, preserve run
  and call captures.

## Row cadence

NON-NEGOTIABLE. Every iteration is one **row**:

1. **Freeze HEAD.** Land every accepted, reviewed fix, push, restart `cria.service`, confirm
   `/health`. Record the row's short HEAD.
2. **Run the whole row.** Queue every open L5 cell (latest comparable result ≤75%) in one
   crash-survivable, GPU-serialized queue at that HEAD, note form
   `BATTERY2 L5 nemotron-elastic <short-HEAD> p<row#>` (the same note for every cell of the
   row). Closed cells (latest comparable result >75%) are done and are **not** rerun. **No `cria.service` restart, model swap, or commit that changes
   live behavior while the row queue is active** — a row with mixed HEADs is evidence only.
   While the row runs, exactly one recurring 10-minute heartbeat covers the queue and reports on
   the currently active cell (fresh `usefulness=<N>%` + material changes, per the rules above);
   each cell's milestone/final judgments are recorded as it finishes.
3. **Walk the whole row.** After the last cell terminates, walk every sub-75% cell's capture (and
   any cell that regressed), then reconcile across cells: a failure class that appears in two or
   more cells is prioritized over a single-cell failure. Walks and candidate work may begin on
   cells that have already finished while later cells are still running, but nothing goes live
   until the row is complete.
4. **Fix from the row.** Select candidates from the cross-cell evidence. Each is still one
   coherent Coder unit with its own fails-before/passes-after test and independent review; several
   independent accepted units may land between rows.
5. **Next row.** Return to step 1. Never launch a single-cell rerun to test one fix. The only
   exception is relaunching a cell whose run was invalid (died mid-flight, deviating note,
   degraded environment), still at the row's HEAD.

A row with no new accepted fix since the previous row is not authorized; that is a strategy reset
(return to the cross-cell evidence and prove a new cause), which is work, never a stopping point.

## The loop

### 1. Establish the baseline

Before each iteration: inspect `git status`/HEAD, the live `~/.cria/cria.toml`, `cria.service`
health, served model identity, `/props` runtime context, and the structured suite records. Read
the complete task prompt and final workspace/evidence for every open cell; run the relevant
frozen check yourself where the archived environment permits. Preserve exact row/run ids and
final usefulness judgments in the report. Provide 10-minute reports per rules above (non-negotiable)

### 2. Walk the failing behavior exactly as `docs/walk-prompt.md` requires

Walk all currently open cells, not only the lowest score. For each selected run, read in
chronological order: every captured outbound prompt/body, every reply and its full reasoning
channel, model tool calls and harness results, cria structured events and milestone/final
usefulness evidence, the final workspace diff and the real task checks. Record specific chains:
**observed context or event → coder reasoning/action → disk/check consequence**. Before forming
any candidate, also read the prior nemotron-elastic walk (`docs/audits/battery-pair-walk.md`) and
compare: a failure mode already fixed for Bonsai 2 that recurs here points at a boundary the fix
did not cover, not at a new mechanism.

### 3. Form candidate fixes only from demonstrated causes

For every candidate, write a compact record before editing: exact observed causal chain and
affected run ids; the upstream owner/path in cria; why existing assists did not fire, reach the
fact, or steer correctly; LANG / MODEL / HARNESS three-lens analysis; why it is
additive/regression-only; the smallest fails-before test; the exact real capture(s) to replay;
and the closed-Bonsai-2-row regression assessment. Search code and commit history first — build
on the existing owner rather than duplicating detection/steer/probe machinery.

### 4. Adversarially test candidates before landing

Check against current code and history for reverted footguns; independent Reviewer assessment;
replay against the exact captured prompts/responses and relevant archived workspace at the actual
intervention boundary. Reject a candidate whose replay does not improve the observed failure
without harming the original good path. Record rejections and why.

### 5. Implement only survivors

One surviving coherent change per Coder: implementation, focused checks, fails-before/passes-after
test, full suite, precise report. Supervisor inspects the diff, reviews with the Reviewer,
commits/pushes, restarts `cria.service`, confirms `/health` before a battery rerun. Do not
combine speculative fixes. After a changed/expanded/recurrent failure class, perform a strategy
reset: return to the complete interaction and the shared boundary, prove a new root-cause
hypothesis with focused deterministic evidence, then continue. Repeated sub-75% reruns without a
new accepted candidate are a convergence failure, not authorization for another rerun.

### 6. Re-run the whole row and judge it honestly

Re-run every open cell as one row per [Row cadence](#row-cadence): same L5 contract, live model,
comparable harness/suite isolation, task prompt revision, and final independent usefulness
judgment for every cell. Do not alter the task contract or score to pass it. A rerun >75% closes
that cell; closed cells are not rerun. If a shared candidate regresses the **frozen Bonsai 2
acceptance evidence**, diagnose that before claiming progress. Provide 10-minute
reports per rules above (non-negotiable)

## Definition of done

This goal is complete only when all six nemotron-elastic L5 cells have a latest comparable final
usefulness judgment **strictly greater than 75%**, each with preserved workspace/capture
evidence, and all shared changes are committed, pushed, fully tested, live-restarted, and
documented in the report. The final report lists final score and run id per cell; accepted and
rejected candidates; capture replay evidence; full-suite result; service health; residual risks;
and confirmation that the Bonsai 2 closed row was not regressed. Never declare success from an
average.
