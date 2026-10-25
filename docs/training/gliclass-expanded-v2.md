# GLiClass expanded fit v2

## Operator authorization and scope

The operator explicitly requests a new GLiClass fit using the admitted real Go, Node and Rust cases alongside the original Java, Python and Ruby training cases, plus at least 100 varied synthetic TRAIN cases that survive independent admission. The operator permits extrapolation from admitted real examples. Train and test; preserve prior results, retain unresolved quarantines, disclose training exposure, and do not deploy. The RTX 3090 remains the approved training device; the RTX 3080 and production services are untouched.

Operative artifacts live in `/home/jesse/.cria/training/gliclass-v4-edge-expanded-v2/`. This is a new run, not an overwrite or relabeling of [v1](gliclass-v4-edge.md). The original 514 TRAIN plus 37 DEV and 93 historical diagnostic real cases become 644 real TRAIN examples in v2. Therefore the old 130-case denominator is **TRAIN replay for v2**, never independent evaluation. Original v1 standings and source files remain unchanged. The older 94 real and 61 synthetic quarantine entries are not released, and the earlier 11 qualified synthetics are not silently added to this experiment.

## Generation and admission

Three isolated authors propose 64 new TRAIN candidates each, extrapolating policy boundary phenomena from complete admitted real cases across six task languages. Authors have separate novel-domain assignments; proposals include complete inputs, proposed labels, rationales, explicit real-parent IDs and contrast-group ancestry. These are proposals, not admissions. A separate author is assigned an entire TEST-only batch **before generation**. That author sees only the two policies, not real examples, training proposals, fitted models or predictions. Its unrelated application domains and sibling groups remain reserved, never backfilled into training.

Sonnet launches through the Claude provider could not authenticate and did no authoring; permitted Sol sessions replaced those authors. Following the operator's routing correction, the two independent reviewers use Sonnet **through Pi**. Existing author sessions were not stopped. All successful author/reviewer identities and actual packets are retained with the experiment. Labels are assistant-reviewed, **not human gold**. Separate isolated reviewers receive complete inputs and policy in a dedicated input directory, with opaque review IDs hiding author/batch/sibling/label cues, and are blinded to author labels/rationales, ancestry and one another's decisions. IDs are mapped back only after complete independent review; the full-input hashes and literal evidence remain unchanged. Reviews bind the complete canonical input hash and a literal supporting span, with explicit ambiguity and local-use holds. Two independent review decisions and the original author's label must all agree. Disagreement, UNKNOWN, reviewer holds, missing approval and duplicate complete inputs stay excluded. Exact-input exclusion also covers all 738 original real candidates, including the 94 unresolved holds, and all 72 previous seed inputs, including the 61 holds and 11 qualified-but-unused cases; a new synthetic ID cannot resurrect an old excluded input. No label is revised to meet the quota. If fewer than 100 TRAIN cases pass, author and independently review additional TRAIN batches without releasing holds or consuming the reserved test batch.

`suite/gliclass_expand.py` reuses the existing canonical input, review validation and disagreement logic in `training_admit`; it does not infer labels from words. Exact source joins restore task/language metadata for former held-out real exports whose `task` was null; neither the complete input nor label is changed. Hashes establish identity, not semantic independence. Reviewers also inspect usefulness, artificial repetition, accidental sensitive content and near-duplicate boundaries.

## Frozen fit and tests

Use the original pretrained revision `885af1af8a07edf4ed34df83ca0d995ed8201283`, not v1 fine-tuned weights. Retain the v1 fixed recipe: seed 17, 12 epochs, final checkpoint only, learning rate 5e-6, actual-divisor accumulation of 16 single-row microbatches, FP32 master weights, BF16 native training graph, FP32 CE+Brier objective, native option-order alternation, no TF32, and unchanged dropout. The eight-case learning/gradient gate runs before a fresh pretrained reset. No held-target tuning, seed/checkpoint matrix, precision substitutions, clipping, chunk voting or private reasoning targets.

