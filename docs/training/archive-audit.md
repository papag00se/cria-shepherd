# Decision-training archive audit

## Finding and admission status

The archive is substantially larger than the earlier ornith1.5_9b / Java replay, but file volume is not labeled-example volume. The strongest currently identifiable narrow-question pools are retrospective-versus-instruction and dictation-versus-description. Even these need complete-evidence extraction, policy review, privacy review and grouped partitions before training. Some apparently large pools contain almost no input diversity: **678 compaction-recognition requests contain one exact candidate text; 153 E2E-requirement requests contain six original-task texts.**

**This is an availability/provenance audit, not a training export or a readiness certificate.** No archive train/calibration/evaluation partition was created, no record was admitted, and no inference, training, GPU access, service/configuration change or campaign change was performed. An independently certified corpus-wide gold count and an independent-lineage count remain **UNKNOWN**, not zero. Previously independently reviewed replay labels exist; they are exposed diagnostics, not a newly certified dataset.

The authoritative compact companion is [`archive-audit-metadata.json`](archive-audit-metadata.json). It contains source/prompt hashes, the sparse 253-row exact-policy × suite-model × programming-language × task × harness matrix, all 15 reviewed seats, native/result metadata axes, separate nonstandard-container schemas, campaign/event references, and known inspection exposures. It contains no prompts, candidate prose, private reasoning, teacher rationales or training rows. Human language is explicitly `UNMEASURED` throughout the archive matrix.

Related work is separated by responsibility: [research/backbones](research.md), [synthetic proposals and limits](synthetic-data.md), [independent integration inspection](main-review.md), and the [workstream boundary](README.md). The synthetic seed remains 72 proposals / 18 related groups / nine families, SHA-256 `88ca1143ed1256ea9c81d35d25d9fa50cf35541ee8322f959685493f2229ff50`; it is quarantined, training-only-if-admitted, and not a substitute for real evaluation.

## 1. Frozen scope, custody and counting units

The calls/results census cutoff was **2026-10-24T17:19:34.193224Z**, integer nanoseconds `1792862374193223758`; the census completed at `2026-10-24T17:21:35.182840+00:00`. The source revision examined for current routing/policy bindings was `15867f4761660e1b7c5d6e7bbba9d06368662e5a`. This does not assign that revision to historical captures.

The frozen results source was `suite/results/results.jsonl`: **846 rows, 30,300,361 bytes**, SHA-256 `1793360256596b71db224dfb36c6366f321c2005bb470491de66fd1627c9a31c`. Preserve every attempt; neither the highest score nor the latest successful run is a labeling rule.

The offline helper [`suite/training_archive_audit.py`](../../suite/training_archive_audit.py) reads the complete regular file, checks cutoff modification/change times, uses no-follow open, checks descriptor/path identity and read completeness, then revalidates its observed inventory after traversal. Unstable, post-cutoff, malformed and unreadable evidence is counted or rejected, never silently accepted as a partial training example. It uses existing `cria.generation.incomplete`, `suite.model_names.canonical_name` and `suite.report_labels.TASK_LANGUAGES`, not a duplicate verdict parser or guessed language map. The final targeted policy pass revalidated 7,201 request files against frozen hashes and shape guards without a reported rejection. This targeted pass was not a second full-tree census.

Saved investigation artifacts live under `~/.cria/tmp/decision-training-audit/`: `availability.json`, `inventory.sqlite`, `policy-metadata.json`, `policy-references.json`, `details.json` and hash/span-only `candidate-custody-metadata.json`. Their hashes and metadata-pass source hashes are in the companion JSON. Scratch references establish provenance; they do not override the repository's closure/retention policy or authorize cleanup. No cleanup was performed.

### Physical files versus requests

| Physical suffix/schema category | Files | Bytes |
|---|---:|---:|
| Other files | 4,996 | 2,199,675,043 |
| Other JSON | 88,317 | 11,590,864,575 |
| Rendered prompts | 62,440 | 3,213,738,085 |
| Response JSON | 62,453 | 1,539,129,329 |
| Reasoning sidecars | 34,563 | 147,202,194 |
| Partial reasoning sidecars | 58 | 1,112,316 |
| Native arrays | 104 | 14,408 |
| JSONL | 19 | 306,207 |
| **Total** | **252,950** | **18,692,042,157** |

