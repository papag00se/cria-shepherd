# Cycle 2 — walk findings

Eight agents over nine runs, 297 chunk files, 17.1 MB, read line by line per `docs/walk-prompt.md`.
Three have reported so far.

**Every claim below carries its verification status.** A walk finding is a CANDIDATE; the walk prompt
says subagent suggestions are signals only. `VERIFIED` means I re-ran the check myself against the
capture or the code and quote the result. `REPORTED` means the agent quoted bytes I have not
independently re-opened.

---

## orders-api-py_ternary-bonsai_codex_poff_1786824929

*Agent read 12 of 18 chunks end to end and the new material in the other 6; it said so.*

### 1. The regression: call 0057 deleted the parameter the grader uses — VERIFIED

`sql_injection_fixed` was green at 15 and 30 minutes and red at 45. The write at call 0057 stripped
`path=` from every public function in `orders/db.py`.

The seed ships:
```python
def get_order(order_id, path=DB_PATH):
def all_orders(path=DB_PATH):
```
The delivered file has `def get_order(order_id):` and `def all_orders():`. And `verify.py:225/235`
probes the injection **through the module**:
```python
out["normal"] = bool(db.get_order(1, path={dbp!r}))
out["alive"]  = bool(db.all_orders(path={dbp!r}))
```

Reproduced cold against the archived workspace:
```
get_order()  got an unexpected keyword argument 'path'
all_orders() got an unexpected keyword argument 'path'
```

The SQL was still parameterised and still safe. The model deleted the door the grader knocks on.
**cria fault: none for the write** — no steer or gate fired between 0056 and 0057.

### 2. cria has NO memory of what was green — VERIFIED by reading the code

This is the finding that matters, and it generalises past this cell. cria's only cross-round memory
of the working tree is `git status --porcelain | sha1sum` (`probegate.py:168`) — a changed/not-changed
digest that records no filenames. Nothing compares round N's passing checks against round N−1's.

**A check that goes from passing to failing is indistinguishable, to cria, from one that was always
failing.** This run's score went backwards and every mechanism cria has was blind to it.

The gate's own steer told the model in that same round: *"changing the test so it stops asking is not
a fix."* The model had edited the seed's `tests/test_db.py` one call earlier. cria states the rule in
prose and cannot detect its violation.

### 3. A steer that stated three false facts — VERIFIED verbatim

Call 0034, exact bytes from the capture:

> ⟦ctx:steer⟧ … The test then calls _request(host, port) with that same 0 , **which fails because you
> can't connect to port 0**. **Change line 24 from port = 0 to a fixed port like 9987**, and update
> lines 31–32 to return host, port . **That single change makes the test discoverable and working** …

The `⟦ctx:checks⟧` block **in the same prompt** says the failure is
`AttributeError: 'tuple' object has no attribute 'rfind'` at `HTTPConnection((host, port))`. It never
reached a connect. The model made the prescribed change; the next gate returned the identical error.
It fixed the real bug itself two calls later.

`cria/prompts/steer_diagnose.txt` forbids all three moves explicitly:

> - *Do not choose the IMPLEMENTATION. Which library to use, which data structure, which flag … Measured: directives that picked the approach cost nine checks.*
> - *Do not state a CAUSE you have not verified … Measured across twenty-four such directives, the coder's own reading was right and the directive was wrong every single time.*

**cria fault: yes.** And `loop.steer_dictated_code` never fired on this session — VERIFIED, zero
steer-related events. The guard (`_CODE_SHAPED`) matches code-shaped text; this directive dictates an
implementation in plain English and passes straight through.

### 4. The swept `orders.db` — REFUTED as a model-facing event

No call shows the model observing the database missing. The sweep at 13:25:53 local landed before the
file carried rows. **cria fault: none for the deletion**, which corrects my own earlier framing.

---

## shipping-rates-rb_ternary-bonsai_codex_poff_1786812235

*Agent read all 16 chunks; full line-by-line for 01–06, every new byte in 07–16.*

### 1. HTTP 202 read as settled content — VERIFIED in code

The model fetched a rubydoc page that answered:

> `HTTP 202 Accepted · … countries (5.7.0) is being processed. You'll be redirected when the pages are built`

cria then refused the re-fetch with:

> `⟦ctx:denied⟧ You already fetched … and re-fetching returns the same content you were given earlier`

`webfetch.py:1214` gates on `200 <= c_status < 300`, so 202 takes the "same content, use it" branch.
**202 Accepted is the one 2xx that promises the content will change.** The comment above that line
records `898ef78`, which added the split precisely to stop cria saying "use it" about something that
was not there. Extending it to 202 completes that fix rather than reverting it.
Fired 3×, and is what pushed the model off the maintained gem onto a 2013 one. **cria fault: yes.**

### 2. The install remedy is a REGRESSION created by its own fix — VERIFIED in code

`_tool_present` returns a **bool** (`dirguard.py:217`), and `_local_install_advice` returns the prompt
string **verbatim** (`dirguard.py:251`). `_versioned_variant` discovers `bundle3.2` and the name is
discarded before it can reach the sentence.

Before `3ac1f19`, `gem_bundler` failed its tool check and cria fell through to `gem_direct`. The agent
ran all three routes on this box:

