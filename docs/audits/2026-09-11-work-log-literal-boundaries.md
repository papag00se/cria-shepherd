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
