# Language ladder — live report

**Generated** 2026-08-01 17:14:34 PDT by `python3 suite/ladder_report.py` · **do not hand-edit** — every value here is read from disk or `ps` at generation time.

Goal: **python** (`ada-handles`), 15 minutes per deliverable. A model repeats until it scores 4/4, then the next one starts.

Authority: `python3 suite/ladder_status.py` — 0 = language complete, 1 = work remains, 2 = a run is in flight.

## Now

**Nothing running.** Next action: **run** `nemotron-elastic` (attempt 1).

## Ladder

| # | model | params | architecture | kind | planner | tries | best | state |
|--:|:--|:--|:--|:--|:--|--:|:--:|:--|
| 1 | ternary-bonsai | 27B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 2 | gemma4 | 12B | `gemma4` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 3 | qwythos | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 4 | qwopus | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 5 | ornith | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 6 | mellum2 | 12B/A2.5B | `mellum 64/8` | moe | on | 5 | 2/4 | ⛔ BLOCKED |
| 7 | nemotron-elastic | 12B/A2B | `nemotron_h_moe 128/6` | moe | on | 0 | — | ⬜ not started |
| 8 | zaya1 | 8.4B/A760M | `zaya 16/1` | moe | on | 0 | — | ⬜ not started |
| 9 | fabliq | 8B/A1B | `lfm2moe 32/4` | moe | on | 0 | — | ⬜ not started |

## Attempts

| started | model | score | terminal | milestones | calls | tok/s | run id |
|:--|:--|:--:|:--|:--|--:|--:|:--|
| 08-01 11:13 | ternary-bonsai | 4/4 | exited | 15m:2✓ | 54 | 39.7 | `ada-handles_ternary-bonsai_codex_poff_1785607985` |
| 08-01 11:44 | gemma4 | 4/4 | exited | 15m:3✓ | 230 | 55.1 | `ada-handles_gemma4_codex_poff_1785609848` |
| 08-01 12:14 | qwythos | 4/4 | exited | — | 108 | 71.9 | `ada-handles_qwythos_codex_poff_1785611662` |
| 08-01 12:28 | qwopus | 4/4 | exited | — | 39 | 73.7 | `ada-handles_qwopus_codex_poff_1785612491` |
| 08-01 12:36 | ornith | 4/4 | exited | — | 63 | 73.3 | `ada-handles_ornith_codex_poff_1785612980` |
| 08-01 12:45 | mellum2 | 2/4 | exited | 15m:1✓ | 114 | 144.7 | `ada-handles_mellum2_codex_pon_1785613520` |
| 08-01 14:41 | mellum2 | 0/4 | milestone-miss-15min | 15m:0✗ | 81 | 160.4 | `ada-handles_mellum2_codex_pon_1785620496` |
| 08-01 16:01 | mellum2 | 0/4 | milestone-miss-15min | 15m:0✗ | 91 | 166.4 | `ada-handles_mellum2_codex_pon_1785625253` |
| 08-01 16:19 | mellum2 | 1/4 | milestone-miss-30min | 15m:1✓ 30m:1✗ | 225 | 142.9 | `ada-handles_mellum2_codex_poff_1785626379` |
| 08-01 16:55 | mellum2 | 0/4 | milestone-miss-15min | 15m:0✗ | 101 | 145.6 | `ada-handles_mellum2_codex_pon_1785628543` |

## Fixes landed during the ladder

```
9b52224 fix(loop): cria withheld its correction on a premise false 73% of the time
aa464fd fix(loop): an authoring step must stop saying "Write X" once X exists and is failing
af69c12 docs(ladder)+fix(execcheck): walk mellum2 attempt 3; a test file is not a program
c4d955c feat(suite): shout when the ladder is idle
484d75d fix(suite,docs): a package named after cria's own tool poisoned a run for nine days
0c0a6d1 docs(ladder): walk mellum2 attempt 2 — 0/4, model wall, and a correction
05b01a7 feat(execcheck): live execution check — corroborate three sources, run, never block
b46dedd docs(ladder): walk mellum2 2/4 — the completion brake asks one fused question
81ab891 docs(ladder): ornith 4/4 — five for five on dense, planner off
051dc13 docs(ladder): qwopus 4/4 in 6.5 min — four dense passes, all first attempt
2d984fd docs(ladder): qwythos 4/4 in 12.7 min — third dense pass, first attempt
3897a8d docs(ladder): ternary-bonsai and gemma4 both 4/4; record the sampling finding as untested
7259203 fix(suite): the runner sets each model's sampling — it was missed 26 times running
91d44ba feat(suite): ladder-report.md — a GENERATED follow-along report
4379943 fix(suite,docs): fabliq is an MoE — the ladder's kinds now come from the GGUF headers
```

---

Walk records — one per failed run, with the four questions and the verdict — are in [`ladder-walk.md`](ladder-walk.md).
