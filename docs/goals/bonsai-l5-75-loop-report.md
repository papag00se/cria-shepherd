# Bonsai 2 L5 >75% closure report

## Acceptance ledger

| Cell | Baseline run | Baseline final usefulness | Status |
|---|---|---:|---|
| shipping-rates-rb | `shipping-rates-rb_ternary-bonsai-2_codex_pon_1789865828` | 55% | open |
| cart-billing-go | `cart-billing-go_ternary-bonsai-2_codex_pon_1789869635` | 0% | open |
| orders-api-py | `orders-api-py_ternary-bonsai-2_codex_pon_1789870342` | 55% | open |
| feed-pipeline-java | `feed-pipeline-java_ternary-bonsai-2_codex_pon_1789872767` | 0% | open |
| handles-cli-node | `handles-cli-node_ternary-bonsai-2_codex_pon_1789874266` | 65% | open |
| rust-toml-cli | `rust-toml-cli_ternary-bonsai-2_codex_pon_1789877114` | 0% | open |

Strict closure criterion: every cell's latest comparable L5 final usefulness judgment is >75%.

## Baseline environment — 2026-09-20

- Branch: `bonsai-l5-75-loop`, branched from `main` at `01dfec3`.
- Preserved pre-existing unrelated modification: `docs/walk-prompt.md` (the concurrent/sibling worktree check found no running sibling agent).
- `cria.service`: active; `GET :18085/health` returned `{"status": "ok"}`.
- Served model: `ternary_bonsai_2_27b_pq2_0`; `GET :18084/props` reports runtime `n_ctx: 40960` (the relevant advertised runtime context, not a trained-context assumption).
- Exact suite rows and all six capture/archive directories were located under `suite/results/results.jsonl`, `~/.cria/calls/`, and `~/.cria/suite/`.
- Compatibility history check begun: preflight repairs are `bf15e62` and `f1f903c`; they are excluded from the comparable score ledger and will be walked at their wire boundary.

## Walks and candidate records

Six chronological walks and one Responses-boundary walk are in progress. First passes established shared leads but each explicitly reported incomplete capture coverage; each owner has been continued on its same assignment. No lead is treated as a finding until full coverage and supervisor verification.

Preliminary, unaccepted cross-cell leads: initial planner `wsview` facts were unavailable; a positively judged step was recorded `observe_only` and remained active; multiple runs ended in an oversized Responses/proxy 400 path after no-change refit; and completed research/setup did not reliably transfer to deliverables. These are not candidates yet. The Responses preflight analysis confirmed the two original failures were ingress rejects before upstream calls, but also flagged a possible silent native-search semantic loss outside the observed Codex route; it is not an accepted change.

Walk integrity: no cell has full coverage yet. The shipping walker created `/tmp/cria-capture-manifest.txt` while attempting a listing, disclosed it immediately, and was directed to continue with read-only tooling only; this did not touch the workspace/repository but is retained as an evidence-process incident. The rust walker continued through `0009`, where planner forcing replaced read/fetch tools with `submit_plan` after unavailable workspace probes; it still must cover `0010+` and matching events/evidence.

## Strategy reset — walk execution

The initial whole-run walker assignments failed their acceptance boundary: each exhausted its context after a handful of large artifacts, and repeated continuations produced no convergent complete walk. Those partial reports are retained only as leads. No further whole-capture assignment may be launched.

Replacement approach: partition each capture into bounded contiguous numeric ranges with a committed/durable handoff ledger recording (1) inclusive artifact range and offsets for a partially read large artifact, (2) files actually opened, (3) chronological context → action → consequence facts, and (4) next exact artifact. A child owns one such bounded range through a complete read-only report; the supervisor verifies its cited files before assigning the next range. The final per-cell walk is complete only when these ranges cover every artifact and the event/workspace/check evidence.

## Accepted units / replay / reruns

None yet.

## Rejected candidates

None yet.
