# Synthetic decision seed: construction and admission contract

Status: **standalone synthetic proposals, independent adjudication/admission pending, not gold and not training-ready**. File: [`suite/training_data/synthetic_seed.jsonl`](../../suite/training_data/synthetic_seed.jsonl). All records carry `label_status=proposed_independentreview_pending`. Main owns independent review, admission, reusable validator coordination and integration. Research motivation and sources are in [research.md](research.md); real availability and coverage are owned by the [archive audit](archive-audit.md).

## What was delivered and checked

The seed contains **72 complete bounded cases in 18 four-member contrast groups**, eight cases per proposed family. It is more than a list of templates: each record contains the actual input strings, exact proposed label, one exact supporting span, domain/language/context metadata and a separately stored author rationale. There are 18 bases, 24 label-changing siblings, 21 label-invariant siblings and 9 explicit UNKNOWN/abstention siblings. Sixteen siblings vary human language; two additionally code-switch. Other siblings change requested scope, temporal attribution, required versus illustrative text, exact versus bounded counts, prior-information availability, program versus file output, whole-file presentation and execution acceptance. All variants are present as full inputs; there is no placeholder-expansion step.

The arithmetic of eight cases per family is an authoring organization, **not** a measured coverage target or a claim that each family is suitable for replacement. Search direction has stricter evidence/routing caveats below. Public-progress sketches were withdrawn during author scope review: a sufficiently reviewed public evidence/label contract is not established yet. No progress/rumination examples are exported in this seed. These are short boundary cases; they do not supply long-context training/evaluation or certify performance over realistic histories.

| Family ID | Cases | Contrast groups | Main boundary |
|---|---:|---|---|
| `searchdirection` | 8 | spatial-index; pdf-fonts | Same information need versus a new fact, despite shared words |
| `requiredoutput` | 8 | sensor-report; migration-doc | Required deliverable versus input/example/conditional obligation |
| `exactform` | 8 | binary-fixture; newline-output | Exact file bytes/ending versus bound/program-output formatting |
| `intake` | 8 | image-cache; docstring-scope | Explanation, one bounded change, multistep implementation |
| `compactionrequest` | 8 | checkpoint; summary-artifact | Conversation continuation summary versus feature/question keywords |
| `retrospective` | 8 | calendar-merge; raster-history | Attributed/past state or unmet outcome versus operative repair |
| `dictation` | 8 | dotnet-diagnostic; http-backoff | Quoted command/code versus exact implementation prescribed to copy |
| `wholefile` | 8 | web-manifest; lua-module | Complete-file presentation versus member fragment/illustration |
| `runtimee2e` | 8 | archive-cli; linter-request | Required runtime/interface acceptance versus unit/design/document scope |

Task domains are 18 separately named synthetic scenarios, not 18 independently collected real tasks. Programming/format metadata uses Rust, Python, C#, C, SQL, Elixir, C++, Kotlin, Swift, Go, Ruby, TypeScript, JavaScript, R, PHP, JSON, Lua, TOML and Shell. JSON/TOML are data formats rather than programming languages; the shared field is an ecosystem label, not a scientific count of programming languages. Human-language metadata separately records English, Spanish, French, German, Chinese, Japanese, Arabic and Hindi. There are 54 English-only cases and 18 cases with other human-language content, including two explicitly code-switched cases. These are author proposals, **not** independently certified translations or demonstrated multilingual coverage. Native/fluent review is required before admission.

Styles include ordinary requests, issue bodies, markdown/fenced-file presentation and tool-result/chat-like contexts. These are synthetic presentation styles, not claims of authentic captured harness serialization or measured multi-harness coverage. Classifier export must use the declared bounded evidence fields, not pretend these cases are wire captures.

Offline assembly checks passed for JSONL round-trip, 72 unique IDs, 72 unique canonical complete-input hashes, group/parent membership, all 72 span substrings/offsets, all declared label relations, provenance/status/partition constants, and absence of the project token inside model inputs. These are **structural checks, not independent semantic adjudication**. The author also inspected the contrast intent; that is still the proposing author, not a second reviewer. No reusable repository validator was added by this worker. No model/tokenizer calls, training, tests requiring inference, GPU use or runtime behavior changes occurred.

