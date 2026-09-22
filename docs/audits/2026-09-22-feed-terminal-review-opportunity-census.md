# Feed terminal `REVIEW.md` opportunity census — 2026-09-22

## Scope and method

Read-only census of the five retained terminal Feed attempts:

| score / run | capture session | terminal review boundary |
| --- | --- | --- |
| 5% / `1790014067` | `20260921T110810-01a0c527-6c46-74b3-bf8d-91cb6d18d707` | `0074-satisfaction` → `0075-coder-s3` |
| 25% / `1790021450` | `20260921T131112-01a0c598-12c3-7973-8ebd-3f87b1ce0016` | `0087-satisfaction-diagnosis` → `0088-coder-s3` |
| 65% / `1790024016` | `20260921T135359-01a0c5bf-3d05-7fd0-a573-6c95720f4526` | `0061-satisfaction` → `0062-coder-s2` |
| 65% / `1790026888` | `20260921T144153-01a0c5eb-172a-7002-b4cf-64ac66d26edf` | `0084-satisfaction` → `0085-coder-s2` |
| 65% / `1790034274` | `20260921T164500-01a0c65b-cd75-7ab3-b3dd-3d839bfb3b35` | `0106`–`0109-satisfaction` → `0112-coder-s3` |

For each boundary, the rendered request (`.prompt.txt`), exact outgoing body (`.json`), reply (`.response.json`), reasoning where supplied (`.reasoning.txt`), and the corresponding session events in `~/.cria/logs/cria-20260921.jsonl` were read. “Opportunity” below means a supported, current, task-scoped `missing_file` remediation for the explicitly named `REVIEW.md`, not its mere appearance in the original task/history or an inferred final-workspace absence.

## Census

| run | last actionable `REVIEW.md` opportunity | classification | exact evidence |
| --- | --- | --- | --- |
| `1790014067` | None established. | **Directive absent / not wire-delivered; no target-review opportunity to classify downstream.** | `0074-satisfaction.response.json` returns `missing_content` for `src/main/java/pipeline/Importer.java`, with the threading task quote and proposed importer repair; it does not return a typed `missing_file` subject `REVIEW.md`. The following `0075-coder-s3.json` therefore has no current review-remediation envelope. `0075-coder-s3.response.json` instead calls `exec_command` to inspect the Commons CSV API. This cannot prove that a review directive was dropped, because no supported review directive existed at this boundary. |
| `1790021450` | None established. | **Directive absent / correctly suppressed; no target-review opportunity to classify downstream.** | `0087-satisfaction-diagnosis.response.json` is exactly `UNDECIDABLE`. No typed, provenance-validated review diagnosis can be injected fail-closed. `0088-coder-s3.json` has no review-remediation envelope, and `0088-coder-s3.response.json` ends in prose about CSV column layout with `finish_reason: stop`. The stop is not evidence of a missed review directive: the antecedent diagnosis is undecidable. |
| `1790024016` | `0062-coder-s2`. | **Correctly serialized; coder takes a nonwrite action.** | `0061-satisfaction.response.json` returns `missing_file`, subject `REVIEW.md`, `workspace_absence`, and the exact task quote. `0062-coder-s2.json` contains the resulting task-named missing-file remediation. `0062-coder-s2.reasoning.txt` says the active work is adding/confirming OpenCSV; `0062-coder-s2.response.json` issues `read_file({"path":"pom.xml"})`, not a write. This is a delivered directive followed by inspection. |
| `1790026888` | `0085-coder-s2`. | **Correctly serialized; coder takes a nonwrite action.** | `0084-satisfaction.response.json` returns `missing_file` / `REVIEW.md` / `workspace_absence` with the exact document requirement. `0085-coder-s2.json` preserves that current remediation. Its complete reply explicitly says, “The completion check flags that `REVIEW.md` is missing,” then calls `list_dir` and `exec_command` to inspect `REVIEW.md` and the workspace before writing. There is no write call in that response. Later terminal turns continue benchmarking/inspection; they do not turn this delivered opportunity into a serializer loss. |
| `1790034274` | `0112-coder-s3`. | **Correctly serialized; coder takes a nonwrite action.** | The satisfaction tool lifecycle is complete: `0107` lists root without `REVIEW.md`; `0108`/`0109` continue the judge’s requested inspection; `0109-satisfaction.response.json` returns typed `missing_file`, subject `REVIEW.md`, `workspace_absence`. Event trace records `loop.negative_diagnosis_supported` and `loop.satisfaction_gap_named`, followed by compaction and `loop.item` step 3. `0112-coder-s3.json` contains the task quote, current absence statement, and bounded document remediation. `0112-coder-s3.reasoning.txt` says the remaining work is `REVIEW.md`; `0112-coder-s3.response.json` calls `read_file(Importer.java)` plus an `exec_command` to inspect output “before creating” it. Neither call writes the document. |

## Terminal transport facts

The first two attempts do not have a supported review-remediation frame. They must not be converted into a claimed wire loss merely because the terminal workspace lacked the document.

The three valid review diagnoses all reached the next actual coder body. Their immediate replies are nonwrite actions. The subsequent end of a capture (including proxy/context failures after an action) is not an additional “terminates before write frame” classification for that same opportunity: each already has a received coder frame and an observable nonwrite choice. Thus this cohort contains **zero** established cases where a supported review directive was created and the session terminated before its first coder frame.

## Shared-root decision

**Reject a single shared root.** The cohort splits before the alleged shared boundary:

- two sessions have no valid review diagnosis to serialize (one different supported importer diagnosis; one `UNDECIDABLE`), and
- three sessions serialize the supported review diagnosis into the immediate next coder request, after which the coder selects inspection/verification rather than a write.

This rejects the proposed shared judge-to-coder delivery ceiling and also rejects any deterministic candidate whose claimed effect is “make the next coder write `REVIEW.md`.” That would test an action choice rather than a cria-owned wire invariant.

## Candidate status and exact-capture criteria

No candidate is supported by all five captures, so no fails-before/passes-after test is proposed.

The only precise criteria retained for a future *delivery* candidate are falsification guards, not acceptance evidence for an implementation:

1. A fixture based on `1790024016/0061`→`0062`, `1790026888/0084`→`0085`, or `1790034274/0109`→`0112` must fail any assertion that a valid typed `REVIEW.md` gap is absent from the following serialized coder body.
2. It must not assert that the recorded following reply writes `REVIEW.md`; the exact replies are nonwrites.
3. A fixture based on `1790014067/0074` or `1790021450/0087` must not manufacture a review verdict: respectively the recorded terminal verdict concerns `Importer.java`, and the recorded diagnosis is `UNDECIDABLE`.

These are evidence-preservation constraints only. They are not fails-before/passes-after support for code because the alleged delivery failure is absent from the exact captures.

## Invalidated prior inference

The terminal document absence and usefulness scores remain outcome evidence. They do **not** establish one common delivery defect. Any earlier statement treating all five terminals as proof that `REVIEW.md` remediation was silently lost on the wire is invalidated by this census.
