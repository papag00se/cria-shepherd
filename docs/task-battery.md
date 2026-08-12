# The task battery — what we test cria against, and why

The suite's job is not to grade models. It is to put cria under the kinds of pressure real coding
work applies, so its own footguns surface where a call-by-call walk can find them. A task earns its
place by exercising machinery no other task reaches.

## Design rules

1. **Comparable weight.** Every task carries roughly four deliverables of similar size, the shape
   the original `ada-handles` set: research, implementation, tests, documentation. A single-skill
   exercise ("fix this one bug") produces a thin signal and finishes in five minutes.
2. **Deterministic scoring only.** `verify.py` runs the deliverables and scores what works. Never a
   model claim, never a judge verdict, never a green gate.
3. **The cheats must be worthless, and must be TESTED.** Every verifier here was run against a real
   cheat before it was trusted — see "Cheat-resistance" below.
4. **Seeded beats greenfield for finding cria bugs.** Greenfield tests research and creation.
   Seeded tasks start from code the model did not write, which is the only way to exercise reading
   an unfamiliar file, editing it surgically, and acting on gate output — where most of cria's
   measured footguns live.
5. **No task is ever special-cased in cria.** Doctrine. The suite doubles as cria's regression
   harness, and a prompt cria recognises is worthless as one.

## The matrix: one kind of work per language

Every task carries four deliverables of similar weight, and **no two tasks share a language**. That
second rule is not decoration. A finding that only ever appears in Python cannot be told apart from
a Python-specific quirk in cria, and the project's whole claim is that it is harness- and
language-agnostic.

**Scores are percentages, not fractions.** A task carries as many checks as its work honestly
needs; the constraint that remains is that every check WITHIN a task costs roughly the same effort.
`suite/capabilities.py` and `suite/coverage.py` model what each task DEMANDS — wall clock does not:
`orders-api-py` takes twenty minutes because it polls an HTTP service and `shipping-rates-rb` takes
one because arithmetic is fast, and neither number says how much the model had to be good at.

**Five of the six now reach the network**, and in every case because the work genuinely calls for
it rather than to tick the box: the right fix for float money in Go is a decimal library, the right
fix for `split(",")` in Java is a CSV parser, and the right source for EU membership in Ruby is a
maintained gem rather than a list typed by hand (Croatia joined in 2013; Switzerland and Norway
never did). The measurement now depends on the package registries being up — a real cost, recorded
here rather than discovered later.

| task | language | categories covered | status |
|---|---|---|---|
| `shipping-rates-rb` | Ruby | **3** resolve failing tests · **1** feature from spec · **4** write missing tests · **19** update docs · country→zone via a gem | built 2026-08-10; 5 checks; seed 0%, honest 100%, four cheats measured |
| `cart-billing-go` | Go | **2** bug from user report · **12** logging/observability · **14** config/environment · **6** refactor · decimal money via a library | built; 5 checks; seed 0%, honest 100%, three cheats measured |
| `orders-api-py` | Python | **8** new API endpoint · **9** database change · **5** integration tests · **11** security fix | built; scored 4/4 by gemma4 and qwen35, so proven satisfiable |
| `feed-pipeline-java` | Java | **17** data transform · **10** optimise slow code · **13** concurrency · **20** code review · real CSV parser | built 2026-08-10; Maven; 5 checks; seed 0%, honest 100%, three cheats measured |
| `handles-cli-node` | JavaScript | **18** external service · **16** CLI tooling · **7** dependency migration · **15** containerise | built; seed scores 0/4; **4/4 not yet proven** |
| `rust-toml-cli` | Rust | discover and use a third-party crate under compile-loop pressure | built; scored 4/4 by gemma4, so proven satisfiable |

Toolchains for all six are on the box and need no network: ruby+minitest, go, python3, JDK 21,
node 22, cargo with a warm crate cache.

### Why the earlier selection was wrong