These are physical categories, not semantic families or distinct calls. The original census reported an empty exclusion/error counter; that is not a privacy, provenance or label-quality certification. Rendered/reasoning sibling-presence flags are explicitly physical-presence-only, not a claim that those sibling bytes were frozen and reviewed for every request.

| Native producer-shaped availability unit | Count |
|---|---:|
| Request records | 62,484 |
| Distinct stored `(session, seq, iso, turn)` coordinates | 62,484 |
| Distinct complete request-file SHA-256 values | 62,484 |
| Distinct exact complete structured `messages` + `tools` contexts | 59,897 |
| Requests with readable response JSON | 62,171 |
| Nominal public-channel candidates without observed incomplete/error | 53,155 |
| Native generation-incomplete records | 1,618 |
| Request-bearing directories / session IDs | 646 / 646 |

A nominal public-channel candidate means nonempty `content` or `tool_calls` and no observed generation-incomplete/error flag. It does **not** establish explicit native terminal proof, a valid classification, absence of inline private material, safety or semantic correctness. The 53,155 records include ordinary coding/authoring replies, not 53,155 decision labels. Private-only output is not a public answer. The exact-input digest includes complete structured messages and tools and ignores model/sampling; it is neither semantic deduplication nor candidate-only identity.

Stored coordinates are not authenticated distinct network dispatches. The frozen 33 event-log files contain 1,101,243 structured events, including 66,277 `upstream.dump` events referring to 66,003 paths. Exact path joins corroborate 62,464 stored request paths; 20 stored paths lack a retained dump event and 3,539 logged paths lack a current native request record. There are 189 paths with multiple dump events, 274 events beyond the first per path. These are operational custody counts, not behavior rates or proof of distinct overwritten contents. Earlier byte versions and replay/copy provenance may be unresolved; repeated events cannot be turned into additional independent examples.

### Result/archive joins and lineage evidence

- Exact request-hash snapshot joins identify **22,430** requests. Declared capture-directory joins identify another **25,801**. Directory association is weaker and does not certify candidate topic, teacher identity or one-to-one dispatch.
- **48,231** requests have a unique joined suite cell; **14,253** remain unjoined. The resolver preserves conflicting cells rather than choosing the last/best run. Same-cell multiple runs would remain multiple run IDs rather than a certified single lineage.
- There are **844 distinct result run IDs across 846 rows**, and **843 distinct declared archive paths**. The two repeated run-ID rows are not two independently established scenarios.
- Of 845 rows declaring an archive path, **469 archive/workspace paths were present and 376 absent** at inspection; one row had no archive path. There were 597 physical top-level archive directories. Presence is not frozen workspace-content verification. Missing retained archives may reflect cleanup and are not evidence of a failed original task or a missing file during the decision.
- **40,054** native records have unknown producer/run revision. A current-template match establishes observed wording compatibility, not the historical executable, effective configuration, reasoning mode, teacher weights or all contextual transforms.
- Twelve frozen campaign manifests provide explicit run references, revisions, planner/level metadata and available rerun/replacement links. Preserve these as graph edges. Manifest membership, usefulness scores, completion status and event counts are not individual semantic labels.

## 2. Coverage axes: measured and unmeasured

### Declared suite coder identity

Explicit registry aliases are canonicalized; other historical identities remain literal. Neither column below identifies authenticated judge/teacher weights.

| Declared suite coder | Result rows | Joined native requests |
|---|---:|---:|
| bonsai2 | 61 | 3,724 |
| gemma4_12b | 169 | 7,439 |
| k2_horizon_7b | 26 | 1,306 |
| ling3.0_tiny | 26 | 1,858 |
| nemotron-elastic | 12 | 1,573 |
| ornith1.5_9b | 81 | 6,030 |
| phi4 | 40 | 3,996 |
| qwen3.8_9b_distill | 27 | 2,690 |
| qwen35 | 123 | 12,680 |
| ternary-bonsai | 148 | 6,935 |
| gemma4-finetune | 46 | 0 joined |
| ornith | 6 | 0 joined |
| qwen38 | 62 | 0 joined |
| qwopus | 5 | 0 joined |
| qwythos | 13 | 0 joined |
| r1-llama | 1 | 0 joined |
| UNKNOWN | — | 14,253 |

