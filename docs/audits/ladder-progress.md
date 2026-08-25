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

## Cells — 69 / 144

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
| qwen35 | L5 ASSISTS_ENAB | **100** | **63** | **29** | **96** | · | · | 72 |
| ternary-bonsai | L0 pure proxy | · | · | · | · | · | · | · |
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

_updated 2026-08-25 04:33_
