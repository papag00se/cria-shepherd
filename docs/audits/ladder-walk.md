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

## What a WALK is

A walk is **reading every call in the run, start to finish** — the whole prompt cria sent and the
whole reasoning the model produced, in order, until you understand the turn. That is the entire
method. There is no faster version of it.

It is **not**:

- a `grep` for a keyword across the capture
- a count, a rate, or an "N of M" over the files
- opening the first and last few and inferring the middle
- reading the verdicts and skipping the reasoning
- re-implementing a check cria already owns and scoring against your version of it

Every one of those has produced a confident wrong answer here. Reading all 46 replies in one set
surfaced four defects that every count over the same files had missed. Reading a plan in full showed
that cria's own plan had mandated a JSON-RPC API the task never mentioned, contradicted itself two
steps later by testing REST, and invented the `--live` flag that made the deliverable score zero —
after two earlier walks of the same run had blamed the model.

If you are about to report what a run did and cannot name the turn numbers you read, you have not
walked it.

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

**P4 — THREE HYPOTHESES, ALL WRONG, AND THE DOCTRINE ALREADY HAD THE ANSWER (2026-08-01).**

The completion brake approves incomplete runs 41% of the time (17 verdicts, 7 wrong). Measured by
model, the failure is not spread evenly:

| model | false done | verdicts | |
|:--|--:|--:|:--|
| gemma4 | 4 | 5 | **80%** |
| mellum2 | 1 | 5 | 20% |
| qwythos | 2 | 14 | 14% |
| ternary-bonsai / qwopus / ornith | 0 | 4 | — |

Three attempts to fix it, each measured on gemma4 — the model carrying the failure — against 8 real
archived workspaces on gemma4's own sampling:

```
1. ask per-deliverable instead of one fused question   split 1/8  vs  fused 3/8   WORSE
2. show what the code DOES instead of its filenames    runtime 2/8 vs  names 5/8   WORSE
3. ...and "names 5/8" is not a score at all
```

The third line is the finding. The filename arm answered **"not done" on all eight cases** — a
constant, not a judgment. Its 5/8 is the class balance (five of eight runs were incomplete), nothing
more. The other arm varied and did worse than the constant.

So gemma4 cannot make this call on any evidence given to it. That is consistent with what was
already recorded: it reads the confirm verdict **0/6**. It carries 4 of the 5 false verdicts because
it cannot do the judgment, not because cria phrased it badly.

**The mistake underneath all three attempts was the same** — searching for a prompt that would make
a weak judge work. Principle 8 is explicit: deterministic code gathers FACTS, a reasoner JUDGES.
"Does this program run and produce the right thing" is a fact. The live-execution check answers it
by running the program and reading the exit code, with no opinion involved, and it is already wired.

**Not shipped, and nothing further to ship here.** The recommendation is to stop asking a judge a
question a deterministic check can answer, on the models measurably unable to answer it.

Method errors worth keeping, all mine:

* I ran the first arm on whichever model happened to be loaded (zaya1 — it timed out), then on the
  fastest good judge (qwythos, 14% failure). The operator pointed out the test belongs on the model
  with the most failures. Convenience is not a sampling strategy.
* My first ground-truth label was "a live test or README is missing" rather than "scored below full
  marks". Both arms shared it so the comparison held, but the absolute numbers did not.
* I nearly recorded "decomposition is worse" as the conclusion. The test could not support it —
  both arms saw only filenames, which cannot distinguish a working file from a broken one.


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

**cria fault: yes** — the plan mandated a JSON-RPC endpoint the task never named and invented a `--live` flag that scored the CLI zero.

> **RE-WALKED 2026-08-01, and the original walk below was WRONG on the central point.** The first
> pass read the workspace and the steers and concluded "it wrote a library, not a program" — a
> model failure. Reading the run properly, every call start to finish, shows cria's own plan caused
> three of the four losses. The original text is kept beneath this note because a walk that was
> wrong is part of the record, not something to quietly overwrite.

### What the re-walk found: the PLAN did it

Every step cria sent, verbatim:

```
[1]  Fetch the API discovery at https://api.handle.me/mcp and read the OpenAPI spec ...
[·]  Write resolve_handle.py ... The script should use requests to call the MCP endpoint
     at https://api.handle.me/mcp with JSON-RPC method get_handle, get_holder, get_stats
[2]  Write test_resolve_handle.py ... Use the /handles/{handle}, /holders/{address}, and
     /stats endpoints with the exact field names from the OpenAPI spec
[3]  Add a CLI option --live to resolve_handle.py that takes handles as arguments
[4]  Write README.md ... how to run the live test (python resolve_handle.py --live goose papagoose)
```

**1. The plan contradicts itself.** The script step mandates MCP/JSON-RPC; the very next step tests
against REST paths. The model built a JSON-RPC client and wrote tests for REST — which is why its
code and its tests never matched.

**2. The plan chose the hard path.** Every model that passed used `GET /handles/goose`. The plan
required JSON-RPC over `/mcp`, and mellum2 spent roughly twenty turns on `curl -X POST` failing to
format the payload. That is where the run died.

**3. The plan invented `--live`.** The task says "create a live test". The plan made it a flag on
the resolver, so `resolve_handle.py goose` prints nothing. The original walk called that "a library,
not a program" and blamed the model. It was cria's instruction. Same shape as the note already on
file: *g25 rewrote a working positional CLI into `--handle` — with cria's help.*

**4. Step 1 never advanced.** The model reported it complete at turns 21, 26, 31, 33 and 38; cria
re-sent it each time. Turn 45 shows the rumination guard aborting mid-stream.

What was genuinely the model: it never once formatted the JSON-RPC payload correctly. But it was
only attempting JSON-RPC because the plan sent it there.

---

### FULL READ (2026-08-01) — all 46 coder turns, end to end

The two earlier passes each read a slice and stopped at the first plausible cause. Reading every
turn changes the picture again. What the run actually contains:

**The curl was a SHELL SYNTAX ERROR, and cria's steer misdiagnosed it as a payload problem.**
Five identical commands, turns 44/46/48/50/63, each ending:

```
... -d '{"jsonrpc":"2025-11-25",...}' https://api.handle.me/mcp'
                                                              ^ unbalanced quote
```

`shlex.split` refuses it — "No closing quotation". The command never executed, not once. The
JSON-RPC payload was correct the whole time. cria's steer told it the payload was malformed, and
the coder recorded that verbatim at turn 50: *"The user is giving me a redirect that explains
exactly what was wrong — the curl payload was malformed."* It then rewrote the payload five times,
re-emitting the same broken quote each time. Five turns of a fifteen-minute budget, spent on a
false diagnosis cria supplied.

**It emits code as PROSE instead of calling a tool.** Turns 51, 67, 73, 79, 92, 103, 106 print a
fenced file into the reply and call nothing. Turn 67 is the sharpest: 12,676 characters that
correctly diagnose its own bug — *"get_total_handles calls _call_mcp('get_holder', …) which is
WRONG… So I wrote resolve_handle.py incorrectly. This is a bug"* — and then print the fix instead
of writing it. Measured fleet-wide: **75 of 653 mellum2 coder turns (11.5%) produce a fenced code
block and no tool call. Every other model is at 0%** except nemotron-elastic at 1.8%.

**It writes to a workspace path that does not exist.** Turns 70 and 71 target
`/tmp/suite_ada_handles_…` — underscores where the real directory has hyphens. Fleet-wide: 26 of
221 mellum2 write/edit calls (11.8%) address a `/tmp/suite…` path that is not that run's workspace;
gemma4 0.3%, everyone else 0%.

**It issues no-op edits.** Turn 68's `edit_file` has `old_string` identical to `new_string`.
Fleet-wide: 27 of 169 mellum2 edits (16%) change nothing.

**It escapes newlines into edits that can never match.** Turn 88's `old_string` carries literal
`\n` two-character sequences and no real newline, so no file can match it. 4 of 125 (3.2%).

**Rumination guard aborted a CORRECT stream.** Turn 45 was cut mid-sentence while writing a working
MCP client.

