# Targeted decision-model training

This directory records the offline data/research workstream behind the optional CPU **GLiClass v2** guards (two questions: retrospective briefing versus operative plan; description versus code dictation). Training receipts are not deployment authorization; the separately authorized runtime is documented in [serving and rollout](../system1.md). Private evidence stays under `~/.cria/training/` and `~/.cria/experiments/`.

## Where things are

- [Methodology and lineage](methodology.md): data admission, blind Pi reviews, frozen pretrained-reset fitting, native export/INT4 quantization, **how the candidate was reached** (rejected 68M Ettin, OneJev, GLiClass v1) and the process lessons. Start here.
- [Expanded GLiClass v2 fit](gliclass-expanded-v2.md): 836 training cases (644 real + 192 blind-reviewed synthetic), 64/64 on the reserved synthetic challenge versus v1's 54/64, artifact identities, exposure and serving limits.
- [Data qualification and grouped evaluation](data-preparation.md): admission, quarantines, task-group partition and the distinction between prepared intake and an actually collected fresh benchmark. **Fresh real evaluation cases: zero.**
- [Archive availability and label-coverage audit](archive-audit.md) (metadata: [archive-audit-metadata.json](archive-audit-metadata.json)); [synthetic training design](synthetic-data.md) and its [structural-check result](synthetic-validation.json) (recheck with `python -m suite.training_seed`; tests: `tests/suite_tooling/test_suite_tooling_training_guards.py`); [research and backbone comparison](research.md).
- Frozen machine inputs of the retired 68M tooling, hash-bound and not to be edited: [qualification](qualification.json), [recipe](training-recipe.json), [resource plan](resource-plan.json), [fresh-evaluation contract](fresh-evaluation.json), [problem focus](problem-focus.json).
- Offline synthetic seed: [`suite/training_data/synthetic_seed.jsonl`](../../suite/training_data/synthetic_seed.jsonl); synthetic proposals are not verified real-world labels.

## Decisions being learned

The target is one explicit question at a time: search information-need equivalence/new direction; requested-output and exact-form intent; incoming request routing; unmarked compaction intent; retrospective state versus new instructions; quoted existing text versus copyable implementation; whole-file versus fragment; and task-required execution/E2E evidence. Module/runner contract interpretation and semantic progress may follow only if their complete evidence and labels are available. A code area can qualify whether its current implementation uses inference or deterministic semantic heuristics.

Do not train away exact facts. Tool-result ownership, successful execution, fresh filesystem observations, check pairing, permission boundaries and wire integrity remain deterministic. Whole-task completion, broad summary fidelity and integration adequacy are not established by a short candidate-only classifier. A narrow supported relationship can be learned only from an explicitly sufficient evidence packet. Missing a known required input slot is a deterministic eligibility failure, not a fact the classifier should be trusted to rediscover. Keep such packet-builder controls distinct from genuinely ambiguous semantic labels; an irrelevant missing optional attachment does not automatically invalidate a candidate-only question. No training work revives removed search relevance or implicitly enables planning. A broken route, destructive input reduction or unjustified normalized-equality bypass is an upstream mechanism problem, not a reason to teach a classifier to compensate for evidence it never receives. Record such findings and quarantine affected data; production repairs remain a separately authorized, regression-tested unit.

## Evidence and labels

Physical files, structured request records, complete request/reply pairs, distinct contexts, independent scenarios and independently adjudicated gold are different quantities. Original public verdicts are proposals/provenance unless separately verified; usefulness scores do not label individual interventions. Actual model identity, suite coder identity, requested wire model and unknown identity must not be conflated.

Capture private reasoning may be read to investigate an incident. It is not an input, target, synthetic-generation source or exportable training rationale in this workstream. Keep annotations outside model inputs. Exclude secrets/PII and unresolved provenance from trainable exports until reviewed; merely hashing a record or storing it locally is not a privacy review.

## Partition before augmentation

1. Freeze source coordinates and their evidence/policy revisions; identify incomplete and active/growing records without editing them.
2. Group retries, rollup/refold descendants, shared scenario/task variants, exact copies and reviewed near-duplicates. A hash is exact identity, not semantic independence.
3. Partition groups into training, calibration/validation and real evaluation before authoring archive-derived synthetic variations. Keep task/session families together; evaluate additional model, programming-language, harness and human-language slices without pretending all these correlated axes are independent.
4. Preserve both a representative real-data evaluation set and a separate hard-boundary challenge set. Neither is used to generate training examples or choose prompts by repeatedly checking its outcomes.
5. Standalone synthetic seeds authored now are training-only proposals, with no claimed ancestry in a not-yet-created archive partition. Translations and counterfactual siblings remain in the same training group. The already inspected replay cases are exposed diagnostics, never fresh holdout.

## Training comparison

Compare supervised native classification/span heads or pretrained decision models' actual typed probability interfaces, not generated JSON or serialized-chat NLI premises. Start separate task specialists with the same frozen examples and group splits. The original smaller-encoder capacity proposal is historical and superseded by the operator's larger-model direction; the 68M candidate is rejected. An NLI-initialized ModernBERT remains a transfer-learning comparator, not an empirically established winner. Current model cards/exports and the strict final-artifact budget require verification. A nominal parameter count or Q4 filename does not certify total weight bytes, usable context, CPU compatibility, or runtime RAM. Count the learned head and all external tensors/shards too; matrix-only quantization can leave a large embedding table in ordinary precision, so parameter-count arithmetic alone cannot establish the strict below-250,000,000-byte deployment limit. Budget the actual required deployment bundle, including every distinct backbone if multiple specialists are selected; fitting each file or each specialist separately does not establish that their combined required artifacts fit. Training several comparison candidates does not imply deploying all of them.

Train with ordinary training precision, evaluate an unquantized reference, then test CPU INT8 and Q4 only as warranted. Preserve full evidence: record no-fit rather than truncation, selected snippets or chunk-voted decisions. Benchmark tokenizer normalization/special tokens, native class ordering, latency, RSS and deployed quantized errors separately. English-pretrained backbones do not acquire demonstrated multilingual capability just because translated examples were added.

Use learning curves over adjudicated training groups and separate real/synthetic ablations rather than declaring a required sample count. Measure per-class confusion and consequential false approvals, not aggregate accuracy alone. Fit any abstention/calibration policy on validation data and evaluate coverage and errors on untouched real cases; a softmax score is not calibrated confidence. If task sharing is proposed, compare against separate specialists to detect negative transfer. Shadow evaluation must precede admission authority.

## RTX 3090 handover

The operator explicitly granted clearing and training on the RTX 3090 after the frozen provisional experiment was prepared. That permission does not extend to the RTX 3080, production integration, changing datasets or selecting a different serving candidate. Availability alone remains insufficient authority for future GPU handovers. Earlier permission-pending receipts are historical; the operative authorization is recorded separately in the local execution directory.
