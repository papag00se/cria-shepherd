# Work-log literal boundaries — isolated implementation evidence

## Scope

This unit changes only `loop._work_log`'s two decoded textual-field boundaries:

- tool-call `function.arguments` is no longer stripped; and
- tool-result `content` is no longer stripped.

For a refused call whose literal argument contains CR or LF, the existing call-only denial label
is rendered before that literal argument.  This leaves the label on the physical `$` header.  The
label is otherwise rendered in its former post-argument position.  No refusal detector, pairing
rule, prompt, deduplicator, context floor, summary policy, or wire preparation changed.

The direct production-owner regressions in `tests/test_denied_calls.py` cover exact decoded
arguments/results, CRLF and terminal LF, a whitespace-only result, checker visibility, structured
call-ID denial attribution, ordinary framing, evidence readers, and byte-identical action folding.
They also put a non-refused multiline payload that resembles a denial header next to a real refusal:
appearance in tool text never grants an attribution label.

## Test evidence

The six new direct owner tests were added before changing `loop.py`.  On the baseline they produced
five failures (exact refused fields/frame, checker boundary, label-like real payload, downstream
evidence/dedup, and whitespace-only result); the ordinary-frame control passed.  After the narrow
owner patch, `python -m pytest tests/test_denied_calls.py -q` reported `31 passed, 10 subtests
passed`.  The isolated full offline suite then reported `4850 passed, 5 skipped, 3194 subtests
passed`.

## Archived CALL0115 versus a future producer output

The archived compactor request is the source of truth for an old replay.  Its `0115-compactor.json`
body was decoded as `Path.read_bytes().decode("utf-8")`, then the user source string was encoded
back to UTF-8 for comparison:

| body | UTF-8 bytes | SHA-256 |
| --- | ---: | --- |
| archived CALL0115 source | 189899 | `cbd4357a285fb5ced87d30398de6aeaf171df3754be68affc3ed77a55e70a1fd` |

The previously preserved, no-executor reconstruction at
`/tmp/feedwalk-1789025662/reconstructed-worklog.txt` is byte-identical to that archived source.
That equality is the before-side provenance proof; the archive itself remains unchanged.

For this isolated unit only, the same captured inbound history was rematerialized through the
patched owner under mocks that reject network and subprocess execution.  It produced this separate
**COUNTERFACTUAL FUTURE PRODUCER OUTPUT**:

| body | UTF-8 bytes | SHA-256 | difference from archived source |
| --- | ---: | --- | --- |
| counterfactual patched producer output | 189981 | `9f42e7b589b1a7ae7eb367425fc4b172852ad7e00e2acb230658c1ae3a3eca7f` | +82 bytes |

Byte alignment found 64 insertion hunks, with 79 LF bytes and 3 CR bytes inserted; it found no
removed or replaced archived-source bytes.  This particular reconstructed history did not exercise
the refused-multiline-argument framing branch; that branch is covered by the direct regression.

The counterfactual output was not sent to an endpoint, tokenized, summarized, or judged.  It is a
changed future prompt, **not** a byte-identical CALL0115 replay and not evidence about model
behavior or usefulness.  Any replay of the archived call must continue to use the 189899-byte
archived source.  Any future prompt using the corrected producer needs its own normal final-wire
admission and separate model evaluation.

## Capacity and fidelity boundary

The 82 additional bytes demonstrate why this unit makes no capacity claim.  Retaining literal
boundaries can increase a work log and can prevent blocks that are no longer byte-identical from
folding.  The existing deduplicator/context-floor/labelled-summary owners retain that responsibility;
this patch neither clips content nor supplies an estimate, window, reserve, fallback, or endpoint
token count.  No model API call occurred in this unit, so summary fidelity and endpoint acceptance
remain unavailable rather than assumed.

## Captured 0036 replacement: transport evidence, not a benefit claim

The first scratch changed-input attempt at
`/tmp/feedwalk-1789025662/0036-changed-input-sse-N6hR4V/` remains
**sent-response-unavailable**.  It entered the one POST but failed when its old post-response
artifact creation rejected the already-created empty `mktemp -d` directory.  The actual transmitted
body and response were not retained.  The later
`/tmp/feedwalk-1789025662/0036-preflight-recovered-cfRv0n/` bundle is explicitly a no-POST recovery
preflight, not evidence of that first transmitted request.

After the scratch SSE capture boundary underwent independent review, one distinct replacement was
sent using the normal selected reasoner `Upstream`/`Role`, the archived 0036 model/settings
(`ornith_1_5_9b_q6`, streaming usage, `max_tokens=8192`, no tools), and the counterfactual patched
producer source.  Its durable pre-send manifest and exact request are at:

- `/tmp/feedwalk-1789025662/0036-replacement-sse-4LGlIT/request-manifest.json`
- `/tmp/feedwalk-1789025662/0036-replacement-sse-4LGlIT/final-wire.json`

Normal endpoint discovery supplied `n_ctx=49152`; the normal owner reserve was 8192.  Density was
recorded as `1.8` with provenance **default-unmeasured**, not as a fit proof.  The response stream
was retained incrementally at `response.sse`; it ended `stop` with `[DONE]`, 4474 SSE events, and
backend usage 16690 prompt + 2234 completion = 18924 total tokens.  This is evidence only for one
durably captured replacement transport outcome.  It is not evidence for the lost first response,
generic endpoint admission, task completion, or usefulness.

The changed source is 56842 bytes rather than the archived 56802 bytes.  Its materialized diff is
limited to preservation of literal result boundaries (blank-line/CRLF bytes); it removes no action,
tool result, or error.  See
`/tmp/feedwalk-1789025662/0036-replacement-sse-4LGlIT/source.diff`.

### Replacement summary rejected

The replacement's model-made summary is quarantined and must not become a compaction/adoption
input.  Its source records the Maven-search command as still running with session ID `34898` and no
final result, while the generated summary says that the search “returned empty.”  It also changes
the recorded Maven-cache state (for example, it calls `com/opencsv/opencsv:5.9.3` a real JAR even
though the source records only `.jar.lastUpdated`) and omits the distinct `web_search` result and
its saved reference path.  These are defects in this generated summary, not evidence that the
byte-preservation repair caused them.

Accordingly this audited unit lands solely as a decoded-field byte-preservation correctness repair.
It makes **no usefulness benefit claim** and does not authorize summary adoption, a retry, a refit,
or any broader history/compaction change.
