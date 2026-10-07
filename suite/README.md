# Model × task evaluation suite

One matrix cell per `run.py` invocation. A run receives active working time in milestone intervals, preserves its workspace and exact call captures, and appends one metadata row to `results/results.jsonl`.

**Default policy:** planner off; report at 15, 30, 45, … active minutes with total inferred usefulness and material changes since the previous milestone. One snapshot and judgment serves both reporting and continuation—there is no separate 10-minute reporting clock.

The first two intervals receive the full 30 active minutes unless the harness finishes earlier (the completion gate where enabled, or the model alone at L0). The minute-15 review cannot stop a still-running task. Continuation decisions begin at minute 30. The campaign agent is the judge: non-strict, semantic inference of useful progress since the last milestone, not a minimum percentage, required score increase, passed-check count, or forecast of perfection. Small reusable improvements count; mere activity does not. Judge waits consume no active time.

For each `[milestone]` notice, the campaign agent inspects the frozen current and previous snapshots, records the judgment, and sends the user a report with model/task, elapsed active time, total usefulness percentage, material changes, and the continuation decision/rationale. `progress_reports.py` is retained only for old independent-report packets, not used by current runs. These are active-time reports; pauses can lengthen their wall-clock spacing. For unattended runs, arrange a supervisor/heartbeat in the controlling agent conversation before launch; the Python runner does not send chat messages or manufacture judgments.

## Run a cell

Planning defaults to **off** in both `run.py` and `battery_run.py`, including L5 and the CRIA arm. It is retained only for explicit experiments (`--planner on`); neither selecting a level nor swapping a model is consent to enable it. Ordinary runs require no planner flag.

```bash
python3 suite/run.py \
  --task cart-billing-go \
  --model ornith1.5 \
  --harness codex \
  --note "experiment label"
```

Pacing is fixed in 15-minute intervals, with the first continuation decision at minute 30. `meta.budget_intervals` remains recorded legacy metadata but no longer forces termination; continuing useful progress is judged at each milestone. `prompt.txt` is the sole task/judgment contract.

When a checkpoint appears:

```bash
python3 suite/milestones.py pending
python3 suite/milestones.py emit <checkpoint>
printf '%s' '<judgment JSON>' | python3 suite/milestones.py record <checkpoint>
```

The runner remains paused until the campaign agent records a valid judgment. Required schema:

```json
{"usefulness_percent": 35, "decision": "continue", "reason": "Useful progress warrants another interval.", "material_changes": "The parser now handles nested inputs; integration remains unfinished.", "evidence": ["Compared the prior and current parser implementation."]}
```

The percentage assesses **all requested work delivered so far**, not merely the last interval. `material_changes` explains the inspected difference from the previous milestone (or seed at minute 15). At minute 15 select `continue`; the runner protects the half-hour even if the judge mistakenly selects a stop decision. From minute 30 onward, `complete`/`stalled` stops and `continue` grants another interval. The percentage itself never controls the run. Every log report includes the percentage and material changes; the result row retains all milestone judgments and `pacing_policy = "inferred-progress-15m-protected-30m-v1"`. Invalid or absent judgments keep the task paused, never silently complete it. Natural early completion is not artificially restarted to fill the half-hour; judge its final archive.

Each row records run identity, settings, elapsed time, terminal state, call/phase counts, throughput, assist events, workspace/archive paths, captures, and harness log. Fresh L5 campaign rows also record an immutable `revision`, the live engagement level read after cria's healthy restart, explicit planner config state, and request phase counts. The worklist credits only explicit L5 rows with live L5 provenance, preserved workspace and matching valid request/response captures, and no abort. Battery cells have no fixed wrapper timeout because judgment waits are excluded from active time. Delivered-work quality is absent until an independent usefulness judgment is recorded.

The fresh L5 cohort is exactly nine roster models × six tasks. Materialize/resume its manifest at a committed revision:

```bash
python3 suite/fresh_l5_campaign.py --revision "$(git rev-parse HEAD)"
```

Run a listed cell through `suite/battery_run.py` with `--level 5 --planner off --fresh-l5 --campaign-revision <same-full-revision>`. The runner rejects a different HEAD. Historical rows are never edited or counted as fresh campaign cells.

## Machine-local Codex sandbox policy

**Sandboxing is mandatory for Codex testing launches from this repo.** Put
`workspace_sandbox = true` in `~/.cria/suite-codex-policy.toml`. Missing, unreadable,
malformed or disabled policy stops launch; there is no unsandboxed fallback.
`suite/run.py` supplies a fresh per-invocation `cria_suite_<unique-id>` permission
profile: read access across the filesystem, write access only to the explicitly
named cell workspace and its isolated install/scratch directory, with approvals
disabled and normal networking retained. Fresh profile names prevent Codex's TOML
merging from retaining extra writes in an existing same-named profile. No inferred
cwd/git-root write grant is used. `TMPDIR` points to the cell's scratch directory;
the host-wide `/tmp` is not granted write access.

This requires a Codex version supporting named permission profiles. The local
integration test invokes `codex sandbox` with the exact launch policy against a
disposable outside sentinel; it never starts inference or executes incident code.
The integration probe verifies outside deletion, overwrite, creation, rename and
symlink writes are denied, including with an inherited permissive profile, while
workspace and scratch writes succeed. No user/global Codex settings, harness code,
or system services are changed. Other machines must configure the same required
policy before launching tests.

Battery and ladder runs go through `suite/run.py`. Any new Codex test launcher must
reuse `_codex_argv(prompt, workspace)` and the suite's isolated environment/scratch
setup, or use the suite runner itself; do not launch bare Codex or add bypass flags.
The isolated `~/.cria/codex-home/config.toml` routing configuration is also required;
its absence stops launch rather than selecting an ambient provider.

This confines Codex child-tool filesystem writes, not the trusted Python runner,
ordinary pytest invocations, host-wide reads or network traffic. The middleware
cleanup review is separate and **is not** a filesystem sandbox.

## Report location and launch readiness

The generated standing report is [`docs/battery-report.md`](../docs/battery-report.md). Generation must not recreate `docs/audits/battery-report.md`. Existing historical rows are not fresh rerun results; record final judgments before claiming measured usefulness.

A restored fleet must be launched from its verified current weights, runtimes, libraries and profiles, not obsolete paths or substituted assets. Missing assets block launch, not count as failed coding cells. The pending full L0 rerun is **not launched** while the restored fleet location is unresolved; its current roster is eight logical models (Defiant-Fable is the selected `qwen3.8_9b_distill` artifact), not nine separate identities. Do not reuse the historical fresh-L5 manifest as this rerun's worklist.

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
