# Finish and re-measure — progress

**Status file for [`docs/goals/finish-and-remeasure.md`](../goals/finish-and-remeasure.md).** Updated as each item lands and as each cell finishes, never batched.

Started at `721fa51`.

## Step 1 — the three open items

| item | what settled it | state |
|---|---|---|
| 1a periodic step check shares a counter with the gate | 21 events on the box, **every one at `turns=12`**, at most one per session | **landed `883de0c`** |
| 1b ecosystem discovery is manifest-only | the gate calls `select_completion_probes`, not `discover` — and it composes `pytest -q` on the exact seed the claim named | **refuted** |
| 1c the gate re-runs the suite in the live workspace | bound what the second run CAN DO, not what gets copied | **landed `8791a49`** |

### 1a — confirmed, and the mechanism was not the one filed

Filed as "the gate zeroes the counter the step check reads". That is half of it. `guard_periodic_gate` owns `coder_turns` as a countdown and zeroes it at 15, so **12 is the only multiple of 12 that counter can ever hold** — and the once-per-tick memo beside it, `step_checked_turn == coder_turns`, then refused every later arrival at 12 for the life of the session. A memo written for a counter that climbs becomes a permanent refusal on one that resets.

The reading, across 177 sessions: **21 `loop.periodic_step_check` events, every one at `turns=12`, at most one per session.** Not one at 24, 36 or 48. Clearest case `01a006c7` — 89 coder calls and 3 completed gate cycles on that path, one step check.

Fixed by giving it the clock nothing resets: `drive_count`, through the same `periodic_check_due` predicate the satisfaction check uses (renamed from `satisfaction_check_due`, whose docstring had already named this as the sibling). The gate keeps its countdown. The event now records both clocks so the drives-to-turns ratio is a reading rather than an argument.

**What it costs, counted rather than argued.** Replayed over the whole corpus (112 sessions that reached this path at all): 16 fires today, 29 after the fix — **13 extra judge calls across every session on the box**. The cadence only bites where a step has run long, which is the case the mechanism exists for; the median session hands back after 6 turns and never reaches 12.

Observe-only either way — what this restores is the **measurement** its own "WHAT FLIPS IT" note requires before it may ever advance a step. One sample per session, all at the same tick, could never accumulate into that decision.

### 1b — refuted

The claim rested on `probediscovery.discover()` returning nothing for `orders-api-py`'s seed. It does. **The gate does not call it.** `plan_gate` calls `proberun.select_completion_probes`, which carries a zero-config TEST FLOOR, and on that exact seed it composes:

```
SyntaxCheck  python3 -m compileall …
Lint         python3 -m pyflakes …
Test         python3 -m pytest -q
```

The floor exists for Python and Ruby precisely because those are the two languages where a testable project needs no manifest; Go/Rust/JS/JVM cannot build without one, so ecosystem discovery always reaches them.

The second leg of the claim — "zero of the recorded gate events found no probes" — was also wrong, in the other direction, and it does not rescue the finding. **18 of `orders-api-py`'s 96 periodic gates report `ran=false`.** But `ran` means *no section markers came back*, not *no probes were composed*: a refused exec, a compaction, an empty result. That is the probe-reissue path, not a discovery gap.

