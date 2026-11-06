# TRAIN progress exemplars: clarity and meaningful nuance — 2026-11-06

**Completed assessment of all 3,000 selected TRAIN samples.** This answers the operator's teaching-value question, not merely whether a supplied label is defensible or an author fixture passes. It supersedes neither the original corpus nor the preserved [earlier label/fixture review](progress-correctness-data-review.md). That earlier review did not deliver this sample-level pedagogical assessment; describing it as a complete answer to sample quality overstated its scope.

## Result

Under the explicit rubric, **750 samples (25%) are not good exemplars: 731 weak examples plus 19 wrong targets**. Another **44 are ambiguous**, excluded from both good and not-good. **2,206 are good exemplars**. These are qualitative AI-assisted judgments under a stated standard, not independent human gold or operator-approved replacements.

| Original target | Good exemplar | Weak exemplar | Wrong target | Ambiguous | Total |
|---|---:|---:|---:|---:|---:|
| DONE | 951 | 0 | 19 | 30 | 1,000 |
| PARTIAL | 998 | 0 | 0 | 2 | 1,000 |
| NOT_STARTED | 257 | 731 | 0 | 12 | 1,000 |
| **Total** | **2,206** | **731** | **19** | **44** | **3,000** |

**Label support is a separate axis:** 2,949 supplied labels are clear and supported, 19 have a concrete counterexample, and 32 remain unresolved. Twelve additional cases have a clear NOT_STARTED label but genuinely debatable teaching value; these account for the difference between 32 label ambiguities and 44 overall ambiguities. All 19 accepted wrong targets are DONE-to-PARTIAL findings: actual implementation exists, but a stated obligation is unmet.

The source is `~/.cria/training/progress-correctness-v2/train-3000-candidate.jsonl`. DEV, the 836 older replay examples and the exposed benchmark are not included in these counts. The 3,000 rows are 1,000 related requirement groups, not 3,000 independently originated tasks.

## What was judged

The policy remains `cria/prompts/offline_onejev_progress.txt`: count only implementation contributed by the diff. Existing seed behavior, plans, claims and comments do not become new progress.

- **Good:** defensible target, concrete implementation witness and nearby contrast, with at least modest task-specific nuance.
- **Weak:** clear/correct target but thin instructional content, such as generic filler without a meaningful relevance contrast.
- **Wrong:** a concrete written-contract counterexample disproves the supplied target.
- **Ambiguous:** the contract, required context, or good/weak distinction remains genuinely unresolved; specify competing interpretations rather than fabricate gold.

Simple examples, minimal operator changes, one missing function and unrelated edits are not inherently weak. A tiny boundary defect can be an excellent PARTIAL example. An unchanged, substantive seed can create a useful attribution trap beside a tiny helper. Conversely, the right filename, a domain word or an isolated scalar constant does not by itself supply meaningful nuance. Weak does not mean an empty-diff baseline is invalid or never useful; it means thin additional teaching range in this corpus.

## Method and consistency corrections

Ten Pi-hosted Terra/Sonnet reviewers individually read the complete requirement and diff for every assigned original, with supplied targets and prior review evidence available. Their 3,000 persisted primary rows cover every source ID exactly once, with no missing/extra/duplicate IDs or original-target mismatches. All ten summaries are present.

A purposeful 87-case calibration exposed inconsistent judgments of similar NOT_STARTED helpers and seed contexts. It was not a random prevalence sample. Therefore all 1,000 NOT_STARTED originals received a second individual pass, not an extrapolated correction. Both 500-row passes and their summaries are complete. Additional shared-boundary and disputed-contract reviews, including explicitly prompted qualifications, remain visible. Eighty-eight explicit coordinator adjudications resolve contract and quality issues after full-original inspection.

The final merge uses primary assessment, designated full NOT_STARTED second pass, then coordinator adjudication. Original and superseded prose are preserved separately; the final view uses the authoritative rationale rather than inherit a contradictory earlier quality explanation. Scripts organize, join, count and render judgments; they do not infer semantic verdicts from names, tags, length, sibling balance or keyword matching.

Important boundary resolutions:

- A one-expression seed is not automatically trivial: the beam reaction's existing force aggregation provides a real pre-existing-work trap. Its initial weak judgment and original example-file selection remain preserved.
- A whole-list count versus the required false-entry count provides a modest operation near-miss. Total string length versus per-run lengths remains a genuine good/weak disagreement, with a clear NOT_STARTED label.
- Seventeen isolated bound/size constants initially called good in one second-pass half were individually reinspected and adjudicated weak, consistently with bare constants in the other half. Their unchanged initial good/medium opinions and sensitivity note remain inspectable. This is a judgment boundary, not a measured universal quality law.
- Build/run sentences are read consistently across languages as source buildability/run context, not an additional missing tool-log target under this diff-only implementation policy. Seventeen earlier process-only ambiguities are resolved on that basis, without claiming any build happened. A literal C link command with no `main` remains ambiguous.
- Explicit rejection clauses are not narrowed by inventing an integer-only or String-only caller guarantee. Initial contrary secondary opinions and their prompted revisions remain visible, not counted as independent corroboration.
- Safe integer inputs can still produce inexact intermediate JavaScript products or sums. Concrete static counterexamples, rather than private fixture magnitudes, ground the numeric findings.

## Findings and their limits

The 731 weak examples are all NOT_STARTED. Repeated empty changes, notes/settings/version helpers and disconnected trivial helpers contribute little task-specific instructional range. The 257 good NOT_STARTED examples include meaningful seed-versus-diff attribution, operation near-misses, same-function behavior-preserving edits and substantive off-target work. The remaining twelve retain explicit good/weak uncertainty.

DONE/PARTIAL examples often contain useful distinctions: rounding, inclusive bounds, ordering, state, error propagation, exact arithmetic and cross-file integration. But good individual minimal pairs do **not** certify a representative corpus. The repeated balanced-triple, complete-looking implementation plus planted-defect construction remains narrow compared with naturally unfinished work. A small edit can also cause a large semantic failure, so line counts cannot measure how nearly complete a PARTIAL is. Alternative complete approaches and varied early/mixed-progress states remain insufficiently represented in the inspected construction. No new universal prevalence percentage is inferred from local shard observations or inconsistent tag vocabularies.

The nineteen wrong targets include the [earlier eleven](progress-correctness-data-review.md#concrete-incorrect-done-labels), plus empty-query overlap, an inherited symbol bucket, exact polygon classification, Vigenère key rejection, safe-integer remainder rounding, priority integrality, polygon simplicity and sparse weight-array validation. Full IDs, clauses and static counterexamples are in the inspection pack. One newly proposed long-leading-zero Python parsing error remains **ambiguous**, because its disposition depends on interpreter/conversion-limit context missing from the visible sample; it is not added to the accepted-error count. Another new ambiguity concerns arbitrary poker suit strings permitting an unspecified five-of-a-kind hand.

These findings do **not** establish the cause of the twelve-pass training deterioration. In particular, thin NOT_STARTED examples do not demonstrate why DONE/PARTIAL learning went poorly. No model capacity verdict, causal ablation, fresh generalization claim or serving qualification follows from this review.

## This target is not a completion checklist

These progress inputs ask whether code behavior satisfies a written requirement. That is semantic code assessment, not simply observing that files and passing test results exist. The older 836 examples instead teach retrospective-versus-plan and description-versus-code-dictation distinctions; successful fitting there does not qualify this different responsibility.

For an evidence-based completion judgment, deterministic code should gather authoritative execution and filesystem facts; a reasoner judges whether those facts cover the actual task. File existence alone is not implementation, and green but inadequate tests are not proof of every obligation. A classifier should not be expected to invent execution evidence absent from its input. This distinction records the operator discussion; no runtime architecture, prompt or training target was changed.

## Inspect the originals and all judgments

Private assessment root: `~/.cria/training/progress-correctness-v2/exemplar3000-20261106T175757Z/`.

- `report.md`, `accounting.json`: final scope, category and label-support counts, complete 3,000/1,000 ID coverage, all summaries and no recorded accounting problems.
- `review.html`, `inspection-records.jsonl`: offline searchable full originals, primary judgments, NOT_STARTED second pass, calibration/secondary opinions, prompted qualifications and final coordinator reasoning.
- `RUBRIC.md`, `CONSISTENCY.md`: original assessment standard and the reason the complete second pass was necessary.
- `shard-*/output/assessment-*.jsonl`, `summary.md`: original primary decisions, not overwritten by final dispositions.
- `negative-consistency-*/output/review-*.jsonl`, `summary.md`: all 1,000 individually reasoned second-pass records.
- `adjudications.jsonl`: 88 final coordinator findings; `adjudications-known.jsonl` and earlier reviews remain separately retained.
- `operator-examples/`: readable unchanged empty-change and PCAP-version weak examples, plus the paired late-day rounding PARTIAL and boundary-complete DONE. The initially selected beam helper file remains alongside its transparently corrected selection; no file was silently replaced.

No sample, fixture or generated check was executed; no classifier inference, training, augmentation, replacement corpus, checkpoint/prompt change or deployment was performed. Existing author outcomes are context, not new certification. No new tests were written for this analysis/documentation-only work. Originals, previous reviews and the selected aggressive checkpoint remain unchanged.
