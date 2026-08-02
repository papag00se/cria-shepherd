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
| 4 | qwopus | 9B | `qwen35` | dense | off | 1 | **4/4** | ✅ PASSED (6.5 min, no walk needed) |
| 5 | ornith | 9B | `qwen35` | dense | off | 1 | **4/4** | ✅ PASSED (7.6 min, no walk needed) |
| 6 | mellum2 | 12B / A2.5B | `mellum` 64/8 | MoE | on | 5 | 2/4 | ⛔ BLOCKED — five walked failures, not a pass |
| 7 | nemotron-elastic | 12B / A2B | `nemotron_h_moe` 128/6 | MoE | on | 0 | — | not started |
| 8 | zaya1 | 8.4B / A760M | `zaya` 16/1 | MoE | on | 1 | 0/4 | 📖 walked — rerun pending |
| 9 | fabliq | 8B / A1B | `lfm2moe` 32/4 | MoE | on | 0 | — | not started |

This table is a human-readable mirror. `python3 suite/ladder_status.py` is the authority; when they
disagree, the command is right and this table is stale.

---

## Notes — findings that are not a single run's walk

**ALL FIVE DENSE MODELS PASSED, planner OFF, first attempt (2026-08-01).** 27B → 9B, 26.2 / 28.4 /
12.7 / 6.5 / 7.6 minutes. The dense half of the operator's hypothesis — that dense models cope with
the planner off — is now supported by 5 for 5.

**The MoE half cannot be tested by the ladder as written, and that is a flaw in this doc's design.**
The ladder runs MoEs with the planner ON and only flips the setting when a model repeatedly fails.
If the MoEs pass with it on, we learn that they pass with it on — not that they NEEDED it. The clean
test is a planner-OFF arm for each MoE, run regardless of whether the ON arm passed. Queued
separately; not silently folded into the ladder, because the ladder's job is 4/4 and this is a
different question.

**gemma4's sampling was wrong for 26 runs (2026-08-01).** Every gemma4 row before the ladder was
sent ternary-bonsai's numbers — coder `0.2/0.95/20`, reasoner `0.6/0.90/40` — read from g26's
captured request bodies, not inferred. `run.py` swapped the model and the planner and never touched
`[roles.*]`. Fixed in `7259203`: `suite/sampling.py` holds canonical per-model values with sources
cited, and the runner applies them on every swap.

The first gemma4 run on its own settings (`1.0/0.95/64`, coding temp 0) scored **4/4** against a
26-run ceiling of 3/4. **That is n=1 and is not a finding yet** — this model's scores have swung
0 to 3 on identical code, so one run cannot separate the settings from variance. It is recorded
here as the thing to measure, not as the reason.

**Four dense models passed on the first attempt (2026-08-01)** — ternary-bonsai 26.2 min, gemma4
28.4, qwythos 12.7, qwopus 6.5. The same Python task scored 0/4 for ternary-bonsai yesterday under
the phase-1 matrix. Two things changed between: the milestone pacing (which was NOT binding — every
run finished well inside the old 30-minute wall) and the day's cria fixes, of which the
steer-writes-no-code rule has a direct mechanism, since C1's documented cause was two steers
shipping broken code under correct diagnoses. **Mechanism is not measurement.** Each model is n=1
and no A/B has been run against the previous build. Recorded as the leading hypothesis to test, not
as a result.

**The shared-install guard was exercised in the field.** gemma4 built a `.venv` inside its
workspace rather than installing into the user's Python; `site_packages_leak` was empty. Landed
same day in `53cae4a`.

---

<!-- walks go below, newest last -->


## ada-handles_mellum2_codex_pon_1785613520

**2/4** · planner ON · 16.3 min · 114 calls · 144.7 tok/s · `exited` (the model believed it was done)
· capture `~/.cria/calls/20260801T124541-019fbedc-5f1b-7812-b2f9-9da30b0575e4`

| deliverable | | detail |
|:--|:--:|:--|
| unit tests | 🟢 | 9 passed |
| README | 🟢 | install / run / tests |
| resolver CLI | 🔴 | `resolve_handle.py goose` → exit 0, **no output** |
| live test | 🔴 | never written |

### What it built

A pure library. `resolve_handle.py` has **no `main()`, no `__main__` guard, no argparse, no
`sys.argv`** — only importable functions. Its README documents `python resolve_handle.py --live
goose papagoose`, which runs and prints nothing.