**It reconstructs an imagined history.** Turn 67 spends thousands of characters enumerating
"Turn 1: User gives plan… Turn 9: Assistant writes test_resolve_handle.py" to work out whether it
had already written a file, and reaches no conclusion.

**Verdict.** The plan defects named below are real but were not decisive — this run scored the
HIGHEST of mellum2's five. What actually consumed it: five turns on a shell quote cria misdiagnosed,
seven turns printing code that never reached disk, two writing to a nonexistent path, and one
no-op edit. The model's reasoning is largely sound throughout; its EMISSION is what fails.

### The original (superseded) walk


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

**cria fault: yes** — same mandated-endpoint plan, plus steers whose prescribed fixes did not execute.

### FULL READ (2026-08-01) — the model reasons well and does nothing

Read end to end. The earlier walk called this a model wall over async mocks. The async diagnosis
was in fact CORRECT and the model reached it repeatedly; what killed the run is that it never
acted on it.

**Eleven consecutive coder turns with no tool call.** Turns 0056, 0057, 0060, 0061, 0062, 0063 and
their neighbours are each thousands of characters of reasoning, all circling `from web_fetch import
web_fetch`, and every one ends without a tool call. Fleet-wide, the longest actionless streak for
EVERY other model is **1** — cria's LEG0 nudge catches a single dead turn and forces action.
mellum2 slips past it eleven times in a row.

| model | longest streak of turns taking no action |
|:--|--:|
| **mellum2** | **11** |
| every other model | 1 |

**Its diagnosis was right.** Turn 0057: *"the test is calling an async function from a sync test…
resolve_handle returns a coroutine, and the with block doesn't raise ValueError because the
coroutine isn't executed."* That is exactly correct for three of the four findings. The fourth was
the `web_fetch` collision, which was unsolvable from inside the run.

**Where `web_fetch` came from — cria's tool name.** Turn 0043, before any error: *"I'll use
web_fetch to GET the URL… I'll use `unittest.mock.patch('web_fetch')` to mock the web_fetch call."*
The model took a TOOL it had been given and wrote it into its source as an importable module. A
stray PyPI package of the same name then resolved the import instead of failing cleanly, turning a
clean ModuleNotFoundError into "'module' object is not callable" — an error with no reachable
explanation. Both halves of that are now closed (the package is gone; preflight refuses to start
while any package shadows a cria tool name). The tool NAME remains.

**cria's truncation guard fired here too** (turn 0053): *"my previous attempt to write the file was
cut off at ~43k tokens and nothing was saved."* Its remedy — build the file in small pieces with
edit_file — is correct, and it is the mode attempt 5 then oscillated inside.

**Verdict: not a model wall. An EMISSION wall.** The reasoning was sound; eleven turns of it
produced no file, no edit, no command.


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

**cria fault: yes** — cria deleted the unit-test, live-test and README steps from its own plan (two numbering systems in one list), approved a step against an empty workspace, and shipped two steers stating things that were false.

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

**cria fault: yes** — a filtered fetch showed 2 of 33 endpoints and pointed at a file it never saved; the compaction briefing was 79% of one coder prompt and told it 145 times not to act.

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

**cria fault: yes** — self-compaction had no closing ask, so the compactor obeyed the coder's step and cria adopted a hallucinated test file as the session summary.

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

**cria fault: yes** — the URL grounding check truncated path templates and produced false UNVERIFIED steers.

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

---

## Fix batch — 2026-08-01, from the full-read walks of mellum2 attempts 3, 4 and 5

Six defects, every one verified against the captures before it was touched. Where an agent's report
is quoted, the quote was re-checked against the file; two of my own measurements were wrong first
time and are recorded as such, because that is the point of 23b.

### 1. A filtered fetch and a plain fetch answered the same document differently

`cria/webfetch.py::_fetch_and_render`. The `find=` branch windowed the match and appended
*"grep the saved ./tmp file"* — a file **that branch never saves**. The spill and the route outline
live only on the no-`find` path.

Measured, run `ada-handles_mellum2_codex_poff_1785626379` call 0016: `find="paths"` against a
186,444-character OpenAPI spec returned **2 of 33 endpoints**, `"/"` and `"/mcp"`. `handles/{handle}`
appears **0 times** in that prompt; the first prompt in the run containing it is **0152**, of 225.
The model built a JSON-RPC MCP client because those two were the only routes it had ever been shown.

Three faults in one branch: a false fact (a file that does not exist), a withheld fact (31 endpoints),
and a silent divergence between two spellings of the same request. Fixed: the find path spills too,
and the message names the real file and offers the outline.

### 2. The protocol probe was switched off exactly when the model dug hardest

`apidiscovery.discover` was gated `if not raw and not find and not cursor`. Every `/mcp` fetch from
call 0019 to 0034 carried `find=` or `raw=`, so the JSON-RPC contract the run needed — *method
`tools/call`, params `{name, arguments}`* — was never probed. It surfaced at **0209**, sixteen calls
before the kill, from a plain fetch. Now gated on `raw` alone; `raw` is the model asking for
untouched bytes and still opts out.

### 3. Self-compaction put cria's ask FIRST

So the transcript ended on the coder's live step. All five compactor calls in run `…1785625253`
obeyed it and wrote code instead of a briefing. In `…1785628543` one degenerated to `v5v5v5…` and
cria adopted a hallucinated `unittest` file as `⟦ctx:rollup⟧ Summary of your earlier turns this
session`; the coder believed it — *"The user has given me a test suite"* — and that is how
`unittest` entered a pytest run. `da35f4e` fixed exactly this on the harness path and never reached
its sibling.

### 4. A briefing that quotes cria's own ask back is not a briefing

Counted in the coder's prompt at call 0063 of `…1785626379` — 68,914 characters, of which the
injected continuation block was 54,274 (**79%**):

```
"Do not emit a tool/function call"   x145
"What you should say instead"        x47
```

Both are cria's words, from `selfcompact_summary.txt`. The coder read them and said so — *"This is
contradictory. The continuation says 'fix search_handles' which IS writing code. The continuation
also says 'Do not write code.'"* — and emitted no tool call. It never recovered: at **0084**, twenty
calls later, the coder's own answer to the user still ENDED with that block, and it reappears
verbatim at 0089 and 0207. Every compaction after the first collapsed identically.

`strip_frame_echo` already dropped lines echoing cria's serialization FRAME and already failed safe
when everything was echo. It now also drops lines echoing cria's INSTRUCTION — which needs no
judgment, because cria composed it.

### 5. `degenerate_tail` only recognised a repeated CHARACTER

The real streams were two wide: `y8y8y8…` for **40,759 tokens** — five minutes of a fifteen-minute
run — and `v5v5v5…` inside the compactor. Now catches repeating units up to 8 characters.

### 6. A step naming an artifact was approved against an EMPTY workspace

The one that killed attempt 3. Run `…1785625253` calls 0034 / 0038 / 0041, step *"Write a CLI script
`resolve_handle.py`"*, inventory *"the workspace has no files at judging time"*. Call 0038's verdict
refutes itself in its own reason:

> `{"done": true, "reason": "workspace has no files, so the claimed resolve_handle.py does not exist … I default to DONE per instructions."}`

The reasoned brake rejected it twice, then ruled `consistent: true` on the third identical listing.
cria advanced to *"write unit tests importing resolve_handle"* and the last 40 turns of the run were
`ModuleNotFoundError: No module named 'resolve_handle'`.

An empty workspace is **ground truth, not a judgment call** (principle 8): every file the step names
is absent, whichever way you read the step. So it is settled before the reasoner is asked, and cannot
be talked out of.

Base-rated over all 135 captured critic verdicts with an inventory: 92 approvals, **7** named a file
not on disk. Only the 3 empty-workspace ones are blocked. The other 4 had files present, where a
named file may be one the step merely *mentions* (a README step naming the module it documents), and
blocking those would be a guess.

*My first base-rate of this returned 0 of 125 — my scorer looked for `THE STEP`, and cria's label is
`STEP:`. The measurement was of my regex, not of cria. 23b, again, on the same day it was written.*

