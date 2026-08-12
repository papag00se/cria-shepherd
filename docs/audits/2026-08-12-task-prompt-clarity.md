# The task prompts were testing English, not coding

Operator direction, 2026-08-12: *"that prompt is not good for a weak model. WTF is it supposed to
think of 'hand-roll'? Be clear in the task prompts. Check them all."*

All six audited and rewritten. **No requirement changed. No threshold lowered. No deliverable
removed.** Only the wording, plus two instrument bugs found while reading.

## What was unclear, and what it cost

A mechanical sweep for idiom and undefined words, and the count per prompt lines up with how each
language did. Suggestive, not proof — the sample is one run per cell and the causes are tangled.

| prompt | unclear phrases | what the assists were worth there |
|---|---:|---:|
| feed-pipeline-java | 6 | **−80** |
| cart-billing-go | 6 | 0 |
| shipping-rates-rb | 3 | −40 |
| orders-api-py | 2 | **+50** |
| handles-cli-node | 2 | 0 |
| rust-toml-cli | 1 | +25 |

The worst offender, and the clearest evidence:

> *"Please don't hand-roll the EU member list; it changes, and we'd rather lean on something
> maintained."*

The models understood the idiom — gemma4's thinking says *"'don't hand-roll' strongly suggests using
a library."* The problem is the second half. **It never says "a library."** "Something maintained" can
be satisfied by a constant you promise to keep updated, which is exactly what ternary-bonsai shipped,
with a comment saying it should come from an upstream data file in production.

Across all eight runs of that task, that check passed **once**. And the clause consumed **206
sentences of model thinking** — deliberation about the wording, not about the code.

## The rewrites

Idioms and undefined words out, the same requirement in.

| was | is now |
|---|---|
| "don't hand-roll the EU member list… lean on something maintained" | "Do not write the list of EU member countries into our code yourself… Install a third-party Ruby gem that already knows which countries are in the EU, add it to the project's dependencies" |
| "use whatever the Go ecosystem standardises on for decimal money rather than hand-rolling it" | "Do not write your own decimal type, and do not keep using float64: add a third-party Go module for decimal money — one that goes in go.mod" |
| "don't hand-roll a CSV parser… pull in whatever the Java ecosystem uses" | "do not write your own CSV parser. Add an existing Java CSV library to the project's dependencies" |
| "make it substantially faster without changing what it produces" | "Make it at least four times faster. The numbers it produces — the totals, the row counts, the per-SKU figures — must come out exactly the same" |
| "silently imports rubbish" | "silently imports incorrect data" |
| "two other things while you're in there" | "three other changes to the same code" |
| "fix it properly and turn the workers back on" | "Fix the bug and turn the workers back on, so that running the same feed twice always gives the same answer" |
| "decide sensible handling" | "decide how each kind of bad row should be handled" |
| "add tests, including one that really hits the API" | "At least one of them must make a real request to the live API rather than a mock" |
| "fix that properly wherever it appears" | "a crafted customer name can run SQL of its own. Fix this everywhere it appears, without changing what the lookups return for ordinary names" |
| "drop the dependency entirely" | "remove `request` from the project's dependencies entirely, so the tool runs with no node_modules directory present" |
| "use a suitable published crate" | "add a published crate from crates.io rather than writing a parser yourself" |

**Naming the category is not naming the answer.** "A third-party Ruby gem that knows EU membership"
still leaves the model to find one, install it, and call the right method. That is the work.

### The one place a threshold was revealed

"At least four times faster" states the checker's `SPEEDUP_BAR = 4.0`. Failing a model at 3.9× and
passing it at 4.1× without ever telling it the number is testing mind-reading. It changed nothing in
practice — every model that got that far was at 29× or better; they failed on *"same totals"*, which
is now spelled out.

## Two instrument bugs found while reading

**The prompt asked for less than the checker demanded, on Node.** The prompt said "drop the
dependency entirely", meaning `request`. The checker hides `node_modules` and requires the tool to
still run — so it demands **zero runtime dependencies**. A model adding `commander` for argument
parsing satisfies the prompt and fails the check. gemma4's run did exactly that. The prompt now
states the real requirement.

**Three tasks were on the wrong clock.** The wall is `15 minutes x deliverable_count`, and
`deliverables` in `meta.toml` had drifted from what each task actually scores. shipping-rates-rb,
cart-billing-go and feed-pipeline-java each scored five things on a four-thing clock (60 min);
handles-cli-node scored four on a five-thing clock (75 min). Now aligned:

| task | was | now |
|---|---:|---:|
| shipping-rates-rb | 60 min | 75 min |
| cart-billing-go | 60 min | 75 min |
| feed-pipeline-java | 60 min | 75 min |
| handles-cli-node | 75 min | 60 min |
| orders-api-py, rust-toml-cli | 60 min | unchanged |

## What this does to the completed campaign

**Every score in `battery-report.md` was earned against prompt v1 on the old clocks.** They remain
valid as a record of what happened; they are no longer comparable to anything run from here on.
The v1 prompts are preserved in git history.

A re-run of both arms is 48 cells, roughly twelve hours. It has not been started.
