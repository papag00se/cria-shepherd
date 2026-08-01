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

| # | model | params | architecture | kind | planner | attempts | best | state |
|--:|:--|:--|:--|:--|:--|--:|:--:|:--|
| 1 | ternary-bonsai | 27B | `qwen35` | dense | off | 1 | **4/4** | ✅ PASSED (no walk needed) |
| 2 | gemma4 | 12B | `gemma4` | dense | off | 1 | **4/4** | ✅ PASSED (no walk needed) |
| 3 | qwythos | 9B | `qwen35` | dense | off | 1 | **4/4** | ✅ PASSED (12.7 min, no walk needed) |
| 4 | qwopus | 9B | `qwen35` | dense | off | 0 | — | not started |
| 5 | ornith | 9B | `qwen35` | dense | off | 0 | — | not started |
| 6 | mellum2 | 12B / A2.5B | `mellum` 64/8 | MoE | on | 0 | — | not started |
| 7 | nemotron-elastic | 12B / A2B | `nemotron_h_moe` 128/6 | MoE | on | 0 | — | not started |
| 8 | zaya1 | 8.4B / A760M | `zaya` 16/1 | MoE | on | 0 | — | not started |
| 9 | fabliq | 8B / A1B | `lfm2moe` 32/4 | MoE | on | 0 | — | not started |

This table is a human-readable mirror. `python3 suite/ladder_status.py` is the authority; when they
disagree, the command is right and this table is stale.

---

## Notes — findings that are not a single run's walk

**gemma4's sampling was wrong for 26 runs (2026-08-01).** Every gemma4 row before the ladder was
sent ternary-bonsai's numbers — coder `0.2/0.95/20`, reasoner `0.6/0.90/40` — read from g26's
captured request bodies, not inferred. `run.py` swapped the model and the planner and never touched
`[roles.*]`. Fixed in `7259203`: `suite/sampling.py` holds canonical per-model values with sources
cited, and the runner applies them on every swap.

The first gemma4 run on its own settings (`1.0/0.95/64`, coding temp 0) scored **4/4** against a
26-run ceiling of 3/4. **That is n=1 and is not a finding yet** — this model's scores have swung
0 to 3 on identical code, so one run cannot separate the settings from variance. It is recorded
here as the thing to measure, not as the reason.

**The shared-install guard was exercised in the field.** gemma4 built a `.venv` inside its
workspace rather than installing into the user's Python; `site_packages_leak` was empty. Landed
same day in `53cae4a`.

---

<!-- walks go below, newest last -->
