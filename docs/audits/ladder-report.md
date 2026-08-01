# Language ladder — live report

**Generated** 2026-08-01 11:41:33 PDT by `python3 suite/ladder_report.py` · **do not hand-edit** — every value here is read from disk or `ps` at generation time.

Goal: **python** (`ada-handles`), 15 minutes per deliverable. A model repeats until it scores 4/4, then the next one starts.

Authority: `python3 suite/ladder_status.py` — 0 = language complete, 1 = work remains, 2 = a run is in flight.

## Now

**Nothing running.** Next action: **run** `gemma4` (attempt 1).

## Ladder

| # | model | params | architecture | kind | planner | tries | best | state |
|--:|:--|:--|:--|:--|:--|--:|:--:|:--|
| 1 | ternary-bonsai | 27B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 2 | gemma4 | 12B | `gemma4` | dense | off | 0 | — | ⬜ not started |
| 3 | qwythos | 9B | `qwen35` | dense | off | 0 | — | ⬜ not started |
| 4 | qwopus | 9B | `qwen35` | dense | off | 0 | — | ⬜ not started |
| 5 | ornith | 9B | `qwen35` | dense | off | 0 | — | ⬜ not started |
| 6 | mellum2 | 12B/A2.5B | `mellum 64/8` | moe | on | 0 | — | ⬜ not started |
| 7 | nemotron-elastic | 12B/A2B | `nemotron_h_moe 128/6` | moe | on | 0 | — | ⬜ not started |
| 8 | zaya1 | 8.4B/A760M | `zaya 16/1` | moe | on | 0 | — | ⬜ not started |
| 9 | fabliq | 8B/A1B | `lfm2moe 32/4` | moe | on | 0 | — | ⬜ not started |

## Attempts

| started | model | score | terminal | milestones | calls | tok/s | run id |
|:--|:--|:--:|:--|:--|--:|--:|:--|
| 08-01 11:13 | ternary-bonsai | 4/4 | exited | 15m:2✓ | 54 | 39.7 | `ada-handles_ternary-bonsai_codex_poff_1785607985` |

## Fixes landed during the ladder

```
91d44ba feat(suite): ladder-report.md — a GENERATED follow-along report
4379943 fix(suite,docs): fabliq is an MoE — the ladder's kinds now come from the GGUF headers
bc29023 feat(suite): the language ladder — one model at a time, 15 min per deliverable
1d49456 fix(prompts): the steer author wrote code it cannot run — describe the change instead
53cae4a fix(dirguard,prompts): cria RECOMMENDED the escape from its own workspace bound
1b97228 fix(suite): preflight now catches a PREVIOUS run's install still on sys.path
c301d1d fix(suite): the status oracle told me to redo finished work, and saw a run that wasn't there
8fa6d71 feat(suite): phase1_status.py — ground truth for the matrix, read from disk not from narration
8fd698d fix(probediscovery): the gate's `go test` could report a pass it never ran
2eaf2e1 fix(loop): bound the judge's inspection by SIZE, not only by round count
615a6fc feat(suite): the remaining three task categories, a preflight check, and phase-1 scoping
9c9f022 feat(suite): task battery documented and raised to comparable complexity
4a0afe7 feat(suite): seeded task categories — resolve failing tests, fix a reported bug, write missing tests
298a145 feat(suite): one task per supported language — handles-{go,rust,node,ruby,php,java}
74a9700 fix(suite,probeparse): score with cria's real parser; parse the test-runner locations cria was blind to
```

---

Walk records — one per failed run, with the four questions and the verdict — are in [`ladder-walk.md`](ladder-walk.md).
