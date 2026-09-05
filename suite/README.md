# Model × task evaluation suite

One matrix cell per `run.py` invocation. A run receives active working time in milestone intervals, preserves its workspace and exact call captures, and appends one metadata row to `results/results.jsonl`.

The harness gets fifteen active minutes per task item. The minute-15 gate is skipped; at minute 30 the campaign agent inspects a frozen workspace snapshot and two task items must be complete, in any order, to continue. Later gates require three complete items at minute 45, four at minute 60, and so on; missing the quota stops the run early.

## Run a cell

```bash
python3 suite/run.py \
  --task cart-billing-go \
  --model nemotron-elastic \
  --harness codex \
  --planner off \
  --note "experiment label"
```

Pacing is fixed at 15 active minutes per task item. `meta.budget_intervals` supplies the number of task slots and therefore the maximum active budget; five slots means 75 minutes. It supplies no task content: `prompt.txt` is the sole judgment contract, and the judge infers exactly that many substantive task items from it.

When a checkpoint appears:

```bash
python3 suite/milestones.py pending
python3 suite/milestones.py emit <checkpoint>
printf '%s' '<judgment JSON>' | python3 suite/milestones.py record <checkpoint>
```

The runner remains paused until the campaign agent records the task-state judgment. Waiting time does not consume the run's active budget. Only completed task items earn later time; partial progress does not.

Each row records run identity, settings, elapsed time, terminal state, call/phase counts, throughput, assist events, workspace/archive paths, captures, and harness log. Delivered-work quality is absent until an independent usefulness judgment is recorded.

## Usefulness judgments

```bash
python3 suite/usefulness.py pending
python3 suite/usefulness.py emit <run-id>
printf '%s' '<judgment JSON>' | python3 suite/usefulness.py record <run-id>
python3 suite/usefulness.py show
```

The judge infers deliverables only from the original `prompt.txt`, inspects the archived workspace with read-only tools, and records a 0–100 usefulness judgment with per-deliverable reasons. Task metadata and claims from the coding session are not judgment contracts or evidence.

## Replays and walks

`replay.py` re-sends real captured calls under a settings or wording matrix and evaluates protocol behavior with cria's own parsers. `walk.py` materializes a call-by-call transcript for manual causal analysis.
