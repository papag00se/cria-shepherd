# Language ladder — live report

**Generated** 2026-08-01 12:32:59 PDT by `python3 suite/ladder_report.py` · **do not hand-edit** — every value here is read from disk or `ps` at generation time.

Goal: **python** (`ada-handles`), 15 minutes per deliverable. A model repeats until it scores 4/4, then the next one starts.

Authority: `python3 suite/ladder_status.py` — 0 = language complete, 1 = work remains, 2 = a run is in flight.

## Now

**RUNNING — qwopus**, 5 min elapsed.

| next checkpoint | at | must hold |
|:--|--:|:--|
| milestone 1 | 15 min | 1/4 |

**Measured just now** (verifier run against a copy of the live workspace): **3/4**

| deliverable | | detail |
|:--|:--:|:--|
| unit_tests | 🔴 | 16 passed, 1 error in 5.00s |
| live_test | 🟢 | live_test.py: real resolution (addr1+stake1 present) |
| resolver_cli | 🟢 | handle_resolver.py goose → address+holder+count |
| readme | 🟢 | README.md covers install/run/tests: True |

## Ladder

| # | model | params | architecture | kind | planner | tries | best | state |
|--:|:--|:--|:--|:--|:--|--:|:--:|:--|
| 1 | ternary-bonsai | 27B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 2 | gemma4 | 12B | `gemma4` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 3 | qwythos | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 4 | qwopus | 9B | `qwen35` | dense | off | 0 | — | 🔵 RUNNING |
| 5 | ornith | 9B | `qwen35` | dense | off | 0 | — | ⬜ not started |
| 6 | mellum2 | 12B/A2.5B | `mellum 64/8` | moe | on | 0 | — | ⬜ not started |
| 7 | nemotron-elastic | 12B/A2B | `nemotron_h_moe 128/6` | moe | on | 0 | — | ⬜ not started |
| 8 | zaya1 | 8.4B/A760M | `zaya 16/1` | moe | on | 0 | — | ⬜ not started |
| 9 | fabliq | 8B/A1B | `lfm2moe 32/4` | moe | on | 0 | — | ⬜ not started |

## Attempts

| started | model | score | terminal | milestones | calls | tok/s | run id |
|:--|:--|:--:|:--|:--|--:|--:|:--|
| 08-01 11:13 | ternary-bonsai | 4/4 | exited | 15m:2✓ | 54 | 39.7 | `ada-handles_ternary-bonsai_codex_poff_1785607985` |
| 08-01 11:44 | gemma4 | 4/4 | exited | 15m:3✓ | 230 | 55.1 | `ada-handles_gemma4_codex_poff_1785609848` |
| 08-01 12:14 | qwythos | 4/4 | exited | — | 108 | 71.9 | `ada-handles_qwythos_codex_poff_1785611662` |

## Fixes landed during the ladder

```
2d984fd docs(ladder): qwythos 4/4 in 12.7 min — third dense pass, first attempt
3897a8d docs(ladder): ternary-bonsai and gemma4 both 4/4; record the sampling finding as untested
7259203 fix(suite): the runner sets each model's sampling — it was missed 26 times running
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
```

---

Walk records — one per failed run, with the four questions and the verdict — are in [`ladder-walk.md`](ladder-walk.md).
