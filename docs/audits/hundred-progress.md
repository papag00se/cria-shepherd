# 100% campaign — live progress

**This file is the status.** Not a chat message, not a memory, not an intention. The goal it serves
is `docs/goals/hundred-goal.md`. The score grid it summarises is `docs/audits/battery-report.md`, which
rewrites itself after every cell.

**Target: 24 of 24 cells at 100%.** Currently 8.

---

## Cycle 1

**Phase: RUN** — started 2026-08-13, cell 11 of 24 in flight.

Driver: `python3 suite/cycle_run.py --start <n>` · log `docs/audits/cycle-run.log`

### Cells

| # | task | model | score | Δ pts | min | calls | what happened |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | shipping-rates-rb | gemma4 | 20% | −80 | 17 | 68 | chose a dead gem. `eu_countries` 0.0.2 (2014) opens with `require "iso3166"`, an entry point gone from modern `countries`, so `require 'eu_countries'` raises LoadError and the four checks that load the library all die on it. The fifth only reads the README. Walk in progress on the question that matters: it declared done on a library that cannot load, and the completion gate did not stop it |
| 2 | shipping-rates-rb | qwen35 | **100%** | +40 | 8 | 92 | |
| 3 | shipping-rates-rb | ternary-bonsai | 80% | 0 | 16 | 52 | |
| 4 | shipping-rates-rb | nemotron-elastic | 0% | 0 | 16 | 57 | |
| 5 | cart-billing-go | gemma4 | **100%** | +40 | 7 | 36 | |
| 6 | cart-billing-go | qwen35 | **100%** | +20 | 10 | 80 | |
| 7 | cart-billing-go | ternary-bonsai | **100%** | +100 | 16 | 54 | |
| 8 | cart-billing-go | nemotron-elastic | 0% | −20 | 16 | 51 | cria's own spilled fetch, saved as `…decimal.go` inside the workspace, was compiled by `go build ./...` — all five checks died on it |
| 9 | orders-api-py | gemma4 | **100%** | 0 | 21 | 71 | |
| 10 | orders-api-py | qwen35 | 50% | −25 | 29 | 131 | model defect, reproduced: its `init()` runs `CREATE TABLE IF NOT EXISTS` (a no-op on the pre-migration database the checker supplies) then `UPDATE orders SET status=…` on a column that was never added — service exits 1, two checks die with it |
| 11 | orders-api-py | ternary-bonsai | *in flight* | | | | |
| 12 | orders-api-py | nemotron-elastic | | | | | |
| 13 | feed-pipeline-java | gemma4 | | | | | |
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
| 1 | 1 | the Ruby task cannot be passed honestly: the prompt demands a third-party gem, the verifier only sees ruby's default load path, and cria correctly refuses any install that reaches it. The passes came from a gem left on the box on 2026-08-08 (`docs/audits/cycle-1-walk.md`, cross-run section) | open | |
| 2 | 1 | cria's install refusal prescribes the command to run, and on this box that command is the losing one — off the load path, and 900 files into the workspace | open | |
| 3 | 1 | the briefing prompt shipped at 167 KB against a 48 K window and the server refused it 12 times; 46% of it was the gem tree cria told the coder to create. `vendor` is deliberately excluded from the build-artifact skip set — **a documented earlier decision, do not revert without surfacing** | open | |
| 4 | 2 | the search note ends "in the file named above" and, on the inline path, nothing above names a file. Self-inflicted by the search-inlining change (#5b) | open | |
| — | 1 | spilled fetch keeps the URL's extension inside the workspace (`cria/webfetch.py:267`) | open — first in the fix phase | |
| — | 1 | steer author's free-prose contract (`_steer_or_none`) | open — deferred at 0.1% prevalence, needs its own pass | |
| — | 3 | cria's story of what happened ≠ cria's own record (5 sites) | open | |
| — | 3 | word-matching decides when to interrupt | open — needs prevalence first | |
| — | 3 | a refusal that leaves no way forward | open | |
| — | 3 | calls the model made that never happened | open | |

Ranks are assigned in the rank phase, once the walk has said how many cells each one cost.

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
