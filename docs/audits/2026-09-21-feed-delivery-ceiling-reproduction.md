# Feed delivery-ceiling reproduction reset — 2026-09-21

## Question and cohort

This is a deterministic trace reconstruction of the five terminal Feed captures, not a Feed rerun and not a replay of a final workspace. The cohort is `1790014067`, `1790021450`, `1790024016`, `1790026888`, and `1790034274`; the active `2fd69ae` run `1790038818` is deliberately excluded.

The proposed failure was: a typed, current `REVIEW.md` absence was found but did not reach the next coder's authoritative frame. That is an observable wire claim. It must be proved from the ordered plan frame, survey-backed judge interaction, and subsequent coder body; a final workspace without `REVIEW.md` cannot prove it.

## Result

The claimed shared plan-to-coder delivery ceiling **does not reproduce**.

The last comparable chain, `1790034274`, is complete and decisive:

1. The plan's active coder frame is capture `0112-coder-s3.json`. Its system/current-step framing is step 3, and its body contains the original task, the compacted work record, and the fresh workspace inventory. It is not a terminal-artifact reconstruction.
2. The periodic satisfaction interaction is `0106` through `0109`. It uses the workspace survey inventory, then its own read-only `list_dir` lifecycle: root (`0107`), `tmp/` and `src/main/` (`0108`), then their children (`0109`). `0109-satisfaction.response.json` returns the typed `missing_file` verdict for task-named `REVIEW.md`.
3. After the resulting self-compaction (`0110`/`0111`), the next real coder body, `0112-coder-s3.json`, contains the delivered periodic-gap envelope verbatim: the exact task requirement, `workspace_absence`, `The task-named file REVIEW.md is not present in the current workspace.`, and the bounded proposed fix. It is the current active user message immediately after the fresh file inventory.
4. The coder's reply to that authoritative frame (`0112-coder-s3.response.json` and `.reasoning.txt`) recognizes `REVIEW.md` as remaining work, but chooses another inspection/verification turn instead of writing it. That is a later action-selection outcome, not a missing delivery from cria.

Two other post-frame-fix captures independently contain the same delivered typed gap in their next actual coder body: `1790024016/0062-coder-s2.json` and `1790026888/0085-coder-s2.json`. They therefore also falsify the assertion that the periodic gap was silently lost between the judge and coder.

The remaining two captures are not evidence for that assertion:

- `1790014067/0075-coder-s3.json` predates the revised framing and still carries the former `Do ONLY this step … then stop` wording. Its satisfaction verdict at `0074` names unmet importer content rather than a checked `REVIEW.md` absence.
- `1790021450` reaches `0087-satisfaction-diagnosis.response.json`, whose support answer is `UNDECIDABLE`; it supplies no validated typed gap to deliver. Absence of a subsequent `REVIEW.md` directive is therefore correct fail-closed suppression, not a dropped directive.

## Why the exact replay passed

`tests/test_feed_delivery_boundary.py` calls `_frame_for_item()` on three archived terminal coder bodies and asserts that the new frame preserves the whole task and uses “Prioritize this step”. It deliberately has no live `PlanSession`, no periodic satisfaction call, no workspace-survey generation, no judge tool loop, no compaction, and no subsequent coder request. It can only establish the local framing transform.

That replay passed because the transform is correct. It could not establish that the historical 65% outcomes were caused by a delivery break. The full trace above shows that, where the typed gap was valid and current, the live path did deliver it. The final workspaces still lack durable artifacts because receiving an instruction and taking the next action are separate facts.

## Durable reproduction design

A future candidate must use one trace verifier, with `1790034274` as its primary fixture and `1790024016`/`1790026888` as corroboration. It must replay only recorded bytes and live path functions, in this order:

1. Parse the recorded plan-frame coder body; retain its active item and the original-task message.
2. Reconstruct the workspace view only from the recorded survey/tool results that the satisfaction judge actually consumed. Do not seed it from a final archive.
3. Feed the exact satisfaction request/response/tool loop until the terminal verdict; accept a gap only through `_negative_diagnosis_nudge`/`judge_satisfaction` typed provenance.
4. Preserve the actual compaction boundary when it occurred, then construct the following coder body through `_work_item()`/`_frame_for_item()` rather than calling `_frame_for_item()` alone.
5. Assert only wire facts: complete/current survey provenance; typed task-named absence; the gap in the following coder body; the original task and active plan frame remain present. Record the subsequent coder reply as evidence, never as an assertion about what a deterministic transform must make it do.

A fails-before test is intentionally not added now. The faithful trace has no delivery divergence to fail: a test that requires the subsequent coder to write `REVIEW.md` would encode a semantic/action decision as deterministic cria behavior, and a test that omits the survey, judge loop, or next outgoing coder body would repeat the terminal-artifact replay error.

## Consequence

This invalidates the previous report sentence that all five final captures proved a shared plan-to-coder delivery boundary and any candidate justified solely by that sentence. It does not invalidate the 65% usefulness judgments: the required review artifact is still absent. It invalidates only the asserted causal owner. No Feed rerun, code change, service restart, or interaction with the active `2fd69ae` run occurred during this investigation.
