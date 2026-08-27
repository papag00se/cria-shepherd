# Engagement ladder — progress

Truth: `python3 suite/engagement_status.py`. This file is for reading; that command is the status.

## Build — DONE

All six rungs gate, `tests/test_engagement_levels.py` passes, 4,624 tests green.

The contract is stated as OBSERVED BEHAVIOUR — a real cria server at each level, its own event log
read back — because the old claim ("assists off means the model on its own") lived in a docstring,
and a docstring cannot fail. Four assertions hold at every rung:

- no level lets a higher rung run;
- every logged mechanism is claimed by exactly one rung;
- levels 0-4 are identical with the planner on and off;
- every rung adds a mechanism its predecessor did not run.

### What each rung adds, measured from the fixture

| level | name | first appears here |
|---|---|---|
| 0 | pure proxy | wire translation only — `ctx.estimate`, `context.window` are measurement, not surgery |
| 1 | `TOOL_CALL_FIXES` | `massage.history_args_repaired`, `context.deorphaned` |
| 2 | `SIMPLE_TOOLS` | `writeproxy.advertised`, `toolmenu.cheatsheet` |
| 3 | `CONTEXT_FIXES` | `context.focus_trim`, `context.floor_skipped` |
| 4 | `DONE_REFUSALS_ENABLED` | `loop.start`, `loop.step_incomplete`, `loop.completion_probe` |
| 5 | `ASSISTS_ENABLED` | `loop.satisfaction_check`, `loop.satisfaction_gap_named` |

### Decisions worth keeping

**One owner per rung.** The tool layer was called identically from the chat path and the Responses
path; the gate went inside `_setup_translation` and the tool menu moved in with it. A level gate
written at two call sites is honoured at one of them the first time someone edits in a hurry.

**The trigger decides the rung, not the machinery.** `done_critic` and the completion probe are
level 4 because the model tried to stop. `satisfaction_check` and the periodic gate are level 5
because a turn counter fired. They call the same functions.

**The planner is an assist**, so below level 5 the loop always drives the synthetic single-item
path however `[planner] enabled` is set. That is what makes levels 0-4 planner-agnostic by
construction rather than by discipline — there is no plan-on branch left to diverge from.

**The periodic check is gated at its callers.** `_periodic_satisfaction` has a deliberate contract
that `blocked` is its first word, asserted against a Loop with no context at all. A level gate in
front of that broke six test files before the gate moved to the two call sites instead.

## Open finding: dialect recovery cannot parse a call with no parameters

`massage._reasoning_call_spans` matches `<function=X><parameter=…>…</parameter></function>` and
returns NOTHING for `<function=X></function>`. Verified directly:

    spans for a NO-PARAMETER call:   []
    spans for a call WITH a parameter: [(14, 81, 'xml-function', [('read_file', {'path': 'a.py'})])]

Walked on L1 handles-cli-node x qwen35 (2026-08-25), judged 0. Recovery fired once, then the model
emitted `<function=list_mcp_resources></function>` and the turn came back empty — the call was
neither recovered, nor refused as off-menu, nor logged. A lost action with no trace, which is the
class doctrine 12 exists for.

NOT FIXED MID-CAMPAIGN, deliberately. Changing what level 1 does while its cells are running would
mean qwen35's L1 arm was measured under two different level-1 behaviours — the same contamination
four L4 cells were superseded for. It also would not have saved this cell: `list_mcp_resources` is
off-menu, so a recovered call is refused, and the fact that the tool does not exist is spoken by the
LOOP, which is level 4. Below level 4 an off-menu call is silence either way.

## Cells — 73 / 144

Judged usefulness per cell. `·` not run, `—` run but not judged.

| model | level | shipping | cart | orders | feed | handles | rust | mean |
|---|---|---|---|---|---|---|---|---|
| gemma4 | L0 pure proxy | **85** | **92** | **89** | **100** | **93** | **86** | 91 |
| gemma4 | L1 TOOL_CALL_FI | **28** | **92** | **34** | **33** | **6** | **51** | 41 |
| gemma4 | L2 SIMPLE_TOOLS | **11** | **89** | **81** | **76** | **66** | **100** | 70 |
| gemma4 | L3 CONTEXT_FIXE | **85** | **88** | **84** | **96** | **78** | **86** | 86 |
| gemma4 | L4 DONE_REFUSAL | **26** | **73** | — | — | — | **86** | 62 |
| gemma4 | L5 ASSISTS_ENAB | **73** | **89** | **92** | **100** | **91** | **51** | 83 |
| qwen35 | L0 pure proxy | — | **21** | **0** | **0** | **0** | **0** | 4 |
| qwen35 | L1 TOOL_CALL_FI | **55** | **92** | **83** | **62** | **0** | **100** | 65 |
| qwen35 | L2 SIMPLE_TOOLS | **76** | **89** | **88** | **100** | **63** | **100** | 86 |
| qwen35 | L3 CONTEXT_FIXE | **93** | · | **83** | **80** | **58** | **74** | 78 |
| qwen35 | L4 DONE_REFUSAL | **86** | **45** | **79** | **100** | **83** | **100** | 82 |
| qwen35 | L5 ASSISTS_ENAB | **100** | **63** | **29** | **96** | **58** | **100** | 74 |
| ternary-bonsai | L0 pure proxy | **54** | **90** | · | · | · | · | 72 |
| ternary-bonsai | L1 TOOL_CALL_FI | · | · | · | · | · | · | · |
| ternary-bonsai | L2 SIMPLE_TOOLS | · | · | · | · | · | · | · |
| ternary-bonsai | L3 CONTEXT_FIXE | · | · | · | · | · | · | · |
| ternary-bonsai | L4 DONE_REFUSAL | · | · | · | · | · | · | · |
| ternary-bonsai | L5 ASSISTS_ENAB | · | · | · | · | · | · | · |
| nemotron-elastic | L0 pure proxy | · | · | · | · | · | · | · |
| nemotron-elastic | L1 TOOL_CALL_FI | · | · | · | · | · | · | · |
| nemotron-elastic | L2 SIMPLE_TOOLS | · | · | · | · | · | · | · |
| nemotron-elastic | L3 CONTEXT_FIXE | · | · | · | · | · | · | · |
| nemotron-elastic | L4 DONE_REFUSAL | · | · | · | · | · | · | · |
| nemotron-elastic | L5 ASSISTS_ENAB | · | · | · | · | · | · | · |

_updated 2026-08-25 05:38_

### Pass 2 — cell 1/76 — L4 shipping-rates-rb × gemma4 (re-run of a superseded cell)

The runner died overnight taking cell 75 with it; relaunched 06:09 with the re-deriving worklist, which offered the four superseded L4 gemma4 cells for the first time. Left behind: an orphaned codex still calling the single-slot model server, and `[engagement] level = 0` in the live config — a killed runner never restores it. Both cleared before relaunch.

**Judged 100.** All five checks met with real work behind each: `countries ~> 8.1` in the Gemfile and `ISO3166::Country#in_eu?` actually called in `lib/shipping/rates.rb`, README table complete, coder-written tests added. Rung clean — no level-5 mechanism fired in the cell's window (`loop.periodic_gate`, `loop.wheel_spinning`, `loop.satisfaction_check` all absent). `loop.rumination` fired once, which is a level-4 recovery and belongs here.

### Pass 2 — cell 2/76 — L4 orders-api-py × gemma4 (re-run of a superseded cell)

**Judged 100.** Parameterised SQL in both query paths, a real index on `customer`, and integration tests that start the server on a thread and speak HTTP to it. Session ended on its own after 63 calls in 15.4 minutes. Rung clean — no level-5 mechanism fired; the one `loop.rumination` is a level-4 recovery. A duplicate `orders.db` at the workspace root is untidy but outside every deliverable.

