# Selected progress TRAIN/DEV data review — 2026-11-06

**Exhaustive two-phase review complete.** All selected 3,000 TRAIN and 600 DEV samples have an individual labels-hidden judgment and a final label/fixture review. All twelve shard summaries exist; there are no missing, extra or duplicate IDs and no original-label mismatches. This is analysis, not a corrected dataset release.

## Bottom line

There are serious corpus-quality problems. The strongest broad finding is not that most labels are wrong: it is that the examples are narrow, artificial and contain powerful label-correlated shortcuts. There are also concrete incorrect DONE labels, underspecified contracts, missing classifier-visible context and author fixtures that exercise the planted defect but leave other obligations unchecked. These findings justify questioning this corpus as the basis for progress judgments; they do not establish why the preceding twelve-epoch run deteriorated.

The original construction guidance already warned against scaling the pilot's addition-only diffs, unrelated-file NOT_STARTED examples and single planted defects. The selected expansion retained substantial versions of those same patterns. Family names and passing author checks did not establish that the design objective had been met.

## Scope and method

The exact reviewed inputs are `~/.cria/training/progress-correctness-v2/train-3000-candidate.jsonl` and `dev-600-candidate.jsonl`, the selected progress inputs used by the twelve-pass continuation. The separate 836 old replay cases and the former TEST/exposed benchmark are outside this review. No fresh qualification set was opened or created.

Twelve Pi-hosted Terra/Sonnet reviewers each received 300 complete samples. They persisted individual labels-hidden judgments before opening original labels and complete author fixture programs/results. Group membership organized work; it was not a constraint requiring one judgment of each label. Original IDs, full requirements, full diffs, initial judgments and later fixture findings remain inspectable. The coordinator read disputed contracts/code and relevant full fixture context, and requested additional independent labels-hidden reviews of 65 distinct cases. Six later prompted reconsiderations are explicitly marked as follow-ups, not additional independent blind votes.

The policy is `cria/prompts/offline_onejev_progress.txt`: only diff-contributed implementation counts; DONE requires the entire stated obligation, PARTIAL some implementation with an omission/error, NOT_STARTED no implementation. Review ambiguity is recorded separately rather than forced into purported gold.

This was static AI review. No sample or fixture was executed, no classifier/model computation or fitting was performed, no training inputs/checkpoints/generators/prompts were altered, and no original label was changed. Existing author execution results were read, not rerun. AI agreement is not the operator's personal review or independent human gold. Initial reviewers sometimes disagreed over input domains; their initial opinions remain visible alongside coordinator adjudications. A prompted correction is not independent corroboration.

## Final accounting

The primary reviewers proposed 3,550 agreements, 36 ambiguities and 14 label errors. These are proposals, not accepted-gold counts. Every one of the 50 disputed primary IDs has a coordinator adjudication; additional lower-confidence and secondary-review concerns were also inspected.

Across 74 escalated IDs, latest coordinator dispositions are **11 confirmed label errors, 50 specification/context ambiguities and 13 concerns not sustained**. The 50 ambiguity dispositions include concerns found in rows initially marked agree; they are not the same set as the 50 disputed primary IDs. Some are minor contract clarifications and some are important missing evidence; they are not 50 demonstrated code defects. Seventy-five adjudication-history records retain one superseded finding, rather than silently overwriting it. All eleven confirmed errors are TRAIN DONE-to-PARTIAL findings. No definitive DEV relabel is established; that does not certify DEV, whose structural shortcuts and unresolved contracts remain serious.

There are 105 explicit primary `repair_fixture` actions over 35 groups, separate from label errors. These count only that action category, not all fixture gaps recorded in narrative findings. They do not mean 105 corrupted samples.

## Concrete incorrect DONE labels

The coordinator identifies eleven TRAIN samples as PARTIAL rather than their supplied DONE. Each has real implemented behavior but a concrete written-contract violation. This is a finding under the stated contract, not a claim that every other sample is semantically certified. Full static traces and exact clauses are in `adjudications.jsonl` and the inspection page.