The first battery ran `shipping-rates-py`, `orders-api-py`, `feed-pipeline-py`, `missing-tests-py`,
`sqlite-inventory` and `rust-toml-cli` — five Python tasks and one Rust. The original five-task
design already had Go and JavaScript in it; the selection dropped both and replaced them with
Python. The `handles-*` ports were excluded on the grounds that one problem in seven languages is a
portability question rather than a variety one. That reasoning is right for measuring variety of
WORK and exactly backwards for measuring variety of LANGUAGE, and the trade was never surfaced.

Two tasks were ported rather than newly invented, so the work axis is unchanged and only the
language moved: `shipping-rates-py` → `shipping-rates-rb`, `feed-pipeline-py` → `feed-pipeline-java`.
The Python originals stay on disk. Retired from the matrix: `missing-tests-py` (its category 4 is
covered by the Ruby task) and `sqlite-inventory` (Python, and overlapping `orders-api-py`).

### Also in the suite, not in the matrix

| task | language | shape |
|---|---|---|
| `ada-handles` | Python | API research + client + tests + live test + docs — already mined for findings |
| `handles-{go,rust,node,ruby,php,java}` | six | the same problem, one language each — isolates the language variable |
| `shipping-rates-py`, `feed-pipeline-py` | Python | the originals the Ruby and Java members were ported from |
| `missing-tests-py`, `sqlite-inventory` | Python | retired from the matrix, kept as evidence |

## Cheat-resistance

Scoring a coding task is mostly a fight against the easy way out. Each defence below was checked by
committing the cheat and confirming the score:

| cheat | defence | measured |
|---|---|---|
| weaken or delete the failing test | seeded tests hashed against `seed/` | 1/4 |
| special-case the numbers in the ticket | hidden cases at inputs never shown | 3/4 |
| `assert True` × 20 | **mutation scoring** — seeded bugs the suite must catch | shallow 2/4, thorough 4/4 |
| mock the "live" test | must PASS with network and FAIL without (`unshare -rn`) | mocked 3/4, live 4/4 |
| import a logger and never call it | run real inputs, read what actually reached stderr | — |
| implement the feature but never test it | the model's own tests must mention it | — |

Two traps worth remembering, both found by running the verifier rather than trusting it:

- `go test` replays a **cached** pass without executing anything. Every Go invocation needs
  `-count=1`, or the network-blocked half of a liveness check succeeds and a genuinely live test
  scores as mocked.
- Hidden expectations must be **computed, not recalled**. One of mine was wrong (7.77 × 7 with
  WELCOME10 rounds to 52.87, not 52.89) and would have failed a correct solution.

## Seeding

A task shipping a `seed/` directory has it copied into the workspace and committed before the run,
so `git status` is clean and the model's own diff stays legible to it. Hidden tests live in
`hidden/` and are copied in only at scoring time — nothing in the workspace hints at them during
the run.


## Verifier corrections found by running the battery

**`shipping-rates-py`, 2026-08-10 — `suite_green_tests_intact` punished the task's own instruction.**
The check demanded the seeded test file be byte-identical to the seed. The prompt says *"Don't
change what the tests assert"* and, two paragraphs later, *"Add it, with tests"* — and the obvious
place to add tests is the file that already has them. The first baseline run caught it: gemma4
appended three correct express tests, deleted nothing, weakened nothing, left the suite green at 10
passed, and lost the point. Its true score was 4/4, recorded as 3/4.

Byte-identity is now per-test-function integrity: every seeded test must still exist with its source
unchanged, and additions are free. The anti-cheat is intact and was re-proven both ways — a weakened
assertion and a deleted test are each still caught, while the honest solution scores 4/4.

The general lesson for the remaining five: a verifier can be wrong by being too STRICT, not only too
lax, and the tell is a plausible-looking near miss rather than an all-zero column. The status tool
catches all-zero automatically; this class needs a human to read the diff.

## RESOLVED 2026-08-12 — cart-billing-go's decimal ambiguity

The prompt said "use whatever the Go ecosystem standardises on for decimal money rather than
hand-rolling it", and `decimal_money_library` requires a THIRD-PARTY module in go.mod. A model could
read stdlib `math/big` as the answer. That was recorded on 2026-08-10 and deliberately left alone at
n=0 realised harm.