### Pass 2 — cell 3/76 — L4 feed-pipeline-java × gemma4 (re-run of a superseded cell)

**Judged 100**, in 8.3 minutes and 30 calls. Notable because the concurrency fix is the correct one, not the near-miss that has sunk other cells on this task: `totals.merge(sku, value, Double::sum)` on a `ConcurrentHashMap` is atomic, where a lock wrapped around a read-modify-write pair is not. Speed bar cleared 32.2× against 4.0×. Rung clean — no level-5 mechanism fired.

### Pass 2 — cell 4/76 — L4 handles-cli-node × gemma4 (re-run of a superseded cell)

**Judged 93** in 3.6 minutes and 32 calls. CLI, dependency removal and Dockerfile are all fully delivered. The live test scores 70: it passes with network and fails without, so the check is honestly met, but it re-implements the fetch inline instead of invoking `lookup.js` — a broken CLI would still pass it. Rung clean.

All four superseded L4 gemma4 cells are now re-run at their own rung: 100, 100, 100, 93.

### Pass 2 — cell 5/76 — L0 shipping-rates-rb × qwen35

**Judged 0.** `crashed-early` after 3 model calls and 21 seconds; `git status` in the workspace is clean, so the tree is byte-identical to the seed. This is the L0 qwen35 pattern the campaign already established — 5 of 6 of its pure-proxy cells die in well under a minute — and it is the whole reason level 1 is worth +61 to this model.

### Pass 2 — cell 6/76 — L3 cart-billing-go × qwen35

**Judged 100** in 1.9 minutes and 34 calls. Decimal arithmetic end to end with a single `Round(2)` at the last step — the shape the task is actually testing — plus a named rounding regression test and a discounts file the program survives without. Rung clean in the strongest possible form: **zero `loop.*` events in the window**, which is what level 3 should look like, since every loop event belongs to level 4 or above.

### Pass 2 — cell 7/76 — L0 orders-api-py × ternary-bonsai (previously wrote no row)

**Judged 89**, `milestone-miss-60min` after 135 calls and 60.7 minutes. Route, schema and injection fix all fully delivered; the integration suite is well built — subprocess server, socket wait, four route cases — but red, and the cause is one Python defect in the coder's own code:

`orders/db.py` binds `def create_order(..., path=DB_PATH)`. Default arguments bind at import, so `serve()`'s `db.DB_PATH = db_path` never reaches it. Point the app at a custom database and `init()` creates the table in the new file while every query still writes to the old one — which is why `orders.db` is 0 bytes on disk. Single-token-class defect, same family as the others this campaign has surfaced.

L0 rung verified clean: zero `loop.*`, `massage.*`, tool or context events in the window.

### Pass 2 — cell 8/76 — L0 feed-pipeline-java × ternary-bonsai (previously wrote no row)

**Judged 0.** `exited` after 10 model calls and 83 seconds. `git status` shows the tree clean apart from a `target/` build directory — the coder compiled the seed and stopped without writing a line. Both previously row-less cells now have rows.

### Pass 2 — cell 9/76 — L0 handles-cli-node × ternary-bonsai

**Judged 100** in 13.7 minutes and 40 calls. Notable for the test suite: `test/run-tests.js` spawns the real CLI as a child process across nine scenarios and asserts on exit codes and parsed output. Compare gemma4's L4 cell on the same task, judged 93, whose live test re-implemented the fetch inline and would pass against a broken CLI. Same check met by both; only one of them actually tests the program.

### Pass 2 — cell 10/76 — L0 rust-toml-cli × ternary-bonsai

**Judged 98** in 30.4 minutes and 75 calls. Recursive table walk with correct `None` on a non-table intermediate, six integration tests that cover the failure paths, and a table-valued key path that exits 1 instead of printing a table. Deducted 5 on `lookup` for `{:.10}` float printing — over-precise, but no float exists in the config, so nothing exercises it. This completes ternary-bonsai's L0 row.

### Pass 2 — cell 11/76 — L1 shipping-rates-rb × ternary-bonsai

**Judged 7.** `milestone-miss-30min` after 49 calls. The coder wrote 622 lines — express zone constants, an EU-membership lookup, the lot — and every line is dead, because line 6 is `require "all_countries"` and no such gem exists. No Gemfile was written either. The box has `countries`, `eu_countries` and `iso_country_codes` installed; the model invented a fourth name.

Worth recording against the rung question: ternary-bonsai scored 54 on this task at L0 and 7 at L1. The failure is a hallucinated dependency name, which is not something any rung of the ladder touches.

### Pass 2 — cell 12/76 — L1 cart-billing-go × ternary-bonsai

**Judged 32.** `milestone-miss-30min` after only 11 model calls. Does not compile. Three invented library APIs in one file — `decimal.NewFromInt64`, `decimal.RoundingHalfEven`, and a two-argument `Round` — plus `Discounts` read but never defined and `sub.Float64()` used in single-value context when it returns two.

Second ternary-bonsai cell in a row lost to hallucinated API surface rather than to reasoning. At L0 this model scored 90 on the same task.

### Pass 2 — cell 13/76 — L1 orders-api-py × ternary-bonsai

**Judged 61.** `milestone-miss-30min` after 49 calls. Three one-line defects, all of a kind:

- `/customers/alice/orders` → `self.path[12:]`. The prefix is 11 characters and the `/orders` suffix is never stripped, so it looks up a customer named `lice/orders`.
- `/orders/1` → `self.path[7:]` leaves the leading slash, so the id is `/1` and every fetch 404s. This is what makes the verifier's "old rows readable" flag false — the migration is sound (guarded `ALTER TABLE ADD COLUMN`, index created); the reader is broken.
- The integration helper signals readiness from inside the request handler, then waits for that signal before sending a request. Ten tests each burn the full 10-second timeout waiting for a request they are blocking.

Scored `schema_migrated` at 85 rather than 0: the data survives, and the check that reads it back was defeated by a different deliverable's bug.

### Pass 2 — cell 14/76 — L1 feed-pipeline-java × ternary-bonsai

**Judged 14.** `milestone-miss-30min` after 59 calls. 13,441 bytes of Java, none of it compiling. Verified by patching a copy: adding the six missing `java.util.concurrent` imports still leaves two errors — `java.util.Arrays` also unimported, and `if (WORKERS_ENABLED && !rows.length > 0)`, which applies logical-not to an int. Even fixing the imports, the worker branch could never have been entered.

Fourth ternary-bonsai L1 cell, fourth loss to mechanical defects the rung has no bearing on. Running L1 row for this model: 7, 32, 61, 14.

### Pass 2 — cell 15/76 — L1 handles-cli-node × ternary-bonsai

**Judged 99** in 13.7 minutes. Test drives the real CLI via `execSync` and asserts on exit codes, stderr text and parsed JSON field types. Docked 5 on the Dockerfile for a no-op multi-stage build — a `builder` stage that copies three files and produces nothing, since the project has no build step.

This model's L1 row now reads 7, 32, 61, 14, 99: four mechanical collapses and one clean pass, on the rung that only repairs tool-call syntax.

### Pass 2 — cell 16/76 — L1 rust-toml-cli × ternary-bonsai

**Judged 11.** `milestone-miss-45min` after 113 calls. The dotted-path resolver is written correctly; the build dies on `map.get(head)` passing a `&&str` where `&str` is wanted. Verified on a copy: changing it to `map.get(*head)` compiles the project clean. One asterisk, 45.8 minutes.

Sharpest instance yet of the pattern: this model's own L0 cell on the same task scored 98 and its source carries a comment explaining precisely this deref — `k is &&str, so *k gives &str which implements Borrow<str>`. Same model, same task, one rung apart, and it got right at L0 what it got wrong at L1.

