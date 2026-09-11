# Feed-pipeline Ornith 1.5 cell — literal-boundary outcome

## Scope

This records the independently judged outcome of the fresh, unchanged level-5
`feed-pipeline-java_ornith15_codex_poff_1789115104` cell.  Its only shipped
behavioral antecedent was the decoded work-log literal-boundary correctness repair
at `0593ff0`, documented with its replay transport evidence at `b726276`.
Those commits were live for this cell; this outcome unit changes no runtime behavior
and does not restart the service.

## Independent checkpoint and final record

- 30 active minutes: **25%**, `continue`.
- 45 active minutes: **20%**, `stalled`.
- Final independent outcome: **20%**.

The authoritative run record is the parent-recorded
`suite/results/results.jsonl` entry for `feed-pipeline-java_ornith15_codex_poff_1789115104`.
The final independent verdict and evidence are retained at
`/tmp/ornith-feed-literal-final-verdict.json` and
`/tmp/ornith-feed-literal-final-evidence.md`.

The final private copy compiled after dependency declarations, but clean and messy
runtime probes both aborted in `Importer.parseHeader` before row processing.  The
final source was byte-identical to the 45-minute source; its single-callable,
synchronous reduction and unused local reduction map also remained.  No final
candidate totals comparison, deterministic-repeat result, malformed-input runtime
result, matched 4x timing, or `REVIEW.md` can be credited.

## Interpretation boundary

This is not a causal benefit claim for `0593ff0` or `b726276`.  The cell used the
corrected work-log producer, but its independently judged 20% outcome supplies no
evidence that the literal-boundary repair improved usefulness; it is a
decoded-field correctness repair only.  The complete repeated-prompt walk remains
ongoing in separate reader assignments, so this note does not treat the walk as
complete or replace its source-level findings.
