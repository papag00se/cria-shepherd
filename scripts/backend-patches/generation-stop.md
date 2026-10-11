# V4: authoritative generation stop and harness action boundary

This is separate from the V3 framing/error-identity unit and the semantic false
completion investigation. Status remains **NOT_READY**; the Java campaign stays
paused. This unit runs only CPU compilation, parser tests and fake upstreams.
No model, GPU, live service/config/runtime, campaign or merge change is included.

Apply pinned revision `8345f333951c661d166b00e6f9362e553768f292` patches in order:
serial, independent named, unchanged V3 no-action, then `8345-generation-stop.patch`.
Export into a new `/tmp/phi4-no-action-source-v4`, configure/build a matching
`/tmp/phi4-no-action-build-v4` with the README's CPU options and all three native
parser targets. Do not reuse or change any V1–V3 directory or parent candidate.

## Native facts and final owner

Stop causes are assigned at the actual native producers: context capacity,
output budget, time, indentation, EOS and stop word. Context shifting is recorded
separately; neither truncated nor token-usage arithmetic identifies stop cause.
Native stop precedence is preserved. The final result captures full sampled
bytes and parser input before streamed final content is emptied or native stop
filtering removes bytes. Evidence distinguishes sampled raw hex from parser-input
hex; both are complete. No usage arithmetic, error-text or model-name classifier
is added.

The active protocol's actual final.update owns completion semantics. Valid LIMIT
prefixes are parsed as partial input, keeping reasoning separate and unfinished
atomic answers withheld. Buffered B removes **all** calls, including a complete
valid call envelope exactly at LIMIT. Explicit parsed/withheld state prevents an
empty answer or withheld reply from falling back to raw Output text. The response
finishes length and carries full raw evidence plus structured call prefixes.

Streamed LIMIT freezes the already-published message. No new calls, argument
healing, changed argument bytes, closing delimiters or retractions can appear in
the terminal diff. Unsent tails are evidence only. Native real-call argument
streaming remains intact; the frontend action quarantine is a separate boundary.

EOS/WORD remain strict completed parses. Structurally invalid/off-menu LIMIT
prefixes are also typed non-acting errors, preserving the actual LIMIT cause;
they never become successful parses or get relabeled EOS. The typed error travels
through the native HTTP and SSE catches with its reason and complete raw bytes.
Ordinary disabled-protocol behavior and mapper errors stay unchanged; untrusted
private parser tags remain security errors. Genuine request 400s and transport
500s retain their existing treatment.

The generic response extension `generation_evidence` carries these facts. Native
assistant-content authority is emitted only for a supported privately activated
parser. Public request JSON, caller headers and raw completions cannot activate
it. Canonical answer.message may contain tool-looking JSON/XML; it remains exact
assistant content and is never recovered, lowered or executed as a call.

## Cria wire and driver policy

One generation-evidence owner withholds incomplete calls before recovery/lowering
and buffers action deltas until explicit successful terminal status. This applies
to Chat JSON/SSE and Responses JSON/SSE, driver and proxy, across L0–L5. Length
stays incomplete; Responses uses response.incomplete, not completed function-call
items or response.completed. Ordinary content/reasoning remain intact and uncapped.
Evidence is opaque data, not another action menu or instruction authority. Native
real-call bytes still stream normally upstream; the harness receives action
fragments only after a completed terminal decision.

Typed malformed responses retain their structured dictionaries through actual
buffered/SSE collection and the chain. They bypass same-body buffered re-ask,
availability classification and failover. Generic transport policy is unchanged.
Proxy routes add no continuation loop.

A watched stream that reaches EOF without a terminal finish and without an
actually recorded local abort raises an ordinary structured transport
`UpstreamError` of type `incomplete_stream_error`. DONE, valid arguments, content
and an installed watcher do not supply a stop event. Full wire hex, collected
content/reasoning and action prefixes are captured before the error is thrown.
There is no same-body buffered re-ask for this EOF case; the existing transport
chain policy remains in charge. Explicit generic SSE errors retain their existing
once-buffered transport behavior. A recorded local abort retains its actual
event and rumination finish, withholds all calls, and produces incomplete
Responses output without inventing a native LIMIT/cause.

The real driver branches on the typed error before call-less completion handling.
It reuses the existing refusal counter and renudge path, with unchanged bounds.
A brief factual prompt-file notice changes each next coder request; the full
original error remains in session/output evidence and is not pasted into model
instructions. Even parser diagnostics stay in evidence: they may quote generated
values, so the notice states only the error and pending-task facts. At the existing
bound the original typed error propagates, the task
stays pending, and no completion gate can approve that error. Existing incremental
write steering may read the structured call prefix; reasoning/answer-only notices
do not invent a cut call or a write. No new retry loop, reserve/refit, calibration,
output cap or semantic exact-content assist is added.

After those existing guards, the shared coder/public drive boundary transfers any
still-incomplete result directly to the caller. Every completion judge/probe is
bypassed, including nested coder calls. The original noncompleted status and full
evidence return with the task pending, with no extra retry or counter change.
An existing guard retry that yields a genuinely complete acting result proceeds
normally. Human refusal notes also state incomplete/actions-withheld facts rather
than inventing a cut call or a token-budget cause.

The protected-input preflight still raises exactly
`UpstreamError("Measured input cannot fit the context window without losing protected input")`
with zero generation POSTs.

## CPU validation and ABI

Run all native parser suites, then from the cria checkout:

```sh
LOCALAI_PROBE_SOURCE=/tmp/phi4-no-action-source-v4 \
LOCALAI_PROBE_LIBRARY=/tmp/phi4-no-action-build-v4/bin \
  python -m pytest
```

Set `LOCALAI_PROBE_RECEIPTS` and `GENERATION_WIRE_RECEIPTS` to new evidence
folders to preserve every native/wire input and full output. Native fixtures call
the actual final owner and partial serializers, with every UTF-8 byte cut,
complete envelopes at LIMIT, unsent tails, both prefill variants and actual native
diffs. Wire tests use real HTTP handlers, fake upstreams and executor spies;
positive complete-call controls demonstrate actual release. The low-rung driver
branch test injects a collected-output driver collaborator; separate real driver
tests prove error → notice → changed request → action, and pending at the bound.
The EOF handler matrix uses the real watched collector for buffered proxy
handlers as a fixture collaborator; it does not change production routing or
enable a driver at lower levels. Native LIMIT cases and ordinary transport EOF
cases remain distinct. The pinned sandboxed client fixture preserves the exact
malformed legacy completed-history literal and `_unparsed` roundtrip separately
from an actual length reply. That length case proves response.incomplete, absent
function items/history/compaction and an absent workspace write marker for valid
JSON arguments. It makes no blanket client retry/continuation claim.

Full source/build/probe/results, before/after failures and exact historical
19-failure comparisons live in
`~/.cria/validation/localai-phi4-install/no-action-native-v4/`.
`TEST-REPAIR.md` classifies changed expectations and fixture failures; incident
inputs and all unrelated historical tests remain preserved.

Rebuild a matching server executable, common library and server-implementation
library together. These C++ changes require the matching private build; never
pair old helpers or servers with a new library. Parent must preserve the original
same-revision CUDA/core libraries/kernels and exclude old helper implementations,
verify the whitelist/symbols/loaded identities, and validate any separate V4
candidate. Never alter a library under a running process. CPU correctness is not
live validation, task equality/newline success or coding usefulness.
