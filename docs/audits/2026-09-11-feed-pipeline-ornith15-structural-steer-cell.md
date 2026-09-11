# Feed-pipeline Ornith 1.5 cell — structural-steer outcome

## Scope

This records the independently judged outcome of the fresh level-5
`feed-pipeline-java_ornith15_codex_poff_1789123549` cell.  It launched at
`d91666acf6ddd33ddc7bd4f800868b0c25b87f63` after the narrowly tested
structural-refusal recovery change.  The task, model, harness, planner, sampling,
and grading remained unchanged.  The captured-response control-flow regression is
not usefulness evidence, and this documentation unit changes no runtime behavior
or service state.

## Independent checkpoint and final record

- 30 active minutes: **20%**, `stalled`.
- Final independent outcome: **20%**.
- The runner ended at 04:25:24 with terminal `milestone-stalled-30min` after 73
  calls; the parent recorded the final result in `suite/results/results.jsonl`.

The independent final verdict and evidence are retained outside the repository at
`/tmp/ornith-feed-structural-final-verdict.json` and
`/tmp/ornith-feed-structural-final-evidence.md`.  The frozen archive is
`/home/jesse/.cria/suite/feed-pipeline-java_ornith15_codex_poff_1789123549/workspace`.

The final `Importer.java` and `pom.xml` are byte-identical to the 30-minute frozen
source.  In the independent private copy, `mvn -q compile` failed at
`Importer.java:225`: `combine` requires `(Map<String,Double>, Map<String,Long>,
long, Partial)` but the delivered call supplies two `Partial` values.  Therefore no
candidate runtime map, determinism, malformed-input, performance, or parallelism
result is credited.  Cached artifacts are not after-state evidence, and `REVIEW.md`
is absent.

## Interpretation boundary

This 20% result is not a causal benefit or harm claim for `d91666a`.  The run's
launch note expressly limits its antecedent evidence to the captured-response
control-flow regression, and the independent verdict finds the delivered candidate
unexecutable.  This note does not infer a cause for the failed task, claim a
behavioral benefit, or change the earlier runs' scores.

## Subsequent walk and delivery closure

The repeated-prompt readers have finished all 63 materialized chunks, and the
independent paired-return audits now close source delivery through each actual
EOF. The audit chain under `/tmp/feedwalk-1789123549/delivery-audit/` is:
`first17`, `completed18-20`, `completed21-22`, `completed23-24`, `completed25`,
`completed26-27`, `completed28-29`, `completed30-32`, and `secondhalf`.

Closure includes explicit recovery, not retrospective credit for unsupported
reader claims. The initial 026–027 audit found discontinuous historical proof for
026 and none for 027; separate uncapped returns recovered the missing spans.
Rounded requested page ends were corrected to actual source extents, and the
reassignment overlap at 028:1–50 counts only once. Initial manifests and capped
returns remain preserved. Source counts, empty probes above a requested bound,
and reader ledgers alone do not prove delivery.

The semantic synthesis is retained at
`/tmp/feedwalk-1789123549/consolidated-findings.md`; separate reviews are
`runtime-root-cause-review.md` and `semantic-26-27-cross-review.md` in the same
directory. Their conclusions remain bounded by original event and revision
provenance. An applied edit is not a verified working repair, and a trailing
success-looking pipeline marker does not override compiler diagnostics.

Delivery closure does not itself establish comprehension, semantic correctness,
a shared-owner defect, or usefulness. No new behavior change, replay, or candidate
adoption follows from this documentation update. The independent final outcome
above is unchanged, and the campaign's strictly-above-75% target remains unmet.
