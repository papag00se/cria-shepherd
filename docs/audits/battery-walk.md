
## orders-api-py_ternary-bonsai_codex_poff_1786367926

**cria fault: yes** — three defects, one run. **All three fixed 2026-08-10** (`d7e7cf3`, `78a0be4`, `e94a5f1`), each with a test that fails before and passes after; full suite 2,914. They live in the coaching path, so no baseline row is affected and none needed superseding. BASE 3/4 in 31 calls / 7.8 min → CRIA 2/4 in 113
calls / 60.1 min. Walked call-by-call, 25 agents, every call read in order; 69 candidate incidents
raised, 8 refuted on adversarial re-check.

**The model solved it in 70 seconds. Both times.** The baseline wrote the full `db.py` (status
column, index, `PRAGMA table_info` + `ALTER TABLE` migration, `%s`→`?`) on call 8 and the route on
call 9, 70 seconds in. The assisted run did the identical thing on the identical schedule. Every
one of the remaining 104 calls was cria.

### 1. A satisfied step stayed pinned — `Loop._research_check` (cria/loop.py:2805)

The reading step ("read app.py and db.py") is only tested for satisfaction every
`RESEARCH_CHECK_EVERY` = 10 acting turns. Its evidence — `research.sources_read()` over the message
list — is deterministic, free, and was complete at coder call 4. The step nevertheless stayed pinned
as the LAST user turn for seven consecutive turns, telling a weak model to restart at "read and
plan" after every piece of finished work.

Result: four byte-identical `db.py` writes, two byte-identical `app.py` writes. Those tripped
cria's own repetition and flail detectors, which fired six reasoner interventions, which produced
the rabbit hole. **A cadence was gating a fact instead of a judgement.**

Fix: clear the step on evidence after every coder turn; keep the cadence only for the reasoner CALL,
and short-circuit before it when the named sources are already read. A step must never be
re-appended as the final user turn once its evidence exists.

### 2. The route was made unreachable by a steer — call 0087

Not reverted, not a verifier blind spot: written correctly, then killed. The steer changed
`db.get_customer_orders(m.group(1))` to `...(m.group(1), path=self.db_path)` and added
`db_path = None`. `db_path` is set only by `_run_server`, a helper in the model's OWN test file.
`serve()` — the real entry point, fifteen lines below, byte-identical to the seed — never sets it.
Every request became `sqlite3.connect(None)`. The code is present, correct, and unreachable.

Root: `cria/prompts/steer_diagnose.txt:13` budgets the author "exactly ONE concrete next action"
and points it at the caller that failed. Nothing requires it to repair a defect at every place the
value is SET.

Fix: a rule beside the existing mismatch rule (line 26) — if a directive changes how a value reaches
code, account for every place that value is set, the failing caller AND the module entry point.
One change to one mechanism is still one action, so the budget holds.

### 3. The judge's own thinking is erased between rounds — `_judge_completion` (cria/loop.py:791, 807)

The shared inspection loop behind the step critic, completion critic, confirm brake, exec-intent
judge and steer author rebuilds the judge's conversation between rounds from `content` and
`tool_calls` only. For a thinking model calling a tool — `content` empty, analysis in
`reasoning_content` — the turn written back is `{"content": None, "tool_calls": [...]}`. By the
final tools-withdrawn "answer now" round, the judge is looking at a transcript in which it appears
to have said nothing.

This is the 42%-empty measurement's real mechanism, and the cost is exact: **at call 0081 the steer
author spent 28,777 characters and reached the correct root cause — that the database functions
capture the path in a default argument, so setting it later has no effect — and cria discarded it.**
Found it, then lost it.

`massage.coerce_text_answer` already applies the right rule and is wired into the summarizer and the
proxy route. It is wired into none of the five judge paths.

Fix: one pure reader (`massage.turn_text`) beside `content_text`/`coerce_text_answer`, used at both
write-back sites so the judge's transcript preserves what it actually produced.


## cart-billing-go_gemma4_codex_poff_1786408722

**CRIA 80% vs BASE 100% — cria fault: NO, task fault: YES**

The campaign's second negative delta, and it is not cria making a model worse. It is an
underspecified task, and I wrote the ambiguity in twice.

