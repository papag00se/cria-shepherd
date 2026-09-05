# Model × task evaluation suite

One matrix cell per `run.py` invocation. A run receives a fixed elapsed-time budget, preserves its workspace and exact call captures, and appends one metadata row to `results/results.jsonl`.

The run ends only when the harness exits or the elapsed-time budget expires. No task assessment can stop it early.

## Run a cell

```bash
python3 suite/run.py \
  --task cart-billing-go \
  --model nemotron-elastic \
  --harness codex \
  --planner off \
  --note "experiment label"
```

The default wall is 30 minutes. `--milestone-minutes N` is retained as a task-sized budgeting interface: the wall becomes `N × declared deliverables`; it does not perform interval judgments.

Each row records run identity, settings, elapsed time, terminal state, call/phase counts, throughput, assist events, workspace/archive paths, captures, and harness log. Delivered-work quality is absent until an independent usefulness judgment is recorded.

## Usefulness judgments

```bash
python3 suite/usefulness.py pending
python3 suite/usefulness.py emit <run-id>
printf '%s' '<judgment JSON>' | python3 suite/usefulness.py record <run-id>
python3 suite/usefulness.py show
```

The judge infers deliverables from the task, inspects the archived workspace with read-only tools, and records a 0–100 usefulness judgment with per-deliverable reasons. Claims from the coding session are not evidence.

## Replays and walks

`replay.py` re-sends real captured calls under a settings or wording matrix and evaluates protocol behavior with cria's own parsers. `walk.py` materializes a call-by-call transcript for manual causal analysis.
