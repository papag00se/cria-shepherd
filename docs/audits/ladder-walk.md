# Language ladder — walk record

One section per walked run. The heading **must** be `## <run_id>` exactly — `suite/ladder_status.py`
reads these headings to decide whether a failure has been walked, and will not release the next run
command until it finds one.

The rule the ladder runs on: a model repeats the language until it scores 4/4, and no model runs
twice without its previous failure being walked first.

For every wrong turn, four questions in order — only when all four fail is it a model wall:

> 1. Did cria state something **false or stale**?
> 2. Did cria tell it to do something **impossible**?
> 3. Did cria **withhold** something it already held?
> 4. Did cria's **wording** cause it?

**RUN any code a steer contains.** A diagnosis that reads correct can still ship a fix that cannot
execute; that is how phase 1's Python cell was cleared wrongly the first time.

---

## Ladder

| # | model | params | kind | planner | attempts | best | state |
|--:|:--|:--|:--|:--|--:|:--:|:--|
| 1 | ternary-bonsai | 27B | dense | off | 0 | — | not started |
| 2 | gemma4 | 12B | dense | off | 0 | — | not started |
| 3 | qwythos | 9B | dense | off | 0 | — | not started |
| 4 | qwopus | 9B | dense | off | 0 | — | not started |
| 5 | ornith | 9B | dense | off | 0 | — | not started |
| 6 | fabliq | 8B | dense | off | 0 | — | not started |
| 7 | mellum2 | 12B / A2.5B | MoE | on | 0 | — | not started |
| 8 | nemotron-elastic | 12B / A2B | MoE | on | 0 | — | not started |
| 9 | zaya1 | 8.4B / A760M | MoE | on | 0 | — | not started |

This table is a human-readable mirror. `python3 suite/ladder_status.py` is the authority; when they
disagree, the command is right and this table is stale.

---

<!-- walks go below, newest last -->