- `60e4c57e80fa446ebc1ff051fd329ca4`, Ruby cross-track calculation: `d/r` uses integer division. `cross_track(1,90,0,2)` returns zero instead of the stated formula's result one. Fixtures use a floating distance for the nonzero case, masking the error.
- `596564d09ca34be683ab20e45f07db20`, JavaScript bond settlement: an absent seller named `toString` is read through `Object.prototype`, bypasses the insufficient-holdings check and can be approved with a NaN balance. Missing accounts are explicitly zero and names are not restricted. Fixtures only use ordinary explicit accounts.
- `042ce5a169a4486aae1f7d68f7093cda`, Ruby enabled flags: the requirement selects fields equal to true; the code uses truthiness. A JSON enabled value zero incorrectly lists the flag. The input object schema never restricts enabled to booleans.
- `adc5a327c130417fa253baca23b19832`, Python HMAC verification: an arbitrary nonmatching string must produce false, but non-ASCII supplied text such as `é` makes string `compare_digest` raise TypeError. No ASCII-only supplied-string precondition was stated.
- `310e38239a58402cb4bdeedc3292b2ac`, Ruby rail-fence cipher: the explicit integer-at-least-two/ArgumentError-otherwise clause is not implemented by merely comparing `rails < 2`. A nil rail argument raises NoMethodError instead.
- `d040b6c007f74da5a2d8edf338a5977a`, Python yogurt labels: missing cups in a CSV data row becomes None; `int(None)` raises TypeError, not the specified ValueError for invalid counts. The requirement has no exact-field-count precondition. Existing output preservation in the CLI is implemented correctly.
- `703e68d30ebd477e87737f05673acb83`, JavaScript homophonic decoder: `some` skips sparse array holes, so `decode(Array(1))` returns an empty string rather than rejecting an invalid token array as explicitly required.
- `1b41585014494b219a4dcf41197bd8ab`, JavaScript order replacement: add never checks duplicate IDs, although uniqueness is an acceptance condition followed by otherwise false/no change. A second add of the same ID returns true and appends another order.
- `c963b88bc6d146d5866641543b660c2a`, JavaScript header lookup: Unicode lowercasing equates Kelvin sign with ASCII k, although equality is defined ignoring ASCII case only. The requirement does not restrict property strings to ASCII. A Kelvin-sign key incorrectly matches k.
- `7f586e5566474043a225b541370bc151`, Ruby diff-hunk parser: `each_line(chomp:true)` removes CR together with LF from content, while the contract removes trailing LF only. A content line ending in CR loses data. This is not a generic requirement to accept arbitrary malformed diffs; CR may be valid content in an LF-delimited diff.
- `40e5b6684bb648d8b0d9847490496985`, Python calendar closure: after processing valid final date 9999-12-31 the loop unconditionally constructs the next day and raises OverflowError. With that sole date closed, the required answer is simply an empty list. Both required input and output remain within the supported date range.

Some are boundary or type-contract cases, not typical day-to-day workloads. The point is not that every application needs every exotic input; it is that synthetic gold must either state the narrower domain or meet the domain it actually states. Conversely, no validation obligation was invented where the text only supplies a precondition.

## Ambiguity and missing visible context are separate findings

Do not add all proposed reviewer errors or ambiguities to the confirmed-error count. Examples requiring clarification include:

- Inline JSON versus filename for a terrain CLI: the requirement says read a JSON grid from the first argument, while code and fixture read a filename. This is an actual specification/fixture interface mismatch; intent cannot be settled by trusting the fixture.
- Whether conveyor bins must contain unused route destinations with zero totals.
- Ruby string versus symbol hash keys, unspecified value types, exact whitespace/sign grammars, SQL output names versus positional tuples, ordering conventions, and empty-image representations.
- A dice assignment task relies on `score.rb`, absent from the model-visible diff. The private scorer demonstrates greedy failure (15 versus optimal 31), supporting the author's PARTIAL, but the classifier input lacks the scoring semantics needed to establish that concrete case. Private evidence does not retroactively become model input.
- Imperatives to actually build/run Go offline ask about process events not recorded by a source diff. The shown implementations can be correct while this separate obligation is unobservable. This is not a demonstrated compilation defect or a reason to relabel them all PARTIAL.
- A culture-name restriction can be a caller precondition or a required invalid-field rule; it must not be converted into validation by assumption.

Some reviewer concerns were not sustained: the C width declaration exists in the full seed, migration never promised failure atomicity, extra legal XML escaping is not prohibited, and a fully LF-terminated four-line FASTQ with empty sequence/quality is not rejected by the shown splitter. Those opinions remain in the record rather than being quietly removed.

## Corpus-wide shortcuts and limited representativeness

The full structural census covers all 3,600 inputs; all 1,200 group requirements and selected overlap pairs were read separately from the primary semantic reviews.

- **193 of 200 DEV NOT_STARTED diffs have a `.txt` header; zero of 200 DONE and zero of 200 PARTIAL do.** One identical project-notes diff occurs 66 times. This is a very strong available surface cue, not evidence that the classifier actually uses it.
- TRAIN repeats a no-task-file-changed evidence string 146 times and the same settings decimal change 44 times. The structural zero-added/deleted-line category contains 160 NOT_STARTED and no DONE/PARTIAL rows.
- In the fully reviewed 300-row shard-04, every NOT_STARTED only adds a tiny unrelated helper; all 100 PARTIALs pass verifier one and fail verifier two; 79 of the 100 DONE/PARTIAL pairs differ by one replaced line. Shard-06 likewise has 100 unrelated-helper NOT_STARTED examples and 100 planted-second-verifier PARTIALs. These are not whole-corpus percentages, but substantial directly inspected examples of the construction pattern.
- All groups are balanced triples, not independent three-task draws. Repeated ordinary-case-plus-planted-defect construction makes the partial-progress distribution much narrower than naturally unfinished coding work. Minimal pairs can be useful, but not as the dominant substitute for varied workspace states.
- All sources say synthetic-hand-authored. All 600 DEV origins and 1,659 TRAIN origins are missing/unrecorded. The 171 TRAIN family IDs and 15 DEV IDs do not prove 186 independently originated projects. TRAIN includes Go, Rust and C; DEV contains none of those languages, limiting the generalization claims DEV can support.