Task/head/label balancing remains unchanged. All newly authored synthetic scenarios share one explicitly declared `synthetic-policy-boundaries` objective stratum; scenario groups are retained for leakage checks but are **not** each promoted into their own high-weight task. All six real task identities come from the canonical source join.

The expansion changes both real-data coverage and synthetic augmentation, so it is not an ablation isolating the effect of synthetics alone.

Training and inference now take cohort sizes from the hash-bound producer contract rather than hard-coded historical 514/130 values. The shared loader refuses changed bytes, wrong counts, duplicate IDs, mislabeled exposure partitions and cross-cohort identity/group/input-hash overlap. Regression tests establish the original limit and prove the expanded-cohort/held-exposure behavior. Whole native inputs must fit unchanged before inference.

Test the final native FP32 reference and actual CPU INT4 artifact, using the existing symmetric block-128 RTN recipe and stable native ONNX export. Check full native/export fidelity and every external shard hash, actual required bundle bytes (<250,000,000), per-family/class agreement, unsafe approvals, false blocks, native-versus-INT4 choices and observed CPU timing. Compare v1 and v2 on the same new admitted synthetic test cases; this remains a **synthetic challenge diagnostic**, not a fresh real-world or human-gold benchmark. Report the old 130 cases separately as exposed training replay. No task usefulness improvement or production serving admission follows from these tests.

## Completed execution and measured results

Both independent Sonnet-through-Pi reviews completed for all 256 new inputs. Each input's author and both blind reviewers agree; all **192 synthetic TRAIN cases** and **64 reserved synthetic TEST cases** passed admission. No new proposal was held, and no old quarantine was released. The training set is **836 cases: 644 admitted real plus 192 newly reviewed synthetic**, including real Java 388, Python 69, Ruby 57, Go 37, Node 40 and Rust 53. The new synthetic training cases cover 96 paired scenario groups; the reserved challenge covers 32 paired groups, not 64 independent scenarios. Both reviewers explicitly caution that useful minimal pairs share situations and policy boundaries; this is not a diverse real-world population sample. All four labels have 48 synthetic TRAIN and 16 synthetic TEST cases.

The frozen contract SHA256 is `3ee91291ebf7da6a5a5ca73e5239f87fbc24ad1a34ba988d1a59ae8681b6a01b`; `admission.json`, `proposal-receipt.json`, original author files, opaque blind packets and both hash/span-bound review files retain the complete source chain. A separate pre-launch source review found the original author IDs exposed grouping/batch cues; this was fixed with opaque IDs before either semantic review began, and exact-input exclusion was expanded to prevent resurrecting earlier holds.

The complete repository suite passed **11,047 tests with 238 skipped** in 432.73 seconds; actual native Torch/ONNX/ORT focused coverage passed **41 tests**. The expanded-cohort, opaque-blinding, exclusion and synthetic-admission regressions fail before their implementations and pass afterward. Source hashes bind these runs in `tests-source.json`; the earlier 11,045-test run and 39-test native run are retained separately. Training, export, CPU assessment and final frozen-input integrity checks all completed successfully (`pipeline.exit`, `train.exit`, `baseline.exit`, `finalize.exit` and `evaluation.exit` are 0). No model is deployed.

The final fit ran 12 epochs and 636 full-fit updates in **5,567.14 seconds** (92.79 minutes, excluding the mechanical preflight), from the original pretrained reset. The eight-case integrity gate passed 8/8 with all active gradients present/finite and changes witnessed in the encoder, text/class projectors, scorer and calibrator. Peak reserved GPU memory was 21,346,910,208 bytes, below the declared 22 GiB ceiling. The final native BF16 training replay matched 836/836; that is training fit, not independent accuracy.

### Same reserved synthetic challenge, actual CPU INT4

| Question | v1 matched | Expanded v2 matched | Unsafe approvals v1 → v2 | False blocks v1 → v2 |
|---|---:|---:|---:|---:|
| Retrospective versus plan | 27/32 | 32/32 | 5 → 0 | 0 → 0 |
| Describes versus dictates | 27/32 | 32/32 | 3 → 0 | 2 → 0 |
| **Total** | **54/64 (84.4%)** | **64/64 (100%)** | **8 → 0** | **2 → 0** |

