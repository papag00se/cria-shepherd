# Environment-parity anomaly sweep — 2026-09-19

## Seed and scope

The seed was `shipping-rates-rb`: cria's suite isolation redirected Ruby's user-install
location but replaced `GEM_PATH` without naming the redirected directory. A normal Ruby
install then require works because the default path includes `Gem.user_dir`; the cell's
did not. The model spent the run trying to load an install that cria had made invisible.

This sweep asks the broader question: **where does cria or its battery harness replace a
normal runtime/wire behavior without completing the replacement?** It covers the actual
Codex child environment at every L0–L5 (the engagement ladder does not vary that child
environment), the Responses↔Chat edge, and level-specific routing. It does *not* call a
purposeful isolation mechanism a defect merely for differing from a host default.

The repaired Ruby library path is deliberately excluded as fixed: the cell's `Gem.user_dir`
now appears in `GEM_PATH`, it loads a gem installed in the cell, and Ruby's own `minitest`
still loads.

## Method

- Read `AGENTS.md`, doctrine/mechanism docs, suite runner, level gates, Responses adapter,
  installation guard, and live service/harness configuration.
- Direct no-network install/use probes in the real `_isolated_installs` environment.
- Three read-only independent reviews: Paseo agents `a803a3a7-cb2d-47da-a7ac-3bbc1a3efbc3`,
  `bdd2d295-34ba-45cd-b970-fe6c5fe476b7`, and
  `3a616459-edfd-41bd-a45a-94d9ae15577f` (their original gpt-5.4 launches failed before
  running; these are the successful gpt-5.6-sol replacements).

Directly established here:

- Stock Ruby includes `Gem.user_dir` in `Gem.path`; its isolated equivalent did not until
  `774be9a`.
- Cell-local npm global commands and Python `--user` console scripts are not on `PATH`.
  The host's corresponding npm prefix and `~/.local/bin` are on `PATH`.
- `uv tool dir --bin` moves from the usable host `~/.local/bin` to the cell's
  `.cell-installs/bin`, also absent from `PATH`.
- Python modules themselves are sound: the redirected user site enters `sys.path`.
- Go and Cargo install-bin directories are absent from both this host's default `PATH` and
  the cell path, so they are **not** claimed as a cria-created regression.

## Tier 1 — broken or measurement-invalidating now

- [x] **Caller Responses instructions are erased (all levels).** Fixed in `a9fd611`.
  `cria/responses.py:32-55` folds top-level `instructions` and caller `system`/`developer`
  items into a system message, then `cria/server.py:226-243` drops every system/developer
  message in the proxy path. The L4/L5 framing path does the same (`cria/loop.py:5220-5280`).
  This is not merely removal of Codex persona: it deletes the caller's actual instruction.
  **Direction:** carry caller instruction intent separately from removable harness persona
  and preserve it to the wire.

- [x] **The advertised L0 control is not actually a pure proxy.** Fixed in `3bf0a19`.
  L0 is documented as wire translation only (`cria/config.py:395-405`), yet production
  routing/classification can replace the requested model and role application overwrites
  sampling/reasoning (`cria/server.py:1144-1223`). The captured L0 Ruby body confirmed
  `reasoning_effort: low` came from cria's role despite the Codex setting. Indicators also
  remain live unless separately disabled. The level test disables indicators and has no
  production failover, so it cannot catch this. **Direction:** gate routing/role/indicator
  mutations above L0, or rename and test L0 as the non-control it is.

- [x] **Responses request semantics are silently lost (all levels).** Direct equivalents fixed in `918be07`; unsupported tool types explicitly reject in `fa16e66`.
  The wire adapter forwards a narrow whitelist (`cria/responses.py:81-94`): it drops such
  behavior-changing controls as `max_output_tokens`, caller sampling/reasoning, text format,
  stop, metadata/store, continuation/previous-response and related fields. Non-function
  tools and richer tool choices are also silently discarded (`:131-151`). **Direction:**
  losslessly map real equivalents; for unsupported semantics return a visible incompatibility
  rather than quietly changing the request.

- [x] **Cell-local CLI installs are unusable (all levels).** Fixed in `38a886f`.
  `suite/run.py:328-359` redirects package destinations, but the child path at `:600` only
  prepends a dead Node-22 literal. Npm global commands, Python user console scripts, and uv
  tools successfully install but cannot be invoked in a later command. This is the executable
  sibling of the repaired Ruby library path bug. **Direction:** derive each cell's executable
  directories and prepend them to the child `PATH`; test install→invoke for npm, Python and uv.

- [x] **Maven can poison later cells while the tripwire misses it.** Fixed by refusing publish goals in `0ea27f5`.
  Maven's shared `~/.m2/repository` is deliberately retained as a download cache
  (`suite/run.py:199-237`), but `mvn install` and `install:install-file` are not in
  `cria/dirguard.py`'s global-install guard (`:83-94`). Those write cell-built artifacts into
  the same repository. `user_install_listing()` only lists immediate root children (`run.py:365-374`),
  so a new artifact under an existing group is invisible. Reusing *downloaded* dependencies is
  purposeful; silently reusing a prior cell's built artifact is not. **Direction:** refuse
  Maven install goals or isolate locally produced Maven artifacts while retaining a read-only
  dependency cache; use authoritative metadata as a backstop.

