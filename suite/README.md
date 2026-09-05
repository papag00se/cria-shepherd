# Model × task evaluation suite

One matrix cell per `run.py` invocation. A run receives active working time in milestone intervals, preserves its workspace and exact call captures, and appends one metadata row to `results/results.jsonl`.

At every interval the harness is paused and the campaign agent inspects a frozen workspace snapshot. The agent infers `complete`, `continue`, or `stalled`; a progressing run earns another interval, while complete or stalled work ends the run.

## Run a cell

```bash
python3 suite/run.py \
  --task cart-billing-go \
  --model nemotron-elastic \
  --harness codex \
  --planner off \
  --note "experiment label"
```

The default milestone interval is 30 active minutes. `--milestone-minutes N` changes that interval; the maximum active budget is `N × meta.budget_intervals`, but each additional interval must be earned by an inference judgment. `budget_intervals` is pacing only: `prompt.txt` is the sole judgment contract.

When a checkpoint appears:

```bash
python3 suite/milestones.py pending
python3 suite/milestones.py emit <checkpoint>
printf '%s' '<judgment JSON>' | python3 suite/milestones.py record <checkpoint>
```

The runner remains paused until the campaign agent records the judgment. Waiting time does not consume the run's active budget.

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
