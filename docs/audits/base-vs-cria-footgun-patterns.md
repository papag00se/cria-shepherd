# Where cria's assists get in the way — five BASE/CRIA pairs, micro and macro

**The question.** Take cells where the model proved it can do the task unaided (BASE above 80%) and the assisted arm sits below that, worst gap first. Read both runs of each pair line by line. Find the per-cell cause, then the patterns across cells. Throughout, separate **cria as the direct author** of a harmful string from **cria relaying** one a reasoner wrote.

---

## The pairs, and the two that did not survive checking

| cell | BASE best | CRIA median | gap | verdict |
|---|---|---|---|---|
| rust-toml-cli × ternary-bonsai | 100% | 0% | **100** | holds |
| feed-pipeline-java × gemma4 | 100% | 0% | **100** | holds |
| cart-billing-go × ternary-bonsai | 100% | 40% | **60** | holds |
| shipping-rates-rb × qwen35 | 100% | 40% | **60** | **confounded** |
| handles-cli-node × ternary-bonsai | 100% | 75% | 25 | **invalid** |

**node is not a comparison.** Its BASE prompt says *"Output the resolved address, the holder's address and the number of handles"*; its CRIA prompt says only *"Output the holder's address and the number of handles"*. The verifier scores for an `addr1…` string. The assisted model built exactly what it was asked for and was graded against one thing more. Two of its four checks were lost on that alone. Found by the walker reading, and independently by dates: **every task's `prompt.txt` was revised on 08-12 or 08-13**, and filtering both arms to runs after their task's revision drops **111 rows**.

**ruby is confounded by cria's own version.** Its CRIA run is 08-16 04:56; the install route gained the half naming `require "bundler/setup"` at 08-16 17:42. The walker's largest finding — that the assisted coder never saw that string in 134 calls — is **not a withheld fact, it is a fact that did not exist yet**. Two of its other findings ("It is YAML", "too large for the context") were fixed earlier the same day.

**And the same confound touches all five.** Every CRIA run here predates every BASE run: CRIA 08-13 to 08-16, BASE all 08-17. This set measures what the assists did *then*. Findings are only worth acting on where the mechanism is still live, which is noted per pattern below.

---

## Macro — the patterns across cells

Ordered by how many of the five cells they appear in.

### 1. The research pre-step is wrong in both directions — 5 of 5 cells

Corpus-wide, across every surviving CRIA capture: **it fires with a step 100 times and answers NONE 37 times.**

| cell | what it produced | what that cost |
|---|---|---|
| rust | *"Visit crates.io to identify…"* | fetched the **unversioned** docs page, which serves the newest release → wrote `toml = "1"` → `E0282` consumed the run |
| node | *"Read api.handle.me and identify…"* | read the schema, never fetched `/handles/goose`; `addr1…` appears **zero** times in the whole run |
| go | *"Read cart.go, cart_test.go and go.mod…"* | sent it to read three files already in the workspace — five calls of scaffolding for a three-file read |
| java | **NONE** | the task's whole difficulty was a third-party CSV API; the model then guessed it **seven** times |
| ruby | **NONE** | the task's whole difficulty was a third-party EU gem |

**When it fires it sends the model to read *about* the thing instead of fetching the thing. When it stays silent it does so precisely where reading was the entire job.** It costs a model call either way.

*Source:* the sentence is **RELAY**; the pinning is **DIRECT**. Still live.

### 2. A relayed steer contradicted the task or the evidence in front of it — 4 of 5

- **go**, twice: *"Stop chasing the decimal library. Switch to integer cents (`int64`)… Delete `go.mod`'s require line NOW."* The task says *"Add a third-party Go decimal module… Do not create a custom decimal type."* The coder obeyed in the same call, both times. Final state: dependency deleted, source still importing it, nothing builds. BASE hit the identical hallucinated-version failure and fixed it in two calls with a bare `go get`.
- **java**: *"identify where concurrency is being blocked"* — it was not; `WORKERS_ENABLED = true` and threads started and joined. And the reasoner's own thinking admits it never checked.
- **ruby**: *"The Rakefile already handles them correctly"* — `rake/testtask` spawns a fresh `ruby`, so it does not, which is why every `rake test` in the run reported `LoadError`.
- **node**: endorsed polishing an `--unknown` flag that appears in neither the task nor the verifier.

The reasoner's own prompt forbids this in words — *"Do not choose the IMPLEMENTATION… directives that picked the approach cost nine checks"*. **The guard is written down and it did not bind.**

*Source:* **RELAY**. Still live.

### 3. The step pin outlives its own release condition — 3 of 5