Main subsequently supplied `suite/training_seed.py` and `tests/test_training_seed.py`. This worker independently read both files and the integration-review record without editing them, then ran `PYTHONDONTWRITEBYTECODE=1 python -m suite.training_seed` and `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_training_seed.py`: the validator accepted the unchanged 72-case seed and reported the explicit admission blocker; **15 focused seed tests passed (0.06s)**. No actionable discrepancy with this declared structural contract was found. This independent focused run is separate from Main's scanner-combined/full-suite runs and certifies neither semantics, privacy, native fit nor training admission.

### Corrections following Main's blinded input review (still not gold)

Main read complete inputs without the proposing labels/rationales before public-progress withdrawal and then reviewed the retained set. This is review evidence, not blanket independent certification or multilingual admission. All statuses remain `proposed_independentreview_pending`.

- The initial 80-case draft included eight public-progress sketches. They were withdrawn, leaving 72 cases, because summary-like intervals did not establish a sufficiently reviewed progress contract. They are not exported or counted in this final seed.
- **`seed-v1-retrospective-calendar-merge-d`: UNKNOWN/abstention → RETROSPECTIVE/label_invariant.** The unchanged candidate reports that a decision is in another note; it does not tell the future coder to act. Missing an external note cannot make the observable candidate-only intent unknown. The record retains this proposal correction in `annotation.proposal_history`; it remains pending, not silently promoted to gold.
- **`seed-v1-dictation-dotnet-diagnostic-d`: explicitly blocked from admission.** Its reference-only prescription (“Apply the exact replacement specified in the attached patch”) raises an unresolved policy-scope question: whether prescription by reference itself counts as DICTATES when no replacement text is visible. Its UNKNOWN stays only an unresolved proposal, with `annotation.admission_blocker`; it must not be exported as UNKNOWN gold or used to teach “missing patch means unknown.” Resolve the contract independently or withdraw the case before admission.

## Real coverage: what the audit does and does not establish

The audit owner's frozen operational inventory at **2026-10-24T17:19:34.193224Z** reports 62,484 native-producer-shaped request records in 646 session directories and 53,155 nonaborted-public-response candidates. The independently adjudicated archive-gold count and independent-lineage count are **UNKNOWN, not zero**; no archive training or evaluation records were admitted by this audit. Previously reviewed replay labels remain exposed diagnostics, not proof that no reviewed labels exist elsewhere. Of the requests, 48,231 join declared suite metadata and 14,253 remain unjoined with model/task/programming-language/harness identity UNKNOWN; requested wire-model strings are retained separately. The owner's subsequent full-source review identifies all 846 result rows and all joined captures as Codex, with ten model identities represented by actual joined captures. This does **not** establish the absence of other harnesses among the 14,253 unjoined requests: their harness coverage remains UNKNOWN/UNMEASURED. The shared canonical result-language map leaves 108 legacy result rows UNKNOWN; that mapping is distinct from human-language measurement. **Human language is UNMEASURED corpus-wide**, not demonstrated monolingual or absent.

The owner's subsequent **source-reviewed complete first-message matching** accounts for source-generated reasoning wrappers, including a config-owned no-think suffix. Initial strict source-template-only matches were **lower bounds caused by wrapping, not evidence of missing family coverage**. The corrected method uses source-owned wire variants and exact whole-message matching without clipping or assigning labels. Prompts and pure configuration helpers at the audited source revision `15867f4761660e1b7c5d6e7bbba9d06368662e5a` are SHA-bound; an unknown historical revision is not silently treated as that policy.

