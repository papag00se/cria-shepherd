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

### A refusal needs its own branch evidence

A command's stdout, a file's bytes and a filename can quote `⟦ctx:denied⟧`, an edit-failure marker, or even the current call's receipt. A receipt correlates a result with its call; it is neither a secret nor proof that quoted text came from the lowering. Authority comes from producer-declared positions, not searching for a marker.

`resultpacket` owns the lowered-result protocol. The call's existing sentinel must be its leading producer header, with a receipt recomputed from that call's identifier and canonical original arguments. Its program prints one ASCII JSON record at output offset zero, after the harness's envelope. The record declares `ran`, `refused`, `unapplied`, `landed` or `uncertain`. A second survey record is consumed only when the call's own declaration permits it, and only at the immediately following position. A valid first record stands when that optional survey is missing or cut. Nothing resynchronizes by searching later output.

Whole and ranged reads, including the read returned instead of an unread overwrite, carry their original returned bytes inside the record with length and SHA-256. The lossless encoding survives a PTY's newline conversion; exact text-cache credit additionally requires valid UTF-8 and the declared returned span, not a substring found elsewhere in a refusal. Empty and whitespace-only reads are observations too. Edit windows, ordering flags, removal facts, unapplied-edit reports and stored-file facts are typed producer fields, never tags rediscovered in a file or page's text. Native shell commands are not wrapped to manufacture these facts.

`writeproxy.represent_inbound` validates the record and preserves the opaque body and tail. Malformed or cut records leave the received bytes visible and the result unknown; they are not replaced by a short notice or rescued by a legacy wording match. Client-supplied internal hints are overwritten, and the resulting hints are stripped at the final wire. Tool-role history/indicator text is not stripped as if it were the assistant's own prose. These are protocol and correlation checks, not containment or a security boundary against the harness.

All consumers use `denial`'s shared pairing and result owners. Missing evidence, an orphan or out-of-order result, multiple results, or an ambiguous reused identifier cannot establish that a call never ran. Positive write claims and supersession require the shared `landed` fact: a later unanswered or uncertain write does not turn a possible replacement into a confirmed one. Histories stored before the protocol remain unknown. A refused write can still return genuine read evidence; the write outcome does not erase the separately verified body.

### Historical writes require file identity and proven completion order

Compaction keeps three outcomes distinct: proven landed, proven unlanded, and unknown. Unknown evidence retains the payload without a refused, current-disk or superseded claim. A later proven whole-file replacement and a later proven partial edit receive different historical wording.

A paired reply alone is not proof of completion: an asynchronous process can still be running. Both focus trimming and compaction use the shared terminal-position owner, backed only by the authoritative landed/unlanded facts and strict pairing. A replacement establishes ordering only after the earlier call's terminal result and before the later dispatch. Overlapping calls are not ordered by their positions within a batch or by dispatch order; unresolved earlier work also prevents calling a later write current.

File-identity candidates come from every observed write target, independently of whether its mutation succeeded. Excluding an unknown absolute target can falsely resolve a relative spelling and delete another file's only recorded content. Ambiguous aliases withhold claims rather than establish different files. Reused identifiers, duplicate results and unanswered calls cannot authorize removal through an identifier-wide deletion set. Genuine resolved, terminally ordered whole replacements still permit the existing historical reduction; final settlement verifies the retained replacement pair rather than inventing missing identity evidence.

### Fetch observations are not rendered-page markers

A paired lowered fetch carries its producer's typed fetch facts, computed directly from the parsed document or successful protocol discovery. A local file, ordinary page text or JSON key quoting an HTTP header or endpoint marker cannot create a fetched-source fact. Native fetch results remain visible and unwrapped, but freeform headers in them do not populate this ledger. The HTTP GET status and a successfully observed MCP/GraphQL surface are separate facts: a real GET 405 remains 405 even when a subsequent protocol exchange succeeds. Research credit, remembered-source merging and answered/failed rendering consume the same observed-success rule rather than discarding that protocol observation or reparsing display text.

### A verified spool still needs declared internal boundaries

The existing gate transport verifies the spool's size and SHA-256, but checker output can quote a cleanup header, survey or another check's section header. The worker therefore declares checker/cleanup/survey extents and the actual section-header offsets at production. The completed transport carries those declarations to `probegate.gate_sections`, the shared splitter. Only those positions establish private reports and check sections. Raw or unproven history supplies no such facts; quoted headers remain ordinary checker output. This reuses the existing spool and executor rather than adding a native-command wrapper.

### Private cleanup preserves its allocation and completion evidence

Owned directory listings use a fresh descriptor relative to the authenticated directory, checked against its verified inode. Reusing a descriptor opened before later entries appeared produced stale listings on the tested btrfs filesystem; batch markers and gate scratch survived cleanup. Fresh listing does not prevent a writer arriving afterward: failed removal remains a real failure, not a successful cleanup claim.

Retirement exclusively holds hard links to the original certificate and any verified completion fact before removing their directory names. If directory removal fails, those same inodes are restored without overwriting another entry. A late writer therefore leaves an authenticated completed transport, and an actual second disposal can succeed. If a source name becomes foreign, missing or unreadable, the held original remains named and the error reports it; neither foreign state nor an existing hold is adopted. Batch cleanup retains its best-effort behavior and does not claim successful removal.

This is not crash recovery: process death can leave held artifacts, and a retained hold blocks another retirement with `EEXIST`. The implementation requires hard links and Linux `/proc/self/fd`. Completion facts are verified for each disposal attempt, not bound across attempts. No prefix-based garbage collection, permission widening or automatic adoption is added.

### A call that never ran is not a mutation

The grounded runaway-recovery notice uses both the gate's write registry and an after-read mutation scan. The scan previously counted a refused shell redirect as a possible mutation even after the registry had recorded the same refusal. Both now consume the shared proven-unlanded owner: a proven denied call or unapplied edit cannot invalidate a source read. Pending calls, real writes, unproven shell commands and a shell process that merely exits nonzero still count as possible mutations. This changes neither shell permissions nor the gate's freshness rules.

The canonical write registry records forwarded occurrences, not equal arguments or tool/target fingerprints. Its all-tool identifier counts are observed lower bounds, not proof of complete lifetime coverage. Once a collision has been observed, a read's result cannot settle a write with that identifier, and compaction or a fresh gate cannot make it unique again. Historical reconciliation is idempotent and cannot shrink the record. A gate taken before any forwarded reply has been recorded remains unknown. The mechanism assumes ordered call/result history and pair-preserving compaction; it cannot identify an unseen older dispatch's late result masquerading as the sole result of a new call after an incomplete restore. It does not reconstruct those missing events. Known ambiguity withholds the optional “no write occurred” claim; it does not replace fresh checks or block completion by itself.

`tests/test_a_call_that_never_ran_does_not_defeat_the_grounded_rumination_step.py` exercises the write-observation and notice paths, including mixed refused/landed calls, later edits, identifier reuse across tool classes, and compaction. Its public `Loop.drive` lifecycle forwards a write, takes a gate, then receives the proven refusal with a generation that aborts: incoming history must settle before recovery selection, without pre-settling the registry or registering a dummy dispatch. In the selected original continuation, other unproven shell commands independently prevented grounding. Repairing refusal custody alone therefore does not establish restoration of that notice or improved coding usefulness.