**ternary-bonsai L1 row complete: 7, 32, 61, 14, 99, 11 → 37.** Against 72 at L0. Every loss is a mechanical defect — a hallucinated gem, three invented Go APIs, two off-by-one slices, missing Java imports, one missing deref. Level 1 repairs tool-call syntax and touches none of them.

### Pass 2 — cell 17/76 — L2 shipping-rates-rb × ternary-bonsai

**Judged 100** in 32.6 minutes and 112 calls. Real `ISO3166::Country#in_eu?` lookup behind a declared Gemfile, complete README table, and 21 self-written tests covering boundaries the prompt never named — oversize surcharge interacting with free shipping, the oversize kilo threshold, negative weight, unknown zone. Rung clean: no `loop.*`, context-floor, focus-trim or compaction events.

Same model, same task: 54 at L0, 7 at L1, 100 at L2.

### Pass 2 — cell 18/76 — L2 cart-billing-go × ternary-bonsai

**Judged 33.** `milestone-miss-30min`. Root cause is a hallucinated version number: `go.mod` requires `github.com/shopspring/decimal v1.30.0`, which does not exist, so `go.sum` can never be written and the package never builds. Confirmed by hand — `go get` reports `unknown revision v1.30.0`. Behind it waits a second invented name, `decimal.RoundModeHalfUp`. Third ternary-bonsai cell lost to invented dependency coordinates.

**Metrics bug found and fixed (`suite/run.py`).** This row recorded `calls: 2` and `avg_tok_s: 51.4`. The run actually made **101 calls at 43.5 tok/s**. `collect_capture` read only the newest capture directory, and cria had opened five during the cell; the newest held a two-call tail. `calls` and `avg_tok_s` feed the `avg calls` and `avg min` columns of every level grid, so the report was carrying a false fact about how hard a model worked.

Fix: sum every capture directory created inside the run window, and pick the primary by call count rather than mtime. Row repaired in place with a `metrics_repaired` note. Swept all other ladder rows against their own capture directories — **this was the only one wrong**.

### Pass 2 — cell 19/76 — L2 orders-api-py × ternary-bonsai

**Judged 100.** `budget-killed` at 60.6 minutes after 130 calls, with the work already finished. 15 tests green, including the coder's own SQL-injection case and a multi-customer isolation case. Both route slices that broke its L1 attempt on this task are correct here.

Metrics repaired for this row too (125 → 130 calls, 38.3 → 38.8 tok/s): it launched two minutes before the `collect_capture` fix landed, so it still ran the newest-dir-only code. Every row from here on is counted correctly at write time.

Same model, same task: 89 at L0, 61 at L1, 100 at L2.

### Pass 2 — cell 20/76 — L2 feed-pipeline-java × ternary-bonsai

**Judged 94** in 25 minutes and 74 calls. Every check met, 53.2× speedup against a 4× bar. Docked 25 on the race deliverable for a defect the checks cannot see: the accumulation strategy is right — per-worker local maps merged only after `join()` — but the `ArrayList` collecting those workers is mutated from all four threads inside the `Runnable`. Eight runs agreed, so the check passed; the code is still not race-free.

Exactly the sort of thing the strict score cannot express — 5.0/5.0 either way.

### Pass 2 — cell 21/76 — L2 handles-cli-node × ternary-bonsai

**Judged 76** in 8 minutes. CLI, dependency removal and Dockerfile all correct. The test suite scores 5: twelve tests that cannot fail.

```js
function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++ }
  catch (e) { failed++ }
}
```

Every test body is `async`, so `fn()` returns a Promise the runner never awaits. `passed++` runs before any assertion does, and the summary prints and exits 0 before the microtasks settle. Confirmed by hand: the suite reports `12 passed, 0 failed` with the network removed, including both tests named "real API request". It would report the same against a deleted `lookup.js`.

**Verifier detail corrected.** The check reported "passes with the network BLOCKED — mocked, not live". Nothing was mocked. The verdict was right and the score unchanged, but the wording named a cause the check never established — the same class of false account the function's own comment block records fixing once before, for the zero-collected-tests case. Now: "nothing here proves a live call (mocked, vacuous, or offline-only)". Detail only; `ok` and scoring untouched, so no cell measures anything different.

### Pass 2 — cell 22/76 — L2 rust-toml-cli × ternary-bonsai

**Judged 11.** `milestone-miss-30min` after 21 calls. Four mismatched delimiters — `&[ ... ];` for `&[ ... ]);` — stop the crate parsing. Verified on a copy: closing them builds a working CLI that prints usage, rejects missing arguments and reports a missing key correctly. The program was never the problem; its inline test module was, and behind the syntax it carries nine further type errors. No README.

**ternary-bonsai L2 row complete: 100, 33, 100, 94, 76, 11 → 69.** Against 72 at L0 and 37 at L1.

### Pass 2 — cell 23/76 — L3 shipping-rates-rb × ternary-bonsai

**Judged 1.** `milestone-miss-30min` after 71 calls. The entire session went into dependency plumbing: a Gemfile pinning `countries ~> 2.0`, `BUNDLE_PATH: ./vendor/bundle`, and 77 MB of vendored gems successfully installed. `lib/shipping/rates.rb` is byte-identical to the seed. Not one line of source was edited in half an hour.

A different failure mode from this model's other losses — not a wrong token, a wrong allocation of the whole session.

### Pass 2 — cell 24/76 — L3 cart-billing-go × ternary-bonsai

**Judged 78.** The application is correct; its tests are not. All four tests compute the right answer — the failure lines literally read `Total() = 48.58, want 48.58` — and fail because they compare `decimal.Decimal` values with `!=` instead of `.Equal()`. Two decimals holding 15 (exponent 0) and 1500 (exponent −2) are numerically equal and structurally different.

Verified: deleting `discounts.json` still builds, and with the comparison corrected the suite goes green. So `discounts_from_file` reads False only because the model's own tests are red — the loader is properly guarded with defaults behind an `err == nil` check. Scored 90 rather than 0.

Strict score 3.0/5.0 for a program that does everything the task asked.

### Pass 2 — cell 25/76 — L3 orders-api-py × ternary-bonsai

**Judged 93.** `milestone-miss-60min` after 93 calls. Nine of ten HTTP tests green. The tenth fails on its own fixture: it builds a V1 database, inserts alice, and calls `close()` without `commit()`, so the row is discarded before the server ever starts. bob's insert then takes id 1 and the assertion reads `assert 'bob' == 'alice'`. Confirmed in isolation — close-without-commit leaves the table empty.

Second cell running where the model's own test setup, not its program, produced the red. The migration it was trying to test passes the verifier's independent probe.

### Pass 2 — cell 26/76 — L3 feed-pipeline-java × ternary-bonsai

**Judged 99** in 18.5 minutes and 39 calls. Atomic `totals.compute(sku, ...)` per key with nothing unsafe behind it — a cleaner fix than this model's own L2 attempt, which left the worker-results list unsynchronized. Review names three real risks.

**Verifier bug found and fixed.** The review check reported `607 words, 0 located finding(s)` and failed the deliverable, for a review that names the file and the line of every finding:

```
**File:** `src/main/java/pipeline/Importer.java`
**Line:** ~238 (call site) / ~224–229 (`printSkipStats` body)
```

Between `Line` and `238` sit a colon, two asterisks, a space and a tilde — **five** non-word characters against a matcher window of **four**. A correctly located finding scored as unlocated because of how it was punctuated.

This is the third instance of the same class in this one check, and the file's own comments record the previous two: case-sensitive `REVIEW.md`, and a markdown table needing five characters against the same four-wide window. Widened the post-`line` window from 4 to 8 — enough for a bolded, punctuated label, not enough to span a sentence. Checked against every `REVIEW.md` on disk: two counts move, one verdict changes (this cell, 0 → 7); qwen35's goes 11 → 12 and was already passing. Row re-verified: 4.0 → 5.0/5.0.

