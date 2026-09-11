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

The repeated-prompt walk is **not complete**.  Its 63 materialized chunks are an
assignment boundary rather than a read/comprehension claim: reader20 was assigned
001–032, and reader19 is reserved for 033–063.  Their completion and any findings
remain separate evidence work.