| Source-reviewed route | Request matches | Nonaborted public pairs | Scope restriction |
|---|---:|---:|---|
| Intake | 671 | 621 | Engagement/work-type routing proposals, not certified labels |
| Compaction request | 678 | 678 | Recognition availability, not independent template/scenario count |
| Retrospective | 815 | 814 | Candidate-intent judgment availability, not briefing-fidelity gold |
| Dictation | 122 | 120 | Within a multiplexed 4,021-record routing pool; **not** 472 `steer-code` label calls |
| Search direction | 71 | 70 | Within a 3,461-record reasoner pool; the entire pool is not search gold |
| Whole file | 17 | 17 | Presentation judgment availability, not correctness/write permission |
| Executed-test requirement | 29 | 29 | Requirement interpretation, not proof that any test executed |
| E2E requirement | 153 | 153 | Requirement interpretation, not E2E participation/completion gold |

Additional reviewed routes are JavaScript runner (11 requests / 11 public pairs), Go module (27 / 26), scope (525 / 525), and fidelity (205 / 204). Scope/fidelity availability covers their **bounded relationship questions only**, not whole-briefing truth, general adequacy or completion. These routes are not automatically added as seed families.

The current narrow required-output template has **zero matches within an overlapping 3,514-record routing pool**; exact-form has zero dedicated-phase records and zero current-template matches. Those zeros do **not** establish absence of original-task requirements, semantic content, historical variants or possible extractable evidence. The deliverable observer has 48 current-template matches / 49 phase records, but those are inspecting **multi-question proposals**, not narrow required-output gold. Preserve that distinction instead of converting observer results or phase names into training labels.

These figures are an explicitly attributed frozen audit-owner handoff, not a second locally recounted inventory or independently certified gold. Pools can overlap and examples can share task/template/session/retry/refold/replay ancestry: do not sum them into independent sample counts. The owner's authoritative `details.json` supplies the exact-text uniqueness and extraction limits below. The final durable [audit](archive-audit.md) (SHA256 `c5f8da596d2175c0dd409947ef7eb95fa89b42d01096dac9c35b3975c49c803f`) and [audit metadata](archive-audit-metadata.json) (SHA256 `aabda96d1384a05f11c5a8227d46cab6f6c6ee1044d5630c9375a30e26626ed6`) were crosschecked for this synchronization. The metadata publishes a 253-cell sparse policy/coverage matrix across 15 reviewed seats, corpus axes, event/campaign references, 28 separate nonstandard containers and 18 explicit inspection-exposure references. These are not independent scenario counts. Complete cross-family typed extraction and a reviewed leakage-group graph remain unfinished; the coverage matrix itself is not a train/evaluation partition.

### Measured uniqueness and extraction limits

These are the audit owner's measurements, not new local recounts, behavioral rates or label certification. This worker read the complete owner snapshot `details.json` (SHA256 `dcf6d3ff5e80221c495ec710e2d8c171dd39846dee934b4a0b01d62b9b10381b`) before synchronizing these limits; the completed archive audit and its companion JSON own the durable provenance and final coverage matrix:

- **Intake:** 671 requests contain 48 distinct complete raw texts; the nonaborted-public-pair intersection is 621 complete extractions / 48 distinct texts. Exact-text uniqueness is not task/scenario independence.
- **Compaction request:** all 678 matches reduce to **one exact 425-byte text across 97 sessions**. High call/session volume therefore does not demonstrate intent, language or template diversity. The recognition route exists; the measured limitation is repetition, not family absence.
- **E2E requirement:** 153 requests reduce to six distinct complete task texts. These are task-text identities, not six independently certified semantic scenarios or labels.
- **Dictation:** 122 requests contain 118 distinct full raw texts; the nonaborted-public-pair intersection is 120 complete extractions / 118 distinct texts. Near-duplicate/ancestry review and adjudication remain separate from exact deduplication.
- **Retrospective:** among 815 requests / 814 nonaborted public pairs, the exact producer slot supports 683 unambiguous complete-candidate extractions, with 653 distinct extracted texts; intersecting with nonaborted public pairs leaves 682 extractions / 652 distinct texts, not 653 paired texts. Another 132 requests are not extractable under that exact slot. Do not call those 132 semantic errors, negatives or unknown gold labels. The owner fully read one `phi4 / Ruby` case in which the context floor had actually dropped the candidate; that establishes one specific missing-evidence mechanism, not an explanation or behavior rate for all 132. Do not reconstruct unavailable candidates from arbitrary prompt snippets.
- **Whole file:** all 17 matches are `phi4 / Java`. The native owning verdict reader reports seven WHOLE_FILE and ten OTHER outcomes. These are **teacher-policy outcomes, not independent gold**, and they do not demonstrate cross-model/programming-language coverage.
- **Other field-rich routes:** full-packet lengths are available for search, runner/module and related questions, but typed raw-field extraction is **UNRESOLVED**. Whole-packet availability does not certify an exact candidate/task field, semantic completeness, native tokenizer fit or a training-ready narrow premise. Do not invent regex slots or clip a packet until it resembles the desired input.
- **Separate nonnative coverage:** 371 Dory performance/smoke generation records exist separately from the native-producer-shaped request inventory. Lacking a canonical suite join is **not evidence that the archive has no Dory records**. Preserve source kind and unknown joins rather than folding these into native decision counts or asserting absence.

