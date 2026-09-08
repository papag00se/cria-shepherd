# Model × task evaluation suite

One matrix cell per `run.py` invocation. A run receives active working time in milestone intervals, preserves its workspace and exact call captures, and appends one metadata row to `results/results.jsonl`.

The first inference checkpoint is at 30 active minutes; later checkpoints are 15 active minutes apart. At every checkpoint, every progress report, and the final judgment, usefulness is always reported as an inferred percentage. The campaign agent inspects a frozen workspace snapshot and also makes a separate holistic `complete`, `continue`, or `stalled` control decision; no percentage mechanically determines that decision.

## Run a cell

```bash
python3 suite/run.py \
  --task cart-billing-go \
  --model ornith15 \
  --harness codex \
  --planner off \
  --note "experiment label"
```

Pacing is fixed in 15-minute intervals, with the first checkpoint delayed until minute 30. `meta.budget_intervals` supplies only the maximum active-time budget; five intervals means 75 minutes. It supplies no task content: `prompt.txt` is the sole judgment contract.

When a checkpoint appears:

```bash
python3 suite/milestones.py pending
python3 suite/milestones.py emit <checkpoint>
printf '%s' '<judgment JSON>' | python3 suite/milestones.py record <checkpoint>
```

The runner remains paused until the campaign agent records the inferred usefulness percentage and control decision. Its progress log prints that percentage at every checkpoint. Waiting time does not consume the run's active budget.

Each row records run identity, settings, elapsed time, terminal state, call/phase counts, throughput, assist events, workspace/archive paths, captures, and harness log. Delivered-work quality is absent until an independent usefulness judgment is recorded.

## Usefulness judgments

```bash
python3 suite/usefulness.py pending
python3 suite/usefulness.py emit <run-id>
printf '%s' '<judgment JSON>' | python3 suite/usefulness.py record <run-id>
python3 suite/usefulness.py show
```

The judge infers usefulness only from the original `prompt.txt` and the archived workspace inspected with read-only tools. The percentage asks how much requested coding work the model usefully wrote so the user does not have to write it: correct reusable code keeps its value despite incomplete integration or a failing build, while pre-existing code does not count as model-delivered work. The final judgment is inferred holistically rather than calculated from item, line, or check counts; task metadata and claims from the coding session are not judgment contracts or evidence.

## Replays and walks

`replay.py` re-sends real captured calls under a settings or wording matrix and evaluates protocol behavior with cria's own parsers. `walk.py` materializes a call-by-call transcript for manual causal analysis.
