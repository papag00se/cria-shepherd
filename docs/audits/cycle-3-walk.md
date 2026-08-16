# Cycle 3 walk — the 8 cells of the 04:48–08:21 run, 2026-08-16

24 agents walked the run call by call. Every claim below I re-checked myself against the artifacts;
each finding carries **VERIFIED** (I reproduced it) or **REPORTED** (an agent's evidence, quoted,
not independently reproduced). Subagent claims are signals, never verdicts — three are marked
CORRECTED or REJECTED where mine disagreed.

**Housekeeping**: all 8 cells ran on one cria code state (git `93e84b8`). Every later SHA in the
result rows is a docs-only commit. The rows are comparable.

| # | task | model | score | terminal | session |
|---|---|---|---|---|---|
| 1 | shipping-rates-rb | gemma4 | 3/5 | exited, 490s | `01a00a66` |
| 2 | shipping-rates-rb | qwen35 | 0/5 | floor@15min, 954s | `01a00a6e` |
| 3 | shipping-rates-rb | ternary-bonsai | 4/5 | floor@75min, 4544s | `01a00a7d` |
| 4 | shipping-rates-rb | nemotron-elastic | 0/5 | floor@15min, 948s | `01a00ac3` |
| 5 | cart-billing-go | gemma4 | 4/5 | exited, 805s | `01a00ad2` |
| 6 | cart-billing-go | qwen35 | 3/5 | exited, 1203s | `01a00ade` |
| 7 | cart-billing-go | ternary-bonsai | 1/5 | floor@30min, 1848s | `01a00af1` |
| 8 | cart-billing-go | nemotron-elastic | 1/5 | floor@30min, 1849s | `01a00b0e` |

Ruby 7/20 = 35%. Go 9/20 = 45%.

---

## The headline

**Most of this run's losses are cria's, and they concentrate in two places.**

Cycle 2 closed with the note that losses were increasingly *the model leaving a structural edit
half-done*. That reading does not survive this walk. Four of the run's clearest losses trace to cria
telling the model something untrue, and two more to cria removing something the model needed.

The two places:

1. **The steer author prescribes specifics from clipped or stale evidence.** Four separate losses,
   one root.
2. **The compaction summary is asked to invent a to-do list, and its answer is then treated as
   fact** — pinned into the coder's prompt as a briefing, and filed to the completion judge under a
   header that says "(ground truth)".

---

# Tier 1 — cria stated a false fact and it cost a check

## 1. cria prescribed the exact symbol its own gate said does not exist — VERIFIED

**Cell 8**, call 0044. The prompt cria composed contains the compiler's
`undefined: decimal.NewFromFloat64` **23 times**. In that same prompt, cria's own steer says:

> ⟦ctx:steer⟧ Read …/cart.go with read_file, then edit the file to replace the floating-point
> `sub * 1.08` with a decimal multiplication **using decimal.NewFromFloat64**, round the result
> correctly, and add the required [code removed — written by this supervisor, not read from your
> files or your checker output; make the change in your own code] line that logs the subtotal…

`NewFromFloat64` does not exist in `shopspring/decimal`; the real method is `NewFromFloat`. The model
had invented the name unaided at call 0013, three minutes in. cria then **endorsed it**, and the
model stopped questioning it for the remaining 63 calls. The cell scored 1/5 on that one identifier.

Note what the dictation strip did: it removed the neighbouring logging line as supervisor-authored
code, and passed the poisoned symbol through. The strip keeps a span if cria "observed" it — and
cria had observed it, in the body of the file that does not compile.

**Chain**: A = the steer author may name a symbol without checking it against the gate's own
undefined-symbol list → B = cria endorses the model's invention → C = the model never revisits it.

**Severity**: blocks-every-check in cell 8.

## 2. cria named the wrong failing test and prescribed a change that would red the right one — VERIFIED

**Cell 4**, call 0047. Nineteen lines apart in one prompt:

```
TestRates#test_oversize_surcharge_still_applies_to_free_shipping [ …/test/test_rates.rb:23]:
Expected: 12.0
  Actual: 0.0
```
```
⟦ctx:steer⟧ The failing test test_domestic_light_parcel reports Expected: 0.0 Actual: 7.24 .
… Fix it now by editing ./lib/shipping/rates.rb to set the domestic surcharge to 0.0
(e.g., change OVERSIZE_SURCHARGE = 0.0 for that zone), then run rake test to verify the test passes.
```

Wrong test, wrong numbers, and the prescription sets to `0.0` the very constant the failing test
asserts is `12.0`. The coder's own thinking that turn had it right and it lost the turn anyway. The
same defect repeats at call 0057.

**Root (REPORTED, agent's evidence)**: the steer author's evidence clips each check block to
head-200 + tail-200 characters, and cria's own preamble is 307 characters — so the failing test's
name lands in the elided middle every time. Compounding it, minitest stamps a random `--seed` per
run, so identical failures never dedup and the window carries a stale failure 5× against the live
one 2×.

**Severity**: blocks-a-check; consumed the cell's remaining turns.

## 3. cria invented a package version and ordered the coder to use it — REPORTED

**Cell 7**, call 0031. The coder had just read real search results and concluded *"Let me use
`v1.4.0`"*. cria's redirect then ordered: *"Update go.mod with a real published version like
`v1.32.0`."* That version does not exist. The steer author's own thinking admits the guess: *"The
most common stable versions are things like v1.32.0, v1.34.0, etc."*

Same root as #2: the steer author's transcript clips tool results to 400 chars head+tail; the search
result lost 1,812 middle characters — every version number in it. `grep v1.4.0` in that prompt
returns zero hits.

## 4. cria chose the library, which its own prompt forbids — REPORTED

**Cell 4**. cria's redirect told the coder to use the `eu_countries` gem. The coder obeyed and spent
its last 25 calls on a gem last touched in 2013 — while the right answer (`countries` → `in_eu?`)
sat in its prompt the whole time. The steer prompt explicitly forbids choosing the implementation.

## 5. cria computed the fix that compiles, then deleted it — REPORTED

**Cell 7**, call 0045. cria authored `decimal.NewFromInt(int64(it.Quantity))` and `taxed.Round(2)` —
both correct. The dictated-code strip replaced both with `[code removed…]` before delivery. The coder
then guessed and invented `decimal.NewFromInt64` and `taxed.Round(2, 0)`, which is what the cell died
on.

**Not proposed as a fix.** `loop.py:7006-7015` carries the opposite incident, and the strip is
correct policy — cria must not author the coder's work. Recorded because it shows the cost side of a
rule worth keeping, and because #1 above shows the strip is *inconsistent*: it removed a correct
repair here and passed a poisoned symbol there.

### The common root of 1–5

All five are the **steer author**. It is handed a clipped transcript, a stale check block, and no
obligation to reconcile what it says against the ground truth sitting in the same prompt. Doctrine 8
says deterministic code gathers facts and a reasoner judges — the gathering half is what is failing
here, not the judging.

---

# Tier 2 — cria's own briefing contradicted the task

## 6. The compaction summary told the model to break the task's first rule — VERIFIED

**Cell 2**, call 0131, one prompt file, two passages:

- line 103 — the task:
  > "1. Fix the failing repository tests. **Do not change assertions in tests that came with the
  > repo.** Tests you add may be changed freely."
- line ~142 — cria's pinned briefing:
  > "**Update the test expectations in `test/test_rates.rb`** to match the actual behavior of the
  > `shipping_cost` method with country codes."

The model obeyed the briefing and changed the seeded `test_unknown_zone_rejected` from
`ArgumentError` to `NameError`. That is verbatim the `verify.py` failure recorded for cell 2.

## 7. The same generator invented deliverables, and cria filed them as ground truth — VERIFIED (chain), REPORTED (call numbers)

**Cell 6**. cria asked its compactor for a briefing; the compactor's *"What remains to be done"*
section invented a `main.go` startup call that the Go task never asks for. cria then re-served that
invention verbatim under `⟦ctx:continuation⟧` on every later prompt **and** handed it to the
completion judge inside `{{EVIDENCE}}`, under this header
(`cria/prompts/satisfaction_user.txt:4`):

> `THE CODER'S REAL ACTIONS AND THEIR OUTPUTS SO FAR (ground truth):`

The judge quoted the invention back as the user's words — *"The task explicitly requires: 'Load the
discount codes from discounts.json at startup'"* — and ruled NOT_DONE. The coder noticed
(*"the task doesn't mention a main.go file"*) and complied anyway: built `main.go`, hit two packages
in one directory, restructured, and renamed the module.

### What that cost, measured — VERIFIED

I copied cell 6's archived workspace and changed **one token**, `module billing` → `module cartsvc`:

```
as-is (module billing)     3.0/5   FAIL rounding_fixed_everywhere   FAIL logging
one token changed           5.0/5   all five green
```

The 15-minute milestone had scored this cell 5/5. **Two points were lost to one word in `go.mod`.**

And a correction to my own earlier reading of the result row: **`logging` never regressed.** The
stderr logger is intact in the final code. It failed only because the verifier's probe is a
`package main` file that does `import "cartsvc"` and would not build. Both failed checks are the same
cause. Nobody should go hunting for a deleted logger.

**Root**: `cria/prompts/selfcompact_summary.txt` forbids planning next steps on line 1 and then asks
for "What remains to be done / the next step" on line 8, with no evidence rule on that bullet. A
tool-less compactor answers by inventing.

**Chain**: A = the compaction prompt asks a tool-less model to plan → B = it invents deliverables and
mis-states the task's constraints → C = the briefing is pinned to every later prompt and filed to the
judge as ground truth, and the coder does what it says.

---

# Tier 3 — cria removed something the model needed

## 8. cria deleted the task text from the coder's prompt — VERIFIED, with prevalence

I checked every coder prompt in all 8 cells for the task's own opening line:

| cell | coder calls | missing the task | which calls |
|---|---:|---:|---|
| C1 rb/gemma4 | 39 | 0 | — |
| C2 rb/qwen35 | 118 | 2 (1%) | 0069, 0084 |
| **C3 rb/bonsai** | 55 | **9 (16%)** | 0052, 0054–0060, 0062 |
| C4 rb/nemo | 43 | 0 | — |
| C5 go/gemma4 | 26 | 0 | — |
| C6 go/qwen35 | 109 | 4 (3%) | 0050, 0052, 0056, 0061 |
| C7 go/bonsai | 43 | 0 | — |
| C8 go/nemo | 92 | 0 | — |

Not systemic — but cell 3's nine are **the last nine coder calls of a 76-minute run**. That cell
finished one check short, and spent its tail with no statement of what it was for.

**Root (REPORTED, two agents agreeing)**: with the planner off, the harness's task turn carries no
`⟦ctx:task⟧` marker, so the context floor's protected-message mask treats it as ordinary history and
drops it as the oldest droppable message.

## 9. The rumination retry re-injects the loop it just killed — VERIFIED

**Cell 8**, calls 0002→0003. The degenerate-tail guard correctly killed a research call that was
emitting `But there is "github.com/mitchellh/mapstructure"? Not.` on infinite repeat. cria then
retried — and built the retry prompt with the killed output quoted back as `You answered:`.

```
0002 prompt: 1,590 bytes
0003 prompt: 10,642 bytes  —  42 verbatim repeats of the killed loop
```

The guard's whole purpose is to stop a model looping. Showing it 42 copies of its own loop as the
immediate context is an invitation to continue.

## 10. The completion checker cannot reach the cells that need it — VERIFIED, and worse than I wrote

`loop.satisfaction_gap_named` — the operator's 2026-08-15 ruling that the completion checker may name
a missing deliverable — fired **zero times in all 8 cells**. I had assumed one of its three bounds
was swallowing it. It is not. Two gates upstream mute it:

1. **Drive threshold.** `~/.cria/cria.toml:45` sets `satisfaction_check_start = 80` (overriding the
   `config.py:437` default of 100). Drive counts this run were roughly 42 / 127 / 57 / 44 / 29 /
   121 / 47 / 93 — five cells never got close.
2. **Blocked on a red gate.** `_periodic_satisfaction` is blocked by `sess.last_gate_red`
   (`loop.py:2399`, `:3671`). Cells 2, 6 and 8 all passed 80 drives; only cell 6 ever ran the check —
   once, at drive 100, verdict `satisfied: true`, so the naming branch was skipped. Cells 2 and 8
   were red whenever it came due.

So the ruling is muted twice: **late, and then closed in exactly the cells that need it most** — the
ones stuck on a broken build.

**My error, stated plainly.** The ruling is about steering a model mid-task. I attached it to a
mechanism built for *stopping* a model that will not quit after a very long session, and it inherited
that mechanism's cadence and its gate. A comment in the same file already warned that this path
rarely fires (`loop.py:3790-3794`). I did not act on it.

**Do not duplicate the naming.** `_confirm_done` (`loop.py:3812`) already returns the judge's named
reason when the coder *declares done*. The real hole is narrower: between drive 1 and the moment the
coder declares done, nothing names a missing deliverable.

---

# Tier 4 — model-facing hygiene

## 11. The leaked gate wrapper manufactures false success — VERIFIED. Not cosmetic.

`cria/proberun.py:709-719` composes the gate shell with variables named `__cria_out`, `__cria_ec`,
`__cria_n`. My count on cell 2 call 0034: 44 + 24 + 24, plus 6 × `__cria_test` = **98 in one prompt**,
and **114 of 134 prompt files in that cell carry them**. Seven agents found it independently across
six cells. That much is the doctrine-17 violation, and it is the part that was already known.

**What is new, and what makes this a Tier-1 defect rather than hygiene: the model copies the idiom
and it produces a false exit code.** Cell 8, calls 0051, 0062, 0065 — the model wrote cria's private
capture wrapper into its own `exec_command`:

```
cd /tmp/suite-…-w290d284 && __cria_out=$(timeout -k 5 240 go build -o cartsvc ./... </dev/null 2>&1);
__cria_ec=$?; __cria_n=$(printf '%s' "$__cria_out" | wc -c | tr -cd '0-9'); if [ … ]; …;
printf 'EXIT:%d\n' "$__cria_ec"
```

The wrapper's last statement is a successful `printf`, so the *shell* exits 0 no matter what ran
inside. The tool response the model got back:

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

Two exit codes in one response, contradicting each other, and the false one sits in the harness's own
standard header position. cria knows to read its `EXIT:` sentinel; the model has no reason to. This is
the same class as the output-truncation and self-truncated-write footguns already fixed — a failed
operation reported as a success.

The existing guard
(`tests/test_gate_script_is_read_only.py::test_litter_bookkeeping_never_reaches_the_model`) checks
only `__cria_pre` / `__cria_post` / `__cria_new`, which is why this survived. A rename must also move
the sentinel matcher at `cria/probegate.py:834`.

## 11b. dirguard refused the model's shell binary, and the model concluded the sandbox was broken — VERIFIED

Cell 8, all 10 `writeproxy.blocked_external` events. The model emitted a malformed nested tool call —
it pasted the tool *signature* text into the shell command:

```
exec_command cmd="go mod download", justification="…", max_output_tokens=10000,
yield_time_ms=30000, tty=true, shell="/bin/bash", login=true, workdir="/tmp/suite-…"
```

`dirguard` saw `/bin/bash`, treated it as a path outside the workspace, and answered:

> ⟦ctx:denied⟧ Writing/reading outside the working directory is not permitted here — keep every file
> you read or write inside the project directory (/tmp/suite-…)

`go mod download` reads no file outside the workspace. The refusal names a rule the command did not
break, and the advice ("keep it inside the project directory") is impossible to act on because there
is nothing to move.

**What it caused (REPORTED, two agents agreeing).** The model generalised it: *"denial of exec_command
might be due to sandbox restrictions"* (0056) → *"we cannot use exec_command to run go commands"*
(0081) → *"The sandbox denies external commands"*. It then spent 27 straight calls blaming module
resolution for `undefined: decimal.NewFromFloat64` and never revisited the symbol name. `go mod tidy`
and `go build` had both run fine every time it wrote a clean command.

**Chain**: A = dirguard inspects a malformed command's tokens without noticing the command is
malformed → B = a false denial the model cannot act on → C = the model believes its toolchain is
fenced off and stops investigating the real error.

## 12. `gem_bundler` installs a gem where nothing can load it — VERIFIED by reproduction

`cria/prompts/install_remedy.txt`:
```
gem_bundler = Install it into the project instead: add the gem to a `Gemfile` and run
              `{{BUNDLE}} install --path vendor/bundle`.
```

Reproduced on cell 2's real artifact (a genuine `--path` install):

| invocation | result |
|---|---|
| `ruby -Ilib -e 'require "countries"'` — **what `verify.py` runs** | `kernel_require.rb:86: cannot load such file (LoadError)` |
| with `require "bundler/setup"` | LOADED |
| under `bundle3.2 exec` | LOADED |
| with `GEM_HOME=vendor/bundle/ruby/3.2.0` | LOADED |

That LoadError is byte-for-byte cell 2's result row.

**The asymmetry that makes it cria's defect.** Every other route in that file carries a reachability
half: `pip_venv` → "then run with `./.venv/bin/python`"; `npm_local` → "which is what your code will
load"; `gem_direct` → "then make it loadable by putting that directory on the load path…";
cargo/go/composer/maven resolve automatically. **`gem_bundler` alone says how to install and not how
to reach it** — and its own sibling two lines down already carries the missing sentence.

The generalisation is not task-specific: a project-local install reachable only through a wrapper
command is unreachable to any consumer that does not use the wrapper. Here that consumer is
`verify.py`'s hidden test, which the model does not write.

**Prevalence — MEASURED, and smaller than I assumed.** I claimed in cycle 2 that this explained the
Ruby column. It does not. Of the four Ruby workspaces:

| cell | what is actually on disk | verdict |
|---|---|---|
| 1 | `Gemfile` only, no `vendor/bundle`, no `.bundle/config` | gem never installed — different failure |
| 2 | real `--path` install; `bundler/setup` in its own test file only | **this trap, exactly** |
| 3 | no bundler at all — hand-downloaded and unpacked two tarballs | ignored the advice |
| 4 | no `Gemfile` at all | never tried |

One cell's blocker, cleanly proven, and a latent trap for the rest.

## 13. The ruby dependency note asserts an install that never happened — VERIFIED

`cria/prompts/dependency_note.txt:10`:

> "Note: `{{NAME}}` is installed nowhere ruby is looking. **A gem installed with --install-dir is not
> on the load path by default** — set GEM_HOME to that directory… **Fix the loading; the code that
> uses it is not what failed here.**"

Keyed on ecosystem alone. It fires when nothing has been installed by any route, presupposes an
`--install-dir` install that never happened, and then rules out the one correct move ("fix the
loading, not the code" — when the actual fix is to install it). Cells 1, 2 and 3 all took it.

Its own header comment says it was written for the opposite case: *"8 checks failed with the
dependency declared correctly and simply not reachable… 'install it' was never the missing step."*
The note is right for that case and wrong for this one, and nothing distinguishes them.

## 14. API-spec language on a Ruby documentation page — VERIFIED

`cria/prompts/fetched_facts_sections.txt:55`:

> `no_structure = (this page answered, but no endpoint definitions were found in it … nothing read
> so far DEFINES the API's routes)`

Three agents found this annotating fetches of the `countries` gem's README and rubydoc pages, on a
task with no API in it. In cell 1 the model then invented `Countries::Country#in_european_union?`;
the real `in_eu?` was on line 166 of the file cria was holding.

The sibling key immediately below (`no_spec_here`) exists because this exact over-claiming was
already narrowed once, for a different case. `no_structure` is the same class, unnarrowed.

## 15. The repetition steer states a count it never measured — VERIFIED

`cria/loop.py:5629-5631`:
```python
"repetition": lambda gs, step: (
    f"It keeps repeating the SAME action {REPEAT_FINGERPRINT_N}× without the outcome changing: …"),
```

The number in the sentence is the **threshold constant**, not the observed count. Cell 1 call 0024
told the reasoner the coder had run `gem install countries` three times. It ran once — the
fingerprint had matched `gem list countries` against `gem install countries`. The reasoner repeated
the false count back verbatim and wrote its redirect on that basis. Doctrine 12: surface a metric
from the authoritative event, never a re-count.

## 16. One naive picker where another module already defends — VERIFIED

`cria/selfcompact.py:188` takes the first user-role message as the task, on a comment asserting the
harness frame is dropped upstream. `cria/loop.py` does not rely on that assumption anywhere: it has
`_is_env_context()` (`loop.py:4456`) and applies it at four sites to skip harness env preambles. One
module trusts, the other defends. The divergence is the defect; the fix is a dedup onto the existing
owner, not a new guard.

---

# What worked

Recorded because a walk that only lists faults is not a measurement.

- **The completion gate failed closed.** Cell 1: blocked three straight `task_complete` calls on real
  red checks and opened only when they were genuinely green. Cell 6: blocked at 14:15:49 on red,
  passed at 14:19:15 when `go vet` / `build` / `test` all genuinely passed.
- **The degenerate-tail guard was right 10 times out of 10.** All 10 `rumination.abort` events in the
  run are on one model (nemotron-elastic). I inspected the first: a genuine infinite loop. No false
  positive found. (Its retry behaviour is finding #9.)
- **The dictated-code strip fired correctly** in cells 2, 6 and 7 — including one case where the
  supervisor emitted a path that resolved outside the workspace, and one where it emitted a
  `write_file` that would have deleted 13 seeded tests.
- **`ground_truth_failed_also` (cycle-2 fix #3) fired and worked** in cell 6 call 0019 — the model
  fixed all six reported problems by 0022. In cell 7 it correctly stayed silent: nothing was
  unparsed, and the compiler's full message including `struct{value *big.Int; exp int32}` reached
  the model verbatim every turn. **The gate is innocent in cell 7.**
- **The vendor-tree inventory fold and the two new stream guards correctly stayed silent** — their
  conditions did not occur.

---

# Corrections to my own earlier reporting

- **"cell 6 lost its logging"** — wrong. The logger is intact; the check failed because the
  verifier's probe could not build under the renamed module. One cause, two checks.
- **"the bundler advice explains the Ruby column"** — wrong. One of four cells took that route.
- **"the gap-naming fix is blocked by its three bounds"** — wrong. It never reaches them; the host
  check is gated at drive 80 and blocked on a red gate.
- **"the live threshold is 100"** — wrong. `~/.cria/cria.toml` sets 80.
- **REJECTED, an agent claim**: that `verify_tools.txt:6` ("one executable next step") contradicts
  `satisfaction.txt:24` ("never a command") in the same prompt. It does not. `verify_tools.txt` is
  loaded only by `cria/verifytools.py:27`, a separate per-step verifier with its own tool loop.
  `judge_satisfaction` loads `satisfaction` + `satisfaction_user` + `reasoner_coder_tools` and
  nothing else. Two judges, two contracts, both defensible.

---

# Ranked for the fix phase

Ordered by points recoverable × confidence. Every candidate names the A in A→B→C.

| # | Fix at A | Cells | Evidence |
|---|---|---|---|
| 1 | Remove or evidence-fence "What remains to be done" in `selfcompact_summary.txt`; stop labelling a model-written summary "(ground truth)" to the judge | 2, 6 | VERIFIED — 2 points in cell 6 alone, reproduced |
| 2 | Rename the `__cria_*` gate variables; move the sentinel matcher with them; widen the guard test | all, worst in 8 | VERIFIED — the model copies the idiom and gets "exit 0" on a failed build |
| 3 | The steer author must not name a symbol, version, or library the ground truth in the same prompt contradicts | 4, 7, 8 | VERIFIED (cell 8), REPORTED (4, 7) |
| 4 | Stop clipping the check block the steer author reasons from (head-200 + tail-200 vs a 307-char preamble) | 4, 7 | REPORTED, precise |
| 5 | dirguard must not refuse a malformed command on its stray tokens — refuse the shape, or say the command was unparseable | 8 | VERIFIED |
| 6 | Mark the plan-off root task as protected so the context floor cannot evict it | 2, 3, 6 | VERIFIED, with prevalence |
| 7 | Give `gem_bundler` the reachability half `gem_direct` already has | 2 | VERIFIED by reproduction |
| 8 | Do not re-inject a killed degenerate loop into its own retry prompt | 8 | VERIFIED |
| 9 | Make the ruby `dependency_note` distinguish "not installed" from "installed and unreachable" | 1, 2, 3 | VERIFIED |
| 10 | Narrow `no_structure` the way `no_spec_here` was already narrowed | 1, 2, 3, 4 | VERIFIED |
| 11 | Do not collapse newlines in a tool result before the supervisor reads it (`selfcompact.py:261`) | 8 | REPORTED, precise |
| 12 | Pass the observed repetition count, not the threshold constant | 1 | VERIFIED |
| 13 | Dedup `selfcompact.py:188` onto `loop._is_env_context` | 5 | VERIFIED |
| 14 | Give the operator's gap-naming ruling a cadence and a gate that can actually reach a stuck cell | all | VERIFIED |

---

# Anatomy of cell 8 — five cria defects on one identifier

Worth setting out in full, because it is the cell where the model's own mistake was smallest and
cria's contribution largest. The model wrote `decimal.NewFromFloat64` at call 0013, three minutes in.
The real name is `NewFromFloat`. It never fixed it in 94 more calls. Here is why.

1. **cria endorsed the invented name.** The periodic-gate steer (0042/0044) said to use
   `decimal.NewFromFloat64` — with the compiler's `undefined: decimal.NewFromFloat64` printed 23
   times in the same prompt. The redirect reasoner at 0047 then ordered *"replace every occurrence of
   `decimal.NewFromFloat64` with `NewFromFloat64`"* — also undefined.
2. **The dictation strip kept the poison and removed the cure.** It deleted an already-correct
   `fmt.Fprintf(os.Stderr, …)` line as supervisor-authored code, and passed the bad symbol through:
   a bare dotted name is not code-shaped, and `_observed_code` whitelists anything seen in a tool
   result — so the more the compiler printed the bad symbol, the more strip-proof it became.
3. **A false denial convinced the model its toolchain was fenced off.** See 11b above.
4. **A false exit code told it a failed build had succeeded.** See 11 above.
5. **cria interrupted the read the model needed to make the fix.** At 0032 the model reasoned its
   way to *"`NewFromFloat64` does not [exist] … the correct function name"* and ended with *"First,
   read the current cart.go content to see the exact lines."* cria answered that read with the
   repetition fold: *"you have now made this exact call 2 times … Repeating it again will return that
   same result … take a DIFFERENT action."* It never came back to the edit.

   **Nuance, against one agent's stronger claim**: the model had the right *diagnosis* and the wrong
   *replacement* — its chosen fix was `decimal.FromFloat64`, also undefined. So this was not one step
   from the answer. But it was the one turn where the model was looking in the right place, and cria
   told it to stop looking.

**What cria got right in the same cell**: the compiler message was never lost. The gate showed it
verbatim on every build, with the on-disk source line annotated correctly, 23-26 copies present in
every prompt. Cell 8 did not fail for lack of the error text — it failed because four cria messages
contradicted it and the fifth cut short the investigation.

Each must be checked against existing incident comments and test docstrings before landing — several
touch code that carries the opposite incident.