PHP has no floor and is the one real hole in the table — and `handles-php` is not in the 24-cell matrix. Recorded, not built (#1, #15).

*(This item was nearly filed a second time on the same mistake: the first measurement here called `discover()` too. Reading `plan_gate` is what caught it.)*

### 1c — landed, and the design named in the sweep was rejected

The sweep's surviving note was "run the offline leg FIRST and stop". **That is a false-green generator**, and the refutation is in this module's own docstring two functions over: a live test can SKIP rather than fail when the service is gone, exit code still 0. So an offline pass does not imply an online pass, and the authoritative run has to be the unblocked one. Reordering also does not even reduce executions on the measured mix — gates that ran split 262 clean / 264 with findings, so it moves the doubling from the green case to the red one and nothing else.

What is bounded instead is **what the second run can do**. The namespace already existed; `-m` plus a read-only re-bind of the working directory costs one syscall pair and makes the whole class impossible. Reads, loopback and `/tmp` are untouched. A suite that writes inside its own tree now fails offline, which `_offline_fact` reads as say-nothing — it speaks only when both sides are green. **Silence, never a manufactured red.**

One trap found by running it: a process's cwd is a resolved dentry, so mounting over the path does not move it. The first cut still wrote through the old cwd; the namespace re-enters the directory after the bind.

No writable fallback — the capability probe performs the same bind the run performs, so a kernel or sandbox that refuses it skips the leg entirely (#4, #11b).

Measured against the four matrix seeds with a runnable suite (`orders-api-py`, `feed-pipeline-py`, `cart-billing-go`, `shipping-rates-rb`): **same exit code read-only as writable, and nothing left behind.**

## Step 2 — the two cells

**CORRECTION — the two cells are NOT at one code state, and the earlier line here saying they were was wrong.** `suite/run.py:135` restarts `cria.service` at the start of every run, to apply the model's sampling and the planner flag. So each cell picks up whatever is on disk when it launches:

| cell | launched | code state |
|---|---|---|
| × ternary-bonsai | 23:44 | `1b05cfd` — before today's three fixes |
| × gemma4 | 00:16 | HEAD — `883de0c` + `8791a49` + `d19bf6c` live |

The plan had been to hold one state across both. The runner's own restart makes that impossible without editing the runner, and it is right to restart. Say it rather than compare across it: any difference between these two cells has a code change in it as well as a model change.

**And it settled 1c's one open risk by reading rather than argument.** The read-only offline leg is composed with a bind mount, and this repo has lost a whole 24-cell arm before to a verb Codex's sandbox disliked. Cell 2's first gate, live, under the real harness:

```
07:18:39  loop.periodic_gate     {"plan_off": false}
07:18:39  loop.gate_offline      {"ran": true, "test_green": true}
07:18:39  loop.periodic_gate_result  {"ran": true, "spoke": false}
```

The mount was not rejected and the leg came back.

| cell | last score | this pass |
|---|---|---|
| shipping-rates-rb × ternary-bonsai | 0/5 | **1/5**, `milestone-miss-30min`, 60 calls, 22.3 tok/s, 1846 s |
| shipping-rates-rb × gemma4 | 1/5 | **running** |

### `shipping-rates-rb × ternary-bonsai` — 1/5, and the score is hiding the run

Read off the surviving workspace, not off the number. The model **installed the gem** — `bundle install --path vendor/bundle`, a lockfile, `.bundle/config` with `BUNDLE_PATH: "vendor/bundle"`, and `countries-8.1.0`, `eu_countries-0.0.2`, `rake-13.4.2`, `unaccent-0.4.0` vendored. It wrote `zone_for` against the gem rather than a hardcoded list, added the `express` zone at 14.99 base / 2.50 per kilo, and wrote the README rate table. That table is the check that scored.

**Four of the five deliverables are written and one line kills all of them.** The gem it chose, `eu_countries-0.0.2`, opens with `require "iso3166"`, and nothing on this box provides `iso3166`; the `countries` gem provides `countries`. Reproduced against a copy of the workspace:

```
ruby -Ilib -e 'require "shipping/rates"'              -> cannot load such file -- iso3166 (LoadError)
bundle exec ruby -Ilib -e 'require "shipping/rates"'  -> cannot load such file -- iso3166 (LoadError)
rake test                                             -> TypeError: no implicit conversion of nil into String
```

The second failure is separate and also the model's: its Rakefile has `$LOAD_PATH.unshift Dir[ENV["GEM_HOME"], Dir.pwd]...`, and with `GEM_HOME` unset `Dir[nil, ...]` raises before any test runs.

**Neither is cria's, and cria did not dress them up.** Replaying `completion_block_nudge` against this exact workspace and a `rake test` LoadError finding: the dependency note does **not** fire, and the coder is handed the checker's own message verbatim — `lib/shipping/rates.rb:7: ... cannot load such file -- iso3166 (LoadError)`. The false install sentence the previous ruby walk found is not in the path here.

**Two prior fixes confirmed live from this run's own artifacts.** The spill directory on disk is `tmp/reference/` (`845900b` — the `./tmp/read-only` retype problem), and the session recorded **zero** `rumination.abort` events (`34a9162` — the 743-second dead stream).

**One thing the new logging made visible.** `loop.satisfaction_blocked` fired on 25 consecutive drives, 26 through 50, every one with `last_ran=25` — the off-ramp check held shut for the whole tail because the gate was red. That is the designed rule (cria never proposes ending a task while the repo's own checks fail), and before `07f06c1` it would have looked identical to the check simply never being due.

Environment: `preflight.py` READY, `suite/tasks` clean, live service reachable. `/usr/bin/bundle` now exists (`ruby-bundler`), so these two cells are a changed **environment** as well as changed code.

**What this task actually requires, measured on this box before the cells were read.** The prompt's last line is *"Add a third-party Ruby gem that determines whether a country is in the EU, add it to the project dependencies, and use it for the lookup"* — so an install is not optional, it is deliverable 4's only route.

```
bundle install                       ->  FAILS  (no write permission on /var/lib/gems/3.2.0)
gem install countries                ->  FAILS  (same)
bundle install --path vendor/bundle  ->  WORKS  (3 gems, 22 s)
bundle exec ruby -e "require 'countries'; puts ISO3166::Country.new('DE').in_eu?"  ->  true
```

**The task is passable in four commands, and nothing leaked into a shared gem home.** `ruby-bundler` fixed the `bundle: command not found` half; the remaining obstacle is ordinary Unix permissions on a system Ruby, which every Ruby developer meets and which bundler's own error names explicitly. Deliberately NOT changed: making `/var/lib/gems` writable, or setting a global bundler path, would be altering the machine to make a task easier to pass.

That reframes what the walk is looking for on this cell. Not "can the model install a gem" — it can — but **whether anything cria says about the install is true**, since the previous ruby walk found cria describing an install that had never happened and ruling out the step that had failed.

## Step 3 — walk

Findings go to `docs/audits/finish-and-remeasure-walk.md`. Not started.

## Step 4 — fix to 100%

Nothing yet. A 100% needs a second run at the same commit to count — the noise floor at identical code is 25 points.

## Step 5 — full suite

Not started.

## Log

- `721fa51` — goal opened. Seven fixes landed in the prior session; the two ruby cells and three plumbing items remained.
- `1b05cfd` — `cria.service` restarted onto it; `shipping-rates-rb × ternary-bonsai` launched.
- `883de0c` — 1a landed: the periodic step check outlives its first fire.
- 1b refuted: the gate's Python test floor composes `pytest -q` on the seed the claim named.
- `8791a49` — 1c landed: the offline leg runs with the workspace read-only.
