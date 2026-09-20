# GOAL: lift every Bonsai 2 L5 battery cell above 75%

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
- Read every selected capture from first prompt to final reply/reasoning. Do not substitute counts, `grep`, snippets, or a model summary for a walk.
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

Keep a finite top-level ledger in `docs/goals/bonsai-l5-75-loop-report.md`: per-cell current score/status, the causal findings, rejected candidates with reasons, accepted changes/tests/commits, replays, exact reruns, and the evidence that closed each cell.

## The loop

### 1. Establish the baseline

Before each iteration:

1. Inspect `git status`, current branch/HEAD, the live `~/.cria/cria.toml`, service health, model identity, `/props`, and the structured suite records.
2. Confirm the served runtime context is the actual context advertised to the harness; do not confuse trained context with runtime context.
3. Read the complete task prompt and final workspace/evidence for every open cell. Run the relevant frozen check yourself where the archived environment permits it.
4. Preserve the exact row/run ids and final usefulness judgments in the report.

### 2. Walk the failing behavior exactly as `docs/walk-prompt.md` requires

Walk all currently open cells, not only the lowest score. For each selected run, read in chronological order:

- every captured outbound prompt/body sent by cria;
- every reply and its full reasoning channel;
- model tool calls and harness results;
- cria structured events and milestone/final usefulness evidence;
- the final workspace diff and the real task checks.

Use at most ten read-only child walkers for disjoint cells or disjoint chronological capture ranges, with boundaries that preserve the whole sequence. The Supervisor must read enough of each complete run to verify every claimed causal chain. Record specific chains in the report: **observed context or event → coder reasoning/action → disk/check consequence**.

Also walk the repaired Responses preflight failures enough to confirm the compatibility fixes are on the correct wire boundary and did not create a silent request-semantic change.

Look for shared, language-agnostic mechanisms that allowed: long no-write periods, scratch-only work, partial scaffolding followed by termination, unresolved dependency recovery, failing checks not changing the next action, missing required tests/docs, missing transfer from scratch to deliverables, premature completion, malformed wire/tool semantics, or stale/missing environment facts. A language-specific symptom is not itself a candidate assist.

### 3. Form candidate fixes only from demonstrated causes

For every candidate, write a compact record before editing:

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
2. Have an independent Reviewer assess the fixed acceptance boundary and likely false-positive/false-negative harm.
3. Replay it against the exact captured model prompts/responses and relevant archived workspace. A replay must exercise the actual intervention boundary and show a changed, correct outcome; a mocked unit assertion alone is insufficient.
4. Reject a candidate if the replay does not improve the observed failure without harming the original good path. Record rejected candidates and why.

### 5. Implement only survivors

Assign one surviving coherent change to a Coder. It owns implementation, focused checks, fails-before/passes-after test, full test suite, and a precise report. The Supervisor inspects the diff, runs independent relevant checks, reviews with the Reviewer, commits/pushes the unit, restarts `cria.service`, and confirms `/health` before a battery rerun.

Do not combine speculative fixes. Do not run broad acceptance repeatedly while a shared failure class is not explained. After a changed/expanded/recurrent failure class, perform a strategy reset: return to the complete interaction and the shared architecture/environment boundary, prove a new root-cause hypothesis with focused deterministic evidence, then continue.

### 6. Re-run only open cells and judge them honestly

Re-run only cells currently at or below 75%, using the same L5 contract, live model, comparable harness/suite isolation, task prompt revision, and final independent usefulness judgment. Do not alter the task contract or score to pass it.

At each milestone, inspect frozen evidence and record the holistic usefulness percentage and `continue`/`stalled` decision through the suite's canonical tooling. Do not turn percentage into a mechanical control rule. On final completion, record usefulness through `suite/usefulness.py`, refresh the battery report, and preserve the run/call captures.

A rerun that is not above 75% remains open and becomes evidence for the next walk. A rerun above 75% closes that cell. If a shared candidate regresses an already closed cell, reopen only that affected cell and diagnose the regression before claiming progress.

## Definition of done

This goal is complete only when all six valid Bonsai 2 L5 cells have a latest comparable final usefulness judgment **strictly greater than 75%**, each with preserved workspace/capture evidence, and all shared changes are committed, pushed, fully tested, live-restarted, and documented in the report.

The final report must list the final score and run id per cell; accepted and rejected candidate fixes; capture replay evidence; full-suite result; service health; and any residual risks that did not invalidate the closed acceptance boundary. Never declare success from an average.
