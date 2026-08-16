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

---

## feed-pipeline-java_nemotron-elastic_codex_poff_1786841228

*Agent read all 12 chunks end to end.*

### 1. The cell wrote NOTHING — VERIFIED, and it corrects my own row

```
$ git log --oneline   → 2ae987e seed
$ git status --short  → (clean)
$ wc -c pom.xml       → 980
```

Twenty-two calls, zero bytes written. My cell-16 row said "it compiles now… it just optimised
nothing." What compiles is the **seed**. The 1.0× speed, the 0 threads, the absent REVIEW.md and the
undeclared dependency are all the seed being scored. Second correction of the day from the same
mistake: reading the verifier's detail instead of opening the workspace.

### 2. The rumination guard names a cause its own detector rejected — VERIFIED in code

`rumination.py:170-171`:
```python
dense = hits >= MIN_MARKERS and (hits / max(reasoning_tokens, 1)) * 1000 >= self.rate_per_1k
if reasoning_tokens >= self.budget or dense:
```
`MIN_MARKERS = 6`, `rate_per_1k = 10.0`, budget from `output_reserve = 16384`. The three aborts:

| abort | hits | tokens | markers/1k | needed | `dense` |
|---|---:|---:|---:|---:|---|
| 0013 | 9 | 16,402 | 0.55 | 10.0 | False |
| 0014 | 18 | 16,404 | 1.10 | 10.0 | False |
| 0018 | 5 | 16,424 | 0.30 | 10.0 | False — and 5 < MIN_MARKERS |

Every one fired on **length**. The message the model received says:

> `[RUMINATION GUARD] Your last reasoning pass hit 5 second-guessing phrases … and was aborted`

cria named the density trigger its own detector had just rejected, then issued the instruction that
follows from it — *"Stop re-examining"* — when the behaviour to interrupt was **drafting a whole file
inside the reasoning channel**. Told to stop second-guessing, the model kept drafting and hit the
identical wall twice more. `loop.py:7471-7478`'s own comment states the rule being broken: *"A guard
must not invent the numbers it fired on… cria states the trigger it actually has."* The degenerate arm
was split out and given its own words; the length arm was left borrowing the phrase arm's.
**cria fault: yes.**

### 3. Two of the four aborts destroyed real work — REPORTED, and it is a known failure mode

0010 and 0013 were genuine loops — one sentence ×30, one 2,162-character paragraph ×20 — correctly
killed. 0014 and 0018 were **coherent, monotonically advancing drafts** of `Importer.java` and
`pom.xml`, cut mid-token:

> `        CSVParser<CSVRecord<String>> parser = CSVParser.parse(br);`
> `        List<String> header`  `[finish: rumination]`

`rumination.py:43-47` already records this exact failure from an earlier cycle of this same cell. The
density fix (`f8a5f4c`) repaired the marker arm; **the raw-length backstop is still a hard cap**, which
is what principle 6 forbids — "never cap output for latency… runaways are caught by the streaming
rumination detector, not a short hard cap" — wearing a detector's name.

### 4. REVIEW.md was named 87 times — REFUTED as a visibility failure

It is in every coder prompt: the user task, the `⟦ctx:task⟧` north star, plan step 2 of 2, and the
compaction briefing's Next step. The model raised it in its own reasoning repeatedly. **It was an
ordering failure, not a visibility one** — in all five plans the model authored, the cheapest
deliverable on the board sat last, behind the two hardest, and it never cleared the first.
`cria fault: none.`

### 5. Five write refusals the model could not diagnose — REPORTED

From call 0015 every `write_file` carried a second tool call folded into its `content`. cria refused
correctly — *"this would replace a currently-valid pom.xml with content that does not parse — not
well-formed (invalid token): line 34, column 1"* — and line 34 is exactly where `</function>` begins.
The model spent its remaining effort re-checking XML that was fine.

`writeproxy._collapse_rejected_payload` then redacts the rejected content
(`[1124 characters — this edit was REJECTED …]`), which is right in general and here **deletes the only
evidence of the defect**, leaving a line number pointing into text the model can no longer see.

