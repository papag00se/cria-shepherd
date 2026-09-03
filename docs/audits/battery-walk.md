
## orders-api-py_ternary-bonsai_codex_poff_1786367926

**cria fault: yes** — three defects, one run. **All three fixed 2026-08-10** (`d7e7cf3`, `78a0be4`, `e94a5f1`), each with a test that fails before and passes after; full suite 2,914. They live in the coaching path, so no baseline row is affected and none needed superseding. BASE 3/4 in 31 calls / 7.8 min → CRIA 2/4 in 113 calls / 60.1 min. Walked call-by-call, 25 agents, every call read in order; 69 candidate incidents raised, 8 refuted on adversarial re-check.

**The model solved it in 70 seconds. Both times.** The baseline wrote the full `db.py` (status column, index, `PRAGMA table_info` + `ALTER TABLE` migration, `%s`→`?`) on call 8 and the route on call 9, 70 seconds in. The assisted run did the identical thing on the identical schedule. Every one of the remaining 104 calls was cria.

### 1. A satisfied step stayed pinned — `Loop._research_check` (cria/loop.py:2805)

The reading step ("read app.py and db.py") is only tested for satisfaction every `RESEARCH_CHECK_EVERY` = 10 acting turns. Its evidence — `research.sources_read()` over the message list — is deterministic, free, and was complete at coder call 4. The step nevertheless stayed pinned as the LAST user turn for seven consecutive turns, telling a weak model to restart at "read and plan" after every piece of finished work.

Result: four byte-identical `db.py` writes, two byte-identical `app.py` writes. Those tripped cria's own repetition and flail detectors, which fired six reasoner interventions, which produced the rabbit hole. **A cadence was gating a fact instead of a judgement.**

Fix: clear the step on evidence after every coder turn; keep the cadence only for the reasoner CALL, and short-circuit before it when the named sources are already read. A step must never be re-appended as the final user turn once its evidence exists.

### 2. The route was made unreachable by a steer — call 0087

Not reverted, not a verifier blind spot: written correctly, then killed. The steer changed `db.get_customer_orders(m.group(1))` to `...(m.group(1), path=self.db_path)` and added `db_path = None`. `db_path` is set only by `_run_server`, a helper in the model's OWN test file. `serve()` — the real entry point, fifteen lines below, byte-identical to the seed — never sets it. Every request became `sqlite3.connect(None)`. The code is present, correct, and unreachable.

Root: `cria/prompts/steer_diagnose.txt:13` budgets the author "exactly ONE concrete next action" and points it at the caller that failed. Nothing requires it to repair a defect at every place the value is SET.

Fix: a rule beside the existing mismatch rule (line 26) — if a directive changes how a value reaches code, account for every place that value is set, the failing caller AND the module entry point. One change to one mechanism is still one action, so the budget holds.

### 3. The judge's own thinking is erased between rounds — `_judge_completion` (cria/loop.py:791, 807)

The shared inspection loop behind the step critic, completion critic, confirm brake, exec-intent judge and steer author rebuilds the judge's conversation between rounds from `content` and `tool_calls` only. For a thinking model calling a tool — `content` empty, analysis in `reasoning_content` — the turn written back is `{"content": None, "tool_calls": [...]}`. By the final tools-withdrawn "answer now" round, the judge is looking at a transcript in which it appears to have said nothing.

This is the 42%-empty measurement's real mechanism, and the cost is exact: **at call 0081 the steer author spent 28,777 characters and reached the correct root cause — that the database functions capture the path in a default argument, so setting it later has no effect — and cria discarded it.** Found it, then lost it.

`massage.coerce_text_answer` already applies the right rule and is wired into the summarizer and the proxy route. It is wired into none of the five judge paths.

Fix: one pure reader (`massage.turn_text`) beside `content_text`/`coerce_text_answer`, used at both write-back sites so the judge's transcript preserves what it actually produced.


## cart-billing-go_gemma4_codex_poff_1786408722

