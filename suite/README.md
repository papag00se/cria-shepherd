# Model × task evaluation suite

One matrix cell per `run.py` invocation. A run receives active working time in milestone intervals, preserves its workspace and exact call captures, and appends one metadata row to `results/results.jsonl`.

**Default policy:** planner off; report at 15, 30, 45, … active minutes with total inferred usefulness and material changes since the previous milestone. One snapshot and judgment serves both reporting and continuation—there is no separate 10-minute reporting clock.

The first two intervals receive the full 30 active minutes unless the harness finishes earlier (the completion gate where enabled, or the model alone at L0). The minute-15 review cannot stop a still-running task. Continuation decisions begin at minute 30. The campaign agent judges total substantive requirement completion relative to approximate pace: roughly15active minutes per main prompt requirement, not per edit. For five requirements,40% at30minutes is expected,30% may be reasonable, but35% at45minutes warrants stopping and recording. Complexity can justify evidence-based exceptions, not indefinite extensions for small edits. Milestones are finished main requirements; clock ticks are review checkpoints. Holistic usefulness separately credits reusable incomplete work. See [the policy](../docs/task-battery.md#time-budgets). Judge waits consume no active time.

For each `[milestone]` notice, the campaign agent inspects the frozen current and previous snapshots, records the judgment, and sends the user a report with model/task, elapsed active time, total usefulness percentage, material changes, and the continuation decision/rationale. Scheduled 15/30/… slots are distinct from actual active elapsed time: waiting for the transport to reach a safe checkpoint remains active work. Packets, checkpoint policy metadata, progress lines and result-row milestone judgments carry `actual_active_seconds`; the legacy `at_active_minutes` field identifies the scheduled slot, not a measurement. `progress_reports.py` is retained only for old independent-report packets, not used by current runs. These are active-time reports; pauses can lengthen their wall-clock spacing. For unattended runs, arrange a supervisor/heartbeat in the controlling agent conversation before launch; the Python runner does not send chat messages or manufacture judgments.

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

Every judged Codex launch also uses the same per-cell HTTP admission adapter. Restored runs retain their existing source-sampling injection; other supported launches use a byte-preserving no-op mode. The isolated provider must speak Responses to local cria, verified before launch; there is no unadapted unsafe-pause path.

Checkpoint safety requires a **serial model-request client**: it consumes the current response before starting the next request. Serializing HTTP forwards does not establish consumption by arbitrary parallel clients, and a second independent request is not an acknowledgement of the first client's reply. Parallel model consumers are not supported by this checkpoint protocol. Supported suite launches explicitly disable Codex's `multi_agent` and `multi_agent_v2` features, including inherited enablement; parallel tool execution within one model turn is unchanged.

For that supported serial client, the adapter parks its next model request before forwarding it, lets active inference forwards finish while the client is still running, and only then freezes the harness process group. On resume every parked request receives retryable HTTP 503 without reaching the producer. This prevents the checkpoint itself from stranding an already-generated action in an expired client stream; it is not a general delivery guarantee for arbitrary parallel consumers or unrelated network failures. There is no request-equality cache, response replay, altered model content or new inference through the adapter during the judgment pause. Read-only GET health/model traffic is not part of inference draining. All terminal paths, including natural leader exit and surviving-child grace, close admission before resuming/stopping the owned process group, then establish the capture cutoff.

This confines Codex child-tool filesystem writes, not the trusted Python runner,
ordinary pytest invocations, host-wide reads or network traffic. The middleware
cleanup review is separate and **is not** a filesystem sandbox.

Go's `GOPATH`, `GOMODCACHE` and `GOCACHE` are explicitly cell-local under the same permitted install root as `GOBIN`. Go writes module downloads and checksum-database state even when the source workspace is untouched; leaving its default `~/go` or inherited cache paths shared/read-only breaks dependency resolution under the sandbox. No extra writable host directories or coder instructions are added. Real Go/login-shell regressions and an offline cache-writing build cover the environment, not task implementation.

JVM tools receive cell-local `maven.repo.local` and `java.io.tmpdir` properties through `JAVA_TOOL_OPTIONS`, retaining unrelated ambient JVM options. Maven otherwise writes to the sandbox's read-only host `~/.m2`; Java/Jansi ignore shell `TMPDIR`. The JVM parses quoted properties directly, including install paths with spaces. Offline real Maven/login-shell regressions exercise absent and poisoned ambient properties without fetching plugins or changing task sources.

Cargo's `CARGO_HOME` and `CARGO_INSTALL_ROOT` also point to the cell's `cargo` directory. Install-root isolation alone does not redirect registry/index/download writes from the host's read-only `~/.cargo`. The toolchain remains the existing runtime; neither host write permissions nor task dependencies are changed. Real Cargo/login-shell tests prove isolated home/config use and an offline compiled binary with absent and poisoned ambient home settings.

## Report location and launch readiness

The generated standing report is [`docs/battery-report.md`](../docs/battery-report.md). Follow [report etiquette](../docs/battery-report-policy.md): exactly six L0–L5 tables, original descriptive titles with table-average percentages, and a legend only. Chat supervision labels use official model / language via `report_labels.cell_label`, matching Ruby/Go/Python/Java/Node/Rust columns, never task types; internal task/run IDs remain provenance. Coverage, supervision, attempts and limitations go in `docs/battery-report-evidence.md` and external campaign records. The campaign-aware writer overlays independent final judgments without erasing pending standings or other levels' scores/metrics. All six tables reorder together by descending exact L5 average usefulness; equal means use ascending official model identity, unscored L5 identities come last, and historical subsets keep the shared relative order without invented rows. Bare `--write` refuses overwrite. Generation must not recreate `docs/audits/battery-report.md`. Existing historical rows are not fresh rerun results; record final judgments before claiming measured usefulness.

For the restored eight-model planner-off L5 run, use the shared serial driver:

```bash
python suite/l0_campaign.py --level 5 --campaign-id NAME --campaign-revision FULL_HEAD --drive
```

The historical script name remains compatible with L0. L5 cell-scoped canonical role sampling is preserved in external config receipts and restored after each cell; newer operator edits are never overwritten. Fleet validation, isolated installs, protected checkpoint pace and independent-final-judgment gating remain shared with the completed L0 campaign.

Refresh a fresh campaign's score table and row averages with:

```bash
python3 suite/battery_status.py --campaign-id l0-restored-20261007 --write
```

The explicit matching manifest selects judged main cells and linked judged replacements/operator dispositions exactly once. Pending/unjudged cells and failed originals do not enter averages. Every row includes average usefulness, wall minutes and model calls; genuine zeros count, unknown/invalid metrics do not, and coverage denominators are generated outside score cells. Wall minutes include judge waits; active time remains the separate continuation clock. Metrics come only from result rows, never reconstructed calls or capture counts. The writer overlays the selected level's standing cells/metrics, synchronizes all six tables to the retained L5 ranking, and appends coverage to the evidence document. Other levels retain their row contents, not necessarily their row positions; no checkpoint prose or attempt ledger belongs in the scorecard. Ambiguous selections, missing scores and mismatched report/manifest identities fail before writing. Bare `--write` refuses overwrite; the historical ladder generator is only a preview, not a standing-report writer.

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

`replay.py` re-sends real captured calls under a settings or wording matrix and evaluates protocol behavior with cria's own parsers. `walk.py` materializes a call-by-call transcript for manual causal analysis. With `--segment-bytes` or `--reader-context-tokens`, each assignment section supplies its own initial prompt per phase, then references exact already-read prompt lines within that section. Readers consume assigned chunks in order; chunks never cross section boundaries. New/changed prompt text and every response/reasoning/tool argument remain whole. References explicitly identify source calls and line ranges; context removals/replacements are marked. `--full-prompts` disables line reuse. Section byte budgets include actual emitted UTF-8 text and reference framing; a single oversized call is flagged rather than split.

Role instructions are separated: [supervisor](../docs/walk-prompt.md) assigns complete independent sections, [reader](../docs/walk-reader.md) performs exhaustive line-by-line observation without coding/diagnosis, and [investigator/fixer](../docs/walk-investigator.md) verifies causal findings and handles history, adversarial checks, replays, code and tests.

## Closed walk and fix retention

Operator policy (2026-10-13): after all fixes associated with a walk/validation unit settle
**ACCEPTED or REJECTED**, delete its walk, proof outputs, reviews, scratch copies and supporting
artifacts. Durable outputs are **repository changes (including genuine regression tests) and
actual model-call logs**, not permanent bug/score archives or hash/tombstone warehouses.
Old assistant-authored archival instructions and incidental citations do not extend closed-work
retention. Keep active owners, unresolved failures, necessary current inputs/deadlines and unique
unapplied source/tests until disposition/application makes those copies unnecessary. Never infer
closure from a finished model run, usefulness judgment, missing findings or an empty fix list.

**Prevent accumulation at creation.** Follow [`docs/walk-prompt.md`](../docs/walk-prompt.md) for the single-directory investigation workflow and bounded acceptance standard. Tests and follow-on tools must not depend on disposable review outputs; port necessary inputs into small repository regression fixtures.

`walk.py` writes chunks and `assignments.json`, not a duplicate plan or placeholder findings. Readers create their own findings inside the same directory. An empty file does not establish reading coverage.

The coordinating owner runs cleanup immediately after the last fix disposition and securing necessary changes. There is no separate cleanup review or permanent closure registry. Supply the declaration on stdin so cleanup does not require another file:

```bash
python -B suite/close_walk.py - <<'JSON'
{"unit":"walk-example","owner":"coordinator","closure":"final fix dispositions",
 "closed":true,"fixes":[{"id":"fix-1","disposition":"ACCEPTED","changes":[
 {"source":"/tmp/example/test_regression.py",
  "worktree":"/home/operator/src/cria-shepherd/tests/test_regression.py"}]}],
 "scratch":["/tmp/example"],"protected_paths":[],"call_logs":[]}
JSON
```

`--dry-run` is optional, not another approval step. An existing temporary JSON file is still accepted, but is not required and must not become a new permanent record. `milestones.py` records task continuation, not fix acceptance; completing a run alone does not authorize deletion.

Declare every fix; only the exact two settled dispositions qualify. Declare each necessary unique
source/test copy; identical regular-file bytes must already exist inside this worktree before
scratch removal. Rejected alternatives that are not needed are disposable, not tests to port.
Explicit `changes: []` means no necessary unique changes, not an unexamined directory. A genuinely
closed walk with no findings requires `fixes: []` AND `no_findings: true`. Unknown/ambiguous
ownership or dispositions deny cleanup. No blanket glob: list only attributable paths strictly
below `/tmp`, `~/.cria/validation` or `~/.cria/walk-findings`. Root deletion/escape, overlapping
paths, missing targets, symlinks/special entries and protected intersections are refused before
any batch deletion. An absent path is not reported as a previously successful deletion.

Declare active dependencies/gates/other-owner inputs in `protected_paths` and ALL misplaced
experimental captures in `call_logs`; an overlap denies the containing-root deletion. Canonical
`~/.cria/calls`, `~/.cria/logs`, this repository and `~/Documents` are always protected. Move actual
experimental call logs to `~/.cria/calls` with explicit original-path provenance and verified full
byte custody before deleting any otherwise eligible containing root. Never move operative gates.
Synthetic CPU-fixture captures are not new model calls, but establish that from actual producer
and transport ownership, never filename resemblance alone. Keep pending runtime candidates,
unique unapplied tests/code, quarantined workspaces and other projects untouched.

The command validates the supplied declaration; it cannot judge whether the coordinator omitted
an active dependency or misclassified arbitrary bytes as scratch. It is not a general garbage
collector, permission sandbox or technical barrier to independent destructive shell commands.
Deletion uses no-follow parent descriptors and the platform's symlink-safe tree remover; stale
inode identity denies deletion. Directory traversal errors deny the whole batch, rather than
silently treating an unreadable subtree as empty. Target directories must belong to the current
process's Unix user; target parents must already allow removal. After full admission, only owned
directories INSIDE the admitted targets gain owner-write permission when necessary (for example,
read-only copied module caches). No file permissions change: a hard-linked original elsewhere
must retain its mode and bytes. No permissions outside admitted trees change. Filesystem failures
can still leave a partially removed batch: inspect and report the actual error, never relabel it
as complete. Temporary closure/cleanup/review records
are themselves disposable after this unit settles; do not keep another permanent archive.
