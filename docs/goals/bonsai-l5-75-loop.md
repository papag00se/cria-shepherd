# Historical goal: lift every Bonsai 2 L5 battery cell above 75%

**Retired operational instructions.** This document preserves historical campaign intent and evidence only; none of its launch, branch, delegation, reading or repair-loop instructions are operative. It authorizes no resumption. All walking now follows [the sole official process](../walk-prompt.md), including stage-specific Luna prompts and Main/Sol diagnosis. Current repository/operator policy governs any separately authorized implementation or campaign.

## Mission

Make `ternary-bonsai-2` useful on the L5 task battery. Run a disciplined **walk → candidate → adversarial check → exact-capture replay → implement → validate → rerun** loop until every cell in the latest comparable L5 row is **strictly above 75%**. A 75% result is not sufficient.

This is cria's responsibility. A low score is evidence that an assist, the wire path, environment parity, or the measurement loop allowed a bad outcome. Do not characterize any result as an inherent limitation or end the investigation there.

This goal is intentionally long-running. Do not stop after an audit, a plausible patch, green unit tests, a single improved cell, or a progress report. Continue until the definition of done is observed, unless every remaining action is truly externally blocked.

## Starting evidence: valid row to walk

The valid Bonsai 2 L5 row is the six cells launched after the Responses compatibility repairs, recorded in `suite/results/results.jsonl` and `docs/audits/battery-report.md`:

| task | final usefulness | run id |
|---|---:|---|
| `shipping-rates-rb` | 55% | `shipping-rates-rb_ternary-bonsai-2_codex_pon_1789865828` |
| `cart-billing-go` | 0% | `cart-billing-go_ternary-bonsai-2_codex_pon_1789869635` |
| `orders-api-py` | 55% | `orders-api-py_ternary-bonsai-2_codex_pon_1789870342` |
| `feed-pipeline-java` | 0% | `feed-pipeline-java_ternary-bonsai-2_codex_pon_1789872767` |
| `handles-cli-node` | 65% | `handles-cli-node_ternary-bonsai-2_codex_pon_1789874266` |
| `rust-toml-cli` | 0% | `rust-toml-cli_ternary-bonsai-2_codex_pon_1789877114` |

The two earlier `shipping-rates-rb` launches were preflight failures caused by unsupported Codex Responses controls. They led to `bf15e62` and `f1f903c`; keep them as compatibility evidence, but do not use them as comparable usefulness cells.

A cell which subsequently scores **>75%** is closed. Do not rerun it merely to raise the average or collect another sample. Reopen it only if a later shared change invalidates its specific acceptance evidence.

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

- Ground truth is an executed check or the authoritative structured event, never a coder claim or a line count.
- Read 100% of each selected capture's text, including complete prompts, replies, recorded reasoning, tool calls and results. Understand the sequence as the small model encountered it: what information it had, how its recorded reasoning interpreted that information, what it did, and what followed. Reading need not be literally one line at a time; lossless parsing and chronological batching are welcome. Search can navigate, but counts, snippets and summaries cannot replace reading. Do not infer unrecorded thoughts.
- Deterministic logic detects and gathers facts; a reasoner makes semantic judgments. Do not add keyword lists, task/language rules, proximity windows, or canned remedies to settle a judgment.
- Never truncate model-visible information; never replace a tool's real output with invented wording.
- Fix the upstream cause in cria. Do not paper it over in Codex configuration, task prompts, benchmark-specific hooks, suite scoring, or a fallback that silently changes behavior.
- Every behavior change needs a fails-before/passes-after test, `python -m pytest`, a commit and push, then `sudo systemctl restart cria.service` and a live health check.
- The model must not see the literal token `cria`; model-facing text belongs in `cria/prompts/*.txt`.
- Preserve user work and existing dirty files.
- Work directly on `main`. Do not create, switch to, or leave work on any other branch; commit and push each accepted unit to `main`.

## Supervisor operating model

This run is launched as the **Supervisor** role in the Paseo Role Orchestrator. Use its `launch_role` tool for every child; do not use generic child creation. The configured child roles are:

