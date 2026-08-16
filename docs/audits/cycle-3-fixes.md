# Cycle 3 — the fixes, what `A` each one addresses, and before/after

Companion to [cycle-3-walk.md](cycle-3-walk.md). Fourteen fixes, ordered by points recoverable ×
confidence.

Every entry states the **A** in A→B→C — the upstream cause, never the symptom — and shows a real
before taken from the run's own artifacts against the after. Where an entry cannot reach A, it says
so and says why.

Vetting verdicts (SAFE / MODIFY FIRST / DO NOT LAND) come from a pass over git history, incident
comments and test docstrings. **Three of these must be landed as an added condition, not a reworded
sentence** — this repo settled that remedy twice already (`57e203c`, `ec05c36`), because the wording
is pinned by a test that records the incident it was written for.

---

## 1. The research step accepts a workspace file as the "external source"

**A** — `cria/prompts/research_step.txt` asks for "one sentence naming **that source**" when "coding
requires reading an **external** source first". `research.step_defect()` refuses five defective
shapes (a build verb, an unnamed location, over-long, third person, an echo of the instructions).
**None of them refuses a source that is a file inside the workspace.** So "read `cart.go`" and the
bare string "`go.mod`" both pass, and the one mechanism that exists to make the coder read real
documentation is satisfied by reading its own project.

**Why this is A and not B.** The symptom is a model inventing four library method names. The
tempting fix is to check invented symbols downstream. But the coder never had the API in front of it
because the step that exists to put it there declared itself done at call 0006.

**Before** — cell 8, call 0002-0006. The task says *"Add a third-party Go decimal module to
`go.mod` and use it for cart calculations."* The research step resolves to reading local `cart.go`,
returns DONE, and the run proceeds. Over the next 107 calls: **zero `web_search`, zero `web_fetch`**,
and four invented `shopspring/decimal` names. Cell 7 is the same shape — the step came back as the
bare filename `go.mod`, which then rode into all 34 coder prompts as *"Do ONLY this step (1 of 2),
then stop: go.mod"*.

**After** — a sixth arm in `step_defect`, enforcing the prompt's own word:

```python
    # A source INSIDE the workspace is not an external source — it is the coder's ordinary work, and
    # a reading step satisfied by reading the project cannot teach a third-party API. Cell 8 of
    # cycle 3 resolved "add a third-party Go decimal module" to reading local cart.go, returned DONE
    # at call 0006, and the coder then reconstructed the whole library from memory: four invented
    # names (NewFromFloat64, `-` on a Decimal, RoundTo, ToFloat64), 107 calls, zero fetches, 1 of 5.
    if _names_only_workspace_files(text, workspace_root):
        return ("it names a file in this project — a reading step exists to learn something the "
                "project does not already contain")
```

A refused step falls back to NONE, which is the existing safe direction (no step). Cell 7's bare
`go.mod` is caught by the same arm.

**Did I confirm the agents?** **Partly — and I overturned their headline.** The walkers (and my own
brief) said cell 8 turned on ONE invented name. I ran the experiment myself: fixing `NewFromFloat64`
alone leaves it at **1/5**; all four names are needed for **5/5, success: true**. One agent had
already reached the four-name answer independently and it was right. I also read `research_step.txt`
and `research.step_defect()` myself and confirmed there is no arm for a workspace-file source.
**Not independently checked**: that the research step returned DONE at call 0006 off a local read,
and the zero-fetch count over 107 calls — both are the agents' evidence, quoted, not re-derived.

**Verdict**: not yet vetted — this candidate was raised after the vetting pass ran. Must be checked
against `tests/test_step_echo_defect.py` before landing.

**Recoverable**: 4 points in cell 8 (proved: 1/5 → 5/5 with the four names corrected). Cell 7
unknown but its 30 minutes went to one config file.

---

## 2. The steer author is shown a re-rendered copy of the gate result instead of the gate object cria already holds

**CORRECTION — my first framing of this was wrong on doctrine, and there was already a logged entry
for it that I did not check.** I wrote that the defect was that tool results are "cut to 200
characters from each end". That is not a violation. Principle 5's counter-nuance is explicit:

> Never-truncate governs the *coder's reads*, NOT a prompt cria *composes* for a judge or steer.
> Bounding a composed prompt breaks no rule — **over-applying never-truncate to composed prompts is
> itself a documented footgun.**

The steer author's prompt is composed by cria. Bounding it is allowed, and un-bounding it would
revert `project_useless_prompting_sweep` — a bad-fix condition the walk process names outright.
`docs/audits/context-footgun-backlog.md` §7 already logs this exact finding (18 occurrences, 5
languages, 3 models, "Fix belongs at: A-earliest") and states the rule correctly: *"Rule 5's
counter-nuance permits bounding a composed prompt only when the bound is DISCLOSED."*

**And the disclosure half has since landed.** My own reproduction shows the marker:
`[749 chars elided; head+tail kept — re-read the source for the middle]`. So the part of §7 that
made this a 5b false fact is fixed. What remains is a different rule.

**A** — **principle 12**, not 5. The steer author's view of the checks is *re-rendered from the
transcript* when cria is holding the authoritative object. `sess.last_gate_flag` is the gate's own
finding-set; `_gate_notes` (`loop.py:5559`, `:5578`) already builds the **coder's** checks block from
it, and `judge_satisfaction` already receives it as `gate_findings=` at three call sites
(`loop.py:2308`, `:3545`, `:3810`). The steer author is the one seat that does not get it — it gets
`selfcompact.serialize(...)` of the message history (`loop.py:6313`), i.e. a bounded re-render of a
tool message rather than the event.