- [x] **Stopping a battery cell can terminate unrelated Codex work.** Fixed in `84e289f`.
  `codex_pids()` matches every host `codex exec --yolo` command (`suite/run.py:381-387`), and
  `stop_run()` sends INT/KILL to all matches (`:624-630`) even though the current run already
  owns a distinct process group. **Direction:** stop only the spawned process group and its
  proven descendants.

- [x] **The orphan reaper searches an obsolete workspace root.** Fixed in `32cfd9c`.
  Runs moved to the canonical, overrideable `RUNS_DIR` (`suite/run.py:55-61,577`), while
  `suite/ladder_cycle.py:89-126` still looks under `<repo>/runs`. A stale harness/server can
  therefore survive and affect a later cell. **Direction:** import/use the same canonical
  `RUNS_DIR` in the reaper.

- [x] **L5's published planner capability is not measured.** Fixed in `4a089fe`.
  L5 is labelled as including the planner (`suite/historical_ladder.json:9`), but
  `suite/battery_run.py:118` passes `--planner off` at every level. **Direction:** either run
  L5 with planner enabled or relabel the measured plan-off ladder honestly.

## Tier 2 — real boundary debt; scope before changing

- [x] **`.cell-installs` is cria state inside the task workspace.** Fixed in `f35d336`. It is captured by milestones
  and usefulness evidence along with deliverables (`suite/run.py:321-359`,
  `suite/milestones.py:34-58`). That conflicts with the doctrine that cria artifacts stay out of
  the user's tree, and `XDG_CACHE_HOME` also contradicts the runner comment promising shared
  download caches. Move private roots beside the workspace (not in it) only after proving model
  shell access and evidence collection retain the intended containment.

- [ ] **The suite `CODEX_HOME` is a deliberate route-isolation exception with an unresolved
  realism trade-off.** `suite/run.py:66-69,108-113` replaces the entire ordinary Codex home so
  the test cannot silently hit another provider. It therefore omits user MCP servers, hooks and
  plugins. The route guarantee is purposeful; the resulting claim that L0 preserves the harness
  toolset is not currently justified. Decide whether the battery intentionally measures this
  stripped harness, or build a controlled overlay rather than treating it as a generic bug.

- [ ] **Ruby's zero-config floor may bypass a project's declared Bundler command.**
  `cria/probediscovery.py:1240-1243,1490-1504` adds bare Ruby test execution even when project
  discovery has a valid command. `docs/open-threads.md` records bare-red/Bundle-green cases.
  This needs a focused probe-discovery audit: the floor protects config-free projects, but must
  not become an additional false-red checker for configured ones.

- [ ] **Global suite configuration is not transactional.** A cell rewrites sampling, planner,
  model window and service state (`suite/run.py:176-193`, `suite/sampling.py`), while
  `battery_run.py:122-126` restores only the engagement level. The health check prevents some
  bad launches, but the effective config is not attested and the context sync return code is
  ignored. Scope a transaction/attestation design before changing it; it crosses live-service
  ownership.

- [ ] **Conditional CLI role routing has no parity contract.** At L4/L5, a CLI role can be
  replaced with the shared HTTP endpoint (`cria/routing.py:102-117`); direct CLI execution may
  inherit the service cwd/environment rather than the harness workspace (`cria/claude_cli.py`).
  It is inactive for the present local HTTP roles, but needs an explicit provider-boundary test
  before a CLI role is advertised as interchangeable.

## Tier 3 — cleanup / review triggers

- [ ] **Dead Node pin.** `suite/run.py:127` prepends a nonexistent Node v22 path; the child falls
  through to ambient mise Node v26. It is harmless today but makes the intended toolchain claim
  false. Resolve and validate a real binary, or remove the pin.
- [ ] **Install-listing coverage is not an isolation proof.** Cargo/Go cache roots and Maven root
  listing are not authoritative installed-artifact inventories; npm scopes, Gradle and Composer
  are absent. Address this only with the Maven containment work—do not grow a fragile recursive
  watcher in place of preventing writes.

## Triage state

This is a map, not an authorization to change live behavior. All Tier 1 items are explicitly
**deferred pending operator ordering** after this sweep; no cleanup has been silently folded into
the Ruby fix. Tier 2 triggers are named in their individual entries; Tier 3 waits for the adjacent
containment/toolchain work. The natural first unit is the install→invoke family (npm, Python, uv),
because it is a single regression class with direct reproductions; process ownership and caller-body
preservation should be separate units.

## Reviewed and deliberately not called defects

- Ruby user-library loading is fixed by `774be9a` with an end-to-end regression test.
- Python's redirected user *module* directory is correctly visible in `sys.path`.
- This host does not expose default Go/Cargo install bins on `PATH`; matching that limitation is
  not evidence that cria regressed a normal environment.
- Shared Go/Cargo dependency caches are purposeful and no model-installed binary leak was found.

## Posture check

The direction is good where cria asks the runtime rather than reconstructing it: the live
`/v1/models` context advertisement and the dynamically generated Codex context pin avoid a
second source of truth; the Ruby repair asked `Gem.user_dir` rather than hardcoding an ABI path;
and the level gates have one named vocabulary with passing matrix tests. The sweep's common
failure pattern is narrower: a deliberate redirection or translation is started, then a later
consumer still sees the old default (or silently loses information). The next fixes should each
prove the complete end-to-end contract—install→use, caller body→served body, or child PID→owned
termination—rather than adding another detector after the fact.