### Pass 2 — cell 27/76 — L3 handles-cli-node × ternary-bonsai

**Judged 94** in 4.4 minutes and 16 calls — the fastest clean cell this model has produced. Nine tests driving the real CLI through `execSync`; synchronous, so the try/catch actually catches. Verified: exits 1 with the network removed, 0 with it. Directly contrast its L2 cell on this task, where an unawaited async runner made twelve tests unfailable.

Docked on the Dockerfile: it works, but carries a builder stage whose output is discarded and two `npm ci ... || true` lines for a project with no dependencies and no lockfile — in a runtime image that installs nodejs without npm, so the command could never succeed and is silenced rather than removed.

### Pass 2 — cell 28/76 — L3 rust-toml-cli × ternary-bonsai

**Judged 18.** `milestone-miss-30min` after 42 calls. Five invented toml API names in one file — `Value::Bool` for `Boolean`, `Value::Int` for `Integer`, `Value::Map` for `Table`, `Value::Null` which does not exist, and `as_map_ref` for `as_table`. Not a typo behind working logic: the value type it reasons about is the wrong shape throughout. README is real and complete; thirteen tests cannot run.

**ternary-bonsai L3 row complete: 1, 78, 93, 99, 94, 18 → 64.**

Its rust cell has now scored 98, 11, 11, 18 across four rungs. The 98 was L0 — pure proxy, no cria involvement at all.

### Pass 2 — cell 29/76 — L4 shipping-rates-rb × ternary-bonsai

**Judged 100** in 43.5 minutes and 163 calls. Real `ISO3166::Country#in_eu?` behind a Gemfile that also scopes minitest to a test group, 18 self-written tests, complete README table. Rung clean — no level-5 mechanism fired.

This model's five attempts at this one task now read **54, 7, 100, 1, 100**. Same prompt, same settings, five different outcomes spanning the whole range.

### Pass 2 — cell 30/76 — L4 cart-billing-go × ternary-bonsai

**Judged 97** in 43.7 minutes and 76 calls. Every check met. Tests compare with `got.Equal(want)` — the correct decimal comparison, where this model's L3 cell on the same task used `!=` and failed four tests that had computed the right answer.

Docked 15 on logging: `%.2f` prints `subtotal=44.98` where the value is 44.9775. A log written to debug a rounding bug that rounds the number under investigation is weaker than the L3 attempt, which logged full precision.

### Pass 2 — cell 31/76 — L4 orders-api-py × ternary-bonsai

**Judged 64.** `milestone-miss-45min` after 70 calls. Migration and injection fix both correct. The customer route fails on half of the bug it had at L1: that run used `self.path[12:]` when the prefix is 11 characters *and* never stripped the trailing `/orders`. This run fixed the offset and still never strips the suffix, so the lookup asks for a customer named `alice/orders`.

Eight of ten tests red — two genuinely catching that route bug, six dying in the suite's own readiness probe.

### Pass 2 — cell 32/76 — L4 feed-pipeline-java × ternary-bonsai

**Judged 80.** `milestone-miss-75min` after 75 calls and 76.4 minutes — the longest cell of the campaign. Code deliverables all correct, including the atomic `totals.merge(sku, value, Double::sum)` with nothing unsafe behind it. The review was simply never written: the workspace holds README, pom, src and data, and no review file under any name.

Same model wrote a 607-word review with seven located findings on this task at L3, in 18.5 minutes.

### Pass 2 — cell 33/76 — L4 handles-cli-node × ternary-bonsai

**Judged 76** in 31.8 minutes. CLI, dependency removal and Dockerfile correct. The tests score 5: two near-duplicate files, 132 and 136 lines, and **neither ever runs**. Both end `module.exports = { ... }` — a suite object nothing invokes — so `node test/run-tests.js` exits 0 having executed no assertion. Two more bugs behind it: `path.join(__dirname, '..', 'lookup.js', ...args)` joins the arguments into the path, and `result.code` is read where `spawnSync` returns `result.status`.

**The verifier wording fix from cell 21 earned itself here.** The check now reports "nothing here proves a live call (mocked, vacuous, or offline-only)". Under the old wording this would have read "mocked, not live" — and there is no mock anywhere in 268 lines. Second cell in this campaign whose cause the old string would have misnamed.

### Pass 2 — cell 34/76 — L4 rust-toml-cli × ternary-bonsai

**Judged 16.** `milestone-miss-30min` after 53 calls. Three errors inside eight lines: `part.as_str()` on a `&&str` (unstable; `*part` is the stable form), a `Vec<&str>` collected from `&&str` without `.copied()`, and that vector printed with `{}`. Verified on a copy — correcting the three compiles the crate. No README; `src/lib.rs` left as a 0-byte file.

**The rust column for this model now reads 98, 11, 11, 18, 16 across five rungs**, and four of the five failures involve the same `&str` reference confusion. Its L0 source carries a comment explaining the fix.

**ternary-bonsai L4 row complete: 100, 97, 64, 80, 76, 16 → 72.** Its L0 row was also 72.

### Pass 2 — cell 35/76 — L5 shipping-rates-rb × ternary-bonsai

**Judged 100** in 28 minutes and 71 calls. Cleanest dependency handling of this model's six attempts at the task: current major version, `rake` scoped to a development group, country codes upcased before lookup.

First L5 cell for this model, and the assists are visibly active — `loop.satisfaction_blocked` ×25, `loop.periodic_gate` ×2, `loop.write_streak_corrected` ×3, `loop.gate` ×4. Those are exactly the mechanisms absent from every rung below, so the level boundary holds.

This task across all six rungs for ternary-bonsai: **54, 7, 100, 1, 100, 100.**

### Pass 2 — cell 36/76 — L5 cart-billing-go × ternary-bonsai

**Judged 97** in 16.3 minutes and 43 calls — the fastest clean pass this model has managed on the task. Tests compare `got.String() != want.String()`, which is correct (decimal string form is canonical) where its L3 cell compared the structs with `!=` and failed four right answers.

Docked 15 on logging for the same reason as its L4 cell: `Float64()` then `%.2f` prints `subtotal=44.98` for a true 44.9775. Two rungs apart, the same weakness — a log written to expose a rounding bug that rounds the number away.

Go column for this model: **90, 32, 33, 78, 97, 97.**

### Pass 2 — cell 37/76 — L5 orders-api-py × ternary-bonsai

**Judged 74.** `milestone-miss-45min` after 57 calls. The customer route crashes every request: the guard uses `self.path.split("/", 2)` (3 parts, passes) and the body then uses `self.path.split("/")` (4 parts) unpacked into three names — `ValueError: too many values to unpack`. Connection closes with no response, hence the check's `-> 0`.

Worth noting against the earlier cells: this run finally abandoned index slicing for splitting, which is the correct approach. The guard and the body just disagree about the maxsplit.

Its three red tests are **correct** — they hit the route and catch the crash. Scored 75 rather than penalised: unlike its L2 and L4 node cells, these tests are not the bug, they are what found it.

Python column for this model: **89, 61, 100, 93, 64, 74.**

### Pass 2 — cell 38/76 — L5 feed-pipeline-java × ternary-bonsai

**Judged 15.** `milestone-miss-30min` after 50 calls. Three compile errors from mixing opencsv's two reading APIs in one method: `reader.readNext()` throws a checked `CsvValidationException` and sits unguarded, while the `catch` written for that exception wraps the `for (String[] parts : reader)` iterator loop, which cannot throw it. The compiler rejects both halves — unreported exception at one site, never-thrown exception at the other — and a third error follows from `cols` possibly uninitialised.

The worker guard is correct here (`!rows.isEmpty()`), which is the exact thing its L1 cell got wrong as `!rows.length > 0`. It never gets to run.

Java column for this model: **0, 14, 94, 99, 80, 15.**

