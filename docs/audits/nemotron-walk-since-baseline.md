# nemotron-elastic — every run since the last baseline, walked

Thirteen CRIA runs, 2026-08-19 07:51 to 2026-08-20 23:39, all `--planner off`, all after the last nemotron BASE run (2026-08-17 12:55). 977 model turns, 812 tool calls, 310 of them shell.

The question this started from: the ladder has nemotron at a reliable 4/4 on `ada-handles`, finishing in 3–9 minutes with 28–58 calls. On the battery it scores 0–50% and runs 15–60 minutes. Same model, same settings. What is different?

| task | score | calls | min | terminal |
|---|---|---|---|---|
| shipping-rates-rb | 20% | 156 | 30.8 | milestone-miss-30min |
| cart-billing-go | 0% | 56 | 15.8 | milestone-miss-15min |
| orders-api-py | 25% | 230 | 61.2 | milestone-miss-60min |
| feed-pipeline-java | 20% | 84 | 31.4 | milestone-miss-30min |
| handles-cli-node | 25% | 32 | 9.1 | exited |
| rust-toml-cli | 0% | 86 | 31.0 | milestone-miss-30min |
| feed-pipeline-java | 20% | 74 | 31.3 | milestone-miss-30min |
| cart-billing-go | 20% | 72 | 30.9 | milestone-miss-30min |
| rust-toml-cli | 75% | 108 | 36.7 | exited |
| shipping-rates-rb | 20% | 107 | 30.8 | milestone-miss-30min |
| orders-api-py | 50% | 181 | 52.5 | milestone-miss-45min |
| handles-cli-node | 25% | 99 | 20.3 | exited |
| shipping-rates-rb | 0% | 55 | 30.8 | milestone-miss-30min |

## Common issues

### 1. Reasoning spirals — 84 turns, 2,394,065 characters discarded

165 turns produced no content and no tool call. Eighty-four of them ended `finish_reason=rumination`: cria's degenerate-run backstop stopped the generation. **They are true positives.** `shipping-rates-rb` 0040, 23,955 characters in, is repeating itself verbatim:

> …because we need to run `bundle install` or something? But the test is running against the code we have now; the code should be updated. Alternatively, maybe the test is using a different version of the code that hasn't been updated because we need to run `bundle install` or something? But the test is running against the code we have

`cart-billing-go` 0023 is 26,145 characters of the same circling over a rounding rule. cria is right to abort, and it recovers well: the very next turn makes a real tool call in **60 of 84** cases; 15 spiral again; streaks are almost always length one (59 of 69), with one run of six.

The cost is the finding, not the detection. **2.39 MB of reasoning generated and thrown away** — roughly 600,000 tokens, about 77 minutes of generation at this model's 130 tok/s, spread across runs whose walls are 30 to 60 minutes. That is the single largest consumer of nemotron's budget, and it is why a model that finishes `ada-handles` in nine minutes cannot finish these.

### 2. Actions written into the reasoning channel — 80 turns

The other eighty empty turns ended `finish_reason=stop` with a complete, well-formed tool call sitting inside the reasoning:

```
<tool_call>
<function=exec_command>
<parameter=cmd>
find . -type f -name "*.rb" | sort
</parameter>
</function>
</tool_call>
```

`massage.recover_reasoning_call` exists for exactly this and **recovers 65 of 80 (81%)**. The twelve refusals are all correct: nine `str_replace_editor` and one `view_file` are tools from other harnesses that this model has memorised and cria never advertised, and the two refused `exec_command` calls were made by the SATISFACTION JUDGE, whose menu is three read-only tools — `loop.verdict_from_reasoning` then recovered its verdict anyway. Nothing here needs fixing.

### 3. Re-running the same command — 89 of 310 shell calls (29%)

Exact repeats of a command already issued, comparing full command text:

| repeats | command |
|---|---|
| 19× | `python3 -m pytest …` |
| 16× | `cargo test` |
| 12× | `go test -…` |
| 7× | `python3 -m pytest …` (second python run) |
| 4× | `go mod tidy` |

By language: python 35, go 23, rust 19, ruby 5, java 4, node 3. The shape is re-running the failing test rather than changing what makes it fail.

### 4. Premature completion — 15 `task_complete` calls

Across 13 runs, four of them in a single `feed-pipeline-java` run on a project that never compiled.

### 5. Wrong tool, wrong path

Seven `view_image` calls aimed at `.rb` and `.java` source files. Six tool calls carrying a mangled path with `runs/suite-` duplicated inside it.

## Language-specific issues

### Rust — never compiles (0%, 0%, 75%)

The failing runs die at the compiler every time: `E0308` mismatched types, `E0432` unresolved import, `E0599` no method, `E0106` missing lifetime.

**And one of them is cria's fault, not the model's.** Run 1787160046 scored 0/4 on `failed to select a version for the requirement 'tomli = "^0.9"'`. The first pass over this corpus recorded that as the model "reaching out of its ecosystem"; walking it call by call says otherwise. The first appearance of the string `tomli` anywhere in that session is cria's OWN TOML manifest check, composed as a `python3 -c` program and carried into the coder's prompt at call 0012 inside the gate command:

    python3 -c 'import sys
    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli as tomllib
    …'

