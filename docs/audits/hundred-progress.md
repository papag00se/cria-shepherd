# 100% campaign — live progress

**This file is the status.** Not a chat message, not a memory, not an intention. The goal it serves is `docs/goals/hundred-goal.md`. The score grid it summarises is `docs/audits/battery-report.md`, which rewrites itself after every cell.

**Target: 24 of 24 cells at 100%.** Currently 9 — mean 53.8%.

---

## Cycle 4 — RUN in flight

**Phase: RUN.** Started 2026-08-16 16:5x on the post-sweep code state, `8be9ea8`. Twenty-four cells, **model-major** for the first time — one model loaded, then taken through all six languages, so the grid fills a readable ROW at a time instead of a column.

**Pre-run checks, both clean:**
- `git status --short suite/tasks` — empty. No verifier writing into the repo.
- The user-level install listing carries **no `gem:` entries**. The `countries-8.1.0` leak that inflated four Ruby rows for weeks is gone, and `shipping-rates-rb` is the one task whose third-party check a user-level package could satisfy without a manifest. The go/maven/npm/cargo caches are present and are *not* the same hazard: those four verifiers require a declaration in the manifest that a warm download cache cannot supply. Recorded as a fact; the per-row `user_install_leak` delta remains the tripwire.
- The service restarted at **16:47:40**, ten seconds after `8be9ea8`, and every fix from this cycle's FIX phase was confirmed present in the **importable module** — not just in the file. That check exists because chaining the restart and the launch into one backgrounded command once raced and invalidated a whole run.

**What changed since cycle 3**, in one line each — the full ledger is [`sweep-fix-progress.md`](sweep-fix-progress.md):

| # | fix | why it should move a cell |
|---:|---|---|
| 1 | harness-compaction detector had **never fired** (0 events vs 139 compactions) | a gate result lost to a compaction now gets re-issued instead of vanishing |
| 2 | a gate cria READ was discarded when the turn returned through the guard-probe door | green→red on a redirect turn no longer leaves cria believing green |
| 3 | the window is learned from what the server accepts; the runaway guard gates on evidence, not on "stop probing" | 8,192-fallback runs destroyed 934 protected messages; runaways to `total_tokens = 49152` were untouched |
| 4 | dirguard: **492 of 1,225** captured refusals named nothing the coder could change | a tool signature written as a command, and `$(go env GOPATH)/…` tails, are no longer refused |
| 5 | `go test -v` | the deleted-test signal was structurally mute on Go |
| 6 | one owner for "is this a test file" | JUnit's `TestImporter.java` prefix convention read as ordinary source |
| 7 | `rake` / `make` / `mix` / `gradle` are runnable | whole languages' deliverables were accepted as the entry point then refused as unrunnable |
| 8 | shell tool matched by family | a harness whose shell has an unfamiliar name had it deleted from the menu |
| 9 | 2.1 MB of duplicate payload folded out of coder prompts (882 of 6,614) | ~522K tokens back |
| 10 | a judge's proposed fix clears the steer bar; the done note claims only what ran | invented URLs and false verification claims |

Cells land here as they finish. **Two numbers**: `strict` is the all-or-nothing verifier, kept as the anchor; `useful` is the judged answer to "how much of what they asked for did they actually get?" — the campaign's real question. See [the JUDGE phase](../goals/hundred-goal.md) and the rubric in `suite/prompts/usefulness_judge.txt`.

| # | task | model | strict | useful | what the person actually got |
|---:|---|---|---:|---:|---|
| 1 | shipping-rates-rb | gemma4 | 1/5 | **25%** | Full README rate table, the gem correctly declared and installed, and zone logic that is right — but the library does not load: `require "iso3166"` names no installed file |
| 2 | cart-billing-go | gemma4 | 5/5 | **100%** | Everything, verified by execution |
| 3 | orders-api-py | gemma4 | 4/4 | **100%** | Everything, verified by execution |
| 4 | feed-pipeline-java | gemma4 | 0/5 | **10%** | One of five attempted; commons-csv added correctly, then fabricated API — does not compile |
| 5 | handles-cli-node | gemma4 | 3/4 | **75%** | A working CLI, dependency removed, valid Dockerfile; no discoverable tests (`node --test` collected 0) |
| 6 | rust-toml-cli | gemma4 | 0/4 | **95%** | A complete, correct, working CLI — in `toml-cli/` instead of the working directory |
| 7 | shipping-rates-rb | qwen35 | 1/5 | **15%** | Zone mapping genuinely right — and a **seeded assertion rewritten** from 15.99 to 32.99 |
| 8 | cart-billing-go | qwen35 | 5/5 | **100%** | Everything, verified by execution |
|  | | | **51%** | **65%** | |

### The baseline cannot be judged, and it is invalid anyway

Checked before re-scoring it, and the answer is worse than "not yet done":

- **Its evidence is gone.** All 24 baseline cells ran 2026-08-10. Archiving landed 2026-07-29, so the workspaces should be there — the oldest surviving archive is **2026-08-12**, and the baseline captures are gone too. Something removed everything older than the 12th, against the goal's own rule that run evidence is never deleted. With no workspace there is nothing to inspect, no re-probe, and no counterfactual: judging those cells would mean guessing where the strict score understates, which is the exact thing the judge was built to stop.
- **Its verifiers have since changed, ten times.** `git log --since=2026-08-10 -- suite/tasks/*/verify.py` lists changes to cart-billing-go, feed-pipeline-java, feed-pipeline-py, handles-cli-node, orders-api-py, shipping-rates-py and shipping-rates-rb — including two that removed contaminants and three that stopped a check failing over capitalisation or punctuation. The goal already says a verifier change invalidates every row scored against it.

So the baseline is stale on two counts, and neither is fixable by re-scoring. **It has to be re-run** — 24 cells with assists off, judged as they land like any other cell. Until then every BASE number carries `ˢ`, every BASE↔CRIA Δ is blank, and the grid says so rather than implying a comparison it cannot make.

**Scheduled: after this cycle's CRIA arm finishes** (operator, 2026-08-16). The assisted arm is the one that answers the question; the baseline only sizes the gain. The command is the same driver with the arm flipped, and it restores the flag afterwards so an interrupted run cannot leave the live config in the baseline arm:

```
python3 suite/cycle_run.py --arm BASE
```

Judge each baseline cell as it lands, the same way — `usefulness.py pending` is arm-agnostic and will list them.

**Strict says 51%. Useful says 65%.** The gap is one cell: rust-toml-cli, 0 strict and 95 useful, where the work was finished and correct and one directory too deep. Every other cell moves by less than 15 points, which is the check that the new number is not simply generosity.


**gemma4 — row complete: 1/5, 5/5, 4/4, 0/5, 3/4, 0/4 → 13 of 27 checks, 48%.** Two clean 100%s, and three of the four losses are cria's: a Ruby install route that stated the problem instead of answering it, a green gate over a project in a subdirectory, and a 12-minute runaway the only bound could not catch sooner. All three fixed during the row.

**Mid-run fixes.** The operator's call: the goal is 100%, not measurement fidelity, so a defect gets fixed when it surfaces rather than parked until the FIX phase. Prompt files load from disk on every call, so a prompt fix is live on the next call with no restart. Recorded here so a cell's score can be read against the code it actually ran on.

| after cell | sha | change |
|---:|---|---|
| 1 | `9eeee96` | **Ruby install routes now ANSWER reachability.** `gem_bundler` said the install is reachable only under bundler and offered "or make the library loadable without bundler" — a restatement, not a way out. It now names `require "bundler/setup"` as the first line of the library, verified by running all three shapes the verifier uses. `gem_direct` led with `GEM_HOME`, which covers only self-launched commands; `$LOAD_PATH.unshift` leads now. Affects cells 7, 13, 19 |
| 4 | `e235d1b` | **An aborted stream names the guard that stopped it.** Four backstops abort a stream; the capture header called all four the rumination guard and rendered that guard's counters, so a window-exhausted abort read `None second-guessing markers`. Each guard now prints only what it counted, and the window wording says why stopping was free rather than a latency cap. Two tests had encoded the misattribution and were corrected |
| 5 | `d9bf9bb` | **A file named `test_lookup.js` is not "no tests were found".** The stranded check keyed on the JS marker `describe(`, which cannot see test code written without a framework, so cria said the project had no tests. It now strands on the FILENAME too — `test`/`spec` as a whole leading or trailing word, tight enough that `testing`, `latest` and `specification` stay out. In the verifier: a runner that collected 0 tests exits 0 both ways and was being reported as "mocked, not live"; it says what happened now (score unchanged) |
| 6 | `bc8be36` | **A green gate that could only run from a subdirectory says which one.** The plan read back, not a judgement about layout: it fires only when NO real check could run at the workspace root, the case where the directory the harness gave the model contains no buildable project. The syntax floor is excluded (it walks from the root by construction). Two edges the tests caught: `abspath("")` is the CWD, and a `working_dir` that climbs out of the workspace is not a subdirectory of it |

| # | task | model | score | Δ | min | calls | what happened |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | shipping-rates-rb | gemma4 | 20% | **−40** | 31 | 83 | **`gem_bundler`'s shadow, and it took four of five checks.** The model installed the gem correctly — `bundle3.2 install --path vendor/bundle` landed `countries-8.1.0` under `vendor/bundle`, and it read the gem's own source. Then its `lib/shipping/rates.rb` opens `require "iso3166"`, which resolves ONLY under `bundle3.2 exec`, and every verifier probe runs bare `ruby -Ilib`. `suite_green_tests_intact`, `hidden_contract`, `express_zone` and `country_zone_mapping` all die on the same `kernel_require.rb:86` LoadError. Only `readme_rate_table` survives (four zones named, 8/8 rate values). **The model diagnosed it itself** and could not escape: *"When I ran `bundle3.2 install --path vendor/bundle`, it installed everything into `vendor/bundle`. But because I am running with `ruby -Ilib -Itest`, it's not looking in the bundle path."* cria rendered BOTH routes — `GEM_HOME` in 26 prompts, the bundler line in 54 — and the model took the one that cannot be loaded bare. Not a new finding: cycle 3 wrote "`gem_bundler` buys the dependency check and costs the bare-ruby one", and it is still open. Also the first-ever live fire of **`loop.history_rewritten`** (1), the detector that had 0 fires against 139 real compactions. **CORRECTION, from the counterfactual I should have run before writing the above:** the reachability gap is real but it was NOT the primary cause. The model wrote `require "iso3166"` — the gem's CONSTANT namespace, not its require path; the gem is `countries` and no installed gem provides a file called `iso3166`. Correcting the name alone still fails (the `--path` install is unreachable bare); adding `bundler/setup` alone still fails (the name is wrong). **Both together score 2/5**, with `country_zone_mapping` green — Croatia=eu, Switzerland and Norway=international, cost 15.99. So the cell needed two one-line fixes, cria's advice covered one of them |
| 2 | cart-billing-go | gemma4 | **100%** | **+20** | 4 | 28 | **Five of five, and the cleanest run this cell has ever had** — 28 calls in 4.2 minutes, against 66 calls and 80% last cycle. Every check green: totals at 48.58 with the hidden cases, `discounts.json` present and the build still passing without it, the stderr line carrying subtotal/code/total, and `shopspring/decimal` both declared and imported by non-test source. **The seeded test survived this time** — cycle 3 lost this cell to a deleted `TestUnknownCode`, and `go test -v` now makes that deletion visible to the regression signal rather than silent. No steer fired at all: no repetition, no wheel-spin, no thrash |
| 3 | orders-api-py | gemma4 | **100%** | **+100** | 12 | 52 | Four of four, against **0%** last cycle where it floored at the 15-minute milestone with 18 calls. Every check green: `GET /customers/alice/orders` returning her items with a total, the schema migrated with old rows still readable and an index on customer, the integration suite making real HTTP calls, and the injection closed with the table intact. The wheel-spin guard fired once and the reasoner authored the steer from real check output — `authored: true, grounded: true`, the metric that used to be the literal `spoke: true` |
| 4 | feed-pipeline-java | gemma4 | 0% | 0 | 15 | 19 | **One runaway ate 12 of the 15 minutes.** Nine fast calls (2–16 s) took it to 00:48, then a single generation ran until the window-exhaustion backstop stopped it at 01:00:35 — 95% of the cell's wall was model generation, only 19 calls in total, `mvn compile` never succeeded. Third consecutive 0 on this cell. The backstop worked (before it, that call ran to the hard window limit and was discarded whole) but the cell was already gone. **What it exposed:** the capture header filed the window-exhausted abort as `⟦RUMINATION GUARD FIRED⟧ None second-guessing markers · ~None reasoning tokens` — wrong guard, and `None` for numbers nothing counted. Fixed mid-run. **Counterfactual: this one is the model's.** It added `commons-csv` to `pom.xml` correctly and rewrote 51 lines of `Importer.java`, but the API is fabricated — `CSVFormat.Builder.setSkipInitialNewline`, `record.getHeader()`, `record.newNode()` are all invented, revealed one batch at a time by javac. Not close, and with ~3 minutes of usable clock it had no room to iterate |
| 5 | handles-cli-node | gemma4 | 75% | 0 | 5 | 35 | Three of four, flat for a third cycle. CLI behaviour, the removed dependency and the Dockerfile all green. The loss is `tests_incl_live`, and **neither side was telling the truth about it.** The model wrote its tests into `test_lookup.js`; `node --test` matches none of its globs, collected **0 tests**, and exits 0 with and without the network — so the verifier called it *"passes with the network BLOCKED — mocked, not live"* over a project with no discoverable tests. cria meanwhile announced *"No jest/vitest tests were found"* with the file sitting in the workspace root. Both fixed mid-run: the verifier says when a run collected zero (same score), and cria now strands the file by NAME when no marker can see it — *"Test code in test_lookup.js will not run"*, one rename from fixed |
| 6 | rust-toml-cli | gemma4 | 0% | **−100** | 9 | 38 | **The worst kind of green.** A from-scratch task: the model ran `cargo new toml-cli` and built a complete, working Rust project — `Cargo.toml`, `src/main.rs`, `README.md`, a compiled `target/` — **inside `toml-cli/`**. cria's gate cd'd into that folder for four of its five probes, they all passed, the gate went GREEN, the completion critic approved and the session exited normally. The verifier runs `cargo` at the working directory: *"could not find `Cargo.toml` … or any parent directory"*. **0 of 4 on a cell that had scored 4/4 for three cycles running.** cria held the fact the entire time — `working_dir=toml-cli` on every probe it composed — and never said it. **Counterfactual: moving the folder to the workspace root and changing nothing else scores 4/4.** Clean build, 3/3 nested lookups including `server.limits.max_conn → 250`, the error contract, tests and README. The work was not close to right — it WAS right, one directory down. Fixed mid-run |

