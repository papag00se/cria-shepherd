# 100% campaign — live progress

**This file is the status.** Not a chat message, not a memory, not an intention. The goal it serves
is `docs/goals/hundred-goal.md`. The score grid it summarises is `docs/audits/battery-report.md`, which
rewrites itself after every cell.

**Target: 24 of 24 cells at 100%.** Currently 8.

---

## Cycle 1

**Phase: RUN** — started 2026-08-13, cell 14 of 24 in flight. Walks of the finished cells run
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
| 14 | feed-pipeline-java | qwen35 | | | | | |
| 15 | feed-pipeline-java | ternary-bonsai | | | | | |
| 16 | feed-pipeline-java | nemotron-elastic | | | | | |
| 17 | handles-cli-node | gemma4 | | | | | |
| 18 | handles-cli-node | qwen35 | | | | | |
| 19 | handles-cli-node | ternary-bonsai | | | | | |
| 20 | handles-cli-node | nemotron-elastic | | | | | |
| 21 | rust-toml-cli | gemma4 | | | | | |
| 22 | rust-toml-cli | qwen35 | | | | | |
| 23 | rust-toml-cli | ternary-bonsai | | | | | |
| 24 | rust-toml-cli | nemotron-elastic | | | | | |

Δ is percentage points against the previous run of the same cell, whatever prompt revision it was
earned against. Run ids are on the rows in `suite/results/results.jsonl`.

### Findings ledger — cycle 1

Seeded from work already done; the walk phase appends to it.

| rank | tier | finding | state | closed by |
|---:|---|---|---|---|
| 1 | 1 | **cria refuses its own gate's output.** A per-probe cap of 8,500 and a per-result bound of 9,000, with a gate that joins several probes into one result — so an ordinary 231-line pytest run is discarded whole and the coder is told to re-run a command cria wrote. 21 refusals across 7 of the 24 cells; one of them was the coder's own failing test suite | open | |
| 2 | 1 | the Ruby task cannot be passed honestly: the prompt demands a third-party gem, the verifier only sees ruby's default load path, and cria correctly refuses any install that reaches it. The passes came from a gem left on the box on 2026-08-08 (`docs/audits/cycle-1-walk.md`, cross-run section) | open | |
| 3 | 1 | cria's install refusal prescribes the command to run, and on this box that command is the losing one — off the load path, and 900 files into the workspace | open | |
| 4 | 1 | the briefing prompt shipped at 167 KB against a 48 K window and the server refused it 12 times; 46% of it was the gem tree cria told the coder to create. `vendor` is deliberately excluded from the build-artifact skip set — **a documented earlier decision, do not revert without surfacing** | open | |
| 5 | 1 | the Java seed ships tracked `.class` files at exactly the path the checker imports from, so a workspace can look correct while the source is not. Task fault | open | |
| 6 | 2 | the gate's litter sweep deletes untracked build output — correct as "clean up my own probe", wrong as "leave the workspace as I found it", and it removes the one artifact that shows where the build put things | open | |
| 7 | 2 | the search note ends "in the file named above" and, on the inline path, nothing above names a file. Self-inflicted by the search-inlining change (#5b) | open | |
| — | 1 | spilled fetch keeps the URL's extension inside the workspace (`cria/webfetch.py:267`) | open — first in the fix phase | |
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
- **Aborts cluster on one model.** 24 of the 26 in the cycle so far are nemotron-elastic, which also
  scores 0% in three of its four finished cells. Whether the guard is catching a model that genuinely
  spirals or helping to sink it needs a read, not a count (#23b). Queued for the walk phase.

### Environment notes — established, deliberately NOT changed mid-cycle

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