**What happened.** gemma4 changed `Subtotal()` to return `decimal.Decimal` — a reasonable
consequence of "use whatever the ecosystem standardises on for decimal money". The seeded
`TestSubtotal` compares against a float literal, so it stopped compiling. cria's steer author, at
call 0022, told it:

> The compilation error in `cart_test.go` occurs because `Subtotal()` now returns a
> `decimal.Decimal`, but your test case is trying to compare it against a float literal. Update all
> assertions in `cart_test.go`...

It did, keeping the same asserted value (`decimal.NewFromFloat(15.00)` for `15.00`), and the
seeded-test integrity check flagged it. −20 points.

**Two faults, one mine and one arguable.**

1. **The Go prompt never forbids changing the tests.** Its Ruby sibling says "Don't change what the
   tests assert; they describe the behaviour our customers were promised." The Go prompt says no
   such thing, and the verifier enforces it anyway. A model is being penalised for something it was
   never told not to do — the fifth instrument fault of this exact class today.
2. **My earlier fix half-closed the ambiguity.** After ternary-bonsai changed `Item.Price`, I added
   "Keep the `Item` struct's field types as they are". That covered the struct and said nothing
   about the return types of `Subtotal()` and `Total()`, so the same conflict reappeared one level
   out. The boundary should have been the public API, not one struct.
3. **cria chose to bend the test rather than the API.** Given a compile error caused by a changed
   public signature, "update the callers" and "revert the signature" are both valid, and the steer
   considered only the first. That is defensible on the information it had — nothing in the prompt
   marks the seeded tests as sacred — but it is worth recording as a pattern: cria resolves an
   API/consumer conflict by changing the consumer.

**Action, deliberately deferred.** The prompt fix is to constrain the boundary to the public API and
add the sibling's "don't change what the tests assert". That invalidates every Go row in BOTH arms,
so it waits for the campaign to close rather than landing mid-arm and giving the remaining CRIA
cells a different task from their BASE twins. Recorded here so this −20 is not read as evidence
about cria, which it is not.


## orders-api-py_qwen35_codex_poff_1786414444

**CRIA 25% vs BASE 50% — cria fault: YES**

The first assisted-arm regression with a real cria cause. The baseline had the status column; the
assisted run does not, and cria told it to remove it.

**Call 0042:**

> The tests are failing because `db.py:62` has a migration that's trying to add a `status` column
> to a table that already exists — but **the schema already defines `status` as a column. The
> migration function itself is broken.** … Fix the migration logic so it checks for column
> existence before adding, or **removes the redundant column-addition**.

**Call 0051, nine turns later:**

> The repo check shows `orders/db.py:62: sqlite3.OperationalError: **table orders has no column
> named status**` — this is the root cause.

One says the column exists and the addition is redundant. The other says the column does not exist.
Both were delivered to the coder as fact, in cria's own voice, about the same line.

**The false fact is 0042's, and the error is specific and generalisable.** `SCHEMA` defines `status`
for tables created fresh; the migration adds it to tables that already exist. Both are required, and
the second IS the deliverable — "orders should carry a status, and existing databases must be
migrated". The steer author read one definition site, found `status` there, and concluded the other
was redundant. It never distinguished the new-table path from the existing-table path, which is the
only distinction that matters in a migration.

The coder followed the directive, the column-addition went, and `schema_migrated` flipped from ok to
MISS along with the route. 50% became 25%, at 146 calls against 76 and 37 minutes against 20.

**Candidate rule, NOT built:** a directive must not call code redundant on the strength of one
definition site when the failing path is a different one. That is adjacent to the value-is-set rule
already added from the ternary walk, and it is n=1 again — recorded here, and deliberately not
turned into a second prompt rule off a single incident.

Fix deferred: no cria change lands mid-arm. This is the first entry in the assisted arm's own
fix list.


## cart-billing-go_qwen35_codex_poff_1786413785

**CRIA 80% vs BASE 100% — cria fault: NO, task fault: YES. Same defect as gemma4's Go pair.**

Identical diff, independently produced: `Subtotal()` returns `decimal.Decimal`, so the seeded
test's float comparison becomes `decimal.NewFromFloat(15.00)` / `got.Equal(want)` — same asserted
value, different type — and the integrity check flags it.