rust's step is still in the **last coder prompt of the run**, 33 calls later, after the critic ruled it `done: true`. `loop.item` re-emits it 20 times and the plan never advances past step 1 of 2. In rust it also outranked cria's own correct `[REDIRECT]`, twice — the model's reasoning at those calls does not mention the redirect at all.

*Source:* **DIRECT** — `step_framing` re-appends *"Do ONLY this step, then stop"* after every tool response. Still live.

### 4. A guard fired on the one action that was working — 3 of 5

- **ruby**: the repetition redirect said *"Continuing down this line will not change the outcome"* about an `-I` sweep whose very next step loaded the gem and ran the suite — each step had consumed exactly one remaining missing dependency. The coder abandoned it.
- **java**: the same guard fired on the `list_dir target/classes` whose output was the answer it was hunting.
- **rust**: 12 calls whose entire content was a denial.

*Source:* **DIRECT**. Still live.

### 5. cria's own probe cannot see what the coder did, and outranks it — 3 of 5

- **ruby**: the composed probe runs plain `ruby -Ilib -Itest` with no gem dirs, so it is structurally incapable of seeing the coder's working invocation — and is presented as *"the CURRENT state of the repo"*.
- **java**: *"a specific line could not be parsed from the output"* with the parsed line one paragraph above.
- **node**: *"NO tests were actually executed"* seconds after the model ran 17 of them, and *"the delivered program was not run, because FileNotFoundError: 'node'"* — cria's probe runner could not find `node` on its own PATH and reported that as a fact about the coder's program.

*Source:* **DIRECT**. Partly fixed (the transcript claim, the YAML sniff); the framing is live.

### 6. Stale evidence re-served as current — 3 of 5

java's compaction froze a compile error the previous call had already fixed; go's reasoner fired seven times on a check snapshot taken before the fix that invalidated it, and reasoned itself into *"Go's toolchain is reading a stale/cached version"*; ruby's compactor dropped the one working incantation from the briefing.

*Source:* **RELAY** authored, **DIRECT** delivered. Partly fixed this session.

### 7. What did NOT generalise

**"cria halves the coder's turns."** True in go — 55 baseline turns against 23 — and false as a pattern. Across the four valid pairs: **196 baseline coder turns, 211 assisted.** Java and ruby gave the coder *more*. Recorded because it is the kind of number that reads well and is wrong.

---

## The quantitative cut, and why most of it is survivorship

Across 206 CRIA runs, mean score when a mechanism fired versus when it did not:

| mechanism | fired | mean | absent | mean | delta |
|---|---|---|---|---|---|
| `loop.rumination` | 60 | 38% | 146 | 62% | −24 |
| `context.repeat_dedup` | 17 | 36% | 189 | 57% | −21 |
| `rumination.abort` | 72 | 42% | 134 | 62% | −19 |
| `loop.repetition` | 114 | 49% | 92 | 62% | −12 |
| `writeproxy.dependency_note` | 21 | 45% | 185 | 56% | −12 |
| `loop.steer_dictated_code` | 54 | 47% | 152 | 58% | −10 |
| … | | | | | |
| `loop.done_critic` | 50 | 80% | 156 | 47% | +33 |
| `loop.gate` | 142 | 70% | 64 | 22% | +47 |

**Read this carefully or not at all.** The positives are survivorship: a completion critic only fires on a run that got far enough to claim it was done, so `+47` says "runs that reached a gate scored better", not "gating helps". Most negatives are symptom, not cause — the rumination guard fires *because* a model is struggling.

The rows worth a second look are the ones that fire **early, before the outcome is settled**: `writeproxy.dependency_note` and `loop.steer_dictated_code`. Both are mechanisms this audit found misfiring by reading, and both sit ~10 points down. That is corroboration, not evidence.

---

## The distinction, summarised

**RELAY did the damage.** The research step, the go redirect, the stale compaction briefings, *"Your code is correct"* delivered immediately before three real compile errors, and an order to delete the `$LOAD_PATH` lines that were the only thing making the gem load.

**DIRECT made it stick.** `step_framing` re-appending the pin after every tool response and never releasing it. The repetition redirect asserting an outcome it had just been contradicted on. The probe that cannot see the coder's own command while claiming to be the repo's current state. And `steer-recover`, which takes a reasoner that answered `ON_TRACK` and manufactures a directive out of its private thinking — that is how the forbidden `int64` instruction reached the go coder a second time.

The two need different remedies. A RELAY footgun is a question about what cria should be willing to pass through — every one above was already forbidden by the authoring prompt's own rules, so the gap is enforcement, not wording. A DIRECT footgun is a string or a code path in this repo, and it can simply be corrected.