---

## Cycle 2 — RANK complete, FIX next

**Phase: FIX.** All eight walk agents reported. Findings in `docs/audits/cycle-2-walk.md`; the ranked list is below and folded into `docs/audits/context-footgun-backlog.md`.

## Cycle 3 — RUN stopped at 8 of 24, then WALK + RANK + FIX

**Eight valid cells**, 04:48–07:51, task-major. The run was stopped there deliberately: the walk had enough to work with and the fix phase was the bottleneck. Findings in `docs/audits/cycle-3-walk.md`, fixes in `docs/audits/cycle-3-fixes.md`, and the application-wide sweep that followed in `docs/audits/application-sweep.md` + `sweep-fix-progress.md`.


**Restarted three times, and the third restart is the one that counts.** The run below begins 2026-08-16 04:48 on the eight-fix code state, with the service verified up first.

- **23:10** — started on the six-fix state. Stopped at cell 9 after a 720 s / 44,058-token call took a cell that had scored 100% in both previous cycles to 0%.
- **03:12** — restarted with the window-exhaustion guard. Stopped at cell 1: the guard counted characters cria had accumulated and the tokens were arriving in a shape the reader does not collect, so it missed the very call it was built for.
- **03:59** — restarted with the guard counting frames. **This run was invalid**: the service restart and the run launch were chained into one backgrounded command and raced, so cell 1 ran 03:59–04:45 on the *pre-fix* code while the service came up at 04:46. My error, and the reason two more runaways (669 s and 649 s) went untouched — nothing was wrong with the guard, it was not running.
- **04:48** — restarted sequentially and verified: run stopped, repo at `93e84b8`, the guard line confirmed present in the **importable module** rather than just the file, service restarted and confirmed active, run started twelve seconds later.

*Measured while diagnosing, rather than assumed: a 120-token request to the live server returns 121 SSE frames carrying a delta. One frame per token, so counting frames is a faithful token proxy here.*

| # | task | model | score | Δ | min | calls | what happened |
|---:|---|---|---:|---:|---:|---:|---|
| 8 | cart-billing-go | nemotron-elastic | 20% | **+20** | 31 | 107 | off zero again, and the whole build hangs on **one invented method**: `./cart.go:58:27: undefined: decimal.NewFromFloat64`. The real name is `decimal.NewFromFloat`. Eight rumination aborts, seven of them degenerate, no runaway. `decimal_money_library` passes for the second cycle running |
| 7 | cart-billing-go | ternary-bonsai | 20% | **−80** | 31 | 61 | floored at thirty minutes, no runaway (longest 87.4 s). It swapped the money type in and never finished the conversion: `cart_test.go:18:12: cannot convert 9.72 (untyped float constant) to type struct{value *big.Int…}` and `in call to taxed.Round — have (number, number), want (int32)`. Only `decimal_money_library` survives, because declaring and importing the module is exactly what it half-did |
| 6 | cart-billing-go | qwen35 | 60% | −40 | 20 | 158 | **it renamed the package.** The passing test line reads `ok billing` where the seed is `cartsvc`, and the verifier's probe then reports `package cartsvc is not in std` — so `rounding_fixed_everywhere` fails on an import, not on arithmetic. `logging` carried nothing on stderr. Same shape as cycle 1's Java cell that dropped `package pipeline;`: one declaration changed, and every check that loads the package dies behind it |
| 5 | cart-billing-go | gemma4 | 80% | −20 | 13 | 66 | four of five, and the loss is **a deleted seeded test** again — `TestUnknownCode`. Everything else green: rounding at 48.58, `discounts.json` with and without the file, the stderr line, a real decimal module in non-test source |
| 4 | shipping-rates-rb | nemotron-elastic | 0% | −40 | 16 | 59 | floored at fifteen minutes, no runaway (longest 65.5 s), two degenerate aborts. Nothing landed: README names one zone, no own tests, no third-party require at all |
| 3 | shipping-rates-rb | ternary-bonsai | **80%** | **+60** | 76 | 62 | biggest gain of the cycle. Four of five: the repo's tests intact, `hidden_contract` green, the express zone with its own tests, the full 8/8 rate table. Only `country_zone_mapping` fails, and for a reason of the model's own — it reached for `active_support` instead of the countries gem and the require chain dies. **Useful evidence the window guard is not over-firing**: three calls at 272 s, 265 s and 260 s were left alone, which is right — on a ~40 tok/s model those are ~11,000 tokens, nowhere near the window |
| 2 | shipping-rates-rb | qwen35 | 0% | −40 | 16 | 134 | floored at fifteen minutes despite 134 calls and no runaway (longest 104.9 s), so the clock went on work, not on a stuck stream. Two things bit: a **seeded test was MODIFIED** — `test_unknown_zone_rejected`, the contract changed rather than satisfied — and `hidden_contract` is back on the bundler LoadError. `readme_rate_table` still names one zone |
| 1 | shipping-rates-rb | gemma4 | 60% | −20 | 8 | 57 | **no runaway at all** — longest call 47.2 s against 669–720 s on every previous attempt, and the whole cell finished in 8.2 minutes instead of 43. The window guard is live and did **not** fire, so this run simply had nothing for it to catch; it remains unexercised. `hidden_contract` passes again (twice running now), so the bundler load-path wound is not universal. The two losses: a **deleted seeded test** (`test_negative_weight_rejected`), and `country_zone_mapping` mapping almost everything to `international` |


| # | task | model | score | Δ | min | calls | what happened |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | shipping-rates-rb | gemma4 | **80%** | 0 | 29 | 94 | **`country_zone_mapping` passes for the first time on this model** — `third-party requires: ['bundler/setup', 'countries/global']` and real zones, where cycle 2 said "none". The install-remedy fix worked: told to run `bundle3.2`, the model installed the gem and used it. The one loss is `hidden_contract`, and it is the same fix's shadow — the model's `rates.rb` now opens `require "bundler/setup"`, and the hidden test runs bare `ruby`, so it dies on a LoadError. `gem_bundler` buys the dependency check and costs the bare-ruby one; `gem_direct`'s text is the route that warns about exactly this |

| 2 | shipping-rates-rb | qwen35 | 40% | 0 | 29 | 204 | **the 259 KB death is gone** — cycle 2 killed this cell with six HTTP 400s; this run finished normally, 204 calls, no oversize body, longest call 137.8 s. The vendor-fold fix did its job. But three checks now die on a LoadError, and that is the install fix's own doing — see below |
| 3 | shipping-rates-rb | ternary-bonsai | 0% | **−20** | 16 | 48 | killed at the 15-minute floor. **The install fight is much shorter** — 3 `blocked_external` against cycle 2's 10, and the model got the gem (`third-party requires: ['countries']`) instead of spending half its budget failing to. It ran out of clock on the work instead: README still names one zone, it wrote no tests of its own, and `country_zone_mapping` dies on the same bare-`ruby` LoadError as cells 1 and 2. Worth noting `express_zone` reads **"prices 14.99 24.99 (want 14.99 24.99)"** and still fails — it is a compound check and the other half, "model wrote its own tests", is False |
| 4 | shipping-rates-rb | nemotron-elastic | 0% | **−40** | 25 | 65 | exited on its own. Every failing check is a `require` LoadError, and `country_zone_mapping` shows the model reaching straight into the tree — `third-party requires: ['vendor/countries/countries']`. 7 `blocked_external`, 4 rumination aborts, no runaway |
| 5 | cart-billing-go | gemma4 | **100%** | **+20** | 6 | 38 | all five green in six minutes. The seeded `TestSubtotal` deletion that cost this cell 20 points last cycle did not happen — `suite_green_plus_regression_test` passes, the rounding is right at 48.58, `discounts.json` works with and without the file, the stderr line carries all three fields, and a real decimal module is imported by non-test source |
| 6 | cart-billing-go | qwen35 | **100%** | 0 | 30 | 225 | all five green, held. **And this is the operator's ruling working, live** — see below |
| 7 | cart-billing-go | ternary-bonsai | **100%** | 0 | 16 | 55 | all five green, held, in 55 calls. One gate, one done-critic, one satisfaction confirm — the completion machinery closed it in a single exchange, the shape cell 18 of cycle 2 showed and cell 14 did not |
| 8 | cart-billing-go | nemotron-elastic | 20% | **+20** | 31 | 92 | **off zero for the first time in the campaign.** `decimal_money_library` passes — declared in `go.mod` *and* imported by non-test source, which is the exact clause it failed on last cycle ("imported by non-test source: none"). The build still does not compile (`cart.go:57:64: too many errors`) so the other four fall behind it. Six degenerate aborts and one phrase abort; no runaway, longest call 126.7 s |

**Go column complete: 100 / 100 / 100 / 20 = 80%**, against cycle 2's 80 / 100 / 100 / 0 = 70%.

### THE OPERATOR'S RULING, VALIDATED ON CELL 6

`loop.satisfaction_gap_named` fired **five times**, and all five reached the coder — verified by counting the request bodies carrying the steer, not by trusting the event:

```
08:45:35  decimal.NewFromString() was used incorrectly in a single-value context
08:48:38  the discount code 'SUMMER25' is not being applied (output shows 'di…
08:52:50  the binary isn't finding the discounts.json file at runtime, which breaks the end-to-end flow
08:55:21  live execution shows discount=none when SUMMER25 code was provided
09:00:32  cmd/main.go has a critical bug: it reads the disc…
```

Five checks, five **distinct** gaps — the never-twice-running bound held, so none of this was the clock-noise the original no-steer decision was defending against. Every one names a specific, checkable defect rather than an opinion about completeness.

**And the cell scored 5 of 5.** `discounts_from_file` and `logging` both pass, which are precisely the checks the discount bug named at 08:48, 08:52 and 08:55 would have failed.

Before the ruling, all five of those verdicts were computed and thrown away. This is the mechanism cycle 2 measured going silent on `Shipping.zone_for` four times while the cell ended 2 of 4 with the method missing.

### REGRESSION — MINE. The install fix cost the Ruby column 15 points

Ruby is complete and it moved the wrong way:

| | cell 1 | cell 2 | cell 3 | cell 4 | mean |
|---|---:|---:|---:|---:|---:|
| cycle 2 | 80% | 40% | 20% | 40% | **45%** |
| cycle 3 | 80% | 40% | 0% | 0% | **30%** |

**The cause is the fix I landed yesterday**, and the chain is the one recorded two entries above. Before it, `_local_install_advice` named `bundle`, which does not exist here; the advice failed with `command not found` and the models fell through to `gem install`, which puts the gem **on the default load path**. That is how cycle 1's Ruby 100% runs happened. After it, the advice names `bundle3.2`, the models follow it, and `--path vendor/bundle` puts the gem where bare `ruby -Ilib` cannot see it.

Every failing check across cells 2, 3 and 4 is a `require` LoadError. Cell 4's model gave up on `require "countries"` entirely and reached into the tree by hand: `third-party requires: ['vendor/countries/countries']`.

**So the fix was right about the false fact and wrong about the remedy.** cria was naming a command that could not run; it now names one that runs and leaves the dependency unloadable. Both are #5b failures — the second is just quieter, because the command succeeds.

**What it does NOT touch:** the `gem` routes are the only ones that changed behaviour, so cells 5–24 (Go, Python, Java, Node, Rust) cannot meet this. The damage is done and contained to a column that has already finished.

**Therefore the cycle runs on.** Stopping now would buy nothing — the affected cells are behind us — and would cost the one-code-state property for the twenty ahead. The Ruby column gets re-run after the fix phase, which is the same treatment any superseded row gets.

### Go column, cycle 3: 80 / 60 / 20 / 20 = **45%** (cycle 2: 70%)

Down, and not one of the four losses is cria's. Read together they are all the same shape:

| cell | what the model did | what it cost |
|---|---|---|
| gemma4 | deleted a seeded test | 1 check |
| qwen35 | renamed the package `cartsvc` → `billing` | 2 checks, on imports not arithmetic |
| ternary-bonsai | swapped the money type in, never finished the conversion | 4 checks |
| nemotron-elastic | called `decimal.NewFromFloat64`, which does not exist | 4 checks |

**A structural edit left half-done, and the checks cannot reach the work behind it.** No runaways, no cria injections in the chain, and in every case a good deal of correct code sits behind a broken boundary. That is a different failure class from the ones this campaign has been chasing — cria feeding the model something false, or eating its clock — and those are getting rarer as the fixes land. This is what is underneath.

### RE-MEASURED — seeded-test tampering, and it is NOT my fixes

Three of the first five cells this cycle tampered with a seeded test — two deletions and one **modification** (`test_unknown_zone_rejected`, "the contract was changed, not the code", a shape the earlier count never saw). Against a 4% historical rate that is roughly 1-in-800 by chance, so it demanded an explanation before anything else was read.

**Checked first, because the reflex is self-suspicion — and it is not the new assists.** `loop.satisfaction_gap_named` fired **zero times in all five cells**, so the operator's ruling cannot be the cause. Gate results fired in every cell including both that did *not* tamper, so the widened gate text does not separate them either.

**What does separate them is the model.** Per-model, tampering rows over scored rows:

| model | history | cycle 3 |
|---|---|---|
| **gemma4** | **10/74 = 14%** | 2/2 |
| qwen35 | 2/52 = 4% | 1/1 |
| ternary-bonsai | 2/61 = 3% | 0/1 |
| nemotron-elastic | 2/56 = 4% | 0/1 |
| every other model ever run (9 of them) | **0 of 157** | — |

gemma4 is a 14% tamperer and always has been; this cycle simply drew it twice in five cells. The cluster is the schedule, not a regression.

**What it does change is the earlier decision.** I measured this at 1.9% and declined to build a guard, on the grounds that the bar to ADD is high. The right denominator was never "all rows" — nine models have never done it once. On the model that does, it is 14%, and it has now cost checks in three different tasks and two languages. That is worth re-ranking next cycle, with the guard shaped as regression-only: a write that removes or weakens a test that currently PASSES is the exact "never delete correct content" case #2 sanctions.

### Ruby column, cycle 3 (valid run): 60 / 0 / 80 / 0 = **35%**

Against cycle 2's 45% and the invalid run's 30%. And the per-cell numbers are the finding, not the mean — **this task's four cells have now spanned 100 points on identical prompts**:

| cell | c1 | c2 | c3-a (invalid) | c3 |
|---|---:|---:|---:|---:|
| gemma4 | 20% | 80% | 0/80% | 60% |
| qwen35 | 100% | 40% | 40% | 0% |
| ternary-bonsai | 80% | 20% | 0% | **80%** |
| nemotron-elastic | 0% | 40% | 0% | 0% |

No cria change explains a swing that size in both directions at once. What the cells have in common is the **fifteen-minute floor**: every 0% here was floored, and every score above 40% came from a run that cleared it and got the rest of its hour. A model that stumbles in the first fifteen minutes is scored on a fifteen-minute run; one that does not is scored on a seventy-five-minute one. That is a measurement property, not a model property, and it is the strongest candidate for why this column will not settle.

`hidden_contract` passed in 2 of 4 cells here, so the bundler load-path wound is real but intermittent — it depends on whether the model writes `require "bundler/setup"`, which is exactly the thing `gem_bundler`'s text omits to tell it.

### TIER 1 (c3) — my install fix works, and the route it unlocked is the wrong one

The `bundle3.2` fix is doing exactly what it was built to do, and that is how it exposed the real defect underneath. Measured on cell 2, where cria emitted this advice **77 times**:

```
run `bundle3.2 install --path vendor/bundle`
```

The model followed it. The gem landed in `vendor/bundle`. Then, from the archived workspace:

```
$ ruby -Ilib -e 'require "shipping/rates"'
  lib/shipping/eu_check.rb:4: cannot load such file -- countries (LoadError)
$ ruby -e 'require "countries"'
  cannot load such file -- countries (LoadError)
```

`--path vendor/bundle` installs into a private prefix that is on **no** load path unless the code says `require "bundler/setup"` or the command runs under `bundle exec`. The verifier runs bare `ruby -Ilib`. Three of five checks die there.

Cell 1 lost only one check because that model happened to add `require "bundler/setup"` itself — and that is precisely why its `hidden_contract` failed, since the hidden test also runs bare `ruby`. Two cells, two different amounts of the same wound.

**Before the fix, cria's advice simply failed** (`bundle: command not found`) and the models fell through to `gem install`, which puts the gem on the default load path — which is how cycle 1's Ruby 100% runs happened. So the fix turned a route that did not run into a route that runs and leaves the dependency unloadable.

**The general defect, stated without reference to this task:** an install route must leave the dependency loadable by the way the project actually runs. `gem_direct`'s text already says this — *"then make it loadable by putting that directory on the load path"*. `gem_bundler`'s says nothing: it names a private prefix and omits the one thing that makes that prefix reachable. That omission is true of bundler `--path` in every project, not just this one.

**Fix phase, not now** — one code state per cycle, and cells 3 and 4 will meet the same thing, which is worth having on the record rather than patched away mid-run.

### TIER 1 (c3) — the dead stream, and the half of it the fix does NOT cover

**Landed mid-cycle and the run restarted from cell 1**, so cycle 3 is still one code state. The fix aborts a stream that has run many frames having accumulated **nothing readable** — the exact shape of the first occurrence: `content: null`, no reasoning, no tool-call fragment, `finish_reason: length`, `total_tokens` equal to n_ctx.

**It did not fire on the re-run, and the re-run hit the same thing.** Call 0009: 736.9 s, 44,549 tokens, `content` empty, `tool_calls` empty, `finish_reason: length`, 4,603 + 44,549 = **49,152 = n_ctx exactly**. Same outcome, and the guard stayed silent — so `streamed_chars` was not zero.

**The reading that follows:** this is not "nothing arrived". Tool-call argument fragments *did* arrive — a `write_file` whose arguments ran for twelve minutes and never closed — so cria counted them as readable, and the final assembly then discarded an unterminated call. Two shapes wearing one result:

| shape | what streams | covered by the new guard |
|---|---|---|
| nothing arrives at all | no deltas cria reads | **yes** |
| arguments arrive and never terminate | tool-call fragments, unclosed | **no** |

**What is NOT the fix.** A size cap on the arguments is precisely the footgun principle 6 forbids and the reason the rumination watcher excludes arguments in the first place; a legitimate large `write_file` is indistinguishable from this one until it ends.

**What might be, and needs the next fix phase rather than another mid-cycle edit:** cria holds `n_ctx` and the prompt's token count, so it knows the exact point past which a generation *can no longer be returned* — at that point `guard_truncation` will discard it whatever happens next. Aborting there destroys nothing that was going to survive, and it converts a silent twelve-minute loss into a labelled one the coder can be told about. That is deterministic ground truth, not a heuristic. It does not save the twelve minutes; it saves the next twelve.

Recorded, not built. One code state per cycle, and this cycle has already been restarted once.

### The original finding — a single call generates ~43,000 tokens and burns twelve minutes

**Not caused by this cycle's fixes, and checked before saying so.** Cycle 2's run of the *same cell* hit the identical runaway — 754.9 s for 43,616 tokens — and still scored 80%, because it landed with enough clock left. Cycle 3's landed inside the first fifteen minutes and the milestone floor took the cell. Same task, same prompt, same model, one call's position deciding 80 points.

Cycle 3 cell 1, from `upstream.done`:

```
06:24:43   703.6s   42,744 tokens   60.8 tok/s
```

Every other call in that run is 0.8–17 s. **That one call is 11.7 of the run's 15.9 minutes and it produced nothing** — `loop.truncated` and `loop.truncated_dropped` both fired, so the guard correctly threw away a self-truncated write.

**Prevalence, counted across every log on disk:** 14 calls over 300 s, in **12 distinct sessions**. Eleven of them are the same shape — 37,000 to 44,500 tokens, 680–783 seconds.

**Why nothing stops it.** Principle 6 says runaways are caught by the streaming rumination detector, `timeout_seconds` and n_ctx, never a short hard cap — and here none of the three fires:

- the rumination detector watches the **reasoning** channel; this is content and tool arguments,
- `output_reserve = 16384` is an input-side reserve, not an output cap, and `max_tokens` is deliberately unset on the coder (`cria.toml:99`, "don't set on the coder"),
- so generation runs to ~43,000 tokens and only the truncation guard catches the result, after the twelve minutes are spent.

**The fix is not a cap** — that is the footgun principle 6 exists to forbid, and the mid-write cut is exactly what `guard_truncation` was built for. The gap is that the *streaming* watcher does not watch this channel: cria is already reading the stream, already aborts on a reasoning runaway, and could abort on a content/arguments runaway on the same evidence. Next fix phase; one code state per cycle.

### The cell-15 re-run: 0%, and it does NOT validate the verifier fix

The superseded row was re-run under the new code state and scored **0 of 5**, killed at the 15-minute floor after 20 calls with `mvn compile failed` and no REVIEW.md written at all. So the matcher change is still unexercised — there is nothing to match.

**Checked first, because the reflex is self-suspicion: none of the six fixes threw.** The session's 418 events contain zero entries at `error` or `warn` level, and the run never reached a gate, a steer or a satisfaction check.

**What it exposes is the floor, not the fix.** This cell is bimodal. The 80% run compiled inside the first fifteen minutes, cleared the milestone and got seventy minutes; this one did not, and died at fifteen with 20 calls on a model that generates at ~40 tok/s. Same task, same prompt revision, same code state, 80 → 0. That is not a regression to diagnose, it is the variance the floor converts into a cliff, and it belongs in the record next to every other cell floored at fifteen minutes this cycle.

The row stands at 0% and cycle 3 re-runs the cell along with the other 23.

### FIX PHASE — cycle 2, what landed

| # | fix | commit shape | test |
|---:|---|---|---|
| 1 | **The periodic completion check may NAME a missing deliverable to the coder** — the operator's ruling. Bounded: empty reason stays silent, a parked steer is never stomped, and the same reason never goes twice running | `cria/loop.py`, `prompts/periodic_gap.txt` | 7 new, 4 fail before |
| 2 | **The install route names the binary that was actually found** — `_resolved_tool` owns "is it there" and "what is it called" together; every route fills a `{{TOOL}}` token. Live on this box the ruby answer is now `bundle3.2 install --path vendor/bundle` | `cria/dirguard.py`, `prompts/install_remedy.txt` | 6 new, 3 fail before |
| 3 | **Never say "no line could be parsed" while quoting the line** — the two readers of one gate report were exclusive and now surface together; it also stops a real failing check being dropped whenever another probe happened to parse | `cria/loop.py`, `prompts/ground_truth_failed_also.txt` | 6 new, 1 fails before |
| 4 | **`review_written` accepts a markdown table** — the window was four non-word characters and a table cell needs five. Verifier defect; cell 15's row marked `superseded` and re-run | `suite/tasks/feed-pipeline-java/verify.py` | 4 new, 1 fails before |
| 5 | **Fold the install tree cria itself prescribed** — 64% of the body that died was `vendor/bundle` lines; without them it fits with room to spare. Keyed on a relative path so `vendor` stays listable and a committed `vendor/mycompany/` is still enumerated. Folded, not dropped, so the completeness clause survives | `cria/groundtruth.py` | 9 new + an anti-drift pin reading `install_remedy.txt` |
| 6 | **The completion judge is no longer handed the coder's tool vocabulary** — judges get names without parameters (the steer author keeps them); `satisfaction.txt` gains principle 8's measured fence and an answer for the case it cannot settle; `proposed_fix` asks what must become true, not how | `cria/loop.py`, `prompts/satisfaction.txt` | 9 new, 8 fail before |

Every one carries a fails-before/passes-after test proven against the pre-change file, `python3 -m pytest` green at 3502, and `cria.service` restarted onto it.

### SURFACED, NOT CHANGED — the litter sweep is defending against the opposite incident

I built the tier-2 sweep fix (bound the sweep to `BUILD_ARTIFACT_DIRS`, so `orders.db` ×12 and `Cargo.lock` ×5 stop being deleted), it passed, and then I read the test file it broke. `tests/test_gate_leaves_no_litter.py`'s own docstring:

> *"Measured on the six-language battery: a leftover `orders.db` from one gate run made the next run's schema assertions fail, and the coder was sent to debug cria's own litter."*

**Sweeping `orders.db` is a deliberate fix for a measured incident, in the opposite direction.** The gate runs the repo's tests in the live workspace; those tests write a database; leaving it makes the NEXT gate assert against stale state and cria then reports, under its strongest header, a failure it manufactured itself.

**Reverted, per the fix-phase rule** — an item that undoes a deliberate earlier decision gets surfaced and stopped on, not landed.

Both findings are real and they are about the same file:

| | claim | evidence |
|---|---|---|
| the earlier decision | leaving it makes cria manufacture the next gate's failure | six-language battery, recorded in the test's docstring |
| cycle 2's walk | deleting it removes what the model is testing against | 18 non-build paths, 9 sessions; `orders.db` ×12, `Cargo.lock` ×5 |

And the walk **refuted its own cost**: `verify.py` stashes any existing `orders.db` and installs its own, so the deletion cost the model's mid-run testing and no checks. The earlier incident's cost was a coder sent to debug cria's litter.

**What would resolve it rather than pick a side:** the gate should not run the project's tests *in the live workspace* at all — the collision only exists because cria's ground truth and the coder's working tree are the same directory. That is a larger change than a fix phase should smuggle in, and it is the operator's call. `Cargo.lock` is separable and safe on its own: nothing writes it but cargo, and no incident says it must go.

### The ranked list — cycle 2

Ranked on cells cost, whether it broke working code, whether it is a false fact, how many models and languages it reached, and how cheap the real fix is.

| # | tier | finding | cost | fix at |
|---:|---|---|---|---|
| 1 | 1 | **The completion judge is handed the coder's tool menu and told to author an executable command.** `satisfaction.txt:22` requires *"one executable next step… include the exact command when a run is required"*, and `_coder_tools_summary` pastes `exec_command` with all nine of its parameter names into the judge's context. The judge's hallucinated calls copy those exact parameter names. Its fence says "never write code" but not the doctrine's measured pair — *"You have NO tools"* and *"Do not think about HOW any of this would be built"*. 43 of 66 judge turns on one cell ended saying nothing at all, and fail-closed read every silence as "not done" | 45 min and ~300 calls on one cell; 12 false not-dones | `cria/prompts/satisfaction.txt` + the `coder_tools` thread |
| 2 | 1 | **cria's install advice creates a tree, then reads it back into its own prompt.** The census cria appends to a refusal was **64% `vendor/bundle` lines** — 42,140 of 65,801 tokens. Without them the body is 23,661 against a 45,056 budget and fits easily | the 259 KB body, six 400s, −60 on cell 2 | the install-denial site records the path it prescribed |
| 3 | 1 | **The install remedy names a binary this box does not have.** `_tool_present` finds `bundle3.2` and the name is discarded before it reaches the sentence, which still says `bundle` | −60 on cell 3, ~half a coder budget | `dirguard._local_install_advice` renders the discovered name |
| 4 | 1 | **A steer stated "no code changes have been made to address performance"** while cria's own prompt showed the thread pool, the concurrent map and the O(n) dedup — and the model then replaced header-keyed column lookup with hardcoded indices | broke working code on the cycle's best cell | the steer author's evidence bundle |
| 5 | 1 | **"a specific line could not be parsed from the output", printed beneath the parsed line.** 5+ occurrences across two runs. `probeparse.split_diag` was fixed for exactly this and its comment records the incident; the **steer-selection path still disagrees with the checks block** | the Java column, two cycles | the selection path, not the parser |
| 6 | 2 | **cria refused a whole-file read 56× saying it "would be truncated" — while its own judge read the same file whole, untruncated, three times in the same run.** A bound cria imposed, stated as a fact about the world | 8 calls reassembling a readable file | `READ_INLINE_MAX` claim wording |
| 7 | 2 | **The rumination guard names a trigger its own detector rejected.** All three aborts fired on raw length; the message says "hit N second-guessing phrases". Two of four aborts destroyed coherent in-progress file drafts | 2 lost drafts, 1 cell | `loop.py:7479` needs a third notice |
| 8 | 2 | **The critic's action log elides the call line and keeps the result**, so a successful fetch appears with no call that produced it — the critic then ruled the research step undone, twice, and 21% of one run's tool calls went to re-fetching one page | two Rust cells | the elision keeps call lines |
| 9 | 2 | **`exec-intent` invents a fresh success criterion each cycle.** Three wordings on byte-identical output gave YES, NO, NO; the strictest demanded a skipped-row breakdown from a feed with no bad rows | 7 false live-execution facts | pin the criterion per session |
| 10 | 2 | **Two owners for the checks preamble.** The one that fires ~30× is an inline f-string at `probegate.py:547` with no "a test YOU wrote is yours" carve-out; its sibling prompt file has it. Also a rule-22 violation | model reversed a correct fix | one owner |
| 11 | 2 | **`find=` answers "no match" about a document containing the term** when the query is regex-escaped — and cria primes that spelling itself | the ISO3166 answer, on the cell it killed | third re-read in `find_in` |
| 12 | 3 | `_doc_format` says "It is YAML" of an HTML page on one leading `Word:` line | noise | second signal or silence |
| 13 | 3 | cria has **no memory of what was green**. Its only cross-round state is a git-status digest with no filenames, so a check going from passing to failing is indistinguishable from one that always failed | the cell that regressed | a green-set per round |
| 14 | 3 | `unsupported call: task_complete` for a tool cria advertises in the same turn | 7 turns | honour or stop listing |