Zero joined is not proof of archive absence. Requested wire-model strings are a separate axis in the JSON; 23,873 requests literally name the compatibility endpoint `cria`, and 21 have unknown requested model. Do not map that endpoint to whichever model happens to run today. The optional captured `assist_selection` receipt is routing provenance, not independently authenticated loaded weights. Future teacher authentication needs the request/response, effective route/configuration and model revision/weight identity at that time, with explicit unknowns when those records are missing.

### Programming language, task and harness

| Canonical task programming language | Result rows | Joined native requests |
|---|---:|---:|
| Go | 110 | 5,159 |
| Java | 188 | 14,512 |
| Node | 93 | 5,194 |
| Python | 102 | 7,505 |
| Ruby | 141 | 11,022 |
| Rust | 104 | 4,839 |
| UNKNOWN | 108 | 14,253 |

The six known joined tasks are `cart-billing-go`, `feed-pipeline-java`, `handles-cli-node`, `orders-api-py`, `shipping-rates-rb` and `rust-toml-cli`. The results additionally declare eight legacy task IDs; their programming languages are not guessed from names. These six current task identities confound task, ecosystem and language. Repeating a task across models does not provide six independent language-transfer experiments or new problem templates.

All **846 result rows**, and all **48,231 joined requests**, declare **Codex**. Other harness coverage among unjoined captures is unknown; a nonnative direct HTTP probe is not proof of another coding-harness journey. A suite language/task association is provenance, not content annotation: an inspected ternary-bonsai / Go classifier request actually asks for a tiny JSON-only response rather than cart work.

**Human-language distribution, multilingual semantic correctness, per-candidate programming language, source licensing/rights, corpus-wide secret/PII status and semantic near-duplicate groups remain unmeasured.** An English-looking policy prompt does not establish the candidate's language. No synthetic quota, zero-coverage assertion or translation claim is justified on these unknown axes.

### Nonstandard containers are separate, not discarded

There are 674 physical top-level calls directories: 646 native-request-bearing directories plus **28 other containers**. Four contain historical response/prompt-only material; 24 contain experiments, replay/tuning or supporting evidence. Their physical files are included above, but their different schemas are not silently coerced into native production requests.

For example, the three Dory tuning containers retain **371 generation HTTP exchange records**: 284 `/completion` and 87 `/v1/chat/completions`, separate from `/props`, `/v1/models` and `/apply-template`. Their recorded response model is `dory1.0_4b`. The main/confirmation/sampling containers have 273/50/48 generation records; within each, the exact completion-prompt hashes number 2/5/5 and chat-context hashes 17/7/6. These overlap across containers; do not sum them into independent cases. Complete inspected examples include an arithmetic chat smoke and a synthetic repeated-code completion/performance prompt. They do not establish coverage of any target decision family, programming-task lineage or coding harness. Existing Dory availability therefore must not be erased merely because there is no Dory suite join, nor advertised as hundreds of training labels. See [runtime provenance](../dory-runtime.md), not a new service authorization.

The prior classifier/Qwen experiments are also nonnative schemas. Their requests, native outputs, model/runtime contracts and review receipts remain actual evidence, but repeated hypotheses, logits, summaries and reused source documents are not new independent examples. The earlier serialized-chat ModernBERT adapter is explicitly invalid for raw-document classification; its artifacts are retained without rehabilitating that baseline. Proper subsequent NLI experiments are separate. No classifier replacement or new inference is implied here.

## 3. Source-reviewed question routes

Routing pools were derived by reading owners/callers/prompts, then matching the **entire current first-message template** within those pools. Actual source-owned `_inject_nothink_directive` and `_set_reasoning_directive` transformations generate the observed wording variants. The method does not strip arbitrary prefixes/suffixes, crop evidence, search for a verdict word, or treat a phase name as a label. An initial unwrapped-template lower bound was superseded before interpreting coverage; wrapper misses are not missing semantic families.

