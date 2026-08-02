# Language ladder — live report

**Generated** 2026-08-02 05:29:54 PDT by `python3 suite/ladder_report.py` · **do not hand-edit** — every value here is read from disk or `ps` at generation time.

Goal: **python** (`ada-handles`), 15 minutes per deliverable. A model repeats until it scores 4/4, then the next one starts.

Authority: `python3 suite/ladder_status.py` — 0 = language complete, 1 = work remains, 2 = a run is in flight.

## Now

**RUNNING — mellum2**, 56 min elapsed.

| next checkpoint | at | must hold |
|:--|--:|:--|
| milestone 4 | 60 min | 4/4 |

**Measured just now** (verifier run against a copy of the live workspace): **3/4**

| deliverable | | detail |
|:--|:--:|:--|
| unit_tests | 🔴 | 4 failed, 1 passed in 0.29s |
| live_test | 🟢 | in-file live test: 1 passed with network, fails without (provably live) |
| resolver_cli | 🟢 | resolve.py goose → address+holder+count |
| readme | 🟢 | README.md covers install/run/tests: True |

## Ladder

| # | model | params | architecture | kind | planner | tries | best | state |
|--:|:--|:--|:--|:--|:--|--:|:--:|:--|
| 1 | ternary-bonsai | 27B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 2 | gemma4 | 12B | `gemma4` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 3 | qwythos | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 4 | qwopus | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 5 | ornith | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 6 | mellum2 | 12B/A2.5B | `mellum 64/8` | moe | on | 10 | 3/4 | 🔵 RUNNING |
| 7 | nemotron-elastic | 12B/A2B | `nemotron_h_moe 128/6` | moe | on | 1 | 4/4 | 🟢 PASSED |
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
| 08-01 17:15 | nemotron-elastic | 4/4 | budget-killed | 15m:4✓ 30m:4✓ 45m:4✓ 60m:4✓ | 291 | 114.1 | `ada-handles_nemotron-elastic_codex_pon_1785629694` |
| 08-01 23:25 | mellum2 | 3/4 | exited | 15m:3✓ | 195 | 165.4 | `ada-handles_mellum2_codex_pon_1785651890` |
| 08-01 23:56 | mellum2 | 3/4 | exited | — | 111 | 178.3 | `ada-handles_mellum2_codex_pon_1785653778` |
| 08-02 00:12 | mellum2 | 0/4 | milestone-miss-15min | 15m:0✗ | 145 | 171.4 | `ada-handles_mellum2_codex_pon_1785654712` |
| 08-02 00:33 | mellum2 | 3/4 | milestone-miss-60min | 15m:1✓ 30m:2✓ 45m:3✓ 60m:3✗ | 375 | 156.8 | `ada-handles_mellum2_codex_pon_1785656001` |
| 08-02 01:37 | mellum2 | 1/4 | exited | — | 40 | 186.4 | `ada-handles_mellum2_codex_pon_1785659842` |
| 08-02 01:44 | mellum2 | 0/4 | milestone-miss-15min | 15m:0✗ | 68 | 160.3 | `ada-handles_mellum2_codex_pon_1785660278` |
| 08-02 02:04 | mellum2 | 3/4 | milestone-miss-60min | 15m:3✓ 30m:3✓ 45m:3✓ 60m:3✗ | 219 | 159.4 | `ada-handles_mellum2_codex_pon_1785661463` |
| 08-02 03:08 | mellum2 | 1/4 | milestone-miss-30min | 15m:1✓ 30m:1✗ | 144 | 158.9 | `ada-handles_mellum2_codex_pon_1785665296` |
| 08-02 03:42 | mellum2 | 0/4 | milestone-miss-15min | 15m:0✗ | 111 | 173.9 | `ada-handles_mellum2_codex_pon_1785667319` |
| 08-02 04:00 | mellum2 | 3/4 | exited | 15m:1✓ | 159 | 164.5 | `ada-handles_mellum2_codex_pon_1785668419` |

## Fixes landed during the ladder

```
6f716ef fix(replan): narrow the artifact protection I added — it was protecting junk
eb9a1fe fix(probeparse): my stdlib fix was incomplete — cover every parser, not just pytest
8c85646 fix(replan): the noise judge may not delete a step that AUTHORS a file
151435b obs(loop): log WHICH steps the noise judge deleted, not just how many
69efeaf fix(probeparse): stop pointing the coder at Python's standard library
78d5d05 fix(replan): refuse a re-derived step that names a CRIA TOOL as the product's code
7bbf886 feat(verify): show the critic when a step's quoted values are absent from the file
895651a fix(loop): the unexecuted-write guard could not see a pasted README
a807a2d chore(ladder): reset mellum2 and zaya1 attempt counts; record the zaya1 a5 walk
f974ed8 fix(planner,contextfloor): spill searches, collapse repeats, and stop cutting
2b945b4 fix(contextfloor): the compaction digest was silently rewriting the task
ea4b8c2 fix(prompts,ladder): stop cria knowing this task, and block the model the rule meant to block
3e8e483 fix(planner): cria's ask goes LAST here too — the third instance of one ordering bug
75eddea fix(planner): retry a round that burns its whole budget THINKING — the critic has had this all along
429e35d fix(planner): the cut-off guard I shipped was wrong twice, and it shipped a false claim
```

---

Walk records — one per failed run, with the four questions and the verdict — are in [`ladder-walk.md`](ladder-walk.md).
