# Whole-read EOF fidelity — transport proof and early replay

## Scope

The proposed change is confined to recognized whole-file reads on inbound re-presentation. It preserves their leading blank lines and EOF newlines instead of stripping file bytes with the harness envelope. Generic envelope cleanup, ranged reads, listings and fetches retain their existing behavior. Explicit failures, denials and known harness cuts cannot overwrite the workspace view with an error or partial body.

This is separate from `5d304ae` (decomposed reasoner evidence and active-fact retention). The rejected denied-mutation experiment is not included.

## History and transport proof

`4671687` introduced envelope stripping; `58b0033` documented the read-result/listing byte discrepancy and removed the competing read-ledger byte label. The lossy read body could still overwrite the authoritative surveyed size through `View.note_read`.

The upstream model captures under `~/.cria/calls` are already re-presented. The pre-representation evidence is instead in `~/.cria/codex-home/sessions`. The checked-in `tests/fixtures/raw_whole_reads_eof.json` preserves complete raw call/result records and expected file bodies from:

- `rollout-2026-09-06T18-00-49-01a07961-d2a8-72f2-ba25-778ffcc6855b.jsonl`: `Cargo.toml`, no EOF newline.
- `rollout-2026-09-09T16-28-29-01a08880-60be-7342-9918-4cb287cd565d.jsonl`: `Importer.java`, one EOF newline.
- `rollout-2026-09-06T16-00-57-01a078f4-14df-7020-85e1-fa2eabdaf4f1.jsonl`: `cart/item.2.go`, three EOF newlines.

Each raw payload exactly matches its preserved workspace file. Codex does not universally append, remove, or collapse trailing newlines in these cases. No new framing protocol is justified by this evidence.

The regression suite executes the real survey program against a temporary fixture, applies that survey, re-presents the captured read, and checks the resulting model-visible body, cached bytes and surveyed size. Synthetic controls cover two EOF newlines, empty and blank-only files, and leading blank lines. The old implementation fails the newline-preservation cases. Additional fails-before controls show that a nonzero read and a marked harness cut previously replaced known bytes with an error or partial body. Denials and generic envelope behavior remain covered.

## Early counterfactuals, not a chained trajectory

Capture: `20260909T162829-01a08880-60be-7342-9918-4cb287cd565d`.

Script: `/tmp/replay_early_read_eof.py`; exact requests and complete responses: `/tmp/replay_early_read_eof/`.

CALL 0051 originally cited the 7551-versus-7552 discrepancy as evidence of stale or replaced source. The counterfactual restores only the latest whole-source read from its raw harness result and updates that source's current inventory byte count. All prompts, summaries, older history and stale-inventory wording remain unchanged. CALL 0052 is tested independently with the same correction. The generated CALL 0051 response is **not** spliced into CALL 0052; no returned tool calls are executed.

- **0051:** the corrected count is acknowledged, but the model still attributes real compiler errors to an older/replaced source and requests a clean compile. This is not a clean behavioral pass.
- **0052:** the model acknowledges matching file size, recognizes that the implementation has no parallel workers, and investigates the original implementation to preserve accumulation semantics. It identifies the inner `BufferedReader` argument problem but gives a false Java-version explanation, still fails to understand the header argument mismatch, and considers unsafe redesign ideas. The emitted baseline-inspection action is task-grounded; no repair, successful execution or usefulness improvement is established.

The earlier late-boundary 0099 replay also remained trapped in false compiler/version theories. That is negative recovery evidence, not proof that preserving file bytes lacks preventive value.

## Status

Transport correctness has fails-before/passes-after evidence. Independent review found no blocking correctness issue and approved exactly one fresh prevention-test cell after an atomic commit. Status-less results remain eligible for existing non-Codex compatibility: the rule is not evidenced unsuccessful, not universally proven exit-zero. Behavioral replay is mixed, not a demonstrated recovery or campaign win. Independent holistic usefulness must exceed 75%; compilation alone cannot satisfy the target. At 75% or below the campaign-effect hypothesis is rejected, while the correctness fix remains unless the failed-run walk establishes a regression. Archived workspaces were read but not modified.