A complete-template match establishes a question route only. Dynamic slots can have ambiguous boundaries, later evidence may be missing/reduced, and historical/role-merged variants remain unresolved. Routing pools overlap, especially `reasoner`; **do not sum their sizes**. `steer-code` is commonly directive authoring, not automatically a DICTATES verdict.

In the table, public pairs are nonaborted nominal public-channel candidates. Distinct contexts include full messages/tools. Raw identity is measured only where a whole candidate can be recovered from one uniquely delimited producer slot or the typed intake user message. A dash is **not extracted**, not no candidate and not a negative label.

| Question seat | Routing pool | Exact current template | Public pairs | Distinct full contexts | Complete raw extractions / distinct raw texts |
|---|---:|---:|---:|---:|---:|
| Intake engagement/work type | 671 | 671 | 621 | 56 | 671 / 48 |
| Unmarked compaction request | 678 | 678 | 678 | 1 | 678 / 1 |
| Retrospective versus instruction | 815 | 815 | 814 | 654 | 683 / 653 |
| Dictation versus description | 4,021 | 122 | 120 | 120 | 122 / 118 |
| Search new direction | 3,461 | 71 | 70 | 71 | — |
| Required-output relation | 3,514 | 0 measured | 0 measured | 0 measured | — |
| Exact-form intent/confirmation | 0 dedicated phases | 0 measured | 0 measured | 0 measured | — |
| Whole-file versus fragment | 17 | 17 | 17 | 17 | — |
| Executed-test requirement | 29 | 29 | 29 | 8 | — |
| E2E requirement | 153 | 153 | 153 | 6 | 153 / 6 |
| JS runner contract | 11 | 11 | 11 | 11 | — |
| Go module contract | 27 | 27 | 26 | 27 | — |
| Bounded briefing scope | 525 | 525 | 525 | 379 | — |
| Bounded briefing fidelity | 205 | 205 | 204 | 202 | — |
| Bounded deliverable observation | 49 | 48 | 48 | 21 | — |

The complete-raw/public-pair intersection is separately recorded: intake **621 extractions / 48 distinct texts**, compaction **678 / 1**, retrospective **682 / 652**, dictation **120 / 118**, E2E **153 / 6**. Thus 653 distinct retrospective request candidates must not be described as 653 distinct paired candidates. None of these counts certifies labels or independence.

### Contract and evidence boundaries

