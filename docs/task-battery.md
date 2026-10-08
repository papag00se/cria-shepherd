# The task battery — what we test cria against, and why

The suite puts cria under the kinds of pressure real coding work applies so its own footguns surface in exact call captures and finished workspaces. At each milestone the campaign agent inspects a frozen workspace snapshot, reports an inferred percentage of usefulness, and infers whether the run is complete, progressing, or stalled. Every progress report carries that percentage; afterward, an independent reasoner inspects the archived final workspace with read-only tools and records the final percentage of usefulness.

## Design rules

1. **Comparable work.** Tasks carry several substantial deliverables: research, implementation, tests, documentation, integration, or operational behavior.
2. **Inference judges usefulness.** At checkpoints, in progress reports, and at the final, the percentage means how much requested coding work the model usefully wrote so the user does not have to write it. Correct reusable code retains value despite incomplete integration, a failing build, or missed behavior; pre-existing code is not model-delivered work. Coder claims are not evidence.
3. **Milestones are finished main prompt requirements, not clock ticks.** Review every15active minutes, but allow roughly15minutes per substantive requirement (often4,5or6), with the first two protected together for30minutes. Judge total requirement completion against active elapsed time semantically, not by counting bullets or computing a score. For five requirements, about40% at30minutes is expected and30% may be reasonable; only35% at45minutes warrants ending and recording the cell. This is approximate pace, not a rigid cutoff. Small edits, repeated rewrites or a possible next fix do not alone justify continuation. Holistic usefulness still credits reusable unfinished code separately.
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

Default operation is **planner off**, with review checkpoints at15,30,45,… active minutes; these clock ticks are not substantive milestones. The first two intervals receive the full 30 active minutes unless the harness finishes naturally earlier: completion is controlled by cria's gate where enabled, or by the model alone at L0. Infrastructure errors remain errors, not completion or usefulness scores.

At minute 15 the campaign agent reports total usefulness and material changes, but cannot stop a still-running task. Starting at minute 30, that same agent separately infers `complete`, `continue`, or `stalled` from total delivered requirement completion relative to approximate task pace, not merely the last interval's edits. There is no mechanical minimum score, required percentage increase, or automatic legacy-budget cutoff. `budget_intervals` is retained as historical metadata, not a stop rule or additional task contract. Waiting for a valid judgment consumes no active time; missing/invalid judgments never imply completion.

Each checkpoint freezes the workspace outside the coder's tree and supplies the task, seed, prior judgments and prior snapshot paths. The agent must inspect the current and previous work and report the full usefulness percentage, material changes (including honestly no useful change), evidence, a requirement-by-requirement completion assessment, and explicit pace rationale. New checkpoints reject judgments missing requirement or pace evidence; historical packets remain readable. Review-ended and operator-ended attempts must preserve termination provenance and must never be called natural completions or scored by copying a checkpoint. The final archived-workspace judgment is also always a usefulness percentage, including for early completion. See [suite operating instructions](../suite/README.md) for recording judgments. The generated standing report lives at [`docs/battery-report.md`](battery-report.md); historical results are retained. **Every model row must carry average usefulness percentage, average wall minutes, and average model calls**, including the fresh-campaign table, not only the historical ladder. Compute each mean from the selected independently judged logical cells (including authorized linked dispositions exactly once), include genuine zeros, and exclude pending/unjudged cells and preserved failed originals. Use authoritative result metrics, never infer calls from text/capture counts; unknown metrics are not zero and their measurement coverage must be disclosed outside score cells. Round displayed means to whole values. Wall minutes include judge waits and are distinct from active-time continuation pace; disclose any operator-ended measurement basis. The legacy ladder's `total` means average usefulness, not a sum. `suite/battery_status.py --campaign-id <matching campaign> --write` owns the fresh table and coverage calculation; it selects manifest-linked judged attempts, refuses ambiguous/unjudged selections, and preserves attempt/checkpoint narrative and historical ladder bytes. Bare `--write` cannot erase a tagged fresh campaign.

## Task prompts

Each task's `prompt.txt` is its sole instruction and judgment contract. `suite/run.py` reads it at the beginning of every run, and neither judge receives `meta.toml`. A material prompt change requires incrementing `PROMPT_REV` in `suite/battery_run.py` so later usefulness comparisons do not silently mix task definitions.