| route | result |
|---|---|
| `bundle install --path vendor/bundle` — what cria emitted 10× | `bundle: command not found` |
| `gem install --install-dir vendor/bundle` — `gem_direct`, now suppressed | 3 gems installed |
| `bundle3.2 install --path vendor/bundle` — the name cria found, then dropped | Bundle complete |

**The one route cria named is the only one of the three that cannot run.** REPORTED for the three
route results; VERIFIED for the code path and for `which bundle` → nothing.

### 3. The unstick steer prescribed the exact command already refused — REPORTED

Call 0046's steer told the coder to run `gem install bundler --user-dir vendor/bundle` — byte-for-byte
the command denied at call 0045. The coder ran it and was denied again. Call 0055 then told it to
fetch a `.gem` binary with `web_fetch`, which returns rendered text.

### 4. The model never once reasoned about the missing binary — REPORTED

Its complete reasoning across the fight is six variations of *"blocked by sandbox restrictions"*.
`bundle: command not found` arrived at 0043 and produced no reasoning at all. It treated cria's
remedy as authoritative and its own contrary evidence as noise.

### 5. Both typo guards missed the real corruptions — REPORTED, and it is the third enumeration

`_typo_fold` folds case and dash/underscore only, so a **deleted character** never folds to equality.
The dropped-word and dropped-digit paths both returned False; the reasoner's own dash-for-underscore
slip would have returned True. Separately, `_NETWORK_CMD` matched the `https://rubygems.org` string
being echoed into a Gemfile and exempted the whole command, so the external `cd` target was skipped.

This is the third typo class added by enumeration (`feedback_matchers_by_shape`). The kernel question
— *is this within one edit of the workspace root* — is deterministic and covers all three at once.

---

## cart-billing-go_nemotron-elastic_codex_poff_1786820112

*Agent read all 36 chunks; full for 01–16, every new byte thereafter.*

### 1. cria executed a fetch the coder never called, and wrote it in as the coder's turn — VERIFIED

The highest-value finding of the walk so far. At call 0008 the coder was about to run a **web_search**
— confirmed by call 0009's reasoner prompt, verbatim from the capture:

> `THE QUERY IT IS ABOUT TO SEARCH:\ngithub.com guyp decimal README`

The supervisor answered `{"on_target": false, "recommendation": "https://github.com/guyp/decimal"}`.
Call 0010's **assistant** message then contains:

> `web_fetch {"url": "https://github.com/guyp/decimal"}` → `HTTP 404 Not Found`

The coder never made that call. The 404 entered the durable `⟦ctx:facts⟧` ledger and was reprinted in
every remaining turn, and the critic cited it as grounds for not-done six times.

**This is deliberate, and that is why it is being surfaced rather than fixed.** `loop.py:477-478`:

> *"recommendation is the better search string OR a concrete URL to fetch instead (**the caller
> substitutes a web_fetch when it's a URL**)"*

It collides head-on with principle 2's corollary — *"cria never SUBSTITUTES its own action for the
coder's: surface the fact, steer, and let the coder act"* — and with 5b, because the transcript then
asserts an action the coder did not take. **Operator ruling needed**, same class as c1-13.

Two sub-defects are unambiguous regardless of that ruling:
- **The recommended URL is never validated.** The supervisor prompt says *"grounded in the task, never
  invented"*; `guyp/decimal` appears nowhere in the task and nowhere in any of the five searches, all
  of which returned govalues / shopspring / ericlagergren / db47h.
- **The name entered the plan from the model's own draft.** cria's step-corrector fed the coder's
  guess back under `You answered:` and forbade only *new* names, so the model read its own invention
  as task text: *"The task does name github.com/guyp/decimal. So we can reference it?"*

### 2. `unsupported call: task_complete` — REPORTED, 7 occurrences

cria advertises `task_complete` in the coder's function list and names it in its own refusal text —
*"The tools you have this turn are: … task_complete …"* — then answers `unsupported call:
task_complete`. Seven turns lost.

### 3. The steer drops the one line that disambiguates the fix — REPORTED

At call 0077 the coder fixed the test correctly. The next `⟦ctx:checks⟧` carried
`the flagged line on disk — line 47: t.Errorf(...)`; the `⟦ctx:steer⟧` appended after it — the last
thing before the model's turn — dropped that quote. The model guessed the wrong line and **reverted
its own working fix**, reinstating the defect that scored the cell 0. The agent reports all four
`flagged line on disk` strings live in checks blocks and zero in any steer.

### 4. The compactor was fed a transcript with the failures stripped — REPORTED

The briefing wrote *"The build passes … No failures are currently reported"* while `go test` was
failing. The transcript handed to it contained 15 gate invocations and only 5 tool results; ten
`⟦ctx:checks⟧` responses were missing, and `grep -c "ctx:checks"` on that chunk returns 0.

*Contained downstream* — the briefing is delivered inside `⟦ctx:continuation⟧` labelled *"NOT verified
ground truth, in EITHER direction"* followed by a live checks block ending *"Trust this over any claim
above."* The guard held. The defect is in what compaction is **fed**.

### 5. What the model did on its own — cria fault: none

It wrote `got.String()` against a `Total()` still returning `float64`, asserting in the same turn that
it had already changed the return type, 300 lines after cria's own `read_file` returned the real
source. The gate quoted line 46 verbatim eight times. The model overwrote its own eyes.
