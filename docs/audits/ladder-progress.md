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
