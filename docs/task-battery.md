# The task battery — what we test cria against, and why

The suite puts cria under the kinds of pressure real coding work applies so its own footguns surface in exact call captures and finished workspaces. It does not decide quality during a run. Afterward, an independent reasoner infers the requested deliverables from the task, inspects the archived workspace with read-only tools, and records a usefulness judgment.

## Design rules

1. **Comparable work.** Tasks carry several substantial deliverables: research, implementation, tests, documentation, integration, or operational behavior.
2. **Inference judges usefulness.** The judgment concerns how much usable work was actually delivered. Coder claims are not evidence.
3. **Elapsed time is only a budget.** A run ends when the harness exits or its wall expires; no quality judgment can end it.
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

The default is a flat 30-minute elapsed-time wall. With `--milestone-minutes N`, the total wall is `N × len(meta.deliverables)`. Despite the historical option name, it performs no interval judgment; the metadata count only sizes the task budget.

## Task prompts

Each task's `prompt.txt` is its sole instruction source. `suite/run.py` reads it at the beginning of every run. A material prompt change requires incrementing `PROMPT_REV` in `suite/battery_run.py` so later usefulness comparisons do not silently mix task definitions.
