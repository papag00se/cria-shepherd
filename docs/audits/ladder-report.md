# Language ladder — live report

**Generated** 2026-08-01 19:01:08 PDT by `python3 suite/ladder_report.py` · **do not hand-edit** — every value here is read from disk or `ps` at generation time.

Goal: **python** (`ada-handles`), 15 minutes per deliverable. A model repeats until it scores 4/4, then the next one starts.

Authority: `python3 suite/ladder_status.py` — 0 = language complete, 1 = work remains, 2 = a run is in flight.

## Now

**Nothing running.** Next action: **run** `zaya1` (attempt 2).

## Ladder

| # | model | params | architecture | kind | planner | tries | best | state |
|--:|:--|:--|:--|:--|:--|--:|:--:|:--|
| 1 | ternary-bonsai | 27B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 2 | gemma4 | 12B | `gemma4` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 3 | qwythos | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 4 | qwopus | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 5 | ornith | 9B | `qwen35` | dense | off | 1 | 4/4 | 🟢 PASSED |
| 6 | mellum2 | 12B/A2.5B | `mellum 64/8` | moe | on | 5 | 2/4 | ⛔ BLOCKED |
| 7 | nemotron-elastic | 12B/A2B | `nemotron_h_moe 128/6` | moe | on | 1 | 4/4 | 🟢 PASSED |
| 8 | zaya1 | 8.4B/A760M | `zaya 16/1` | moe | on | 1 | 0/4 | 🔁 ready to rerun |
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

## Fixes landed during the ladder

```
af3056f fix(suite): the idle watcher called a deliberate measurement 'idle'
087cab5 fix(prompts,suite): P1 — the plan must not invent filenames or a human's workflow
f732f69 fix(suite): correct the reattach measurement, and measure P1 and P4 offline
2172e77 feat(loop)+test: wire the live execution check, and audit today's fixes against the doctrine
bcecf45 feat(suite): replay captured runs through cria's deterministic logic — no GPU
1843570 feat(loop): detect the gate ALTERNATING between two finding-sets
a91d193 fix(loop): the "task is finished but I can't stop" off-ramp never ran with a plan
e651951 docs(ladder): walk mellum2 attempt 5 — the fix worked and the run still failed
9b52224 fix(loop): cria withheld its correction on a premise false 73% of the time
aa464fd fix(loop): an authoring step must stop saying "Write X" once X exists and is failing
af69c12 docs(ladder)+fix(execcheck): walk mellum2 attempt 3; a test file is not a program
c4d955c feat(suite): shout when the ladder is idle
484d75d fix(suite,docs): a package named after cria's own tool poisoned a run for nine days
0c0a6d1 docs(ladder): walk mellum2 attempt 2 — 0/4, model wall, and a correction
05b01a7 feat(execcheck): live execution check — corroborate three sources, run, never block
```

---

Walk records — one per failed run, with the four questions and the verdict — are in [`ladder-walk.md`](ladder-walk.md).