**Two deliberate decisions need the operator, not a fix.** cria substitutes its own `web_fetch` when the search supervisor returns a URL (`loop.py:477-478`, documented) — it collides with principle 2's corollary and put a phantom 404 in the durable ledger for 86 calls. And `_periodic_satisfaction` may end a session but never steer it, which is why four correct verdicts naming a missing method never reached the coder.

**One verifier defect**, worth a full 20 points: `review_written` misses a markdown table by one character. Fix, then supersede and re-run cell 15.

### The walk phase Started **2026-08-15 20:5x**. Nine runs prepared with `suite/walk.py` — 297 chunk
files, 17.1 MB — and **eight agents reading them line by line**, per `docs/walk-prompt.md`. Findings land in `docs/audits/cycle-2-walk.md`, one `## <run_id>` per run.

| agent | run | why it was picked |
|---|---|---|
| 1 | `shipping-rates-rb × qwen35` | −60, cria killed it with a 259 KB body |
| 2 | `shipping-rates-rb × ternary-bonsai` | −60, ten refusals naming a binary that does not exist |
| 3–4 | `feed-pipeline-java × qwen35` (head / tail, 153 chunks) | 100% but 45 minutes and ~300 calls wasted after finishing |
| 5 | `cart-billing-go × nemotron-elastic` | 0%, and the spill-to-`.txt` fix needs checking for new harm |
| 6 | `orders-api-py × ternary-bonsai` | the score went BACKWARDS mid-run; find the regression |
| 7 | the three 15-minute floored cells | one trivial compile error each, cria surfaced all three |
| 8 | `feed-pipeline-java × nemotron-elastic` | four rumination aborts ate 7 of 17 minutes |

The run phase ran The run phase ran **2026-08-15 09:02 → 20:31**, all 24 cells, 11.3 hours of wall clock and 2,239 calls. Driver `python3 suite/cycle_run.py` · log `docs/audits/cycle-run.log`.

### Cycle 2 result

| | cycle 1 | cycle 2 |
|---|---:|---:|
| checks passed / attempted | — | **66 / 108 = 61.1%** |
| mean of the 24 cell percentages | 53.8% | **62.1%** |
| cells at 100% | 9 | **9** |

**Read that honestly.** The mean is up 8.3 points and the number of perfect cells did not move. Nine and nine — but not the same nine, and the composition is better: `feed-pipeline-java`, which had never scored above 40% in the campaign's history, produced a 100% and an 80%; `rust-toml-cli × qwen35` and both Python leaders held; and the two Ruby cells cria broke are the reason the count did not rise.

By language:

| task | cells | mean | vs cycle 1 |
|---|---|---:|---|
| `orders-api-py` | 100, 100, 50, 75 | **81%** | up from 75% |
| `handles-cli-node` | 75, 100, 100, 50 | **81%** | up from 75% |
| `cart-billing-go` | 80, 100, 100, 0 | 70% | down from 75% |
| `rust-toml-cli` | 100, 100, 0, 0 | 50% | flat |
| `shipping-rates-rb` | 80, 40, 20, 40 | **45%** | **down from 50%** |
| `feed-pipeline-java` | 0, 100, 80, 0 | **45%** | **up from 10%** |

And by model, from the grid — `qwen35` is now green at 89% with five of six languages perfect:

| model | total | Δ |
|---|---:|---:|
| qwen35 | **89%** | +7 |
| gemma4 | 70% | +7 |
| ternary-bonsai | 59% | +4 |
| nemotron-elastic | 26% | +15 |

**The two things standing between this cycle and a much higher number are both cria's**, both in the Ruby column, both traced to the line, and both listed below: the context floor that cannot fit a single oversized message (cell 2, −60) and the install refusal naming a binary this box does not have (cell 3, −60). A third, the `review_written` matcher, is a verifier defect worth a full 20 points on cell 15.

### Environment, verified clean 2026-08-15 (before cell 1)

Thirteen cria changes landed after cycle 1's run and none of them had been measured. That is what this run measures. `cria.service` was restarted onto the current code state immediately before the first cell; **nothing under `cria/` changes until the run phase ends.**

### Environment, verified clean 2026-08-15 (before cell 1)

- **`user_install_listing()` — no Ruby gems at all.** The `countries` / `unaccent` leak that inflated four Ruby rows is still gone. The listing carries only the pre-existing maven/cargo/go/npm/py baseline, and the tripwire is a per-run *diff* (`run.py:354` before, `run.py:455` after), so a standing baseline cannot inflate a score — only something installed *during* a cell can.
- **`git status --short suite/tasks` — clean.** No verifier is writing into the repo.

### Cells — cycle 2

| # | task | model | score | Δ pts | min | calls | what happened |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | shipping-rates-rb | gemma4 | **80%** | **+60** | 32 | 101 | four of five green, and the dead-gem chain that sank this cell last cycle is gone — tests, hidden contract, express zone and the full 8/8 rate table all pass. The one loss is `country_zone_mapping`, and the cause is not a dependency problem: **the model never wrote `Shipping.zone_for` at all.** `lib/shipping/rates.rb` is the workspace's only source file and it contains no `zone_for` and no mention of `countries`/`ISO3166`, while `Gemfile` declares `gem "countries"` and `vendor/bundle` holds the installed gem. It set the dependency up and never used it. Deliverable 4 of 5, simply not attempted |
| 2 | shipping-rates-rb | qwen35 | **40%** | **−60** | 9 | 88 | **cria killed this cell.** The run ended on six consecutive HTTP 400s against a 259 KB briefing body, 67% of which is the `vendor/bundle` gem tree. Two checks were still red when it died, from a model defect reproduced cold: `Country[...]` inside `module Shipping` resolves to `Shipping::Country` → `NameError`, and the fix (`ISO3166::Country`) was in the doc cria had just size-gated at 9,645 bytes against a 9,000 bound. See below |
| 3 | shipping-rates-rb | ternary-bonsai | **20%** | **−60** | 31 | 56 | **cria sent this cell into a wall it built.** Ten `writeproxy.blocked_external` refusals, each one answering "run `bundle install --path vendor/bundle`" — and **there is no `bundle` on this box**. Calls 0037–0057, roughly half the coder budget and the last twenty minutes, went on install attempts that could not succeed. Only the untouched seed tests pass; the README still names one zone and nothing was built. Killed at the 30-minute floor. See below |
| 4 | shipping-rates-rb | nemotron-elastic | **40%** | **+40** | 45 | 191 | up from zero, and the most informative cell of the cycle so far. The completion judge ran eleven times, named the missing `zone_for` **four times with a written fix**, and the coder was told none of it — then flipped to `satisfied: true` on a claim that is false on disk. Ends 2/5 with deliverable 4 absent and `PER_KILO` missing its `express` entry. See below |
| 5 | cart-billing-go | gemma4 | **80%** | **−20** | 14 | 32 | four of five green — the rounding fix, `discounts.json` with the fallback, the stderr log line, and a real third-party decimal module imported by non-test source. The one loss is **the seeded `TestSubtotal` deleted from `cart_test.go`**. Not a cria fault, and not laziness either: see the measurement below |
| 6 | cart-billing-go | qwen35 | **100%** | 0 | 6 | 58 | all five green in under six minutes. Held from last cycle. One wheel-spin probe, one gate, three `task_complete` claims each verified |
| 7 | cart-billing-go | ternary-bonsai | **100%** | 0 | 34 | 75 | all five green, held from last cycle. Ten `writeproxy.blocked_external` refusals here too — and unlike the Ruby column it cost nothing, because `go get` records the dependency in `go.mod` project-locally and never needs a machine-wide install. The same guard, the same count, two different outcomes: the Ruby remedy is the broken half |
| 8 | cart-billing-go | nemotron-elastic | 0% | 0 | 31 | 94 | flat at zero, **but the cria fault that caused last cycle's zero is fixed and verified.** Last cycle `go build ./...` compiled cria's own spilled fetch, saved as `…decimal.go`. This cycle every file in `tmp/read-only/` ends `.txt` — 8 of 8, zero non-`.txt` — and the build never sees them. The new cause is the model's: `cart_test.go:46` calls `got.String()` while `cart.go` still returns `float64`, so it rewrote the test to a decimal API and never changed the implementation. `decimal_money_library` says it plainly — declared in `go.mod`, "imported by non-test source: none" |
| 9 | orders-api-py | gemma4 | **100%** | 0 | 38 | 133 | all four green, held. The route returns alice's items and a total, the migration keeps old rows readable and adds both the status column and the customer index, the integration tests make real HTTP calls, and the injection is closed with the table intact. Two wheel-spin diagnoses and twelve gate sweeps along the way |
| 10 | orders-api-py | qwen35 | **100%** | **+50** | 10 | 78 | all four green in under ten minutes. The migration defect that halved this cell last cycle — `CREATE TABLE IF NOT EXISTS` as a no-op against the pre-migration database, then `UPDATE orders SET status` on a column never added — is gone; old rows read, the status column and customer index are both there |
| 11 | orders-api-py | ternary-bonsai | 50% | 0 | 46 | 71 | flat, and it **went backwards while running**: 3 of 4 at the 15-minute mark, 3 at 30, **2 at 45**. The route and the migration both pass; the integration suite ends 2 failed and the injection probe cannot get a normal lookup through. Along the way cria's gate deleted the task's own `orders.db` — see below, and it did **not** cost the score |
| 12 | orders-api-py | nemotron-elastic | **75%** | **+25** | 61 | 134 | three of four, and the closest this model has come. Held 3/4 at every milestone — 15, 30, 45, 60 — and ran out the full hour rather than being floored early, which is new. The route, the migration and the injection fix all pass. **One stray file costs the fourth**: the model wrote a scratch `test_init.py` at the repo root at call 0117 doing `import db` (the module is `orders.db`), and pytest aborts the whole suite on the collection error before running a single test. **Not cria's** — cria put `1 error during collection` and `ERROR test_init` into **15 consecutive prompts** from call 0121 to the kill, and the model had fourteen calls and 17 rumination aborts in that window and never deleted the file |
| 13 | feed-pipeline-java | gemma4 | 0% | 0 | 16 | 35 | flat at zero, and **one typo is the whole cell**: `mvn compile` fails on a single error, `cannot find symbol: class CSVRecordRecord` at `Importer.java:96` — the model wrote the word twice. Nothing else is wrong with the build. All five checks fail behind it. **Not cria's**: `CSVRecordRecord` appears in **10 request bodies**, `cannot find symbol` in 9, `BUILD FAILURE` in 8 — the model was told plainly and repeatedly. Killed at the 15-minute floor with 29 coder calls, three of which cria refused as malformed (`write_missing_arg` ×2, `edit_missing_arg` ×1) — 10% of the budget, on a cell whose budget was the binding constraint |
| 14 | feed-pipeline-java | qwen35 | **100%** | **+60** | 76 | 492 | **the first 100% ever scored on `feed-pipeline-java`**, the campaign's worst column. All five: messy feed handled with skipped rows reported, **70.3× against a 4.0× bar with the totals matching** (29.9× and mismatched totals last cycle), 4 worker threads with one distinct result across 8 runs, `csv_library` importing the quoted-comma row at 25.00, and **`review_written` at 828 words with 13 located findings** — a check missed 4 of 4 last cycle. And it was **5/5 at the 30-minute milestone and ran for 45 more minutes**; see below |
| 15 | feed-pipeline-java | ternary-bonsai | **80%** | **+80** | 70 | 82 | biggest single gain of the cycle, from a cell that **never compiled** last cycle. The build works, 33.4× against a 4.0× bar with matching totals, 4 worker threads, quoted-comma row imported. `review_written` is scored 0 and **the model earned it** — this is a verifier defect, proven below, and the row is a re-run candidate for the fix phase |
| 16 | feed-pipeline-java | nemotron-elastic | 0% | 0 | 18 | 22 | flat at zero. **CORRECTED by the walk: nothing was written at all.** The archived workspace is one commit — `2ae987e seed` — with a clean `git status` and `pom.xml` still 980 bytes. My earlier row said "it compiles now… it just optimised nothing"; what compiles is the *seed*, and the 1.0× speed, 0 threads, absent REVIEW.md and undeclared dependency are the seed being scored. Five `write_file` calls were refused as malformed XML and the model never worked out why. Killed at the 15-minute floor after **22 calls**. It ran at its normal 116–128 tok/s; what ate the budget was six-to-twelve-thousand-token replies plus four rumination aborts, 16.4 of 17.5 minutes inside the model. See the correction below |
| 17 | handles-cli-node | gemma4 | 75% | 0 | 16 | 36 | three of four, held. The CLI prints address, holder and count, `--json` and `--help` both work, a bad handle exits non-zero, `request` is gone from both `package.json` and the source, and the Dockerfile is right. **Same single loss as last cycle**: `tests_incl_live` — its tests pass with the network blocked, so they are mocked. Not a cria fault and not an impossible check: two of the four models passed it last cycle. This model chose to mock, twice running |
| 18 | handles-cli-node | qwen35 | **100%** | 0 | 6 | 59 | all four green in six minutes, live test included — `npm test` passes with the network and fails without, which is exactly the property the check asks for. Held from last cycle. **And the completion machinery worked**: one `task_complete`, one `done_critic`, one gate, session over. The same subsystem that burned 45 minutes and 118 calls on cell 14 closed this one in a single exchange — so the defect there is not "the judge is slow", it is the silent-turn path |
| 19 | handles-cli-node | ternary-bonsai | **100%** | 0 | 36 | 66 | all four green, live test included, held from last cycle. Climbed the whole way — 2/4 at fifteen minutes, 3/4 at thirty, 4/4 at the end — which is the shape a milestone floor is meant to allow and did |
| 20 | handles-cli-node | nemotron-elastic | 50% | **+25** | 18 | 74 | up from 25%. The live test now passes with the network and fails without, and the Dockerfile is right. Both losses are **one line**: `lookup.js:44` assigns to a `const`, so `node lookup.js goose` dies with `TypeError: Assignment to constant variable` — which fails `cli_behaviour` outright and fails `request_removed`'s "runs with no node_modules" for the same reason (there are no dependencies at all). **Not cria's, verified**: cria ran the program seven times, reported `it exited 1` to the coder in 7 prompts and to the judge in 7 more, and the completion critic refused 8 of 9 done-claims. The model saw the TypeError in its own command output and shipped it anyway |
| 21 | rust-toml-cli | gemma4 | **100%** | 0 | 16 | 64 | all four green, held — clean build, 3/3 dotted-key lookups, the missing-key error contract, tests and README |
| 22 | rust-toml-cli | qwen35 | **100%** | 0 | 17 | 129 | all four green, held. Heavily assisted again — 4 periodic gates, 3 completion probes, 6 `task_complete` claims each verified, one gate red-advance, one poisoned search refused — and landed |
| 23 | rust-toml-cli | ternary-bonsai | 0% | 0 | 16 | 25 | flat at zero, and again **one line**: `src/main.rs:54` calls `part.as_str()` on something already a `&str`, and `str::as_str` is unstable — `error[E0658]: use of unstable library feature`. Delete six characters and it builds. **cria's cycle-1 defect on this exact cell is fixed**: last cycle "two gates ran and not one `⟦ctx:checks⟧` block reached the model"; this cycle three `⟦ctx:checks⟧` blocks did, `could not compile` reached it in 14 prompts and `error[E…]` in 12. Killed at the 15-minute floor with 25 calls |
| 24 | rust-toml-cli | nemotron-elastic | 0% | 0 | 16 | 44 | flat at zero. `error[E0106]: missing lifetime specifier`, two errors, nothing builds. The number that stands out is **`editrecovery.escalated: 11`** — the only cell in the whole cycle to fire it, eleven times in 44 calls. A quarter of its turns went on edits that would not apply |