> Rule 12: *Derive counts and signals from the structured event — never by re-counting a finalized
> response or matching an English needle in prose.*

Two things follow from re-rendering, and both were measured:

1. **cria's own preamble is charged to the ground truth's budget.** The gate result the author reads
   begins with cria's 307-character `⟦ctx:checks⟧` explanation, so the entire 200-char head half is
   spent on cria's words and none on the checker's.
2. **The bound is applied to the wrong unit.** A per-transcript-line bound is right for background
   turns and wrong for the one turn the steer is *about*.

**Before** — I ran cell 4's *real* 1,157-character gate result through `selfcompact._defanged_line`
myself. What the steer author sees:

```
→ result: ⟦ctx:checks⟧ the repo's own checks report these error-class problems — each is the
checker's OWN message and the line it flagged; resolve what each one names with the smallest
change that makes it act...[749 chars elided; head+tail kept — re-read the source for the
middle]...tes.rb:23]: Expected: 12.0 Actual: 0.0 7 runs, 7 assertions, 1 failures, 0 errors, 0
skips rake aborted! Command failed with status (1) …
```

`"test_oversize_surcharge" in line` → **False**. The failing test's name is gone and the path is cut
mid-word to `tes.rb:23]`. The author is asked which test failed while holding text that no longer
says — and it answered `test_domestic_light_parcel`, then prescribed setting to `0.0` the constant
the real failing test asserts is `12.0`.