### Pass 2 — cell 39/76 — L5 handles-cli-node × ternary-bonsai

**Judged 89.** `budget-killed` at 60.5 minutes after 136 calls. Ten integration tests that are real and provably live — `execSync` against the CLI, exits 1 with the network removed.

Half the suite is dead, though. `test-runners.js` requires each test file to aggregate their counters, and `test-integration.js` ends with `process.exit()`. The runner dies inside its first `require`: `test-unit.js` and its 25 assertions never execute, and the runner's own `Results:` line never prints. Only `--- test-integration.js ---` appears in the output, and the exit code is still 0, so nothing signals the loss.

Fourth distinct way this model has broken a node test suite across six attempts: unawaited async bodies, exported-but-never-invoked modules, args joined into the path — and now a runner that exits inside the loop that loads its files.

### Pass 2 — cell 40/76 — L5 rust-toml-cli × ternary-bonsai

**Judged 100.** `budget-killed` at 60.5 minutes after 119 calls, with the work complete. 26 tests green, clean build, `map.get(*key)` with the deref right and `Value::Integer` / `Value::Boolean` spelled correctly.

**Rust column for this model, all six rungs: 98, 11, 11, 18, 16, 100.** Two clean runs at the extremes, four collapses between — every one of them a wrong name or a missing deref for the same `toml` API.

**ternary-bonsai is complete: all 36 cells across six rungs.**

| rung | ruby | go | python | java | node | rust | total |
|---|---|---|---|---|---|---|---:|
| L0 | 54 | 90 | 89 | 0 | 100 | 98 | 72 |
| L1 | 7 | 32 | 61 | 14 | 99 | 11 | 37 |
| L2 | 100 | 33 | 100 | 94 | 76 | 11 | 69 |
| L3 | 1 | 78 | 93 | 99 | 94 | 18 | 64 |
| L4 | 100 | 97 | 64 | 80 | 76 | 16 | 72 |
| L5 | 100 | 97 | 74 | 15 | 89 | 100 | 79 |

Highest rung is the top one, but the spread within every column swamps the differences between rows. Ruby runs 1 to 100; java 0 to 99; rust 11 to 100. The campaign's evidence on this model is that **which defects a run happens to produce decides the cell, and the rung does not predict them**.

### Pass 2 — cell 41/76 — L0 shipping-rates-rb × nemotron-elastic

**Judged 0.** `crashed-early` after 7 model calls and 30 seconds; `git status` clean, so the workspace is byte-identical to the seed. First cell for this model, and it matches qwen35's pure-proxy pattern exactly — quit inside a minute having written nothing. Throughput was fine at 137 tok/s, so this is not a speed problem.

### Pass 2 — cell 42/76 — L0 cart-billing-go × nemotron-elastic

**Judged 0.** `exited` after 7 model calls and 6.4 minutes, tree clean against the seed. Second nemotron cell, second one that wrote nothing at all — same call count as the first (7), so the model is stopping at the same point rather than failing at different places.

### Pass 2 — cell 43/76 — L0 orders-api-py × nemotron-elastic

**Judged 0.** `exited` after 5 model calls and 6.4 minutes. Only `__pycache__` bytecode differs from the seed — the model ran the existing tests and stopped. SQL injection still live.

Three nemotron cells, three zeros, 7 / 7 / 5 model calls. It is not attempting the work at the pure-proxy rung.

### Pass 2 — cell 44/76 — L0 feed-pipeline-java × nemotron-elastic

**Judged 0.** `exited` after 10 model calls and 4.1 minutes; only a `target/` build directory added, importer untouched. Fourth nemotron cell, fourth zero. It compiles the seed and stops — the same thing ternary-bonsai did on this task at L0.

### Pass 2 — cell 45/76 — L0 handles-cli-node × nemotron-elastic

**Judged 0.** `crashed-early` after **2 model calls** and 54 seconds. Fifth nemotron cell, fifth zero. Call counts across its L0 row so far: 7, 7, 5, 10, 2.

### Pass 2 — cell 46/76 — L0 rust-toml-cli × nemotron-elastic

**Judged 0.** `exited` after 3 model calls and 90 seconds with an **empty workspace** — not one file created. This task starts from nothing, so it is the only one where "did no work" and "wrote no files" are the same picture.

**nemotron-elastic L0 row complete: 0, 0, 0, 0, 0, 0 → 0.** Call counts 7, 7, 5, 10, 2, 3. Every cell under seven minutes, every workspace untouched.

**The pure-proxy rung across all four models: gemma4 91, ternary-bonsai 72, qwen35 4, nemotron 0.** Three of four do not engage with the task at all when cria only translates the wire.

### Pass 2 — cell 47/76 — L1 shipping-rates-rb × nemotron-elastic

**Judged 0.** `crashed-early` after 3 model calls and **12 seconds**. Workspace identical to the seed. First L1 cell for this model; the tool-call repair rung did not change the outcome on this task.

### Pass 2 — cell 48/76 — L1 cart-billing-go × nemotron-elastic

**Judged 6.** `exited` after 13 calls and 5.8 minutes. It wrote a correct `discounts.json` — all three codes, right rates — and never wired it in: `cart.go` contains no reference to the filename. The check `discounts_from_file` reads met, and its second half ("still builds and passes without the file") passes precisely because nothing depends on the file.

First non-zero deliverable from this model in seven cells, and it is an orphan artifact.

### Pass 2 — cell 49/76 — L1 orders-api-py × nemotron-elastic

**Judged 0.** `exited` after 7 model calls and one minute; every source file as the seed left it, SQL injection still live.

### Pass 2 — cell 50/76 — L1 feed-pipeline-java × nemotron-elastic

**Judged 0.** `crashed-early` after 3 model calls and 18 seconds.

### Pass 2 — cell 51/76 — L1 handles-cli-node × nemotron-elastic

**Judged 0.** `crashed-early` after 2 model calls and 30 seconds — same 2-call stop as its L0 cell on this task.

### Pass 2 — cell 52/76 — L1 rust-toml-cli × nemotron-elastic

**Judged 0.** `exited` after 4 model calls and 1.7 minutes, empty workspace.

**nemotron-elastic L1 row complete: 0, 6, 0, 0, 0, 0 → 1.** Against 0 at L0. Twelve cells, one non-zero deliverable — an orphaned `discounts.json` no code reads.

### Pass 2 — cell 53/76 — L2 shipping-rates-rb × nemotron-elastic

**Judged 0.** `crashed-early` after 4 model calls and 12 seconds. Level 2 hands the model cria's own tool menu lowered to shell — the rung that lifted ternary-bonsai from 7 to 100 on this exact task. No effect here.

### Pass 2 — cell 54/76 — L2 cart-billing-go × nemotron-elastic

**Judged 6.** `exited` after 8 calls and 2.2 minutes. Identical outcome to its L1 cell on this task: a correct `discounts.json` with all three codes, and `cart.go` containing no reference to it. Twice now, one rung apart, the model has produced exactly one artifact on this task and left it unwired.

### Pass 2 — cell 55/76 — L2 orders-api-py × nemotron-elastic

**Judged 45** — this model's first substantial score in fourteen cells. `exited` after 10 calls and 1.4 minutes, and in that time it rewrote `orders/db.py` properly: guarded `ALTER TABLE ADD COLUMN status`, `CREATE INDEX IF NOT EXISTS` on customer, bound parameters everywhere, and a `get_customer_orders` with a COALESCE'd total.

It never opened `app.py`. The route those queries exist to serve still 404s.

Same shape as its go cells, one layer up: it completes a single self-contained piece and never connects it. Three cells on two tasks now, all the same pattern.

### Pass 2 — cell 56/76 — L2 feed-pipeline-java × nemotron-elastic

**Judged 0.** `exited` after 11 calls and 7.3 minutes, importer untouched. Third attempt at this task from this model, third zero.