Closed in the prompt-clarity pass, not because it finally bit, but because the whole prompt was
being rewritten for a different reason and the sentence was one of the vaguest in the battery. It
now says: *"Do not write your own decimal type, and do not keep using float64: add a third-party Go
module for decimal money — one that goes in go.mod."* Same requirement, no second reading.

## RESOLVED 2026-08-12 — deliverables count vs checks count

`suite/run.py` paces a run at `len(meta.deliverables) x --milestone-minutes`, and the counts had
drifted from what each task scores. Three tasks scored five checks on a four-thing clock;
handles-cli-node scored four on a five-thing clock.

Held open through the campaign for arm parity, then corrected once it closed. shipping-rates-rb,
cart-billing-go and feed-pipeline-java now declare five and run to 75 minutes; handles-cli-node
declares four and runs to 60. The milestone FLOOR is unaffected — it is one passing check per
interval regardless of the count.

## The prompts themselves

The text below is generated from `suite/tasks/<task>/prompt.txt`, which is the source of truth.
Revision **p2** (2026-08-12): idiom and undefined words removed, no requirement changed, no
threshold lowered — `docs/audits/2026-08-12-task-prompt-clarity.md`. Rows in
`suite/results/results.jsonl` carry `p1` or `p2` in their note.

### shipping-rates-rb — Ruby

5 deliverables, 5 scored checks, 75-minute wall.

Checks: `suite_green_tests_intact`, `hidden_contract`, `express_zone`, `readme_rate_table`, `country_zone_mapping`

```
Four changes to the shipping module, please.

The test suite is failing — work out why and fix it. The tests that came with the repo describe
behaviour our customers were promised, so do not change what they assert. Tests you write yourself
are yours to change freely.

We're also launching an express service. It should cost 14.99 base plus 2.50 per kilo, and it
follows the same free-shipping and oversize rules as the other zones. Add it, and add tests for it.

The README has no rate table at all. Add one that lists every zone with its base rate and per-kilo
cost, so support can answer pricing questions without reading the code.

Finally, customers give us a two-letter country code, not a zone name. Add `Shipping.zone_for(code)`
that returns the zone — we ship from the UK, so GB is domestic, EU member states are eu, and
everywhere else is international — and let `shipping_cost` accept a country code as well as a zone.
Do not write the list of EU member countries into our code yourself: EU membership changes over
time, and a list we maintain will go stale. Install a third-party Ruby gem that already knows which
countries are in the EU, add it to the project's dependencies, and get the answer from it.
```

### cart-billing-go — Go

5 deliverables, 5 scored checks, 75-minute wall.

Checks: `suite_green_plus_regression_test`, `rounding_fixed_everywhere`, `discounts_from_file`, `logging`, `decimal_money_library`

```
A customer has reported a billing problem. They bought three items at 19.99 each with the SUMMER25
code and were charged 48.57, but they calculated 48.58 themselves and say we are undercharging by a
cent on lots of orders. Our accountant confirms the totals are consistently a cent low. Please find
the cause and fix it, and add a test so it can't come back.

Three other changes to the same code.

Ops keep asking us to change discount codes and we currently need a deploy to do it. Load the codes
from a discounts.json file next to the binary instead of hard-coding them, keeping the current three
as the file's contents. If the file is missing, use those same three rather than failing.

We can't see anything in production. Add logging so that every total we compute writes one line to
stderr recording the subtotal, the discount code used (or none), and the final total. Support needs
to be able to find a customer's order in the logs with grep.

The accountant also says we should not be doing money arithmetic in floating point at all, and that
we will hit another rounding bug if we keep it. Do not write your own decimal type, and do not keep
using float64: add a third-party Go module for decimal money — one that goes in go.mod — and do the
arithmetic with it. Keep the `Item` struct's field types exactly as they are, because the checkout
service builds those values and we can't change it this sprint, so convert inside the cart.
```

### orders-api-py — Python

