# Model × task evaluation suite

One matrix cell per `run.py` invocation. A run receives active working time in milestone intervals, preserves its workspace and exact call captures, and appends one metadata row to `results/results.jsonl`.

**Default policy:** planner off; report at 15, 30, 45, … active minutes with total inferred usefulness and material changes since the previous milestone. One snapshot and judgment serves both reporting and continuation—there is no separate 10-minute reporting clock.

The first two intervals receive the full 30 active minutes unless the harness finishes earlier (the completion gate where enabled, or the model alone at L0). The minute-15 review cannot stop a still-running task. Continuation decisions begin at minute 30. The campaign agent judges total substantive requirement completion relative to approximate pace: roughly15active minutes per main prompt requirement, not per edit. For five requirements,40% at30minutes is expected,30% may be reasonable, but35% at45minutes warrants stopping and recording. Complexity can justify evidence-based exceptions, not indefinite extensions for small edits. Milestones are finished main requirements; clock ticks are review checkpoints. Holistic usefulness separately credits reusable incomplete work. See [the policy](../docs/task-battery.md#time-budgets). **Checkpoints are asynchronous (2026-10-26):** the coder is never paused for a snapshot or a judgment, so active time is wall time since the harness started. See [Asynchronous checkpoints](#asynchronous-checkpoints).

For each `[milestone]` notice, the campaign agent inspects the current and previous snapshots, records the judgment, and sends the user a report with model/task, elapsed active time, total usefulness percentage, material changes, and the continuation decision/rationale. Scheduled 15/30/… slots are distinct from the actual active elapsed time at which the snapshot was cut. Packets, checkpoint policy metadata, progress lines and result-row milestone judgments carry `actual_active_seconds`; the legacy `at_active_minutes` field identifies the scheduled slot, not a measurement. `progress_reports.py` is retained only for old independent-report packets, not used by current runs. For unattended runs, arrange a supervisor/heartbeat in the controlling agent conversation before launch; the Python runner does not send chat messages or manufacture judgments.

## Asynchronous checkpoints

Policy change 2026-10-26 (operator): no pausing the coder for judgment or snapshot precision; mutable files are fine and the continuing run has priority. **No SIGSTOP, no adapter quiesce, no wait blocks the coder.**

- **Snapshot.** At each due interval the monitor copies the LIVE workspace (`suite/milestones.py create`) while the harness runs. The copy is **approximate by design**: files may change before, during and after it, and the operator accepts that. It is not fingerprinted, locked, retried or repaired. `policy.json["snapshot"]` records only `mode: live-unpaused` and any copy `errors` (e.g. a file that vanished mid-copy); the packet's `SNAPSHOT CONDITIONS` line says the copy is approximate and, if applicable, could not be fully copied. It never claims the tree was unchanged.
- **Judgment.** The campaign agent answers whenever it can, with the same `pending/emit/record` commands. The monitor polls (`milestones.poll`, non-blocking) for a valid recorded judgment while it keeps observing natural exit and the next intervals. A later packet lists any earlier checkpoint still awaiting judgment (`NOT YET JUDGED`, with its snapshot path) and the judged ones as before.
- **Result row.** `milestone_judgments` has one record per checkpoint: `status: judged` with the real judgment and `judged_at_active_seconds`, or `status: pending` with no verdict fields. A checkpoint still unanswered at natural exit stays pending; the runner never completes, scores or invents it, and it can still be recorded afterwards in `~/.cria/suite/_milestones/`.
- **A recorded stop decision ends the run.** `complete`/`stalled` (from minute 30) from the campaign agent's real judgment stops the harness even though files changed since its snapshot and even though a newer checkpoint is still unanswered; no file state, timestamp or newer unanswered copy can veto it. One ordering rule: the judgment of the NEWEST judged checkpoint decides, so an older stop decision recorded after a newer checkpoint was already judged is retained with `terminal_not_applied` ("a newer checkpoint was already judged") and does not stop the run; one recorded after the process ended is also retained, not applied. Minute 15 still cannot stop. There is no task wall cap, retry or numeric threshold.
- **Row identity.** `active_seconds` equals `wall_seconds`. Rows carry `judgment_policy = "requirement-pace-15m-protected-30m-v3-async-live-snapshot"` and `checkpoint_mode = "async-live-snapshot"`; `pacing_policy` (`inferred-progress-15m-protected-30m-v1`) is the cadence: 15-minute interval, protected first 30 minutes.
- **Interfaces.** `run.monitor_milestones(proc, pacing, run_id, ws, task_dir, *, stop)`; `HarnessControl` has `stop()`; `milestones.poll` is the non-blocking judgment check.

## Run a cell

Planning defaults to **off** in both `run.py` and `battery_run.py`, including L5 and the CRIA arm. It is retained only for explicit experiments (`--planner on`); neither selecting a level nor swapping a model is consent to enable it. Ordinary runs require no planner flag.

Assists are **L5 only**. When the tested server selects `[assists] profile = "rank4-ablation"`, it disables four Rank-4 definitions with `default_level = 5` after the operator's 2026-10-22 restoration of grounded stalled-work, completed-work briefing, shrinking-file protection, plan revision and living-plan (planning-related mechanisms remain explicitly opt-in); level-eligible L0–L4 wire fixes, cria tools, context fitting (including history compaction) and completion brakes remain active. The original profile disabled all 48 ranked definitions, including 39 below L5, so those historical runs did not isolate assists. Compare deployed revisions/configs and request-event `pilot_assists`; the profile name alone cannot distinguish the historical 48-disabled, nine-disabled, seven-disabled and current four-disabled selections. Planning still requires separate opt-in. See the [profile contract](../README.md#exact-rank-4-ablation).

```bash
python3 suite/run.py \
  --task cart-billing-go \
  --model ornith1.5 \
  --harness codex \
  --note "experiment label"
```

Pacing is fixed in 15-minute intervals, with the first continuation decision at minute 30. `meta.budget_intervals` is recorded metadata and does not force termination; total requirement completion relative to approximate pace is judged at each review. `prompt.txt` is the sole task/judgment contract.

When a checkpoint appears:

```bash
python3 suite/milestones.py pending
python3 suite/milestones.py emit <checkpoint>
printf '%s' '<judgment JSON>' | python3 suite/milestones.py record <checkpoint>
```

The runner does not wait for the judgment: the coder keeps running and the runner collects the judgment whenever a valid one is recorded. Required schema:

```json
{"usefulness_percent": 35, "decision": "stalled", "reason": "Requirement completion is too slow for another interval.", "material_changes": "Local accumulation introduced; integration remains unfinished.", "evidence": ["Compared prior and current source."], "requirements": [{"requirement": "Deterministic parallel import", "status": "partial", "evidence": "Current rewrite fails compilation."}], "pace_reason": "At45active minutes too little of the prompt is finished; another small rewrite does not warrant continuation."}
```

The percentage assesses **all requested work delivered so far**, not merely the last interval. `material_changes` explains the inspected difference from the previous milestone (or seed at minute 15). At minute 15 select `continue`; the runner protects the half-hour even if the judge mistakenly selects a stop decision. From minute 30 onward, `complete`/`stalled` stops and `continue` grants another interval. The percentage itself never controls the run. Every log report includes the percentage and material changes; the result row retains all milestone judgments and `judgment_policy = "requirement-pace-15m-protected-30m-v3-async-live-snapshot"` plus `checkpoint_mode = "async-live-snapshot"`; the existing `pacing_policy` cadence/provenance identity remains unchanged (historical rows are not relabeled). New checkpoint judgments require evidence-backed `requirements` (main requirement, completed|partial|not_started, evidence) and `pace_reason`; changes-only judgments are rejected. Code validates shape, never counts bullets or applies a numeric stop threshold. An invalid or absent judgment is simply not a judgment: the checkpoint stays pending (and is listed in the result row as `status: pending`), and the runner never invents a verdict or a completion. Review-ended/operator-ended runs are not natural completions; preserve their exact stopped archive and termination before an independent final score. Natural early completion is not artificially restarted to fill the half-hour; judge its final archive.

Each row records run identity, settings, elapsed time, terminal state, call/phase counts, throughput, assist events, workspace/archive paths, captures, and harness log. Campaign rows also record the `revision`, the live engagement level, the planner config state, the role sampling applied, and request phase counts. Battery cells have no fixed wrapper timeout. Delivered-work quality is absent until a usefulness judgment is recorded.

A campaign is the set of (model, task, level) cells that still lack a judged result row. Run any cell through `suite/battery_run.py` with `--level N --planner off`; a cell without a result row is simply run again.

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

Every judged Codex launch also uses the same per-cell HTTP admission adapter. Restored runs retain their existing source-sampling injection; other supported launches use a byte-preserving no-op mode. The isolated provider must speak Responses to local cria, verified before launch; there is no unadapted unsafe-pause path.

Terminal paths use `cancel()`, which closes admission, answers waiters with retryable HTTP 503 without reaching the producer, and precedes the process-group stop and the capture cutoff. Natural leader exit and surviving-child grace follow the same order.

This confines Codex child-tool filesystem writes, not the trusted Python runner,
ordinary pytest invocations, host-wide reads or network traffic. The middleware
cleanup review is separate and **is not** a filesystem sandbox.

Go's `GOPATH`, `GOMODCACHE` and `GOCACHE` are explicitly cell-local under the same permitted install root as `GOBIN`. Go writes module downloads and checksum-database state even when the source workspace is untouched; leaving its default `~/go` or inherited cache paths shared/read-only breaks dependency resolution under the sandbox. No extra writable host directories or coder instructions are added. Real Go/login-shell regressions and an offline cache-writing build cover the environment, not task implementation.

JVM tools receive cell-local `maven.repo.local` and `java.io.tmpdir` properties through `JAVA_TOOL_OPTIONS`, retaining unrelated ambient JVM options. Maven otherwise writes to the sandbox's read-only host `~/.m2`; Java/Jansi ignore shell `TMPDIR`. The JVM parses quoted properties directly, including install paths with spaces. Offline real Maven/login-shell regressions exercise absent and poisoned ambient properties without fetching plugins or changing task sources.

Cargo's `CARGO_HOME` and `CARGO_INSTALL_ROOT` also point to the cell's `cargo` directory. Install-root isolation alone does not redirect registry/index/download writes from the host's read-only `~/.cargo`. The toolchain remains the existing runtime; neither host write permissions nor task dependencies are changed. Real Cargo/login-shell tests prove isolated home/config use and an offline compiled binary with absent and poisoned ambient home settings.

## Report

The standing report is [`docs/battery-report.md`](../docs/battery-report.md): an `Updated: YYYY-MM-DD HH:MM TZ` line under the title, then six L0–L5 tables (original descriptive titles with table-average percentages) and a legend. Cell and chat labels use official model / language via `report_labels.cell_label`, matching the Ruby/Go/Python/Java/Node/Rust columns. All six tables are ordered together by descending L5 average usefulness; equal means use ascending official model identity and unscored L5 identities come last.

Refresh it from the result rows:

```bash
python3 suite/battery_status.py --write
```

Each judged (model, task, level) cell contributes its latest judged row. Every table row shows average usefulness, wall minutes and model calls; genuine zeros count, unknown metrics do not. Wall minutes include judge waits in older rows; in rows from the asynchronous runner active time equals wall time (see [Asynchronous checkpoints](#asynchronous-checkpoints)). Metrics come only from result rows.

## Running cells

A campaign is the set of (model, task, level) cells that still lack a judged result row. A single cell runs through `suite/battery_run.py` (which also supports `--restored-fleet`); a cell that ends without a result row is simply run again:

```bash
python3 suite/battery_run.py --level 0 --restored-fleet \
  --model gemma4_12b --task shipping-rates-rb --campaign-id NAME
```

[Parallel lanes](#parallel-lanes-one-cell-per-slot-both-gpus) run the whole set. The controlling agent answers milestone packets and records final usefulness judgments via `suite/usefulness.py`.

The owner establishes the live engagement level, planner off and call capture before launch. `~/.local/bin/llama-fleet switch <official-id>` switches models. All four source roles come from `~/.config/llama-fleet/roles.json`. A per-cell stdlib loopback adapter injects the row's numeric coder sampling into complete Responses requests, forwards every response byte, and records the injected map and the actual upstream capture values. A persistent rate-limit gate honors wait signals across calls and cells; there are no adapter retries. Codex uses the explicit `0.159.3` binary with the mandatory sandbox and an isolated provider URL override; the row records the binary path and version.

## Parallel lanes (one cell per slot, both GPUs)

[`suite/lanes.py`](lanes.py) serves **one model per card, many slots of that one model, one cell per slot**. The 3090 lane is 4 slots at 49,152 tokens each; the 3080 lane is 2 slots at the largest per-slot window that fits with `MARGIN_MIB` free after a loaded run (49,152 → 45,056 → 40,960 → 36,864; recorded per model in `LANE_WINDOWS`, `None` = 3090 lane only). A model's profile context caps its window (`bonsai2`/`k2_horizon_7b` 40,960, `phi4` 16,384). `--ctx-size` is the TOTAL (slots × per-slot); the window cria and Codex are told is the PER-SLOT one. The canonical single-slot RTX3080 profiles and `llama-fleet switch` are unchanged: a lane plan is the profile's own plan with only `--parallel`, `--ctx-size`, port and device overridden. `lanes.take_hardware` stops the HyperQwen container, its idle-check timer and any running managed fleet model, and `python suite/lanes.py restore` puts them back after an interrupted run.

Each ACTIVE ROW (lane × model × level) gets one cria instance on its own port (from 18400) with its own config copy (the row's role sampling, plus transport-only edits: port, endpoint, logs, captures, engagement level) and its own capture/log directories under `~/.cria/suite/_lanes/<lane>/rows/`. Every concurrent cell of that row shares the instance (cria state is session-scoped); a cell's sessions and events are the Codex session ids its harness log printed. Row instances run the deployed `cria.service` code (same python and release directory); the service itself is not used or edited by lane runs.

Run the driver as its own `systemd --user` unit, never as a child of an agent's shell: a killed parent (an agent
scope taken by systemd-oomd took 239 lane processes with it) must not take the lanes down, and `ExecStopPost`
puts the hardware back however the driver ends:

```bash
systemd-run --user --unit=lanes-ID --collect --working-directory="$PWD" \
    -p ExecStopPost="/usr/bin/python3 $PWD/suite/lanes.py restore" -p StandardOutput=append:"$HOME/.cria/suite/_lanes/ID.log" -p StandardError=append:"$HOME/.cria/suite/_lanes/ID.log" \
    python3 suite/lane_driver.py --campaign l5-20261102:5 [--campaign l0-20261102:0] \
    [--lanes 3090x4,3080x2] [--models M,..] [--tasks T,..] [--max-cells N]
```

`python3 suite/lanes.py restore` is the same recovery by hand.

The driver serves one model at a time, fills every free slot of its lanes with that model's pending cells across all campaigns/levels, and switches model only when every slot has drained. A cell awaiting its usefulness judgment does not hold a slot. A cell that fails or ends without a result row is run again.

`suite/lane_measure.py` measures each model × lane with a fixed load (~6K-token code prompt, 600-token outputs: solo, then every slot at once) and reports the fit and the factor. **Reported wall minutes** are solo-equivalent rough estimates: measured minutes × `LANE_FACTORS[model][lane]` (per-stream tok/s at the lane's slot count ÷ solo tok/s on the same card; an unmeasured model uses the `ornith1.5_9b` factor). The factor is applied by `battery_status` from the row's `lane`; `wall_seconds` stays the measured value.

## Usefulness judgments

```bash
python3 suite/usefulness.py pending
python3 suite/usefulness.py emit <run-id>
printf '%s' '<judgment JSON>' | python3 suite/usefulness.py record <run-id>
python3 suite/usefulness.py show
```

The judge infers usefulness only from the original `prompt.txt` and the archived workspace inspected with read-only tools. The percentage asks how much requested coding work the model usefully wrote so the user does not have to write it: correct reusable code keeps its value despite incomplete integration or a failing build, while pre-existing code does not count as model-delivered work. The final judgment is inferred holistically rather than calculated from item, line, or check counts; task metadata and claims from the coding session are not judgment contracts or evidence.

## Replays and walks

`replay.py` re-sends real captured calls under a settings or wording matrix and evaluates protocol behavior with cria's own parsers. `walk.py` prints a call-by-call transcript for manual causal analysis. With `--segment-bytes` or `--reader-context-tokens`, each assignment section supplies its own initial prompt per phase, then references exact already-read prompt lines within that section. Prepared chunks preserve call order and never cross section boundaries. New/changed prompt text and every response/reasoning/tool argument remain whole. References identify source calls and line ranges; context removals/replacements are marked. `--full-prompts` disables line reuse. Section byte budgets include the emitted UTF-8 text and reference framing; a single oversized call is flagged rather than split.

The process has two documents: [Walking](../docs/walk-prompt.md) owns preparation and delivery; [Analysis](../docs/walk-analysis.md) owns source challenge, diagnosis and fix evaluation. Luna receives only its short role instruction and the current stage prompt: reasoning-only extraction, then a separate same-Luna whole-list context mapping. `walk.py` writes chunks and `assignments.json`; readers create their own findings inside the same directory.