*Attribution tested, not assumed:* the agent replayed both plausible emission shapes through the
current `massage._xml_args` and both parse cleanly into two calls. So the fold is **not** reproduced by
cria's code as it stands and the junk most likely arrived inside the argument from the runner's own
tool-call parser. `cria fault: not proven for the fold; yes for the refusal being undiagnosable.`

---

## The three cells floored at 15 minutes

*Agent read all 31 chunks across the three runs.*

### The unifying answer

**In all three runs cria put the exact error in front of the model and then, in the same turn or the
next, pointed it somewhere else.**

### `feed-pipeline-java × gemma4` — a steer that contradicts the block above it — REPORTED

One turn, call 0020, carried both:

> `⟦ctx:checks⟧ … [ERROR] …/Importer.java:[92,44] incompatible types: CSVRecord cannot be converted to Map<String,String>`

> `⟦ctx:steer⟧ … the repo's own checks FAILED, but **a specific line could not be parsed** from the output … Run that exact check yourself and read the actual error`

cria says no line could be parsed while displaying the parsed line two blocks above. The stuck-reasoner
that authored it had the checks block **elided** from its transcript (`…[3011 chars elided]`) — the
elision cut out exactly the `Importer.java:[92,44]` line — so it saw only the false claim.
**cria fault: yes**, and the cause is cria eliding evidence from its own judge.

### Both Rust runs — a plan step that never advanced — REPORTED

From call 0003 to the kill, **every** coder turn re-appended `Do ONLY this step (1 of 2): Read
crates.io to identify a published TOML parser crate…`. The research finished at call 0007. The first
critic check on that step did not run until **call 0017 — fourteen coder turns later.**

Consequences, per run:
- **ternary-bonsai:** call 0013's reasoning is the same four paragraphs ×40 (*"I've already done step
  1… The user is now giving me a new instruction that overlaps"*), 149 markers, 16,392 tokens, aborted.
  Then at call 0016, told again to do step 1, it **replayed its opening sequence and re-wrote
  `src/main.rs` with the original broken content**, reverting both fixes it had already landed.
- **nemotron-elastic:** **six of 28 emitted tool calls — 21% — are `web_fetch` of the same page**, plus
  three more refused by the dedup guard.

And the critic that could have closed the step ruled `done: false` on a false premise, twice, because
cria's own elision cut the successful fetch's **call line** off the front of its action log while
leaving the page text behind it:

> `[1,452 characters of EARLIER actions elided …]`

so the page appeared with no call that produced it, and the only visible `$ web_fetch` line was one
marked `[THIS CALL DID NOT RUN — it was refused]`. **cria fault: yes.**

### The DICTATES gate labels but does not block — REPORTED, needs verifying

At call 0024 the reasoner produced the correct and complete fix. The `steer-code` judge at 0025 ruled
`DICTATES` — cria's own verdict that the directive hands the coder code to paste — and the directive
**shipped verbatim anyway** at 0026. Here that was lucky, because the directive was right. It means
the gate is not doing what its prompt says. *Not yet re-verified by me; flagged for the fix phase.*

### The edit-recovery escalation is helping; the context rebuild keeps re-arming it — REPORTED

Every one of the eleven escalations was followed by a `write_file` that landed. The budget is burned by
the three failed edits **before** each escalation, and those recur because
`coder-s1-focus1`/`focus2` and the compaction rebuild re-present the file's **obsolete first draft**
near the top of the conversation — which is exactly the text the model then copies into `old_string`.
A → B → C: *focus-trim re-seeds the stale body → the model copies it → three failed edits → escalation
→ one good write → the next trim re-seeds it.* **The escalation is not the problem; the counter
resetting behind a rebuild that re-supplies the wrong text is.**

### Refuted — the invented crate cost nothing here

At call 0004 the search supervisor recommended `toml2`, reasoning that *"toml2 is the de facto standard
for Rust TOML parsing"*. It does not exist. Because `on_target` was **true**, the recommendation never
reached the coder. **Refuted as a cause in this run** — and it is the same hallucinated-recommendation
path that DID fire on `cart-billing-go × nemotron`, where `on_target` was false.

---

## shipping-rates-rb_qwen35_codex_poff_1786811660

