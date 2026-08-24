# Goal — the engagement ladder: six levels, measured one at a time

## The one truth

```
python3 suite/engagement_status.py
```

That command is the completion status. Not a checklist, not a message, not a plan. Run it at the start of every turn and after every unit of work. The goal is DONE when it prints `LADDER COMPLETE` and not before.

Its contract, and it is the first thing to build:

```
BUILD    tests/test_engagement_levels.py .......... PASS|FAIL
CELLS    <n>/144 run          (distinct level x model x task rows in suite/results/results.jsonl)
JUDGED   <n>/144 judged       (usefulness verdicts recorded)
LADDER COMPLETE               (only when all three are satisfied)
```

Exit non-zero while anything remains. Everything else in this document is how to make that command print `LADDER COMPLETE`.

## Why this exists

The suite has compared two arms — `[engagement] drive` true and false — and called the false one "the model on its own". It never was. Counting events inside the 24 baseline run windows of 2026-08-24:

| ran in the "assists off" arm | fires |
|---|---:|
| tool-menu curation | 1,011 |
| write-proxy tool translation | 980 |
| indicator stripping | 991 |
| reasoning-call repair | 333 |
| context focus-trim | 514 |
| harness-compaction reframing | 136 |
| context floor (drop-oldest) | 54 |

`config.py` justified this by arguing that a true zero cannot exchange a message, because Codex speaks the Responses API and llama.cpp does not. That is true of **wire-format translation only**. Tool curation, context surgery, template repair and dialect recovery were grandfathered in behind it, and have therefore been present in every arm of every comparison ever run. The one time a piece of this layer was checked, it was destroying 24% of every command result for a whole campaign (`writeproxy.note_harness_cuts`).

So: what the other 95% of the codebase is worth has never been measured. This goal measures it.

## The six levels

Cumulative and ordered. Level N implies every level below it. No configuration can express a gap.

| level | name | what it turns on |
|---|---|---|
| 0 | *(pure proxy)* | Responses↔chat wire translation and nothing else. No indicators, no tool changes, no context changes, no repairs, no loop. |
| 1 | `TOOL_CALL_FIXES` | Making the many ways models emit tool calls homogeneous: template repair, tool-call dialect recovery, malformed-history repair, fenced-JSON parsing, tool-name normalisation. **Does not alter the toolset the harness offered. cria provides no tools of its own. No lowering to shell.** |
| 2 | `SIMPLE_TOOLS` | cria's own tool menu, and lowering those tools to shell and representing them back. Minor context edits needed to keep those calls coherent belong here. |
| 3 | `CONTEXT_FIXES` | cria's context surgery, the parts that are not assists: the context floor, focus-trim, repeat-dedup, ledger-dedup, harness-compaction reframing. |
| 4 | `DONE_REFUSALS_ENABLED` | The refusal of a completion CLAIM: the model tries to finish, cria says "no, `<this>` is still outstanding". done-critic, the completion probe, `task_complete` handling, and the disk-confirmation brake on an approving verdict. |
| 5 | `ASSISTS_ENABLED` | Everything else, and any context work an assist needs to do its job: steers, periodic gates, the periodic satisfaction check, every detector, the planner. |

### The dividing line at 4 and 5 is the TRIGGER, not the machinery

The same judge and the same gate code are reached from two directions. What decides the level is who started it:

- **the model tried to stop** → level 4
- **a turn counter fired** → level 5

So `done_critic` and `completion_probe` are level 4; `satisfaction_check`, `satisfaction_gap_named` and `periodic_gate` are level 5, even though they call into the same functions. Gate at the call site.

`satisfaction_confirm` — the brake that checks an approving verdict against the fresh on-disk listing — rides with whichever path invokes it. It must exist at level 4, or level 4 can approve a completion whose named deliverable is not on disk.

### Measured sizes, so a level that goes quiet is visible as a bug

From the 24-cell run of 2026-08-24, per level, across ~1,000 model turns:

| level | fires |
|---|---:|
| 1 | ~333 |
| 2 | ~2,000 |
| 3 | ~2,100 |
| 4 | ~71 (done-critic 25, completion probe 35, `task_complete` 11) |
| 5 | ~600 |

Level 4 is thin by design. If it fires in the thousands, something from level 5 has leaked into it.