Accordingly:

- **Measured blocker:** independent label certification, complete candidate extraction and trustworthy lineage/split metadata are not supplied by file availability alone. Adjudication/extraction is the first priority, rather than generating thousands of examples.
- **Likely review priorities, not quotas:** prioritize retrospective instruction/attribution and dictation for initial real-data adjudication. Compaction intent, engagement and explicit E2E evidence need genuinely new input diversity; whole-file needs broader coverage and typed packet extraction, not just more repeats of the observed cases. Prioritize by unique complete evidence and reviewed grouping, not call volume: compaction's single repeated text and E2E's six task texts are measured diversity limits, while unresolved typed extraction remains an availability uncertainty. The small whole-file route count motivates careful inspection, not an invented population rate, unique-case count or automatic synthetic oversampling ratio.
- **Unknown axes:** language, valid cross-harness semantics, task diversity within a phase, historical required-output coverage, and semantic class balance remain unknown until independently examined. Do not turn unknown into measured absence.
- **Seed target:** explicit policy boundary coverage across unrelated toy domains, including negative and missing-evidence cases. It does not claim to fill any counted archive gap or match production prevalence. Once the reviewed lineage graph and real labels exist, add or remove proposed families and target measured gaps rather than translating everything or forcing balanced classes.

No frozen held-out research input, template, raw archive document or private reasoning was supplied as a generation input. The author had previously seen exposed research cases; the seed therefore discloses prior author exposure and **does not claim semantic independence or eligibility as evaluation data**. Abstract policy questions and prior research observations influenced boundary selection, not copied case text. All earlier inspected replay documents remain exposed diagnostics. The final metadata explicitly records this worker's complete `phi4 / Java` whole-file inspection (`20261011T005747-01a129f7-c922-78d0-9b14-802e082ccd99/0008-text-write.json`, request SHA256 `7789db34119594ca66351eb672d8a8b4cdee0de54f13f4781fdad7ac26848e49`) as research-exposed, not fresh holdout. Its 18 exposure references are not exhaustive: unlisted paths, ancestor tasks/templates and prior controls are not thereby untouched. No archive TRAIN split exists for this seed, and no TRAIN ancestry is asserted.

## Record schema and input isolation

One UTF-8 JSON object per LF-terminated line; embedded newlines remain JSON string escapes. No comments or non-record header lines.