No filename stripping, input truncation or shortcut classifier was built. The remedy is realistic evidence and sampling, not hiding true tool/file information from the model.

## Fixture weaknesses are not automatically bad labels

All selected rows join to retained author evidence. The selected rows have 7,326 recorded fixture outcomes; these are prior author checks, not independent certification or executions from this review. The older 7,138 count described a different working-pool snapshot and is not the selected-row total.

Concrete fixture weaknesses include Go Merkle proofs tested only at depth one; a track-merge expected output identical to plain concatenation, so sorting is not discriminated; a log-ID change always coinciding with shrinkage; a queue fixture containing no running job despite its slot-consumption clause; exact Rational/floor obligations exercised only with exactly divisible values; and incomplete poker category coverage. Several no-progress seeds also pass non-discriminating empty/zero or throw-only checks.

Shard-06 explicitly recommends fixture repair for 32 groups, represented on 96 sibling rows. That is **32 weak fixture groups, not 96 corrupted examples**. Other reviewers record more gaps without using the same action classification, so counts of `repair_fixture` actions are not a complete fixture-defect prevalence measure. Shared group-level author rationale is non-model-facing metadata, not itself a sample defect.

## Split independence was not established

There are no exact repeated requirement-plus-diff inputs or exact cross-split requirement/evidence matches. Exact matching does not exclude translations, common task cores or shared provenance. Directly inspected close cross-split cores include contiguous capacity packing in Python/Ruby, union-map reconciliation, original-coordinate string replacements and closed-rectangle selection.

These weaken a strong task-disjoint evaluation claim. They do not prove copying or a common author origin. Standard overlap predicates or cipher conventions alone are not proof of leakage. The existing DEV-author exposure incident remains historical provenance; this review does not erase it or invent direct reuse. There was no comprehensive semantic near-clone clearance.

## Recommended next action, not performed

1. Preserve these originals and training history. If a corrected corpus is authorized, make a separately identified revision; do not silently rewrite what the historical model saw.
2. Repair confirmed examples or deliberately narrow their stated domains, and independently exercise the missing contract cases. Clarify/exclude unresolved requirements and provide all necessary classifier-visible helper context.
3. Replace the dominant distractor and one-planted-defect construction with varied, genuinely coherent coding states, including real partial implementations, several simultaneous omissions, refactors, migrations, correct alternatives and incidental documentation across labels. Do not pad to a count or merely rebalance extensions.
4. Track actual source/project ancestry, group transformations and close task cores together, and obtain genuinely separately originated evaluation material before making generalization claims. The exposed benchmark remains exposed.
5. Let the operator inspect the actual corpus before deciding on another data-build/training experiment. No such experiment, correction build, deployment, export or publication is authorized or performed here.

## Inspection and evidence

Private review root: `~/.cria/training/progress-correctness-v2/review3600-20261106T161512Z/`.

- `review.html`: offline full-sample inspection, original labels, primary proposals, secondary reviews and coordinator decisions; filters include confirmed errors. Complete author seed/fixtures/results are separately labeled as non-model-facing evidence.
- `inspection-records.jsonl`, `inspection-summary.json`: page data and coverage snapshot.
- `review-result.json`: exact per-shard unique-ID coverage, mismatches/duplicates, primary proposals, latest coordinator dispositions and limitations.
- `shard-*/output/blind*.jsonl`, `final*.jsonl`, `summary.md`: all primary judgments and fixture reviews.
- `secondary-01..03/`: 65 additional labels-hidden judgments. `secondary-02/qualification.jsonl` preserves six coordinator-prompted follow-ups; those are not independent blind votes.
- `adjudications.jsonl`: coordinator history, retaining a superseded finish-window collation-only decision alongside the later missing-schema finding. Latest record per ID governs summary counts.
- `selection-facts.json`, `structure/{facts.json,report.md,inspection-notes.md}`: selected-evidence join, full structural census and directly inspected overlap leads.

A duplicate consolidated shard-05 review file was an identical copy of its 300 incremental records, not another 300 reviews. It was preserved under `output/provenance/`; the canonical incremental set contains one record per ID. A copied original-label field was corrected against the source without changing the blind judgment. Small ID transcription corrections and reviewer follow-ups are disclosed in shard summaries.