**CRIA 80% vs BASE 100% — cria fault: NO, task fault: YES**

The campaign's second negative delta, and it is not cria making a model worse. It is an underspecified task, and I wrote the ambiguity in twice.

**What happened.** gemma4 changed `Subtotal()` to return `decimal.Decimal` — a reasonable consequence of "use whatever the ecosystem standardises on for decimal money". The seeded `TestSubtotal` compares against a float literal, so it stopped compiling. cria's steer author, at call 0022, told it:

> The compilation error in `cart_test.go` occurs because `Subtotal()` now returns a `decimal.Decimal`, but your test case is trying to compare it against a float literal. Update all assertions in `cart_test.go`...

It did, keeping the same asserted value (`decimal.NewFromFloat(15.00)` for `15.00`), and the seeded-test integrity check flagged it. −20 points.

**Two faults, one mine and one arguable.**

1. **The Go prompt never forbids changing the tests.** Its Ruby sibling says "Don't change what the tests assert; they describe the behaviour our customers were promised." The Go prompt says no such thing, and the verifier enforces it anyway. A model is being penalised for something it was never told not to do — the fifth instrument fault of this exact class today.
2. **My earlier fix half-closed the ambiguity.** After ternary-bonsai changed `Item.Price`, I added "Keep the `Item` struct's field types as they are". That covered the struct and said nothing about the return types of `Subtotal()` and `Total()`, so the same conflict reappeared one level out. The boundary should have been the public API, not one struct.
3. **cria chose to bend the test rather than the API.** Given a compile error caused by a changed public signature, "update the callers" and "revert the signature" are both valid, and the steer considered only the first. That is defensible on the information it had — nothing in the prompt marks the seeded tests as sacred — but it is worth recording as a pattern: cria resolves an API/consumer conflict by changing the consumer.

**Action, deliberately deferred.** The prompt fix is to constrain the boundary to the public API and add the sibling's "don't change what the tests assert". That invalidates every Go row in BOTH arms, so it waits for the campaign to close rather than landing mid-arm and giving the remaining CRIA cells a different task from their BASE twins. Recorded here so this −20 is not read as evidence about cria, which it is not.


## orders-api-py_qwen35_codex_poff_1786414444

**CRIA 25% vs BASE 50% — cria fault: YES**

The first assisted-arm regression with a real cria cause. The baseline had the status column; the assisted run does not, and cria told it to remove it.

**Call 0042:**

> The tests are failing because `db.py:62` has a migration that's trying to add a `status` column to a table that already exists — but **the schema already defines `status` as a column. The migration function itself is broken.** … Fix the migration logic so it checks for column existence before adding, or **removes the redundant column-addition**.

**Call 0051, nine turns later:**

> The repo check shows `orders/db.py:62: sqlite3.OperationalError: **table orders has no column named status**` — this is the root cause.

One says the column exists and the addition is redundant. The other says the column does not exist. Both were delivered to the coder as fact, in cria's own voice, about the same line.

**The false fact is 0042's, and the error is specific and generalisable.** `SCHEMA` defines `status` for tables created fresh; the migration adds it to tables that already exist. Both are required, and the second IS the deliverable — "orders should carry a status, and existing databases must be migrated". The steer author read one definition site, found `status` there, and concluded the other was redundant. It never distinguished the new-table path from the existing-table path, which is the only distinction that matters in a migration.

The coder followed the directive, the column-addition went, and `schema_migrated` flipped from ok to MISS along with the route. 50% became 25%, at 146 calls against 76 and 37 minutes against 20.

**Candidate rule, NOT built:** a directive must not call code redundant on the strength of one definition site when the failing path is a different one. That is adjacent to the value-is-set rule already added from the ternary walk, and it is n=1 again — recorded here, and deliberately not turned into a second prompt rule off a single incident.

Fix deferred: no cria change lands mid-arm. This is the first entry in the assisted arm's own fix list.