**After** — hand the author the same object the coder's block and the judge already get, exactly as
§7 proposed ("build the author's check block from the same last-gate object the coder's checks block
uses, staleness sentence included"):

```python
    # Rule 12: the checks slot is filled from the authoritative gate object, never re-rendered from
    # the transcript. `_gate_notes` already builds the coder's block from `last_gate_flag`, and
    # judge_satisfaction already takes it as gate_findings= at three sites; the steer author was the
    # one seat left reading a bounded re-render. Cycle 3 cell 4: the 200-char head went entirely to
    # cria's own 307-char ⟦ctx:checks⟧ preamble, the failing test's NAME landed in the elided middle,
    # and the steer named a different test and prescribed a change that would red the real one.
    # The transcript bound STAYS as it is — this is a composed prompt and bounding it is #5's own
    # carve-out; what changes is which object the checks slot is built from.
    gate_block = _gate_notes(gs)          # the same last-gate object, staleness sentence included
```

The 400-char transcript bound is left exactly where it is. Nothing about never-truncate changes.

**Still open from §7, and not proposed here**: "never clip the turn that carries the task" and
"budget `edit_file`'s two strings separately". Both are real; neither was measured in this run, so
neither is ranked here — see §7 for their own evidence.

**Separately — the newline collapse is a different defect and stands on its own.**
`' '.join(body.split())` at `selfcompact.py:261` flattens a compiler's or a test runner's
line-oriented output into one line *before* bounding. That is not a truncation question — a
reasoner read `cart.go` as a single line and concluded *"That's invalid syntax"*, ordering a fix for
a problem that did not exist. Keeping newlines for a check result costs no budget.

**Did I confirm the agents?** **Yes on the mechanism, and the operator corrected my reading of it.**
Three agents reported a 400-char and a head/tail clip; I pulled cell 4's real gate output and ran it
through the function myself, and found the detail they missed — cria's own preamble eats the head.
But I then framed the clip itself as the violation, which inverts principle 5's counter-nuance and
would have reverted a previous fix. The operator caught it. Checking
`context-footgun-backlog.md` §7 — which I should have done before proposing anything — showed the
finding was already logged with a better fix than mine, and that its disclosure half had already
landed. **Not independently checked**: cell 7's 1,812 elided characters.

**SECOND CORRECTION — I over-corrected, and the cited source says so.** The operator asked where
"over-applying never-truncate to composed prompts is itself a documented footgun" is actually
documented. Following the citation: `docs/audits/2026-07-20-useless-prompting-anomaly-audit.md`
**is not in the repo**. It and three other dated audits `principles.md` cites were removed by
`8f52a11 chore(docs): stop tracking the dated audit reports`. Recovered from git
(`git show 810eabe:…`), its cross-cutting root reads:

> cria has a deliberate, correct stance — **never truncate content the model asked to READ** … That
> stance is right for the *coder's own reads*. But it has been **over-applied to prompts cria
> COMPOSES for a judge/steer** — where the floor bounds the total but never **de-dupes** or
> **stubs**, so redundant + growing content re-crowds every reasoner call. Two concrete failure
> modes fall out of it: a byte-equality dedup that silently fails, and the whole session
> re-serialized on every steer fire. Composing a judge prompt is *not* the coder's read — bounding
> it there breaks no rule.

The documented footgun is **failing to DE-DUPE or STUB**, so a composed prompt bloats. The licence
is to dedup and stub. It is not a licence to head/tail clip the one block the steer is about — and
the same audit says so explicitly, four lines from the end:

> **Direction:** bound only *re-included READ payloads* … **keep genuine command/test output full.**
> Brushes never-truncate — keep the cap as the safety valve; treat as judgment, not fix-on-sight.

A gate result **is** genuine command/test output. So the clip measured here is being applied to
precisely the category its own governing audit says to keep full. My original instinct was not the
doctrine violation I then talked myself into — the operator was right that "cut to 200 chars" is not
*by itself* a violation, and I was wrong to conclude from that the clip was therefore fine.

**The rewritten fix stands anyway, and is still the better one**, because it makes the question moot:
filling the slot from the authoritative gate object means there is no transcript re-render to bound.
Rule 12 settles it without anyone having to adjudicate rule 5.

**Verdict**: **MODIFY FIRST — as now written.** The blanket "never bound a composed steer prompt"
version remains **DO NOT LAND** — that would revert `project_useless_prompting_sweep`, whose whole
finding is that composed prompts were going un-deduped and un-stubbed. The rewritten version is
additive (one more slot filled from an owner that already exists) and touches no bound.

**Docs defect found on the way, worth its own line.** `docs/principles.md` cites four dated audit
files, and **all four are absent from the working tree** — removed deliberately by `8f52a11`, but the
citations were left pointing at them. The canonical doctrine document currently sends a reader to
four dead paths. Not fixed here: re-adding the files would revert a deliberate untracking decision,
so the right repair is to change the citations to name the commit that holds them. Operator's call.

**Recoverable**: cell 4 and cell 7 both lost their remaining turns to steers written from this.

---

## 3. The compaction briefing is asked to invent a to-do list, then filed as ground truth

**A** — `cria/prompts/selfcompact_summary.txt`. Line 1 says *"do NOT … plan the next steps"*. Line 8
then asks for:

```
- What remains to be done / the next step.
```

Every other bullet in that prompt carries an evidence rule ("Only from a check that RAN in the
transcript", "Never carry a problem forward from memory"). **This bullet carries none.** A tool-less
model asked what remains, with no evidence rule, answers by inventing.

Then `loop.py:4130-4137` folds that answer into the completion judge's evidence under
`cria/prompts/satisfaction_user.txt:4`:

```
THE CODER'S REAL ACTIONS AND THEIR OUTPUTS SO FAR (ground truth):
```

**Before** — cell 2, call 0131, one prompt file. Line 103 is the task:

> "1. Fix the failing repository tests. **Do not change assertions in tests that came with the
> repo.** Tests you add may be changed freely."

Line ~142 is cria's briefing:

> "**Update the test expectations in `test/test_rates.rb`** to match the actual behavior of the
> `shipping_cost` method with country codes."

The model obeyed the briefing and changed the seeded test from `ArgumentError` to `NameError` —
verbatim the `verify.py` failure for that cell.

Cell 6, same generator: the briefing invented a `main.go` startup call the Go task never asks for.
The judge quoted the invention back as *"The task explicitly requires…"*, the coder said *"the task
doesn't mention a main.go file"* and built it anyway, which forced a package split, a restructure,
and the module rename. Cell 8, same generator: *"No `discounts.json` file exists yet"* and *"The code
does not log totals to stderr"*, both contradicted by the file list in cria's own prompt, re-injected
17 times.

**After** — two changes, neither deleting the bullet:

```
- What remains to be done / the next step — subject to the SAME evidence rule as the bullets above:
  name something remaining only where a check that RAN reported it, or the task itself asks for it
  and no run has shown it done. Never a file, a command, a function, or a step the task does not
  name. If nothing meets that bar, say "nothing verified outstanding".
```

and the FILES ON DISK rule made two-directional — today it forbids claiming a file **was created**,
and says nothing about claiming one is **missing**:

```
- … Never state that a file was created unless it is on that list, AND never state that a file is
  missing when it IS on that list.
```

and the judge's header relabelled to wording this repo already owns (`verify_user.txt`):

```
THE CODER'S REAL ACTIONS AND THEIR OUTPUTS SO FAR (tool output is ground truth; any SUMMARY OF
EARLIER WORK below is the coder's own claim — trust the tool output over it):
```

**Did I confirm the agents?** **Yes for cell 2 and for the wiring; no for cells 6 and 8.** I opened
`0131-coder-s1.prompt.txt` myself and read both passages — the task at line 103 and the contradicting
briefing at ~142 — in the one file. I read `satisfaction_user.txt:4` and `loop.py:4130-4137` myself to
confirm a model-written summary is folded into evidence under a "(ground truth)" header.
**Not independently checked**: cell 6's invented `main.go` bullet and the judge quoting it, and cell
8's four false facts — both are the agents' quotes. Two agents reached cell 6's chain independently,
which is why I rank it despite not re-deriving it.

**Verdict**: **MODIFY FIRST.** `tests/test_compaction_contract_stated_once.py:42` pins the literal
`"What remains to be done"`, and that file records a *previous* trim of this prompt being reverted —
so fence the bullet, never delete it. Dropping the summary fold entirely would revert `e4d1122` (a
judge ruled a live build "the coder hasn't started"); the *label* is unpinned, so relabelling is the
safe half.

**Recoverable**: 2 points in cell 6 (proved), the seeded-test loss in cell 2, nine wasted calls in
cell 8.

---

## 4. The leaked gate wrapper manufactures a false exit code

**A** — `cria/proberun.py:709-719` composes the gate shell with variables literally named
`__cria_out`, `__cria_ec`, `__cria_n`. Principle 17 says the model never sees the token "cria". It
sees it 98 times in a single prompt, in 114 of 134 prompts in one cell.

**The leak is not the damage. The copying is.** The model learns the idiom and writes it into its
own commands — and the wrapper's last statement is a successful `printf`, so the shell always exits
0 regardless of what ran inside.

**Before** — cell 8, call 0051. The model's own tool call:

```
cd /tmp/suite-…-w290d284 && __cria_out=$(timeout -k 5 240 go build -o cartsvc ./... </dev/null 2>&1);
__cria_ec=$?; __cria_n=$(printf '%s' "$__cria_out" | wc -c | tr -cd '0-9'); if [ … ]; …;
printf 'EXIT:%d\n' "$__cria_ec"
```

and what came back:

```
Process exited with code 0
Original token count: 43
Output:
# cartsvc
./cart.go:49:17: undefined: decimal.NewFromFloat64
./cart.go:55:21: undefined: decimal.NewFromFloat64
./cart.go:58:27: undefined: decimal.NewFromFloat64
EXIT:1
```

Two contradictory exit codes, and the false one sits in the harness's standard header position where
a model looks first. Same class as the output-truncation and self-truncated-write footguns already
fixed: a failed operation reported as a success.

**After** — rename to a token that carries no identity and no idiom:

```python
        f"__p_out=$(timeout -k {TIMEOUT_KILL_GRACE_S} {timeout_s:g} {argv} "
        f"</dev/null 2>&1); __p_ec=$?; "
```

**Did I confirm the agents?** **Yes, all of it, and I found the part they under-stated.** Seven
agents reported the token leak with counts from 49 to 196; I counted one prompt myself
(44 + 24 + 24 + 6 = **98**) and found the token in **114 of 134** prompt files in that cell. Then I
opened calls 0051, 0062 and 0065's response bodies myself and found the model writing cria's wrapper
into its own `exec_command`, and pulled the resulting tool response out of 0052's prompt: **"Process
exited with code 0"** sitting directly above **"EXIT:1"** for a failed `go build`. Two agents
mentioned the copy; I verified the false exit code, which is what moves this out of hygiene.

**Verdict**: **MODIFY FIRST.** The rename as scoped closes only half of it —
`probegate.py:835`'s litter regex depends on the names being disjoint, seven test files hard-code
them, and `probediscovery.py:863` leaks `.cria` separately. All must move together, and
`tests/test_gate_script_is_read_only.py::test_litter_bookkeeping_never_reaches_the_model` must be
widened from the three `__cria_pre`/`post`/`new` names it checks today to *any* occurrence of the
token.

---

## 5. dirguard refuses a malformed command on its stray tokens

**A** — `cria/dirguard.command_refusal()` scans a raw command for path-shaped tokens and refuses if
any is external. It has no notion of whether the string it was handed is a *command* at all. A
malformed call whose text happens to contain `/bin/bash` is refused as a filesystem violation.

**Before** — cell 8, ten times. The model pasted a tool signature into the shell:

```
exec_command cmd="go mod download", justification="…", max_output_tokens=10000,
yield_time_ms=30000, tty=true, shell="/bin/bash", login=true, workdir="/tmp/suite-…"
```

cria answered:

> ⟦ctx:denied⟧ Writing/reading outside the working directory is not permitted here — keep every file
> you read or write inside the project directory (/tmp/suite-…)

`go mod download` reads no file outside the workspace. The refusal names a rule the command did not
break, and its advice cannot be acted on — there is nothing to move inside the project. The model
drew the only available conclusion: *"denial of exec_command might be due to sandbox restrictions"*
→ *"we cannot use exec_command to run go commands"* → *"So we cannot run go. Hmm."* It then spent 27
straight calls blaming module resolution for a misspelled method, and called `task_complete` three
times on a build that never compiled. `go mod tidy` and `go build` had both run fine every time it
wrote a clean command.

**After** — judge the shape before the tokens:

```python
    # A malformed call is not a path violation. Cycle 3 cell 8 pasted the tool SIGNATURE into cmd
    # (…, shell="/bin/bash", login=true, …); the scan found /bin/bash and refused `go mod download`
    # as an external access. Ten times. The coder concluded its whole toolchain was sandboxed off and
    # never ran another verification. Say what is actually wrong — a refusal the coder cannot act on
    # is worse than no refusal, because it is a false fact about its own environment (#5b).
    if _looks_like_a_pasted_tool_signature(command):
        return prompts.load("command_unparseable")
```

with the new prompt naming the real problem: the command contains the tool's own argument syntax, so
re-issue it as a plain shell command.

**Did I confirm the agents?** **The defect yes, the consequence no.** I dumped all ten
`writeproxy.blocked_external` events myself and pulled the offending command and the refusal text out
of prompt 0044 — the pasted tool signature carrying `shell="/bin/bash"`, and the "outside the working
directory" answer to a `go mod download` that touches nothing outside it. **Not independently
checked**: the model's chain of belief ("we cannot run go") and the claim that `go mod tidy` had
already succeeded. Two agents reached that chain independently from different call ranges.

**Verdict**: not yet vetted. Must not weaken the guard's actual job — `tests/` around dirguard
record a workspace-wipe incident and the refusal path is load-bearing.

---

## 6. The context floor evicts the plan-off root task

**A** — `cria/contextfloor.py:83` protects `⟦ctx:task⟧` among its markers. On the **plan-off** path
the harness's root task turn is never tagged with that marker, so `_protected_mask` treats it as
ordinary history and `_drop_oldest` evicts it first.

**Before** — measured across every coder prompt in all 8 cells:

| cell | coder calls | missing the task | which |
|---|---:|---:|---|
| C2 rb/qwen35 | 118 | 2 (1%) | 0069, 0084 |
| **C3 rb/bonsai** | 55 | **9 (16%)** | 0052, 0054–0060, 0062 |
| C6 go/qwen35 | 109 | 4 (3%) | 0050, 0052, 0056, 0061 |
| the other five | — | 0 | — |

Cell 3's nine are the **last nine coder calls of a 76-minute run**. That cell finished one check
short and spent its tail with no statement of what it was for.

**After** — tag the root task on the plan-off path so the existing protection applies. The
mechanism already exists and is correct; it is simply never handed the message it was built for.
No new guard, no new marker.

**Did I confirm the agents?** **Yes for the fact, and I supplied the prevalence they did not have.**
Two agents reported the task text vanishing in their own ranges. I measured every coder prompt in all
8 cells myself — the table above is mine, not theirs — which is how the "16% in cell 3, zero in five
cells" shape emerged. I read `contextfloor.py:83` myself and confirmed `⟦ctx:task⟧` is in the
protected set. **Not independently checked**: that the plan-off root task is never tagged with it. I
read the protection, not the tagging site.

**Verdict**: not yet vetted. This is the additive half of an existing owner, which is the shape the
repo prefers — but the tagging point must not double-tag on the plan-on path.

---

## 7. `gem_bundler` installs a gem where nothing can load it

**A** — `cria/prompts/install_remedy.txt`. Every route in that file carries an install half **and** a
reachability half — except one:

| route | install | reachability |
|---|---|---|
| `pip_venv` | `python3 -m venv .venv && …` | "then run with `./.venv/bin/python`" ✅ |
| `npm_local` | `npm install <pkg>` | "which is what your code will load" ✅ |
| `gem_direct` | `gem install --install-dir vendor/bundle` | "then make it loadable… `GEM_HOME=…` or `$LOAD_PATH.unshift`" ✅ |
| **`gem_bundler`** | `bundle install --path vendor/bundle` | **nothing** ❌ |

**Before** — reproduced on cell 2's real artifact, which has a genuine `--path` install:

| invocation | result |
|---|---|
| `ruby -Ilib -e 'require "countries"'` — **what `verify.py` runs** | `kernel_require.rb:86: cannot load such file (LoadError)` |
| with `require "bundler/setup"` | LOADED |
| under `bundle3.2 exec` | LOADED |
| with `GEM_HOME=vendor/bundle/ruby/3.2.0` | LOADED |

That LoadError is byte-for-byte cell 2's result row. The model put `bundler/setup` in its own test
file, which made its own tests pass and left `lib/` unloadable to every consumer it did not write —
including the hidden test, which it never sees.

**After**:

```
gem_bundler = Install it into the project instead: add the gem to a `Gemfile` and run
`{{BUNDLE}} install --path vendor/bundle`. That install is only visible to code running under
bundler — anything started as plain `ruby` will still fail to require it, including tests or scripts
you did not write. Either run it with `{{BUNDLE}} exec`, or make the library itself loadable without
bundler.
```

**Did I confirm the agents?** **Yes, by reproduction, and I corrected my own earlier claim.** I
copied cell 2's archived workspace and ran all four invocations myself — the table above is my output.
I read all four Ruby workspaces myself to get the prevalence, which is what forced the correction:
I had said in cycle 2 that this explained the Ruby column; only 1 of 4 cells took the route. I also
confirmed `bundle` does not exist on this box and `/usr/bin/bundle3.2` does.

**Verdict**: **SAFE TO LAND.** The reachability sentence is a recorded fix that landed on
`gem_direct` only; this completes the pair rather than reverting anything. **Must** use `{{BUNDLE}}`
— a literal `bundle exec` would recreate the exact incident
`tests/test_install_remedy_names_the_real_binary.py` exists for (`bundle` does not exist on this box;
`/usr/bin/bundle3.2` does).

**Recoverable**: cell 2's whole column of LoadErrors. Prevalence honestly stated: 1 of 4 Ruby cells
followed this route. The other three failed differently.

---

## 8. The rumination retry re-injects the loop it just killed

**A** — the abort path kills a degenerate generation and then builds the retry prompt with the killed
output quoted back as the model's own previous answer.

**Before** — cell 8, calls 0002→0003. The guard correctly killed a research call emitting
`But there is "github.com/mitchellh/mapstructure"? Not.` on infinite repeat. The retry prompt:

```
0002 prompt:  1,590 bytes
0003 prompt: 10,642 bytes  —  42 verbatim repeats of the killed loop, as "You answered:"
```

The guard's purpose is to stop a model looping. Handing it 42 copies of its own loop as the
immediate context is an invitation to continue.

**After** — the retry says what happened without replaying it:

```
[your previous answer was cut off: it repeated the same phrase without advancing. Answer again,
differently — do not continue from where it stopped.]
```

**Did I confirm the agents?** **Yes, and the agent's number was slightly off.** The agent reported
~45 verbatim repeats; I counted **42** myself, and measured the prompt growth (1,590 → 10,642 bytes).
I also read the killed generation in `0002-research-step.response.json` myself and confirmed the
abort was correct — a genuine infinite loop, not a false positive.

**Verdict**: not yet vetted. Must not collide with the `steer_rescue_skipped` path, which already
handles "an abort left no directive".

---

## 9. The ruby dependency note cannot tell "not installed" from "installed and unreachable"

**A** — `cria/prompts/dependency_note.txt:10` is keyed on **ecosystem alone**, with no condition on
what is actually on disk:

> "Note: `{{NAME}}` is installed nowhere ruby is looking. **A gem installed with --install-dir is not
> on the load path by default** — set GEM_HOME to that directory… **Fix the loading; the code that
> uses it is not what failed here.**"

Its own header records the incident it was written for: *"8 checks failed with the dependency
declared correctly and simply not reachable… 'install it' was never the missing step."* That is
true of the case it was built for. Fired when **nothing was ever installed**, it presupposes an
`--install-dir` install that never happened and then rules out the one correct move.

**Before** — cells 1, 2 and 3 all took it. Cell 1's workspace at the end: a `Gemfile`, and **no
`vendor/bundle`, no `.bundle/config`** — the gem was never installed by any route, and cria's note
told the model the problem was its load path.

**After** — add the condition; do not touch the pinned sentence:

```python
# The note answers "installed but unreachable". Ask the disk which case this is before sending it:
# with no install tree anywhere, "fix the loading, not the code" points away from the only fix.
if not _any_install_tree(workspace, ecosystem):
    return prompts.render("dependency_note_absent", NAME=name)
return prompts.render("dependency_note", ...)   # unchanged wording, unchanged test
```

**Did I confirm the agents?** **Yes.** I read `dependency_note.txt` in full myself, including the
header comment recording the opposite incident. I read cell 1's archived workspace myself and
confirmed there is a `Gemfile` and **no** `vendor/bundle` and **no** `.bundle/config` — so nothing was
installed by any route while cria was telling the model its load path was the problem. Two agents
flagged the same sentence independently.

**Verdict**: **MODIFY FIRST — add a condition, never soften the sentence.**
`tests/test_a_missing_dependency_says_so.py:66` pins `"load path"` with the docstring *"'Install it'
was never the missing step — every one of these had it installed"*. Narrowing by rewording would
revert that test's incident. Adding a disk condition leaves it green.

---

## 10. API-spec language on a documentation page that is not an API

**A** — `cria/prompts/fetched_facts_sections.txt:55`:

```
no_structure = (this page answered, but no endpoint definitions were found in it — that status is a
fact about the REQUEST, not about what the API returns; whatever the page returned is in the
transcript, but nothing read so far DEFINES the API's routes)
```

**Before** — cells 1, 2, 3 and 4 all had this stamped on fetches of the `countries` gem's README and
rubydoc pages. A Ruby gem has no routes. In cell 1 the model then invented
`Countries::Country#in_european_union?`; the real `in_eu?` was on line 166 of the file cria was
holding, and cria's annotation said nothing in it defined anything.

The sibling key immediately below (`no_spec_here`) exists **because this exact over-claiming was
already narrowed once**, for a different case. `no_structure` is the same class, unnarrowed.

**After** — the same remedy the sibling got: a condition at the call site, not a reworded string.
The note applies when the task is about an API and the fetch was of a spec; otherwise it is silent
(#3, silence over noise).

**Did I confirm the agents?** **The text yes, the per-cell annotations no.** I read
`fetched_facts_sections.txt` myself and confirmed both the `no_structure` wording and — the part that
decides the fix shape — the sibling `no_spec_here` and its comment recording that this exact
over-claiming was already narrowed once. **Not independently checked**: that the note was stamped on
those specific gem-documentation fetches, or that cell 1's invented `in_european_union?` followed from
it. Three agents reported it independently across four cells.

**Verdict**: **MODIFY FIRST.** Two tests pin the wording
(`assertIn("nothing read so far DEFINES", out)`, docstring *"the swagger-shell case this note was
built for is untouched"*). The sibling was narrowed by adding a **condition** at `loop.py:5911`, not
by rewording. Do the same.

---

## 11. The repetition steer calls three different commands "the SAME action"

**A** — `cria/loop.py:5631`:

```python
"repetition": lambda gs, step: (
    f"It keeps repeating the SAME action {REPEAT_FINGERPRINT_N}× without the outcome changing: {gs.repeat_action}"),
```

**I had this wrong at first and am correcting it.** The count is fine — the detector fires at
`matches + 1 >= REPEAT_FINGERPRINT_N` and flushes both windows, so it fires at exactly three and
"3×" is true. What is false is the rest: the fingerprint is a deliberately fuzzy nature-match
(`loop.py:81`, "jitters one flag or word without changing what it's doing"), so three *different*
commands routinely trip it, and `gs.repeat_action` is built from the **last matched call only**
(`loop.py:4994`).

**Before** — cell 1, call 0024. cria told the reasoner:

> It keeps repeating the SAME action 3× without the outcome changing: `gem install countries`

`gem install countries` ran **once**. The other two matches were `gem list countries` — a different
command, and one the coder ran precisely because cria's own earlier note had told it to take a
different action. The reasoner swallowed it whole: *"The coder called it three times in a row… The
coder ignored the instruction in the error message"* — both false — and wrote its redirect on that.

**After** — say what actually matched:

```python
"repetition": lambda gs, step: (
    f"It has made {REPEAT_FINGERPRINT_N} closely similar calls without the outcome changing: "
    f"{gs.repeat_actions}"),   # all matched calls, not just the last
```

**Did I confirm the agents?** **No — I checked and the agent's premise was wrong, then the vetting
pass caught that I had repeated it.** One agent said the "3×" was a hardcoded constant standing in for
an unmeasured count, and I marked that VERIFIED after reading `loop.py:5631`. The vetting pass
disagreed; I re-read `loop.py:4973` myself and it fires at `matches + 1 >= REPEAT_FINGERPRINT_N` and
flushes both windows, so it fires at exactly three and the number is true. The surviving defect —
"the SAME action" over three *different* commands, naming only the last (`loop.py:4994`) — is mine,
not theirs. **Not independently checked**: that `gem install countries` ran only once in cell 1.

**Verdict**: **DO NOT LAND as first written** — the "pass the observed count" version was my
misread and is a no-op on the wire. The re-scoped version above is untested against history and
needs its own vetting pass.

---

## 12. One naive "first user message" picker where another module already defends

**A** — `cria/selfcompact.py:188`:

```python
root = next((i for i, m in enumerate(messages) if m.get("role") == "user"), -1)
```

on a comment asserting *"The harness frame is dropped upstream of here"*. That assertion is false:
`_drop_harness_frame` explicitly **keeps** the preamble. `cria/loop.py` does not rely on the
assumption anywhere — it has `_is_env_context()` (`loop.py:4456`) and applies it at four sites
(3855, 3995, 4360, 4526) precisely to skip harness env preambles.

**Before** — cell 5. The harness's `Working environment — cwd: …` line is a user message, so it was
picked as "the task" and rendered whole; the real task was clipped to 400 characters, losing *"if the
file is missing, fall back to those same three codes"* and the entire decimal-module clause. cria
then told the coder stderr logging was not done (it had been since call 0014) and read a deliberate
`rm discounts.json` fallback proof as fakery. Cost: 184 seconds of an 805-second run, ~7,000
reasoning tokens, zero code changed — and the coder was right the whole time.

**After** — move `_is_env_context` to a shared module and use the one owner:

```python
    root = next((i for i, m in enumerate(messages)
                 if m.get("role") == "user" and not is_env_context(m)), -1)
```

**Did I confirm the agents?** **The code divergence yes, the cost no.** I read
`selfcompact.py:188` and `loop._is_env_context` myself and confirmed the four `loop.py` call sites
that guard against exactly the assumption `selfcompact.py`'s comment asserts is safe. The vetting pass
added the decisive fact I had not checked: `_drop_harness_frame` explicitly **keeps** the preamble, so
that comment is false. **Not independently checked**: cell 5's 184 seconds and the clipped
fallback/decimal clauses — the agent's evidence, quoted.

**Verdict**: **SAFE TO LAND.** Completes `9c4b5f5` rather than reverting it. `_is_env_context` must
move to a shared module — `loop` imports `selfcompact`, not the reverse.

---

## 13. The exec-intent check answers before consulting the branch written for this case

**A** — `cria/execcheck.py:318`. An `if not entries` early return from 2026-08-01 sits **above** the
`_PROJECT_RUNNERS` branch from 2026-08-13, so the newer branch is never consulted.

**Before** — cria told the completion judge *"no file in the workspace is an entry point"* about a
project that declares `go run` and `go test`. Cell 5 spent 4 exec-intent calls on byte-identical
prompts, ~10,000 reasoning tokens, returning `inconclusive` every time. Hits every library-shaped
project in Go, Rust, Maven and npm.

**After** — let the runners branch answer before the early return.

**Did I confirm the agents?** **No. This is the one item on the list I did not verify myself at
all.** Two walkers reported it independently from different cells, and the vetting pass confirmed it
from git blame — the early return is dated 2026-08-01, the runners branch 2026-08-13, and the newer
fix's own comment names the miss. I am carrying it on their evidence. It is also the lowest-stakes
item here: it costs churn and one false statement to a judge, not a check.

**Verdict**: **SAFE TO LAND.** Blame settles it: the newer fix's own comment names the miss ("the
head-first half landed without its caller"), and no test passes `entries=[]`.

**Honest scope**: fixing this would not have saved cell 5. It is churn and a false statement to a
judge, not a lost check.

---

## 14. The operator's gap-naming ruling is muted twice over

**A** — two gates, not the fix's own three bounds.

1. `~/.cria/cria.toml:45` sets `satisfaction_check_start = 80` (default 100). Drive counts this run:
   42 / 127 / 57 / 44 / 29 / 121 / 47 / 93 — five cells never came close.
2. `_periodic_satisfaction` is blocked by `sess.last_gate_red` (`loop.py:2399`, `:3671`). Cells 2, 6
   and 8 all passed 80 drives; only cell 6 ever ran the check — once, at drive 100, verdict
   `satisfied: true`, so the naming branch was skipped.

**Before** — `loop.satisfaction_gap_named` fired **0 times in all 8 cells**. The ruling is late, and
then closed in exactly the cells that need it: the ones stuck on a broken build.

**This is my placement error.** The ruling is about steering a model mid-task; I attached it to a
mechanism built for *stopping* a model that will not quit after a long session, and it inherited that
mechanism's cadence and its gate. `loop.py:3790-3794` already warned that this path rarely fires.

**After** — **not** a second naming site. `_confirm_done` (`loop.py:3812`) already returns the named
reason when the coder declares done, so duplicating would be the assist-duplication the walk process
forbids. The hole is narrower:

> Between drive 1 and the moment the coder declares done, nothing names a missing deliverable.

The fix is a cadence and a gate that can reach a stuck cell — the two purposes (stop-a-runaway vs
name-a-gap) may need separate numbers rather than one shared threshold, and the red-gate block is
right for stopping and wrong for naming.

**Did I confirm the agents?** **Yes, and I had to correct myself twice.** Five agents said the fix
was unreachable; I dumped the satisfaction events myself and found exactly one `loop.satisfaction_check`
in all 8 cells (cell 6, drive 100, `satisfied: true`). I read `~/.cria/cria.toml:45` myself — the live
threshold is **80**, not the 100 default I first reported — and read the warning comment at
`loop.py:3790-3794` myself. **Not independently checked**: the `sess.last_gate_red` block at
`loop.py:2399`/`:3671`. Those line references are the agents', and they are the second half of the
root, so they should be read before the fix lands.

**Verdict**: needs a prevalence measurement before landing. Doctrine 9 argues for it (one reasoner
call naming the absent deliverable beats forty coder turns of thrash), but the original objection —
steering off a clock is noise on a clock — is what the three bounds were built to answer, and a
changed cadence re-opens it.

---

# Summary

| # | Fix | Reaches A? | Confirmed by me? | Vetting |
|---|---|---|---|---|
| 1 | research step must not name a workspace file as the external source | yes | **partly** — I proved the 4-name score myself and overturned the 1-name headline; the DONE-at-0006 chain is theirs | unvetted |
| 2 | fill the steer author's checks slot from the authoritative gate object (rule 12), not a re-render; keep newlines for check output | yes | **mechanism yes — but I framed it wrong and the operator corrected me**; the backlog already had the better fix | MODIFY FIRST (original version: DO NOT LAND) |
| 3 | evidence-fence "what remains to be done"; relabel the judge's header | yes | **yes for cell 2 + the wiring**; cells 6 and 8 are theirs (two agents, independent) | MODIFY FIRST |
| 4 | rename `__cria_*`; move the matcher; widen the guard test | yes | **yes, all of it** — counted it, found the copied wrapper, pulled the false exit code | MODIFY FIRST |
| 5 | dirguard must judge the shape before the tokens | yes | **defect yes, consequence no** — I have the command and the refusal; the belief-chain is theirs | unvetted |
| 6 | tag the plan-off root task so the existing protection applies | yes | **yes for the fact** — the prevalence table is mine, not theirs; the tagging site I did not trace | unvetted |
| 7 | give `gem_bundler` the reachability half | yes | **yes, by reproduction** — and it corrected my own earlier over-claim | **SAFE** |
| 8 | do not replay a killed loop into its own retry | yes | **yes** — their count was 45, the real number is 42 | unvetted |
| 9 | condition the ruby dependency note on what is on disk | yes | **yes** — read the prompt and cell 1's workspace myself | MODIFY FIRST |
| 10 | condition `no_structure` the way its sibling was conditioned | yes | **text yes, annotations no** — I read the prompt and the sibling precedent; the per-cell stamps are theirs | MODIFY FIRST |
| 11 | name what actually matched, not "the SAME action" | yes | **no — I checked and their premise was wrong**, and I had already repeated it | DO NOT LAND as written |
| 12 | dedup `selfcompact.py:188` onto `loop._is_env_context` | yes | **code yes, cost no** — the vetting pass supplied the fact that settles it | **SAFE** |
| 13 | let the runners branch answer before the early return | yes | **no — the one item I did not check at all** (2 walkers + git blame) | **SAFE** |
| 14 | give the gap-naming ruling a reachable cadence and gate | partly — needs a product decision on cadence | **yes, and I corrected myself twice**; the red-gate line refs are theirs and unread | needs measurement |

**Scoring my own confirmation**: 7 of 14 fully reproduced myself, 5 partly, 2 carried on the agents'
evidence alone (11 and 13 — and 11 is withdrawn as written *because* I checked it). Where I did not
re-derive something, the entry says so rather than borrowing their confidence.

## Agent claims I rejected or corrected

Recorded because a walk that only forwards its agents is not an audit.

| claim | what I found |
|---|---|
| Cell 8 turns on ONE invented name (my own brief said this too) | **Wrong.** Fixing it alone leaves 1/5. Four names are needed for 5/5. |
| Cell 6 "lost its stderr logging" | **Wrong.** The logger is intact; the probe could not build under the renamed module. One cause, two checks. |
| The repetition steer quotes an unmeasured count | **Wrong.** It fires at exactly three and flushes; the number is true. The false part is "the SAME action". |
| `verify_tools.txt` contradicts `satisfaction.txt` in the same prompt | **Rejected.** `verify_tools.txt` is loaded only by `verifytools.py:27`, a separate per-step verifier. Two judges, two contracts. |
| The killed loop is replayed ~45 times | **Corrected**: 42. |
| The live satisfaction threshold is 100 (my own earlier claim) | **Corrected**: `~/.cria/cria.toml:45` sets 80. |
| The bundler advice explains the Ruby column (my own earlier claim) | **Corrected**: 1 of 4 Ruby cells took that route. |

**Three are clean to land now** (7, 12, 13). **Four must be landed as an added condition rather than
a reworded sentence** (3, 4, 9, 10) — the repo settled that remedy twice already. **One is
withdrawn as first written** (11). The rest need vetting first.

**Two items are one root each behind several findings**, which is where the leverage is: #2 explains
three separate losses, and #3 explains three more.
