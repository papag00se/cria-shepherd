# Open threads — what's left to decide and build

The single source of truth for work that is **undecided or unbuilt right now**. Update it as decisions land and items ship. Grew out of the 2026-07-18 routes/naming/reasoning discussion.

**Where the rest is tracked (so nothing feels lost):**
- [docs/goals/work-plan.md](goals/work-plan.md) — the `/goal` wave (Epics A/B/C). **COMPLETE.**
- [docs/audits/port-fidelity-audit.md](audits/port-fidelity-audit.md) — older port gaps (the former `DEFERRALS.md` was merged in here, commit `5be0f9f`).
- This file — the live themes below.

---

## Decisions — all resolved (2026-07-18)

| # | Decision | Resolution |
|---|----------|------------|
| D1 | Reasoning knob names | **LEAVE ALONE.** No `think`/`show_thinking` rename — `reasoning`, `[indicators].reasoning`, `reasoning_transcript` stay. The whole rename is cancelled. |
| D2 | local/cloud → new names | **Not a rename — a UNIFY.** They were never two things: one concept, `[backends]` + `[roles]`, differing only by transport/auth. No `served`/`keyed` split. |
| D3 | Classic config schema | **ZERO ALIASES.** Classic `[models.local]`/`[models.cloud]`/`[providers]`/`[upstream]`/`local_only` + the desugar layer DELETED. `[backends]`/`[roles]` is the only format. |
| D4 | Route-unification scope | **(b) full unify** — plan-off = a degenerate 1-item plan → one driver. |
| D5 | Order | **Do everything**, no per-theme gating. |

---

## Build queue

### Theme 1 — Reasoning legibility  ❌ CANCELLED (D1)
No rename. The one real bug it carried (B3b half-done: the loop's internal reasoner hand-rolled `enable_thinking=false`, so a cloud reasoner's "off" was a no-op) is **CLOSED by the config unify** — every role now goes through `role.apply()`, which translates via its backend's `think_protocol`. Nothing left here.

### Theme 2 — Config unify (was local/cloud rename)  ✅ SHIPPED (`68a4597`)
- [x] ONE model: `Backend` (where) + `Role` (how). Killed `LocalRole`/`CloudEntry`/`ProviderConfig`, `local_roles`/`cloud_pools`/`providers`/`local_only`, the desugar, and the `cloud.<role>` address.
- [x] ONE format: `[defaults]` + `[backends]` + `[roles]` + `[failover]`. Zero aliases.
- [x] `role.think_protocol` (chat_template | openai | openrouter | none) resolved from the backend → `role.apply()` translates reasoning uniformly; B3b closed by construction.
- [x] `endpoint_for` builds an authed Upstream for a keyed backend → **B1-http residual closed** (a loop role on groq/openrouter is now reachable, not just the proxy coder).
- [x] `cria.example.toml` (all keys, terse) + live `~/.cria/cria.toml` converted; cria restarted. 930 tests.

### Theme 3 — Route unification  ✅ SHIPPED (`10404d0`→`1d128f9`, live-smoked)
Plan-off is now a degenerate 1-item plan → ONE driver (`Loop.drive`); the planner is an internal on/off stage. `_drive_direct_coder`/`_gate_direct_done` + 8 more server helpers DELETED. All 3 invariants held: (1) the off-ramps (stall-terminate / satisfaction / done-critic) live in `Loop._drive_single_item`, reached only via `sess.synthetic` — the multi-item path is untouched; (2) `_frame_for_item(synthetic=True)` = raw task, no "step 1/1", byte-equivalent to the old framing; (3) synthetic session persists on stable `sid:` keys, **ephemeral** on unstable `task:` keys. The shell-tool decline is gated to planner-ON (else the synthetic path would lose its guards).

- [x] Design pass → `docs/goals/route-unify-plan.md`.
- [x] Phase 1 synthetic framing; Phase 2 relocate into `Loop`; Phase 3 creation + persistence; Phase 4 flip dispatch + delete plan-off path; Phase 5 remove dead `GuardStore`.
- [x] 944 tests; **live smoke**: a coding turn drove `loop.start synthetic=true steps=1`, ZERO `plan_off`/`direct_coder` events, HTTP 200 coder `write_file`.

