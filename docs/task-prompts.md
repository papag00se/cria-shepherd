# The task prompts

**Generated — do not edit.** `python3 suite/prompt_digest.py --write`

This is the text a model actually receives. Each block is `suite/tasks/<task>/prompt.txt`
verbatim, which is the file `suite/run.py` reads and the only source of truth. The
deliverables and the clock come from that task's `meta.toml`; the scored checks are parsed
out of its `verify.py`.

One kind of work per language, so a fault that only shows up in one language is visible as
such. Why these six and not others: `docs/task-battery.md`.

A run's wall clock is 15 minutes per declared deliverable. The milestone FLOOR is separate
and is one passing check per 15-minute interval, regardless of how many deliverables a task
declares.

| task | language | deliverables | checks | wall |
|---|---|---:|---:|---:|
| [shipping-rates-rb](#shipping-rates-rb) | Ruby | 5 | 5 | 75 min |
| [cart-billing-go](#cart-billing-go) | Go | 5 | 5 | 75 min |
| [orders-api-py](#orders-api-py) | Python | 4 | 4 | 60 min |
| [feed-pipeline-java](#feed-pipeline-java) | Java | 5 | 5 | 75 min |
| [handles-cli-node](#handles-cli-node) | Node | 4 | 4 | 60 min |
| [rust-toml-cli](#rust-toml-cli) | Rust | 4 | 4 | 60 min |

## shipping-rates-rb

**Ruby** · 5 deliverables · 75-minute wall

Deliverables: `threshold bug fixed`, `express zone`, `own tests for express`, `README rate table`, `country code -> zone via a maintained gem`

Scored checks: `suite_green_tests_intact`, `hidden_contract`, `express_zone`, `readme_rate_table`, `country_zone_mapping`

```text
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

## cart-billing-go

**Go** · 5 deliverables · 75-minute wall

Deliverables: `rounding fixed + regression test`, `discounts.json with fallback`, `structured logging`, `behaviour preserved`, `third-party decimal money`

Scored checks: `suite_green_plus_regression_test`, `rounding_fixed_everywhere`, `discounts_from_file`, `logging`, `decimal_money_library`

```text
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

## orders-api-py

**Python** · 4 deliverables · 60-minute wall

Deliverables: `GET /customers/<name>/orders`, `status column + customer index, migrated`, `HTTP-level tests`, `SQL injection fixed`

Scored checks: `customer_orders_route`, `schema_migrated`, `integration_tests`, `sql_injection_fixed`

```text
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

## feed-pipeline-java

**Java** · 5 deliverables · 75-minute wall

Deliverables: `messy rows handled + skip counts`, `four times faster, same numbers`, `race fixed, workers on`, `REVIEW.md with file and line`, `third-party CSV library`

Scored checks: `messy_feed_handled`, `substantially_faster`, `race_fixed_workers_on`, `review_written`, `csv_library`

```text
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

## handles-cli-node

**Node** · 4 deliverables · 60-minute wall

Deliverables: `CLI with --json/--help/exit codes and holder + total handles`, `off `request` onto fetch, no runtime deps`, `tests incl. live`, `Dockerfile`

Scored checks: `cli_behaviour`, `request_removed`, `tests_incl_live`, `dockerfile`

```text
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

## rust-toml-cli

**Rust** · 4 deliverables · 60-minute wall

Deliverables: `cargo project`, `dotted-path lookup`, `unit tests`, `README`

Scored checks: `builds`, `lookup`, `error_contract`, `tests_and_readme`

```text
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