### CANDIDATE — a `confirmed` run of the TEST suite followed a failing run of the PROGRAM

Filed as a candidate, not a finding: the event sequence is suggestive and the critic's reasoning has not been read. Cell 20, verbatim from the log:

```
02:23:04  exec_check  not_observed  node lookup.js goose   exit 1
02:23:23  done_critic satisfied=false
02:24:03  exec_check  CONFIRMED     npm run test           exit 0
02:24:24  done_critic satisfied=TRUE      ← session ends
```

`exec-intent` picks the command to run per completion attempt. Seven times it picked `node lookup.js goose` — the deliverable — and four of those exited 1. The eighth time it picked the test suite, which passed, and the verdict `confirmed` is the one the design makes silent (#3: on a clean signal, say nothing). The critic then approved, with the last known state of the actual program being "it crashes".

The tests pass because the CLI's failure is in its argument parsing, which the tests do not exercise.

**What would settle it**: read the critic's evidence bundle at 02:24:24 and see whether the earlier `not_observed` markers were still in it, or whether the `confirmed` displaced them. If a `confirmed` on any command can erase a known-failing run of the deliverable, that is a fail-open on ground truth cria already holds. If the markers were all present and the critic simply weighed them, it is a judgement call and not a defect. **Not concluded either way.**

### CORRECTED — cell 16 was not slow. I read the wrong session.

**What was published here first, and is wrong:** that cell 16 ran at 34–52 tok/s against its model's 108–126 average, prefill-dominated, and that a busy GPU might explain it.

**The error.** I selected the session by matching the prefix `01a007c` in the log. Cell 16's session is `01a00809-e68a-7eb1-bdcb-85cda527521c`. The prefix matched `01a007c9-4389-7632-8085-8a020ad7f51e`, which is **cell 15, ternary-bonsai** — and 34–52 tok/s is simply that model's ordinary speed (its row says `avg_tok_s` 40.6). I reported one model's normal throughput as another model's slowdown. Rule 23b, at the level of picking the file: a prefix is not an identifier, and the row carries the exact `capture_dir`.

**What cell 16 actually did**, from its own session:

| | |
|---|---|
| `tok_per_s` across its 23 calls | **116–128** — normal, no slowdown at all |
| upstream time inside a 17.5-minute wall | **16.4 minutes — 94% of the cell** |
| context growth | 9,441 → 14,332 tokens, small and never a factor |

The time went into **enormous single generations**, not prefill and not the box:

```
00:50:14   6,498 tokens   55.1s
00:51:11   6,570 tokens   55.4s
00:57:31  12,636 tokens  109.1s
00:59:56   9,448 tokens   80.9s
01:04:03  12,214 tokens  104.8s
```

plus **four aborted calls** — `tokens=None`, totals of 48.6 s, 121.5 s, 126.0 s and 125.8 s — which are the run's four `rumination.abort` events. Roughly **seven minutes of a 17.5-minute budget spent inside runaway generations before the guard cut them**, on a model fast enough to have done the work.

**The finding that survives, restated honestly.** The rumination guard is catching real runaways — four of them, correctly — but it is catching them one to two minutes in, and on a cell whose whole budget is fifteen minutes that is the difference between 22 calls and a working build. That is worth ranking on its own evidence, and it has nothing to do with the GPU.

**What does NOT survive.** No slowdown was observed and none should be inferred. GPU state is still recorded nowhere, and sampling it per milestone is still cheap and still worth doing — the operator started a 3080-hungry app mid-cycle on 08-15 and nothing in the record would have shown it. But that is a **precaution against a hazard**, not a diagnosis of anything measured, and it must not be justified by this cell.

### VERIFIER DEFECT — `review_written` misses a markdown table by one character

Not cria's, and it cost a real check. `feed-pipeline-java`'s fourth deliverable asks for a review naming a file and a line for every issue. Cell 15 wrote one — 729 words, findings in a proper `| File | Line(s) | Before | After |` table:

```
| `src/main/java/pipeline/Importer.java` | ~45–50 | `knownSkus()` used `ArrayList.contains()` … |
| `src/main/java/pipeline/Importer.java` | ~30–45 | Shared mutable state: `static Map…` … |
```

Scored **0 located findings**.

`verify.py:215` looks for the file and the line near each other:

```python
r"[\w/]+\.java\W{0,4}\d+"        # Importer.java:31 · `Importer.java` (31) · .java, 31
```

In a table cell the gap between `.java` and the line number is `` ` | ~`` — **five** non-word characters. The pattern allows four. Measured directly:

| `\W{0,N}` | located findings |
|---|---:|
| 4 (shipped) | **0** |
| 5 | **13** |
| 8 | 13 |

Off by one, and the review has thirteen properly located findings behind it.

**Scope, checked rather than assumed** — every `REVIEW.md` on disk, under the shipped pattern and a widened one:

| run | words | now | widened |
|---|---:|---:|---:|
| gemma4 (c1) | 267 | 3 | 3 |
| nemotron-elastic (c1) | 419 | 0 | **0** — genuinely unlocated, correctly scored |
| qwen35 (c1) | 1162 | 21 | 21 |
| qwen35 (c2, cell 14) | 828 | 13 | 13 |
| **ternary-bonsai (c2, cell 15)** | 729 | **0** | **13** |

**Exactly one row is misjudged.** Cell 15 is 80% and should be 100%.

**This is not making the task easier to pass.** The property the task names — a file and a line for every issue — is satisfied. The matcher fails on a *presentation format the task never forbade*, and the verifier's own comment at `verify.py:213` names this exact failure class: *"a correctly located finding scored as unlocated because of how the reviewer punctuated it… assert the property the task names, nothing adjacent."* It is also the shape the operator has flagged twice — a matcher keyed to one way of writing something is inert on every other way.

**Not fixed now, deliberately.** A verifier change invalidates every row scored against it. It lands in the fix phase; cell 15's row is then marked `superseded` and re-run.

### RANK 1 — the completion judge is not judging. It is going silent, and silence means "not done"

Cell 14 finished the work at the 30-minute milestone and ran for **45 more minutes and ~300 more calls** before cria would agree. Read end to end, the reason is not that the judge was wrong twelve times. It is that **the judge never answered at all**, and the fail-closed rule turns every silence into a "not done".

**The trace, from the structured events:**

```
22:34:53  satisfaction_check  drive= 80  satisfied=false
22:38:38  satisfaction_check  drive=100  satisfied=false
22:42:50  satisfaction_check  drive=120  satisfied=false
   … 160, 180, 200, 220, 240, 260, 280, 300, 320 — all satisfied=false …
23:35:04  satisfaction_check  drive=340  satisfied=TRUE   ← 45 minutes later
23:35:50  loop.gate  blocked=false
                                            budget-killed one minute later
```

Three `task_complete` claims from the model in between (22:39, 23:26, 23:28), each answered by `done_critic satisfied=false`.

**What the replies actually contain.** 66 satisfaction-phase responses:

| | count |
|---|---:|
| empty content | **58** |
| containing the word `satisfied` at all | **4** |
| `finish_reason: tool_calls` (the judge inspecting — legitimate, no verdict expected yet) | 23 |
| **`finish_reason: stop`, no tool calls, empty content** | **43** |

Forty-three turns where the judge stopped having said nothing. Of those, **40 carry reasoning**, and the reasoning shows what happened — verbatim from `0091-satisfaction.response.json`:

```
Now let me run the tests and verify the importer works correctly. I'll also check if REVIEW.md exists.

<tool_call>
<function=exec_command>
<parameter=cmd>
ls -la /tmp/suite-feed-pipeline-java_qwen35_codex_poff_1786832410-bwezzbyl/
</parameter>
```

The judge is emitting its tool call as **literal text inside the reasoning channel**, in a dialect cria did not lift into structured `tool_calls` — and it is asking for `exec_command`, which a read-only judge does not hold (`massage.reasoning_call_off_menu` fired 10 times). So the turn ends with no content, no tool call, and no verdict.

**A → B → C:**

- **A** — the judge wants a tool, writes the call as prose in its thinking, and asks for one that is off its own menu.
- **B** — cria gets `finish_reason: stop`, empty content, no tool calls. `judge_satisfaction` has no verdict to parse, so #13 applies: an undecidable judge means NOT done.
- **C** — twelve consecutive "not done" verdicts on a workspace that was already scoring 5 of 5, and a finished session cannot end.

**Why the existing recoveries did not save it.** They fired hard — `massage.reasoning_call_recovered` 248 times in this run — and `verdict_from_reasoning` is wired at this exact site. But `verdict_from_reasoning` recovers **only a NOT-satisfied ruling, never an approval**, and that one-direction guarantee is deliberate and structural: a recovered approval could end a session on unfinished work. So when a judge's answer is lost, the only thing recoverable from it is "keep working". A completed task is *unrecognisable through a lost verdict, by design.*

**This is the exact mirror of cell 4** and the pair is the argument. Cell 4: the judge was RIGHT four times, named the missing method, and was forbidden from telling the coder. Cell 14: the judge was SILENT twelve times, and silence is the only thing that could have ended a finished run. The same subsystem, failing in opposite directions, in one cycle.

**Cost here:** ~45 minutes and roughly 300 of 492 calls on a cell that was already perfect, plus 118 satisfaction-phase model calls — **24% of the whole run** — most of them producing nothing. The score survived only because the work was already done.

**Fix belongs at B.** A judge turn that ends with no content, no tool call and reasoning that contains an unlifted or off-menu tool call is not an undecidable verdict — it is a *malformed turn*, and cria can tell the two apart from the authoritative event (`finish_reason`, `tool_calls`, `reasoning_content`). Fail-closed is right for a judge that considered and could not decide; it is the wrong reading of a judge that never got to speak. This does not weaken #13: nothing here proposes recovering an approval from reasoning.

### TIER 2 — "my probe created it" is not the same as "it is mine to delete"

Cycle 1 filed this as "the litter sweep deletes untracked build output — wrong as *leave the workspace as I found it*". Read properly, the mechanism is more careful than that and the problem is more interesting.

`probegate.sweep_litter` does not delete untracked files. It deletes the **difference** in git's `??` set across the gate's own probe run — "the untracked files the gate's OWN probes created" — and it is bounded three ways (git must call it untracked, it must resolve inside the workspace, any failure is skipped). Nothing guesses.

**The assumption underneath it is the bug.** cria's probe *is the project's own build and test command* (#10 — verify by doing). So anything those commands legitimately produce is attributed to cria's probe and removed.

Counted across every log on disk, keyed on the emitted event:

| | |
|---|---:|
| gate sweeps logged | 121 |
| non-build paths swept | **18, across 9 sessions** |

and the paths themselves say it:

| path | times |
|---|---:|
| `orders.db` — the Python task's live database | **12** |
| `Cargo.lock` — the Rust project's lockfile | **5** |
| `target/` — genuinely build output | 1 |

*(`sample` is a sample; 18 is a floor, not a count.)*

**On cell 11, verified in the log:** `20:25:53`, session `01a00711`, four paths swept, `orders.db` among them, ten minutes into the run. `git status` in the archived workspace confirms `?? orders.db` — the seed does not ship it, `orders/db.py` creates it, and the gate's own test run is what made it appear.

**And it did not cost the score — checked, because the chain was too neat to trust.** `verify.py::Service.__enter__` stashes any existing `orders.db` and installs its own prepared database at that exact path (lines 79–81), *because* the seed reads `orders.db` relative to cwd. So the final checks never see the model's database. What the deletion cost is the model's own testing, mid-run, against a file that vanished under it.

**Fix at A, and it reverts nothing.** The sweep's question should not be "did this appear while my probe ran" but "did *cria's own composed command* write this". cria knows which commands it composed and which are the project's — the gate plan holds both. A probe that runs `cargo test` produces cargo's artifacts, and those are the project's, not cria's.

**Ranked 2, not 1**, because no cell loss is demonstrated: the Python verifier is immune by construction and cargo regenerates its lockfile. It is on the list because deleting a file the coder is actively using is a footgun whether or not this quarter's verifier happens to be insulated from it — and because `Cargo.lock` deletion changes which crate versions resolve, in a column where two of four models never built.

### REFUTED — the 305 KB of raw HTML in the workspace is not cria's doing

Four of the 76 spilled files across every archived workspace are raw `<!DOCTYPE html>` — 305 KB, 301 KB, 51 KB, 50 KB, 708 KB between them, all on `nemotron-elastic`, across both Go and Ruby and both cycles. One of them is named `…_README.md.txt` and is a GitHub error page. It looked like cria's HTML-to-text extraction failing and falling back to raw markup, which would be a fallback (#4) producing a mislabelled file (#5b).

It is not. Every one of them was requested with `"raw": true` **by the model**:

```
{"url":"https://github.com/guyp/decimal/blob/main/README.md","raw":true}
{"url":"https://rubygems.org/gems/countries","raw":true}
```

`webfetch.py:151` honours that flag exactly as its docstring says it must — "the caller wants the literal source… `raw` is about the bytes the model reads." Flattening it would be cria overriding an explicit instruction. No fault, no fix.

What the same read did turn up, deduplicated by `tool_call` id rather than counted across prompt copies: cell 4 issued **10 distinct fetches, three of them the same `rubygems.org/gems/countries` URL with `raw: true`** — 51 KB of markup, three times. The durable fetch ledger exists to tell the coder it already has that. Worth a look in the walk; not ranked on three occurrences.

*(Method note: the first count of these fetches said 97. That was the same call re-counted once per prompt it appeared in — the identical mistake the truncation observer makes, made by hand, one subsection after writing it up. Dedupe by call id, always.)*

### MEASURED, NOT BUILT — models delete seeded tests, at 2%

Base-rated before proposing anything (#15), across every row in `results.jsonl` that has captures:

| | |
|---|---:|
| rows scanned | 368 |
| rows where a seeded test was deleted | **7 (1.9%)** |

Spread: two tasks (`cart-billing-go` ×4, `shipping-rates-rb` ×3), two languages, three models (`gemma4` ×5, `nemotron-elastic`, `ternary-bonsai`). So it is not one model's tic and not one language's, but it is thin.

**And four of the seven are the same test, for a reason that is not carelessness.** `cart-billing-go`'s seed has:

```go
func TestSubtotal(t *testing.T) {
    c := &Cart{Items: []Item{{"pen", 2.50, 4}, {"pad", 5.00, 1}}}
    if got := c.Subtotal(); got != 15.00 { … }
}
```

and the task says *"Stop using `float64` for money arithmetic… Keep the `Item` struct field types unchanged; convert values inside the cart."* A model that returns `decimal.Decimal` from `Subtotal()` makes `got != 15.00` stop compiling, and deleting the test is the shortest way out. Keeping `Subtotal() float64` and converting internally is available and is what the prompt intends — but the collision is designed in, and it is where four of the seven landed.

**Nothing built.** A guard here would be exactly the regression-only shape #2 sanctions ("never delete correct content" — removing a currently-passing test makes something already working worse), and equally it would risk blocking a legitimate deletion, which #2 forbids just as firmly. At 1.9% the bar to ADD is not met. Recorded with the number so the next cycle can re-rank it rather than re-discover it.

### RANK 1 — the judge knew, four times, and the coder was never told

This is the c1-13 question with fresh bytes behind it, and it is no longer abstract. One cell, `shipping-rates-rb × nemotron-elastic`, eleven completion judgements, read in full from the captured responses.

**Four correct NOT-satisfied verdicts, each naming the missing deliverable by name:**

| call | verdict | what it said |
|---|---|---|
| 0041 | `satisfied: false` | "…the **`zone_for` method for two-letter country codes**, EU-membership detection via a third-party gem, and the new tests for these features have not been implemented yet" — with a `proposed_fix` spelling out the mapping |
| 0059 | `satisfied: false` | "the express service…, the **`Shipping.zone_for(code)` lookup**, the README rate table… are all missing or incomplete" |
| 0072 | `satisfied: false` | enumerated 1–5, item (2) is **`Shipping.zone_for(code)`… has not been implemented** |
| 0086 | `satisfied: false` | "the Counties gem used for EU detection has not been added…, so **`require "countries"` will fail**" |

Every one of those is specific, correct, actionable, and was **logged only**. `_periodic_satisfaction` may end a session, never steer it, so none of it reached the coder.

**Then the judge flipped, and it was wrong:**

> `0090` — `"satisfied": true`, "All five required changes are implemented: … **`Shipping.zone_for` using the third-party Countries gem for EU detection** …"

That is false on disk. Reproduced cold from the archived workspace:

```
-e:1:in `<main>': undefined method `zone_for' for Shipping:Module (NoMethodError)
```

`zone_for` does not exist. Neither does `PER_KILO["express"]`, which is why `express_zone` fails.

**The brake held, for the wrong reason.** `0091-satisfaction-confirm` returned `consistent: false` and stopped the false completion — the fail-closed design working. But its stated reason is itself a false fact about the task:

> "The claimed completion mentions adding tests and a README rate table, **which are not listed as required changes in the task**."

They are listed. "Add tests for it" is part of item 2 and "Add a README rate table" is item 3 of the five numbered changes. The right answer was reached on a wrong premise.

**So the mechanism failed in both directions in one run.** It computed the truth four times and threw it away; it then asserted the opposite and was caught by a check that misread the task. What survived is a cell that ends at 2 of 5 with the judge having known the answer since call 0041.

**This is the ruling the operator still owes.** The c1-13 note asked whether a NOT-satisfied verdict naming a *specific missing deliverable* is still "judgment" in the sense the no-steer rule meant. Four verdicts here name a Ruby method by name and carry a written fix. The timer objection — "steering off a clock is noise on a clock" — does not obviously cover a verdict whose content is a named, checkable absence.

**Not changed. Not proposed as a change.** Recorded with the bytes so the ruling can be made on evidence rather than on the shape of the rule.

### RANK 1 — cria's refusal prescribes a command that does not exist on this machine

The fix for this was written, its incident recorded in two places, and it corrected the half that chooses the route without ever reaching the half that writes the sentence.

**Verified cold, just now:**

```
$ which bundle      → nothing
$ ls /usr/bin/bundle*  → /usr/bin/bundle3.2   /usr/bin/bundler3.2
```

**What the model was told, ten times, verbatim from the captured tool result:**

> `⟦ctx:denied⟧ Installing into the shared system or user environment is not permitted here — an install must land inside the project directory (…), and this one would not. Install it into the project instead: add the gem to a `Gemfile` and run `bundle install --path vendor/bundle`.`

**Why it says that.** `dirguard._INSTALL_REMEDY` lists the ruby routes as `(("gem_bundler", ("bundle",)), ("gem_direct", ("gem",)))` and picks the first whose tools are all present. `_tool_present("bundle")` returns **True** — because `_versioned_variant` finds `bundle3.2`, which is exactly what it was built to do. So `gem_bundler` wins the selection, and `cria/prompts/install_remedy.txt:20` then emits the plain name:

```
gem_bundler = Install it into the project instead: add the gem to a `Gemfile` and run `bundle install --path vendor/bundle`.
```

The binary name is a hardcoded literal. Nothing interpolates the name that was actually found.

**The same file's header comment describes this exact bug, as history:**

> *A ROUTE CRIA HAS NOT VERIFIED IS A ROUTE CRIA IS GUESSING. The ruby row prescribed `bundle install --path vendor/bundle`, and `bundle` is not installed on the box the battery runs on. Two runs followed the advice into `bundle: command not found` and spent the rest of the run on transport rather than the task. cria refused a real command and answered with an imaginary one — the same class as stating a false fact, one step removed (#5b).*

`dirguard.py:209-217` carries the matching note for the discovery half. Both halves of the fix are written down; only one of them shipped. cria now *selects* a route on the strength of `bundle3.2` and *tells* the coder to run `bundle`.

**What it cost, from the captured commands.** Twenty-one distinct commands in the run; calls 0037–0057 are one continuous install fight — `gem install eu_countries --path vendor/bundle`, `--user-dir ~/.rubygems`, `--user-dir vendor/bundle` (not valid gem syntax), `which bundler`, `gem install bundler`, then curling the `.gem` and the `bundler` gem down by hand. The model never tried `bundle3.2`, because nothing ever told it that name. Score 20% against 80% last cycle.

**Fix at A.** The route's discovered binary must be the one the sentence names — `_versioned_variant` already holds it. This reverts no intent; it finishes one that is stated twice in comments and once in a prompt file header.

**Second-order, worth a line:** two of the model's commands carry a corrupted workspace path — `/tmp/suite-shipping-rb_…` with `rates` dropped, and `…_178681235-…` with a digit dropped. A 61-character generated path retyped by a 9B model into every single `cd`. Not cria's bug, but the suite chooses that path, and it is a cheap thing to shorten.

### RANK 1 — the context floor is not a fit guarantee, and it killed cell 2

Every link below is read from the captured body or the structured events, not inferred from the score. This is the third occurrence of the same shape and the second time it has killed a cell.

**What happened, in order, on `shipping-rates-rb × qwen35`:**

1. `16:43:37` — `route.compaction {"role": "compactor"}`. The harness asks for a briefing.
2. The body cria composes for it is **`n_messages: 2`** — one system prompt and **one 259,474-byte user message**. `rendered_chars: 263,147`, `msg_tokens: 67,647`, against `n_ctx: 49152`.
3. `contextfloor` runs. Six times, plus six refits. Every single one logs the same thing:

   ```
   context.floor  window=49152  msg_before=65761  msg_after=65761
                  turns_dropped=0  outputs_reduced=0  tools_compressed=0
   ```

   **It reduced nothing.** Not once, in twelve attempts.
4. `context.refit {"real": 100131, "est": 65762, "n_ctx": 49152}` — the server tells cria the body is really **100,131 tokens against a 49,152 window**, twice over. cria refits and sends the same 65,761 message tokens again.
5. `16:43:38 → 16:43:45` — **six `HTTP Error 400: Bad Request`**, one per attempt. The session ends.

**Why the floor could not act, which is the actual bug.** The floor has three levers and all three operate at message granularity: bound the tool schema, reduce oversized tool *outputs*, and drop whole oldest *turns*. This body has **zero tools, zero tool messages, and two messages** — one of which is the system prompt and the other of which is the payload. There is nothing for any lever to grip, so the floor completes, reports `over_budget`, changes nothing, and the caller sends anyway.

`docs/principles.md` #5 calls the floor "the **one** lossless-first place" that guarantees the body fits the window. On a single oversized message that guarantee does not hold, and nothing downstream notices — the only signal is a 400 from the server.

**What is in the 259 KB.** Measured on the captured body: **1,966 of 3,117 lines mention `vendor/` — 63% of lines, 175,174 bytes, 67% of the payload.** The top prefixes are `vendor/bundle/doc/countries-3.1.0/ri/lib/countries/data/…` (473 lines) and `vendor/bundle/gems/countries-3.1.0/lib/countries/data/…` (473 lines).

**The full chain, each link verified:**

| | link | evidence |
|---|---|---|
| A | cria's install advice prescribes `--path vendor/bundle` | `dirguard._INSTALL_REMEDY`, ruby route `gem_bundler` |
| B | the coder follows it and the tree lands in the workspace | `vendor/bundle/gems/countries-3.1.0/` in the archive |
| C | `vendor` is deliberately outside `BUILD_ARTIFACT_DIRS`, and the inventory is deliberately complete | `groundtruth.py:207-209`, `workspace_inventory` docstring |
| D | so the composed body is 67% gem tree | 175,174 of 259,474 bytes, counted on the capture |
| E | the floor cannot reduce a single message | `msg_before == msg_after`, 12 consecutive floor/refit events |
| F | six 400s, session over, two checks still red | `upstream.error` ×6, 16:43:38–45 |

**Fix at A and at E, not at C.** C is a documented decision with a live reason (`vendor` is real source in PHP and vendored Go) and reverting it would hide deliverables. A is the seam already identified on cell 1: a package manager's install prefix that **cria itself named** in its own advice is not the coder's source, and cria knows the path because cria chose it. E is independent and worth fixing on its own — a fit guarantee that silently does not hold on a one-message body is a false guarantee, and the honest floor either reduces that message or says it cannot.

**Prior occurrences of the same shape:** cycle 1 cell 1 (167 KB, server refused 12×, cell killed), cycle 2 cell 1 (253 KB, 47% vendor, survived at 80%), cycle 2 cell 2 (259 KB, 67% vendor, refused 6×, cell killed). Not a one-off; it lands whenever a Ruby run installs a gem.

### The 9,000-byte bound gated the document that held cell 2's answer

Separate from the above and also cria's, on the same cell.

The model's `zone_for` calls `Country[...]` from inside `module Shipping`, so Ruby resolves `Shipping::Country` and raises `NameError: uninitialized constant Shipping::Country`. Reproduced cold from the archived workspace:

```
lib/shipping/rates.rb:25:in `zone_for': uninitialized constant Shipping::Country (NameError)
Did you mean?  Countries
```

The correct constant in `countries` 3.x is `ISO3166::Country`. At `16:43:37` — the last coder action of the run — the model tried to read `./tmp/read-only/www.rubydoc.info_gems_countries_3.1.0.txt`, the rubydoc page cria had spilled for it. **That file is 9,645 bytes and contains `ISO3166::Country`.** `writeproxy` size-gates a whole-file spill read at `READ_INLINE_MAX = INLINE_RESULT_MAX_BYTES = 9000` and steered it to grep instead. 645 bytes over the line, on the one document that held the fix, at the last call before the 400s.

Stated precisely, because the code is careful about this and so should the finding be: the gate does not refuse — it hands back a grep steer, and the size test runs on the harness's filesystem. What is certain is that the whole-file read did not happen, the model never learned the constant, and the run ended eight seconds later.

This is the same 9,000-byte constant whose justification cycle 1 could not reproduce and cell 1 of this cycle finally demonstrated. Both facts now stand together: the harness's truncation policy is real, **and** the bound cria derived from it is still costing reads that would have fitted.

### Cell 1 read in full — one refutation, and the 9,000-byte question answered the other way

#### REFUTED before it was written down — "cria's bundler route cost the check"

The candidate was clean and wrong, and it is worth recording because it nearly went in the ledger. `dirguard._INSTALL_REMEDY` prefers `gem_bundler` (`bundle3.2 install --path vendor/bundle`) over `gem_direct`, and its own comment at `dirguard.py:184-186` names the failure mode — "installing to vendor/bundle without putting it on the load path is the failure that cost a 100% ruby run." The cell then lost exactly the check that reads third-party requires. The chain wrote itself.

The refutation took one command: open the archived workspace. `lib/shipping/rates.rb` is its only source file, and it has **no `zone_for` and no mention of `countries` or `ISO3166` anywhere outside `vendor/`**. The load path cannot have cost a point for code that was never written. Deliverable 4 was not attempted; the Gemfile and the installed gem are set-up with nothing built on top of them.

What the walk still has to answer is the 100% question: what in the context would have let the model notice it had skipped one of five numbered deliverables.

#### DEMONSTRATED — the harness really does truncate, and cycle 1's "zero markers" was wrong

`harness.truncated_a_result` — the observer that landed after cycle 1 precisely to stop cria believing a remembered number — fired on the first cell of this cycle. Cycle 1 recorded "grep 50 sessions, both forms: **zero**" and concluded the 9,000-byte bound was "guarding a mechanism nobody can currently demonstrate." It is now demonstrated.

Read, not counted. Two distinct cut results in cell 1:

| | role | bytes | cut |
|---|---|---:|---|
| first, call 0064 | `tool` | 10,207 | `…436 tokens truncated…` |
| second, call 0102 | `user` | 253,790 | same marker |

The first, opened and read: a 142-line `vendor/bundle/gems/countries-8.1.0/**` file listing, cut in the middle of the translation YAMLs. Nothing of value was lost — it is a directory listing of `countries-ne.yaml`, `countries-ru.yaml`, `countries-ab.yaml` and 130 more. So the policy is real **and** the one instance in this cell destroyed nothing. Both halves matter: the bound's premise is true, and this is not yet evidence that the bound is earning its cost.

#### The observer over-reports, by the rule it exists to serve

`assists` shows `harness.truncated_a_result: 34`. There were **two** cut results. `note_harness_cuts` runs from `represent_inbound` on every inbound turn and re-scans the whole message list, so one cut already in history is counted again on every later turn — 23 copies of the first, 12 of the second.

That is rule 12 — surface a metric from the authoritative event, never a re-count — broken inside the instrument built to settle a rule-5b argument. Anyone reading `assists` gets 17× the real number, in the direction that argues for the bound. Fix phase, tier 2: count a cut once, keyed on the result it belongs to.

#### CONFIRMED, third occurrence — the prompt is half gem tree

Cycle 1's ledger item 10 recorded a 167 KB briefing against a 48 K window, 46% of it the gem tree cria told the coder to create. Cell 1 of cycle 2, measured on the captured body:

- **253,790 bytes**, 3,834 lines
- **1,810 lines mention `vendor/` — 47% of the lines, 166,416 bytes**
- top prefixes are `vendor/bundle/doc/countries-8.1.0/ri/...` and `vendor/bundle/gems/countries-8.1.0/lib/countries/data/...`

The two decisions that produce this are both deliberate and both documented, and the fix reverts neither. `groundtruth.BUILD_ARTIFACT_DIRS` excludes `vendor` on purpose — "real source directories in some projects and whose cost of being wrong is hiding a deliverable" — and `workspace_inventory` is complete on purpose — "a bounded list weakens the one clause that makes it decisive."

The third fact neither decision had: **cria itself told the coder to create this tree.** `dirguard._INSTALL_REMEDY`'s ruby route prescribes `--path vendor/bundle`. A package manager's install prefix that cria named in its own advice is not the coder's source, and cria knows it is not, because cria chose the path. That is the seam — not "exclude vendor", which would hide a real deliverable in a PHP or vendored-Go repo.

### Run-phase investigations — the carried items, answered read-only

The run phase forbids touching `cria/`, so the carried items that were filed "needs a replay before touching" got their read-only half done while cell 1 ran. Three of the seven now have answers, and two of those answers are **refutations**.

#### 1. REFUTED — the 12 × HTTP 503 cost zero cells

The carried line said "12 × HTTP 503 hard-failed instead of retried." The count is right and the consequence is wrong.

Every 503 in every log is in one of three bursts, each a few seconds long: 08-12 22:58:00–06, 08-14 03:46:36–42, 08-14 03:51:00–03. Read in full, each burst has the same shape — `server.stop {"reason": "interrupt"}`, then a handful of turns from a session that was already running, then `server.stop` again. That is the campaign driver restarting `cria.service` between cells while a **leftover harness session from the previous cell** keeps POSTing. `connection refused` comes first (the endpoint is down), then 503 (llama.cpp is up but still loading the model).

The check that settles it: **no scored run's `capture_dir` matches any of those three session ids** (`019ff802`, `019ffe31`, `019ffe61`), across all 24 rows. They produced no row because they were not cells. Cost to the campaign: zero checks, zero cells.

What is still true, and is now correctly ranked as cosmetic: `classify_failure` maps 503 to `MODEL_UNAVAILABLE`, whose only action is walk-the-chain, and with the single-endpoint chain `("upstream",)` that walk immediately returns `ChainExhausted`, so `upstream.chat` re-raises. A transient "model is loading" is not retried. Worth fixing on its merits; not worth a tier.

#### 2. REFUTED — the context-window fallback is not a leak

Those same bursts show `context.window {"source": "fallback", "n_ctx": 8192}` where the real window is 49152, and the floor then drops turns against the smaller number. That looks like a transient error silently shrinking the window for the life of the process. It is not. `upstream._resolve_window` sets `_window_final` **only on success**, re-probes on every call until `_MAX_PROPS_ATTEMPTS`, and then keeps re-probing every `_PROPS_RETRY_EVERY`. The docstring names the incident it was built for. Self-healing, bounded, no fix.

#### 3. CONFIRMED and quantified — the completion judge is absent exactly where it is needed

This is the real one, and it merges two carried items that turn out to be one root.

`_periodic_satisfaction` is the only completion judgement that does **not** need the coder to claim done. It fires on a drive counter: `satisfaction_check_start = 80`, `every = 20` (this box's `cria.toml`; the code default is 100/25).

Counted from the authoritative phase counts on all 24 cycle-1 rows:

| | cells |
|---|---:|
| reached the drive-80 threshold | **5 of 24** |
| never reached it | **19 of 24** |
| scored 0–50% | 11 |
| …of those, reached the threshold | **3** |

And the judgement census, counted from the events rather than inferred — `loop.satisfaction_check`, `loop.done_critic`, `loop.done`, `loop.done_unverified`, `loop.satisfaction_confirm`, `loop.satisfaction_failclosed`, `loop.done_confirm`, per session:

**Seven cells got no completion judgement of any kind.** Their scores: 0, 0, 0, 0, 0, 20%, 50%. Every single cell that got no judgement is a cell that failed. Every cell that scored 100% got one.
*(The carried note said eight cells; seven is what the events say.)*

The reason the threshold is 80 is written down. `27512a9` built the check for a session that **finished the work and could not stop** — "176+ calls on a done task" — and for that purpose a late first check is correct; you do not ask "is it done?" at drive 5. `d4308bc` made the cadence tunable because "different models spiral at different rates."

So the reason is still true *for the problem it was built for*, and it is the wrong shape for the problem the campaign found. A → B → C, in plain words:

- **A** — the trigger is a drive counter, a proxy for "this session has gone on a long time."
- **B** — a run that is going badly is usually a *short* run (killed at a 15-minute milestone floor), so it never reaches the counter.
- **C** — cria forms no opinion at all about whether the task is done, on precisely the runs where that opinion is the thing missing.

**Not fixed in this cycle, deliberately.** Two reasons. One code state per cycle. And the experiment that would justify a change has to run against the model, which is busy running cells — replaying `judge_satisfaction` now would contend for the same GPU and corrupt the timings the cycle is measuring. The fix phase runs it: replay the 19 short cells' captured evidence at drives 20/40/60 and count how often the judge would have said *satisfied* on a red run. If that number is not ~zero, the threshold is load-bearing as a false-completion guard (#13) and must not move.

#### 4. CONFIRMED — the failover chain-walk never shipped

`failover.run`, `Attempt`, `NextInChain`, `ChainExhausted` and `_walk` have **zero production call sites**; `grep` finds `fo.run` only in `tests/test_failover.py`. The one live use is `upstream.py:438`, calling `decide_action` with a one-element chain to get retry-once-on-timeout. The module docstring advertises "a small buffered `run` executor that drives them," which is true of the file and not of the running system.

Corroborating: **`route.retry_same`, `route.failover` and `upstream.retry` have never been emitted — zero occurrences in every log on disk.** So even the retry-once-on-timeout that *is* wired has never actually fired in production.

#### 5. CONFIRMED, but the carried note named the wrong function

The carried line read "`loop.py:3279` lets a regex decide alone; `8bdeee2` wired only the satisfaction site." Half right, and the half that is wrong changes what gets fixed.

`verdict_from_reasoning` — the function at that line number today — **is** wired at both sites. `loop.py:3413` builds `recover` from `self._ctx.reasoner_role` and hands it to both calls at 3417 and 3418, exactly as `8bdeee2`'s message claims; the satisfaction site does the same at 464–469. Nothing to fix there.

The real asymmetry is its neighbour, five lines down:

| site | call |
|---|---|
| satisfaction, `loop.py:1546` | `_claims_impossible_action(obj, rlog, "satisfaction", fab_ask)` |
| step critic, `loop.py:3284` | `_claims_impossible_action(obj, rlog, "critic")` |

The `ask` argument is missing at the critic. `_claims_impossible_action`'s own docstring sets the contract — "TRIGGER, THEN JUDGE… **With no reasoner the trigger decides alone**, exactly as before" — so the degraded mode is deliberate, and reserved for having no reasoner. At the critic site a reasoner is available and simply is not passed, so the mode meant for a missing reasoner runs with one present. When `_JUDGE_ACTION_CLAIM` hits, the regex discards the verdict on its own; the docstring names the false hits it cannot separate ("I ran the tests" vs "I ran through the checklist"), and the cost of each is a good verdict thrown away and a retry burned.

**Prevalence: zero.** `loop.verdict_fabricated_action` has never been emitted — not once, at either phase, in every log on disk. Denominator stated honestly: the logs only reach back to 2026-08-12, four days, but that window contains cycle 1's entire 24-cell run, and the critic path was busy in it (57 `loop.step_done`, 10 `loop.step_incomplete`).

So: a real inconsistency, a one-argument fix, and **tier 4 by impact** — recorded, not scheduled above anything that actually cost a check (#15).

### What actually blocks the 15 non-100% cells

Read off `verify.py`'s own failure details on all 24 cycle-1 rows, not off the scores. Grouped by check, most-failed first:

| times failed | check | reading |
|---:|---|---|
| 4 | `feed-pipeline-java::substantially_faster` | qwen35 hit **29.9× against a 4.0× bar** and lost it anyway on "same totals: False"; the other three never compiled |
| 4 | `feed-pipeline-java::review_written` | **the cheapest point on the board** — sixty words, two line numbers, no build. Missed in all four cells, one of them 371 calls long |
| 4 | `feed-pipeline-java::csv_library` | qwen35 and gemma4 declared the dependency and still mis-parse the quoted-comma row; the other two never built |
| 3 | `feed-pipeline-java::race_fixed_workers_on` | "import spawned 0 thread(s) (need >=2)" — the concurrency half of the task is not attempted at all |
| 3 | `orders-api-py::customer_orders_route` | the route answers (200, or 0 when the service never bound) but carries neither the items nor the total |
| 3 | `shipping-rates-rb::suite_green_tests_intact` | one deleted seed test (ternary, 80%), one LoadError chain (gemma4), one genuine failure (nemotron) |
| 2 | `rust-toml-cli::builds` | `E0308` / `E0277`+`E0599` — two models never compiled, and the other two checks are `skipped: project does not build` behind them |
| 2 | `handles-cli-node::tests_incl_live` | tests pass with the network blocked — mocked, not live |
| 2 | `orders-api-py::integration_tests` | 3 and 11 of the models' own tests failing |

Three things follow that the fix phase should aim at, in this order.

**`feed-pipeline-java` is the campaign's worst column and its cheapest win.** 0 / 40% / 0 / 0. The `review_written` check needs no build, no library and no concurrency, and was missed four times out of four. Cycle 1 already established why in one of those cells: the completion judge computed the exact missing deliverable ("Create REVIEW.md") four separate times and **the coder was never told**, because `_periodic_satisfaction` may only end a session, never steer it — the deliberate decision recorded under "SURFACED — c1-13".

**That joins finding 3 above into one thread.** On 19 of 24 cells the completion judge never runs at all; on the cells where it does run and finds a specific missing deliverable, what it found is logged and discarded. Both halves have to hold for the finding to reach the coder, and today neither reliably does. This is the rank-1 candidate for cycle 2's fix phase, and its second half needs the operator's ruling, which is still open.

**One cria fault is already visible in this table and is under test this cycle.** `cart-billing-go × nemotron-elastic` failed all five checks because cria's own spilled fetch, saved as `…decimal.go` inside the workspace, was compiled by `go build ./...`. The fix — spill files are always `.txt` — landed after cycle 1's run. Cell 8 of this cycle is the measurement.

### Environment, verified clean 2026-08-14

- **The leaked gems are gone.** `countries-8.1.0` / `unaccent-0.4.0` uninstalled. They had inflated four Ruby rows since 2026-08-10; re-scored with the directory hidden those runs were 1/5, 1/5, 1/5. The untouched seed now scores an honest 0/5.
- **The Java seed's tracked build output is gone**, and so is the reason it existed — `verify.py` built its speed baseline inside the git tree. It builds a copy now, and `suite/tasks/.gitignore` stops the same class of artefact returning from any seed.
- Check both before every run phase: `user_install_listing()` and `git status --short suite/tasks`.

### Carried into cycle 2's fix phase

| finding | state |
|---|---|
| the periodic satisfaction check fires at drive 80 and almost no run gets there — 14 firings across 24 cells, 3 cells | open, needs a replay before touching |
| 8 cells got no completion judgement of any kind; their scores were 20/0/0/50/0/0/0/0 | open, same investigation |
| 12 × HTTP 503 hard-failed instead of retried — the ported table says "switch models", wrong for a single endpoint | open, operator ruling |
| `loop.py:3279` lets a regex decide alone; `8bdeee2` wired only the satisfaction site | open |
| `failover.py` — the chain-walk engine never shipped; the docs claim it did | open |
| six verdict-word readers with divergent strip sets | open, latent — zero occurrences measured |
| `_verdict` / `_satisfaction_verdict` are the same 60-line algorithm twice | open |

---

## Cycle 1

**Phase: WALK** — the run phase finished 2026-08-14 02:45, all 24 cells scored.

**Cycle 1 result: mean 53.8%, up from 51.2%. Nine cells at 100%, up from five.**

Read that as it is. Four cells gained a lot (+100, +75, +50, +50), four lost a lot (−80, −80, −60, −25×3), and eleven did not move at all. The gains came from two task-prompt corrections and the losses from cria; the eleven flat cells include five that never compiled and were never going to on this code state.

*(An earlier running count in this file said twelve at 100%. It was a hand-incremented number and it was wrong; nine is what the results file says.)* Java column complete: 0 / 40 / 0 / 0. Walks of the finished cells run alongside it; no fix lands until the run phase ends.

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

Δ is percentage points against the previous run of the same cell, whatever prompt revision it was earned against. Run ids are on the rows in `suite/results/results.jsonl`.

### The assists, measured against the plain proxy

Better in 7 cells, worse in 3, level in 14. **Net +145 points.** The three own-goals are the fix phase's priority, above any cell that is merely low:

| cell | BASE | CRIA | Δ | cause, from the walk |
|---|---:|---:|---:|---|
| feed-pipeline-java × gemma4 | 80% | 0% | **−80** | a wheel-spin steer fired on a build that had just gone green; the rewrite it prompted dropped `package pipeline;` |
| shipping-rates-rb × nemotron | 60% | 0% | **−60** | 57 calls, two writes, both the same Gemfile. 26 calls hunting a gem already installed, 13 re-running a check cria said it could not parse, 12 on cria's own judges |
| shipping-rates-rb × gemma4 | 40% | 20% | **−20** | the dead-gem chain |

Caveat stated rather than buried: the BASE rows were earned earlier on an older code state, so this is two code states, not a controlled A/B. A −60 and a −80 are not noise, and every cause here is read from the captures rather than inferred from the delta.

### Verdict on the fixes landed BEFORE this cycle

Two different questions get confused here, so both are answered separately.

**Question 1 — were the fixes we landed worth it?** Three clear keepers, three that need correcting, three that should be examined for removal. Nothing to revert.

| fix | verdict | what the walks saw |
|---|---|---|
| reasoning logged on unfinished streams | **KEEP — for observability, not for score** | counted across the walk sections: 6 clear "helped", 4 "did not fire", 6 ambiguous. And every "helped" means it made the WALK possible, not that it moved a run. It is the reason a dozen findings in this document exist. One gap: a killed run still loses its last reasoning |
| rumination rate change | **KEEP — on the readings, not the counts** | abort RATE went **down on 5 cells and up on 4**, including `rust-toml-cli × nemotron` 0/76 → 5/57. The case for keeping it is that where a walk actually read the aborts they were right 5/5 (Rust) and 4/4 (Ruby) — a reading, not a tally |
| the p4 task-prompt corrections | **KEEP — but it is a repair, not an advance** | the +75/+50/+50 are real deltas against the previous run, and misleading as causation. `handles-cli-node` scored 4/4 and 3/4 under earlier wording; the **p3** revision crashed it to 0/2/2/1; p4 restored it to 3/4/4/1. gemma4 is still below the 4/4 it held before p3 |
| derived probe output cap | **CORRECT IT** | this is rank 1. The intent was right and the arithmetic was wrong: 8,500 per command against a 9,000 bound applied to all the commands at once |
| search inlining | **CORRECT IT** | titles inline was right; the note still ends "the file named above" with no file named above — third cell |
| PATH oracle | **CORRECT IT** | right idea, `bash -lc` should be `-lic`; misses every version manager |
| cheap `mvn compile` probe | **CORRECT IT** | helped early in one cell, reported green over a no-op in two others |
| cached-check age note | **EXAMINE FOR REMOVAL** | counted across the walk sections rather than quoted from one: "never fired" ×5, "fired in form, dated nothing" ×3, "fired, did nothing" ×2, "fired on an empty section" ×1. **Zero positive results anywhere** |
| verdict tool | **EXAMINE** | fired in a minority of chances; once ended a run cleanly, once malformed its own arguments |
| completion-judge report framing | **EXAMINE** | mostly nothing; stopped the model damaging working code once, hurt once |

**Question 2 — are the standing assists worth having?** That is what the control walk asked, and it is about the machinery that predates this cycle, not the fixes above. Its answer: of every injection in two winning runs, only the **gate** demonstrably changed the outcome, and only when its report was the only copy of the finding. The rest confirmed or cost calls. That is an argument for **pruning**, which principle 1 already says is the safe direction — not for reverting this cycle's work.

### Fix-phase state, cycle 1

Landed and live: the shared gate budget · `-lic` so cria can see `node` · spill files always `.txt` · Maven/MSVC diagnostics parse · the live-execution probe honours the project's declared command · the search note names its file · a killed run keeps its last reasoning · the assists ledger stops dropping events · **the inbound exec bound deleted** · the XML parameter boundary · four verifiers made case-forgiving · **cria now observes whether the harness truncates instead of assuming it**.

Built and removed: an exec-output spill (a fourth duplicate of machinery that already existed twice) and a steer-rename guard (fixed nothing — see below). Two of thirteen were waste.

### REVERTED — the `data/review.md` guard fixed nothing

Built and removed the same day. The walk ranked it "the likely root of `review_written` failing" and I took that at face value without checking the consequence.

Checked afterwards, in the archived workspace and every prompt of the run:

- no `REVIEW.md`
- no `data/review.md`
- **zero write calls with "review" in the path, across all 371 calls**

The coder never wrote a review file anywhere, so the path cria named made no difference to the score. A guard against a rename that never happened.

**The real reason that check failed:** in 371 calls and 46 minutes the coder never spent one call on a deliverable worth 20 points that needed sixty words and no build. cria noticed four times and said nothing (below), and the one time it did mention the file it was inside a steer about threading.

Same mistake as the 9,000-byte story: repeating a walk's attribution without testing whether the thing it blamed actually caused the outcome. The walks find real bytes; their causal claims are candidates.

### SURFACED — c1-13 is a deliberate decision, not a bug

The walk found four completion verdicts that each named the missing deliverable ("Create REVIEW.md") and said none reached the coder. Verified: zero coder prompts in that run carried a completion nudge, no "Proposed fix" line, no mention of REVIEW.md in any steer.

The cause is one line, and it is on purpose — `loop.py::_periodic_satisfaction`:

```python
if not satisfied:
    return None   # do NOT steer — the reason is judgment, not ground truth. Log only.
```

The periodic satisfaction check may only END a session, never steer it. The asymmetry with the done-claim path (which DOES steer with the critic's reason) is the point: a done-claim is an anomaly the coder created, a timer is not, and steering off a timer is noise on a clock — #3 and #11.

**Not changed.** Reversing it would be exactly the class of revert the operator has asked me to surface instead of doing. What it costs is on the record now: a judge computed the exact unmet deliverable four times in one run and the coder never heard any of it, on a task where that deliverable was the cheapest point on the board — sixty words and two line numbers, no build needed.

The question for the operator is whether a NOT-satisfied verdict that names a **specific missing deliverable** is still "judgment" in the sense that rule meant, or whether that is ground truth of a kind the timer objection does not cover.

### Findings ledger — cycle 1

Seeded from work already done; the walk phase appends to it.

| rank | tier | finding | state | closed by |
|---:|---|---|---|---|
| 1 | 1 | **cria discards its own gate output and then reports the checks GREEN.** Verified cold: 8 discards over the bound, then 19× "the repo's own checks reported no error-class problems" and 8× "the repo's automated checks pass" — while pytest was red and the route returned nothing. A fail-open on missing ground truth (#13), stated as fact (#5b). Same bound as the two below | open | |
| 2 | 1 | **`mvn -q compile` prints 9,390 bytes and the bound is 9,000** — so every Maven run in a whole session was discarded, 15 of them. The model saw its 18 compile errors once, by accident, when it happened to use bare `javac`. The fix is to REDUCE oversized results through `content_reduce`, which already owns lossless head+tail, instead of discarding them | open | |
| 2c | 1 | **`task_complete` is folded into the previous write's content**, so `validate-before-lower` refused a `pom.xml` write 12 times for malformed XML at the line where cria's own junk starts. 14 calls lost | open | |
| 2d | 2 | **the assists ledger undercounts and I quoted it.** 6 steers and 30 gate-carrying prompts recorded as 0 steers and 2 gates. Every "cria intervened N times" from `assists` is a floor, not a count (#12) | open | |
| 3 | 1 | **The same number closes two more doors.** It refuses cria's own joined gate output, and it refuses the coder reading its own source. `Importer.java` at 9,889 bytes was unreadable by every route from call 0068 to the kill; the model said "389 lines, which is not that large" and ended up web-searching a `file://` URL to see its own code. Found independently by three readers who could not see each other's ranges | open | |
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

- **A dropped declaration is silent in some languages and impossible in others.** Cell 13 lost `package pipeline;` in a rewrite and scored 0%. Measured across every Java and Go workspace on disk: 1 of 17 files, one run. Go never loses it because Go refuses to compile a file without one; Java accepts the default package without a murmur. So the exposure is real but narrow, the cost when it lands is the whole cell, and the bar to ADD a guard is high (#1). The rank phase decides.

- **The rumination rate change.** Aborts on the cells that have run under it are mostly down — `orders-api-py × nemotron` 15/200 → 7/175, `cart-billing-go × nemotron` 6/124 → 2/51, `orders-api-py × qwen35` 4/260 → 1/131 — and up on one, `shipping-rates-rb × nemotron` 3/77 → 4/57. That is roughly what it was built to do. The four `feed-pipeline-java` cells are the real test and they have not run yet this cycle; the 11-aborts-in-35-calls figure on that task predates the change and says nothing about it.
- **Aborts cluster on one model, but they are not what sinks it.** nemotron-elastic this cycle: 0% / 0% / 50% / 0% / 25%, with aborts of 4 / 2 / 7 / 1 / 0. Its best cell had seven aborts and its 25% cell had none, so the guard is not the driver. What the five have in common is that four were killed at a milestone floor. That is the question worth reading, and it is now being read.

### The 9,000-byte bound: its justification does not reproduce

Asked for an example of something cria returned that the harness cut. **I could not produce one, and I looked properly.**

What the bound claims (`content_reduce.INLINE_RESULT_MAX_BYTES`): Codex truncates every tool result in its history at 10,000 bytes, so anything cria hands back above that is silently middle-cut in every later prompt.

What is verifiable today:

| claim | check | result |
|---|---|---|
| the harness really has that policy | read the Rust | **TRUE** — `TruncationPolicyConfig::bytes(10_000)`, `models-manager/src/model_info.rs:83`, the production fallback profile for local models |
| the marker appears in cria's prompts | grep 50 sessions, both forms (`…N chars truncated…`, `…N tokens truncated…`) | **zero** |
| large results get cut on cria's path | find the largest tool result cria actually sent upstream | **160,447 bytes, uncut** — sixteen times the supposed limit |
| the cited evidence run | look for `1785893473` | **gone** — deleted in the housekeeping of 2026-08-13 |

So the policy exists in the harness's source and is **not observably operating on the path cria uses**. A 160 KB tool result reached the model through cria intact.

Against that, the bound's measured cost this cycle: 24% of all command results discarded (1,179 sampled, p75 = 8,424), the gate blinded in 7 of 24 cells, a model unable to read its own 389-line source file by any route, and the chain that cost `cart-billing-go × nemotron-elastic` every check.

**What would change this conclusion:** if the harness applies the policy only when rendering its own history to its own model — a path cria never sees, because cria captures what cria sends. That is plausible and it is exactly what needs testing before the number moves. Until then the bound is guarding a mechanism nobody can currently demonstrate, at a cost everybody can.

**Operator's call.** Discovering the limit from the harness rather than hardcoding it is the only version that satisfies principle 18 either way.

### Environment notes — established, deliberately NOT changed mid-cycle

- **A foreign server owns port 8081 on this box, and it answered the Python task's requests.** Confirmed live: `uvicorn` pid 479454, `app.compaction_main:app --host 127.0.0.1 --port 8081`, from `/home/jesse/src/coding-agent-router`, started 2026-08-13 23:21 — during the campaign. In `orders-api-py × nemotron-elastic` the model tried four times to start its own service (calls 0123, 0148, 0166, 0172) and never bound once; every 404 it then chased came from that server. The final score is still honest, because `verify.py` starts the service on a port it chooses itself — but the model could not test its own work for the whole run.
  **This is the operator's process and the operator's call. Not touched.** Backlog entry 30 recorded this exact collision in an earlier campaign and filed it `nothing-to-fix, 1 occurrence`. That judgement was wrong and the entry is re-opened.

- **Java is NOT blocked by its environment — checked directly.** The seed compiles clean out of the box, offline (`mvn -o compile`) and online. A third-party CSV dependency added to the `pom.xml` resolves and downloads (commons-csv 1.10.0, plus six versions already in `~/.m2` from earlier runs). So the task's mandatory "use a third-party Java CSV library" is satisfiable, and the three `mvn compile failed` cells are the models' own broken code plus the cria faults the walks found — not a wall like Ruby's. The cached `.m2` artifacts are contamination of the same shape as the Ruby gem but benign: the `pom.xml` must still declare the dependency and that declaration is what the checker reads.

- **`bundle` is not on this box's PATH.** Debian ships the binaries as `bundle3.2` / `bundler3.2` and nothing provides the unversioned name, so `bundle install` and `bundle exec` both answer "command not found" — for every model, on every Ruby run. The models fall back to `gem install`, which ignores the Gemfile's resolution and installs the newest transitive dependencies, which is how a 2014 gem ends up paired with a 2024 one that no longer exports what it requires.
- **It is a hazard, not a blocker.** `shipping-rates-rb`'s verifier runs bare `ruby -Ilib`, so the intended solution never needed bundler: `gem install countries` puts the gem on the default load path and `require "countries"` just works. Three runs prove it — every Ruby run that chose `countries` scored 60–100%, and both runs that chose `eu_countries` collapsed.
- **So the environment stays as it is.** Installing the binstub mid-campaign would change what is being measured and invalidate every Ruby row. What the walk has to answer instead is what cria told the model when `bundle` failed, and why nothing caught a library that could not load.

### Log

- **2026-08-14 02:45 → 07:33** — nothing. The run phase closed and the walk phase did not start. The per-cell watcher had been the heartbeat all night; when the last cell landed it fired for the last time, and the turn that closed the run phase ended on "continuing now" without launching anything. Five hours idle, found only because the operator asked. Rule added to the goal doc: never end a turn on an intention — have work in flight or say there is none.

- **2026-08-13** — cycle 1 run phase resumed at cell 9 after a driver-imposed `timeout 3000` killed `orders-api-py × gemma4` at 52 minutes of its own 60-minute wall. The cap is gone; the suite owns the only wall clock. The rerun finished in 21 minutes at 100%.
- **2026-08-13** — the campaign driver moved out of a session scratchpad into `suite/cycle_run.py` so a lost terminal cannot lose the loop.
- **2026-08-13** — the goal docs moved to `docs/goals/` and the port-fidelity audit to `docs/audits/`; every reference in `docs/` and `suite/` was repointed. Three comments under `cria/` still name the old path (`cria/loop.py:1757`, `cria/loop.py:3952`, `cria/probediscovery.py:854`). They are inert text and they wait for the fix phase — one code state per cycle applies to a comment as much as to a line that runs.
