# Language ladder — live report

**Generated** 2026-08-04 09:26:35 PDT by `python3 suite/ladder_report.py` · **do not hand-edit** — every value here is read from disk or `ps` at generation time.

Goal: **python** (`ada-handles`), 15 minutes per deliverable. A model repeats until it scores 4/4, then the next one starts.

Authority: `python3 suite/ladder_status.py` — 0 = language complete, 1 = work remains, 2 = a run is in flight.

## Now

**RUNNING — gemma4**, 10 min elapsed.

| next checkpoint | at | must hold |
|:--|--:|:--|
| milestone 1 | 15 min | 1/4 |

**Measured just now** (verifier run against a copy of the live workspace): **2/4**

| deliverable | | detail |
|:--|:--:|:--|
| unit_tests | 🔴 | 1 failed, 5 passed in 0.72s |
| live_test | 🟢 | in-file live test: 2 passed with network, fails without (provably live) |
| resolver_cli | 🔴 | -m ada-handles goose papagoose: exit=1 |
| readme | 🟢 | README.md covers install/run/tests: True |

## Ladder

| # | model | params | architecture | kind | planner | tries | best | state |
|--:|:--|:--|:--|:--|:--|--:|:--:|:--|
| 1 | ternary-bonsai | 27B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 2 | gemma4 | 12B | `gemma4` | dense | off | 1 | 4/4 | 🔵 RUNNING |
| 3 | qwythos | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 4 | qwopus | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 5 | ornith | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 6 | mellum2 | 12B/A2.5B | `mellum 64/8` | moe | off | 22 | 4/4 | 🟢 PASSED |
| 7 | nemotron-elastic | 12B/A2B | `nemotron_h_moe 128/6` | moe | on | 1 | 4/4 | 🟢 PASSED |
| 8 | fabliq | 8B/A1B | `lfm2moe 32/4` | moe | on | 6 | 1/4 | 📖 needs walk |
| 9 | zaya1 | 8.4B/A760M | `zaya 16/1` | moe | off | 1 | 0/4 | ⛔ BLOCKED |

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
| 08-02 04:29 | mellum2 | 3/4 | milestone-miss-60min | 15m:2✓ 30m:3✓ 45m:3✓ 60m:3✗ | 479 | 166.9 | `ada-handles_mellum2_codex_pon_1785670156` |
| 08-02 05:32 | mellum2 | 1/4 | milestone-miss-30min | 15m:1✓ 30m:1✗ | 156 | 155.1 | `ada-handles_mellum2_codex_pon_1785673911` |
| 08-02 06:05 | mellum2 | 1/4 | milestone-miss-30min | 15m:0✗ 30m:1✗ | 204 | 163.4 | `ada-handles_mellum2_codex_pon_1785675899` |
| 08-02 06:42 | mellum2 | 1/4 | milestone-miss-60min | 15m:1✓ 30m:3✓ 45m:3✓ 60m:1✗ | 279 | 159.3 | `ada-handles_mellum2_codex_pon_1785678150` |
| 08-02 07:45 | mellum2 | 2/4 | exited | — | 63 | 189.4 | `ada-handles_mellum2_codex_pon_1785681911` |
| 08-02 07:51 | mellum2 | 2/4 | milestone-miss-45min | 15m:2✓ 30m:2✓ 45m:2✗ | 155 | 149.6 | `ada-handles_mellum2_codex_pon_1785682267` |
| 08-02 08:39 | mellum2 | 3/4 | exited | — | 53 | 175.0 | `ada-handles_mellum2_codex_poff_1785685170` |
| 08-02 08:49 | mellum2 | 3/4 | exited | — | 161 | 168.0 | `ada-handles_mellum2_codex_poff_1785685763` |
| 08-02 09:03 | mellum2 | 2/4 | exited | — | 88 | 173.6 | `ada-handles_mellum2_codex_poff_1785686596` |
| 08-02 10:52 | mellum2 | 2/4 | exited | 15m:1✓ | 166 | 162.9 | `ada-handles_mellum2_codex_poff_1785693138` |
| 08-02 16:43 | mellum2 | 2/4 | exited | — | 34 | 165.7 | `ada-handles_mellum2_codex_poff_1785714194` |
| 08-02 17:52 | mellum2 | 4/4 | exited | 15m:4✓ | 111 | 173.5 | `ada-handles_mellum2_codex_poff_1785718325` |
| 08-02 18:13 | zaya1 | 0/4 | milestone-miss-15min | 15m:0✗ | 13 | 49.8 | `ada-handles_zaya1_codex_pon_1785719577` |
| 08-02 18:43 | fabliq | 0/4 | milestone-miss-15min | 15m:0✗ | 267 | 218.4 | `ada-handles_fabliq_codex_pon_1785721353` |
| 08-02 19:59 | fabliq | 0/4 | milestone-miss-15min | 15m:0✗ | 255 | 268.9 | `ada-handles_fabliq_codex_pon_1785725976` |
| 08-02 21:41 | fabliq | 1/4 | milestone-miss-30min | 15m:1✓ 30m:1✗ | 280 | 245.4 | `ada-handles_fabliq_codex_pon_1785732102` |
| 08-03 08:36 | fabliq | 0/4 | crashed-early | — | 21 | 264.9 | `ada-handles_fabliq_codex_pon_1785771361` |
| 08-03 11:22 | fabliq | 0/4 | milestone-miss-15min | 15m:0✗ | 221 | 243.9 | `ada-handles_fabliq_codex_pon_1785781354` |
| 08-03 12:58 | fabliq | 0/4 | milestone-miss-15min | 15m:0✗ | 115 | 248.7 | `ada-handles_fabliq_codex_pon_1785787074` |