### Pass 2 — cell 57/76 — L2 handles-cli-node × nemotron-elastic

**Judged 0.** `exited` after 5 calls and 6.6 minutes, seed unchanged. Third attempt at this task, third zero.

### Pass 2 — cell 58/76 — L2 rust-toml-cli × nemotron-elastic

**Judged 18.** `exited` after 7 calls and 7.2 minutes. 17 compile errors, rooted in one wrong idea: the program reads its arguments with `env::argc()` and `env::argv[0]`, which is C, not Rust — `std::env::args()` is the real API. Nothing downstream can run.

Second structural mistake in the same cell: `tests` was written as a **1192-byte regular file**, where cargo requires a directory. There is no test target at all.

README is real (1692 B), so this is the model's first cell to deliver a written artifact that isn't an orphan.

**nemotron-elastic L2 row complete: 0, 6, 45, 0, 0, 18 → 12.** Rows so far: L0 0, L1 1, L2 12.

### Pass 2 — cell 59/76 — L3 shipping-rates-rb × nemotron-elastic

**Judged 0.** `crashed-early` after 5 model calls and 18 seconds. Fourth attempt at this task from this model; scores so far 0, 0, 0, 0.

### Pass 2 — cell 60/76 — L3 cart-billing-go × nemotron-elastic

**Judged 0.** `exited` after 6 calls and 6.5 minutes, tree clean. Its L1 and L2 cells on this task both produced an orphaned `discounts.json`; this one produced nothing at all. Go column: 0, 6, 6, 0.

### Pass 2 — cell 61/76 — L3 orders-api-py × nemotron-elastic

**Judged 50.** `exited` after 12 calls and 3.1 minutes. Its best cell yet and its first HTTP tests, undone by one truthiness bug:

```python
if not conn.execute("SELECT name FROM sqlite_master WHERE ... name='orders'"):
    conn.executescript(SCHEMA)
```

`conn.execute()` returns a Cursor, which is always truthy, so the CREATE branch never runs and a fresh database has no table. Six lines later the same check is written correctly with `cur.fetchone()` for the index. The verifier's migration probe passes because it starts from a seeded database; every test starts from a temp file and hits `no such table: orders`.

**Two of the four failing tests are the seed's own, which passed before this run.** This is the first nemotron cell to actively break something that was working.

`app.py` is still byte-for-byte the seed's, so the customer route 404s exactly as at L2 — the query layer exists, nothing routes to it.

### Pass 2 — cell 62/76 — L3 feed-pipeline-java × nemotron-elastic

**Judged 12.** `exited` after 11 calls and 10.1 minutes. Two independent structural errors:

1. `pom.xml` places a `<dependency>` block directly under `<project>` with no `<dependencies>` wrapper — Maven rejects the file outright.
2. Behind that, `Importer.java` imports `CSVSyntaxException` and `CSVStream`, neither of which exists in commons-csv. Verified by repairing the pom on a copy: the compile then fails on those symbols.

The dependency coordinates themselves are right, and the worker chunking is written correctly. Nothing reaches the compiler.

### Pass 2 — cell 63/76 — L3 handles-cli-node × nemotron-elastic

**Judged 0.** `crashed-early` after 2 model calls and 30 seconds — the third time this model has stopped at exactly 2 calls on this task (L0, L1, L3). Node column: 0, 0, 0, 0.

### Pass 2 — cell 64/76 — L3 rust-toml-cli × nemotron-elastic

**Judged 15.** `exited` after 7 calls and 1.7 minutes. The project is laid out as two nested copies of the same crate: a root `Cargo.toml` with no `src/` beside it, and `toml_dotted_key/` holding a byte-identical manifest plus the actual source. cargo fails at the root with "no targets specified".

Built the inner crate alone to see how far it gets: three errors — `?` used twice inside a `main()` that returns unit, and a call to `Value::walk()`, which does not exist. It also hardcodes `config.toml` while its own usage string promises a file argument.

**nemotron-elastic L3 row complete: 0, 0, 50, 12, 0, 15 → 13.** Rows: L0 0, L1 1, L2 12, L3 13.

### Pass 2 — cell 65/76 — L4 shipping-rates-rb × nemotron-elastic

**Judged 26** — this model's first passing check and its first self-written tests, in 153 calls over 30.8 minutes (`milestone-miss-30min`). Its most engaged cell by a wide margin: previous cells averaged 6 calls.

Everything is dead behind one wrong path. `rates.rb:6` reads `require 'vendor/europe'`; the gem was genuinely fetched and unpacked to `vendor/gems/europe/europe-0.0.28`. The dependency is present, the require names a path that does not exist, and every test errors before any code runs.

The README check passes on real content — all four zones, 8/8 rate values. `zone_for` is written sensibly against `Europe::Country#european?` with GB special-cased.

### Pass 2 — cell 66/76 — L4 cart-billing-go × nemotron-elastic

**Judged 28.** `milestone-miss-30min` after **147 calls** — second consecutive L4 cell with a call count 25× its L0–L3 average of 6.

**First cell where this model connected its own artifact to its own code.** Its L1 and L2 cells wrote a correct `discounts.json` that `cart.go` never mentioned; here `os.ReadFile("discounts.json")` reads it, with a documented fall-back to a default map.

Killed by two invented names on one line: `taxed.Quantize(2, decimal.ROUND_HALF_UP)`. Both belong to Python's `decimal` module, not shopspring's — the real API is `Round(int32)`. The subtotal is also still computed in float before reaching decimal, so the rounding would be wrong even if it compiled.

### Pass 2 — cell 67/76 — L4 orders-api-py × nemotron-elastic

**Judged 40.** `milestone-miss-30min` after 134 calls — third consecutive L4 cell running long where L0–L3 averaged 6 calls.

Two single-token defects:

- `CUSTOMER_RE = re.compile(r"^/customers/([^/]+)$")` — the `$` forbids the trailing `/orders`, so the route it exists to serve never matches. Third rung in a row where this model builds the query layer and cannot reach it.
- `_schema_version()` returns `SELECT COUNT(*) FROM sqlite_master WHERE type='table'` — a table count, not a version. On a seeded database that is ≥ 1, so the `if cur_version < 1` branch holding the `ALTER TABLE` never runs. `init_version` is defined twice, both bodies `pass`.

Its two seed tests are red again on `no such table`, repeating the L3 regression.

### Pass 2 — cell 68/76 — L4 feed-pipeline-java × nemotron-elastic

**Judged 19.** `milestone-miss-30min` after 68 calls. The pom is well-formed this time — a real improvement on its L3 cell, which put `<dependency>` outside `<dependencies>` — and the review is 428 words of accurate description. 27 compile errors from one wrong idea: `new CSVParser(new FileReader(...))`, treating opencsv's parser class as the reader class, then calling `setQuoteAll()` and `setAllowComments()` on it.

The review fails its check on locations only: 1 finding names a line where 2 are required, and it is written as a summary of changes rather than remaining problems.

**Incidental observation, not a defect in the run:** the model set the project's `artifactId` to `cria-shepherd`. The suite creates run workspaces under `runs/` inside this repo, so the harness's own directory name is visible in the model's cwd and it named the project after it. Nothing to fix for the campaign — the workspace is the seed plus its own writes — but worth recording that the model reads its path and will name things after it.

### Pass 2 — cell 69/76 — L4 handles-cli-node × nemotron-elastic

**Judged 40.** `milestone-miss-45min` after **267 model calls** — its most engaged cell of the campaign, against an L0–L3 average of 6.

The CLI is one identifier from working:

```js
const flags = ['--json', '--help'];
const args  = process.argv.slice(2);
const handle = args.find(arg => !flags.includes(arg));   // correct
const jsonMode = flags.includes('--json');               // wrong list
const help     = flags.includes('--help');               // wrong list
```

