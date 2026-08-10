
## orders-api-py_ternary-bonsai_codex_poff_1786367926

**cria fault: yes** — three defects, one run. BASE 3/4 in 31 calls / 7.8 min → CRIA 2/4 in 113
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
