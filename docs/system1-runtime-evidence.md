# Runtime evidence: requirement-status research, periodic review, and System 1

Historical inspection, 2026-11-06. This separates three different mechanisms in response to the operator's questions: did cells run, did the mechanism fire, and did it help? No new cell, inference, training, model swap, or service restart was performed. Reading saved calls and accounting for structured events is not a new model evaluation.

## The trained requirement-status classifier was never deployed

The experimental `progress` family predicts DONE/PARTIAL/NOT_STARTED from a requirement and seed-to-snapshot diff. It is not connected to cria's completion or periodic-review path. There are offline training and scoring results, but no deployed intervention from that family to attribute a coding result to. The production classifier remains the expanded-v2 INT4 bundle with only retrospective and dictation families.

This is different from the existing reasoner-based periodic whole-task review. Its revised cadence was committed as `45993acdbc61aeebb53b17e289f31b32d349e5e8` on November 4: initially eight minutes of coder work, then four, converted to turns with bounds. The November 5 rerun revision, `7a32e8b9f7465937bfbc5457ff36246157db3f23`, includes that change. Inspected lane configuration also explicitly selects eight/four and the production System 1 bundle.

## Cells after the periodic-review timing change

The retained `l5-red-20261105` campaign has 17 distinct scored run IDs in `suite/results/results.jsonl`. Sixteen record periodic satisfaction checks, totalling 38 `loop.satisfaction_check` events. Direct inspection of the corresponding session-filtered lane logs reconciles those counts; all 38 final review-path events report `satisfied=false`. This is the final path's disposition, not a claim that every underlying reasoner reply rejected completion.

Three `loop.satisfaction_gap_named` events record queued feedback. These are not three verified recoveries or three specific missing-feature diagnoses. Two say that required test execution was not proved; the third says completion could not be confirmed. One queued message was also verified in the subsequent coder request, rather than assuming that a queued event establishes delivery.

A fully opened example is `gemma4_12b / Ruby`, run `shipping-rates-rb_gemma4_12b_codex_poff_1793918182`:

- Request/response/reasoning `0122-satisfaction` show an incomplete verdict, no available current file bodies, and a diagnosis subsequently suppressed with `evidence quote is not exact`.
- The complete `0135-satisfaction` prompt contains newer coder tool outputs reporting `9 runs, 9 assertions, 0 failures, 0 errors, 0 skips`, alongside a stale gate block saying no tests executed and test participation was unknown. Its raw reasoner reply approves completion, but the final review path does not.
- The queued test-verification warning occurs in `0137-coder-s1.json`, message 31. This establishes delivery of that warning, not its necessity, correctness, benefit, or the correctness of the whole shipping implementation.

These calls expose evidence availability, conflicting test evidence, diagnosis grounding, and delivery as concrete investigation targets. They do not establish that more frequent review improved coding outcomes. Final usefulness percentages are not judgments of whether a particular earlier approval or refusal was correct.

## System 1 has actually run in coding cells

At least 191 distinct stored run IDs have a positive `assists["system1.judgment"]` count in the latest retained result row for each ID. This is a lower bound on recorded runtime use, not a count of independent semantic evaluations or all sessions ever run. The initial two October deployment cells are not the entirety of System 1's runtime history.

Within the same 17-row November 5 campaign, 16 cells record 139 System 1 judgments. Direct session-filtered events reconcile them: 100 RETROSPECTIVE, 33 PLAN, three DESCRIBES, and three DICTATES. Those are classifier answers, not accuracy counts. No claim that all 33 PLAN or all three DICTATES judgments were correct follows from this accounting.

Two individually inspected examples establish actual policy enforcement:

- `phi4 / Node`, run `handles-cli-node_phi4_codex_poff_1793911194`: native capture `system1/0007-system1-retrospective.json` contains future-facing instructions under "Outstanding," including "Ensure," "Verify," "Add tests," and "Create a Dockerfile." System 1 answers PLAN; the same-turn `context.compaction_validation` event records `accepted=false`, lens `retrospective`. This is an observed, policy-supported briefing rejection.
- `ornith1.5_9b / Ruby`, run `shipping-rates-rb_ornith1.5_9b_codex_poff_1793918192`: native capture `system1/0015-system1-dictation.json` prescribes swapping a Ruby require statement. System 1 answers DICTATES. Same-turn `loop.steer_dictated_code` and `loop.steer_outcome` events report `delivered=false` and `refused_by='dictated_code'`. This establishes that the directive was withheld under the code-dictation policy, not that withholding it improved the shipping code.

There is also a concrete miss, not just successful examples. The complete first fresh October deployment capture, `~/.cria/calls/20261025T134610-01a174d0-4add-7a91-9ae5-b28dd2b8014e/system1/0001-system1-retrospective.json`, answers RETROSPECTIVE despite a "What remains to be done" section instructing the future agent to "Rewrite" the importer and "Verify" the rewrite. That conflicts with the exact policy carried in the request. It does not establish that the briefing reached the coder; other validators are independent. This is an AI-assisted policy assessment of one original, not human gold or an aggregate error rate.

## What “helped” is supported

- The trained requirement-status family has no demonstrated live benefit because it was never connected.
- The revised periodic reasoner check was exercised and delivered at least the inspected warning. These observations do not show improved coding outcomes.
- Production System 1 was exercised, and the opened November cases demonstrate correct local guard actions. The opened October case demonstrates a real policy miss. Neither correct local enforcement nor an overall cell score establishes a controlled coding-usefulness improvement.

The missing evidence is not whether these mechanisms ever ran. They did. It is whether the relevant decisions were correct across real cases and whether their interventions improved the work. The saved runtime evidence permits investigating those questions without beginning another training run.

## Evidence locations and accounting scope

Private inspection output is `~/.cria/training/progress-origin-20261106/runtime-evidence/`: `nov05-original-result-rows.jsonl` preserves the full selected result rows; `nov05-raw-events.jsonl` preserves selected original events with their source log paths and run IDs; `accounting.json` records the bounded counts. Native captures retain full policy, input, rendered input, token IDs, and response. Classifier captures do not contain generative reasoning, and none is inferred.

Lane log/capture roots used for the individually opened November cases:

- `~/.cria/suite/_lanes/3080x2/rows/phi4-L5-1793911182/`
- `~/.cria/suite/_lanes/3080x2/rows/gemma4_12b-L5-1793918172/`
- `~/.cria/suite/_lanes/3090x4/rows/ornith1.5_9b-L5-1793918182/`

All counts describe saved historical records at inspection time, not a fresh campaign or current operational prevalence. Selected source captures were opened in full; the 191-run accounting is not a claim that all 191 runs were individually semantically reviewed. See [System 1 technical reference](system1.md) for deployment boundaries and [training results](training/gliclass-expanded-v2.md) for the distinct reserved-synthetic evaluation.