`flags` is the constant catalogue of known flags and always contains both, so `help` is always true and every invocation prints usage. The line above it uses `args` correctly — right variable once, wrong variable twice, three lines apart.

Its live test passes the check and is worth 30, not 100: it re-implements the fetch inline with a hardcoded expected holder address and never invokes `lookup.js`. It passed against a CLI that does nothing but print help — which is precisely the failure it was written to catch.

**nemotron L4 row so far: 26, 28, 40, 19, 40** — against 0, 1, 12, 13 for the rungs below.

### Pass 2 — cell 70/76 — L4 rust-toml-cli × nemotron-elastic

**Judged 20.** `milestone-miss-30min` after 77 calls. `toml = "0.10"` no longer resolves — crates.io offers 1.1.x — so nothing builds. Pinned a valid version on a copy to see what waits behind it: four more errors, all invented API (`toml::ValueTypeId`, `type_id()`, `as_i64()` on `Value`).

The README is the strongest artifact this model has produced in the campaign: 2785 B covering features, installation, build requirements and the test cases it intended. A `tests/fixture.toml` exists with no test file to use it.

**nemotron-elastic L4 row complete: 26, 28, 40, 19, 40, 20 → 29.**

| rung | ruby | go | python | java | node | rust | total | avg calls |
|---|---|---|---|---|---|---|---:|---:|
| L0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6 |
| L1 | 0 | 6 | 0 | 0 | 0 | 0 | 1 | 5 |
| L2 | 0 | 6 | 45 | 0 | 0 | 18 | 12 | 8 |
| L3 | 0 | 0 | 50 | 12 | 0 | 15 | 13 | 7 |
| L4 | 26 | 28 | 40 | 19 | 40 | 20 | **29** | **141** |

**The call count is the finding.** L0–L3 average 6–8 calls per cell; L4 averages 141. Level 4 is where cria begins refusing the model's claim to be finished, and this model stops quitting after thirty seconds and works for half an hour instead. Every cell in the row produced real code; none of it compiles, and the causes are the same class throughout — invented library names and single wrong identifiers.

### Pass 2 — cell 71/76 — L5 shipping-rates-rb × nemotron-elastic

**Judged 8.** `milestone-miss-30min` after 163 calls. The entire diff is one character:

```ruby
-    return surcharge if order_total > FREE_SHIPPING_THRESHOLD
+    return surcharge if order_total >= FREE_SHIPPING_THRESHOLD
```

It is a genuine fix — at-or-above is the boundary the task describes — and it turns the seed suite green. Nothing else was attempted: no express zone, README untouched, and a Gemfile declaring `countries` and `eu` that no source file requires.

Assists were firing heavily: `loop.compaction_reframed` ×80, `write_streak_corrected` ×27, `satisfaction_blocked` ×25, `periodic_gate` ×6. Half an hour of engagement for one character.

### Pass 2 — cell 72/76 — L5 cart-billing-go × nemotron-elastic

**Judged 24.** `milestone-miss-30min` after 78 calls. Discounts are wired properly this time — `os.Stat` guard, `os.ReadFile`, default map behind it.

The rounding fails on three invented names stacked together: an import of `github.com/shopspring/decimal/quantize`, a subpackage that does not exist, which breaks resolution before compilation. Stripping it on a copy exposes `taxed.Quantize(...)` and `decimal.RoundHalfUp` behind it — **the same two names its L4 cell on this task invented**, one rung earlier, spelled `ROUND_HALF_UP` there.

### Pass 2 — cell 73/76 — L5 orders-api-py × nemotron-elastic

**Judged 5.** `milestone-miss-30min` after 115 calls. The package cannot be imported at all:

```python
db = { 'connect': connect, 'init': init, ... }      # a plain dict
setattr(db, "DB_PATH", DB_PATH)                     # dicts take no attributes
```

`AttributeError: 'dict' object has no attribute 'DB_PATH'` fires at import, so the service never starts, the tests error out, and the verifier's own SQL-injection probe dies before it can run. It invented a module-like dict to stand in for a module, then treated it as one.

Its worst L4/L5 cell on this task despite 115 calls of engagement — the L4 attempt at least reached the point of serving a 404.

### Pass 2 — cell 74/76 — L5 feed-pipeline-java × nemotron-elastic

**Judged 22.** `milestone-miss-30min` after 74 calls. 39 compile errors from two invented class locations: `com.opencsv.CSVRecord` (that class belongs to commons-csv; opencsv has no such type) and `com.opencsv.exceptions.CsvParseException` (the real name is `CsvException`).

Its review passes the check with 199 words and 7 located findings, and what it contains is worth recording: **the findings are its own unfixed compile errors**, each with file and line — a `ConcurrentMap` type mismatch, a missing `java.util.concurrent` import. It diagnosed them correctly, wrote them up as the deliverable, and never fixed them.

### Pass 2 — cell 75/76 — L5 handles-cli-node × nemotron-elastic

**Judged 39.** `milestone-miss-30min` after 129 calls. **The first nemotron cell in the campaign whose program does the task's actual work**: `node bin/cli.js goose` returns the correct resolved address, holder address and handle count from the live API.

Everything around it is wrong:

- `--json` is parsed and then ignored; output stays human-readable.
- `--help` prints usage via a `usage()` helper that ends `process.exit(1)`, so asking for help is reported as failure.
- The seed's `lookup.js` was left untouched with `require('request')` in it — the model wrote a new `bin/cli.js` beside the old file instead of replacing it, so the banned dependency survives in source.
- `package.json` sets `"test": "jest"` with jest not installed, so no test runs at all.

### Pass 2 — cell 76/76 — L5 rust-toml-cli × nemotron-elastic — CAMPAIGN COMPLETE

**Judged 84.** `milestone-miss-60min` after 191 calls. **The only one of this model's 36 cells that builds and does what the task asks**: clean build, 3/3 lookups including `server.limits.max_conn → 250`, correct non-zero exit on a missing key.

Its tests are the sole broken part. They match on `toml::Value::Number`, a variant that does not exist — toml has `Integer` and `Float`. The invented variant appears only inside the `#[cfg(test)]` module and in a doc comment copying it, so `cargo build` is clean and `cargo test` fails. Same class of defect as its other 35 cells, confined this time to the part that does not ship.

---

## Walk — every L5 cell below 60% (2026-08-26)

Full report: [`l5-sub60-walk.md`](l5-sub60-walk.md).

Nine of twenty-four level-5 cells scored under 60. Each was read from its captured session — cria's event log, the prompts it sent, the workspace it left — asking only: what failed, and did cria cause or worsen it?

**Two cria defects found, both fixed and pushed.**

1. **The workspace-typo note was blind to a dropped letter.** `shipping-rates-rb × nemotron-elastic` typed `…-zpis1_t` for its real `…-zpsis1_t` and drew a correct refusal on **42 of its 115 coder calls**, second call to last, scoring 8. cria owns the sentence that ends this loop, and `_case_typo_of_workspace` only case-folded and collapsed dash/underscore. Third walk, third glyph class — the docstring records the other two. Replaced the enumerated classes with the property: one edit (Damerau-Levenshtein ≤ 1) on the segment that should have been the workspace.

2. **cria's survey outgrew the tool result it rides home on.** The ride-along note promises the survey only attaches to tools "whose own output is one bounded line" — true of writes and edits, false of `list_dir`, capped at 9,000 bytes on its own against a 6.6–10 KB survey. The harness cut the middle, `apply_survey` refused the remains, and the workspace view went stale for the rest of the run. **449 refused surveys across 11 cells**, tracking the harness's own cut markers nearly 1:1 (94/94, 46/47, 29/29, 17/17); eight are L5. Dropped `list_dir` from `_SURVEYABLE`.