- **Intake:** `classify.py` / `classify.txt`; classify the complete latest message into the engagement and work-type enums. Preserve the two axes. JSON validity, defaults and cache behavior remain deterministic; a normalized default is not an independently annotated target.
- **Compaction intent:** `memoryhandoff.py::recognize` / `recognize_compaction_request.txt`; latest tool-less turn's request intent, not whether summarization would be helpful. All 678 observed candidates are the same complete 425-byte checkpoint text across 97 sessions. No real negative-class diversity is demonstrated by this pool.
- **Retrospective:** compaction validation in `loop.py`, `memoryhandoff.py`, `selfcompact.py`; `compaction_validate_retrospective.txt`. Preserve the complete candidate, attribution and temporal/conditional context. An unmet original requirement is not automatically a new prescription. Do not use the later scope/fidelity rollup as the first lens's label.
- **Dictation:** `groundedaction.py::_dictates_code`, loop bindings, `steer_dictates_code.txt`. Distinguish implementation/commands prescribed for copying from attributed existing source/observed output. Claims of existing-reference identity need their proper evidence; a code-like name is not enough. Safety or correctness of a prescribed command is a different question.
- **Search direction:** `semanticquery.py::Judge.rehunt`, `search_rehunt_judge` and its user packet. It compares information needs using the task/visible query and fetch context. It is not generic topical relevance, a keyword overlap test, or permission to suppress a tool's content. The complete multi-field packet is available; typed field extraction and independent relational labels are not yet established.
- **Required output:** `completiondiagnosis.py`/loop and `missing_output_requirement.txt`; original task plus the proposed missing subject, with a literal contiguous original-task quote supporting the relation. Zero exact current narrow-template observations in the reviewed pool does not prove absent original-task requirements, historical variants or useful unlabeled task text. A deliverable-observation reply is not automatically this label.
- **Exact form:** `completionapproval.py` and the requirement/bytes/ending prompts. Intent extraction differs from calculating exact byte length, checking final bytes or enforcing JSON. Those measurements stay code. Zero dedicated-phase/template observations is a measured lower bound, not proof that nobody asked for exact output anywhere.
- **Whole-file:** `pastedfile.py`, `shrinkprotection.py`, `wholefile.py`, text/write-call judges and their full measured-fact packets. All 17 exact observations belong to **phi4 / Java**, across five sessions, not broad file-type/model coverage. Applying the existing `whole_file_ruling` reader to full saved public contents returns seven WHOLE_FILE and ten OTHER: **teacher/reader outcomes, not semantic gold or proof of the complete original gate**. Raw multi-field custody remains unresolved. Do not replace measured shrink facts or byte/write custody with a learned guess.
- **Execution/E2E intent:** `completionapproval.py`, `test_participation_requirement`, `test_e2e_requirement`. Keep the questions separate. The execution pool covers Node/Python and eight complete contexts; the E2E pool repeats six task texts across eight known suite coder identities and six programming-language associations. Neither labels actual successful test execution, network access or implementation adequacy.
- **JS runner / Go module:** `runnercontract.py` / `runner_reset_judge` and `modulestate.py` / `module_state_judge`; narrow contract questions with full task/command/output/module evidence. Actual command ownership, installed dependencies and exit status remain code. These are small, long-packet, single-language pools, not priority candidate-only heads.
- **Bounded scope/fidelity/observation:** compaction validation and `completiondiagnosis.py`. The archive contains packets, not automatic short-text training labels. Define an independently reviewed supported relation with sufficient public evidence before use; do not turn whole-history fidelity or whole-task completion into an unsupported short classifier.
- **Public-progress rumination:** deferred. No admitted label contract or sufficient public-observation dataset was established. Private reasoning, token counts, repeated wording, a quiet interval or an incomplete trace does not prove no public progress. The author withdrew eight insufficient seed sketches rather than force their labels. Unknown evidence is not a negative example.

## 4. Complete-input and length limits

Complete raw fields were recovered only through typed positions or exact single-slot producer frames; metadata retains the source request SHA, JSON pointer, decoded-character and UTF-8 byte spans, full candidate hash and lengths. Nothing is shortened, normalized into a different candidate or exported as text. Multi-slot template equality is not custody proof; field-rich routes stay unresolved until their actual serialized layouts can be reconstructed unambiguously.

| Seat | Complete raw UTF-8 bytes, min / lower median / max | Full string-message bytes, lower median / max |
|---|---|---|
| Intake | 2 / 766 / 5,075 | 1,443 / 5,752 |
| Compaction intent | 425 / 425 / 425 | 1,340 / 1,340 |
| Retrospective, extracted subset | 740 / 2,266 / 9,250 | 2,981 / 10,140 over all exact matches |
| Dictation | 137 / 323 / 3,540 | 1,782 / 4,999 |
| E2E requirement | 521 / 628 / 959 | 1,205 / 1,536 |
| Search packet | not extracted | 3,124 / 3,266 |
| Whole-file packet | not extracted | 6,696 / 11,722 |
| Executed-test packet | not extracted | 12,266 / 14,313 |
| JS runner packet | not extracted | 42,260 / 83,629 |
| Go module packet | not extracted | 45,258 / 113,991 |
| Briefing fidelity packet | not extracted | 63,610 / 113,821 |

These byte lengths do not certify future tokenizer fit. String-message totals omit non-string structured content; complete messages/tools hashes do not. Native `usage.prompt_tokens` refers to the historical prepared request and tokenizer, possibly after context-floor reduction, not a future complete raw candidate plus hypothesis/head contract. For example, observed runner/module/fidelity prompt-token maxima are 25,297/35,457/35,470; this is a warning about scope, not a conversion formula or native-fit claim.