It also targeted `https://api.handle.me/mcp` with malformed JSON-RPC (`"jsonrpc": "2025-11-25"` —
a protocol date where the version belongs). The endpoint is REAL and answers "Invalid JSON-RPC
request".

### The four questions

| | |
|:--|:--|
| false or stale? | **No.** The MCP endpoint was not cria's suggestion — `api.handle.me`'s own root page lists it, and its OpenAPI spec defines `/mcp` as "Model Context Protocol endpoint". cria relayed the site verbatim, and its note was actively good: *"Nothing you have read so far DEFINES a route, so any endpoint in your plan would be a guess"* — after which the model fetched the real spec. |
| impossible? | No. |
| withheld? | **YES — see below.** |
| wording? | Contributory, same finding. |

### The finding: the completion brake asks ONE fused question about a FOUR-deliverable task

The approve-path brake works as designed and has real tools. It used them — `list_dir(".")` returned:

```
README.md (795 B)   resolve_handle.py (1995 B)   test_resolve_handle.py (4227 B)
```

That listing PROVES the live test is absent. The brake answered `{"consistent": true, "why": ""}`.

It was asked whether the verdict's *reason* was consistent — one yes/no over a four-clause claim
("resolves addresses, retrieves holder details, comprehensive unit tests, implements live mode,
includes a README"). Three of those clauses were true. A fused question over a mostly-true claim
gets a yes.

**cria already owns the decomposition it needed.** `planner.missing_deliverables(ask, task, steps)`
takes the task, names its deliverables, and returns the ones nothing produces. It runs at plan
draft and at every re-derivation — and **never at completion**, which is the one place a wrong
answer ends the session.

The plan also shrank 8 → 4 → 3 → 2 → 1 steps across four re-derivations while two deliverables were
never built, and no coverage event fired at any of them.

### Prevalence

Across every captured suite run with a results row: **17 `satisfied: true` verdicts, 7 of them on
runs that finished below full marks — 41%.** Three different models (qwythos, gemma4, mellum2). Not
a mellum2 quirk.

### Status: measuring before changing

The mechanism is identified and the component already exists, but the fix is a new model call on the
completion path, and the bar to ADD is high. Doctrine says measure first, and the replay harness can
answer this without spending runs: replay captured `satisfaction-confirm` prompts with the current
fused ask against a per-deliverable ask, n≥12, across the fleet — the critic-wording change that was
"obviously right" once before took a judge from 8/8 to 1/8.

Not fixed yet. Recorded as the leading candidate with its measurement queued.

**Also true and not to be papered over:** mellum2 is a weak judge — the fleet readability table has
it at **1/6** on the critic ask. Part of this is the model. The cria-side question is whether a
sharper question rescues a weak judge, which is exactly what the replay will say.


## ada-handles_mellum2_codex_pon_1785620496

**0/4** · planner ON · killed at 15 min (`milestone-miss-15min`, re-checked and confirmed) · 81 calls
· 160.4 tok/s · capture `~/.cria/calls/20260801T144148-019fbf46-ad70-7271-bd36-f98d97802a35`

Everything red: 8 of 9 unit tests failing, no README, no live test, CLI silent.

### The four questions

| | |
|:--|:--|
| false or stale? | **No.** The gate ran and blocked **11 consecutive times** on the same real findings (4, then 2), floor clean throughout. The failures are genuine: `TypeError: 'coroutine' object…`, `aiohttp…`, `TypeError: 'module' object…`. |
| impossible? | No. |
| withheld? | No — the same accurate diagnosis was in front of it eleven times. `loop.gate_stalled` fired 9 times, which is cria correctly recording "this is not converging". |
| wording? | No. One steer in the whole run. |

**Verdict: MOSTLY a model wall, with one finding cria seeded — corrected after reading the
reasoning.** Three of the four gate findings are the model's own: it chose `aiohttp` and `async def`
for a task with no concurrency (7 occurrences in one file) and could not make its mocks match the
coroutines. The fourth was not its fault.

#### `resolve_holder.py:24 — TypeError: 'module' object is not callable`

The model wrote `from web_fetch import web_fetch`. **`web_fetch` is one of cria's own synthetic tool
names** — the model treated a tool it had been given as a library it could import. On its own that
is a rare slip (measured: **1 of 59 archived workspaces**, so NOT a pattern and NOT worth an assist).

What made it unrecoverable was the box. A real, unrelated PyPI package called `web_fetch` (a web
scraper by another author) had been sitting in the user's site-packages since **2026-07-23** —
installed by some earlier `--yolo` run that made the same mistake and ran `pip install web_fetch`.
So the import did not fail cleanly. It SUCCEEDED, bound a module, and produced
`TypeError: 'module' object is not callable` — an error with no reachable explanation from where the
model stood.

Its reasoning shows exactly that. It traced the line correctly, twice, and could not accept the
result:

> *"The import `from web_fetch import web_fetch` makes `web_fetch` the function. So `web_fetch(url)`
> IS correct. But the error says 'module' object is not callable, which suggests that `web_fetch` is
> the module, not the function."*

It was right, and the world disagreed with it. ~12,000 characters of reasoning went into that one
line, inside a 15-minute budget.

**Fixed, both ends:**

| | |
|:--|:--|
| the install that seeded it | already refused by `53cae4a` — `pip install web_fetch` is a shared install and dirguard now blocks it |
| the package already on the box | moved out of site-packages (backed up, not deleted); the import now raises a clean `ModuleNotFoundError` |
| the class | `suite/preflight.py` now refuses READY while any package on the path collides with a cria tool name (`web_fetch`, `read_file`, `write_file`, …). Tested both ways. |

The earlier `.pth` check could not have caught this — it looks for editable installs pointing into
`/tmp`, and this was an ordinary PyPI package.

### The budget was NOT the problem, contrary to first impression

| phase | calls | seconds | share |
|:--|--:|--:|--:|
| coder | 27 | 532.1 | **69.9%** |
| planner | 25 | 88.6 | 11.6% |
| critic | 11 | 71.3 | 9.4% |
| reasoner | 13 | 49.5 | 6.5% |

The coder's first call came **91 seconds in**, and it got 70% of all model time. The planner's 25
calls cost 88 seconds total. Worth recording because "planner ON means the crew eats the run" was
the obvious hypothesis from the call counts alone, and the timings refute it.

### What the two mellum2 attempts say together

| | attempt 1 | attempt 2 |
|:--|:--|:--|
| score | 2/4 | 0/4 |
| terminal | `exited` (believed itself done) | `milestone-miss-15min` |
| entry point | **none** — a pure library | present in all three files |
| shape | sync `requests`, MCP endpoint | async `aiohttp`, coroutine mocks |

**Same build, same settings, same model, 2/4 then 0/4.** The two runs did not even fail the same
way. This is the variance the goal doc warns about, and it is the justification for the ladder's
repeat-until-pass design over reading any single score.

It also corrects something written after attempt 1: the missing entry point is **not** a repeating
mellum2 signature. It happened once. The claim that three workspaces in a row lacked one was wrong.

### Cost of the milestone pacing, measured

Killed at 15.9 minutes instead of running the old flat 30. The saved half hour bought this walk and
the live-execution check.


## ada-handles_mellum2_codex_pon_1785625253

**0/4** · planner ON · killed at 15 min (re-checked, confirmed) · 91 calls · 166.4 tok/s
· capture `~/.cria/calls/20260801T160104-019fbf8f-40be-7f53-a1c0-881700caf8e7`

Tested exactly one change from attempt 2: the leaked `web_fetch` package removed from the box.
That error is gone. The run failed anyway, differently.

### It went BACKWARDS at the checkpoint

| | |
|:--|:--|
| 13 min | 2 tests passing → unit tests 🟢 → **1/4** |
| 15 min | 2 failed, 2 passed → 🔴 → **0/4** |

It did not lose work — it **added two error-path tests that fail** to a green suite, and the
checkpoint landed mid-edit.

### The four questions

| | |
|:--|:--|
| false or stale? | **No.** `loop.gate_stalled` fired **11 times** — cria correctly recording that the same findings kept coming back. Two steers were dropped as roleplay by the existing guard, which is that guard working. |
| impossible? | No. |
| withheld? | No. |
| wording? | No. |

**Verdict: model wall**, and the third distinct failure shape in three attempts.

### The ONE thing consistent across all three attempts

Every mellum2 run produced a **CLI that exits 0 and prints nothing**:

| attempt | score | entry point in the deliverable | CLI |
|:--|:--:|:--|:--|
| 1 | 2/4 | **none** | `--live goose papagoose` → exit 0, silent |
| 2 | 0/4 | present | exit 0, silent |
| 3 | 0/4 | **none** (only the TEST file had one) | exit 0, silent |

Attempt 3's `resolve_handle.py` ends on a function definition. Running it defines functions and
exits. Nothing else in the three runs repeats — the API shape, the async choice, the failing tests
all differ — but the deliverable is never a program.

### A defect this exposed in cria's OWN new check

`execcheck.entrypoints()` counted `test_resolve_handle.py` as an entry point, because test files
routinely carry `if __name__ == "__main__": unittest.main()`. So a workspace whose only runnable
file was its test suite read as "this project has a program". Fixed the same hour: test files are
excluded by name and by directory, across languages. Re-run over all three archives now reports
NONE / present / NONE, which matches the deliverables by hand.

Worth stating plainly: that check was written today to catch this exact class, and it would have
mis-reported the very run that motivated it.

### Next: planner OFF

Three stalls at the hypothesised setting. The goal doc sanctions flipping the planner as an explicit
experiment at this point, and it is also the operator's own hypothesis (dense cope with it off, MoEs
need it on) finally getting an arm that can disconfirm it. Attempt 4 runs `--planner off`.