### 7. A turn that PASTED the file is not a claim that the step is done

Both driver halves read a coder turn with no tool call as *"it thinks the step is done"*. That is a
bet on a model trait. Measured over **every captured coder turn**:

| model | prose-only turns | total | rate |
|:--|--:|--:|--:|
| gemma4 | 0 | 3,955 | **0.0%** |
| qwopus | 1 | 29 | 3.4% |
| qwythos | 36 | 795 | 4.5% |
| **mellum2** | **192** | **653** | **29.4%** |

Nearly a third of mellum2's turns were being read as completion claims and spent on a probe
round-trip plus a critic call. They are not completion claims. Read in full, run `…1785625253`:
**call 0012 is the complete resolver typed into chat**, and **call 0033 is a polished rewrite of it**
— correct base URL, correct `GET /handles/{handle}`, argparse CLI, typed dataclass — with no
`write_file` call anywhere. That run scored **0/4 with its own finished deliverable sitting in the
transcript**.

A summary of finished work does not paste the file; a model that failed to emit the call does. Not a
new assist — a wrong inference removed. Bounded at 2 nudges per step, then it falls through to the
gate exactly as before. Landed in BOTH halves, with a test asserting it.

### Still open from these walks

- A steer may name an API symbol that appears in no captured tool result. `get_holders` (real name
  `get_holder`), `my.handle` (the spec's placeholder, offered as a handle "you know resolves"), and
  `get_handle(…)` (no such function) were all invented and all obeyed. `urlgrounding` enforces this
  for URLs and routes; method and field names have no equivalent.
- cria told the coder *"'goose' does not resolve to an address"* at 0056 and repeated it six times.
  It resolves — `GET /handles/goose` → 200, holder `stake1u85prp8…`. The coder obeyed instantly and
  rewrote every test to a placeholder handle, deleting the task's own word from the test file.
- The check summariser reports the LAST traceback frame, which for a mock failure is
  `/usr/lib/python3.12/unittest/mock.py:1193`. Forty turns of fixes were pointed at the standard
  library. It should walk back to the last frame inside the workspace.
- The planner's spill note offers `read_file` with a `start_line`/`end_line` range; the planner's
  `read_file` takes a path only. The planner reasoned *"Read it with a line range: roughly lines
  70-120"*, called it with a path, and cria dumped 96,538 characters into its window.
- The whole-file-rewrite recovery pastes the disk bytes without the newest evidence. At 0198 it
  anchored the model back onto an endpoint it had disproved one turn earlier.
- The bullet fallback in `planner.py` drops each bullet's indented detail lines; the numbered path
  (`_numbered_with_details`) preserves them. That is where a step lost its endpoint and field names.

---

## ada-handles_zaya1_codex_pon_1785644114

**cria fault: yes** — cria never told the planner where the workspace was, so it invented a path and read five imaginary files 140 times.

**0/4, killed at the 15-minute floor. 8 model calls total: 1 classifier, 7 planner, and
zero coder.** The run never reached the coding model at all. Every call read in full.

| call | finish | completion tokens | what it did |
|:--|:--|--:|:--|
| 0001 classifier | stop | 675 | correct — `{"engagement":"task","task_type":"coding"}` with an accurate restatement |
| 0002 planner | **length** | 8,192 | pure reasoning, no tool call, no content — the whole budget burned thinking |
| 0003 planner | **length** | 8,192 | **138 tool calls**, 32 distinct |
| 0004 planner | **length** | 8,192 | **134 tool calls**, 16 distinct |
| 0005 planner | stop | 570 | no calls, no content |
| 0006 planner | stop | 6,583 | finally drafted a plan |
| 0007 planner | stop | 3,245 | coverage judge: `{"missing": []}` |

Prompt sizes tell the same story: 6 KB, 7 KB, **56 KB**, **105 KB**, **105 KB**.

### Question 3 — did cria WITHHOLD something it already held? **Yes. This is the run.**

cria gives the planner `read_file` and `exec_command`, resolves every one of those calls against
`cwd` internally, and **never tells the planner what `cwd` is**. No path, no cwd tag, no listing —
I read the entire 0002 prompt to confirm it, system message to final token.

So the model guessed. It invented `/workspace/dumps/workspace` and read, under it, `README.md`,
`requirements.txt`, `setup.py`, `pyproject.toml`, `Dockerfile`, `package.json` and
`.github/workflows/test.yml` — over and over, in blocks of six, for two entire rounds.

Measured across every captured prompt in `~/.cria/calls`:

| prompt | names the workspace | share |
|:--|--:|--:|
| critic | 292 of 331 | **88%** |
| planner | 31 of 481 | **6%** |

cria renders that exact ground truth for the critic on nearly every call and withholds it from the
one role it hands a filesystem to.

**Fixed** — the planner now gets the critic's own inventory. `workspace_inventory` moved from
`loop.py` to `groundtruth.py` so both can import it (loop imports planner, so planner cannot import
loop); one owner, not a copy. No cwd still means no section — cria must not invent a root either.

### Second fault — rounds were bounded, calls per round were not

Measured over every captured planner round (n=328, 719 calls issued): **236 — 32.8% — are exact
duplicates of another call in the same round.** This run is the extreme: 138 calls of which 32 were
distinct, then 134 of which 16 were. Four of them were `curl` against the live API with the identical
request.

**Fixed** — each distinct call executes once. Nothing is withheld: every distinct call still runs in
full and every `tool_call_id` still receives its own complete result, so the protocol stays
well-formed and the model sees exactly what it asked for. Only the re-execution goes.

### Not fixed, and recorded rather than guessed at

Three of the seven planner responses ended at `finish_reason: length`, and cria executed a tool-call
list the model had not finished emitting. That is a real gap — the coder has `guard_truncation` and
the planner has no equivalent — but the right handling is not obvious (re-ask, or execute what
parsed and disclose the cut), and with the two causes above removed the flail that produced those
8,192-token responses may not recur. Re-measure on the next zaya1 attempt before building anything.

### Questions 1, 2 and 4

- **False or stale?** No. The planner prompt states nothing untrue; its fault is silence, not error.
- **Impossible?** No.
- **Wording?** Not the wording — the omission.

**Model wall: not reached.** zaya1 planned a reasonable 6-step plan at 0006 once it stopped
thrashing, and the coverage judge passed it. It never got to code.

---

## ada-handles_zaya1_codex_pon_1785645441

**cria fault: yes** — cria executed tool-call lists from replies the model never finished emitting.

**0/4, killed at 15 minutes. 5 model calls: 1 classifier, 4 planner, zero coder.** Every call read.

The previous run's workspace fix **worked** — the planner now reads the real path
(`/tmp/suite-ada-handles_zaya1_codex_pon_1785645441-d6s14rvf/`) instead of an invented one. That
cause is closed. The run still died, of a second cause the first was masking.

| call | finish | tokens | calls | distinct |
|:--|:--|--:|--:|--:|
| 0002 planner | **length** | 8,192 | 95 | 13 |
| 0003 planner | **length** | 8,192 | 100 | **6** |
| 0004 planner | **length** | 8,192 | 92 | 92 |
| 0005 planner | **length** | 8,192 | 93 | 93 |

Every reply filled the entire output budget with tool calls and was cut off mid-emission. cria ran
them anyway. 0003 is 98 `exec_command`s of which nearly all are the same `curl` against the live API;
0004 and 0005 are "distinct" only by string equality — the same command wearing different tails
(`|| echo "not found"` vs `|| echo "error"`). One call in 0005 is not a command at all, it is the
model's reasoning leaking into the argument and sliced mid-sentence:

> `{"cmd":"shamefully I cannot make HTTP requests directly via exec_command? Actually exec_command can run shell commands, including`

### The signal is `finish_reason`, and it is clean

Measured over every captured planner round in `~/.cria/calls` (n=333 rounds with tool calls):

| | |
|:--|--:|
| rounds with `finish_reason: length` | **8** |
| rounds emitting more than 12 distinct calls | **7** |
| of those 7, how many are cut off | **7 — all of them** |
| median distinct calls in a healthy round | **1** |
| p90 distinct calls in a healthy round | **1** |

A healthy planner round makes one call. Every runaway round is a cut-off round. No threshold on call
count is needed and none was added — the model telling you it did not finish is the whole signal.

`_reason` was **discarding `finish_reason` entirely**, so cria could not distinguish a finished reply
from a truncated one and executed tool-call lists the model never finished emitting.

**Fixed** — the finish reason is now carried out of `_reason` on a private key the gather never puts
on the wire, and a cut-off research round is refused rather than executed: re-ask once, plainly
("your last reply was cut off, so none of its tool calls were run — make a few at a time"), then take
what parses. Exactly the contract `guard_truncation` has enforced on the coder's partial writes since
the file-corruption loop.

### The dedup from the last fix did fire

0003 went from 100 executions to 6. It was not enough on its own, because 0004 and 0005 varied their
commands just enough to defeat exact-match dedup. That is the right division: dedup removes waste,
the cut-off refusal removes the runaway that produced it.

### Questions

- **False or stale?** No.
- **Impossible?** No.
- **Withheld?** Not this time — the inventory fix closed that.
- **Wording?** No. cria's fault here is *acting on* a reply the model never finished.

**Model wall: not reached.** zaya1 has never been given a chance to code. Three attempts, zero coder
calls in all three.

---

## ada-handles_zaya1_codex_pon_1785647676

**0/4, killed at 15 minutes. 8 calls: 1 classifier, 7 planner, zero coder.** Fourth zaya1 attempt,
fourth run that never handed anything to the coding model.

**cria fault: yes** — three of them, one of which had been sitting in cria since the beginning.

The previous run's fixes held: the planner reads the real workspace path, and the runaway 90-to-138
call rounds are gone. What replaced them was worse and more revealing.

| call | finish | tool calls | content | reasoning |
|:--|:--|--:|--:|--:|
| 0002 | length | **0** | 3,838 | **27,089 chars** |
| 0006 | length | **0** | 0 | **31,475 chars** |
| 0008 | tool_calls | 2 | 0 | 2,600 |

### The prompt, read in full

The user turn zaya1 receives is, in order: the workspace inventory, then the task verbatim —
*"I would like you to write a Python script … When you're done, add a README"* — then
`<|im_start|>assistant`. **cria's planning instruction is in the SYSTEM message, far above it.**

### The reasoning, read in full — it is not failing to plan, it is refusing to

Its own words, call 0002:

> *"We can place everything in a single response."*
> *"We'll call web_search with query … **Let's simulate in our mind**."*
> *"We'll use web_fetch. But we might not have internet access. **However, we can simulate.**"*
> *"We must be careful not to include any extraneous text like **'Step 1: …'**. The answer is just
> the deliverables."*

It decided its job was to deliver the finished files, and it **simulated** its tool calls instead of
emitting them — which is the entire explanation for four runs of near-zero tool calls. Word counts in
that one reasoning block: `script` 86, `readme` 35, **`plan` 4**.

**Fault 1 — cria's ask is not last.** The model obeys the last instruction it reads, and the last
instruction it reads is "write a Python script". This is the SAME defect as `da35f4e` (harness
compaction), `e72a0e9` and `5d2b119` (the two self-compaction paths) — a fourth instance of one
ordering bug. Fixed: the seed now ends with cria's ask, stated generically.

**Fault 2 — no reasoning-off retry on the planner.** A round that spends its whole budget thinking
and emits nothing is retried thinking-off on the CRITIC — 21 uses in `loop.py`, and the critic's own
note says exactly why. In `planner.py`: zero. Measured across all 499 captured planner rounds, 15
were cut off at the cap and 5 produced nothing at all, behind 26,337 / 28,936 / 31,248 / 31,475 and
106,829 characters of reasoning. Fixed.

**Fault 3 — mine, from the previous fix.** Sharing the critic's inventory with the planner also
shared its wording: *"on-disk ground truth **at judging time**"*. The planner judges nothing and read
that on every round. Fixed with a planner flavor.

**Also corrected here:** the cut-off guard I shipped one run earlier was wrong twice — it refused
rounds whose calls had all arrived intact (5 of 8 in the captures), and on rounds with no calls at all
it told the model *"none of its tool calls were run"*, which was untrue. Now only a trailing
unparseable call is dropped, and the note only fires when calls were present.

**Model wall: not reached.** zaya1 has never been given the chance to write a line of code.

### Not yet tried: planner OFF

All five zaya1 rows are `pon`. Every failure has been a planner failure. Planner-off skips the
planner entirely and would answer the question no run has answered yet — whether this model can code
at all.

---

## ada-handles_zaya1_codex_pon_1785649909

**0/4, killed at 15 minutes. 8 calls: 1 classifier, 7 planner, zero coder.** Fifth zaya1 attempt.
Read call by call, prompt and reasoning, first to last.

**cria fault: yes** — search results were never spilled, the compaction note repeated one identical
error 89 times, and the digest had been rewriting text through a function-word stripper.

### The ask-last fix WORKED — this is what changed

Attempt 4's planner refused to plan and simulated its tool calls. This one, call 0002, in its own
words:

> *"We have to provide a short numbered list of steps another model will follow to do it."*
> *"We **must not** produce the actual script or README; just the steps for another model to follow."*
> *"We need to use a tool now — a real call. Which tool? Possibly web_fetch to get the API spec."*
> *"We'll call web_fetch with url `https://api.handle.me`."*

Reasoning fell from **27,089 characters to 2,641**, because it stopped writing the deliverable in its
head. It emitted real calls instead of describing them. By rounds 5 and 6 it had settled to **one
call per round**, which is the healthy median across all captures — the cut-off steer landed and it
said so: *"We have to do one call at a time. Let's do that."*

### What 119 tool calls actually were

Counting said "119". Reading said:

- **calls 0–5** — purposeful: `web_fetch https://api.handle.me`, then targeted searches, then `pwd`.
- **calls 6–14** — fabricated: `read_file {"path":"/tmp/README.md (placeholder)"}`. It is putting the
  word *(placeholder)* in the path and reading files it wishes existed.
- **calls 26 onward** — one three-call cycle (`ADA-HANDLE_TO_TEST`, `handle_goose.ada`,
  `papagoose.ada`) repeated ~30 times to the token cap. A degenerate loop, the same shape as the
  `y8y8y8` character repetition one level up.

It emits all 119 before seeing a single result, so nothing interrupts it. Call 0003 confirms it:
*"**We haven't seen the result.** Let's assume the result is something like the Swagger/OpenAPI
spec."*

### Fault 1 — cria's compaction was rewriting the task

Those calls blew the window. The compacted note that came back had been run through
`content_reduce`'s prose tier, which **deletes function words**:

| | |
|:--|:--|
| task, before | "I would like you **to** write **a** Python script that accepts **an** Ada Handle **as** input and resolves it **to the** Cardano address" |
| task, as sent | "I would like you write Python script that accepts Ada Handle input and resolves it Cardano address" |
| cria's own ask, before | "The request above **is** what the WORK **is** — **it is** not addressed **to** you" |
| cria's own ask, as sent | "The request above what WORK — it not addressed you" |

And one line was **inverted**, not merely degraded. cria's own fetch note *"no endpoints or field
names could **be read from** it"* reached the model as *"could read it"* — turning "nothing was
learned here" into a claim that something was.

`strip_prose_text` calls these "certain-junk function words". They are not junk. The output reads as
fluent English and is not, which is worse than truncation because truncation is visible.

**Fixed** — the digest no longer word-strips.

### Fault 2 — the note repeated one error 89 times

The note ran to **22,149 characters across 117 bullets, of which 25 were distinct**.
`{"error":"route_not_found","message":"Route not found: /info"}` appeared **89 times**; repeated
bullets were **42% of the note's characters**. The model had emitted the same failing curl in a loop,
and cria replayed the identical failure back at it 89 times.

**Fixed** — consecutive identical digests collapse to one line with the count. Lossless: nothing
reworded, nothing cut, and runs collapse separately so ordering still carries information.

### Fault 3 — search results were never spilled

The fetch path has saved oversized bodies to the scratchpad for a long time. `_web_search` returned
its results **inline** and always had. One search for "README.md generation guide install run script
tests" put **9,269 characters** into the planner's context — npm packages, Reddit threads, jest
configs, valkey test docs — none of it about the task, and it survived verbatim into the compaction
note and was still there at call 0004.

**Fixed** — spilled like its sibling: the full list on disk, the pointer and the titles in context.

### A fix of mine that was wrong, and was reverted

Between this run and the next I added a digest that CUT prose to the cap and labelled the cut. Shown
a real example it was cutting **mid-word** — `...ithub.com/matiassi` — out of exactly the
search-result noise fault 3 removes. That is a truncation, and it was treating the symptom: reaching
for a size fix before removing the redundancy and the noise. Reverted to keep-or-disclose.

### Verdict

**Model wall: not reached.** Five attempts, zero coder calls. Every one has been a planner failure,
and every one has found a cria fault. Planner-OFF has still never been tried and remains the
experiment that would answer whether this model can code at all.

---

## ada-handles_mellum2_codex_pon_1785651890

**3/4 — mellum2's best ever, and its first run to clear the milestone floor.** 195 calls, 26 minutes,
165 t/s. Previous best across five attempts was 2, and three of those scored 0.

**cria fault: yes** — the unexecuted-write guard shipped this morning could not see a pasted README.

### What it actually built

| check | verdict |
|:--|:--|
| unit tests | **pass** — 4 passed in 1.24s |
| live test | **pass** — "2 passed with network, fails without (provably live)" |
| resolver CLI | **pass** — `resolve_handle_with_count.py goose` → address + holder + count |
| README | **fail** — "covers install/run/tests: False" |

The README on disk is genuinely good: it documents all three modules with usage examples and
`python3 -m pytest`. What it lacks is the **install** section. The plan's own step 5 asked for it —
*"Write README.md that explains the dependencies (requests), how to run the script, how to run the
tests"* — so the plan was right and the deliverable was one section short.

### The coder wrote that section. Three times. It never reached disk.

Calls 0178, 0183 and 0187 each emit a complete README **with `## Installation` and
`pip install requests pytest`** — as a fenced block in `content`, with no tool call.

The guard shipped this morning exists exactly for that and did not fire. A pasted README is a
` ```markdown ` block containing ` ```bash ` blocks, and the guard toggled an inside/outside flag on
every fence line — so the inner CLOSING fence read as opening a new block and the run of lines never
reached the threshold. Measured over this run's 12 tool-call-less turns carrying a fenced block: it
caught 7 and **missed 5**, four of which were that README.

**Fixed** — depth tracking rather than a toggle. Re-measured on the same captures: 11 of 12 fire, and
the one that does not is a turn of prose complaining about the prompt, which is not a pasted file.

### What worked, and is worth recording

- Call 0186 attempted `edit_file` with a stale `old_string`; cria's edit recovery answered *"your
  old_string is not in the file (likely a stale copy). Read the file to get its exact current text"* —
  correct, and the model had in fact read the file four calls earlier and then edited against memory.
- No false facts, no impossible instructions, no withheld ground truth found in this run.
- The plan named the right endpoints from the spec cria surfaced, and the coder built to them.

**Model wall: not reached.** One markdown section short of 4/4, and the model produced that section
three times.

---

## ada-handles_mellum2_codex_pon_1785653778

**3/4 again — and a DIFFERENT deliverable.** 111 calls, 12 minutes, 178 t/s.

**cria fault: yes** — the critic approved a step against evidence that disproved it, in its own reason.

| check | attempt 1 | attempt 2 |
|:--|:--|:--|
| unit tests | pass | pass |
| resolver CLI | pass | pass |
| README | **fail** | **pass** ← the depth fix worked |
| live test | pass (provably live) | **fail** |

The README fix landed: `README.md covers install/run/tests: True`. Two consecutive 3/4s with
non-overlapping misses means this model can produce all four — just not yet in one run.

### The live test works. It just is not a test.

I ran it, both ways:

```
$ python3 live_test.py            → {"error": "Usage: live_test.py <handle1> ..."}   exit=1
$ python3 live_test.py goose      → goose's real address, holder stake1u85prp8…, 15 handles   exit=0
```

Real network, real data, correct code. But the deliverable is scored by running it, and run with no
arguments it exits 1.

### The plan was right; the critic was not

Plan step 3: *"Write live_test.py: a standalone script that calls the real API ... to resolve the
handle **'goose' and 'papagoose'** and prints the results."* Step 4 even says how it is run —
*"how to run the live test (**python live_test.py**)"*, no arguments. The coder built something that
contradicts both.

cria's critic ruled `done: true`, and its own reason contains the disproof:

> *"live_test.py exists and calls the real API to resolve handles ... **and prints a usage message
> when no handle is provided**. The step is fully satisfied."*

It observed that the file does not resolve those handles by itself, and called the step satisfied.

**Fixed** — cria now gathers the fact and puts it in the critic's evidence: *the step quotes 'goose',
'papagoose'; live_test.py contains neither.* Deterministic code gathers, the reasoner judges
(principle 8); the note states in as many words that it is not a verdict and the critic decides.

Base-rated across every captured critic approval (n=106 with a workspace and a parseable verdict) it
fires **once**, on exactly that verdict, with no false positives. One occurrence in 106 does not earn
a hard gate — which is why it is evidence, not a block.

**Model wall: not reached.**

---

## ada-handles_mellum2_codex_pon_1785654712

**0/4** after two consecutive 3/4 runs. 145 calls, killed at the 15-minute floor.

**cria fault: yes** — the living replanner wrote one of cria's own tool names into the deliverable's
design, and the coder built to it.

| check | detail |
|:--|:--|
| unit tests | fail — **9 errors in 0.01s**, all at collection |
| live test | fail — no live-test file |
| resolver CLI | fail — `cli.py goose: exit=1` |
| README | fail — none written |

### The surface error is not the cause

All nine errors are `fixture 'mocker' not found` — the model wrote `pytest-mock` tests in an
environment without it. But running the workspace shows the deeper break: `resolve_handle.py` ships

```python
resp_text = web_fetch(url=url)
```

with no import and no such function anywhere. pyflakes says `undefined name 'web_fetch'`. Every unit
test mocks a function that does not exist, so they error before they run.

**`web_fetch` is one of cria's own tool names.**

### Where it came from — cria, not the model

The INITIAL plan is clean. Step 4: *"Write unit tests that mock the API call ..."*

The living re-derivation at **call 0064** rewrote it:

> *"Write unit tests for resolve_handle and total_handles_for_holder with fixtures for a known handle
> (**mock web_fetch** to return a successful response), a not-found handle (**mock web_fetch** to
> raise an exception) ..."*

That step reached the coder from call 0068 onward and was judged four times. The coder read it and
built production code around a harness tool. Its reasoning at 0108 shows it trying to rationalise the
step it was given: *"The import should be something like `from unittest.mock import patch` or
`from pytest_mock import mocker`... `undefined name 'web_fetch'` suggests the line is
`from web_fetch import web_fetch` and that module doesn't exist."*

The replanner's own system prompt already forbids this: *"Any tool list you are shown belongs to the
coder, so the steps you write are things IT can do."* A prompt is a request, not an enforcement —
which is the sentence `urlgrounding` was written for.

### What cria got RIGHT here

The gate ran, and the exact error text reached **27 coder prompts**. cria did not hide the failure or
speak over the tool. The coder simply could not satisfy a step that was impossible as written.

**Fixed** — a re-derived tail naming a coder tool as code the deliverable calls/mocks is REFUSED, and
the step that was already correct stands. Framing is the discriminator and it is the model's own:
"web_fetch the spec" is an instruction to the agent and passes; "mock web_fetch" describes the
product and does not. Base-rated over every captured judged step (n=372): 4 hits, all this run, all
this one step. cria never rewrites a plan step — it declines the bad tail, exactly as it already
declines a tail that drops deliverables.

**Model wall: not reached.** Score variance across three runs on near-identical code — 3, 3, 0 — is
also a reminder that one number is not signal.

---

## ada-handles_mellum2_codex_pon_1785656001

**3/4 — third 3/4 in four runs, and the miss moved a third time.** 375 calls, the FULL hour (it
earned every 15-minute interval by delivering), killed at 60 minutes.

**cria fault: yes** — cria spent the run pointing the coder at a line inside Python's standard library.

| check | a1 | a2 | a4 |
|:--|:--|:--|:--|
| resolver CLI | pass | pass | pass |
| README | fail | pass | pass |
| live test | pass | fail | pass |
| unit tests | pass | pass | **fail** |

Three runs, three different single misses. This model can produce all four.

### What failed, run rather than read

```
FAILED test_resolve.py::test_resolve_valid_handle  - AssertionError: assert 'N/A' == 'addr1'
FAILED test_resolve.py::test_resolve_404_returns_na - Exception: 404
FAILED test_resolve.py::test_resolve_network_error  - Exception: Network error
```

The tests mock `raise_for_status` to raise; the resolver never catches it, so the exception escapes
instead of returning the `'N/A'` the tests expect. A real, small, fixable mismatch.

### cria told it to fix the standard library

The last steer of the run, verbatim:

> `• /usr/lib/python3.12/unittest/mock.py:1193: Exception: 404`
> `• /usr/lib/python3.12/unittest/mock.py:1193: Exception: Network error`

`parse_pytest` took `locs[-1]` — the last traceback frame — while its own docstring claimed that
"gets the real test-file location". When a mock raises, the deepest frame is inside the interpreter.

Base-rated over every captured coder prompt carrying a check block (n=2,836): a stdlib or
site-packages `file:line` appears **7,888 times across 48 runs** — `mock.py` alone 2,680, then
`__init__.py` 1,461, `rewrite.py` 825, `ast.py` 549. This is systemic, not a quirk of one run.

It was also **already recorded as an open finding** from the mellum2 attempt-4 walk — *"forty turns
of fixes were pointed at the standard library"* — and had not been acted on until now.

**Fixed** — the finding now names the deepest frame in the coder's OWN code, falling back to the last
frame only when none qualify (the failure is then genuinely outside the workspace, and saying so
beats inventing a location).

### Also seen, not yet acted on

The workspace holds **both** `resolve-handle.py` and `resolve_handle.py`. The hyphenated one is not
importable in Python, and the last steer records the coder repeatedly reading it
(`read_file {"path": "resolve-handle.py"}`). mellum2's self-corrupted-path habit is recorded from
earlier walks; measure it before building anything.

**Model wall: not reached.**

---

## ada-handles_mellum2_codex_pon_1785659842

**1/4, and the session EXITED after 181 seconds / 40 calls.** An early exit is the failure class this
project has fought hardest, so this one is worth reading closely.

**cria fault: yes** — cria deleted the unit-test and live-test steps from its own plan, then ended
the session because the plan it had left was finished.

### The chain, in order

1. The planner drafted a **four**-step plan. The coverage judge saw it at call 0008 and approved:

   ```
   1. Write resolve_handle(...)                                  ← built
   2. Write unit tests for resolve_handle with 3-4 test cases     ← DELETED
   3. Write a live test script live_test_goose.py ...             ← DELETED
   4. Write README.md that documents (a) install (b) run (c) tests ← built
   ```

2. The living replan's **noise judge** (call 0025) answered `1, 2, 4` and cria dropped those
   indices — `loop.replan_noise dropped=2 kept=1`. Unit tests and the live test were gone.

3. `missing_deliverables`, the reasoner brake that exists precisely to refuse a tail that drops
   deliverables, said nothing was missing. It did not fire.

4. Both surviving steps completed and verified. The plan mirror ends:

   ```
   - [x] Write resolve_handle(...)   > verified
   - [x] Write README.md             > verified
   ```

5. The satisfaction judge was then asked whether the task was done — and with an empty plan it said
   yes, inventing the missing work in its reason: *"unit tests for goose and papagoose are written;
   README includes installation, usage, and a live test for the specified handles."*

6. The confirm brake **called `list_dir` and saw the disproof**:

   ```
   .git/   README.md (859 B)   __pycache__/   resolve_handle.py (1419 B)   tmp/
   ```

   No test file. No live test. It answered `{"consistent": true, "why": ""}`.

The task text is unambiguous — *"Unit tests are required. Separately, create a live test…"* — and
this is the SECOND time in this ladder that the noise judge has deleted deliverable steps (see
`ada-handles_mellum2_codex_pon_1785625253`, where it removed unit tests, the live test and the
README).

### Measured before proposing anything

Across every log day:

| event | count |
|:--|--:|
| `loop.replan_noise` | 156 |
| …that dropped at least one step | 75 |
| …that left **zero** steps kept | **37** |
| `loop.replan_uncovered` (the deliverables brake FIRING) | 34 |

So the brake does work, and often. It failed on this instance. That is a judge miss, not a missing
mechanism — and adding a second heuristic layer on one data point is the footgun this project's
doctrine exists to prevent.

**Not fixed yet, deliberately.** What is needed first is the DROPPED STEP TEXTS, which the logs do
not currently carry — `loop.replan_noise` records counts, not what went. The next step is to log the
dropped text and then base-rate how often a deleted "noise" step names a deliverable. A step naming a
concrete file artifact (`live_test_goose.py`) is definitionally not strategy noise, and that is the
candidate rule — but it should be measured, not assumed.

**Model wall: not reached.** The model built what it was asked to build; it was asked for half the task.

---

## ada-handles_mellum2_codex_pon_1785660278

**0/4.** 68 calls, killed at the 15-minute floor.

**cria fault: yes** — the noise judge deleted the live test and the README from the plan, and this
time the log proves it directly.

The dropped-step logging added one run earlier caught it on its very first outing:

```
loop.replan_noise  dropped 2  kept 1
  "Write live_test.py: call GET /handles/goose, print resolved_address, holder_address, total_handles"
  "Write README.md: install requirements (requests, pytest); run script; run tests; explain two-step resolution"
```

The verifier then reported `no live-test file found` and `no README` — precisely the two steps
deleted. No reconstruction from captures needed; the log says it.

**Third occurrence in this ladder**, and the first one measured rather than archaeologically
recovered:

| run | deleted | outcome |
|:--|:--|:--|
| 1785625253 | unit tests, live test, README | 0/4 |
| 1785659842 | unit tests, live test | 1/4, **session ended in 181 s** |
| 1785660278 | live test, README | 0/4 |

`missing_deliverables` is the reasoned brake for exactly this, and it works — 34 firings across every
log day. It is a judge, and it missed all three.

**Fixed** — a step that says to WRITE a file is definitionally not strategy noise, so it is settled
deterministically before any judgment. The judge's real targets are untouched: "Error handling
strategy.", "Run the tests", "Set up the development environment".

Authoring intent is the discriminator, not the presence of a filename — an existing test caught that
within a minute. `grep -n 'resolve' spec.json` names a file and IS the bare-command noise this judge
should delete; it stays droppable.

**Known limit, recorded rather than papered over:** *"Write unit tests for resolve_handle with 3-4
test cases"* names no file and is NOT protected. Two of the three cases above are covered in full;
that one is not, and a test asserts the gap so it cannot be quietly assumed away.

**Model wall: not reached.**

---

## ada-handles_mellum2_codex_pon_1785661463

**3/4 — fourth 3/4 in seven runs.** 219 calls, the full hour. Unit tests the only miss.

**cria fault: yes** — my own previous fix was incomplete, and this run proved it.

### The good news first

The noise judge did NOT delete a deliverable this run, and the pytest steer named a real workspace
line — `test_resolve_handle.py:105: AssertionError: assert '' == 'holder2'` — not a stdlib frame.
Both fixes from the previous two runs held where they applied.

### Where my fix did not reach

I reported the stdlib-frame fix as working. It was only partly working. This run still showed the
coder:

```
/usr/lib/python3.12/json/decoder.py:355    x13
/usr/lib/python3.12/json/decoder.py:337    x13
/usr/lib/python3.12/json/__init__.py:346   x13
```

`_failing_frame` fixed the frame CHOICE inside `parse_pytest`. A JSONDecodeError traceback is not
something `parse_pytest` touches, and every other parser still reported whatever `file:line` it
found. `summarize()` shows the FIRST finding, and that is the line the coder goes and edits.

**Fixed properly** — `prefer_own_code()` at that one choke point, covering every parser. ORDER, not
deletion: a failure genuinely inside a library is still a failure the coder must know about, it just
must never be the first thing handed over. An all-foreign list is left exactly as it is.

### The remaining failures are the model's own

```
FAILED test_resolve_handle.py::test_resolve_handle_missing_ada
FAILED test_resolve_handle.py::test_resolve_handle_missing_holder
FAILED test_resolve_handle.py::test_resolve_handle_from_stdin
ERROR  test_resolve_handle.py::test_resolve_handle_success
```

Real assertion mismatches between the tests and the resolver, with accurate steers naming the right
lines. 79 of the run's prompts carried a steer, across 20 distinct steers — cria was not repeating
one message at it.

### The running picture for mellum2

| run | score | miss |
|:--|:--|:--|
| a1 | 3/4 | README |
| a2 | 3/4 | live test |
| a3 | 0/4 | cria wrote `web_fetch` into the plan |
| a4 | 3/4 | unit tests |
| a5 | 1/4 | cria deleted test steps; session ended in 181 s |
| a6 | 0/4 | cria deleted live test + README |
| a7 | 3/4 | unit tests |

Every 0/4 and the 1/4 trace to a cria fault since fixed. The 3/4s are converging on one thing: the
unit-test step. **Model wall: not reached**, but the next walk should focus there.

---

## ada-handles_mellum2_codex_pon_1785665296

**1/4.** 144 calls, killed at the 30-minute floor. Unit tests **1 failed, 3 passed**; no live test,
no README.

**cria fault: yes — mine, introduced one run earlier.**

The artifact protection I added to stop the noise judge deleting deliverables fired three times in
this run, on the wrong step:

```
loop.replan_noise_refused
  "Commit the three files (resolve.py, resolve_test.py, README.md) to a new repo, add a
   .gitignore with __pycache__ and .pyc, push to a new GitHub repo."
```

That is git plumbing the task never asked for — precisely what the noise judge exists to delete —
and my rule kept it in the plan, three times, while the live test and README never got written.

**Intended firings across the whole ladder: 3. False firings in one run: 3.** The doctrine line is
"an assist that fires on a clean signal is pure downside", and it landed on my own change within a
single run of shipping it.

**Cause:** the rule was "any authoring verb anywhere in the step + any filename anywhere in the
step". `add a .gitignore` supplied the verb; `resolve.py` supplied the filename; they had nothing to
do with each other.

**Fixed** — the verb must GOVERN the filename:

| step | now |
|:--|:--|
| "Write live_test.py: …" | protected |
| "Add README.md documenting install" | protected |
| "Create a new file utils.py with the helper" | protected |
| "Commit the three files (resolve.py, …) to a new repo" | droppable |
| "Add tests, then commit resolve.py" | droppable |
| "grep -n 'resolve' spec.json" | droppable |

Regression tests pin the false positive by name so the loose form cannot come back.

**Lesson worth keeping:** the dropped-step logging added two runs ago is what made this visible
within one run instead of three. Logging what a mechanism DID, not just how often it ran, is what
turned both this bug and the one it was fixing from archaeology into measurement.

**Model wall: not reached.**

---

## ada-handles_mellum2_codex_pon_1785667319

**0/4.** 111 calls, killed at the 15-minute floor. All four artifacts exist; none works.

**cria fault: yes** — cria told the coder the wrong API field, in every one of its 63 prompts.

### Running the CLI gives it away in one line

```
$ python3 resolve_handle.py goose
Error: 404 Client Error: Not Found for url:
  https://api.handle.me/holders/addr1qxsfzsmy6y2seduagp6fx9pht4yz9nspxvzyldtv36p2uz0gzxzwvk47q...
```

It is passing the **ada** address (`addr1…`) to `/holders/{address}`, which wants the **holder's
stake** address (`stake1…`).

### The initial plan was clean

```
1. Read the OpenAPI spec ... noting that /handles/{handle} returns resolved_addresses.ada AND
   holder, and /holders/{address} returns total_handles.
2. Write resolve_handle.py that ... calls /handles/{handle} and /holders/{address} ...
```

Both fields named correctly; step 2 says `{address}` generically.

### What actually reached the coder

Counted over the run: **63 of 63 coder prompts** carried

> `/holders/{address}` *(api.handle.me/holders/{address} where **address = resolved_addresses.ada
> from the first response**); return dict with keys: resolved_address, holder_address,
> total_handles*

A re-derived step baked in the wrong field as a concrete fact, and the coder built exactly what it
was told. Every request 404s.

The replanner's own prompt forbids precisely this: *"DON'T CODIFY A GUESS: never bake into a step a
concrete external detail the coder has NOT confirmed from the real source."* Same class as the
`web_fetch` leak in attempt 3 — a re-derivation inventing a concrete external detail — and a
**recurrence**: the mellum2 walk of run 1785625253 recorded the identical wrong mandate
(*"The script GETs /handles/{handle} then GETs /holders/{resolved_addresses.ada}"*), where cria also
contradicted its own facts block in the same prompt.

### Candidate fix, NOT built yet

cria's shape ledger already holds the real parameter description for `/holders/{address}` — *"the
stake/enterprise/script/other address of the Holder"*. A step that asserts `where <param> = <field>`
about a route cria has fetched is checkable against that ledger, deterministically, the way
`urlgrounding` checks that a route exists. That is the shape of the fix.

It is **not** built here, and the measurement says do not build it in that shape: across every
captured judged step (**n=404**), a step asserting `where <param> = <field>` about a route appears
**once** — this one. Keying a rule on that phrasing would be fitting to a single string, which is
exactly attempt 8's mistake one run earlier.

The real class is broader: a re-derivation baking in a concrete external detail the coder never
confirmed. `urlgrounding` already enforces that for ROUTES; the gap is parameter-to-field bindings,
and closing it properly means grounding the binding against the fetched spec rather than
pattern-matching the sentence. That is a real piece of work, not a regex, and it should be measured
against the shape ledger before anything ships.

**Model wall: not reached.** The model implemented what cria asserted.

---

## ada-handles_mellum2_codex_pon_1785668419

**3/4 — fifth 3/4 in ten runs.** 159 calls, 27 minutes. Unit tests **6 passed**, live test provably
live, README passes. The CLI is the only miss.

**cria fault: none.** This is the first mellum2 walk in this ladder where I could not find one.

### The failure

```
$ python3 resolve_handle.py goose
Error resolving goose: 404 Not Found: https://api.handle.me/holders/addr1qxsfzsmy6y2seduagp6...
exit=1
```

The same wrong-address bug as attempt 9 — passing the ada address to `/holders/{address}`, which
wants the holder's stake address.

### But the cause is different, and it is not cria

Attempt 9 failed because cria asserted the wrong binding in **63 of 63** coder prompts
(*"where address = resolved_addresses.ada"*). Counted here: **0 of 65**. cria did not state it, and
all 65 prompts carried the stake-address material the model needed.

The model made the wrong choice itself, from correct information.

### Why this matters for the ladder

Under the block rule, a failure whose walk finds no new cria fault is a strike. This is one. That is
the rule working as intended — it exists so a model that keeps failing on its own does not eat days,
and it must not be dodged by manufacturing a finding.

The honest summary of ten runs:

| | |
|:--|--:|
| 3/4 | **5** (a1, a2, a4, a7, a10) |
| 0/4 or 1/4 traced to a cria fault since fixed | 4 |
| failures with NO cria fault found | **1** |

Every deliverable has now passed in at least one run, and a10 passed three of four with a genuinely
live test. What has never happened is all four in the same run.

**Model wall: possibly reached on this one deliverable.** The next walk should confirm or refute
that rather than assume it — one strike is not five.

---

## ada-handles_mellum2_codex_pon_1785670156

**3/4 — sixth in eleven runs.** 479 calls, the full hour. Unit tests the only miss
(4 failed, 1 passed).

**cria fault: yes** — two, both partial and both mine to finish.

### 1. The whole hour went to ONE step

```
coder calls by step:   s1: 5     s2: 370
```

370 of 375 coder calls on step 2. `_replan_if_thrashing` exists for exactly this and did not
rescue the run. That is the single biggest lever left on this model: five 3/4s and a 3/4 here all
end with the clock gone, not with the model out of ideas.

### 2. My stdlib fix is better but still not complete

Measured over this run's pytest SUMMARY lines — the one line cria tells the coder to act on:

| | |
|:--|--:|
| pointing at the coder's own file | **56** |
| pointing at stdlib / site-packages | **17** |

`prefer_own_code` reorders findings so an own-code one leads, and falls back when *every* finding is
foreign. Those 17 are the fallback firing. The open question — not answered here — is whether an
own-code frame existed in those tracebacks and simply was never parsed out, in which case the parser
is losing it before the ordering ever runs.

Raw traceback text in the check block still contains stdlib lines, and that is correct: cria must
never speak over a tool's own output. Only the actionable summary line is cria's to choose.

### The eleven-run picture

| | |
|:--|--:|
| 3/4 | **6** |
| failures traced to a cria fault since fixed | 4 |
| failures with no cria fault found | 1 |

**Model wall: not reached.** Every deliverable has passed in some run; none has passed all four in
one run. The next work is the stuck-step lever, not another parser fix.

---

## ada-handles_mellum2_codex_pon_1785673911

**1/4.** 156 calls, killed at the 30-minute floor. Only the CLI passed.

**cria fault: yes** — the noise judge deleted the live test again, and my own protection was too
tight to catch it.

```
loop.replan_noise  dropped 1  kept 1
  "Write a live test file (e.g., test_live_resolve.py) that calls the real API for 'goose'
   and asserts the response contains resolved..."
```

Verifier: `no live-test file found`, `no README`.

### Both of my versions were wrong, one run apart

| version | behaviour | consequence |
|:--|:--|:--|
| verb anywhere + filename anywhere | protected `"Commit the three files (resolve.py, …) to a new repo, add a .gitignore …"` | junk kept in the plan 3× in run 20260802T024816 |
| verb directly against the filename | missed `"Write a live test file (e.g., test_live_resolve.py) …"` | live test and README deleted, this run |

**Fixed** — a 40-character window that never crosses a sentence boundary. Correct on every measured
case in both directions: all three logged deletions protected; the git-plumbing step and
`grep -n 'resolve' spec.json` still droppable.

I also removed a test assertion of my own. I had written that `"Add tests, then commit resolve.py"`
must be droppable — I invented that example, and it is not a false positive: "Add tests" is authoring
work. The reasoning now sits in its place so it is not reintroduced from memory.

### The pattern worth naming

Three consecutive runs where the fix itself was the finding. The dropped-step logging is what made
each one visible within a single run instead of three — logging what a mechanism DID, not just how
often it ran, is what turned this whole area from archaeology into measurement.

**Model wall: not reached.**

---

## ada-handles_mellum2_codex_pon_1785675899

**1/4.** 204 calls, killed at the 30-minute floor. README passed; nothing else.

**cria fault: none — but the run is not valid evidence either.**

### My noise-judge fix held

```
loop.replan_noise  dropped 0  kept 2
loop.replan_noise  dropped 0  kept 1
```

Zero deliverables deleted, after three runs where that was the cause. The 40-character window is
doing its job.

### The API rate-limited us mid-run

```
$ python3 resolve_handle.py goose
HTTP error 403 for https://api.handle.me/handles/goose
Failed to fetch handle goose
```

Checked from my own shell immediately after: **HTTP 200**, goose resolves normally. The 403 was
transient, during the run.

Counted across every capture: **251 coder prompts show a 403 from the API, across 3 runs.**

### CORRECTION (same session, after building the guard)

The diagnosis above is **wrong** and is left standing only so the correction is visible.

`api.handle.me` does not rate-limit us. It blocks `Python-urllib/3.x` **by name**. Verified on this
box:

| client | result |
|:--|:--|
| urllib default UA | **403** |
| curl | 200 |
| browser UA | 200 |
| python-requests | 200 |

I found this because the preflight probe I wrote to detect "throttling" used urllib's default UA and
returned 403 every single time — a guard that would have refused to start **any** run, forever, while
looking exactly like the problem it was written for.

What this means for the run: the coder's generated code uses `requests` and is unaffected; cria's own
`web_fetch` sets a User-Agent and is unaffected. Whatever produced 403s inside the run, "we hammered
the API" is not supported by the evidence, and spacing the runs would have fixed nothing.

### What was actually built



Thirteen back-to-back runs, each making dozens of live calls to `api.handle.me`, is enough to get
throttled. A throttled run fails for a reason that is neither cria's nor the model's, and it is
scored exactly like a real failure — which quietly corrupts the ladder's evidence.

**Recommended before continuing:**

1. `preflight.py` should check `GET /handles/goose` returns 200 and REFUSE to start otherwise —
   the same shape as its existing cold-cache and site-packages guards.
2. A run whose captures show 403/429 should be marked `aborted` automatically. It is not an attempt;
   it says nothing about the model.
3. Space the runs, or the ladder measures our own request rate.

Both were built, and the first one was wrong — see the correction above. What stands:

* `preflight` probes any task declaring a `live_probe` and refuses READY on non-200, identifying
  itself with a real User-Agent;
* `run.py` marks a row `aborted` when five or more of its own coder prompts carry a 403/429. A run
  peppered with them is not evidence about the model, whatever the cause.

The URL is declared in the task's `meta.toml`, never in cria.

**Model wall: not reached.** This run proves nothing either way.

---

## ada-handles_mellum2_codex_pon_1785678150

**1/4 — after holding 3/4 for half an hour.** 279 calls, the full sixty minutes.

**cria fault: yes** — cria kept driving at the one failing check until the model destroyed two
deliverables that were already passing.

### The model peaked at 3/4 and then took it apart

| at | unit tests | live test | CLI | README | score |
|:--|:--|:--|:--|:--|--:|
| 15 min | ✗ | ✗ | ✓ | ✗ | 1 |
| 30 min | ✗ | **✓** | ✓ | **✓** | **3** |
| 45 min | ✗ | **✓** | ✓ | **✓** | **3** |
| 60 min | ✗ | **✗** | ✓ | **✗** | **1** |

A **provably live** live test and a **complete** README, both held for thirty minutes, both gone by
the end. The only check that never passed is the one cria spent the hour steering toward.

This is the first run in this ladder with milestone history dense enough to see it: **1 of the 9 runs
carrying more than one milestone finished BELOW its own peak.** Every other run ended at its high
water mark. It is one instance — but it is an instance of the exact thing the doctrine's
"additive / regression-only — never delete correct content" rule exists to prevent, happening at the
level of the run rather than the intervention.

### Why this is cria's, not the model's

cria has no notion that the workspace was ever in a better state. Its loop is: checks fail → steer →
coder edits → re-check. Nothing in it is monotonic. A coder that rewrites a working file while
chasing an unrelated failing test looks identical, to cria, to one making progress.

The suite's own milestone snapshots are the proof it is knowable — cria simply never asks. cria does
have a cheap, model-free equivalent already in the loop: the gate. **A step that turns a green gate
red is a regression, and cria currently steers straight through it.**

### The candidate fix, and why it is not built here

A "did my last change break something that was working" check belongs in the loop, driven by the
gate cria already runs — not by the suite's verifier, which cria must never see. That is a real
mechanism, and it must be measured across the captures first: how often does a gate go green→red
within a step, and does the coder recover on its own?

Recorded rather than built, because the last four runs are a sustained lesson in what shipping a
mechanism before its false-positive surface is understood actually costs.

**This is the highest-value open finding in the ladder.** Six 3/4s and now a 3/4 held for thirty
minutes and thrown away — mellum2's problem is no longer reaching four, it is keeping three.
