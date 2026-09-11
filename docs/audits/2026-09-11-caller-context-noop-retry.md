# Caller context no-op retry — tested landing record

## Scope

This is the narrow companion to the [context-shaping overflow re-trim and
retry mechanism](../heuristic-assists.md#context-shaping--what-the-model-sees-and-how-much).
It suppresses one immediate compactor reasoning-off retry only when the wire owner has already
parsed a context rejection, refused its unchanged inner refit, and then finds the caller retry's
normal post-`_prep` bytes unchanged. It does not classify HTTP status/text at the caller, deduplicate
requests globally, alter capacity/reserve/floor/serialization, or decide whether a summary is useful.

## Historical incident and retained limits

The `2026-09-10` CALL0115 sequence establishes this chronology:

1. `0115-compactor` was an outer POST. Its parsed context event recorded `real=54068`,
   `est=47603`, and `n_ctx=49152`.
2. `0116-compactor` was an unsent inner refit: `upstream.refit_no_change` at 197044 bytes.
3. `0117-compactor-noreason` was a second outer POST with the same prepared body.
4. `0118-compactor-noreason` was its unsent inner refit.

The archive retains parsed capture-body objects, not original `Request.data`; it also lacks the
original HTTP-error body, headers, message, response framing, and response capture. Consequently,
neither the repair nor its replay claims original raw-wire equality or an original backend response.

## Repair and controls

`Upstream._open_with_refit` alone creates typed inner no-change provenance after normal preparation.
`loop.summarize` carries it only to its immediate forced-off pass. The same wire owner strips the
private hint, prepares normally, and suppresses only equal final bytes. The unavailable compactor
result leaves `_summarised_evidence`'s complete source in place.

The prospective baseline exercised both real evidence-builder call sites. On clean `fc35c8c`, the
desired one-outer-POST assertions were genuinely red (`2 failed, 6 controls passed`), rather than
failing through a missing helper. Candidate controls are green: empty completion, transient error,
non-context 400, changed reasoning-off wire, whole-evidence retention, and the two builder paths.
The durable same-role state-change regression uses real `summarize(..., evidence_blocks=...)` and
normal floor learning: its three final wires are distinct (`outer`, `inner-refit`, `outer-retry`) and
the successful outer retry remains permitted. The focused candidate run recorded 13 passed tests and
3 subtests; the full suite recorded 4863 passed, 5 skipped, and 3217 subtests passed.

## Offline Phase A

The independently reviewed r2 artifacts at
`/tmp/feedwalk-1789025662/caller-context-noop-retry-candidate/phase-a-offline-0115-20260911/`
verified the reviewed diff fingerprint
`60797aa81fb5838e0cdf7c8d0f304314c95ba5ff952755131e2780033de56a40` atop
`fc35c8c5b6936906b28fcb0bf9a6868d6a11d77e`.

Each arm entered the real `_summarised_evidence → summarize → Role.apply → chat_watched →
_open_with_refit → _prep` chain with only `urlopen` replaced. A write-ahead unsent preflight required
field equality to the retained `0115.body`, absent internal keys, and the same 197044-byte final wire
before the fake fixture ran. The fixture HTTP 400 contains only the retained parsed token/window facts
and is labeled reconstructed.

The r2 baseline made two capped fake sends; the candidate made one. Both retained the whole source
and adopted no summary. The write-ahead failure control stopped before a fake send/error. The initial
r1 artifacts are preserved; r2 additionally durably retains the exact reconstructed fixture-error
payload before the normal parser consumes it, and only r2 was independently reviewed for this landing.

This is an offline reconstructed-transport control-flow result only. It does not establish current
endpoint capacity, historical raw-wire or error-byte identity, model-summary fidelity, usefulness, or
campaign benefit. Live Phase B remains unauthorized by this record.