4 deliverables, 4 scored checks, 60-minute wall.

Checks: `customer_orders_route`, `schema_migrated`, `integration_tests`, `sql_injection_fixed`

```
Four things on the orders service, please.

Support needs to answer "what has this customer ordered?" without anyone running SQL themselves. Add
a GET /customers/<name>/orders route that returns that customer's orders together with a total value
for them.

For that to be quick we need the database to change: orders should carry a status ('pending' by
default) and the customer column needs an index. Existing databases have to keep working — people
have live data, so an old orders.db must pick up the change rather than breaking or starting empty.

We have no tests that go through HTTP at all, only tests that call the database directly. Add tests
that start the server and make real requests against it, covering the new route and the existing
ones.

One more thing: a security review flagged that order lookups build SQL by string formatting, which
means a crafted customer name can run SQL of its own. Fix this everywhere it appears, without
changing what the lookups return for ordinary names.
```

### feed-pipeline-java — Java

5 deliverables, 5 scored checks, 75-minute wall.

Checks: `messy_feed_handled`, `substantially_faster`, `race_fixed_workers_on`, `review_written`, `csv_library`

```
The nightly supplier feed importer has three problems and I'd like your help with all of them.

First, it is far too slow. It takes minutes on a feed we receive every hour, and profiling says it
is the code and not the disk. Make it at least four times faster. The numbers it produces — the
totals, the row counts, the per-SKU figures — must come out exactly the same as they do now.

Second, there is a threading bug. When we turned on parallel workers the totals came out different
every run, so someone disabled the parallelism instead of fixing it. Fix the bug and turn the
workers back on, so that running the same feed twice always gives the same answer.

Third, the feed has started arriving with rows we didn't anticipate — blank quantities, prices with
currency symbols, duplicate SKUs, rows missing columns entirely, and descriptions with commas inside
quotes that our comma-splitting throws straight into the wrong column. Right now the importer either
crashes or silently imports incorrect data. Decide how each kind of bad row should be handled,
implement it, and make the summary it prints say how many rows were skipped and why. For the quoted
commas: do not write your own CSV parser. Add an existing Java CSV library to the project's
dependencies and let it do the parsing.

Other tooling calls `Importer.summarize(path)` and reads `skus`, `rows` and `totals` off what it
returns, so keep those working.

When you're done, write REVIEW.md giving me your assessment of the code you worked on: what is still
wrong or risky in there. For every problem you name, give the file name and the line number.
```

### handles-cli-node — Node

4 deliverables, 4 scored checks, 60-minute wall.

Checks: `cli_behaviour`, `request_removed`, `tests_incl_live`, `dockerfile`

```
We have a small script that resolves an Ada Handle against api.handle.me. I need it turned into a
command-line tool we can ship.

It should take the handle as an argument, support a --json flag for machine-readable output and a
--help flag, and exit with a non-zero status when a handle cannot be resolved. It must also print
the holder's address and the number of handles that holder owns, which it does not do today.

The script currently uses the deprecated `request` package. Move it to the fetch function built into
modern Node, and remove `request` from the project's dependencies entirely, so the tool runs with no
node_modules directory present.

Add tests. At least one of them must make a real request to the live API rather than a mock, so we
know the tool works end to end.

Finally, add a Dockerfile so ops can run it without installing Node.
```

### rust-toml-cli — Rust

4 deliverables, 4 scored checks, 60-minute wall.

Checks: `builds`, `lookup`, `error_contract`, `tests_and_readme`

```
Create a Rust command-line tool in this directory using cargo.

The tool reads a TOML file and prints the value found at a dotted key path, so
`cargo run --quiet -- config.toml server.port` prints just the value (for example 8080). For TOML
parsing, add a published crate from crates.io rather than writing a parser yourself.

If the file does not exist, or the key path is not in it, print an error to stderr and exit with a
nonzero status.

Include unit tests for the key-path lookup logic, covering a nested table, an integer value, a
string value, and a missing key.

Add a README that explains how to build the tool, how to use it, and how to run its tests.
```
