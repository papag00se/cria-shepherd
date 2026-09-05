# The task battery — what we test cria against, and why

The suite puts cria under the kinds of pressure real coding work applies so its own footguns surface in exact call captures and finished workspaces. At each milestone the campaign agent inspects a frozen workspace snapshot and infers whether the run is complete, progressing, or stalled. Afterward, an independent reasoner inspects the archived final workspace with read-only tools and records a usefulness judgment.

## Design rules

1. **Comparable work.** Tasks carry several substantial deliverables: research, implementation, tests, documentation, integration, or operational behavior.
2. **Inference judges usefulness.** The judgment concerns how much usable work was actually delivered. Coder claims are not evidence.
3. **Task completion earns time.** A judge infers task-item state from the actual workspace. There is no minute-15 gate; minute 30 requires any two task items complete, minute 45 requires any three, and minute 60 requires any four. Partial progress does not earn another interval.
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

Each task item is worth 15 active minutes. The first gate is at minute 30, where any two completed items earn the next slot; minute 45 requires three, minute 60 four, and so on. Missing the completion quota stops the cell early. The positive integer `budget_intervals` supplies the task-slot count and maximum budget—five slots means 75 minutes—but no task content; the judge infers exactly that many substantive items from `prompt.txt`. Waiting for the judge consumes no active time.

## Task prompts

Each task's `prompt.txt` is its sole instruction and judgment contract. `suite/run.py` reads it at the beginning of every run, and neither judge receives `meta.toml`. A material prompt change requires incrementing `PROMPT_REV` in `suite/battery_run.py` so later usefulness comparisons do not silently mix task definitions.
