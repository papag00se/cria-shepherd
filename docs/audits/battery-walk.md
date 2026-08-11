
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


## cart-billing-go_gemma4 CRIA 80% vs BASE 100% — cria fault: NO, task fault: YES

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


## orders-api-py_qwen35 CRIA 25% vs BASE 50% — cria fault: YES

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
