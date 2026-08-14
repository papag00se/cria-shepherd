# 100% campaign — live progress

**This file is the status.** Not a chat message, not a memory, not an intention. The goal it serves
is `docs/goals/hundred-goal.md`. The score grid it summarises is `docs/audits/battery-report.md`, which
rewrites itself after every cell.

**Target: 24 of 24 cells at 100%.** Currently 9 — mean 53.8%.

---

## Cycle 1

**Phase: WALK** — the run phase finished 2026-08-14 02:45, all 24 cells scored.

**Cycle 1 result: mean 53.8%, up from 51.2%. Nine cells at 100%, up from five.**

Read that as it is. Four cells gained a lot (+100, +75, +50, +50), four lost a lot (−80, −80, −60,
−25×3), and eleven did not move at all. The gains came from two task-prompt corrections and the
losses from cria; the eleven flat cells include five that never compiled and were never going to on
this code state.

*(An earlier running count in this file said twelve at 100%. It was a hand-incremented number and it
was wrong; nine is what the results file says.)* Java column complete: 0 / 40 / 0 / 0. Walks of the finished cells run
alongside it; no fix lands until the run phase ends.

Driver: `python3 suite/cycle_run.py --start <n>` · log `docs/audits/cycle-run.log`

### Cells

| # | task | model | score | Δ pts | min | calls | what happened |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | shipping-rates-rb | gemma4 | 20% | −80 | 17 | 68 | chose a dead gem. `eu_countries` 0.0.2 (2014) opens with `require "iso3166"`, an entry point gone from modern `countries`, so `require 'eu_countries'` raises LoadError and the four checks that load the library all die on it. The fifth only reads the README. **The gate did not fail here** — five gates fired and every one got the real LoadError back; both completion gates refused the model's `task_complete`. The run was killed by a 167 KB briefing prompt the server rejected twelve times |
| 2 | shipping-rates-rb | qwen35 | **100%** | +40 | 8 | 92 | |
| 3 | shipping-rates-rb | ternary-bonsai | 80% | 0 | 16 | 52 | |
| 4 | shipping-rates-rb | nemotron-elastic | 0% | 0 | 16 | 57 | |
| 5 | cart-billing-go | gemma4 | **100%** | +40 | 7 | 36 | |
| 6 | cart-billing-go | qwen35 | **100%** | +20 | 10 | 80 | |
| 7 | cart-billing-go | ternary-bonsai | **100%** | +100 | 16 | 54 | |
| 8 | cart-billing-go | nemotron-elastic | 0% | −20 | 16 | 51 | cria's own spilled fetch, saved as `…decimal.go` inside the workspace, was compiled by `go build ./...` — all five checks died on it |
| 9 | orders-api-py | gemma4 | **100%** | 0 | 21 | 71 | |
| 10 | orders-api-py | qwen35 | 50% | −25 | 29 | 131 | model defect, reproduced: its `init()` runs `CREATE TABLE IF NOT EXISTS` (a no-op on the pre-migration database the checker supplies) then `UPDATE orders SET status=…` on a column that was never added — service exits 1, two checks die with it |
| 11 | orders-api-py | ternary-bonsai | 50% | −25 | 47 | 92 | killed at 45 min for sitting below the floor. Scored 2 at the 15-, 30- and 45-minute marks and never moved. The route answers 200 but the body carries neither the items nor the total, and eleven of its own tests fail. The stuck detector fired three times and changed nothing — walk running |
| 12 | orders-api-py | nemotron-elastic | 50% | −25 | 46 | 175 | same signature as cell 11: score frozen at 2 across all three milestones, killed at the 45-minute floor. `GET /customers/alice/orders` did not answer at all (status 0) and three of its own tests fail. Five oversize refusals in the same 8,935–10,103 byte band |
| 13 | feed-pipeline-java | gemma4 | 0% | −80 | 16 | 54 | its rewrite of `Importer.java` dropped the seed's first line, `package pipeline;`. The file still compiles — javac puts it in the default package — so nothing complained, and the checker's `import pipeline.Importer` then found nothing. All five checks died on one missing line; killed at the 15-minute floor. Walk running |
| 14 | feed-pipeline-java | qwen35 | 40% | −60 | 46 | 371 | fast and wrong. It hit **29.9× against a 4.0× bar** and lost the point anyway because the totals no longer match the seed's. The quoted-comma row is mis-parsed despite declaring `opencsv`, and no REVIEW.md was written in 371 calls — the cheapest point on the board. Five more oversize refusals in the same band. Walk running in three parts |
| 15 | feed-pipeline-java | ternary-bonsai | 0% | 0 | 16 | 46 | never compiled. `mvn compile` failed and stayed failed; killed at the 15-minute floor with one gate fired. Flat against last cycle, which was also 0% |
| 16 | feed-pipeline-java | nemotron-elastic | 0% | 0 | 16 | 66 | never compiled either. One near-miss: it *did* write REVIEW.md — 419 words — but with zero located findings, and the prompt asks for a file name and line number on every issue. Flat against last cycle |
| 17 | handles-cli-node | gemma4 | 75% | **+75** | 4 | 26 | biggest gain of the cycle, and the fastest cell yet — 26 calls, three and a half minutes. The p4 prompt fix landed: the CLI now prints address, holder and count, which is exactly what the checker asked for and the old wording did not. Only `tests_incl_live` failed — its tests pass with the network blocked, so they are mocked, not live |
| 18 | handles-cli-node | qwen35 | **100%** | +50 | 24 | 202 | all four green, including the live test — `npm test` passes with the network and fails without it, which is exactly the property the check is asking for |
| 19 | handles-cli-node | ternary-bonsai | **100%** | +50 | 9 | 32 | all four green in 32 calls, live test included. One rumination abort, one gate, nothing else needed |
| 20 | handles-cli-node | nemotron-elastic | 25% | 0 | 8 | 41 | half a migration: it took `request` out of `package.json` and left the `require` in the source, so the program cannot start — `node lookup.js goose` exits 1. It then **stopped on its own** at 41 calls with three checks failing, which is the part that is cria's. Walk running |
| 21 | rust-toml-cli | gemma4 | **100%** | 0 | 14 | 73 | all four green — clean build, 3/3 lookups, the error contract, tests and README. Held its perfect score from last cycle |
| 22 | rust-toml-cli | qwen35 | **100%** | 0 | 19 | 153 | all four green, held from last cycle. Heavily assisted — 5 periodic gates, 4 wheel-spin steers, 3 litter sweeps, one dictated steer dropped — and still landed |
| 23 | rust-toml-cli | ternary-bonsai | 0% | 0 | 16 | 42 | never built — `E0308`, two type errors, killed at the 15-minute floor. **Two gates ran and not one `⟦ctx:checks⟧` block reached the model**, on a run whose whole problem was a compile error. Three oversize refusals at 10,102–10,104 bytes sit where those results should be. Sixth cell showing that bug |
| 24 | rust-toml-cli | nemotron-elastic | 0% | 0 | 16 | 57 | never built either — four errors, `E0277`/`E0599`. Five rumination aborts. Flat |