Future fit qualification must freeze the exact backbone/tokenizer/checkpoint, usable window, special tokens, pair construction and full evidence contract, then tokenize every complete candidate and all alternatives without clipping. One overlength alternative means whole-case NO_FIT; record coverage separately from conditional accuracy. Do not summarize, use arbitrary windows, keep only a supporting quote or chunk-vote a different question to force a fit.

### Historical missing-candidate control

Among 815 retrospective current-template matches, **132 lack an unambiguously extractable complete candidate under the exact producer-slot contract**. They are not 132 demonstrated semantic errors. Their distribution is 118 phi4-associated and 14 unjoined requests; historical transformations/source availability need individual resolution.

One fully read control is **phi4 / Ruby**, `20261009T121148-01a12214-2811-7141-afc9-fd95066fa24f/0008-harness-compaction-validate-retrospective.{json,prompt.txt,response.json}`, request SHA-256 `6feb26f1da72533dfed1d21a2c555cdd3357df4320231af5908ab3b0cbae409c`. The actual prepared body and rendered prompt say the candidate turn's text was compacted out; only its heading survives. The public answer is RETROSPECTIVE. The same session/turn's authoritative `context.floor` event immediately before `upstream.dump` reports one dropped turn, a 16,384-token window and 15,872 reserve. This is an observed historical loss of the judgment's object, not a finding against the weights or proof about today's service.

Quarantine this input/answer relationship. If the original candidate can later be recovered from an authenticated ancestor, it is a separately reviewable unlabeled example; do not silently pair it with a reply from a judge that did not receive it. This audit records the upstream evidence failure; it neither authorizes production changes nor teaches a classifier to compensate for missing evidence.

## 5. Label provenance, security and representative readings

Keep distinct provenance states for (a) unavailable/incomplete evidence, (b) raw public teacher proposal, (c) source-reader acceptance/normalization, (d) independently proposed annotation, (e) adjudicated policy label, and (f) reviewed/admitted export. A public word, accepted JSON or native gate decision can exist at stages b/c without reaching e/f. An undecidable annotation remains UNKNOWN/deferred; never label it the permissive class to balance a dataset.

Native owner readers must be reused for format/consumption checks. Do not reimplement token matching, infer the class from phase names, count verdict substrings in reasoning, equate rejected scope with PLAN, or label requirement intent from a suite score. Original judgments can be wrong, normalized, context-deprived or based on a different historical policy. Future workspace state, a later successful repair and the final usefulness score must not leak into the earlier semantic input or target.

The audit owner read representative complete request/public-response artifacts across all six canonical programming languages and ten joined suite coder identities; rendered prompts were checked separately. Available reasoning was analysis-only. These are diagnostic readings, not a random sample or accuracy estimate. Exact request/response/rendered hashes and exposure tags are in the companion JSON. Illustrative observations:

| Suite coder / programming language | Capture suffix under the recorded session | Bounded observation |
|---|---|---|
| gemma4_12b / Ruby | `20261008T102528…/0042-compaction-recognize` | Explicit checkpoint request; YES; demonstrates a real source-owned no-think wrapper. |
| ling3.0_tiny / Ruby | `20261009T072403…/0088-classifier` | Public JSON uses `task_type: reason`, outside the stated enum; presence of an answer is not a valid target. |
| gemma4_12b / Rust | `20261008T152445…/0017-test-e2e-requirement` | Task explicitly asks unit tests; stored E2E_REQUIRED needs semantic review rather than automatic teacher acceptance. |
| phi4 / Java | `20261011T032524…/0055-write-shrink` | Full replacement and measured existing-file facts accompany OTHER; facts and semantic presentation are different evidence. |
| ling3.0_tiny / Node | `20261009T104436…/0257-compaction-validate-retrospective` | PLAN proposal over a briefing; attribution and original requirements must survive annotation. |
| bonsai2 / Node | `20261009T003454…/0001-classifier` | Complete CLI request; task/coding proposal, not independent gold. |
| k2_horizon_7b / Python | `20261010T124154…/0001-classifier` | Complete orders-service request; task/coding proposal. |
| qwen3.8_9b_distill / Go | `20261010T154734…/0001-classifier` | Complete cart request; task/coding proposal. |
| ornith1.5_9b / Java | `20261022T094824…/0088-compaction-validate-retrospective` | RETROSPECTIVE proposal over a full briefing; not certification of its workspace statements. |
| nemotron-elastic / Node | `20261009T052745…/0106-test-e2e-requirement` | Explicit real-request/end-to-end task wording with E2E_REQUIRED proposal. |
| qwen35 / Python | `20260812T233444…/0001-classifier` | Historical complete orders task; keep literal historical identity/provenance. |
| ternary-bonsai / Go | `20260825T124859…/0001-classifier` | Actual user turn is a JSON-only probe; joined task metadata does not annotate candidate content. |
| phi4 / Ruby | `20261009T121148…/0008-harness-compaction-validate-retrospective` | Candidate absent from actual prepared input; quarantine, not a semantic-error label. |

