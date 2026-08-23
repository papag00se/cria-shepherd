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

### Results

| cell | cycle 1 | cycle 2 | what changed underneath |
|---|---|---|---|
| nemotron × ruby | 20% | **0%** | It fixed the seeded bug and wrote 58 lines of real implementation, then unpacked `europe-0.0.28.gem` into the project ROOT — `cache/`, `doc/`, `gems/`, `specifications/` and a stray `lib/europe.rb` — and pointed its Gemfile at it with `gem 'europe', path: 'gems'`. `lib` is on the Rakefile's load path, so `require 'europe'` finds that half-extracted file and dies on `require "europe/version"`. Every test fails at load, including the ones green at seed. The implementation was worth 2–3; the self-inflicted LoadError took all of it. |
| nemotron × go | 20% | 20% | The invented API is GONE: `RoundingMode*` 4 uses → 0. It now calls `decimal.NewFromString(priceStr)` capturing both returns, `Mul`, `Add` — the library as it actually exists, which is what the empty-grep and page-not-file fixes were aimed at. What remains is ordinary Go: `cannot use nil as decimal.Decimal value`, `2 variables but p.Mul returns 1 value`. Same score, shallower failure. |
| nemotron × java | 0% | running | |
| ternary × ruby | 20% | pending | |

### Reading so far

Two of the three predictions have held where they could be tested. The go cell stopped inventing an
API — the specific thing cycle 1 aimed at — and the score did not move, because this cell scores
nothing until the build compiles. The ruby cell got FURTHER than cycle 1 and scored LOWER, which the
number alone hides: it wrote the code and then broke its own load path.

Both of those are cycle-3 walk questions: did anything cria said push the ruby coder toward unpacking
a gem by hand, and is there anything in the go context that would have caught `nil` for a struct
return.

---

## Cycle 3 — walked cycle 2, fixed to `3ce7fcb`

**Walk:** 8 agents over 393 coder prompts of all four cells, every prompt and reasoning file in order.
Each band carried the established facts and one question, so it explained rather than re-derived.

**Found and fixed — 13 roots, every one reproduced by executing the code:**

| root | evidence |
|---|---|
| The elision dropped every test runner's MESSAGE | `-A3` keeps context after a `path:line`; compilers write the message there, minitest/JUnit/RSpec/pytest/`go test` write it ABOVE the first frame. The ternary coder saw `rates.rb:21` sixteen times and never `NoMethodError: undefined method 'new' for Countries:Module` |
| The Ruby backtrace frame had no pattern at all | `from /w/lib/europe.rb:3:in …` — the shape of every non-assertion Ruby failure. cria said "a specific line could not be parsed" 31 times about a trace whose second line names a file and a line |
| dirguard refused the command that would have saved the run | `ls vendor/bundle/ruby/*/gems/x/lib/` → "The path '/gems/x/lib/' is outside it". `*` terminates the path token, so the tail reads as rooted. Three refusals, on a directory inside the workspace |
| `gem install -i local_gems` refused, `--install-dir=.` allowed | The guard tested spelling, not destination — and the one it waved through unpacked a gem tree over the repo root |
| "gems is already installed on this machine" | `\w*` let the path `gems/europe-0.0.28.gem` match the tool's own name |
| The external-path refusal named no safe place | "use a path within the project instead" → the coder wrote `lib/europe.rb`, which the load path finds ahead of the gem |
| A shadowing file was known and unsaid | `names_a_workspace_file` walked the tree, found `lib/europe.rb`, and used it only to fall silent |
| The fetch tail on a fetchless block (MY cycle-2 regression) | 43 of 46 java prompts called a list of local files "your real fetch record" and said "code against THOSE rather than re-fetching" |
| The band kept duplicates | Two of six slots on one repeated import; `method parse()` and the constructor candidate list cut |
| The supervisor prompt contradicted itself | "You cannot run commands" + "command it NOW with a tool call" — most of a 21KB trace spent there, fabrications at the end of the spiral |
| The search judge could not see the session | Endorsed `github.com/oklog/decimal` twice while cria held two 404s for it |
| Maven's prose location unparsed | `@ file, line N, column M` |
| The degenerate notice lacked the library clause | Its two siblings carry it; it fires most often |

**Not fixed, needs the operator's call:** three cells now end the same way — a real library, chosen
from memory, then used from memory. cria has guards for repeating a call, a search, a fetch and a
thought, and none for "you are writing against a library you have never opened." Every existing
mechanism that should have helped has now been fixed; whether to ADD one is a decision, not a bug.

---

## Cycle 3 results