## cart-billing-go_qwen35_codex_poff_1786413785

**CRIA 80% vs BASE 100% — cria fault: NO, task fault: YES. Same defect as gemma4's Go pair.**

Identical diff, independently produced: `Subtotal()` returns `decimal.Decimal`, so the seeded test's float comparison becomes `decimal.NewFromFloat(15.00)` / `got.Equal(want)` — same asserted value, different type — and the integrity check flags it.

Two models converging on the same change to the same line is the task asking for it. The full diagnosis and the deferred fix are in the gemma4 entry above; nothing in this run adds to it, and the −20 is an instrument artifact in both rows.


## orders-api-py_ternary-bonsai_codex_poff_1786424418

**CRIA 0% vs BASE 25% — cria fault: PARTIAL, and it is the second sighting of one pattern.**

Every check reads `service did not start`. The cause is one deletion: the assisted run's `orders/app.py` **has no `if __name__ == "__main__":` block**. Its BASE twin does. The file ends with a new `serve_once(port, path)` helper — "start the server and handle exactly one request", written to make `test_http.py` work — and the program's own entry point is gone. `python3 -m orders.app` now imports the module, defines two functions and exits 0.

The parameterised query is present and correct in both runs. `sql_injection_fixed` did not regress because the SQL changed; it regressed because nothing answers.

**cria did not order the deletion.** Its steers at 0027, 0046 and 0052 were all about `test_http.py` — the server thread, the readiness loop, a duplicated `db.init`. The model restructured `app.py` to serve those and took `__main__` with it.

**But this is the second time in one campaign that the production entry point became collateral damage while cria helped with tests.** The first was this morning's walk on the same task: a steer routed the working route through `self.db_path`, set only by `_run_server` in the model's own test file, never by `serve()`. Different model, different mechanism, identical outcome — the code is right, the tests are the only thing that can reach it, and the deliverable scores zero.

**The actionable gap is cria's, and it is on the observable side.** cria runs the repo's checks before letting a session end. It does not run the program. Whether the documented entry point still starts is deterministic ground truth — the same category as a compile error, which this campaign showed is worth +100 to a model that cannot compile. A smoke probe that starts the thing the README says to start, and says so when it stops working, would have caught both of these.

n=2, two models, two mechanisms, one campaign. That clears the bar the value-is-set rule did not. Recorded as the campaign's primary fix candidate; not built here, because the closing summary is owed first and no cria change should land on the strength of an unreviewed conclusion.


## feed-pipeline-java_qwen35_codex_poff_1786416866

**CRIA 0% vs BASE 40% — cria fault: NO individually, YES in aggregate.**

The assisted run does not compile, on one symbol: `AtomicInteger`. The file imports `java.util.concurrent.*`, which does not cover `java.util.concurrent.atomic`. A one-line fix, and the model never made it in 106 calls.

No steer is wrong. Call 0105 says exactly the right thing — "Read the actual compilation errors from `target/compile.log` … before rewriting code again". cria diagnosed it correctly and pointed at it.

What cria contributed is the rope. The BASE run compiled and scored 40% in 5.5 minutes on 69 calls. Under the assists the same model grew the file from 241 lines to 281, broke the build on a subtle package boundary, and was killed at the 15-minute milestone still broken. **Persistence gave a churning model more room to churn**, which is the effect this campaign's summary names.

Contrast worth keeping: ternary-bonsai took the same class of signal — a compile error — from 0% to 100% on Rust. The signal being available is not sufficient; the model still has to act on it.

## handles-cli-node_qwen35_codex_poff_1786417858

**CRIA 50% vs BASE 75% — cria fault: YES. A false fact about the task itself.**

The lost check is `request_removed`, and it reproduces on the preserved workspace: the assisted solution does `require('undici')` and will not run without `node_modules`. Its BASE twin uses built-in fetch and runs clean.

The prompt says: *"Move it to the built-in fetch that ships with modern Node, and **drop the dependency entirely**."*