Do not reuse the figure "1,048 completion refusals" from earlier reporting. `loop.satisfaction_blocked` counts cria SKIPPING its own check — 841 of those 1,048 were `why: gate-red` — and is not an intervention at all.

## Planner on and planner off behave identically

Levels 0–4 must be indistinguishable with the planner on and off. Plan-off already runs as a synthetic single-item plan through the same `_drive_single_item`, and `plan_off` branches at only five points in `loop.py` (2565, 3413, 3516, 3543, 3905), none of which is in levels 0–4.

**The rule: the level is checked ONCE, where the capability is invoked, never inside a plan-on/plan-off branch.** A level gate written into one side of such a branch is the defect this project has repeatedly paid for.

The one honest exception is at level 5: replanning and step re-derivation exist only when there are steps, so plan-on has two assists plan-off cannot have. Say so in the config docstring; do not paper over it.

## Phase 1 — build

`[engagement] level = 0..5` in `~/.cria/cria.toml`, replacing `drive`. One ordered integer, with the five names above as derived read-only properties, so an impossible combination cannot be configured. Keep `drive` reading as `level >= 5` for one release so nothing else breaks.

Every model-facing string stays in `cria/prompts/*.txt`. No new environment variables — this is behaviour configuration, not a secret and not environment-varying.

Then gate one capability at a time, lowest level first, each with its own test, each committed and pushed separately, restarting `cria.service` after each.

`tests/test_engagement_levels.py` must, for every level 0–5 and for the planner both on and off:

1. assert the mechanisms belonging to that level and below are reachable;
2. assert the mechanisms above it are not;
3. assert the set of mechanisms that fired is the same with the planner on and off, for levels 0–4.

## Phase 2 — run

144 cells: 6 levels x 4 models x 6 tasks, planner off, the same six tasks and the same `p4` prompt revision as the 2026-08-24 run, so the level-5 column is comparable to it.

`battery_run.py` sets the level per cell exactly as it sets the arm today, and records it in the row's note so `engagement_status.py` can count it. Add a `level` field to the results row.

Expect level 0 and level 1 cells to die in seconds on some models — a bare assistant turn is a structural 400 on the gemma template, and one malformed historical tool call 500s every later turn. **That is the measurement, not a bug to fix.** Record it; do not repair it upward into level 0.

Run grouped by model so the GPU swaps as few times as possible. Preserve every run's evidence.

## Phase 3 — judge

Every cell gets a usefulness verdict, by the same worklist and the same fixed rubric as the battery:

```
python3 suite/usefulness.py pending --arm LADDER
python3 suite/usefulness.py emit <run_id>
python3 suite/usefulness.py record <run_id> < verdict.json
```

The strict verifier is not the measure. It credits tests that test a copy of themselves and scores a complete program as zero for one wrong symbol; both errors were confirmed in the 2026-08-24 run. **The trigger to judge a cell is that cell finishing.** The worklist is the memory, not the agent's.

## The progress file

`docs/audits/ladder-progress.md`, rewritten after every unit of work so the operator can follow along without asking. It carries:

- the build table: which levels are gated, which tests pass;
- the cell table: level x model x task, strict and judged;
- the headline the whole exercise is for — **what each level adds over the one below it**, judged, per model.

This file is for reading. It is not the completion status; `engagement_status.py` is.

## Rules

- One unit of work at a time; commit and push each.
- Restart `cria.service` after landing a change, and say what went live.
- Never edit `suite/tasks/*/prompt.txt`. Never make a task easier to pass.
- Never delete run evidence.
- No mitigations, fallbacks or band-aids. Find the upstream fix.
- Do not report a level as built because the code was written. It is built when its test passes.
- Never say what you are about to do. Do it, then say what happened.

## Done

`python3 suite/engagement_status.py` prints `LADDER COMPLETE`. Then, and only then, report:

**What each of the six layers is worth, measured, per model — and which of them are worth nothing.**

---

## A note on the name

The completion command is `suite/engagement_status.py`. It is NOT `suite/ladder_status.py` — that
name was already taken by the LANGUAGE ladder (`docs/goals/language-ladder-goal.md`), whose truth
this goal must not disturb. The `/goal` prompt that started this work named `ladder_status.py`; the
collision was found on the first turn and the engagement ladder took the free name instead.