**Six of the nine cells had no cria contribution at all** — invented library APIs, every one: opencsv's reader and parser classes swapped, `com.opencsv.CSVRecord` (a commons-csv class), Python's `Quantize`/`ROUND_HALF_UP` written in Go, `setattr` on a dict, `--help` tested against the wrong array.

**Two things deliberately left alone.** The retired "same action N times" detector stays retired: `cart-billing-go × nemotron-elastic` spent 30 of 60 calls in a read/test spiral, self-corrected out of it unaided at call 31 exactly as the removal note predicts, and then failed on `Quantize` — a defect no anti-spiral steer touches. And `[safety] external_dir_permission = none` refused 213 prompts' worth of `/tmp` scratch and dependency-source reads across the L5 cells; one of them was a model reading the toml crate's source to learn the API it went on to invent. Raising it to `read` is an operator decision with a real quality argument, not a bug.

Nothing in the walk showed cria destroying working code, mis-steering a model off a correct approach, or truncating content it needed. Both defects were cria failing to help, never cria doing harm.

---

## Re-run of the nine sub-60 L5 cells, after the truncation sweep

Same rung, same models, same tasks. The comparison is against each cell's own earlier score.

### gemma4 × rust-toml-cli — **51 → 100**

Clean build, 3/3 lookups, 3 tests green, README, in **3.3 minutes and 24 calls** against 28.4 minutes and 98 calls. The previous run never fixed `args[2]`/`args[3]` — `env::args()` yields three items — and spent 37 of its 60 turns inside its own test mocks. This one parses positionals by walking the argument list, so that confusion cannot arise.

cria's own instrumentation is visibly healthier: **2 survey rejections against 46**, and the log now names the reason — `entry-count-mismatch`, exactly what the two walkers reproduced independently and what my earlier truncation hypothesis got wrong.

### qwen35 × orders-api-py — **29 → 71**

Three of four checks met against one. Both defects that decided the previous attempt are gone: the app honours `sys.argv[2]` (the old run ignored it, so every test hit the shared `./orders.db` and saw accumulated rows), and the destructive `DELETE FROM orders` / `DROP TABLE IF EXISTS` that a cria steer talked the old run into never appears.

A third defect takes their place, and it is one this campaign has seen twice before in other cells: `db.py` declares `connect`/`init`/`create_order`/`get_customer_orders` with `path=DB_PATH`, and Python binds default arguments at import — so `serve()`'s `db.DB_PATH = path` never reaches them. `init()` creates the table in the test database while every query still reads `./orders.db`, and each request dies with `no such table: orders`. Eight HTTP tests red.

326 calls over the full hour.

### qwen35 × handles-cli-node — **58 → 93**

The hollow suite that defined the previous attempt is gone. That one scored 0 on `tests_incl_live`: a homemade runner called async test bodies without awaiting them, so all seven counted PASS before an assertion ran and the suite finished identically with the network removed. This one has eight tests that await, mock `globalThis.fetch` deliberately for most cases, and leave one that really reaches the service — verified by hand, exit 0 online and 1 offline.

What remains is one wrong exit code: `--help` prints correct, complete usage and then `process.exit(1)`. Third node cell in this campaign to lose a point that way.

279 calls, 38.7 minutes, ended on its own.

### nemotron-elastic × shipping-rates-rb — **8 → 9**

The same one-character diff as before (`>` → `>=`, which turns the seed suite green) and nothing else. What changed is where the turns went: **zero external-path refusals against 20**, so the workspace-path typo loop that consumed 42 of the previous run's 115 calls did not recur. It spent the recovered turns writing a Gemfile pinned to `countries ~> 0.9.3` — nine major versions behind what is installed — that no source file requires.

The loop is gone; the model still does not do the task.

### nemotron-elastic × cart-billing-go — **24 → 27**

The invented `github.com/shopspring/decimal/quantize` import — the unresolvable module that decided the previous attempt, and which a cria steer had talked that run into — does not appear. `discounts.json` is genuinely wired in this time via a guarded `loadDiscounts`.

It still does not build. `go.mod` pins `v1.2.3`, which does not exist, and the rounding is written against three more names shopspring does not have: `taxed.Quantize(decimal.QuantizeModeHalfUp, …)`, `decimal.NewFromFloat64`, and `float64(int64(quantized) / 100)` on a `decimal.Decimal`.

cria fired `loop.steer_invented_version` once — a guard aimed at exactly this — and two wheel-spin steers. Neither the fake subpackage nor a destructive steer recurred.

### nemotron-elastic × orders-api-py — **5 → 76**

The largest move of the re-run. The previous attempt built a dict named `db` and called `setattr` on it, so the package raised at import and every deliverable was unreachable — the service never started, and the verifier's own injection probe could not load the module. None of that recurs: the package imports, the service runs, and route, migration and injection all pass.

What is left is one wrong assumption in the test helper. `app.serve()` ends in `HTTPServer(...).serve_forever()`, which never returns; `_start_server` calls it directly and only then tries to start a thread for it. The suite hangs on its first test.

### nemotron-elastic × feed-pipeline-java — **22 → 16**

The two invented opencsv class names that decided the previous attempt — `com.opencsv.CSVRecord`, which belongs to commons-csv, and `com.opencsv.exceptions.CsvParseException` — are gone, and the pom is well-formed. It fails one step earlier instead: `opencsv:5.13.0` does not exist, and the only trace of it in the local repository is a pair of `.lastUpdated` markers, which is Maven recording a download that failed. 5.9 and 5.10 are there.

Its pom now declares **both** opencsv and commons-csv — the previous run's confusion written out as a dependency list rather than resolved.

The review is 458 words with 0 located findings: not one names a file and a line.

### nemotron-elastic × handles-cli-node — **39 → 33**

The CLI itself is complete and correct for the first time on this cell: `node cli.mjs goose` returns the address, the holder and the count from a live call, `--json` parses, `--help` works and a bad handle exits non-zero. All four behaviours, which no previous attempt managed.

Two deliverables were never attempted — no Dockerfile, and `test/cli.test.mjs` exists but package.json declares no test script to run it. And the seed's `lookup.js` is still on disk with `require('request')` in it, which is what the dependency check reads: the model wrote its CLI beside the old file rather than replacing it, the third time this campaign has seen that on this task.

**Instrument fix (#25), landed between passes.** `entrypoints()` tried a hardcoded list of `.js` names and never consulted package.json. This run set `"main": "cli.mjs"` and `"start": "node cli.mjs"`, and the verifier ran `node lookup.js` — the untouched seed — and recorded `no runnable entry point` while a working CLI sat beside it. The task's words are "turn the Ada Handle resolver into a command-line tool"; nothing in it names a filename, so failing the run for the spelling is failing it over a property the task never named. Discovery now reads `bin`, `main` and `scripts.start` first — package.json is where Node itself says the entry point is — then the README command, then the name list with `.mjs`/`.cjs` added. This row was re-verified: 0.0 → 1.0/4.0, annotated with `reverified`.

### ternary-bonsai × feed-pipeline-java — **15 → 12** (the row the timeout destroyed, re-run)

20 compile errors. `java.util.concurrent.*` is imported and `AtomicInteger`/`AtomicLong` live in `java.util.concurrent.atomic`, which a wildcard on the parent package does not reach. Verified on a copy that this is not a one-line miss: adding both imports leaves four more real errors — a `Map.get` called with the wrong arity, an assignment to a `final` field, a no-argument `remove()`.

The previous attempt at this cell was the campaign's worst cria incident: a green build at 17.4 minutes, destroyed after cria's stale `LATEST CHECK RESULTS` block asserted a compile error in 24 of 42 prompts for nine minutes after the coder's own `mvn clean compile` returned 0. **That did not recur** — the block now states its age and yields to the coder's newer result. This run never reached a green build to lose.

No REVIEW.md this time, against 607 words and 7 located findings before.
