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

---

## What was removed on the strength of this audit

### The repetition trigger (2026-08-19)

`guard_track_repetition` had two ways to reach the same redirect. One counted **identical actions** in a rolling window; the other counted **cria's own refusals**. The action route is gone; the refusal route stays, and the function is now `guard_track_refusals`.

**The measurement.** BASE runs (all assists off) that contained three or more identical consecutive calls scored a mean of **51%** across 7 runs. CRIA runs the steer actually fired in scored **48%** across 55. The steer's whole premise is that a model cannot get itself out of a repeat, and the arm without it did no worse. One BASE `cart-billing-go × ternary-bonsai` run wrote a byte-identical `cart.go` five times, stopped on its own, and finished at 100%.

**Why the refusal route is not the same thing wearing a hat.** It fires on a fact cria owns outright — it refused the calls, so they did not run — rather than on a similarity judgement about what the model meant. And the thing it reports is invisible to the model in a way a repeat is not: a coder can see it just wrote the same file twice; it cannot see that cria is the reason nothing happened.

**The incident that motivated the action route is still covered.** Run `20260802T195958` spent 35 turns on a byte-identical `web_fetch` and ran to the wall. A repeated identical fetch is refused by the web_fetch visibility gate, and that refusal carries the denial marker (`webfetch._REFUSAL_KEYS`) — so three of them trip the surviving route. `tests/test_reasoning_tool_calls.py::TheRepeatGuardSeesTheRecoveredCall` asserts that link directly, including that the keys stay marked.

**What went with it**, because nothing else read it: the word-set action signature and its two vocabularies (`_action_signature`, `_actions_match`, `_BOILERPLATE_WORDS`, `_NAV_TOOLS`), the progress predicate (`_is_progress`, `_MUTATOR_WORDS`), the no-op-write and refused-call filters that existed only to stop the window mis-flushing (`_rewrites_the_same_bytes`, `_denied_signatures`, `_last_write_by_path`), and `GuardState.recent_actions` / `repeat_kind`. Roughly 300 lines.

**Two things that improved on the way out.**

1. The steer quotes a call that was **actually refused**. It used to quote whatever call was in flight when the counter tripped — a call cria had not refused at all, printed under the words "cria REFUSED 3 of its recent calls … the most recent was". That is the same false-fact shape (#5b) this file's `step_framing` finding is about, in the seat where it does the most damage.
2. The wheel-spin guard can now see a shell-native write in a **truncated** argument blob. The raw-tolerant scan lived only inside `_is_progress`; `_shell_write_target` returned None and the streak went uncounted — and a truncated write is exactly when a model is spiralling on one file.

**One shape changes hands.** Five identical `write_file` calls in one completion used to trip the repetition redirect, which flushed the write window, so the wheel-spin guard never saw a shape that exactly met its own threshold. It reaches the spin guard now — a better-aimed intervention, since it names the file.

### The authored research step, and the plan cage it dragged in (2026-08-19)

On every plan-off coding task a reasoner was asked whether the task needed something read first. Its answer became the first item of a synthesized plan — which made that plan **two** items, which is what routed plan-off through the multi-item driver and pinned `Do ONLY this step (1 of 2), then stop:` to every coder turn.

**What the assist actually produced.** 174 captured authorings from `~/.cria/calls`:

| the answer | count |
|---|---|
| `NONE` — nothing needs reading | 42 |
| names only files already in the workspace | 102 |
| names an external source | 30 |

So 77% of the guidance was "open the files you were handed" — the thing a coder does on its first turn unprompted, and in several captures had already done inside the same reply (`I'll start by reading the existing source files… cat cart.go`).

**The other 23% already had a better home, eighteen days older.** `prompts/coder_system.txt` line 5: *"RESEARCH & INVESTIGATE FIRST: If the task depends on an external thing (an API, a library, a service, a file format), READ its real source/docs before writing code against it."* Landed `4929843`, 2026-07-16. The authored step landed `a0cf3ae`, 2026-08-03 — on top of a rule that already said it, generally, for free, in both arms. And the one fact the step contributed that the general rule cannot — *which* source — cria extracts deterministically with `first_domain_in(task)` and was passing **into** the reasoner's prompt.

**And the failure mode was never the firing.** From the quantitative cut in this file: a run whose research step cleared averaged 55% (n=55, 18 at 100%); a run whose step never cleared averaged 24% (n=5, 1 at 100%). Presence discriminates nothing — 30% of successes, 29% of failures. What discriminates is whether the assist ever lets go.

**Removed:** `research.authored_research_step` and the reasoner call behind it, `step_reading_verdict`, `step_defect` and its guess-shape vetting, `Loop._research_check` and `PlanSession.research_checked_turn`, seven prompt files, and the second plan item. `research.py` goes 447 → ~200 lines and keeps only what it always did honestly: read cria's own fetch/read ledger and report what was really read, for the judges and steers that ask.

**What this fixes beyond the step.** `_plan_off_session` no longer computes `synthetic` from the item count — plan-off is synthetic, always. There is no path by which a synthesized plan grows a second item, so there is no path by which the step cage reaches a mode with no planner.

**One thing moved rather than died.** `AUTH_SHAPE` was shared between the authored-step channel and `loop._steer_auth_refuted`. With one reader left it lives where it is read.