| Field | Type / contract | May enter model input? |
|---|---|---|
| `schema_version` | Literal `synthetic-decision-seed-v1` | No |
| `id` | Unique stable string, `seed-v1-<family>-<group>-<variant>` | No |
| `family`, `policy_id` | Family enum below; policy ID `<family>-research-v1` | Family selects a head/contract out of band; do not concatenate labels or annotation metadata |
| `complete_input` | Family-specific object below, preserving every supplied field/string/null | **Only this evidence object**, through a separately frozen lossless serialization |
| `label` | Family enum below, including `UNKNOWN` | Target only |
| `support_spans` | List of exact span objects; explanatory support, not an evidence filter | Target/review only; never replace complete input with these snippets |
| `language` | `{programming: [ecosystem labels], human: [language codes]}` | Slice metadata only |
| `task_domain`, `harness_style` | Synthetic scenario/style tags | No |
| `group_id` | All linked contrasts/translation siblings share it | Split/dedup only |
| `variation_type` | Descriptive change, e.g. `time_counterfactual`, `human_language_invariant` | No |
| `contrast` | `{parent_id: string|null, expected_relation: base|label_invariant|label_changing|abstention}` | No |
| `source_kind` | Literal `synthetic` | No |
| `origin` | Authorship method/batch, null archive lineage, empty archive parent list, evaluation-input/exposure disclosures | No |
| `research_refs` | Stable IDs defined in [research.md](research.md#verified-sources-and-stable-research-reference-ids); methodological inspiration, not copied source sentences | No |
| `label_status` | Literal `proposed_independentreview_pending` until an independent admission artifact exists | No |
| `partition` | Literal `UNASSIGNED_QUARANTINE` in this seed | No |
| `partition_constraint` | Literal `TRAIN_ONLY_IF_REVIEWED_AND_ADMITTED` | No |
| `fit_status` | Literal `NOT_MEASURED`; no tokenizer/native fit was measured here | No |
| `annotation` | Author rationale, family target fields, explicit bounded-evidence scope; optional `proposal_history` and blocking `admission_blocker` | **Never** |

A support span is `{field: "/<top-level-complete_input-key>", start: integer, end: integer, text: string, unit: "unicode_codepoints", bounds: "zero_based_half_open"}`. The field is a JSON pointer relative to `complete_input`. Require `complete_input[key][start:end] == text` on the decoded original string without normalization. These are **character**, not UTF-8-byte or tokenizer offsets. All current spans refer to string-valued fields. Missing-context spans quote the visible cross-reference/unavailability, not evidence for the unavailable conclusion. Positive required-output support must be a contiguous original-task quote including the unchanged subject. Literal presence is checked deterministically; semantic sufficiency is independently reviewed.

`annotation.target_fields` is `{}` unless a proposed exact-form label supplies `bytes: nonnegative integer|null` and `ends_with_line_break: boolean|null`. Null means not established by this task, not zero bytes or no newline. These targets belong outside inputs. Future span-head schemas may add structured per-target support, but a reviewer must settle policy before that schema changes. Do not silently merge contradictory constraints or normalize away file identities.

### Family input shapes

All listed required string keys may be null **only** to represent explicitly unavailable evidence and require review/UNKNOWN where decisive. Empty `public_context` means there is no further context in this bounded case, not an omitted transcript. Optional keys are part of the complete input when present.

- `searchdirection`: `previous_query`, `proposed_query`, `question_context`, `previous_results_available: boolean|null`.
- `requiredoutput`: `original_task`, exact `subject`; optional `available_note`.
- `exactform`: `original_task`, exact `subject`; optional `prior_agreement`.
- `intake`: `latest_request`, `public_context`.
- `compactionrequest`: `latest_turn`, `tools_offered: []` in this seed; optional `preceding_control_message`.
- `retrospective`: whole `candidate_briefing`; optional `referenced_note`.
- `dictation`: whole `public_directive`; optional `attached_patch`.
- `wholefile`: `target`, `presentation`, entire `candidate_payload`, `original_file_facts`.
- `runtimee2e`: `original_task`, `requested_interface`; optional `linked_ticket`.

Every synthetic case is a complete **bounded observation problem**. A null attachment/history is intentional unavailable evidence, not a clipped historical document. A whole-file OTHER candidate may itself be an intentionally supplied fragment: the entire proposed fragment is included, not selected lines from an unprovided candidate. For archive-derived data, this authoring convention is not an excuse to discard available historical evidence: extract the entire actual candidate with source hash, JSON pointer, exact character/UTF-8 spans, extraction rule and policy revision, or mark it unavailable/ineligible. Preserve headings, quotation/attribution and producer boundaries.

## Family contracts

These are annotation contracts for research, **not exact replacements of the current runtime schemas or uncertainty adapters**. Production prompt pointers are orientation to the existing question; current-source files cannot establish every historical archive policy. UNKNOWN is deliberately retained in data instead of fabricating gold. The existing runtime may conservatively map uncertainty to a binary safe outcome; that is a separately reviewed admission adapter, not a reason to train uncertainty as a definite semantic negative.

### Search direction — `searchdirection-research-v1`

Labels: `SAME_HUNT`, `NEW_DIRECTION`, `UNKNOWN`. Source question: `cria/prompts/search_rehunt_judge.txt`.

Compare information need, not tokens. Same concept/fact with reordered words or language change remains SAME_HUNT. A different fact, API property, error or problem may be NEW_DIRECTION despite the same library nouns. The seed classifies the proposed query's relation, **not permission to execute it**, relevance of returned search results, whether the current evidence already suffices, or the usefulness of repeating the search. A production seat may need additional public question/results evidence and availability rules; this short pair schema alone does not prove sufficiency. Missing prior intent/referents → UNKNOWN. Do not restore outgoing-search relevance or infer this label from multiplexed reasoner calls.

### Required output — `requiredoutput-research-v1`

Labels: `REQUIRED_OUTPUT`, `NOT_REQUIRED_OUTPUT`, `UNKNOWN`. Source question: `cria/prompts/missing_output_requirement.txt`.

Judge whether the untouched task requires creating/updating the exact subject as an output. A required report is positive; an input, example, optional suggestion, expressly excluded deliverable or different path is not. Absence on disk is not requirement evidence and is deliberately not an input here. Positive labels require a verbatim contiguous task span with unchanged subject. Missing task or unresolved condition that changes obligation → UNKNOWN. Do not translate identifiers while translating prose. A classifier must not become a filename-mention heuristic or a second competing required-output subsystem.

### Exact file form — `exactform-research-v1`

Labels: `EXACT_FILE_FORM`, `NO_EXACT_FILE_FORM`, `UNKNOWN`. Source question: `cria/prompts/exact_form_requirement.txt`.

Interpret an **exact file** byte count or ending-line-break requirement for the exact subject. At-most/at-least bounds alone do not establish an exact byte count; character count is not byte count. Runtime stdout formatting does not fix a documentation file's bytes. EXACT_FILE_FORM needs at least one supported target field; NO_EXACT_FILE_FORM means this bounded task establishes neither targeted requirement, not that the task has no other constraints. An unavailable prior agreement, ambiguity or unresolved contradictory requirement → UNKNOWN rather than guessing. Deterministic code retains literal quotes, rejects malformed outputs, and measures actual bytes/ending separately. This is an interpretation/span task, not a general JSON-generation or code-arithmetic task.

### Engagement intake — `intake-research-v1`

Labels: `QUESTION`, `SIMPLE`, `TASK`, `UNKNOWN`. Source question: engagement in `cria/prompts/classify.txt`.

QUESTION requests an answer without substantive implementation. SIMPLE is one plainly bounded tiny edit. TASK requires broader implementation/investigation or multiple coordinated deliverables; uncertain SIMPLE versus TASK uses the conservative TASK boundary after the request is understood. An absent referent such as “do that change” → UNKNOWN for annotation. The seed does not annotate the separate `task_type` field or reproduce the full runtime JSON response. A TASK label is **not** planner opt-in, executor authority, or permission for writes beyond the user request.

### Compaction intent — `compactionrequest-research-v1`

Labels: `YES`, `NO`, `UNKNOWN`. Source question: `cria/prompts/recognize_compaction_request.txt`.

YES means the latest turn asks for a conversation checkpoint/summary for continuation. A product called a summary dashboard, a question containing checkpoint vocabulary, explicit “do not summarize,” or an unrelated task with no tools is NO. Tool absence alone proves nothing. If the latest turn depends on an unavailable control message and intent cannot be settled → UNKNOWN in annotation. This is intent recognition, not instruction precedence, whether summary quality is adequate, or whether a destructive compaction action is authorized.

### Retrospective versus operative instruction — `retrospective-research-v1`

Labels: `RETROSPECTIVE`, `PLAN`, `UNKNOWN`. Source question: `cria/prompts/compaction_validate_retrospective.txt`.

Read the entire candidate. Reported state, past actions, existing source comments/designs and still-unmet requested outcomes remain RETROSPECTIVE, including “requirements still require X.” Any newly operative repair instruction, prescribed command or approach makes PLAN. An instruction conditional on a future observation is still an instruction. Attribution and temporal status matter more than future-looking nouns. Judge the observable candidate, not unseen note contents: “the repair decision is in another note” reports state, while “follow the repair steps in that note” supplies an operative instruction even without the note. External-reference absence alone does not justify UNKNOWN. Only missing decisive candidate evidence or genuinely unresolved candidate intent does; the current binary runtime's conservative PLAN handling is not changed. This classification **does not** check factual fidelity or certify that the summary is safe to install.

### Dictation — `dictation-research-v1`

Labels: `DESCRIBES`, `DICTATES`, `UNKNOWN`. Source question: `cria/prompts/steer_dictates_code.txt`.

DICTATES supplies copyable code/calls/lines/commands as implementation to use or execute. DESCRIBES may name existing APIs, quote captured commands/errors/code or state prose goals without supplying a new copyable prescription. Exact same literal text can change labels when attribution changes. A reference-only prescription is a policy-scope question, not an automatic UNKNOWN from missing attachment bytes: the seed's one such case is explicitly blocked pending independent adjudication of whether the reference itself is DICTATES. Judge what the public directive actually prescribes; do not convert command presence into DICTATES automatically. These labels do **not** authorize execution, judge safety/correctness, or make an implementation injection acceptable. Public author directives and dedicated judgment calls are different archive roles.

### Whole-file presentation — `wholefile-research-v1`

Labels: `WHOLE_FILE`, `OTHER`, `UNKNOWN`. Source question: `cria/prompts/write_call_judge.txt`.

WHOLE_FILE means presented as the complete named file, first-to-last. OTHER covers an explicitly partial member/block, illustrative code not proposed as a file, or a patch fragment. A much shorter complete replacement may still be WHOLE_FILE. Correctness/parseability is a different question. Missing the candidate payload or decisive presentation → UNKNOWN. This does not claim that overwriting the file is authorized, that content was preserved appropriately, or that a whole-file write passed checks; those guards remain separate.

### Task-required runtime E2E — `runtimee2e-research-v1`

Labels: `E2E_REQUIRED`, `NOT_REQUIRED`, `UNKNOWN`. Source question: `cria/prompts/test_e2e_requirement.txt`.

E2E_REQUIRED needs original-task execution-based acceptance through the requested interface: for example launching the built CLI on a fixture and asserting outputs/status. A CLI implementation, generic unit-test requirement, design answer or illustrative documentation heading alone is not such a requirement. An unresolved acceptance-ticket reference → UNKNOWN. Do not infer best practice as a user requirement. This label neither establishes that execution occurred nor settles whether a particular test is genuinely end-to-end; execution ownership/participation and actual completion require other evidence.

### Deferred public semantic progress (not in the seed)

A future research contract might distinguish progress, repeated unchanged public evidence and insufficient observability. No labels or examples for it are admitted or exported here, and no claim of equivalence to a current production rumination/private-reasoning classifier is made. Initial author sketches were withheld because summary-like interval observations are too easy to turn into circular labels; complete actions/results, task relevance and observer limits need independent review first.

Any future contract must use only bounded chronological public task/actions/results. Fresh diagnostic information or an evidence-informed landed change can be evidence of progress without writing files or completing the task. Repeated identical observations on an unchanged state without a new question/action/evidence may indicate stalled public work **for that interval**, not a diagnosis of hidden thought or global usefulness. A still-running tool emitting new observations is not a stall merely because it is slow. Silence with unknown running state or missing receipts → insufficient evidence. Do not set a fixed count/time/keyword threshold from toy sketches. Before admitting this family, reviewers must require complete enough public context and establish inter-reviewer agreement on the boundary. Private reasoning remains analysis-only: never input, target, rationale source for export, or synthetic-generation material.

## Annotator procedure and abstention/evidence contract

1. Review the complete input and exact family policy, blinded to the author's label/rationale and historical model verdicts. Ignore style/ID/metadata cues. Preserve quotation, negation, conditionals, time, original-task authority and exact subject identity.
2. Set a proposed decision and minimal exact supporting span(s). For positive requirements, support must come from the original task, not a diagnosis or file absence. For paired questions, consider both sides even if one short quote is sufficient annotation support.
3. Record whether the decisive evidence is present. Keep missing source, semantic ambiguity, unreviewed language, wrong family/routing and unusable native length distinct in review metadata. Do not force a “balanced” negative to repair class counts.
4. Independently review semantics and translation equivalence. If reviewers disagree, adjudicate against the policy or retain UNKNOWN/quarantine; do not rewrite the candidate until it matches its intended label. If a candidate is revised, create a revision with preserved lineage and recheck all siblings/spans. Neither synthetic intent nor two agreeing model outputs are gold.
5. A literal/span checker can reject impossible support and malformed fields, but cannot certify intent, completeness or label truth. There is no lexical-rule substitute when evidence calls for semantic judgment.
6. Future model calls require complete native input/pair including special tokens. If required evidence exceeds the pinned window: **NO_FIT**, no clipped inference, no arbitrary excerpt, chunk voting, summary substitution or hidden deletion. Native fit is measured later; every current record says NOT_MEASURED. NO_FIT is applicability, not a semantic wrong label or successful decision.
7. Low calibrated confidence, unsupported evidence, invalid output, exact ties and out-of-domain/unreviewed language keep the existing inspecting judgment/evidence path. They do not grant approval, silently become a definite label, or terminate work by handing back to a human. Runtime mapping requires separately authorized, regression-tested integration; this data file changes none of it.

## Leakage, provenance and admission gates

- `origin.method=standalone_authored_for_review`; archive split lineage is null and archive parent IDs empty. The authoring batch itself is a **shared leakage factor** above the 18 scenario groups. All current records are quarantine/training-only proposals, never DEV/TEST by splitting siblings. A group ID is not proof of independence from a different group or the same author.
- Future **archive-derived** synthesis must start only from independently reviewed TRAIN parents after real scenario/session/template/retry/refold/replay grouping and splits are frozen. Record parent source hash, capture/pointer/spans, policy version, generation recipe/model/revision when relevant, author/reviewer identities, and generator batch. All translations/paraphrases/counterfactual siblings inherit the parent train-only group. No locked real evaluation input/template/label/rationale is exposed to generation or active-learning selection.
- Exact input hashes check identity, not semantic near-duplicates. Review near-duplicate candidates and ancestry links; group unresolved related examples conservatively rather than deleting attribution or shortening model evidence. Do not train/test split merely by document or capture basename. Already research-exposed real documents are not fresh holdout.
- Check synthetic text for accidental secrets/PII, copyrighted copied material, authoritative-looking fake receipts and labels that secretly imply execution permission. Here receipts are explicitly **synthetic observations**. Code/commands are classification evidence only; no executor-safety labels were invented.
- Independent review must settle labels, useful family scope and multilingual quality before changing `label_status` or exporting a training set. Records with `annotation.admission_blocker` cannot enter that export until the blocker is explicitly resolved in the admission artifact; retaining a provisional UNKNOWN is not resolution. Maintain a separate signed admission/revision manifest rather than erasing the original proposing status. Unresolved examples remain quarantine; removing an unsuitable family is acceptable, forcing it into a narrow model is not.
- After permission, compare real-only versus reviewed-synthetic augmentation over increasing independent real groups. Evaluate complete-input coverage, class-specific false permission/release costs, group consistency, languages/ecosystems, lengths and native fit. Select calibration/abstention on reserved validation data, then evaluate once on locked real groups. Synthetic sibling accuracy is a diagnostic, not a production success claim.
- Actual training/resource readiness requires an admitted task/export, split and locked evaluation, pinned backbone, floating training plan, measured final-weight budget plan and separately approved compute handover. No training, inference, GPU handover, model/service swap, planner activation or new production guard is authorized by these files.
