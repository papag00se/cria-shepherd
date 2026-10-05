# Recovered forensic drafts: evidence review, 2026-10-05

The two recovered September 6 drafts are preserved unchanged in
`4d52df02cbecec7fefd6cdb34aceaa5576416cc4` on
`recovery/unique-forensic-drafts-2026-10-05`. The edited documents here distinguish
source-confirmed facts from historical claims whose primary evidence is missing:

- [gigachat31 shipping/cart/orders](gigachat31-shipping-cart-orders-walkthrough.md)
- [ornith1.5_9b feed importer](ornith15-feed-pipeline-java-walkthrough.md)

This review uses code at `3edc3146542f6d575bd810238fc30e88aaaf052a`. It changes
documentation only. No historical result rows, fixtures, source behavior, service
configuration, or preserved refs were changed.

## Evidence and its limits

Original drafts were read privately with `git show`; complete bytes, including
quoted reasoning and code blocks, were reviewed. Their SHA-256 hashes are:

| Original path | SHA-256 |
|---|---|
| `docs/forensics/gigachat31-shipping-cart-orders-walkthrough.md` | `f1244563c72750be3ea088409d34f5b32d197fb3076965d769f7d9d87ccf2b54` |
| `docs/forensics/ornith15-feed-pipeline-java-walkthrough.md` | `1727da8d9e57900bd35dcabf2a37e340cc2c77c08d38298be1a5470ca7fadfd2` |

All four named native capture directories are absent. Exact-ID filename and
content searches covered `~/.cria/calls`, logs, suite archives/milestones,
quarantine, validation, walk findings and review scratch; the owned checkout;
and the shepherd reconciliation backup. Both reconciliation tar member lists
were inspected. A read-only query of
`/home/jesse/Work/recovery-placement/inventory.sqlite` found the retained Ornith
harness log and its former, now-absent candidate location, with no exact-session
capture paths. The resolved orders run ID was also searched. This documents the
available local sources, not a claim that no other backup can exist.

The surviving Ornith harness log was read completely and privately. Its original
bytes match the member in `working-tree.tar`. It contains harness-visible actions,
reasoning and results, but does not contain the complete serialized prompts and
all private supervisor replies. It therefore supports specific transcript
observations, not a full cria call WALK under [principle 23b](../principles.md).

Historical ledger records were read as structured records, preserving their
original run IDs and exact row hashes. Their scores, phase labels and assist
totals are **stored historical metadata**, not independently remeasured behavior.
Neither text occurrence counts nor repeated transcript renderings were used to
infer unique interventions, successful writes, or prevalence.

## Rules applied to the recovered proposals

Whatever the coder did, cria let it happen. A useful investigation must identify
the absent, silent, mistimed or wrong assist; it cannot end with an attribution
to the weights. A low usefulness score describes delivered work. It does not
prove why that work was poor or that a guard worked correctly.

An unread first write is not sufficient evidence to block a valid first attempt
([principles 2 and 11](../principles.md)). A repeated directory name does not
prove an invalid path. A compiler's unresolved symbol does not authorize an
implementation chosen from memory. A reasoner judges facts gathered through the
harness; it does not acquire a synchronous workstation executor. Real checker
output stays separate from authored advice.

The documents retain the investigation questions, correct source contradictions,
and record existing repairs. They do not install the drafts' proposed first-write
vetoes, lexical path rules, arbitrary new retry thresholds, or automatic symbol
inspection. Complete primary evidence and a current regression are needed before
such behavior can be justified.

Local nonsensitive evidence summaries and the exact reviewed-source manifest live
under
`/home/jesse/Work/git-reconciliation-2026-10-05/backups/shepherd/cria-shepherd/followup/validated-forensics/`.
Raw captures and sensitive transcript payloads are not reproduced in these docs.

## Validation

The existing dependency-cache, cache-root guidance, whole-action diagnostic,
supervisor scope, writeproxy, directory guard, rumination retry, completion-gate
and planning-policy regressions were run with `python -m pytest`. Result:
**235 passed, 71 subtests passed in 4.58s** (exit 0). The exact command and JUnit
results are in the external evidence directory. These are code-invariant checks;
they do not certify the missing historical WALK. No test or fixture was changed.

The historical/current dependency-access comparison independently reproduced the
pre-fix refusal and current acceptance using real source. Documentation checks
verify local links, original draft hashes, exact ledger-row hashes, harness-log
byte identity, seed provenance and the unchanged preservation ref.
