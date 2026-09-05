# The task battery — what we test cria against, and why

The suite puts cria under the kinds of pressure real coding work applies so its own footguns surface in exact call captures and finished workspaces. At each milestone the campaign agent inspects a frozen workspace snapshot and infers whether the run is complete, progressing, or stalled. Afterward, an independent reasoner inspects the archived final workspace with read-only tools and records a usefulness judgment.

## Design rules

1. **Comparable work.** Tasks carry several substantial deliverables: research, implementation, tests, documentation, integration, or operational behavior.
2. **Inference judges usefulness.** The judgment concerns how much usable work was actually delivered. Coder claims are not evidence.
3. **Milestones are inferred, not counted.** Each additional interval is earned by an agent inspecting the actual workspace. There is no fixed deliverable count due at a particular minute.
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

A task with `seed/` is copied into a fresh workspace and committed before the run. This keeps `git status` clean and makes the coder's changes legible. Task-specific hidden grading material is not part of the suite.

## Time budgets

The default interval is 30 active minutes. At every interval the harness pauses while the campaign agent inspects a frozen snapshot and records `complete`, `continue`, or `stalled`. A `continue` judgment earns one more interval, up to the maximum active budget of `N × len(meta.deliverables)`; waiting for the judge consumes no active time.

## Task prompts

Each task's `prompt.txt` is its sole instruction source. `suite/run.py` reads it at the beginning of every run. A material prompt change requires incrementing `PROMPT_REV` in `suite/battery_run.py` so later usefulness comparisons do not silently mix task definitions.
