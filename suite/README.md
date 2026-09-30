# Model × task evaluation suite

One matrix cell per `run.py` invocation. A run receives active working time in milestone intervals, preserves its workspace and exact call captures, and appends one metadata row to `results/results.jsonl`.

The first milestone checkpoint is at 30 active minutes; later milestones are 15 active minutes apart. Independently, a fresh read-only usefulness report is requested every 10 active minutes. Reports compare the frozen snapshot semantically with the seed/baseline and preceding independent reports, are informational only, and never stop or extend the run. At 30 minutes the report and milestone are separate snapshots/judgments; at 40/45 the same separation holds. Judge waits are excluded from active time. Milestones retain the separate holistic `complete`, `continue`, or `stalled` control decision; no percentage mechanically determines that decision.

For each `[progress-report]` or `[milestone]` notice, inspect the corresponding read-only packet and record a fresh inference. Reports: `python3 suite/progress_reports.py pending|emit|record`; milestones: `python3 suite/milestones.py pending|emit|record`. Recording one judgment does not satisfy the other.

## Run a cell

Planning defaults to **off** in both `run.py` and `battery_run.py`, including L5 and the CRIA arm. It is retained only for explicit experiments (`--planner on`); neither selecting a level nor swapping a model is consent to enable it. Ordinary runs require no planner flag.

```bash
python3 suite/run.py \
  --task cart-billing-go \
  --model ornith1.5 \
  --harness codex \
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

Each row records run identity, settings, elapsed time, terminal state, call/phase counts, throughput, assist events, workspace/archive paths, captures, and harness log. Fresh L5 campaign rows also record an immutable `revision`, explicit planner config state, and request phase counts; only rows proving planner disabled in config and no planner request phase satisfy the revision-pinned worklist. Delivered-work quality is absent until an independent usefulness judgment is recorded.

The fresh L5 cohort is exactly nine roster models × six tasks. Materialize/resume its manifest at a committed revision:

```bash
python3 suite/fresh_l5_campaign.py --revision "$(git rev-parse HEAD)"
```

Run a listed cell through `suite/battery_run.py` with `--level 5 --planner off --fresh-l5 --campaign-revision <same-full-revision>`. The runner rejects a different HEAD. Historical rows are never edited or counted as fresh campaign cells.

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
