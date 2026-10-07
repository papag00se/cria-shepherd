# The task battery — what we test cria against, and why

The suite puts cria under the kinds of pressure real coding work applies so its own footguns surface in exact call captures and finished workspaces. At each milestone the campaign agent inspects a frozen workspace snapshot, reports an inferred percentage of usefulness, and infers whether the run is complete, progressing, or stalled. Every progress report carries that percentage; afterward, an independent reasoner inspects the archived final workspace with read-only tools and records the final percentage of usefulness.

## Design rules

1. **Comparable work.** Tasks carry several substantial deliverables: research, implementation, tests, documentation, integration, or operational behavior.
2. **Inference judges usefulness.** At checkpoints, in progress reports, and at the final, the percentage means how much requested coding work the model usefully wrote so the user does not have to write it. Correct reusable code retains value despite incomplete integration, a failing build, or missed behavior; pre-existing code is not model-delivered work. Coder claims are not evidence.
3. **Milestones are holistic.** Report every 15 active minutes: the full-task inferred usefulness percentage and material changes since the previous snapshot. The first continuation decision is at minute 30; minute 15 is informational and cannot stop the run. The campaign agent judges useful progress non-strictly and semantically, not from minimum scores, numeric deltas, file/line counts, passed-check counts, or fixed task budgets. Small useful progress can warrant continuation even when the rounded percentage is unchanged. Mere activity is not useful progress.
4. **Seeded beats greenfield for finding cria bugs.** Seeded tasks exercise unfamiliar-file reading, surgical editing, and reactions to real gate output.
5. **No task is special-cased in cria.** The suite is useful only while cria remains harness-, prompt-, and language-agnostic.

## Matrix: one kind of work per language

| task | language | work exercised |
|---|---|---|
| `shipping-rates-rb` | Ruby | failing tests, feature from specification, tests, documentation, dependency research |
| `cart-billing-go` | Go | reported bug, logging, file-backed configuration, decimal-money refactor |
| `orders-api-py` | Python | API endpoint, database change, integration tests, security |
| `feed-pipeline-java` | Java | data transformation, performance, concurrency, code review, CSV dependency |
| `handles-cli-node` | JavaScript | external service, CLI, dependency migration, containerization |
| `rust-toml-cli` | Rust | discover and use a third-party crate under compile-loop pressure |

The matrix deliberately spans languages. A pattern seen only in one ecosystem cannot establish a harness-agnostic cria defect.

### Additional tasks

- `ada-handles`: API research, client, tests, live behavior, and documentation.
- `handles-{go,rust,node,ruby,php,java}`: the same problem across languages.
- `shipping-rates-py`, `feed-pipeline-py`: Python counterparts.
- `missing-tests-py`, `sqlite-inventory`: retained non-matrix workloads.

## Seeding

A task with `seed/` is copied into a fresh workspace and committed before the run. This keeps `git status` clean and makes the coder's changes legible. The retired hidden graders sometimes enforced requirements their prompts left open; they and their source-text tests are gone, so a task cannot punish work against a contract the coder never received.

## Time budgets

Default operation is **planner off**, with one milestone at 15, 30, 45, … active minutes. The first two intervals receive the full 30 active minutes unless the harness finishes naturally earlier: completion is controlled by cria's gate where enabled, or by the model alone at L0. Infrastructure errors remain errors, not completion or usefulness scores.

At minute 15 the campaign agent reports total usefulness and material changes, but cannot stop a still-running task. Starting at minute 30, that same agent separately infers `complete`, `continue`, or `stalled` from useful progress since the previous milestone. There is no minimum score, required percentage increase, or automatic legacy-budget cutoff. `budget_intervals` is retained as historical metadata, not a stop rule or additional task contract. Waiting for a valid judgment consumes no active time; missing/invalid judgments never imply completion.

Each checkpoint freezes the workspace outside the coder's tree and supplies the task, seed, prior judgments and prior snapshot paths. The agent must inspect the current and previous work and report the full usefulness percentage, material changes (including honestly no useful change), evidence, and continuation rationale. The final archived-workspace judgment is also always a usefulness percentage, including for early completion. See [suite operating instructions](../suite/README.md) for recording judgments. The generated standing report lives at [`docs/battery-report.md`](battery-report.md); historical results are retained.

## Task prompts

Each task's `prompt.txt` is its sole instruction and judgment contract. `suite/run.py` reads it at the beginning of every run, and neither judge receives `meta.toml`. A material prompt change requires incrementing `PROMPT_REV` in `suite/battery_run.py` so later usefulness comparisons do not silently mix task definitions.
