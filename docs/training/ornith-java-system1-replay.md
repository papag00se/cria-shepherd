# ornith1.5_9b / Java: key-call System 1 replay

## Result and scope

The actual trained four-bit GLiClass artifact was run on CPU against **all ten admitted, exact-source guard cases** found in the fixed three key historical sessions (provenance runs 025–027). **Six guard decisions change:** two admitted PLAN targets that originally passed the retrospective guard are now blocked, and four admitted RETROSPECTIVE targets that originally failed are now allowed by that lens. The remaining four decisions are unchanged.

Agreement with the unchanged reviewed targets rises **4/10 → 10/10**; reviewed unsafe approvals fall **2 → 0**, and false blocks fall **4 → 0**.

**All ten cases were in TRAIN.** This is an exposed, training-case counterfactual demonstration, not new generalization evidence, fresh evaluation or human gold. It establishes changed guard decisions—not a changed Java implementation, a higher usefulness score, or proof that a resumed coding session would finish. The Java task was not rerun, no campaign score changed, and nothing was deployed.

## Selection and provenance

Selection was fixed before inference: take every case in the frozen admitted corpus whose exact recorded source belongs to any of these original sessions:

- run 025: `20261023T104755-01a169e0-63df-7c90-96ba-4cba4a974a13`
- run 026: `20261023T120001-01a16a22-63a4-7533-a913-16ebca571a0a`
- run 027: `20261023T161447-01a16b0b-a442-7843-bcc6-cc4f180fdcae`

The source inventory is `~/.cria/training/decision-qualified-v1/candidates.jsonl`; admission and reviewed labels come only from the immutable GLiClass training/held exports. Their file hashes were verified against the original training contract. Each selected request hash and exact decoded field span were checked against the complete admitted candidate string, without clipping, trimming or source transformation. Original public replies were read from their saved response captures, not regenerated with today's different backend. Original retrospective replies passed through the existing exact-positive verdict behavior; original dictation replies passed through the existing native verdict parser. Unrelated briefing-fidelity judgments were not scored.

The earlier twelve-case selection is not silently treated as admitted: only five of those exact raw candidate strings match the final admitted corpus. The other seven were not newly scored or admitted, and no held/quarantined label was released. Selecting all admitted cases in the three fixed sessions yields the ten cases below, rather than cherry-picking the five overlapping older examples or selecting only changed predictions.

The candidate is the saved trained INT4 artifact under `~/.cria/training/gliclass-v4-edge-v1/train-001/export-002/`. The same complete-input renderer, frozen policy bytes, native label semantics and CPU execution provider were used. No thresholds, labels, weights, option order or model configuration were changed. Preparation used the production-compatible Python interpreter for the original verdict path; inference used the isolated native CPU toolchain. No GPU or production service was needed.

## Every selected guard call

The run/call columns are original immutable provenance; the cell identity throughout is **ornith1.5_9b / Java**.

| Run | Original call | Reviewed target | Original reply | Trained System 1 | Decision effect |
|---|---|---|---|---|---|
| 025 | 0054 compaction retrospective | RETROSPECTIVE | PLAN | RETROSPECTIVE | Removes reviewed false block |
| 026 | 0042 compaction retrospective | PLAN | RETROSPECTIVE | PLAN | Blocks reviewed unsafe approval |
| 026 | 0059 compaction retrospective | RETROSPECTIVE | RETROSPECTIVE | RETROSPECTIVE | Unchanged |
| 026 | 0066 compaction retrospective | PLAN | RETROSPECTIVE | PLAN | Blocks reviewed unsafe approval |
| 026 | 0075 harness compaction retrospective | RETROSPECTIVE | PLAN | RETROSPECTIVE | Removes reviewed false block |
| 027 | 0036 compaction retrospective | RETROSPECTIVE | RETROSPECTIVE | RETROSPECTIVE | Unchanged |
| 027 | 0042 compaction retrospective | RETROSPECTIVE | RETROSPECTIVE | RETROSPECTIVE | Unchanged |
| 027 | 0052 compaction retrospective | RETROSPECTIVE | PLAN | RETROSPECTIVE | Removes reviewed false block |
| 027 | 0056 harness compaction retrospective | RETROSPECTIVE | PLAN | RETROSPECTIVE | Removes reviewed false block |
| 027 | 0081 steer-code | DICTATES | DICTATES | DICTATES | Existing block retained |

The full original prompt and reply for the run-026 0042 case were read, as were the full original request/reply/reasoning for run-027 0081 and an actual complete native System 1 packet. The code-prescribing `java -cp target/classes pipeline.Importer data/feed.csv` directive in 0081 was **already caught** by the original guard; System 1 retains that block rather than inventing a new correction there.

For the changed retrospective decisions, PLAN now rejects that candidate at the retrospective lens; RETROSPECTIVE only permits the remaining scope/fidelity checks to run. It does not guarantee eventual memory injection. Additional retries, rewritten briefings, later code edits, build results and usefulness remain unobserved counterfactuals.

## Saved actual calls

Private replay root: `~/.cria/experiments/ornith-java-system1-v1/`.

- `selection.json`: all ten frozen selections, full admitted inputs, TRAIN membership, original public replies and source/response hashes.
- `results.jsonl`: actual native rendered policies/state, complete token IDs/masks, calibrated logits/probabilities, final decisions and original-call mapping.
- `completed.json`, `replay.exit`: authoritative aggregate and successful completion.
- `replay.py`: explicit selection, original verdict interpretation and actual CPU inference procedure.

Results SHA-256: `5eb4282e6e5c906b325f067f0c64db5387ffcb46267a37ae93912b9958b1a0b3`.

The [130-case historical current-guard comparison](current-guard-comparison.md) remains the separate paired diagnostic result. Do not merge these ten TRAIN replays into its denominator or publish them as a new held-out score.
