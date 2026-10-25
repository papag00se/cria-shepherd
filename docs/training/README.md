# Targeted decision-model training

This is an offline data/research workstream, not a production-model integration or an authorization to train yet. It covers all available models, tasks, programming languages and harnesses, rather than the Ornith/Java replay alone. The live coder, services, campaign and planner setting are unchanged.

## Deliverables

- [Final data qualification and grouped evaluation](data-preparation.md), [machine-readable readiness](qualification.json), and [execution/evaluation preparation](execution-readiness.md): completed whole-input reviews, explicit quarantines, matched native-fit exports, and the distinction between prepared intake and an actually collected fresh benchmark.
- [Frozen first training recipe](training-recipe.json), [resource evidence](resource-plan.json), and [prospective evaluation contract](fresh-evaluation.json): pinned candidate, complete tokenization, CPU-only shape checks and collection gates—not training/GPU permission or deployment evidence.
- [Archive availability and label-coverage audit](archive-audit.md): authoritative capture/run joins, available inputs, label provenance, representative full-case readings, duplicate/lineage limits and readiness gaps.
- [Research and backbone comparison](research.md): what the cited work actually supports, what remains untested, and suitable supervised-learning candidates.
- [Synthetic training design](synthetic-data.md): policy definitions, variation/contrast families, actual seed examples, review status and leakage restrictions.
- [Main integration review](main-review.md): additional complete cross-language capture readings, independent annotation cautions, selected primary-source checks and the training-readiness boundary.
- Offline synthetic seed: [`suite/training_data/synthetic_seed.jsonl`](../../suite/training_data/synthetic_seed.jsonl). Synthetic proposals are not verified real-world labels or evaluation results.
- [Reproducible seed structural-check result](synthetic-validation.json), bound to the exact seed hash. Recheck with `python -m suite.training_seed`; focused tests: `python -m pytest tests/test_training_seed.py tests/test_training_archive_audit.py`. Neither command tokenizes, trains, runs model inference, or grants data admission.

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

Compare supervised native classification/span heads, not generated JSON or serialized-chat NLI premises. Start separate task specialists with the same frozen examples and group splits. Ettin encoder 68m and 150m are candidate capacity points; an NLI-initialized ModernBERT is a transfer-learning comparator, not an empirically established winner. Current model cards/exports and the strict final-artifact budget require verification. A nominal parameter count or Q4 filename does not certify total weight bytes, usable context, CPU compatibility, or runtime RAM. Count the learned head and all external tensors/shards too; matrix-only quantization can leave a large embedding table in ordinary precision, so parameter-count arithmetic alone cannot establish the strict below-250,000,000-byte deployment limit. Budget the actual required deployment bundle, including every distinct backbone if multiple specialists are selected; fitting each file or each specialist separately does not establish that their combined required artifacts fit. Training several comparison candidates does not imply deploying all of them.

Train with ordinary training precision, evaluate an unquantized reference, then test CPU INT8 and Q4 only as warranted. Preserve full evidence: record no-fit rather than truncation, selected snippets or chunk-voted decisions. Benchmark tokenizer normalization/special tokens, native class ordering, latency, RSS and deployed quantized errors separately. English-pretrained backbones do not acquire demonstrated multilingual capability just because translated examples were added.

Use learning curves over adjudicated training groups and separate real/synthetic ablations rather than declaring a required sample count. Measure per-class confusion and consequential false approvals, not aggregate accuracy alone. Fit any abstention/calibration policy on validation data and evaluate coverage and errors on untouched real cases; a softmax score is not calibrated confidence. If task sharing is proposed, compare against separate specialists to detect negative transfer. Shadow evaluation must precede admission authority.

## RTX 3090 handover

The operator has offered the RTX 3090 for training but explicitly retained control over clearing its current workload. Readiness means the chosen first task, reviewed training export, group split, frozen evaluation, backbone/runtime plan and resource estimate are ready. Notify the operator at that point and wait for explicit handover permission. Do not stop the live GPU process, clear memory, swap a model or start GPU training merely because the hardware is available.