- **Coder** — owns one bounded, coherent implementation/validation unit. Use it for a read-only capture walk only when its assignment explicitly forbids edits, and for a surviving implementation candidate only after the Supervisor has selected the candidate.
- **Reviewer** — independent review after an integrated candidate exists. It must not edit.
- **General Purpose** — only if neither specialist fits.

The plugin gives delegated children no parent context by default. Each child prompt must therefore be self-contained: state the exact run id/capture paths, objective, scope, required reading method, constraints, expected artifact, and whether it is read-only. Do not ask children to rediscover the assignment from a missing parent transcript.

For a single WALK, launch **no more than ten children total**. Parallel read-only walkers may inspect disjoint cells/captures; no two editing children may touch the same code path or worktree. Reconcile every child report against the actual files/captures yourself before treating it as evidence. A child report is a lead, not a finding.

**Partition every walk into compaction-safe segments before delegating — a reader must never compact mid-walk.** Do not hand a walker a whole capture: its context fills, it compacts, and the walk silently degrades into a summarized skim (this is what derailed the prior run). Run `python3 suite/walk.py <capture_dir> --out <dir> --segment-bytes 250000 --label <cell>` for each open cell (resolve `<capture_dir>` from the run's `capture_dir` field in `suite/results/results.jsonl`). It writes self-contained segments under the measured compaction ceiling and one `assignments.json`; readers create actual findings inside the same temporary directory. Give each segment its own **fresh** walker — never continue a walker onto a second segment — and require it to write its finding file. Verify a segment's finding file cites real chunks/calls before assigning the next. A capture yields more segments than the ten-child cap, so dispatch in waves of fresh read-only walkers, verifying each wave's finding files before launching the next; the ten-child cap is per wave.

Use the canonical suite records and battery publication for run judgments/status. Keep causal findings and unresolved candidate decisions only in the current temporary walk directory, following `docs/walk-prompt.md`. Do not append another permanent attempt ledger, duplicate score table, proof inventory or intermediate review history; the old loop report is historical, not a required dependency.

## The loop

### 1. Establish the baseline

Before each iteration:

1. Inspect `git status`, current branch/HEAD, the live `~/.cria/cria.toml`, service health, model identity, `/props`, and the structured suite records.
2. Confirm the served runtime context is the actual context advertised to the harness; do not confuse trained context with runtime context.
3. Read the complete task prompt and final workspace/evidence for every open cell. Run the relevant frozen check yourself where the archived environment permits it.
4. Preserve the exact row/run ids and final usefulness judgments in the canonical suite records.

### 2. Walk the failing behavior exactly as `docs/walk-prompt.md` requires

Walk all currently open cells, not only the lowest score. For each selected run, read in chronological order:

- every captured outbound prompt/body sent by cria;
- every reply and its full reasoning channel;
- model tool calls and harness results;
- cria structured events and milestone/final usefulness evidence;
- the final workspace diff and the real task checks.

Use at most ten read-only child walkers for disjoint cells or disjoint chronological capture ranges, with boundaries that preserve the whole sequence. The Supervisor must read enough of each complete run to verify every claimed causal chain. Record specific chains in the current temporary findings: **observed context or event → coder reasoning/action → disk/check consequence**.

Also walk the repaired Responses preflight failures enough to confirm the compatibility fixes are on the correct wire boundary and did not create a silent request-semantic change.

Look for shared, language-agnostic mechanisms that allowed: long no-write periods, scratch-only work, partial scaffolding followed by termination, unresolved dependency recovery, failing checks not changing the next action, missing required tests/docs, missing transfer from scratch to deliverables, premature completion, malformed wire/tool semantics, or stale/missing environment facts. A language-specific symptom is not itself a candidate assist.

### 3. Form candidate fixes only from demonstrated causes

For each candidate, establish the following in the current working findings, not a separate receipt or permanent report. Consider removal and upstream correction before adding another assist:

- exact observed causal chain and affected run ids;
- the upstream owner/path in cria;
- why existing assists did not fire, did not reach the fact, or gave the wrong/mistimed steer;
- LANG / MODEL / HARNESS three-lens analysis;
- why it is additive/regression-only and how it can mislead;
- the smallest fails-before test and expected passes-after behavior;
- the exact real capture(s) to replay.

Search code and commit history before implementation. Build on the existing owner rather than duplicating detection/steer/probe machinery. Reject candidates that merely react to task vocabulary, a particular language/package manager, a fixed time/count threshold chosen as a semantic proxy, or that duplicate an existing assist.

### 4. Adversarially test candidates before landing

For each candidate:

1. Check the implementation against current code and relevant history for an earlier reverted footgun.
2. Challenge the proposed boundary for false-positive/false-negative harm; independently review the complete integrated change once in step 5, not every intermediate patch.
3. Replay the actual captured boundary and check relevant legitimate cases. Preserve necessary workspace inputs as small regression fixtures, not a permanent source/workspace mirror. Bound the conclusion to the demonstrated cause and correction; do not require whole-task or universal assist-benefit proof.
4. Reject a candidate if it does not correct the observed cause or harms the original good path. Keep the reason only while it is needed to settle current work.

### 5. Implement only survivors

Assign one surviving coherent change to a Coder. It owns implementation, focused checks, a fails-before/passes-after test, and the full test suite; hand off the diff and relevant test outcome, not another permanent report. The Supervisor inspects the diff, runs independent relevant checks, reviews with the Reviewer, commits/pushes the unit, restarts `cria.service`, and confirms `/health` before a battery rerun.

Do not combine speculative fixes or repeatedly run broad checks without using their results. A recurring or changed failure is a reason to inspect the relevant evidence, not an automatic restart of the investigation. Reuse completed readings and established facts; expand the investigation only when a concrete unresolved question requires it. A demonstrated local fix and its relevant regression checks can be settled without re-reading unrelated captures or reopening accepted fixes.

### 6. Re-run only open cells and judge them honestly

Re-run only cells currently at or below 75%, using the same L5 contract, live model, comparable harness/suite isolation, task prompt revision, and final independent usefulness judgment. Do not alter the task contract or score to pass it.

**Launch every battery run in the BACKGROUND, never as a blocking foreground shell.** `suite/run.py` pauses at each active-time checkpoint and blocks waiting for the campaign agent to record a milestone judgment via `suite/milestones.py`. A supervisor that runs `suite/run.py` in the foreground is then blocked waiting for the run while the run is blocked waiting for the supervisor — a deadlock that strands the run at its first checkpoint. So start the run detached (e.g. `setsid … &` or a background process), capture its run id and log, and END your turn — do not sit inside the run with `sleep` polling (that both blocks reporting and burns the turn).

**Report to the user every 10 active minutes while a run is in flight, driven by a heartbeat — not a self-timed loop.** An agent cannot reliably schedule its own periodic reports without blocking, so create a 10-minute Paseo heartbeat (`create_heartbeat`) whose prompt tells you to inspect the in-flight run's live workspace and post one report, and delete it when the run completes. Each report states the current inferred usefulness percentage and the material changes since the last report (inspected from the live workspace, not claimed), posted to the user — it is not the same thing as the internal milestone verdict. Between reports, at each 30/45/60-minute checkpoint, inspect frozen evidence and record the holistic usefulness percentage and `continue`/`stalled` decision through the suite's canonical tooling. Do not turn percentage into a mechanical control rule. On final completion, record usefulness through `suite/usefulness.py`, refresh the battery report, and preserve the run/call captures.

A rerun that is not above 75% remains open and becomes evidence for the next walk. A rerun above 75% closes that cell. If a shared candidate regresses an already closed cell, reopen only that affected cell and diagnose the regression before claiming progress.

## Definition of done

This goal is complete only when all six valid Bonsai 2 L5 cells have a latest comparable final usefulness judgment **strictly greater than 75%**, each with preserved workspace/capture evidence, and all shared changes are committed, pushed, fully tested, and live-restarted when authorized by the current operational gates.

Publish final judgments through the canonical suite/battery tooling. Report the outcome and material residual risks briefly; do not reproduce the attempt ledger or preserve temporary walks/reviews for score explanations. Close and remove each walk once its associated fixes settle, keeping repository regressions and actual model-call logs. Never declare success from an average.
