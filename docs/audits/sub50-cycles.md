# Sub-50% cells — the walk/fix/re-run cycle

**The loop:** run the cells below 50% → walk every call of the ones still below → verify each finding
by executing the code → fix at the root → re-run. One code state per run; the grid is refreshed from
`suite/results/results.jsonl` after each.

Status of the cycle currently running is at the bottom. Every root is listed with the evidence that
found it and the commit that closed it.

---

## Cycle 1 — walked `ef8ee77`, fixed to `cdc4f9e`

**Walk:** 14 agents over 451 coder prompts of the four sub-50% cells, every prompt and every
`reasoning.txt` read in order. Report: `docs/audits/2026-08-23-sub50-walk.md`.

**Found:** 24 roots, each reproduced by executing the shipped code. The shape: three of the four cells
were lost the same way — cria stated something false about the world in its own voice and the model
believed it over its own eyes.

**Fixed:** all 24, in twelve commits `05dd511`…`cdc4f9e`. Suite 4,429 green.

| # | root | commit |
|---|---|---|
| A1 | Ruby's failing test arrived as a stopwatch reading (`assert` matched inside `assertions/s`) | `f0c…` |
| A2 | `bundle exec rspec` published as "the repo's own checks" for a repo with no rspec | `f0c…` |
| A3 | The Maven note named the project instead of the missing jar | `05dd511` |
| A4 | "not installed anywhere" while `vendor/bundle` held four gems | `612a146` |
| A5 | A refused search recorded as a search that ran | `2d53174` |
| A6 | `Shipping.zone_for` and `e.g.` printed as missing files | `271e0fd` |
| A7 | `FILE FOLD_AT — does NOT exist on disk`, cria's own constant | `2d53174` |
| A8 | `go`/`rust` (and four more) notes asserting the calling code was innocent | `05dd511` |
| A9 | "saved IN FULL" for a file cria knew it had cut | `c5e6793` |
| A10 | The wrong-root note naming a parent of the directory just searched | `63c54c9` |
| A11 | The staleness ledger blind to changes made through the shell | `612a146` |
| A12 | A reading hint measuring the document and naming the file | `c5e6793` |
| B1 | The recovered diagnostics band cut the three errors that mattered, uncounted | `a640190` |
| B2 | Compaction kept the fetched URLs and dropped every file read off disk | `cdc4f9e` |
| B3 | 46KB of stylesheets saved as `…_decimal.go.txt` and called the document | `c49c4a8` |
| B4 | A `grep` that matched nothing rendered as a blank | `63c54c9` |
| C1 | "Just pick one and proceed" to a model that had not read the library | `15ea251` |
| C2 | Length aborts blamed on second-guessing (densities 0.73–2.50 vs a threshold of 10) | `15ea251` |
| C3 | "Continue from what you already know" after cria discarded the reasoning | `15ea251` |
| C4 | A directive inventing `v1.5.0` | `aee15aa` |
| C5 | A re-orientation inventing `lib/shipping.rb` | `aee15aa` |
| D1 | Four identical `rake test` runs read as four different results | `e2a4fa9` |
| D2 | The fused-call tail left in place when the second call was multi-word | `e2a4fa9` |
| D3 | A judge told to "ask again next round" when no round could answer | `aee15aa` |

**Withdrawn:** gating filename claims on "does this workspace contain that suffix" — it broke a true
claim about a genuinely missing `handles.py`, which the existing suite caught. Shipped two shape rules
instead (a trailing boundary, a two-character stem).

**Wider than the walk reported:** the "not what failed here" clause was in six dependency notes, not
two; the fused-tail gap covered any multi-word second call, not only `exec_command`.

---

## Cycle 2 — running at `cdc4f9e`

Four cells: nemotron × {ruby, go, java}, ternary × ruby. Baseline going in: 20 / 20 / 0 / 20.

What each fix is expected to change, so the result can falsify it:

* **ruby** — the minitest failure now carries `Expected` vs `Actual`, and the phantom `rspec` check is
  gone. If the model still never writes code, the cause is elsewhere.
* **go** — an empty grep says the string is absent, the spill says it holds a web page, and the
  version-inventing directive is refused. The question is whether it reaches `RoundCeil`.
* **java** — the dependency note names the right artifact, all nine compile errors are counted, and
  no steer tells it to commit without looking. The question is whether it reads the commons-csv API.
* **ternary ruby** — expected to stay low. Its gem choice decides the cell, cria's remedy was already
  correct and already delivered, and `eu_countries 0.0.2` is unwinnable: its own `require "iso3166"`
  no longer resolves against today's `countries` gem. Reproduced with the full remedy applied.

Results land here as each cell finishes.
