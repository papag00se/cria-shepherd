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

### `shipping-rates-rb × ternary-bonsai` at `0b6020b` — 3/5, the cell's best by 2 checks

Run `1787111689`, 75 calls, 61 minutes, 29.9 tok/s, killed at the 60-minute floor needing 4.

```
15 min  2/5  floor 1  ok
30 min  3/5  floor 2  ok
45 min  3/5  floor 3  ok
60 min  3/5  floor 4  MISS
```

The cell's five runs, oldest first: **0, 0, 1, 0, 3**. The noise floor at identical code is 25 points — 1.25 checks on a five-check task — so 1 → 3 is above it and 0 → 3 well above. That makes it a result rather than noise. It is still ONE run; the campaign's own rule is that a reading worth acting on gets repeated at the same commit.

**Green:** `hidden_contract` 10/10 (the contract at inputs the model never saw), `express_zone` priced exactly `14.99 24.99` with its own tests, `readme_rate_table` 8/8.

**Red, and both the model's own code:** three failures in its own test suite, and `zone_for` returning `international` for EU codes. The dependency is not the problem this time — `countries 3.1.0` is installed with its three real dependencies and exposes `in_eu?`.

**What the two removals did, measured in the capture:**

| | before | after |
|---|---|---|
| `exec-intent` calls | 1 | **0** |
| satisfaction calls per check | 7 | ~4.3 |
| inspection rounds per check | 6 | ~3.3 |

The exec-intent seat is gone as designed. The judge seeding fired three times (20,555 / 14,964 / 16,627 chars) and roughly halved the inspection — **but it did not eliminate it: 4 of 10 rounds re-fetched a file that was already in the prompt** (`README.md`, `Gemfile`, `lib/shipping/rates.rb`, the spilled rubydoc page). The header tells the judge in as many words to judge against them rather than ask again, and it asked anyway. Why, is a walk question, not a guess.

Also live and behaving: 2 `rumination.abort` (the wire guards), 5 `loop.gate_offline` with no gate refusals — so the read-only bind mount is still not being rejected by the sandbox.

One correction to a number I stated: `JUDGE_FILE_BUDGET` is 20,000 characters of **file bodies**; the header, separators and skipped-file line ride on top, so a block measured 20,555.

## Step 3 — walk

Findings go to `docs/audits/finish-and-remeasure-walk.md`. Not started.

## Step 4 — fix to 100%

Nothing yet. A 100% needs a second run at the same commit to count — the noise floor at identical code is 25 points.

## Step 5 — full suite — **RUNNING**

`python3 suite/cycle_run.py`, launched 23:17 at `2b2fe2e`, log `runs/cycle-postwalk.log`, cell order model-major (gemma4 → qwen35 → ternary-bonsai → nemotron-elastic × six tasks). ~8 h. The runner restarts `cria.service` per cell, so every cell picks up HEAD.

Environment checked before launch: tree clean and pushed, nothing else running, GPU idle, `preflight.py` READY, `suite/tasks` clean, **no leaked gems**.

**What is live for the first full pass.** Nineteen fixes since the goal opened, of which nine came out of the `1787111689` walk ([plan](1787111689-walk-fix-plan.md)) and five of those are about cria destroying or fabricating evidence:

- an elision that spliced the head of one failure record onto the tail of another
- a digest that deleted an empty line which was itself the answer
- a stale edit that showed the before and hid the after
- a compaction note that re-served the original file as current state
- a ledger that said a document was in the transcript cria had refused to write it to

Plus: the exec-intent seat removed entirely, the judge handed its files instead of fetching them one call at a time, the dictated-code detector able to see Ruby, and the read refusal now naming a range that fits.

**How to read the result.** Compare against the previous pass **through the noise floor** — `battery_status.py` marks a delta smaller than one check as `~+20` and never bolds it. A `~` is not movement. Only a gap bigger than one check, or the same gap repeated, is a result.