## Regression campaign (REGRESSION1)

```
REGRESSION CAMPAIGN — python (ada-handles), 3 runs per model, note prefix REGRESSION1

model              plan  runs  scores           verdict
------------------------------------------------------------------------
ternary-bonsai     off      3  4 3 4            NOT STABLE 2/3
gemma4             off      0  —                RUNNING
qwythos            off      2  4 0              2/3 run
qwopus             off      2  4 1              2/3 run
ornith             off      2  4 0              2/3 run
mellum2            off      2  3 1              2/3 run
nemotron-elastic   on       2  3 3              2/3 run

IN FLIGHT: gemma4 — do not start another run, and do not edit cria or its prompts (they load lazily; an edit changes the RUNNING system)
```

Operator report: [`regression-report.md`](regression-report.md) · authority: `python3 suite/regression_status.py`.

## Fixes landed during the ladder

```
90e684b fix(steer,loop,editrecovery): rebase five guards off blind-author-era evidence — the provenance retunes
c731f5c docs(regression): ternary 3/3 closes 4-3-4; gemma4 rows superseded by the hand-back fix; audit recorded
a25b037 fix(loop): plan-off is a reading step plus the RAW task — and the audit batch
26bfa92 docs(regression): nemotron 2/3 = 3/4 walked — cria fault none; stable model defect; pass 3 begins
fae111a docs(regression): mellum2 2/3 = 1/4 walked — cria fault none; pytest-mock dead-end; row stands
7e4b167 docs(regression): ornith 2/3 = 0/4 walked — cria fault none; mock-protocol oscillation; row stands
134c382 docs(regression): qwopus 2/3 = 1/4 walked — cria fault none; truncated README + mock oscillation; row stands
1dc813b docs(regression): qwythos 2/3 = 0/4 walked — cria fault none; interface oscillation; row stands
98a4951 docs(regression): gemma4 2/3 = 0/4 walked — same edit-spiral disease; false-field steer counter-evidence to open-threads
7ec52ff docs(regression): ternary-bonsai 2/3 = 3/4 walked — cria fault none; clock death mid-fix; row stands
2ab7dcb docs(regression): nemotron 1/3 = 3/4 walked — cria fault none; refuted-by-disk guard fired 4x correctly in-run
ccf601b docs(regression): nemotron-elastic 1/4 walked + superseded — confirm veto refuted-by-disk fixed; rerun on new code
ecc40f1 fix(loop): a confirm veto claiming a file is MISSING is refuted by cria's own disk
3aab947 docs(regression): mellum2 1/3 = 3/4 walked — cria fault none; live test not separate; 5b steer instance recorded
086dca6 docs(regression): ornith 1/3 = 4/4 on the confirm-applicability fix
```

---

Walk records — one per failed run, with the four questions and the verdict — are in [`ladder-walk.md`](ladder-walk.md).
