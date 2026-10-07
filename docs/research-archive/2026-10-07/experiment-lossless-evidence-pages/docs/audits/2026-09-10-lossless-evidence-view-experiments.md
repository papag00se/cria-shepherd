# Lossless evidence-view experiments — not a deployed fix

Live behavior remains `ec28f2f`. These experimental prompts and the artifacts below do not change the running service. Latest independently graded Ornith/feed-pipeline-java usefulness remains 50%; historical best70%, target strictly above75%.

## Established failure boundary

The failed cell is `feed-pipeline-java_ornith15_codex_poff_1789025662`, capture `20260910T003432-01a08a3d-5e99-7123-bce7-5d058cd57443`.

Native events distinguish prepared/captured bodies from requests accepted for inference:

- Turn `df48cec1`: compactor0115/0117 rejected at54,068 prompt tokens against49,152. Unchanged refits0116/0118 were captured but not resent. Satisfaction0119 and its no-reason attempt also exceeded capacity; no semantic verdict resulted.
- Turn `c334932b`: compactor0173/0175 rejected at62,022; satisfaction0177 at69,474; no-reason0179 at65,155. The corresponding unchanged refits0174/0176/0178/0180 were not sent. This was not evidence of an empty model answer or a response parser losing one.

Walk-reader delivery audits concern the reader's native tool returns, not accepted Ornith inference. An embedded truncation warning in chunk181 is captured task evidence, not by itself truncation of the walk reader's output.

## Rejected/non-adopted approaches

All experiments were inference-only; returned tool calls were never executed against evaluation workspaces.

1. A strict-admission overlay around the actual context floor and `Upstream._prep` consumed the exact0115 source in three completed buffered model calls. Every source byte was accounted for, without floor reduction or reserve clamping. Free-prose fidelity nevertheless failed: a source record saying `Process running with session ID 34898` became “no usable output (truncated).” No folio was adopted or passed downstream.
2. Extractive line-range v1 returned valid ranges but retained almost the whole page; output framing made it non-reducing.
3. V2 kept internal coordinates private, used literal excerpts, and clarified compactness. It still failed net reduction.
4. V3 added the exact original task as protected context, without changing source or sampling. It changed selection but returned fenced, nested, overlapping and inverted ranges. No repair or adoption.
5. V4 offered one ordinary non-executable `select_source_lines` declaration, without forced tool choice. It returned a complete declaration plus commentary. The initial no-prose rule rejected it. Subsequent review found the declaration structurally valid—365 unique supplied IDs—but its evidence recall inadequate. The initial rejection remains recorded. Future declaration handling should quarantine commentary, not veto independently valid data merely because commentary exists; it must never forward that prose or private IDs.

Artifact directories under `/tmp/feedwalk-1789025662/`: `lossless-page-model-replay/`, `extractive-page-replay/`, `extractive-page-replay-v2/`, `extractive-page-replay-v3-task/`, and `extractive-page-replay-v4-declaration/`. Exact bodies, responses and previous runner/prompt variants are preserved there. These are not five shipped fixes or five usefulness grades.

## A lossless source representation, tested offline

`reconstruct_worklog.py` reconstructs the raw harness prefix through0115 using cria's own Responses conversion, inbound representation, gate transport verification, nested workspace survey, worklog rendering and dedup owners. The reconstructed worklog equals the exact captured0115 source. Restoring the active transport identity was necessary to retain its no-tests qualifier; restoring its nested survey was necessary to reproduce the exact0119 current-file packet. No captured command was executed.

The candidate view then uses:

- Exact result-repeat runs scoped to the same call signature. References preserve refusals and point forward only within an equal-result run.
- Exact read-result equality with a preceding whole-write content argument, without inferring that the write succeeded.
- References to identical file values already supplied in the unchanged current-file packet.
- One line-based COPY/literal representation for a later historical whole-write argument, based on the nearest preceding still-literal argument for the same path. This is an argument-value representation, not an edit to apply. Its values round-trip exactly; it does not delete old source or author task code.

No action-block dedup is applied after introducing references: equal-looking reference text must not be mistaken for equal original outcomes. Experimental code uses private copies for rendering only; production must not mutate protocol tool calls that later pass through normalization.

The value codec passed16 tests covering insertion/deletion, Unicode, CRLF, blank lines, missing final newline, and invalid references. This is not a production-suite result for an integrated feature.

The complete candidate0119 packet measures **40,861 input tokens +8,192 reserve**, within49,152. The original tokenization reproduces the backend's61,432-token rejection. Measurements concern the full final packet, not just the smaller compactor input.

## Real judge replay and the ordering result

Both arms retain the same model, sampling, tools, data values and output budget. Response transport is buffered for these controlled replays. Proxy admission is calibrated from the exact tokenizer measurement; no model setting or live calibration is changed.

- Original ordering: the lossless packet reached inference, but consumed8,192 output tokens and ended `length`, without content or tools. Full reasoning was read. It repeatedly claimed it lacked final source and tried to reconstruct historical references despite the literal current-file packet being present before the long history.
- Ordering-only arm: moved that unchanged current-file packet after the historical task/evidence message. No closing reminder, forced verdict or tool removal. Post-`_prep` order and full reserve were verified. Input count stayed40,861. It ended normally with a structured negative verdict, recognizing current `WORKERS_ENABLED=false` and discarded worker maps.

Cria's existing `_satisfaction_verdict` parser and `_verdict_nudge` grounding accepted the exact missing-`REVIEW.md` diagnosis against the reconstructed message-derived view. Only that grounded task quote would be delivered; the broader proposed implementation is not promoted into a directive. This is a promising single-call result, not demonstrated usefulness improvement or permission to weaken other guards.

Artifacts: `prototype_paired_result_dedup.py`, `prototype_write_read_dedup.py`, `prototype_keeper_dedup.py`, `prototype_argument_delta.py`, `argument_delta_codec.py`, tokenizer/proof JSON files, `lossless-0119-replay/`, and `lossless-0119-current-tail/` under the same `/tmp` directory.

## Requirements before integration

- Keep every reference resolvable in every consumer, including no-reason retry and negative-diagnosis support—not only the first satisfaction request. A bare source string that depends on an absent file packet is invalid.
- Keep the current packet literal and correctly attributed. Historical COPY/literal data must not be read as an applied patch.
- Enforce no-loss admission and reserve accounting at the wire; preserve role intent and strip private hints. Never generalize an estimate into a claim of backend acceptance.
- Preserve meaningful inspection tools, source pairing, refusal provenance, completion safeguards and original task/grading scope.
- Test the integrated producer/consumer path fails-before/passes-after, run the full suite, then run a fresh unchanged cell with independent usefulness grading. Rejecting a candidate or avoiding an overflow is not campaign completion.