*Agent read chunks 01–07 raw, then folded the 31-file corpus to 504,837 bytes by dropping only lines
byte-identical to lines already read inside a replayed `PROMPT Δ` region, and read that end to end. It
said so.*

### 1. The run-killer, MEASURED — and the fix at A is sufficient on its own

The last coder call asked to read the spilled doc. cria refused it (9,645 B against the 9,000 bound)
**and appended a complete file census to the refusal** — 1,949 entries, 1,942 of them under
`vendor/bundle`.

| the body that 400'd six times | chars | est. tokens |
|---|---:|---:|
| as sent | 263,205 | 65,801 |
| `vendor/bundle` lines only | 168,559 | **42,140 — 64%** |
| **body without them** | 94,646 | **23,661** |

Budget is ≈45,056. **Without the tree cria told the coder to create, the body fits with room to
spare.** So the floor's inability to shrink a single message is real but secondary; the sufficient fix
is upstream.

A → B → C, all cria's: **A** the install denial ordered the gem into the project directory → **B** the
workspace gained ~1,950 dependency files → **C** `workspace_inventory` walks them all, and
`_self_compact` calls it **three times in one compaction**.

**Do not add `vendor` to `BUILD_ARTIFACT_DIRS`** (deliberate — real source in some projects) and **do
not cap the listing** (operator's call — a bounded list weakens "not listed = does not exist"). Fix at
A/B: cria *wrote the install instruction*, so it knows the exact directory it created. Record that
prescribed target on the session and fold that one tree to a line. A `vendor/` a human committed is
still listed.

### 2. `find="in_eu\?"` answered "no match" about a document containing `in_eu?` — VERIFIED by replay

The agent replayed cria's own matcher against the preserved spill file:
```
_find_hits(doc, None, r'in_eu\?') -> False
_find_hits(doc, None, 'in_eu?')   -> True
```
`_find_hits` is a literal substring test. `find_in` re-reads a miss two ways — alternation split and
HTTP-verb strip — neither covering a regex-escaped term. **cria primes the spelling itself**: the spill
message says *"Grep the file for what you need"* and the tool description shows `grep -n "<keyword>"`.
The model wrote the query the way cria told it to and was told the document does not contain the one
method it needed. Same class as the `holder_address|total_handles` incident the module's own comment
records. **cria fault: yes.**

### 3. "It is YAML." about an HTML page — VERIFIED by replay

`_doc_format` returns YAML when any line in the first 200 chars matches `^[A-Za-z_][\w.-]*:(\s|$)`.
The page begins `RubyDoc.info:`. **cria fault: yes** — needs a second signal, or silence (#3).

### 4. cria laundered the coder's own wrong belief into ground-truth voice

Call 0085, the **coder's** reasoning: *"the countries gem uses `Countries` (plural) not `Country`"*.
Call 0087, cria's reasoner, in cria's voice: *"The error messages show Countries (plural module) not
Country (singular)"*. Its own system prompt says *"THE CODER'S OWN WORDS AND THINKING — what it
BELIEVES. Frequently wrong… Never repeat a claim from here as fact."* The real cause was in cria's own
`⟦ctx:checks⟧` block verbatim: `NameError: uninitialized constant Shipping::Country`.

Call 0088, the coder: **"The steer message is right - I need to read the fetched documentation file"**
→ the 9,000-byte gate → the 169 KB census → six 400s → run over. **cria fault: yes.**

### 5. Two owners for the checks preamble — one has the carve-out, one does not

The anti-test-editing preamble fired ~30× from an **inline f-string at `probegate.py:547-550`**
(a rule-22 violation on its own) with no carve-out. Its sibling
`cria/prompts/block_nudge_preamble.txt:1` carries *"A test YOU wrote earlier in this session is
yours."* The model found the right answer at 0035 and reversed at 0036. **cria fault: yes.**

### Fixes landed this cycle, as measured on this run

| fix | verdict |
|---|---|
| spill files always `.txt` | **behaving** — both spills `.txt`, and `spill_path_redirect` caught an absolute path |
| `-lic` login shell | **works, and exposed a new false fact** — it is how `bundle3.2` was found, and the sentence built on it names `bundle` |
| shared gate budget | **behaving** — 5 gates, 5 results, no exhaustion |
| harness-truncation observer | **silent, not exercised** |

---

## feed-pipeline-java_qwen35 (chunks 001–076)

*Agent read chunks 053–076 itself and delegated 001–052 to readers, cross-checking quotes where the
ranges touch. It said so.*

### 1. The work was complete at CALL 0141 — established from tool output, not the score

All five deliverables demonstrated inside one call: REVIEW.md on disk at 6,800 B, the messy feed
reporting `invalid_price: 1 / invalid_quantity: 2`, three byte-identical 40,000-row runs,
`mvn compile -q` exit 0, and opencsv 5.12.0 in the pom. **The run continued for ~380 more calls.**

### 2. THE OWN-GOAL — a false clause in a steer, and the model gutted working code

Call 0212, delivered verbatim:

> `⟦ctx:steer⟧ [REDIRECT] … The task requires 4× faster execution … but **no code changes have been
> made to address performance**. Read the full Importer.java source file … implement concrete
> optimizations`

False, and **cria's own prompt proves it** — the same prompt shows `WORKERS_ENABLED = true`,
`ConcurrentHashMap`, `AtomicInteger`, `Executors.newFixedThreadPool`, `LinkedHashSet` replacing the
O(n²) `List.contains`, and OpenCSV replacing `line.split(",")`.

The model adopted the steer's voice in the next turn and then, at 0217/0218, **replaced header-keyed
column lookup with hardcoded positions**:

```java
colIndex.put("sku", 0); colIndex.put("quantity", 2); colIndex.put("unit_price", 3);
String sku = values.length > 0 ? values[0] : null;
```

`colIndex` became dead code; the header is read and discarded. That directly attacks the task's
"missing columns" requirement. Measured runtime never moved — 1.147 s → 1.925 s → 1.147 s — because it
was JVM startup all along. **cria fault: yes.** This is the single most expensive byte-string in the
cycle.

### 3. The same false steer, one cycle earlier in the run — call 0182

> `The coder is stuck in a loop … without addressing the core task requirements: achieving 4× speedup,
> fixing the threading bug, or ensuring REVIEW.md is complete`

All three were satisfied and visible **inside the reasoner's own prompt**. The reasoner's private
thinking also slips out of the judge seat — *"I need to profile the current implementation… I should
read the current Importer.java"* — the exact fence failure principle 8 documents. The model resisted
this one; the damage landed on the next.

### 4. "a specific line could not be parsed" — printed beneath the parsed line, 5+ times

Found at calls 0018, 0045, 0056 and 0170 in this run, and independently at call 0020 of
`feed-pipeline-java × gemma4`. The `⟦ctx:checks⟧` block shows
`Importer.java:[216,28] cannot find symbol / symbol: variable knownSkus`; the steer beneath it says no
line could be parsed and quotes the trailing `[Help 1]` URL instead.

**And `probeparse.split_diag` was already fixed for exactly this** — `_MAVEN_LOC` normalises
`file:[line,col]`, and its comment records the incident: *"cria then told the steer author 'a specific
line could not be parsed from the output' while the located errors sat in the same turn… Seen in every
Java cell of cycle 1; that column scored 0 / 40 / 0 / 0."*

So the parser is fixed and **the steer path still selects `ground_truth_failed.txt`**. The checks block
parses the line; the steer-selection path concludes there is none. Two paths, one signal, still
disagreeing. **cria fault: yes** — and this is the cheapest high-value fix on the list.

### 5. What the assists were worth over calls 0159–0223

| mechanism | calls | earned |
|---|---:|---:|
| the gate | 10 | **1** — nine repeated "no error-class problems" the coder's own `mvn compile` had just printed |
| the reasoner/steer | 3 | **0** — two asserted unfinished work that was finished, one of those caused the regression |
| completion machinery | ~12 | reached `satisfied: true` at 0201 and the run still did not stop |

Two mechanisms worked and are worth protecting: the repetition guard (accurate counts, model changed
action) and `⟦ctx:denied⟧` on the 40,001-line `feed.csv`.