`tomli` is a Python package. The model was writing a Rust TOML reader. It read that as the library to use, wrote `tomli = "^0.9"` into Cargo.toml, and every later build died. Two of cria's own steers then contradicted each other about it — call 0070 says *"replace `use toml::Toml;` with `use tomli::Toml;`"*, calls 0051 and 0053 say delete it.

The same leak feeds Java `from xml.etree import ElementTree as ET` (pom check) and Node `json.load(fh)` (package.json check). Fixed: a probe the coder could retype is one line; a program cria wrote is several, and only the first is shown. Across every gate command in these 13 runs that is 2,519,840 characters cut to 451,288.

The one run that compiled scored 75% and exited on its own.

### Go — invented module paths (0%, 20%)

`go get github.com/arithmetic/decimal` — that module does not exist. Later in the same run, `go get cartsvc` — the project's own module name. A web search did find the real `github.com/ericlagergren/decimal`, but the check still reports `decimal_money_library: declared nothing; imported by non-test source: none`.

One of cria's steers here prescribes invalid code: call 0055 says *"Edit go.mod to remove the version spec v0.1.0 for github.com/shopspring/decimal (keep only `require (github.com/shopspring/decimal)`)"* — a `require` line without a version does not parse.

### Java — uses classes it never imports (20%, 20%)

A steer here also prescribes uncompilable Java: call 0081 hands back `private static final ConcurrentMap<String,Long> skippedCounts = new ConcurrentHashMap<>;` — missing the constructor parentheses.


`cannot find symbol: class ConcurrentMap`, and `(+64 more)` symbols on one run. It declared `opencsv` correctly in the pom, so the dependency reasoning is sound and the code does not compile around it. `race_fixed_workers_on: import spawned 0 thread(s) (need >=2)` — the parallelism it reported adding is not there.

### Node — module-system confusion, and tests that test nothing (25%, 25%)

Its own reasoning, verbatim: *"The user is using ES module? Actually they have `"type": "module"`. In Node.js v22, when using `"type":"module"`, you cannot use `require`…"*. Downstream: `request_removed: listed in package.json: False, required in source: True` — it removed the dependency from the manifest and left the `require` in the code. And the tests it writes do not test: `passes with the network BLOCKED — mocked, not live`, and on another run `ran but collected 0 tests`.

### Python — leaves a server running (25%, 50%)

`integration_tests: the suite never finished — a test is hanging (a server started and not shut down?)`. The trace shows it noticing: `kill -9 $(lsof -t -i :8080 …)`, twice. `customer_orders_route: service did not start` and `schema_migrated: service did not start` on the other run. This is also where the pytest re-run count is highest (19).

### Ruby — the scores are not trustworthy (20%, 20%, 0%)

Two separate false-red mechanisms, both since fixed or filed:

- cria's gate ran a bare `rake test` in a project that vendors its gems, so it reported `cannot load such file` for a suite that passes. Fixed in `249e1a6` — `bundle exec rake test` when the Gemfile declares rake.
- `verify.py` runs its checks the same way. In `shipping-rates-rb_gemma4_…_1787290881` the delivered project gives **8 runs, 8 assertions, 0 failures** under bundler and is scored 1/5. Three of 45 archived ruby runs are affected. Filed, not changed — it is the measuring instrument.

One ruby run is a genuine zero: `readme: zones named ['domestic'], 0/8 rate values`, `third-party requires: none`. It did not do the work.

## What this says about the ladder gap

Nothing here is a pacing artifact and nothing is a cria fault except the ruby measurement. The gap between 4/4 on `ada-handles` and 0–50% on the battery is:

1. **Budget destroyed by spirals** — 600K tokens, ~77 minutes, across runs bounded at 30–60 minutes.
2. **Compile-and-link failures in the three typed languages** — Rust, Java and Go all fail on the toolchain rather than on the task's logic, and in two of the three the model reaches into the wrong ecosystem entirely.
3. **Not knowing when it is done** — 15 premature completions and 89 pointless re-runs.

`ada-handles` is Python, single-file, no compiler and no dependency manifest. That is the whole of the difference.


## Addendum — what the first pass got wrong

The first pass over these runs counted patterns and did not read them. Three of its conclusions do not survive the walk:

- **"Reaches out of ecosystem entirely: `tomli` in a Cargo.toml"** — cria put `tomli` in front of it. See the Rust section.
- **"The step never advances"** — it does. `loop.research_satisfied` cleared step 1 after nine turns and `loop.plan_off_handback` followed. The regex used only matched the last step block in each prompt and there is none after the handback.
- **"29% of shell calls are exact repeats"** stands, but an earlier version of the same number was wrong: commands were compared on their first 80 characters, which the long absolute workspace paths consumed entirely, so distinct commands collapsed together.

What the walk found that counting could not: cria authored the failure in the Rust run, prescribed invalid Go and Java in three steers, and blocked its own satisfaction check 601 times against 7 runs — 244 of the named blocks on `gate-red`, which for a model whose projects rarely compile means the completion machinery is dormant for whole runs.
