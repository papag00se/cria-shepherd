# Language ladder — live report

**Generated** 2026-08-01 23:23:22 PDT by `python3 suite/ladder_report.py` · **do not hand-edit** — every value here is read from disk or `ps` at generation time.

Goal: **python** (`ada-handles`), 15 minutes per deliverable. A model repeats until it scores 4/4, then the next one starts.

Authority: `python3 suite/ladder_status.py` — 0 = language complete, 1 = work remains, 2 = a run is in flight.

## Now

**Nothing running.** Next action: **walk** `ada-handles_zaya1_codex_pon_1785649909` (capture `/home/jesse/.cria/calls/20260801T225200-019fc107-780c-70f3-b376-c6c37dda57a3`), then write `## ada-handles_zaya1_codex_pon_1785649909` into `docs/audits/ladder-walk.md`.

## Ladder

| # | model | params | architecture | kind | planner | tries | best | state |
|--:|:--|:--|:--|:--|:--|--:|:--:|:--|
| 1 | ternary-bonsai | 27B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 2 | gemma4 | 12B | `gemma4` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 3 | qwythos | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 4 | qwopus | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 5 | ornith | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 6 | mellum2 | 12B/A2.5B | `mellum 64/8` | moe | on | 5 | 2/4 | 🔁 ready to rerun |
| 7 | nemotron-elastic | 12B/A2B | `nemotron_h_moe 128/6` | moe | on | 1 | 4/4 | 🟢 PASSED |
| 8 | zaya1 | 8.4B/A760M | `zaya 16/1` | moe | on | 5 | 0/4 | 📖 needs walk |
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
| 08-01 17:15 | nemotron-elastic | 4/4 | budget-killed | 15m:4✓ 30m:4✓ 45m:4✓ 60m:4✓ | 291 | 114.1 | `ada-handles_nemotron-elastic_codex_pon_1785629694` |
| 08-01 18:17 | zaya1 | 0/4 | milestone-miss-15min | 15m:0✗ | 7 | 38.6 | `ada-handles_zaya1_codex_pon_1785633412` |
| 08-01 21:15 | zaya1 | 0/4 | milestone-miss-15min | 15m:0✗ | 7 | 47.6 | `ada-handles_zaya1_codex_pon_1785644114` |
| 08-01 21:37 | zaya1 | 0/4 | milestone-miss-15min | 15m:0✗ | 5 | 46.4 | `ada-handles_zaya1_codex_pon_1785645441` |
| 08-01 22:14 | zaya1 | 0/4 | milestone-miss-15min | 15m:0✗ | 7 | 48.4 | `ada-handles_zaya1_codex_pon_1785647676` |
| 08-01 22:51 | zaya1 | 0/4 | milestone-miss-15min | 15m:0✗ | 8 | 45.6 | `ada-handles_zaya1_codex_pon_1785649909` |

## Fixes landed during the ladder

```
f974ed8 fix(planner,contextfloor): spill searches, collapse repeats, and stop cutting
2b945b4 fix(contextfloor): the compaction digest was silently rewriting the task
ea4b8c2 fix(prompts,ladder): stop cria knowing this task, and block the model the rule meant to block
3e8e483 fix(planner): cria's ask goes LAST here too — the third instance of one ordering bug
75eddea fix(planner): retry a round that burns its whole budget THINKING — the critic has had this all along
429e35d fix(planner): the cut-off guard I shipped was wrong twice, and it shipped a false claim
5d2b119 fix(verify,selfcompact): close the fail-open default; the THIRD compaction path
dfcd83c refactor(selfcompact): ONE owner for the compaction request, not two that agree
36d2d4b fix(planner): a reply cut off at the output cap is not a finished turn
743405d fix(planner): tell the planner where the workspace is, and stop re-running its own calls
04a346b fix(loop): a turn that PASTED the file is not a claim that the step is done
c8692f7 fix(selfcompact): a briefing that quotes cria's own ask back is not a briefing
e72a0e9 fix(webfetch,loop,rumination): four faults the mellum2 full walks exposed
b8f6892 fix(urlgrounding): a path template's VARIABLE NAME is not part of the route
4b9c203 fix(planner): a plan step must not carry its own number — cria's framing states the position
```

---

Walk records — one per failed run, with the four questions and the verdict — are in [`ladder-walk.md`](ladder-walk.md).
