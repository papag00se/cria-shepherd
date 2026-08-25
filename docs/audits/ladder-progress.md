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