Main's additional complete cross-language readings and independent proposed annotations are in [main-review.md](main-review.md). The research owner's full inspection of **phi4 / Java**, `20261011T005747-01a129f7-c922-78d0-9b14-802e082ccd99/0008-text-write`, SHA-256 `7789db34119594ca66351eb672d8a8b4cdee0de54f13f4781fdad7ac26848e49`, is also explicitly research-exposed, not holdout. The companion exposure list is not exhaustive: prior 20 reviewed replay documents, ancestor tasks/templates, the supplied controls and historical Main inspection remain exposure constraints. An unlisted path is not thereby fresh.

**No corpus-wide security/PII or license review was completed.** Hashing is custody, not redaction. Requests can contain user material, repository code, fetched text, tool output, paths and credentials. Private reasoning can be embedded inside response JSON even without a sidecar. Future exports require explicit public-evidence field allowlists, security/rights review and immutable original/transformed identities. Do not export raw responses or serialized conversations wholesale. If removing private material or secrets destroys relevant public evidence, quarantine rather than quietly shortening the input or pretending the original proposal still labels it. Annotator notes, labels, policy rationales and group/exposure metadata stay out of model inputs.

## 6. Leakage groups and evaluation design

The measured 646 sessions, 844 result run IDs, 59,897 exact contexts and the raw-candidate hashes are **grouping clues**, not certified independent lineages. The full task/session/retry/refold/replay/exposure graph has not been built. Do not split rows independently or call one stored coordinate an independent example.

Before any augmentation or training export:

1. Bind each complete public candidate/evidence packet to request hash, producer/policy revision, actual slot spans, source reader, original task/template identity and all retained run/session/campaign references. Keep unknowns explicit. Resolve historical source transforms rather than inventing a substitute candidate.
2. Group identical target inputs, task/template variants, shared sessions/turns, retries/refolds, rollup descendants, replay parents and reviewed near-duplicates. Preserve relation direction and origin IDs. Replayed prompt/hypothesis alternatives from one document stay together. Generic policy text alone is not a data edge; the **identical compaction candidate itself** is a repeated target input and must not be split into independent examples.
3. Inspect graph components before allocating groups. Shared exact candidates can connect many sessions/tasks; a strict cross-family/session graph may collapse ostensibly numerous observations into very few components. Do not break true edges merely to obtain a convenient train/validation/test ratio. Acquire unrelated prospective tasks if the retained components cannot support a credible holdout.
4. Freeze train, calibration/development and untouched real evaluation by groups. Never use heldout documents, translations, answers or outcomes as synthetic-generation or prompt-selection inputs. The standalone seed has no archive partition ancestry and is training-only-if-admitted; all its contrast/translation/negation siblings remain together.
5. Keep **representative real-data evaluation** separate from deliberately balanced/hard-boundary challenges. Triggered historical calls and chosen failure cases are not a natural traffic sample; label frequencies and selection mechanisms must be reported. The exposed 20-document replay controls are diagnostics, not a fresh test.
6. Report per-family, per-class, consequential false-approval, UNKNOWN/abstention and NO_FIT coverage with denominators, plus coder, task/programming-language, harness and human-language slices where actually measured. Fit calibration/abstention only on development data. A softmax score is not calibrated confidence. Class imbalance or a single repeated checkpoint must not turn into misleading high accuracy.