**Call 0155, cria's reasoner:**

> The coder is now trying to remove the undici dependency from package.json, but **this isn't required by the task** and may even be necessary for the tool to work

It is required by the task, in those words. The model was already doing the right thing and cria talked it out of it. Doctrine 5b — cria stated a false fact about the world, and the ground truth was the task text sitting in its own prompt.

Then the completion judge ratified it. **Call 0163:**

> Move from deprecated `request` package to built-in fetch — ✓ (uses undici's fetch)

`undici` is a third-party package; "built-in" is the entire point of the deliverable. Two separate cria judgements, the same wrong belief, and the second one closed the session on it.


## Method note — "model own fault" is the bucket to distrust (operator, 2026-08-11)

The 24-pair walk classified incidents into kinds, and the largest single bucket after good-assist was `model-own-fault`: 130 of the first 620. The operator's correction: **that label is usually traceable to something in the context — ambiguous language, or anything that could sway a weak model the wrong way.**

Measured against the walk's own text before any re-reading: **80 of those 130 mention cria machinery inside the incident description that filed them as the model's fault.** 88 sit in the assists-ON arm, where cria's context exists at all; the other 42 are in the control arm, where the only context is the task prompt and the harness — so a model-own-fault there is a TASK-DESIGN finding, not an absolution.

The clearest single misfiling, and the reason this is a method problem rather than a bookkeeping one:

> `[satisfaction-confirm 0034]` The confirm checker guessed a Maven-conventional package path that does not exist in this project (`com/example/importer`) instead of the pipeline package the tree actually has … **"no cria injection prompted the wrong guess."**

The confirm checker IS cria. It hallucinated a Java layout convention rather than reading the directory, and because it emitted no *injection* the walker recorded it as the model's mistake. That is both a cria fault and a language-convention bias, filed under neither.

**The rule this produces, for every walk from here:** a wrong turn is attributed to the model only after reading what the model was looking at when it turned. The categories to exhaust first are cria's own JUDGES (which act without injecting), cria's injections, cria's tool and denial surface, and the task prompt's own wording — a prompt that says "report the holder address" invites a weak model to invent a field literally named `holder_address`, and that is the prompt's doing, not the model's. `genuinely-model` is the verdict of last resort. It is real, and it must not be inflated away, but it is reached last.

This is principle 16 (assume cria caused it until proven otherwise) applied to the CLASSIFICATION step rather than only to the investigation step — the place it was quietly being skipped.

## cart-billing-go_nemotron-elastic_codex_poff_1788230301

L5, HEAD 734226b, milestone-15, force-stopped at the 30-min gate (judged 1/floor 2). Strict 1/5, usefulness 31. Walked full via `suite/walk.py` (14 chunks), 18-agent fan-out, every claim re-verified against the chunks.

**Genuinely-model, reached last (method note applied).** The run never built. Across 51 calls the model invented Go decimal dependencies IN ITS OWN reasoning and tool calls — `go get github.com/arvidsson/decimal` (call 0009 tool result: `repository not found`), then `--- THINK ---` at 0009 ruminated "arvidsson/decimal … maybe not published" ~10× verbatim; later `shopspring/decimal` pinned to a nonexistent `0.1.0` (no `v`), then a malformed `require` with no version at all; and an invented decimal API (`FromFloat64`, `QuantizeOptions`, `RoundingHalfUp`) mixing `float64` with `decimal.Decimal`. cria's system prompt (call 0001) says in words *"DO NOT GUESS URLs, FORMATS, OR OBJECT STRUCTURE … READ its real source/docs before writing code against it"*; the model guessed anyway.

**Subagent over-attributions FALSIFIED on re-read.** Five slices filed the invented module/version as a cria injection; every one was the model's own `--- THINK ---`/`--- TOOL CALL ---` rendered inline by walk.py, not a `⟦ctx:…⟧` block. The `⟦ctx:checks⟧` staleness flagged in calls 0042/0044 is LABELLED — `"These checks ran BEFORE your edit to \`go.mod\` … re-run them before concluding anything"` — #5b-compliant; the model ignored the label. `loop.output_loop` (0043) and the duplicate-read blocker (0023) fired correctly.

**cria contribution: none confirmed in this cell.** Injected context was grounded and labelled throughout; the failure is capability + instability.

## feed-pipeline-java_nemotron-elastic_codex_poff_1788232218

L5, HEAD 734226b, milestone-15, force-stopped at the 30-min gate (judged 0/floor 2). Strict 0/5, usefulness 24. Walked full via `suite/walk.py` (51 chunks), 18-agent fan-out, every claim re-verified.

**Genuinely-model, reached last.** The model wrote a real 210-line rewrite (workers on, `ConcurrentHashMap` skip-reason counting, blank-qty handling) and a substantive 498-word REVIEW.md — but never compiled. It had the CORRECT coordinate `com.opencsv`/`5.9` in `pom.xml` at calls 0013 and 0021, then REGRESSED to `org.opencsv` and shipped it. Decisively, cria's `⟦ctx:facts⟧` (calls 0060+) surfaced the ground truth with a trust-label: *"PAGES YOU HAVE ALREADY FETCHED — these SUCCEEDED … `com/opencsv/opencsv/5.9/…pom → HTTP 200`"* and *"THESE FETCHES FAILED … `org/opencsv/…5.9.3.jar → HTTP 404`"*. The model shipped `org.opencsv` regardless. It also mixed opencsv and commons-csv APIs (`CSVRecord` is commons-csv) and declared an invalid `commons-csv:1.8.0`.

**THE ONE CONFIRMED cria CONTRIBUTION — a steer re-blessing a checks-rejected Maven coordinate (call 0040).** `⟦ctx:steer⟧ Add the OpenCSV dependency (groupId org.opencsv, artifactId opencsv, version 5.9.3) … so the symbols com.opencsv.CSVException … become visible` — injected in the SAME prompt whose `⟦ctx:checks⟧` reads `[ERROR] Could not find artifact org.opencsv:opencsv:jar:5.9.3 in central`. The steer is internally inconsistent (groupId `org.opencsv`, symbols `com.opencsv`), the tell of an unverified echo: the model introduced `org.opencsv:5.9.3` itself at calls 0034–0038, and cria's reasoner (0039) repeated it back as an instruction. `_prescribes_what_the_checks_reject` did not fire because a Maven coordinate `org.opencsv:opencsv:5.9.3` is not tokenised against the checker's `Could not find artifact org.opencsv:opencsv:jar:5.9.3`, and the QUOTES-exemption treats it as the coder's own line. Effect: cria re-authored, with its authority, a coordinate its own checks had just rejected (#2/#5b). Not the sole cause — cria's later `⟦ctx:facts⟧` corrected it and the model ignored the correction — but a real guard gap, same class as the 824dd3a invented-code and CSVParser-constructor cases, one claim-type over (dependency coordinate, not code span).

**Candidate fix (needs a prevalence census first, #15):** extend `_prescribes_what_the_checks_reject` (or `_invented_version`) to refuse a steer that names a dependency coordinate the current checks report as `Could not find artifact G:A:V` / `was not found`. Do NOT special-case Maven — key it on the checker's own "not found artifact/module/package" shape across ecosystems (#20). Measure how often steers echo a checks-rejected coordinate before building.

**Subagent over-attributions FALSIFIED.** The guessed `opencsv 5.9.0` URL lives ONLY in cria's search-judge sub-call (call 0046 THINK/SAY) — cria's prompt to that judge explicitly forbids recommending a failed/version-bumped URL; the weak model (driving the judge role) ignored it, and cria did NOT propagate it: `5.9.0` never enters any coder-facing `⟦ctx:…⟧`. `⟦ctx:steer⟧ The repo's automated checks could NOT be run here` (call 0013) is honest gate-offline reporting, not a false claim the coder can't exec. Stale `⟦ctx:checks⟧` is labelled "ran BEFORE your edit". The malformed `</think><tool_call>` replay (call 0017) is the model emitting fused tool-call syntax, a #24 wire-hygiene question at most, not a cria false fact.

## cart-billing-go_nemotron-elastic_codex_poff_1788241229

L5, f07f1df (walk-2 fixes LIVE), milestone-15, force-stopped @30min (judged 1). strict 1/5, usefulness 32. Walked full via `suite/walk.py` (40 chunks, 123 calls), 10-agent `pi/claude-fable-5` fan-out, load-bearing claims re-verified against the chunks.

**Origin genuinely-model.** `v0.5.0` invented at call 0002 THINK **before any shell ran** (no refusal existed to launder); `arndt/decimal` at 0009; the seeded-test rewrite intent is model-authored at 0009 — no cria text suggested it. The model re-pinned refused modules ≥8× after verbatim `unknown revision`/`repository not found` lines.

**W3 — compaction destroys the refusals, then a judge re-blesses (VERIFIED).** Call 0095 the compactor emitted a condensate with zero actions/errors — every `unknown revision v0.5.0` / `Repository not found` gone; call 0096 the satisfaction seat then ruled "No further modifications are needed" over the refused `v0.5.0` pin. The re-bless is not a judge ignoring evidence — the evidence had been folded away. This is why a resolver-refusal ledger must PERSIST across compaction (the fetch ledger already does).

**Corrected over-attributions (walkers wrong; I checked the chunks).** (a) Reasoner 0089's SAY recommends `go get github.com/shopspring/decimal` — a VALID recovery, not a re-bless of `v0.5.0`; the go re-bless is the satisfaction seat (0062/0096), not 0089. (b) The one ORIGINAL stale-note sighting a walker called "false, reset by a refused edit" is unconfirmed: `_paths_written_after` gates on `selfcompact.write_landed`, so a refused edit cannot set `changed_paths`.

**W4 — suite path leak (infra, VERIFIED).** `RUNS_DIR` lives inside the repo, so every workspace path the model reads contains `cria-shepherd`; at call 0061 the model minted module `github.com/jesse/creashepherd` from it. Brushes #17 from the SUITE side, not the shim.

**Fix-audit (walk-2).** F1 spill: 0 sightings (not exercised — the reference doc wasn't oversize-spilled this run). F2 stale-note: truthful variant rendered ~20× and was USED (model re-ran `mvn`/`go build`); no confirmed false original. F3 vouching: 0 sightings on the GO run. **cria assists otherwise held**: rumination cut, [OUTPUT LOOP] (told it to fetch the real API — it declined), repeat-blocker, and the completion gate refused every false `task_complete`.

**W5 — instrument (VERIFIED, no score impact this run).** The 0071 "rewrite" preserved every seeded test and appended `TestTotalRoundingBug`, but reindented tabs→spaces; `_seedtests._norm` `.rstrip()`s and drops blanks/comments but does NOT normalize LEADING indentation, so `unchanged` flunks a pure reformat (#25). Build failed anyway, so nothing scored on it.

## feed-pipeline-java_nemotron-elastic_codex_poff_1788243086

L5, f07f1df, milestone-15, force-stopped @30min (judged 1). strict 1/5, usefulness 34. Walked full via `suite/walk.py` (64 chunks, 132 calls), 16-agent fan-out, verified.

**Origin genuinely-model.** `5.9.3` and `com.opencsv.CSVParseException` invented in THINK pre-resolver (0006/0007); the model held the CORRECT `com.opencsv`/`5.12.0` coordinates all run (no groupId regression this time) and was felled by a one-letter package hallucination (`com.opencsv.exception` — real is `exceptions`) and the invented exception class it flip-flopped for ~130 calls, never once listing the downloaded jar. REVIEW.md (14 located findings) came from the model alone, seeded by the task's own "file name and line number" demand — several line numbers fabricated (three `main`s at 218/233/248 in a ~180-line file). Run-to-run variance, not a fix effect.

**W1 — false vouch over LOCATED compile findings (VERIFIED, 6 slices).** `⟦ctx:checks⟧ GROUND TRUTH — the checks that ran do NOT report a problem with: com.opencsv.exception.CSVParseException, OpenCSV, com.opencsv.CSVParseException … Do not rewrite working code` (chunk40:349 and re-rendered at 0076/0084/0102/0109/0122/0132) — rendered directly ABOVE javac's `package com.opencsv.exception does not exist` / `symbol: class CSVParseException` on the same symbols. A #5b false fact telling the coder the broken import is working code. Mechanism: `_briefing_denies_working_symbols` extracts the dotted FQN whole (`com.opencsv.CSVParseException`), which never appears as one substring in javac's split `symbol:`/`location:` rendering, so `t not in findings` is True and the symbol is vouched. My walk-2 F3 fix (unlocated-abstention) doesn't engage — these are LOCATED findings.

**W2 — steer/reasoner re-blesses a compiler-refused symbol, coder-facing (VERIFIED, HEAD-current).** Reasoner 0071 → `⟦ctx:steer⟧` 0073, and again 0110/0111: "replace `import com.opencsv.CSVParseException;` with `import com.opencsv.exception.CSVParseException;`" — the exact package javac refused ≥3× in the seat's OWN prompt. `_prescribes_what_the_checks_reject` IS wired in but its trigger `_shared_symbols` runs `CSVParseException` through `_NAMES_A_FAILURE`, which strips `*Exception`/`*Error` names on the theory "a checker REPORTS an exception, never REJECTS it" — false when javac says `cannot find symbol: class CSVParseException`. So the trigger is filtered before the reasoner is ever asked, same blind spot as W1. NOT a mechanical DICTATES bypass: 0048 ruled DICTATES, but `_invented_code_spans` exempted the directive because the coder itself had typed BOTH wrong variants, so neither read as "invented" (the QUOTES-exemption).

**Fix-audit.** F1 spill: 1 sighting, no denial (pass). F2 stale-note: both variants sighted, claims TRUE where rendered, model heeded them. F3: the W1 regression class above. Compactor overload recurred (0060/0061 `finish: length`), but the coder rollup was checks-only so the poison didn't reach it — verify that fail-safe is deliberate.

## Vouch-rework (P1) — measured, then resolved NO-CHANGE (2026-09-02)

Walk-3 judged P1 (the split-FQN leaf-match on the working-symbols vouch) a B-fix — a second patch
(after F3) on a mechanism whose root is lexical containment doing a semantic job (#8). Two candidate
A-fixes were drafted: R (reasoner-gate it) and X (remove it), decision deferred to a census.

The census over all `~/.cria/calls` found the vouch had fired 3 times ever, false 3/3, correct 0 —
and concluded REMOVE. But every one of those 3 was a PRE-P1 capture (the split-FQN CsvParser case):
the census measured the bug, not the fix. Then the live nemotron re-run #4 (f07f1df, feed-pipeline-
java call 0038) produced the FIRST correct vouch, verified in full: the briefing called `CsvParser`,
`CsvParserBuilder` AND `skipRow` broken; the checks flag the CsvParser classes but are silent on
`skipRow`; P1 WITHHELD the CsvParser classes (leaf in checks) and vouched ONLY `skipRow` (leaf
absent) — correct discrimination on a mixed set.

So P1 did not make the vouch inert (the census's assumption); it made it DISCRIMINATE. Both R and X
are withdrawn — removing it would delete a now-working assist; reasoner-gating adds a call the
leaf-match does not need. **Resolution: keep P1, no further change.** Lesson: a census over captures
that all predate a fix measures the defect, not the remedy — live ground truth (#23b) corrected it.
(Full working notes: local docs/audits/2026-09-02-vouch-rework-candidate.md, gitignored scratch.)