Δ is percentage points against the previous run of the same cell, whatever prompt revision it was
earned against. Run ids are on the rows in `suite/results/results.jsonl`.

### Findings ledger — cycle 1

Seeded from work already done; the walk phase appends to it.

| rank | tier | finding | state | closed by |
|---:|---|---|---|---|
| 1 | 1 | **cria discards its own gate output and then reports the checks GREEN.** Verified cold: 8 discards over the bound, then 19× "the repo's own checks reported no error-class problems" and 8× "the repo's automated checks pass" — while pytest was red and the route returned nothing. A fail-open on missing ground truth (#13), stated as fact (#5b). Same bound as the two below | open | |
| 2 | 1 | **The same number closes two more doors.** It refuses cria's own joined gate output, and it refuses the coder reading its own source. `Importer.java` at 9,889 bytes was unreadable by every route from call 0068 to the kill; the model said "389 lines, which is not that large" and ended up web-searching a `file://` URL to see its own code. Found independently by three readers who could not see each other's ranges | open | |
| 2 | 1 | **cria named the wrong file for a deliverable** — steer 0109 says "create `data/review.md`"; the task and `verify.py:190` want `REVIEW.md`. One check lost to a filename, and the steer author is forbidden from choosing files at all | open | |
| 3 | 1 | **cria cannot see `node`, so JavaScript had no syntax floor and no execution all cycle.** `toolpath` probes with `bash -lc`; nvm installs into `.bashrc`, which a non-interactive shell never sources. Verified cold: `-lc` finds nothing, `-lic` finds it. My own Tier 1 fix, half-built — the same hole hits rbenv, pyenv, nodenv, sdkman, asdf | open | |
| 4 | 1 | **cria's gate is not read-only.** Its only route to ground truth is the project's own test runner, and these tests POST over real HTTP — the workspace database ended with 53 orders in it. The failing count the model was chasing climbed 3 → 22 because cria kept moving it. Verified cold | open | |
| 5 | 1 | **the live-execution probe refuses to run the thing.** It fires and then declines with `X is not an entry point on disk` — in 6 of 24 cells. `pytest` is a program not a file; `pipeline.Importer` is a class path; `lookup.js` was 611 bytes and present. `exec-intent` asks the project how it runs, gets a true answer, and a file-existence test on the wrong token throws it away | open | |
| 5b | 2 | **a killed run loses its last reasoning.** `rust-toml-cli × ternary` call 0043 has a prompt and a body and no `.reasoning.txt` — the suite's kill terminates the process before the `finally` runs. The operator asked for all streamed reasoning logged whether it finishes or not; the fix covered stream errors and exceptions, not process death. Write it incrementally as it streams | open | |
| 5c | 1 | **(superseded framing) no probe ever starts the thing and asks it something.** Three cells now point at this from different directions: the migration branch the Python task is about was never executed by anything cria ran, the Java entry point was never invoked, and the Node CLI was never started. cria's probes are syntax linters plus the coder's own tests | open | |
| 6 | 1 | **a purposeful reasoner call with no output path.** The search supervisor returned `on_target: false` and a better query; `_add_note` wrote it to the `⟦cria⟧` display channel, which is stripped before the model. "off-target" appears zero times in the whole run — cria paid for the judgement and threw it away | open | |
| 7 | 1 | **cria refuses its own gate's output.** A per-probe cap of 8,500 and a per-result bound of 9,000, with a gate that joins several probes into one result — so an ordinary 231-line pytest run is discarded whole and the coder is told to re-run a command cria wrote. 21 refusals across 7 of the 24 cells; one of them was the coder's own failing test suite | open | |
| 8 | 1 | the Ruby task cannot be passed honestly: the prompt demands a third-party gem, the verifier only sees ruby's default load path, and cria correctly refuses any install that reaches it. The passes came from a gem left on the box on 2026-08-08 (`docs/audits/cycle-1-walk.md`, cross-run section) | open | |
| 9 | 1 | cria's install refusal prescribes the command to run, and on this box that command is the losing one — off the load path, and 900 files into the workspace | open | |
| 10 | 1 | the briefing prompt shipped at 167 KB against a 48 K window and the server refused it 12 times; 46% of it was the gem tree cria told the coder to create. `vendor` is deliberately excluded from the build-artifact skip set — **a documented earlier decision, do not revert without surfacing** | open | |
| 11 | 1 | the Java seed ships tracked `.class` files at exactly the path the checker imports from, so a workspace can look correct while the source is not. Task fault | open | |
| 12 | 2 | the gate's litter sweep deletes untracked build output — correct as "clean up my own probe", wrong as "leave the workspace as I found it", and it removes the one artifact that shows where the build put things | open | |
| 13 | 2 | the search note ends "in the file named above" and, on the inline path, nothing above names a file. Self-inflicted by the search-inlining change (#5b) | open | |
| 2b | 1 | spilled fetch keeps the URL's extension inside the workspace (`cria/webfetch.py:267`) — **ablation proves it**: verifier says FAIL with `tmp/` present, `ok` after `rm -rf tmp`. Cheapest fix in the ledger | open — first in the fix phase | |
| — | 1 | steer author's free-prose contract (`_steer_or_none`) | open — deferred at 0.1% prevalence, needs its own pass | |
| — | 3 | cria's story of what happened ≠ cria's own record (5 sites) | open | |
| — | 3 | word-matching decides when to interrupt | open — needs prevalence first | |
| — | 3 | a refusal that leaves no way forward | open | |
| — | 3 | calls the model made that never happened | open | |

Ranks are assigned in the rank phase, once the walk has said how many cells each one cost.

### Watching, not yet concluded

- **A dropped declaration is silent in some languages and impossible in others.** Cell 13 lost
  `package pipeline;` in a rewrite and scored 0%. Measured across every Java and Go workspace on
  disk: 1 of 17 files, one run. Go never loses it because Go refuses to compile a file without one;
  Java accepts the default package without a murmur. So the exposure is real but narrow, the cost
  when it lands is the whole cell, and the bar to ADD a guard is high (#1). The rank phase decides.

- **The rumination rate change.** Aborts on the cells that have run under it are mostly down —
  `orders-api-py × nemotron` 15/200 → 7/175, `cart-billing-go × nemotron` 6/124 → 2/51,
  `orders-api-py × qwen35` 4/260 → 1/131 — and up on one, `shipping-rates-rb × nemotron` 3/77 → 4/57.
  That is roughly what it was built to do. The four `feed-pipeline-java` cells are the real test and
  they have not run yet this cycle; the 11-aborts-in-35-calls figure on that task predates the change
  and says nothing about it.
- **Aborts cluster on one model, but they are not what sinks it.** nemotron-elastic this cycle:
  0% / 0% / 50% / 0% / 25%, with aborts of 4 / 2 / 7 / 1 / 0. Its best cell had seven aborts and its
  25% cell had none, so the guard is not the driver. What the five have in common is that four were
  killed at a milestone floor. That is the question worth reading, and it is now being read.

### Environment notes — established, deliberately NOT changed mid-cycle

- **Java is NOT blocked by its environment — checked directly.** The seed compiles clean out of the
  box, offline (`mvn -o compile`) and online. A third-party CSV dependency added to the `pom.xml`
  resolves and downloads (commons-csv 1.10.0, plus six versions already in `~/.m2` from earlier
  runs). So the task's mandatory "use a third-party Java CSV library" is satisfiable, and the three
  `mvn compile failed` cells are the models' own broken code plus the cria faults the walks found —
  not a wall like Ruby's. The cached `.m2` artifacts are contamination of the same shape as the Ruby
  gem but benign: the `pom.xml` must still declare the dependency and that declaration is what the
  checker reads.

- **`bundle` is not on this box's PATH.** Debian ships the binaries as `bundle3.2` / `bundler3.2`
  and nothing provides the unversioned name, so `bundle install` and `bundle exec` both answer
  "command not found" — for every model, on every Ruby run. The models fall back to `gem install`,
  which ignores the Gemfile's resolution and installs the newest transitive dependencies, which is
  how a 2014 gem ends up paired with a 2024 one that no longer exports what it requires.
- **It is a hazard, not a blocker.** `shipping-rates-rb`'s verifier runs bare `ruby -Ilib`, so the
  intended solution never needed bundler: `gem install countries` puts the gem on the default load
  path and `require "countries"` just works. Three runs prove it — every Ruby run that chose
  `countries` scored 60–100%, and both runs that chose `eu_countries` collapsed.
- **So the environment stays as it is.** Installing the binstub mid-campaign would change what is
  being measured and invalidate every Ruby row. What the walk has to answer instead is what cria
  told the model when `bundle` failed, and why nothing caught a library that could not load.

### Log

- **2026-08-14 02:45 → 07:33** — nothing. The run phase closed and the walk phase did not start.
  The per-cell watcher had been the heartbeat all night; when the last cell landed it fired for the
  last time, and the turn that closed the run phase ended on "continuing now" without launching
  anything. Five hours idle, found only because the operator asked. Rule added to the goal doc:
  never end a turn on an intention — have work in flight or say there is none.

- **2026-08-13** — cycle 1 run phase resumed at cell 9 after a driver-imposed `timeout 3000` killed
  `orders-api-py × gemma4` at 52 minutes of its own 60-minute wall. The cap is gone; the suite owns
  the only wall clock. The rerun finished in 21 minutes at 100%.
- **2026-08-13** — the campaign driver moved out of a session scratchpad into `suite/cycle_run.py`
  so a lost terminal cannot lose the loop.
- **2026-08-13** — the goal docs moved to `docs/goals/` and the port-fidelity audit to
  `docs/audits/`; every reference in `docs/` and `suite/` was repointed. Three comments under
  `cria/` still name the old path (`cria/loop.py:1757`, `cria/loop.py:3952`,
  `cria/probediscovery.py:854`). They are inert text and they wait for the fix phase — one code
  state per cycle applies to a comment as much as to a line that runs.