### Residual — a cli backend can't be a loop-internal endpoint (B1-cli)
`endpoint_for` now resolves served + keyed-http; a **cli** backend (claude) still falls back to the shared endpoint (a raw chat endpoint can't be a subprocess agent). Rare config; left as a known gap.

- [ ] (low priority) Make a cli backend usable as a loop-internal role, or reject it with a reason.

---

## Considered and REFUSED (don't rebuild)

### Withhold a steer that contradicts the session's own response shapes (2026-08-03)
A steer naming a parsed endpoint AND a field that endpoint does not return would have been deleted before delivery. Built twice, refused twice. What the evidence said, all of it re-derived by an independent reviewer over the 98-run corpus:

- **The trade is upside-down.** 18 candidate steers: **4 defective, 10 correct**, 3 capture artifacts, 1 unclassifiable — and nothing lexical separates them. Correct and defective name the same two endpoints and the same two fields in the same kind of sentence. Ten clean signals gated to catch four (rule 1: the bar to ADD is high).
- **It cannot prevent the damage.** All four defects arrive AFTER the coder already wrote the wrong field: −53, −196 and −19 calls. The one case where the steer led the write is the case the gate MISSED at temp 0. Withholding an echo of a fact the coder is already acting on changes nothing.
- **The real cause was upstream and is already fixed.** The steer author's evidence block ended `utxo(string, e.g. …), …+4 more field(s)` — it was shown 34 of 39 fields and told 4 were hidden, so it could not rule the field out. That is cria showing an author a cut list, not a model inventing a fact. `FIELD_CAP` 30→40 (`ce8ac20`) renders the same spec with **no elision**. Every run behind this branch predates that commit by hours.
- **The message that actually destroyed the recovery is out of its reach.** The coder worked it out alone — *"the API response we have does not contain a field for total handles"* — and what pushed it back was the step critic's `reason`, which reaches the coder on a different path the check never sees.

If it is ever revisited, the fix belongs in the steer author's own prompt (fence it to the parsed field names it was given), which also covers the critic path and the plan step. Not a downstream deletion. Re-open only with ≥5 runs on current code showing the false claim still happens.

---

## Shipped this session (done — don't re-litigate)
- Never-truncate overhaul (`fc2682c`); web_fetch/read exec-envelope strip (`4671687`, `f77d3bb`).
- Turn-stats ledger fixes (`86cb1c3`, `1c6fe74`, `3d7dcc8`); satisfaction-gate-on-green (`9355ca6`).
- validate-before-lower + normalize_tool_names + subtractive gate framing (`d12b248`).
- The whole `/goal` work-plan — Epics A/B/C, 11 commits (see work-plan.md).
- Self-recursion detector idea dropped (`3cdf774`); B3b reasoning-portability (`ea6fba9`, `130228c`).
- **Config unify — one backends/roles model, zero aliases (`68a4597`).**

**2026-08-04 addendum (REGRESSION1 walks), counter-evidence:** run `ada-handles_gemma4_codex_poff_1785843217` steer 0080 asserted camelCase field names (`resolvedAddresses`/`totalHandles`) against a ledger holding the snake_case truth — and the coder's code was CORRECT until it obeyed; the shipped resolver kept `totalHandles` and was unusable. This is a defect that arrived BEFORE the write it caused, the case the refusal's "damage already landed" bullet said did not occur. A second same-day instance: `ada-handles_nemotron-elastic_codex_pon_1785834747` (plan-step side) survived five replans and seven correct critic rejections demanding fields from an endpoint the ledger proves does not return them. Two walked runs, two surfaces (steer, plan step), both ledger-disprovable. Re-adjudication is the operator's call.

---

## Open: a command cria composes cannot exceed 128 KiB, and one path is unmeasured

**The bound.** The harness runs `bash -lc "<command>"`, so every command cria composes is ONE argv string, and Linux caps a single argument at `MAX_ARG_STRLEN` = 32 pages = 128 KiB. Nothing inside the command escapes it — a heredoc, chunked printfs and base64 are all bytes in that same string. Codex reports the overrun as `Argument list too long (os error 7)` and fails the WHOLE exec, so nothing lands and the model gets an error it cannot attribute to anything it did.

**Where it is handled.** The fetch spill (`writeproxy._spill_command`). It was measured there: a large spec never landed, and the workaround — stage the doc in cria's own directory, lower a small `cp` — copies a file the harness cannot see the moment cria and the harness are not the same machine, which silently produced an EMPTY doc under a pointer telling the model to read it. It now cuts at `SPILL_CONTENT_MAX` and states the cut in both the file and the pointer message.

**Where it is not.** `writeproxy._write_command` — the model's own `write_file`. A model writing more than ~90 KB in one call would hit the same wall and get the same unattributable error. **Not observed once**, in any walked run, from any model. Per #15 that is not enough to build on: what a guard here would do (refuse, and tell the model to write in parts) is an ADD, and the bar to add is high.

**What would settle it.** One walked run where a `write_file` fails with `os error 7`, or a count of write payload sizes across the capture corpus showing any above ~90 KB. Until then the docstring states the ceiling and nothing enforces it.

---

## Open: the zero-config TEST FLOOR has the same bundler blindness, and its counter-case is unread

**Settled and fixed:** `rake test` now runs through bundler when the Gemfile declares `gem "rake"` (`probediscovery.build_ruby`). Evidence and counter-evidence are in `tests/test_the_repos_own_check_is_the_repos_own_command.py`.

**Not settled:** the ruby TEST FLOOR — `ruby -Ilib -Itest -e 'Dir["test/**/test_*.rb"].each { … }'` — has the identical problem. It does not consult bundler, so in a project that vendors its gems it dies on `require` and cria publishes that as the repo's own check. Both false reds show it: floor red bare, green under `bundle exec`.

**Why it was not changed with the other one.** Running the floor under bundler flips one archived run the OTHER way — `shipping-rates-rb x qwen35` 1786864442, where the bare floor is GREEN and `bundle exec` is red. That run does not declare `gem "rake"`, so the shipped rule leaves it alone, but a floor-specific rule keyed on "a Gemfile exists" would not. **Nobody has read why that one fails under bundler.** Until someone does, a change here trades two false reds for an unknown number of false greens, and a false green is the worse direction (#13).

**There is also a design question underneath it.** The floor's own docstring says it exists "for the config-free case: a runner is added when the tree has that language's test files but no manifest to trigger ecosystem discovery". It is firing on projects that HAVE a Gemfile, where `build_ruby` already supplies rspec and rake. Either the floor should not fire there at all (subtractive, #1's safe direction) or it should be composed like the manifest's own command. Deciding that needs the reading above.

**What would settle it:** read `bundle exec ruby -Ilib -Itest -e …` in archive `shipping-rates-rb_qwen35_codex_poff_1786864442` and say why it exits non-zero where the bare command does not.

---

## Elision sweep — 2026-08-22 — all fourteen roots closed

Eight agents read all 37,355 lines of `cria/` plus all 168 prompt files, on one dimension: **anything that makes what a model reads shorter or less complete than what cria had.** Every claim below was reproduced by running the code. The working notes with the per-site evidence are at `docs/audits/2026-08-22-elision-sweep.md`, on disk and out of git by the usual rule.

**All fourteen are fixed and live.** The table is kept as the record of what each root WAS and what the fix at the root is — the shape is what stops the next instance, and a table of shapes is worth more than a changelog of sites. Two guards ride with them and are the durable half: `tests/test_unknown_is_never_read_as_absent.py` (no workspace answer is tested for bare truthiness, since None is falsy) and `tests/test_no_new_unmarked_bounds.py` (every bare `[:N]` reaching model-facing text carries a written reason). A third, `tests/test_the_operator_sees_every_reshape.py`, holds R13's rule that a mechanism which rewrites the context declares itself.

Grouped by ROOT rather than by site, because the same mistake appears in up to seven modules — fixing seven sites without fixing the shape means the eighth arrives next week.

| # | Root | The fix at the root |
|---|------|---------------------|
| R1 | **"I could not see it" rendered as "it is not there."** Seven sites throw away `View`'s third value. `_token_is_grounded`, the survey entry cap, `reroot`, `names_a_workspace_file` on an absolute path, `_veto_refuted_by_disk` when nothing resolves, an unreadable MCP schema rendering as "takes no arguments", `linterprobe` on an unlistable directory. | One shared `absent(view, path) -> bool \| None`, the only sanctioned way to ask; plus a test that no model-facing negative-existence string can be reached from a `None`. The second half is what stops the next one. |
| R2 | **A bounded list printed without its remainder.** `stranded[:4]`, `dropped_paths[:6]`, `top[:40]`/`[:12]`, MCP resources, `_touched_paths` 8, `_writes_since_last_gate` 3, grep's 60 hits. Bare literals, no named constants, three under sentences asserting completeness. | One `named_list(items, cap)` returning the names AND the remainder sentence, deriving the count from the list it printed. A lint test forbids a `[:N]` on a list inside a model-facing string. |
| R3 | **A string clipped with no marker.** `msg[:200]`, `text[:200]`, `[:90]`, `[:120]`, grep's line clip, `refusal_reason`'s window. `probeparse`'s own comment says these were all removed; it is no longer true of that module. | One `clip()` that always appends the marker and is the only way to shorten model-facing text. The two existing ellipsis-clippers nobody reads collapse into it. |
| R4 | **Output cut before cria's own parser reads it.** The offline leg's `tail -c 600` (a bare literal, no marker, and it is *all* the offline evidence there is) and `MAX_PROBE_BYTES = 2 MB` (a cut introspection reads as "no API found"). | Parse first, bound second. Completion probes no longer use the former head/middle/tail exception: the harness spools their complete stream and returns checked pages until its byte count and SHA-256 verify. |
| R5 | **A remedy named that the reader cannot take.** The planner's spill notes say `exec_command: grep` to a seat with no shell, and `read_file with a line range` to a schema with no range. `focustrim` says "read the file if you need to be sure" about files `read_file` refuses. `verify_tools` opens "You have inspected enough" exactly when it did not. | The remedy clause is generated from the tool menu the reader holds — `toolmenu` already does this for its cheatsheet *"so the prompt can never disagree with the menu"*. Where no route exists, say so rather than name one. |
| R6 | **cria's metadata concatenated into someone else's text.** `summarize` glues `(+1 more)` onto the compiler's message — 21 of 90 calls lost to hunting a stray `+`. `_annotate` splices cria's line between a Go diagnostic and its own remedy, 132 times in one run, under "each is the checker's OWN message". | A field holding a tool's words holds only those words. cria's count, annotation and pointer are separate fields in the render. |
| R7 | **A filter that DELETES, keyed on a substring.** `_error_class_only`'s twenty advisory phrases; the gate's second application of the same rule over raw lines; `_is_failure` calling a live API's `{"error":"route_not_found"}` "nothing usable". | Key a deletion on STRUCTURE — the parser's severity field, the exit code — never a phrase. No structural signal means keep and label. Every deletion carries a count. |
| R8 | **The newest turn folded away.** `_tail_start` documents "Keeps at least one message" and returns an empty tail when the newest message alone exceeds the budget — the coder gets a two-message conversation and a summary headed "older turns were elided", about the turn it is answering. | The tail always contains the message being answered. If it alone does not fit, reduce it with a label or report an overflow — never fold the present and call it the past. |
| R9 | **cria rewriting the model's own words.** `fold_repeated_messages` builds its index from user/tool roles and applies it to every role — reproduced on an `assistant` turn and a `system` message, against its own docstring. An unmatched reasoning fence drops the rest of a message. | The role filter gates the WRITE, not the index build. An unmatched fence is a parse failure to trace, not a licence to delete. |
| R10 | **A tool schema reduced until it is unusable.** `_DESC_CAPS` ends in `0`: the description key is removed for every tool and every parameter. Reproduced — `read_file` arrives as `{"path": {"type": "string"}}`. | A tool with no description is not smaller, it is unusable. Stop at the lowest cap that carries a first sentence, then drop whole tools by name, the way `focus_tools` already does. |
| R11 | **Content replaced by a byte count with no way back.** A non-allowlisted content-type destroys the document before the parse, and `raw=true` re-runs the same branch. The binary note passes `kind=None`, so it cannot say what it was. | cria may say what it did not show; it may not close the route. Name `raw=true` or a spill, and sniff the bytes rather than trusting the header that was wrong. |
| R12 | **Pruning that never reaches the check.** `ignore.default_matcher()` unions eight `.gitignore` templates, so unanchored `lib`, `out`, `dist`, `build`, `target` prune any such directory at any depth — a Python package in `lib/` is pruned from the lint floor, and the gate then reports "no error-class problems" about code it never read. | A VCS's "untracked" is a different question from "this project's source". Use cria's own small exclusion set, exclude a directory only on proof it is generated, and name what was skipped in the clean-gate sentence. |
| R13 | **The operator cannot see cria reshaping.** Four events that rewrite or remove model-visible content are missing from `turnstats._RESHAPE_EVENTS`, under a heading about exactly that. | Generate the turn line from the set of events that reshape, not a hand-maintained list beside it. |
| R14 | **Bounds stated as certainties.** The window-exhausted guard says "nothing it produced could have been kept" — fired at 92% on a frame proxy, by cria's own choice. The evidence-summary note states a small model's compliance as fact. | A sentence about what happened says who did it, and names the threshold. A model-made summary is labelled as a request made, not a guarantee kept. |

**Two that are the operator's call, not cria's.** `INLINE_RESULT_MAX_BYTES = 9000` still bounds eleven model-facing paths, and cria's own source calls the belief behind it *"outlived its evidence"* — the question is whether the number should be measured from the wire (`note_harness_cuts` already asks) instead of remembered. And `toolmenu.focus_tools` drops a harness's native search, which in a deferred-tool harness removes the model's only route to most tools.

**What the fixes changed on the way through.** Several roots turned out to be load-bearing beyond their own site. R6's glued `(+1 more)` was silently defeating the gate's own de-duplication, so every multi-finding probe printed its first finding twice. R12's template pruning was removing `lib/`, `build/` and `dist/` from the lint floor for every language at once, and the hand-kept name lists beside it removed `target`, `vendor`, `bin` and `obj` as well. R13's guard test, written to hold the rule, immediately found three more undeclared events. R7's structural rule kept a traceback's source echo that the phrase filter had been deleting from the middle of a block cria ships as the checker's own words.

---

## Sub-40 walks — four items left unbuilt (2026-08-27)

Eight cria-side defects were fixed across two passes; these four remain because the clean decision is not obvious, not because they are small.

| # | What | Why it was left |
|---|------|-----------------|
| S1 | The `no_structure` fetch-ledger label — *"this page answered, but no endpoint definitions were found in it … nothing read so far provides one"* — rode every prompt of a Go run over a library README that cria had on disk and that contains the exact constructor the run failed to guess. | The sentence is *accurate*; the fault is that it characterises a page instead of pointing at the copy cria saved. Rewording it well means deciding what the ledger should say about a page that answered and is simply not an API spec. |
| S2 | The duplicate-search judge ruled `europe` versus `eu` "a new direction" **4 times out of 4** in one run, while its own prompt says a synonym swap is the same hunt. | A prompt fix with a clean measurement behind it, but the judge's whole job is to be conservative, and tightening it risks blocking a genuinely new search. Wants its own before/after over the captured near-duplicates. |
| S3 | `judge_query` (`loop.py`) sees the task, the query and the fetch record — not the workspace. In the ruby run it told the coder to keep searching for a gem that `bundle install` had put in `vendor/bundle` two calls earlier. | cria already builds exactly that listing for its satisfaction critic. Giving it to the search supervisor is a few lines; deciding what the supervisor should *do* with an installed-but-unused dependency is the open part. |
| S4 | `spill_outline` maps JSON and YAML only. A spilled markdown doc is handed over with "grep the file for what you need" and no map. The `countries` README has `### European Union Membership` at line 202. | Straightforward to add heading extraction; the open question is whether an outline belongs in the inline result or in the ledger entry, and how it interacts with the search-description change that landed with it. |
| S5 ✅ | **PARTLY FIXED (`420ecf4`) — the narrow half.** A turn that finishes with words only in the reasoning channel now keeps them (`massage.recover_reasoning_text`), gated on `finish_reason == "stop"` so the rumination guard still wins. 15 turns across the three walked runs, one of which decided a run. The general problem stands: **the coder's conclusions never carry forward.** 100% of coder turns across three walked runs emit reasoning and zero visible content, so every assistant turn in the model's own history is `content: ''` plus a tool call. The go model reached the run's correct fix seven times and never wrote it. `massage.text_or_reasoning` fixed this for cria's own seats and was never applied to the coder. | Feeding a model its own prior text is how cria's briefings once became unfalsifiable, and half a megabyte per run cannot go back wholesale. The narrow version — stop erasing a turn that emitted nothing at all — is the defensible part, and the 460 degenerate-run aborts in four days are where to start. |

### What the sub-40 fixes are worth, measured against the same logs

The two `_invented_code_spans` false positives fixed on 2026-08-27 were checked against the refusals that were actually logged, not only against the walked case. Of 28 `dictated_code` refusals in four days, **24 were over one or two spans** — the thin end, where a single false positive decides it. Replayed against the current code, both measured shapes now score zero:

- `Quote the error: "go build ./... — ./cart.go:59: undefined: decimal.NewFloat64" — edit cart.go …` — the author quoting the failing command back, as its own prompt asks it to. The surrounding quote marks were what made the quote fail the quote test.
- `Fix the compilation error: the code cannot find symbol CSVRecord and cannot find symbol method readNext().` — the empty-parens method name.

Both now pass. Whether that moves the delivered/refused ratio is a question for the next measurement pass, and `loop.steer_outcome` is what will answer it.

**Two candidate fixes were considered and NOT built, on #15.** Naming the packages inside a folded `vendor/bundle` line, and giving `judge_query` the workspace inventory. The evidence is one run — the ruby coder searching nine times for a gem `bundle install` had already put on disk. The first attempt at a shape rule for "which directory is a package" landed on `bin/cache/gems/specifications` rather than the gem names, which is the tell that the rule was being invented rather than found. Both stay here until a second run shows the same thing.