### Cells as they land

| # | cell | score | note |
|---|---|---|---|
| 1 | shipping-rates-rb × gemma4 | **0/5** | killed at 15 min. Chose `eu_countries` — the broken gem — so every check dies on one `require`. This cell's last six runs read 1, 4, 0, 1, 4, 0: it genuinely oscillates, and 0 is inside its own range. |
| 2 | cart-billing-go × gemma4 | **5/5** | exited on its own. |
| 3 | orders-api-py × gemma4 | **4/4** | full marks, exited on its own, 97 calls |
| 4 | feed-pipeline-java × gemma4 | **5/5** | full marks, exited on its own, 35 calls |
| 5 | handles-cli-node × gemma4 | **4/4** | full marks, 29 calls |
| 6 | rust-toml-cli × gemma4 | **4/4** | full marks, 33 calls |
| 7 | shipping-rates-rb × qwen35 | **1/5** | killed at 30 min, 218 calls |
| 8 | cart-billing-go × qwen35 | **5/5** | full marks |

### The gemma4 arm, complete — and what it does and does not say

**22 of 27, five of six cells at 100%.** The one failure is `shipping-rates-rb`, again.

Against the previous complete gemma4 arms:

| arm | total | cells at 100% |
|---|---|---|
| `1786924773` | 13/27 — 48% | 2 |
| `1786979961` | 23/27 — 85% | 2 |
| **now** `1787120221` | **22/27 — 81%** | **5** |

**The total is flat** — 22 against 23 is well inside the noise. What changed is the distribution: three cells each gained exactly ONE check (`orders-api-py` 3→4, `handles-cli-node` 3→4, `rust-toml-cli` 3→4) and thereby maxed out. Each of those moves is inside the per-cell floor on its own. Three in the same direction is suggestive and **not** established — a fourth arm would settle it, and the remaining three arms of this pass are that test.

`handles-cli-node` is the one to watch: its last six read 0, 3, 3, 3, 3, **4**. Five runs stuck on the same number and then a clear.

The campaign's target is every cell at 100%, so cells-maxed is the metric that matters more than the total — but it is also the metric most sensitive to a single check, which is exactly why one arm cannot carry the claim.

**Through the noise floor, four cells in:** three at 100%, one at 0, and **nothing has moved by more than one check** except `shipping-rates-rb`. That cell's last six runs read 1, 4, 0, 1, 4, 0 — comparing it against the immediately previous run means comparing against a cherry-picked high; against the run before that it is 1 → 0, which is inside the floor. Bimodal, not regressed.

| cell | now | prev | last five | verdict |
|---|---|---|---|---|
| shipping-rates-rb × gemma4 | 0/5 | 4 | 1, 4, 0, 1, 4 | down 4 — but see above |
| cart-billing-go × gemma4 | 5/5 | 5 | 4, 5, 4, 5, 5 | `~` |
| orders-api-py × gemma4 | 4/4 | 3 | 4, 4, 0, 4, 3 | `~` |
| feed-pipeline-java × gemma4 | 5/5 | 5 | 0, 0, 0, 5, 5 | `~` |

**No fault from the new code so far.** Zero tracebacks in the cycle log, zero error-level events, and every new mechanism is firing: `loop.judge_files_seeded` 5, `loop.gate_offline` 17, `loop.steer_dictated_code` **2** — that last one is the Ruby fix working, since the detector logged one event in the entire previous run and could not see a Ruby call at all.


## Log

- `721fa51` — goal opened. Seven fixes landed in the prior session; the two ruby cells and three plumbing items remained.
- `1b05cfd` — `cria.service` restarted onto it; `shipping-rates-rb × ternary-bonsai` launched.
- `883de0c` — 1a landed: the periodic step check outlives its first fire.
- 1b refuted: the gate's Python test floor composes `pytest -q` on the seed the claim named.
- `8791a49` — 1c landed: the offline leg runs with the workspace read-only.
