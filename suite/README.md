# Model × task evaluation suite

One matrix cell per `run.py` invocation. A run receives active working time in milestone intervals, preserves its workspace and exact call captures, and appends one metadata row to `results/results.jsonl`.

**Default policy:** planner off; report at 15, 30, 45, … active minutes with total inferred usefulness and material changes since the previous milestone. One snapshot and judgment serves both reporting and continuation—there is no separate 10-minute reporting clock.

The first two intervals receive the full 30 active minutes unless the harness finishes earlier (the completion gate where enabled, or the model alone at L0). The minute-15 review cannot stop a still-running task. Continuation decisions begin at minute 30. The campaign agent judges total substantive requirement completion relative to approximate pace: roughly15active minutes per main prompt requirement, not per edit. For five requirements,40% at30minutes is expected,30% may be reasonable, but35% at45minutes warrants stopping and recording. Complexity can justify evidence-based exceptions, not indefinite extensions for small edits. Milestones are finished main requirements; clock ticks are review checkpoints. Holistic usefulness separately credits reusable incomplete work. See [the policy](../docs/task-battery.md#time-budgets). Judge waits consume no active time.

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

Pacing is fixed in 15-minute intervals, with the first continuation decision at minute 30. `meta.budget_intervals` remains recorded legacy metadata but no longer forces termination; total requirement completion relative to approximate pace is judged at each review. `prompt.txt` is the sole task/judgment contract.

When a checkpoint appears:

```bash
python3 suite/milestones.py pending
python3 suite/milestones.py emit <checkpoint>
printf '%s' '<judgment JSON>' | python3 suite/milestones.py record <checkpoint>
```

The runner remains paused until the campaign agent records a valid judgment. Required schema:

```json
{"usefulness_percent": 35, "decision": "stalled", "reason": "Requirement completion is too slow for another interval.", "material_changes": "Local accumulation introduced; integration remains unfinished.", "evidence": ["Compared prior and current source."], "requirements": [{"requirement": "Deterministic parallel import", "status": "partial", "evidence": "Current rewrite fails compilation."}], "pace_reason": "At45active minutes too little of the prompt is finished; another small rewrite does not warrant continuation."}
```

The percentage assesses **all requested work delivered so far**, not merely the last interval. `material_changes` explains the inspected difference from the previous milestone (or seed at minute 15). At minute 15 select `continue`; the runner protects the half-hour even if the judge mistakenly selects a stop decision. From minute 30 onward, `complete`/`stalled` stops and `continue` grants another interval. The percentage itself never controls the run. Every log report includes the percentage and material changes; the result row retains all milestone judgments and `judgment_policy = "requirement-pace-15m-protected-30m-v2"`; the existing `pacing_policy` cadence/provenance identity remains unchanged (historical rows are not relabeled). New checkpoint judgments require evidence-backed `requirements` (main requirement, completed|partial|not_started, evidence) and `pace_reason`; changes-only judgments are rejected. Code validates shape, never counts bullets or applies a numeric stop threshold. Invalid or absent judgments keep the task paused, never silently complete it. Review-ended/operator-ended runs are not natural completions; preserve their exact stopped archive and termination before an independent final score. Natural early completion is not artificially restarted to fill the half-hour; judge its final archive.

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

Go's `GOPATH`, `GOMODCACHE` and `GOCACHE` are explicitly cell-local under the same permitted install root as `GOBIN`. Go writes module downloads and checksum-database state even when the source workspace is untouched; leaving its default `~/go` or inherited cache paths shared/read-only breaks dependency resolution under the sandbox. No extra writable host directories or coder instructions are added. Real Go/login-shell regressions and an offline cache-writing build cover the environment, not task implementation.

JVM tools receive cell-local `maven.repo.local` and `java.io.tmpdir` properties through `JAVA_TOOL_OPTIONS`, retaining unrelated ambient JVM options. Maven otherwise writes to the sandbox's read-only host `~/.m2`; Java/Jansi ignore shell `TMPDIR`. The JVM parses quoted properties directly, including install paths with spaces. Offline real Maven/login-shell regressions exercise absent and poisoned ambient properties without fetching plugins or changing task sources.

Cargo's `CARGO_HOME` and `CARGO_INSTALL_ROOT` also point to the cell's `cargo` directory. Install-root isolation alone does not redirect registry/index/download writes from the host's read-only `~/.cargo`. The toolchain remains the existing runtime; neither host write permissions nor task dependencies are changed. Real Cargo/login-shell tests prove isolated home/config use and an offline compiled binary with absent and poisoned ambient home settings.

## Report location and launch readiness

The generated standing report is [`docs/battery-report.md`](../docs/battery-report.md). Follow [report etiquette](../docs/battery-report-policy.md): exactly six L0–L5 tables, original descriptive titles with table-average percentages, and a legend only. Coverage, supervision, attempts and limitations go in `docs/battery-report-evidence.md` and external campaign records. The campaign-aware writer overlays independent final judgments without erasing pending standings or other levels; bare `--write` refuses overwrite. Generation must not recreate `docs/audits/battery-report.md`. Existing historical rows are not fresh rerun results; record final judgments before claiming measured usefulness.

For the restored eight-model planner-off L5 run, use the shared serial driver:

```bash
python suite/l0_campaign.py --level 5 --campaign-id NAME --campaign-revision FULL_HEAD --drive
```

The historical script name remains compatible with L0. L5 cell-scoped canonical role sampling is preserved in external config receipts and restored after each cell; newer operator edits are never overwritten. Fleet validation, isolated installs, protected checkpoint pace and independent-final-judgment gating remain shared with the completed L0 campaign.

Refresh a fresh campaign's score table and row averages with:

```bash
python3 suite/battery_status.py --campaign-id l0-restored-20261007 --write
```

The explicit matching manifest selects judged main cells and linked judged replacements/operator dispositions exactly once. Pending/unjudged cells and failed originals do not enter averages. Every row includes average usefulness, wall minutes and model calls; genuine zeros count, unknown/invalid metrics do not, and coverage denominators are generated outside score cells. Wall minutes include judge waits; active time remains the separate continuation clock. Metrics come only from result rows, never reconstructed calls or capture counts. The writer replaces only the tagged fresh table/coverage: attempt provenance, current checkpoint prose and the historical ladder are preserved byte-for-byte. Ambiguous selections, missing scores and mismatched report/manifest identities fail before writing. Bare `--write` refuses to overwrite an existing tagged fresh campaign. Historical-only reports retain the legacy ladder generator.

A restored fleet must be launched from its verified current weights, runtimes, libraries and profiles, not obsolete paths or substituted assets. Missing assets block launch, not count as failed coding cells. The restored fleet now has a completed operational readiness receipt at `~/.local/share/cria/fleet/restoration-state.json` and an immutable `verification/restoration-completion.json`. The fresh L0 roster has eight logical models (Defiant-Fable is the selected `qwen3.8_9b_distill` artifact) × the six `battery_status.TASKS`: **48 new cells**. Phi's unconstrained Unicode tool-argument limitation remains recorded; restored readiness does not claim a full protocol pass or delivered-work quality. Historical rows and the fresh-L5 manifest receive no credit.

The owner must establish live L0, planner off, and call capture before launch. This path reads and verifies that config and its service startup; it never rewrites live role settings. The permanent `~/.local/bin/llama-fleet switch <official-id>` owns guarded model switching and frontend cache synchronization. All four source roles come from canonical `~/.config/llama-fleet/roles.json`. At L0 a per-cell stdlib loopback adapter injects only source numeric coder sampling into complete Responses requests, forwards every response byte, and records both the injected map and actual upstream capture values. A persistent rate-limit gate honors wait signals across calls/cells; there are no adapter retries. Codex uses the tested explicit `0.159.3` binary with the mandatory sandbox and an isolated provider URL override; the row records binary path/version/hash.

Create or inspect a manifest without launching inference:

```bash
python3 suite/l0_campaign.py --campaign-id l0-restored-20261007 \
  --campaign-revision "$(git rev-parse HEAD)"
```

Add `--drive` to run serially. State, driver logs and harness logs live under `~/.cria/suite/_campaigns/<campaign-id>/`. Before every cell the driver rejects changed revision, config, effective units, weights, runtimes, libraries, templates or receipts. It requires completed restored readiness, retains scoped known limitations, and checks only the six task runners without installing dependencies. The manifest uses the existing 15-minute semantic milestone policy, protects the first 30 active minutes and ignores legacy budgets. The controlling agent must answer milestone packets and record final usefulness via `suite/usefulness.py`; the next cell waits for that final judgment. Invalid, duplicate, interrupted or missing runs block the campaign with **no automatic retry**.

A single manifest cell is routed through:

```bash
python3 suite/battery_run.py --level 0 --restored-fleet \
  --model gemma4_12b --task shipping-rates-rb \
  --campaign-id l0-restored-20261007 --campaign-revision <full-revision>
```

`--campaign-id` and `--campaign-revision` are also supported by `suite/run.py`. Legacy service and sampling registries remain available only on the existing path without `--restored-fleet`; archived identities are preserved.

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
