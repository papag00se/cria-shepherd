# Bonsai 2 L5 >75% closure report

## Acceptance ledger

| Cell | Baseline run | Baseline final usefulness | Status |
|---|---|---:|---|
| shipping-rates-rb | `shipping-rates-rb_ternary-bonsai-2_codex_pon_1789940747` | 85% | closed |
| cart-billing-go | `cart-billing-go_ternary-bonsai-2_codex_pon_1789869635` | 0% | open |
| orders-api-py | `orders-api-py_ternary-bonsai-2_codex_pon_1789870342` | 55% | open |
| feed-pipeline-java | `feed-pipeline-java_ternary-bonsai-2_codex_pon_1789872767` | 0% | open |
| handles-cli-node | `handles-cli-node_ternary-bonsai-2_codex_pon_1789874266` | 65% | open |
| rust-toml-cli | `rust-toml-cli_ternary-bonsai-2_codex_pon_1789877114` | 0% | open |

Strict closure criterion: every cell's latest comparable L5 final usefulness judgment is >75%.

## Baseline environment — 2026-09-20

- Branch/HEAD: `main` at `3aaa99f`; `git status --short --branch` was clean. The Roles Orchestrator showed no sibling agent modifying this worktree before report maintenance.
- `cria.service`: active; `GET :18085/health` returned `{"status": "ok"}`.
- Served model: `ternary_bonsai_2_27b_pq2_0`; `GET :18084/props` reports runtime `n_ctx: 40960` (the relevant advertised runtime context, not a trained-context assumption).
- Live config was inspected at `~/.cria/cria.toml`: planner and L5 are enabled; capture calls are on; coder output reserve is 16384.
- Exact suite rows and all six capture/archive directories were re-confirmed under `suite/results/results.jsonl`, `~/.cria/calls/`, and `~/.cria/suite/`.
- Compatibility history check remains required: preflight repairs are `bf15e62` and `f1f903c`; they are excluded from the comparable score ledger and must be walked at their wire boundary.

## Walks and candidate records

Previous incomplete walk reports remain leads only and do not establish causal findings. A fresh lossless walk was initialized on 2026-09-20 with `suite/walk.py` for every open cell under `/tmp/cria-l5-walk-20260920/`, using self-contained full-prompt segments at the prescribed 250,000-byte ceiling. Wave 1 has six fresh, read-only Coder walkers, one per cell, on the first chronological segment; each must persist a cited finding file before its next segment is assigned. No lead is treated as a finding until complete coverage and supervisor verification.

Preliminary, unaccepted cross-cell leads: initial planner `wsview` facts were unavailable; a positively judged step was recorded `observe_only` and remained active; multiple runs ended in an oversized Responses/proxy 400 path after no-change refit; and completed research/setup did not reliably transfer to deliverables. These are not candidates yet. The Responses preflight analysis confirmed the two original failures were ingress rejects before upstream calls, but also flagged a possible silent native-search semantic loss outside the observed Codex route; it is not an accepted change.

Walk integrity: no cell has full coverage yet. Fresh wave 1 finding files are present for all six cells and were checked against the actual opening capture artifacts. Five complete first segments establish the same provisional chain: the planner receives `wsview`'s explicit unobserved sentinel, repeatedly probes speculative paths, and then may submit an ungrounded plan. This is a lead, not a candidate, until all chronological segments, workspace/check evidence, and the Responses boundary are walked. The initial shipping finding omitted `chunk004.txt`, so it was rejected as incomplete and a fresh complete rewalk of segment 1 was dispatched; the other five cells advanced to their verified next segments. No repository or workspace was changed by walkers.

## Strategy reset — walk execution

The initial whole-run walker assignments failed their acceptance boundary: each exhausted its context after a handful of large artifacts, and repeated continuations produced no convergent complete walk. Those partial reports are retained only as leads. No further whole-capture assignment may be launched.

Replacement approach: partition each capture into bounded contiguous numeric ranges with a committed/durable handoff ledger recording (1) inclusive artifact range and offsets for a partially read large artifact, (2) files actually opened, (3) chronological context → action → consequence facts, and (4) next exact artifact. A child owns one such bounded range through a complete read-only report; the supervisor verifies its cited files before assigning the next range. The final per-cell walk is complete only when these ranges cover every artifact and the event/workspace/check evidence.