## ada-handles_mellum2_codex_poff_1785626379

**1/4** · planner **OFF** (the sanctioned experiment after three stalls) · killed at 30 min ·
225 calls · 142.9 tok/s · capture `~/.cria/calls/20260801T161949-019fbfa0-6dd0-7710-b67f-127f4a2fe40a`

README green. One qualitative change from attempts 1–3: the CLI **exits 1** instead of exiting 0
silently — a program that runs and errors, rather than a library that does nothing. One run, so not
a finding; the planner flip is the only variable but this model has scored 2/4, 0/4, 0/4 on
identical settings.

### The finding: cria withheld its correction on a premise that was false 73% of the time

`loop.steer_same_checks` fired **11 times**. That guard suppresses a second steer when the repo's
findings have not moved, and its reasoning is sound and measured — 36% of every steer cria has ever
authored was fresh prose on unchanged findings, and g22 cost ten consecutive contradicting steers on
one assertion diff. It rests on one stated premise:

> *"The check output is the better steer, it is already in front of the coder."*

Measured across this run's coder prompts:

```
coder prompts                     176
...carrying the checks or a steer  47   (27%)
...with NO correction attached    129   (73%)
```

The premise is false for three turns in four. So cria was staying quiet because a better correction
was visible, while for most turns nothing was — the same shape as attempt 3's walk, seen from the
other side. There the standing instruction outlived its artifact; here the correction is actively
suppressed and nothing replaces it.