The paired comparison corrects ten errors and introduces none on these 64 cases. Both artifacts also matched 54/64 and 64/64 respectively with the native FP32 reference, although v1's native-versus-INT4 choices agree on only 62/64 cases. Expanded v2's native and INT4 choices agree on **all 194 assessed inputs**: 64 reserved synthetic cases plus 130 exposed real training replays. All assessed native FP32 versus normalized ONNX logits passed the unchanged rtol/atol 0.0002 fidelity check. The exporter also passed the original tiny-eight-plus-longest-input-per-head gate. No post-hoc recipe, label, threshold, seed, precision, checkpoint or test-batch changes were made.

A complete inspected example is `expand2-test-006`: the briefing says, “For the continuation, treat the room as a separately reserved resource and reject an allocation whenever its interval intersects an existing room reservation.” That is new repair advice, not merely the recorded state of the fictional room allocator. v1 returned RETROSPECTIVE in both native and INT4; expanded v2 returned PLAN in both. Complete rendered policies, inputs, token IDs, native/ONNX/INT4 logits and choices are retained in `assessment/{v1,v2}/results.jsonl`; no private reasoning exists for these native encoder calls.

### Exposure, artifact and serving limits

The former 130 real held cases now match **130/130** in both v2 native and INT4, but **every one was used in v2 training**. This number is a separate TRAIN replay and is never added to the 64-case challenge denominator. There is still no fresh human-gold real benchmark, no full-session Java counterfactual, and no measured task-usefulness improvement. The perfect challenge score is limited to 32 paired synthetic groups with assistant-reviewed labels and shared policy/generator/reviewer factors; it is not a claim of universal correctness or zero real-world unsafe approvals.

The final required INT4 graph and external weight shard total **239,829,455 bytes**, below 250,000,000. Artifact directory: `train-001/export-001/int4/`. Files:

- `model.onnx`: 3,202,383 bytes, SHA256 `1c5264a03aee24a79bf6cd1bdc8dd88c8e90f6fa1416959af008f99a4e880fb2`.
- `model.onnx.data`: 236,627,072 bytes, SHA256 `6f706024b8f6d00ac0942da84be01f21c41ad3355cba31300daf3386c476cc7c`.
- Final native weights SHA256: `fb264ea9355debf86adfe063369deec979dcc92236f63c44dc8d66fa3af062c0`.

Observed v2 CPU INT4 inference on the 64 challenge cases: mean 0.6020 s, median 0.5738 s, nearest-rank p95 0.8939 s. The 130 exposed real replays have mean 1.1143 s, median 0.9526 s, p95 2.4253 s. These use ORT CPUExecutionProvider with six intra-op/one inter-op threads, exclude tokenization/model load/native-reference evaluation, and do not establish production RSS, end-to-end latency or stdlib/in-process serving admission.

### Evidence and preservation

Training source is commit `0931a768` (following `0ef3b2cf`), bound by `train-001/training-source.json` and the frozen contract. `assessment.json`, `assessment-source.json`, `train-001/trained.json`, `train-001/export-001/{download.json,quantized.json,trained/completed.json}`, and `integrity-final.json` own the measurements. v1 assessment calls SHA256: `078ef1d2af45f702705ab160aa45928ea7ac278ac4ce4b30aef77683fe59e5e7`; v2 assessment calls SHA256: `b943509c1710ffc224e67d0d4c409baaf1c00f0ee7c6a1640e2665944477df60`.

Prior models/results and the original 94 real/61 synthetic holds remain intact. The final check verified every frozen source/input hash unchanged. Native weights, successful FP32/INT4 artifacts, authors' proposals, both blind reviews and actual inference/training call records remain available. Only the redundant rolling optimizer checkpoint is retired after final native/export validation. Production configuration/services, the RTX 3080 and planner settings were not changed.
