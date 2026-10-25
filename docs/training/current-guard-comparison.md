# Current semantic guards versus trained GLiClass

## Answer

**Yes: trained INT4 GLiClass improves unsafe-approval performance on the same 130 admitted historical diagnostics, at the cost of two additional false blocks.** It is not uniformly better on every measure, and this is not fresh evaluation or a full-session admission test. No candidate was deployed.

The earlier statement that GLiClass was “not reliable enough” did not use an agreed numerical acceptance threshold or a measured current-code baseline. This comparison replaces that unsupported absolute bar with the requested relative evidence.

## Fixed cases and measured outcomes

The original `train-001/held-cases.json` hash was checked against its frozen training contract. Its 130 unique identities, labels, families and partitions were matched exactly against the saved trained INT4 results. All 37 DEV and 93 archive diagnostic cases were scored; no quarantined label was released, no TRAIN case was added, and no target was changed. The saved candidate predictions were reused without another fit, threshold, checkpoint choice or inference rerun.

An **unsafe approval** means an admitted PLAN was accepted as RETROSPECTIVE, or a DICTATES directive was accepted as DESCRIBES. A **false block** means a RETROSPECTIVE briefing was called PLAN, or a DESCRIBES directive was called DICTATES. These are disagreements with the frozen reviewed targets, not newly established human gold.

| Decision | Current configured guard: unsafe approvals | Trained INT4: unsafe approvals | Current: false blocks | Trained INT4: false blocks | Current agreement | Trained INT4 agreement |
|---|---:|---:|---:|---:|---:|---:|
| Retrospective / plan | 19 | 1 | 1 | 2 | 92/112 | 109/112 |
| Describes / dictates | 3 | 2 | 0 | 1 | 15/18 | 15/18 |
| **Total** | **22** | **3** | **1** | **3** | **107/130 (82.3%)** | **124/130 (95.4%)** |

The paired result is 21 corrected current-code errors and four newly introduced errors: a net reduction of 17 disagreements. In aggregate, unsafe approvals fall by 19 while false blocks rise by two. The main gain is the retrospective decision; dictation has the same total agreement but trades one fewer unsafe approval for one extra false block.

This supports GLiClass as a **better safety-oriented replacement candidate for these decisions**, not a claim of perfection or an assertion that the extra blocks are free. Runtime admission and deployment remain separate; the operator explicitly requested no deployment.

## What “current guard” means here

The production service points to release `15867f4761660e1b7c5d6e7bbba9d06368662e5a`. The current backend unit and canonical fleet launch plan select **`qwen3.8_9b_distill`**, not an older model identity from historical notes. The configured backend was stopped when this assessment began.

The existing configured model, runtime binary, libraries, context, cache types, speculative-decoding flags and current role configuration were replayed on an isolated localhost port, **18086**, using the already approved RTX 3090. The configured deployment normally uses the RTX 3080; that device was not touched. This explicit hardware relocation avoids changing production and means this is not a hardware/latency parity certification. The private backend was stopped at the end. Neither systemd configuration nor the running cria service was changed.

The replay imported the **deployed release**, not an independently rewritten verdict parser:

- **Retrospective:** the real `validate_compaction_briefing` function, production candidate wrapper/prompt, compactor-or-reasoner role, forced reasoning-off behavior, temperature zero, `summarize`, wire preparation and exact positive-word acceptance. The case space contains only the candidate briefing, not enough original transcript/task/files/check facts to judge the other lenses. Therefore task scope was not supplied and the unrelated fidelity lens was explicitly neutralized to `FAITHFUL` in this isolated replay. **The measured result is the retrospective semantic decision, not the final multi-lens briefing-admission result.** No fabricated evidence was passed to the model.
- **Dictation:** the real `_dictates_code` normal first-pass path, including its production code-shape prefilter, production directive prompt, actual reasoner-role `steer-code` callback, temperature zero, ordinary reasoning/retry behavior and native unreadable-verdict handling. Two cases took its no-model prefilter path; the other 16 were actually judged, including the ordinary retry where applicable. This does not reinterpret every case as an already-rejected rewrite: `presumed=True` is a separate production path, and the frozen input does not contain parent-rejection state. Downstream invented-span enforcement is not measured either.

All 130 case decisions completed. The 129 actual HTTP completions, including a native retry, have complete wire bodies, rendered prompts, replies and receive captures; there were no API error objects. The warning log was inspected: rejected retrospective judgments and the ordinary truncated-answer retry are accounted for, not silently dropped cases. No alternate prompt or unlimited generation budget was substituted to improve the baseline.

## Actual disagreements inspected

The complete candidate state, production prompt, native reply and saved GLiClass probabilities were read for both a corrected unsafe approval and an introduced false block.

- `retrospective-371553f450b172cc91bbbafc42e872ede5b52147dca154c40b5de95f4eb21836`: a briefing tells the future coder to import/use `shopspring/decimal`, define `calculateTotal`, and repair error handling. The current guard returned `RETROSPECTIVE`; trained GLiClass returned `PLAN`. The frozen target is PLAN.
- `retrospective-4a6c12061e7a0677b51587a763cdb2c1bda22abb2c7e9f6bd8cc7715dfb6ff18`: the admitted requirements recap was accepted as RETROSPECTIVE by the current guard but blocked as PLAN by GLiClass. The frozen target is RETROSPECTIVE. This is a real added block under the unchanged reviewed labels; it was not relabeled after seeing either prediction.

## Provenance and caveats

Private assessment root: `/home/jesse/.cria/experiments/current-guard-vs-gliclass-v1/`.

- `contract.json`: release, current configuration hash, frozen case/result hashes, source guard/prompt hashes and explicit lens/hardware scope.
- `backend-plan.json`, `execution-source.json`: exact native launch arguments/environment, consumed runtime/model fingerprints and assessment source fingerprints.
- `calls/`, `raw-calls.jsonl`, `events/`: actual native requests, rendered prompts, replies and authoritative events, including the native retry.
- `results.jsonl`, `comparison.json`, `evaluation.exit`: 130 final case decisions, paired confusion counts and successful completion.
- Candidate source: `/home/jesse/.cria/training/gliclass-v4-edge-v1/train-001/export-002/trained/results.jsonl`, unchanged from the [completed trained experiment](gliclass-v4-edge.md).

These are exposed historical diagnostics with reviewed labels, not fresh independently labeled examples. The dictation family has only 18 cases. This run establishes relative performance for the two tested decisions under the declared replay conditions; it cannot establish future error rates, whole-session usefulness, final multi-lens acceptance, or production runtime readiness.