Model holdout while reusing a task is not task holdout; language holdout with one task per language confounds both axes. Corpus-wide human-language coverage and unseen-harness generalization cannot be claimed from the present metadata. Use learning curves over reviewed independent training groups and real-versus-synthetic ablations, not a fixed invented sample quota.

## 7. Collection priorities and deterministic exclusions

**First qualification candidates:** retrospective and dictation. They have hundreds of distinct complete raw inputs, a narrow source question and explicit policy. Begin with independent semantic adjudication and complete-evidence/security checks, preserving genuine negative/uncertain cases and long candidates; do not treat the existing proposal as the answer key. Resolve the 132 retrospective custody gaps separately. These are priorities for data work, not a selection of a production replacement or permission to train.

**Diversity acquisition rather than duplication:** intake, compaction intent and E2E requirements. Their many calls mostly repeat few tasks/harness text. Obtain genuinely different complete incoming turns, naturally ambiguous non-checkpoint turns, and independently sourced task requirements/negations. Measured compaction diversity is one candidate; that finding supports collection, not a universal synthetic negative quota. Review synthetic-language coverage independently from archive-language unknowns.

**Next extraction/label contracts:** search direction, required-output relation and exact-form intent. Search needs the complete relational packet and actual visible search/fetch evidence, not query snippets. Required-output/exact-form have no measured current narrow-route examples in this census but do have source-owned contracts and potentially useful original task text; collect or independently annotate full subject/task pairs without borrowing heldout cases. Preserve literal Unicode support spans and no-fit/unknown outcomes.

**Deferred expansion:** whole-file across actual file/content types and more suite models/languages; executed-test intent; runner/module contracts; bounded briefing/deliverable relations; and public-progress rumination only after complete public observations and an independently reviewed question exist. Small, long, single-task pools do not justify broad integration authority.

Keep execution facts, exit/check ownership and pairing, freshness, arithmetic/byte settlement, filesystem/permission boundaries, cleanup proof, evidence custody, parsing and native wire integrity in deterministic code. A learned intent relation never establishes that a tool succeeded, a dependency exists, a missing path is safe to write, a task is complete or a cleanup action is authorized. Do not revive removed outgoing relevance, disabled spill relevance, experimental step preparation or planning; planning remains OFF unless explicitly enabled by the operator.

## 8. Reproduction, tests and handover gate

The reusable scanner is offline and metadata-only. Use a new output/database path and a deliberate cutoff; it does not overwrite an existing SQLite inventory or run models:

```bash
python -m suite.training_archive_audit --help
python -m pytest tests/test_training_archive_audit.py
```

The seven focused tests cover no-follow/cutoff behavior, growth during read, producer shape rather than filename, private-only/incomplete replies, ambiguous joins, exact messages/tools identity, and a complete fake-archive `scan` invocation with snapshot-SHA precedence, long Unicode custody, malformed JSON/shapes, native tool replies, archives and honest no-gold output. Collection failed before implementation and all seven passed afterward. Main subsequently reported the combined **22 focused tests** and final full `python -m pytest`: **10,949 passed, 216 skipped**; that is Main's run, not another audit-owner full-suite execution. See the integration review for the exact final source/testing scope.

The audit and metadata are ready for integration; **training is not ready to launch**. Required next gates are a chosen first question/backbone, a reviewed complete public-evidence export, adjudicated targets, resolved group graph, frozen real evaluation/calibration, exact tokenizer/export/budget contract and a resource plan. The strict deployment weight limit includes the learned heads and all external tensors/backbones, not just one nominally quantized file. Prior classifier experiments did not validate a replacement.

Once that concrete training package is ready, notify the operator and wait for **new explicit RTX 3090 handover permission**. The hardware offer does not authorize inspecting GPU workloads, clearing memory, stopping another process, swapping the live coder or starting training. This audit performed none of those actions.