| cell | c1 | c2 | c3 | what it ended on |
|---|---|---|---|---|
| ternary × ruby | 20% | 40% | **100%** | `require "countries"` / `ISO3166::Country#in_eu?` — the real API, suite green 16/22 |
| nemotron × java | 0% | 20% | 20% | declared opencsv, wrote *commons-csv's* `CSVRecord` against it |
| nemotron × go | 20% | 20% | 20% | `Quantize` and `RoundHalfUp` back; the real `Round` in zero prompts |
| nemotron × ruby | 20% | 0% | 0% | `NameError: undefined ... 'surcharge'` — its own code, but the workspace is CLEAN: no unpacked gem, no shadow file, good gem choice |

**ternary is the headline and the caveat.** First perfect score this cell has had. The failures that
were cria's own are verifiably gone from it — no dead 2013 gem, no phantom `rspec`, no "not installed
anywhere" while the gems sat on disk, no `/gems/...` refusal (0 this run, 3 last). But it got the API
from `rubydoc.info`, not from the vendored source, so removing the refusal is not *proven* to be what
freed it. One run cannot separate that from taking a different path.

**nemotron × ruby is 0% for the third cycle and it is not the same 0%.** Cycle 2 unpacked a gem over
the repo root and shadowed the load path; cycle 3's workspace holds one modified file and a Gemfile
naming the right gem. What is left is an ordinary bug in its own code.

Found by watching rather than walking, and fixed at `19d0210`: minitest's ERROR frames have no `from`
prefix, so they parsed as nothing, and the fallback then took the tally as the failure — 33 of 81
prompts said "a specific line could not be parsed" and quoted a count.

---

## The one addition, put to the operator rather than built

Three cycles, thirty-seven root fixes, and three cells sit at 20% for one unchanged reason: **a real
library, chosen from memory, then used from memory.**

| cycle | ruby | go | java | ternary |
|---|---|---|---|---|
| 1 | 20% | 20% | 0% | 20% |
| 2 | 0% | 20% | 20% | 40% |
| 3 | 0% | 20% | 20% | — |

Cycle 2's go cell looked like progress on this axis — the invented API vanished — and I read it as the
fixes working. That was too generous, and the walk had said so plainly: *"The fix worked. It worked in
spite of the harness, not because of it."* A web search happened to run at call 0048 and returned the
real library. Cycle 3 it did not happen, and `Quantize` and `RoundHalfUp` came straight back. That was
variance, not a mechanism.

What is left, in cycle 3, in each cell's own words:

* **java** — `symbol: class CSVRecord` / `location: package com.opencsv`. It declared opencsv in
  pom.xml and wrote *commons-csv's* class names against it. Two libraries blended from memory.
* **go** — `taxedDec.Quantize undefined (type decimal.Decimal has no field or method Quantize)`. One
  search, four fetches, and the real signature `func (d Decimal) Round` in zero prompts.
* **ternary ruby (cycle 2)** — `NoMethodError: undefined method 'new' for Countries:Module`, with the
  gem's source installed on disk in the same workspace.

### Why no existing mechanism reaches it

Every adjacent one has now been fixed and verified: the elision that deleted the message, the parser
that could not read a Ruby frame, the guard that refused reads of the vendored source, the notes that
said a library was uninstalled when it was not, the judge that endorsed a repository it had already
404'd. None of them is this. cria has guards for repeating a call, a search, a fetch and a thought —
and none for *"you are writing against a library you have never opened."*

### What it would be

A FACT, not a directive, and deterministic — no reasoner, no guess, no prescription:

> the checker reports a missing symbol in `com.opencsv`, and nothing this session has read comes from
> that package.

Feasibility checked, all three inputs already in hand at one seat:

* the finding carries the package — `location: variable parser of type com.opencsv.CSVParser`
  survives whole in `Finding.message`
* `loop._fetch_ground_truth` — what was fetched
* `loop._read_ground_truth` — what was read off disk

It names no class, no fix and no library to use; it states what the checker said and what the session
has read, and stops. That is the shape of #8 (deterministic gathers, the reader judges) and #11b (it
speaks only about what it reached).

### Why it is the operator's call and not mine

Doctrine #1 says assists are footguns and the bar to ADD is high, and `research.py`'s own history
records a mechanism built for this exact failure and later deleted for being a step nobody needed. The
argument for it now is that the bar has been met by elimination rather than by assertion: three cycles
of fixing everything adjacent has bounded the residue to this one thing. The argument against is that
it is still an ADD, on a shape that has been tried before.

Not built. Awaiting a decision.