Verified fresh coverage now includes shipping segments 1–2, cart/orders/feed/handles/rust segments 1–4 (except shipping segment 3 is being corrected after its generated stub was detected). Segments consistently show an unobserved `wsview` sentinel before generic planning; later evidence adds distinct downstream forms: plan-cleaning deletes local-discovery and behavioral-check steps (shipping/orders/feed/handles), narrow research/rumination paths lose their outstanding factual objective or force ungrounded dependency discovery (cart/rust), and a serialized Handles step corrupts the grounded API URLs into `https://{handle}` / `https://{holder_address}`. The latter is a concrete false fact at the model boundary, but no candidate is accepted yet: all remaining chronological capture, final workspace/check state, history, adversarial review, replay, and the repaired Responses boundary remain required. Fresh next readers were dispatched only after cited reports were read and checked.

## Focused deterministic root-cause proof — 2026-09-20

The common first-segment chain is now deterministically located, not inferred from prose: `cria/planner_tools.py:_list_dir` answers from `wsview.current(cwd)` and returns the `not_yet_known` sentinel whenever `View.scandir()` is `None`. `wsview.py` establishes that a view is empty until a harness-executed survey returns on a later request. The only survey carriers are lowered outbound shell calls in `cria/writeproxy.py` (and completion gates), whereas the planner's deliberately shell-less reader loop answers synchronously from the current view. Therefore an initial planner `list_dir` cannot itself obtain the fact it asks for; repeated planner paths preserve `None`, and plan submission can occur before any coder-lowered call carries a survey. This exactly matches the cited initial capture sequences across all six cells.

This proves the upstream reach failure. It does **not** yet establish a safe candidate: a planner-side synchronous survey would violate the harness asynchronous boundary, while merely suppressing the planner or forcing a generic plan would preserve the missing fact. The existing Handles URL candidate is rejected at this stage: `_item_prompt()` deterministically preserves `https://api.handle.me/handles/{handle}` and `/holders/{holder_address}`; the current code/history already contain brace/template-grounding repairs, so capture coverage must identify the actual producer before any edit.

## Accepted units / replay / reruns

- **Private planner survey bootstrap — `76b904e`.** On a fresh planner-on task with a known unsurveyed harness root, Loop now performs one private existing lossless gate survey before planner gather, routes its asynchronous result through the existing transport/ingestion path, and removes the private call/result together before planner context. Exact Rust capture replay executed actual emitted scripts and both transport pages against `/home/jesse/suite-runs/suite-rust-toml-cli_ternary-bonsai-2_codex_pon_1789877114-6yfsl1v7`; the planner received root entries `Cargo.lock`, `Cargo.toml`, `src`, `target`, `tmp`, with no private protocol, tool role, or tool calls in planner history. Focused 87 passed; implementation full suite 4935 passed, 6 skipped; `cria.service` restarted and `/health` returned ok. An initial post-change shipping run `shipping-rates-rb_ternary-bonsai-2_codex_pon_1789937694` scored 55% by final usefulness but was deliberately excluded from the comparable grid because its note was `planner-survey 76b904e`, not the required `BATTERY2 …` form; it remains evidence only. A comparable detached rerun is now PID `1014693`, log `/tmp/shipping-rates-rb-battery2-rerun.log`, with heartbeat `fbe9517f`. Shipping-rates-rb closed at 85% in comparable run `shipping-rates-rb_ternary-bonsai-2_codex_pon_1789940747`; its monitor heartbeat was deleted. The remaining five cells remain open pending comparable reruns.

## Rejected candidates

- **Handles serialized URL corruption (2026-09-20): rejected before implementation.** The capture shows malformed current-step URLs, but deterministic focused execution of `loop._item_prompt()` preserves balanced template URLs verbatim, and current history includes prior brace/template-grounding repairs. The capture producer is not yet isolated; changing template cleaning now would duplicate or regress an existing owner.
- **Make `list_dir` a survey carrier (2026-09-20): rejected by history and adversarial check.** It appears to make the first coder list bootstrap `wsview`, but `tests/test_the_survey_never_outgrows_one_result.py` documents and proves the prior carrier regression: a list result can reach `READ_INLINE_MAX`, so appending a 6KB survey permits harness truncation of the model's real listing and leaves the view rejected. This violates the lossless-output boundary; no implementation/replay is permitted.
- **Private pre-planner gate survey bootstrap (2026-09-20): rejected after exact-capture replay.** A bounded implementation reused gate transport, cleaned private terminal results, and passed focused (88) and full (4936 passed, 6 skipped) tests. Its archive-root replay only surveyed the archive container and listed `workspace`; the required replay mounted at the nested archived project root did not prove the project-root listing. Per the replay gate, the change was reverted uncommitted; tests/review do not substitute for the missing real-boundary evidence.

## Artifact hygiene

The unrelated untracked `findings/` directory was preserved by moving it to `~/.cria/walk-findings/20260920/recovered-worktree-findings`; it was not committed into the user workspace.
