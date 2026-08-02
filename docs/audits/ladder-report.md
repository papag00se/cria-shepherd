# Language ladder — live report

**Generated** 2026-08-02 09:25:55 PDT by `python3 suite/ladder_report.py` · **do not hand-edit** — every value here is read from disk or `ps` at generation time.

Goal: **python** (`ada-handles`), 15 minutes per deliverable. A model repeats until it scores 4/4, then the next one starts.

Authority: `python3 suite/ladder_status.py` — 0 = language complete, 1 = work remains, 2 = a run is in flight.

## Now

**Nothing running.** Next action: **walk** `ada-handles_mellum2_codex_poff_1785686596` (capture `/home/jesse/.cria/calls/20260802T090329-019fc337-4fd6-7472-af0b-a348e8fb002c`), then write `## ada-handles_mellum2_codex_poff_1785686596` into `docs/audits/ladder-walk.md`.

## Ladder

| # | model | params | architecture | kind | planner | tries | best | state |
|--:|:--|:--|:--|:--|:--|--:|:--:|:--|
| 1 | ternary-bonsai | 27B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 2 | gemma4 | 12B | `gemma4` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 3 | qwythos | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 4 | qwopus | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 5 | ornith | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 6 | mellum2 | 12B/A2.5B | `mellum 64/8` | moe | off | 19 | 3/4 | 📖 needs walk |
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
| 08-02 04:29 | mellum2 | 3/4 | milestone-miss-60min | 15m:2✓ 30m:3✓ 45m:3✓ 60m:3✗ | 479 | 166.9 | `ada-handles_mellum2_codex_pon_1785670156` |
| 08-02 05:32 | mellum2 | 1/4 | milestone-miss-30min | 15m:1✓ 30m:1✗ | 156 | 155.1 | `ada-handles_mellum2_codex_pon_1785673911` |
| 08-02 06:05 | mellum2 | 1/4 | milestone-miss-30min | 15m:0✗ 30m:1✗ | 204 | 163.4 | `ada-handles_mellum2_codex_pon_1785675899` |
| 08-02 06:42 | mellum2 | 1/4 | milestone-miss-60min | 15m:1✓ 30m:3✓ 45m:3✓ 60m:1✗ | 279 | 159.3 | `ada-handles_mellum2_codex_pon_1785678150` |
| 08-02 07:45 | mellum2 | 2/4 | exited | — | 63 | 189.4 | `ada-handles_mellum2_codex_pon_1785681911` |
| 08-02 07:51 | mellum2 | 2/4 | milestone-miss-45min | 15m:2✓ 30m:2✓ 45m:2✗ | 155 | 149.6 | `ada-handles_mellum2_codex_pon_1785682267` |
| 08-02 08:39 | mellum2 | 3/4 | exited | — | 53 | 175.0 | `ada-handles_mellum2_codex_poff_1785685170` |
| 08-02 08:49 | mellum2 | 3/4 | exited | — | 161 | 168.0 | `ada-handles_mellum2_codex_poff_1785685763` |
| 08-02 09:03 | mellum2 | 2/4 | exited | — | 88 | 173.6 | `ada-handles_mellum2_codex_poff_1785686596` |

## Fixes landed during the ladder

```
ee13db6 docs: drop the invented word 'oracle' — it is just suite/ladder_status.py
782479e ladder: flip mellum2 to planner OFF — the hypothesis loses on this model
f258a83 fix(verify): the resolver's COUNT check could never fail
d466769 fix(replan): delete the regex guard; tell the judge the invariant it was breaking
5d7ba9e fix(suite): the live probe I just shipped would have blocked every run forever
e680f6b fix(suite): refuse to start, and refuse to score, when the live service throttles us
c4e34b9 fix(replan): bound the artifact match — adjacency was too tight, the sentence too loose
6f716ef fix(replan): narrow the artifact protection I added — it was protecting junk
eb9a1fe fix(probeparse): my stdlib fix was incomplete — cover every parser, not just pytest
8c85646 fix(replan): the noise judge may not delete a step that AUTHORS a file
151435b obs(loop): log WHICH steps the noise judge deleted, not just how many
69efeaf fix(probeparse): stop pointing the coder at Python's standard library
78d5d05 fix(replan): refuse a re-derived step that names a CRIA TOOL as the product's code
7bbf886 feat(verify): show the critic when a step's quoted values are absent from the file
895651a fix(loop): the unexecuted-write guard could not see a pasted README
```

---

Walk records — one per failed run, with the four questions and the verdict — are in [`ladder-walk.md`](ladder-walk.md).