**Fixed — by making the premise TRUE rather than by removing the guard.** When the findings are
unchanged AND the checker's own first line is not present in the request, cria now hands back the
**checker's exact lines**, wrapped in "unchanged since you were last shown them — you have not
cleared them yet". It never re-invokes the reasoner, so g22's failure mode is untouched: no second
diagnosis, no new prose, no paraphrase. cria may SELECT a checker's real lines and must never
SUBSTITUTE its own words, and this only repeats them.

When the checks ARE already visible, the guard suppresses exactly as before.

Two existing tests asserted the old shape and were updated to assert the INVARIANT instead of the
exact output — "no second reasoner diagnosis" rather than "returns None". The distinction is the
whole fix. A third case neither covered (checks visible → still silent) was added.


## ada-handles_mellum2_codex_pon_1785628543

**0/4** · planner ON · killed at 15 min · 101 calls · 145.6 tok/s · the FIRST run carrying both of
today's correction fixes · capture `~/.cria/calls/20260801T165554-019fbfc1-741b-7ea0-a7f8-1dc1054309f3`

### The step-reframe fix WORKED, mechanically

It fired in **53 of 62** coder prompts (85%), and the behaviour it was built to stop, stopped:

| | attempt 3 (no fix) | attempt 5 (fix live) |
|:--|--:|--:|
| whole-file rewrites | 8 | **2** |
| targeted edits | 4 | **18** |
| rewrites of `test_resolve_handle.py` | 6 | **1** |

The rewrite loop is gone. The score did not move.

### What replaced it: an OSCILLATION between two errors that are each other's cause

The model alternated between two test styles, and **each individual fix was correct for the error it
was shown**:

| turn | gate said | model did | correct? |
|:--|:--|:--|:--|
| 0036 | `fixture 'self' not found` | removed `self` from the signature → pytest style | **yes** |
| 0052 | `undefined name 'self'` | wrapped in `class TestResolveHandle(unittest.TestCase)` | **yes** |
| 0070 | `undefined name 'self'` | wrapped in a class **again** | **yes** |

Removing `self` from the signature leaves the body's `self.assertEqual(...)` undefined → error B.
Adding the class back makes the standalone function form wrong → error A. It also stripped `self.`
from assertions one at a time across turns 0061, 0078, 0081, 0086, 0093, 0096, 0098, 0099 — while
re-wrapping in a class that requires `self`.

Ping-pong. Eighteen targeted edits, each locally right, that undo one another.

### The uncomfortable part: my own wording enforced it

The reframe note ends *"make the smallest change that clears the failures reported below."* The
model quoted it back at turn 0070:

> *"This is a hard constraint. The user has been clear about the 'small change' principle for
> several turns and is now explicitly telling me to obey it."*

The smallest change that clears `undefined name 'self'` **is** to add the class. The smallest change
that clears `fixture 'self' not found` **is** to remove `self`. Both are locally minimal and the pair
is a cycle. What the file actually needed was to commit to ONE framework and become coherent — which
is not a small change.

So the fix traded a rewrite loop for an oscillation loop, and the "smallest change" clause actively
held the model inside it. That is a real cost and it belongs in the record next to the win.

### The cria gap this exposes — and it is NOT the one I already built for

cria detects **repetition** — `gate_stalled` (the same block twice) and `steer_same_checks` (findings
unchanged since the last steer). Both are "same as last time" tests. An **alternation** A→B→A→B
defeats both by construction: the findings really did change every turn. `steer_same_checks` fired
**0 times** this run; `gate_stalled` only 4.

cria has no notion of "you have been in this state before, two states ago". The model cannot see it
either, because the gate only ever shows the CURRENT findings — never that this exact finding set
already appeared and was already fixed.

**Not building it yet: n = 1.** I shipped the reframe on a measured 33-vs-15 prevalence from attempt
3, which was grounded. This oscillation is one run, and today already contains an example of a
locally-sensible change making things worse. It needs a base rate across the captures first.

### Verdict

Model wall, with a cria-side aggravation of my own making. mellum2 reaches five walked failures and
is recorded **BLOCKED** — not a pass, the language does not complete, and the ladder moves on.


## ada-handles_zaya1_codex_pon_1785633412

**0/4** · planner ON · killed at 15 min · **7 calls total** · 38.6 tok/s
· capture `~/.cria/calls/20260801T181725-019fc00c-1773-7ea0-831d-84ae0a44c9be`

One classifier, six planner, **one coder**. It never wrote a line of code.

```
0001 classifier    17s
0002 planner      207s   116 TOOL CALLS in one response
0003 planner      218s   empty — no tools, no content
0004 planner      123s   plan text
0005 planner      108s   submit_plan
0006 planner      119s   coverage check
0007 planner       51s
0008 coder-s1      50s   ← first and only coder turn, ~13 minutes in
```

The planner consumed **13 of the 15 minutes**. The coder got one turn before the wall.

### The 116-call response

Not repetition — **104 of the 116 arguments are distinct**, and they reference files that never
existed (`/tmp/README.md_before`, `/tmp/README.md_after`). The model generated an entire imagined
session's worth of actions in a single turn, and the harness would have executed all of them.

### The four questions

| | |
|:--|:--|
| false or stale? | No. |
| impossible? | No. |
| withheld? | No. |
| wording? | No. |

**Verdict: model wall.** zaya1 is the fleet's experimental entry — it runs on a local draft-PR
llama.cpp build, and 38.6 tok/s is below its own service-verified 46 t/s. A degenerate first planner
turn plus an empty 218-second second turn is the model, not the harness.

### A guard NOT built, and why

A bound on tool calls per response is the obvious reaction. Base-rated across every capture on the
box first:

```
responses containing tool calls : 9,873
...with 10 or more              :     2   (0.02%)
worst single response           :   292 calls
```

Two events in nearly ten thousand. Principle 15 is explicit that a detector built for a one-off is
dead weight that can itself misfire, so this stays unbuilt and recorded. If a third appears, the
base rate changes and so does the answer.