Two models converging on the same change to the same line is the task asking for it. The full
diagnosis and the deferred fix are in the gemma4 entry above; nothing in this run adds to it, and
the −20 is an instrument artifact in both rows.


## orders-api-py_ternary-bonsai_codex_poff_1786424418

**CRIA 0% vs BASE 25% — cria fault: PARTIAL, and it is the second sighting of one pattern.**

Every check reads `service did not start`. The cause is one deletion: the assisted run's
`orders/app.py` **has no `if __name__ == "__main__":` block**. Its BASE twin does. The file ends
with a new `serve_once(port, path)` helper — "start the server and handle exactly one request",
written to make `test_http.py` work — and the program's own entry point is gone. `python3 -m
orders.app` now imports the module, defines two functions and exits 0.

The parameterised query is present and correct in both runs. `sql_injection_fixed` did not regress
because the SQL changed; it regressed because nothing answers.

**cria did not order the deletion.** Its steers at 0027, 0046 and 0052 were all about
`test_http.py` — the server thread, the readiness loop, a duplicated `db.init`. The model
restructured `app.py` to serve those and took `__main__` with it.

**But this is the second time in one campaign that the production entry point became collateral
damage while cria helped with tests.** The first was this morning's walk on the same task: a steer
routed the working route through `self.db_path`, set only by `_run_server` in the model's own test
file, never by `serve()`. Different model, different mechanism, identical outcome — the code is
right, the tests are the only thing that can reach it, and the deliverable scores zero.

**The actionable gap is cria's, and it is on the observable side.** cria runs the repo's checks
before letting a session end. It does not run the program. Whether the documented entry point still
starts is deterministic ground truth — the same category as a compile error, which this campaign
showed is worth +100 to a model that cannot compile. A smoke probe that starts the thing the README
says to start, and says so when it stops working, would have caught both of these.

n=2, two models, two mechanisms, one campaign. That clears the bar the value-is-set rule did not.
Recorded as the campaign's primary fix candidate; not built here, because the closing summary is
owed first and no cria change should land on the strength of an unreviewed conclusion.


## feed-pipeline-java_qwen35_codex_poff_1786416866

**CRIA 0% vs BASE 40% — cria fault: NO individually, YES in aggregate.**

The assisted run does not compile, on one symbol: `AtomicInteger`. The file imports
`java.util.concurrent.*`, which does not cover `java.util.concurrent.atomic`. A one-line fix, and
the model never made it in 106 calls.

No steer is wrong. Call 0105 says exactly the right thing — "Read the actual compilation errors
from `target/compile.log` … before rewriting code again". cria diagnosed it correctly and pointed
at it.

What cria contributed is the rope. The BASE run compiled and scored 40% in 5.5 minutes on 69 calls.
Under the assists the same model grew the file from 241 lines to 281, broke the build on a subtle
package boundary, and was killed at the 15-minute milestone still broken. **Persistence gave a
churning model more room to churn**, which is the effect this campaign's summary names.

Contrast worth keeping: ternary-bonsai took the same class of signal — a compile error — from 0% to
100% on Rust. The signal being available is not sufficient; the model still has to act on it.

## handles-cli-node_qwen35_codex_poff_1786417858

**CRIA 50% vs BASE 75% — cria fault: YES. A false fact about the task itself.**

The lost check is `request_removed`, and it reproduces on the preserved workspace: the assisted
solution does `require('undici')` and will not run without `node_modules`. Its BASE twin uses
built-in fetch and runs clean.

The prompt says: *"Move it to the built-in fetch that ships with modern Node, and **drop the
dependency entirely**."*

**Call 0155, cria's reasoner:**

> The coder is now trying to remove the undici dependency from package.json, but **this isn't
> required by the task** and may even be necessary for the tool to work

It is required by the task, in those words. The model was already doing the right thing and cria
talked it out of it. Doctrine 5b — cria stated a false fact about the world, and the ground truth
was the task text sitting in its own prompt.

Then the completion judge ratified it. **Call 0163:**

> Move from deprecated `request` package to built-in fetch — ✓ (uses undici's fetch)

`undici` is a third-party package; "built-in" is the entire point of the deliverable. Two separate
cria judgements, the same wrong belief, and the second one closed the session on it.
