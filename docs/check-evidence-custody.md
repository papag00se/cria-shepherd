# Check evidence custody

## Review lens and scope

The second pass over the 26 stopped ornith1.5_9b / Java runs used evidence ownership and freshness, rather than guidance authorship or follow-through. Main examined the final coder request's explicit check/steer carriers for every run, followed the historical continuation/check carriers where those explicit blocks were absent, and searched paired ordinary shell results for the exact orchestration-marker collision. This is a selected-boundary review across all 26 runs, not 26 complete chronological walks. Prior independent final judgments remain unchanged; no usefulness gain is inferred from these corrections.

The review found genuine coder-issued build output containing `EXIT:`. Examples include run004/0034 (a missing `CSVReader.readHeader` member), run014/0018 (offline Maven plugin resolution failure), and run023/0070 (missing `CSVHeaderMapping`). The full paired commands and returned outputs were read. Some commands print pipeline status rather than compiler status; preserve those bytes without interpreting their printed zero as successful compilation. Successful ordinary build output with the same marker exists too, so the correction must preserve successes and failures alike, not recognize error words.

The selected final carriers also retain older failures, current results, unknown automatic-check results, and historical handoff snapshots. Their presence alone does not demonstrate a freshness defect. For example run026/0091's complete judge reasoning explicitly follows the returned failing compilation and absence of a subsequent edit; its negative verdict is not evidence of an erroneous stale-failure judgment.

## Restored invariants

### Ordinary output is not orchestration

The shared evidence renderer must identify internal gate plumbing from its producing call/transport provenance, not arbitrary substrings in user command arguments or tool output. `EXIT:` is ordinary text that a build script can print. Losing the command, result, or their paired identifier deprives every downstream judgment of authoritative evidence. Genuine internal probes still pass through the existing gate representation owner; this does not authorize exposing private scaffolding.

### Supersession requires the corresponding newer check

Reading a log containing a green test tally is not running that check. A passing subset cannot establish that a broader failing check passed. An older green run cannot outrank a newer red run. The invocation owner must establish scope and ordering before a runner tally can suppress old findings. Unknown scope remains unknown; do not replace it with a semantic guess or a keyword detector. All carried commands need qualifying receipts; repeated display command heads do not establish distinct scope coverage. Native writes use the existing mutation and refused/failed-call owners: a pending mutation, a settled write after a green check, or a check overlapping a write prevents that green from suppressing the cached observation. A new check after settled writes can establish new evidence; refused writes and nonmutating reads do not erase a valid receipt.

### Shared framing is not visibility

The old visibility predicate matched only the first 80 characters of the first line. Different check blocks share the same long preamble, so an unrelated finding could falsely establish visibility and suppress the authoritative finding's reattachment. Only the complete offered evidence now establishes its own visibility. If an alternate rendering is not an exact copy, uncertainty cannot suppress the copy; ordinary final-wire deduplication handles actual repeated bytes. A stalled-work lifecycle regression proves that unrelated visible framing no longer withholds reattachment, without another author call.

### Historical failure is not current failure

`_gate_notes` previously called cached failures “currently FAILING” even after `gate_fresh` became false. It now preserves their exact findings under an explicitly historical label when current freshness is not established. This proves neither repair nor continuing failure. Completion remains unverified without current evidence; fresh red results retain their current-failure wording. This repairs an upstream evidence assertion, not the critic's grounding or fail-closed contract.
