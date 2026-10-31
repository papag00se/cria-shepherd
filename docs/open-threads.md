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

## Open — compaction evidence continuity and post-compaction reorientation, re-measured on HEAD (2026-10-30)

**Fixed (reproduced, replayed):** (a) the verbatim tail of a compacted view could start on a lone tool result, so the wire re-roled it as a bare `user` message with its call and path gone: 60 of 315 self-compactions rebuilt from the ornith-java captures shipped one (a `read_file` text, a compiler transcript, `Wrote src/main/java/pipeline/Importer.java`), 0 after `_whole_exchange_start` (`5075f44e`; 0 dangling calls before or after). (b) A compaction lens reserved its whole 16,384-token cap as reply room, so the fidelity lens read a floor digest instead of 53–215 evidence turns in 35 of 77 campaign requests (33 judge-shaped `context.floor` events with `turns_dropped > 0`); `COMPACTION_VERDICT_RESERVE` = 2,048 lets 21 of those 33 fit whole (`40747fda`). **Not fixed:** the four densest rebuilt requests (learned density 1.6–1.8) still drop 43–58 turns at that reserve; the validator then judges a labelled digest. The next owner is the same one that chunks the writer's evidence (`handoffdistill`): validators are documented as reading the full transcript and do not.

**Does the real fidelity verdict catch evidence loss? No.** Eight real briefings (4 whose request the floor digested, 4 not; `LATEST CHECK FACTS` empty or without a test run), n=8 each (2 at temperature 0, 6 at 0.7), same request with the candidate unchanged vs with a fabricated "`mvn compile` succeeded and the complete test suite passes" line appended: unchanged accepted 26/32 (whole evidence) and 25/32 (digested); the fabricated line accepted 30/32 (whole) and 17/32 (digested). No transcript shows a test run, yet 47 of 64 fabricated samples were FAITHFUL. This is the known weak verdict; the typed build lens is the signal. Claim families in this evidence that the size and build-state lenses do not cover: none found — the fabricated claim is a build-state claim.

**Reorientation `ungrounded` (current prompts, boundary listing from the preceding compaction request).** Run-4 fixture (ornith-java-overnight-c7dd… 0043): 30/30 authored, 0 ungrounded; all 30 name `Importer.java` and `pom.xml`, where the real pre-listing directive named neither (and the coder restored the seed). Other fixtures: 0 of 51 across an 18-fixture sweep (about 3 each), 0/30 for 01a174d0 (the Oct 25 real rejection), 0/24 so far for 01a16b0b. One fixture (overnight-98473…, call 0065) rejected 5 of 30 (0.7 sampling, 5/24 at 0.7 and 0/6 at 0): all five were opened in full and none invented anything — each names only `REVIEW.md`, the task's required deliverable, in verification framing ("check whether REVIEW.md exists", "write REVIEW.md naming file and line"); one adds the true "no REVIEW.md appears in the inventory". The name gather (`reorientation.invented_names`) is right to send it to the judge (the name is not in the summary or listing); the judgment is what fails: three `{"grounded": false}` and two EMPTY one-token answers (`completion_tokens: 1`, prefix-cache hit, fail closed). The same text is accepted and rejected across runs (one rejected text accepted 8/8, one accepted text rejected 8/8 on a later replay): a borderline judgment, not a name-check bug, and with an owned handoff a rejection omits the steer entirely. Not tuned: a prompt change here needs fabricated-existence controls ("REVIEW.md already exists and lists the issues") at n>=8 first. Usefulness, honestly bounded: of 33 real authored directives, 30 name at least one file the coder touched in its next 8 calls and 3 name no file; in this one task the same four or five files are always needed, so overlap proves little.

---

## Open — the whole-briefing fidelity verdict carries almost no claim-level signal (2026-10-30)

Measured on the real run-3 judge call (0064) by replacing only the candidate briefing, prompt and settings exactly as production sends them, n=8 per case (2 at temperature 0, 6 at 0.7): P(FAITHFUL) is about 0.55–0.70 whatever the briefing says; the correct briefing was rejected 2 of 8, the real incident briefing 2 of 8, and ten single-false-claim briefings 26 of 80. From full responses the judge invents evidence (a `pom.xml` write absent from the transcript), rejects honest negatives ("has not been compiled" against a check block reading "no authoritative fact was available"), and reads the task's requirements as state. Typed-evidence blocks, contradiction-only wording, per-claim judging, reasoning-on and verbatim-citation requirements each moved every briefing together or inverted order; none separated true from false without losing detection in step, so nothing was landed against the verdict itself.

What has real signal is the typed lenses, which ask the model only to LIST names and let code settle them: the file-presence lens (`filepresence`, vs a complete-and-current survey) and the change-claim lens (`filepresence.unsupported_changes` with `writerecord`, vs the session's typed write record; abstains whenever the transcript is not provably the whole span). On the real incident briefing they refuse it 10 of 10 and 8 of 8, and 0 of about 30 controls. Built since: size claims against the complete survey (`filepresence.contradicted_sizes`) and build-state claims against the typed run/write order (`filepresence.unsupported_builds`, `writerecord.CheckRecord`); see `docs/heuristic-assists.md`. Known limits: `probeparse`'s JUnit tally only matches a line that STARTS `Tests run:`, so Maven's `[INFO] Tests run:` is never recognised and the newest-run-red refusal never fires for Java (the no-run and write-after-run refusals do); a write to a scratch/non-code file after the last run still counts as a later write. Remaining: whether the verdict should keep its veto at all (operator decision; needs a way to tell when the transcript is the whole session).

---

## Open — a false "compiles / tests pass" sentence beside an honest negative (2026-10-31)

The build-state lens (`filepresence.unsupported_builds`, labels GREEN / EARLIER / NOT GREEN, settled by code against the typed check record) refuses a false success claim 8 of 8 when it stands alone, and a specific one ("the rewritten `Importer.java` compiles cleanly and all tests pass") 7 of 8. A VAGUE one ("the code compiles cleanly and all tests pass") placed next to an honest "the rewrite has NOT been compiled" is refused only 2–4 of 8: the model lists the sentence but labels it NOT GREEN because the honest negative colours how "the code" reads. Measured on the real incident briefing (call 0062) plus the appended sentence, no check run in the transcript, n=8 per variant (2 at temperature 0, 6 at 0.7). Every variant tried that catches the vague contradiction also falsely refuses an honest briefing: a prompt telling it to label each sentence by its own words (noise-level, one regression), per-sentence labelling with the sentence alone (every sentence GREEN, 8 of 8 false refusals on the baseline), per-sentence labelling with the whole briefing (the contamination stays, 5 of 8 false GREEN on a baseline bullet), and a second "is the result dated before the changes" question (8 of 8 false refusals). The model cannot tell a qualified success claim from a contradicted one. Nothing was landed. Candidate for the owner: a grounded question asked only after the typed record already says no check ran, which was not tested.

---

## Open — multipart reads and image workflow (2026-10-29)

Built, committed and deployed (live as release `<short-hash>-multipart-image-20261029`, rebuilt from each HEAD; rollback = remove `99zzzzzzzz-multipart-image.conf`, `sudo systemctl daemon-reload && sudo systemctl restart cria.service`): transparent multipart reads (verified pages assembled into one logical read, fitted against the complete model-visible request, unverified carriers preserved without read credit) and the same-coder image observe/reinspect workflow ([docs/image-workflow.md](image-workflow.md)). Validated against real inference on the RTX 3080: native measurement equalled the server's own count in 45 of 45 checks; multipart reads of 12 KB to 150 KB through a real PTY and a real sandboxed Codex; real `gemma4_12b` vision on Chat and Responses, workspace `view_image`, remote URL references, streaming. Still open:

- **Automatic retained-state cleanup**: none, because cria has no trusted session-close signal or fenced lease; inferring closure from idleness, eviction or history is forbidden. `python -m cria.retention` is the explicit, operator-run route (dry run by default).
- **Binary and single-huge-line reads**: `read_file` has no byte-range argument and cria must not invent one; overflow answers state the measured size and ask for narrower pieces.
- Page reads are hash- and metadata-checked, not an atomic snapshot against a concurrent writer.
- Resolved (statement-only image tasks): the file-based confirmation is skipped when an observed image task has no file component, and the coder's closing reply reaches the satisfaction judge as a labelled claim checked against the observation (see `docs/image-workflow.md`). Still open: a closing reply is judged only for plan-off done claims; a plan-on or scheduled review does not carry it, and a non-image deliverable that is only a statement still has no reply in the judge's evidence.
- `suite/run.py` builds the Codex catalog with `input_modalities: ['text']`, so the stock suite catalog cannot run `view_image` at all.
- Chat-completions system messages are always replaced by cria's own coder system (by design, unlabelled to the model); only Responses `instructions`/developer items carry the caller marker.
- `writeproxy.rejected_payload_dropped` fires once per request while the rejected call stays in history (the audit count is inflated; nothing is lost).

---

## Lifecycle frontier (2026-10-30) — candidate not ported; its two boundary failures do not exist here

The unported "lifecycle frontier" candidate (r10: per-source declaration frontier over a store-owned `workspace_authority` / persisted workspace history) was blocked by two failing boundary tests (`test_sessions_roots_and_explicit_task_generations_do_not_share_pending_calls`, `test_completed_scope_does_not_pin_unresolved_state_into_other_tasks`) and "no current lifecycle owner". Re-expressed on the current owners (`wsview.View` per request + `writeproxy.represent_inbound`, `loop.LoopStore`), both hold: **already satisfied, premise now invalid.** A pending (unreturned) native mutation withholds current bytes for the conversation that contains it and for nothing else, because the view is rebuilt from the request's own history each time; no effect ledger, task-generation nonce or per-root pending set outlives a request (`git log -S workspace_authority` finds none, ever), so there is nothing to leak across root/session/task or to pin on a DONE scope. The candidate's frontier bug (a user-only suffix re-rendering a completed native mutator charging a second global effect) cannot occur for the same reason; the real capture it was built from (session `20260816T191710-01a00d82…`, call 0358, an 8-message history whose one exec_command is cria's own XML-check + `mvn` gate probe) was replayed through current `represent_inbound` with and without a user suffix: peer reads stay current, a read after the effect stays current across the replay.

The current owner of the *remediation lifecycle* is `completiondiagnosis` (`arm` / `acknowledge` / `follow_up` / `settle`, reached through `loop._settle_completion_remediation`), and it is **plan-on only**: plan-off `deliver_gap` never arms it, and planning is OFF by policy. Its one remaining gap is the candidate's retirement: `settle` releases only on cria's own `Wrote PATH` confirmation, so a missing-file remediation stays pending after the file exists by another route (a shell redirect with exit 0 leaves `completion_remediation_subject` set, measured). Not built: (1) it only affects the retired planner path, no plan-off incident exists; (2) the evidence that would retire it, "this exact path is present NOW", is a survey/whole-read fact `View` exposes only as `read()`/`isfile()` (no exact-path current-presence API exists in the current tree), and a shell exit code alone cannot distinguish a landed redirect from a silent failure, so the input is indistinguishable without that survey. If planning is ever re-enabled, the next test is the same shell-redirect case with a fresh complete survey or whole read of the subject retiring the remediation, never approving completion.

---

## Build queue

### Candidate new cria-wide languages

Candidates requested by the operator: **C, C++, Swift, Objective-C, Dart, Lua,
Perl, R, Julia, and PowerShell**. These are candidates, not a commitment to an
implementation order and not a claim of existing cria-wide support.

The immediate work is narrower: [filesystem-mutation analysis](cleanup-safety.md)
for these languages. Promoting any of them to cria-wide support is separate work:
workspace/ecosystem discovery, authoritative build/lint/test commands, participation
evidence, appropriate battery tasks, and regression coverage. A destruction-check
adapter alone does not satisfy that bar.

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

**2026-08-04 addendum (REGRESSION1 walks), counter-evidence:** run `ada-handles_gemma4_codex_poff_1785843217` steer 0080 asserted camelCase field names (`resolvedAddresses`/`totalHandles`) against a ledger holding the snake_case truth — and the coder's code was CORRECT until it obeyed; the shipped resolver kept `totalHandles` and was unusable. This is a defect that arrived BEFORE the write it caused, the case the refusal's "damage already landed" bullet said did not occur. A second same-day instance (plan-step side, a since-purged model) survived five replans and seven correct critic rejections demanding fields from an endpoint the ledger proves does not return them. Two walked runs, two surfaces (steer, plan step), both ledger-disprovable. Re-adjudication is the operator's call.

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
| R1 | **"I could not see it" rendered as "it is not there."** Seven sites threw away `View`'s third value. `_token_is_grounded`, the survey entry cap, `reroot`, `names_a_workspace_file` on an absolute path, the former free-form completion-veto path when nothing resolved, an unreadable MCP schema rendering as "takes no arguments", `linterprobe` on an unlistable directory. | One shared `absent(view, path) -> bool \| None`, the only sanctioned way to ask; plus a test that no model-facing negative-existence string can be reached from a `None`. Completion diagnoses now preserve the same three values through `_workspace_subject` and suppress unknown state. The second half is what stops the next one. |
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

---

## Open: cria has no concept of PROGRESS — the diagnosis holds, the obvious fix measured inert (2026-09-18)

Walked on the first two `ternary-bonsai-2` L5 cells (`shipping-rates-rb` 5%, `cart-billing-go` 0%).
Across ~54 model calls the coder wrote **one file** (a Gemfile) and never touched a task file.

**The diagnosis, verified three ways in the source and not in doubt:**

1. `cria/prompts/coder_system.txt:5` says *"RESEARCH & INVESTIGATE FIRST … READ its real source/docs
   before writing code against it."* A grep of every prompt finds **no counterweight** — nothing tells
   the coder when investigation is finished.
2. `⟦ctx:facts⟧` records *"FILES YOU HAVE ALREADY READ"*. There is no counterpart for a conclusion
   reached or a change shipped, which is why the one-line `>` → `>=` fix was re-derived at calls 6, 7,
   9 and 26 of the same run and written zero times.
3. Every nudge in [heuristic-assists.md](heuristic-assists.md) keys on **repetition** (same tool+args
   ×3, same file rewritten ×5) or **doubt**. `unexecuted_write` needs file content in prose;
   `leg0_nudge_step` needs *zero* tool calls. A coder taking nine *different* read actions matches
   nothing in the arsenal.

So a coder that reads forever with varied arguments is invisible, and the rumination guard — the only
thing that ever fires — prescribes *"prefer reading the current file"*, which is the same blind spot
written as advice.

**The fix that follows from it, and MEASURED INERT.** Replace the guard's generic remedy with a true
progress fact cria already holds (the gate's failing `file:line`, turns elapsed with no write, and
whether that file changed). Replayed against the live model on the real captured call
(`0030-coder-s1-focus1`, the turn immediately after an 8,240-token abort), n=4 per arm:

| notice | writes | touched a task file |
|---|---|---|
| as sent (*"prefer reading the current file"*) | **0/4** | 1/4 |
| progress fact | **0/4** | 1/4 |

Identical. Worth recording *how* this nearly went wrong: at **n=1** the fact arm looked like a win —
it moved the read from `Gemfile.lock` (irrelevant) to `lib/shipping/rates.rb` (the file to fix) — and
that difference disappeared at n=4. A single sample was about to be reported as a result.

**THIS IS NOT A UNIVERSAL NEGATIVE, and the idea is kept here rather than in *Considered and
REFUSED*.** What was measured is one notice wording, on one guard arm, on one turn, of one cell, with
one model, on one task, at n=4. The cell it was tested against is also the *hardest* case for it: a
coder deadlocked on an unmade decision, where more true facts are least likely to help. Cases where it
is still plausible, none of them tested:

- a coder stalled on a **missing fact** rather than a decision (`cart-billing-go` is that shape)
- a **different model** — nothing here generalises off `ternary-bonsai-2`
- delivery somewhere other than the rumination notice — the periodic gate, or the step framing
- a longer horizon: the replay measures ONE turn, and a progress fact may pay over several

**What the negative does establish:** adding a true fact to the prompt is not, by itself, sufficient.
The coder already knew the fix — it derived it four times. So the blocker is not information, and any
next attempt should target something other than telling it more.

**The prompt lever was then tested too, and is ALSO inert.** Same harness, same captured turn:

| lever | writes |
|---|---|
| baseline (*"prefer reading the current file"*) | 0/12 |
| progress fact in the guard notice | 0/4 |
| `STOP INVESTIGATING ONCE YOU CAN ACT` counterweight added | **0/12** |
| `RESEARCH & INVESTIGATE FIRST` deleted outright | 0/4 |

The counterweight arm also touched FEWER task files than baseline (1/12 vs 4/12). And it repeated the
n=1 trap exactly: at n=4 it showed 1 write including a real `edit_file`, which vanished at n=12. Two
different remedies, two false positives at small n, both caught only by re-running.

**So the family is ruled out, which is the useful result.** On this turn, with this model, a
prompt-level intervention does not convert a read into a write — not by adding facts, not by granting
permission, not by removing the instruction that looked responsible. The coder had derived the fix
four times already. Whatever holds it is not reachable by editing the text handed to it, and that
retires the whole class of fix this thread was drawn to.

**The tool-menu lever WAS then measured, and it splits the two cells.** Same harness. Withholding
the read-only tools (`read_file`, `list_dir`, `exec_command`) for one turn:

| | baseline | read tools withheld |
|---|---|---|
| cell 1 `shipping-rates-rb` (turn after an 8,240-token abort) | 1/12 writes | **9/12 writes**, 4 of them the correct `>=` fix |
| cell 2 `cart-billing-go` (late research turn) | 0/6 writes | **0/6 writes** |

Withholding `read_file` ALONE does nothing (0/12) — the coder routes around it via `exec_command`.
And in cell 2 it routed around the full constraint too: `exec_command` became `web_fetch`, six for
six. No `task_complete` in any constrained sample, so it is not being pushed into a false done.

**This is not a progress fix; it is a DECISION-DEADLOCK fix.** The two cells are the two stalls:

- cell 1 had an **unmade decision** — it had read everything and derived the one-line fix four times.
  Removing the read tools left nothing to do but act, and it acted, correctly.
- cell 2 had an **unread fact** — it genuinely did not know which Go decimal package exists. No tool
  constraint can manufacture that, so it reached for the nearest remaining intake tool and kept
  hunting. Here the constraint is useless and probably harmful: that coder SHOULD still be looking.

So the same cause-split that defeats the rumination guard's fixed remedy defeats this one, in a
different mechanism. **Any fix in this area has to tell the two stalls apart first**, and nothing
deterministic does. That is the original open question, unchanged, and now with a second mechanism
blocked behind it.

NOT BUILT, deliberately. One arm works on one turn of one cell and does nothing on the other, and
shipping it would put a mechanism on the live path that fires on the wrong half of cases with no way
to know which half it is in. 9/12 on a single turn is not a licence — two remedies already looked
like wins at small n in this same session and evaporated on re-running.

**Incidental, and worth keeping:** the probe calls the model directly, so cria is not in the path.
One baseline sample then generated for **10 minutes and 10,940 tokens without ever emitting a tool
call**, and only stopped because the harness timed out. That is what the rumination guard prevents on
every one of these turns, measured by its absence.

## Closed — when to compact is a predicate over measured room, not a configured trigger (2026-10-30)

`[context] trigger_compaction` and `windowcaps.SELFCOMPACT_TRIGGER` are gone (a config still carrying the key fails at startup naming it). A view is compacted NOW iff one more turn of MEASURED growth (the largest of the last five turns the view grew by; the largest single message before any turn) would not fit EITHER bound: the coder's (`(view + frame) × learned density + reply reserve ≤ window`, past it the floor drops turns) or the compaction calls' (`evidence × summary density + prompt frame + writer reply cap + verdict reserve + facts ≤ window`: the writer and every validator read the whole view). Unknown window: no room, so only floor pressure and a step boundary compact. `Loop._compaction_room`, `selfcompact.view_room` / `expected_growth` / `evidence_tokens`; `tests/test_compaction_room.py`.

**Why the pinned 28,884 at 49,152 was wrong, not merely arbitrary.** 49,152 − the live coder reserve 16,384 − 28,884 = 3,884: the pin is `window − reserve − frame` at density 1.0, a hand-derived version of this formula that ignores the learned density (1.13–1.2) and the real frame (system + root + tools ≈ 7.4–8.0K est. measured on the 8 sessions below, not 3.9K). Evidence: in the ornith-java campaign events (pin live) 463 coder requests carried reserve 16,384 and were floor-trimmed, 428 of them DROPPED coder turns, median view before the floor 34,245 est., max coder prompt 32,278 real tokens (= 49,152 − 16,384); and over 86 real sessions (no model, `offline`: density 1.2, frame measured per session) the pin's first fire leaves the coder request over the window in 83 of 83 sessions by a median 12.6K real tokens, where the predicate's first fire does in 37 of 86 (median −820: it fits; the 37 are single-turn jumps past the measured growth, e.g. an 11K file read, or a session whose first request already carried 136K).

**The knee, measured** (real captured views cut at exact sizes, production writer + validators, n=8 per cell, fixed share of the window as trigger; the floor events of the compaction calls): the evidence stays whole up to ≈0.44 of the window at 16,384 (5.6K est.: 0 of 8 calls reduced; 7.6K: 5 of 6), ≈0.58 at 32,768 (15.3K: 0 of 8; 19.8K: 1 of 5), ≈0.62 at 49,152 (29.7K: 0 of 8, 2 distilled; 35.1K: 2 of 8 reduced; 40.3K: 2 of 5) — exactly where `(window − fixed) / density` puts it, so the knee is a formula of known numbers, not a share. Triggering late harms the coder (above) and the compaction calls; triggering early only costs one earlier first fold (after a summary stands the cadence is unchanged: recompact band).

**Production-path check** (new code, no trigger anywhere; real sessions walked turn by turn until the predicate fires, then the real writer + validators; n=8 sessions per window, 2 at temperature 0 and 6 at 0.7; summary density UNMEASURED = the cold-process worst case): 16K / 32K / 49K servers: 0 of 8 / 0 of 8 / 1 of 8 compaction calls floor-reduced, the one being a session whose very first request already held a 136K-token history (nothing to predict from). Fire points at 49,152 with the live reserve: view 15.7–20.3K est., measured growth 2.2–11.2K, coder room 19.3–20.4K, evidence room 20.2K cold (30.3K once the summary density is measured at ~1.3): earlier than the old 28.9K and before the floor trims. Accepted-rate of the folds is the briefing lenses' (4 of 8 / 2 of 8 / 5 of 8 here), not this predicate's, and is tracked under the next thread.

Frame, not window, is what limits a small window: this harness's frame is ≈7.6K est. (≈9K real) so a 16,384 window has ≈2.6K est. of view room — the predicate then says "always" and the recompact band (1,333) sets the cadence; the floor drops regardless. The tail / recompact / refold sizes stay window shares: they do other jobs (the coder's live working set, a throttle against re-summarizing a sliver, a bound on the standing rollup), and the post-fold views measured above (49K: 12.2K vs room 19.7K; 32K: 12.1K vs 12.9K, dominated by the oversized newest turn the engine never folds) show clamping the tail would not change them.

---

## A small-window self-compaction briefing is often rejected (PLAN / UNFAITHFUL) — pre-existing, found while scaling the caps

Found 2026-10-30 replaying the captured ornith1.5_9b / Java coder history (session 01a162ad call 0061, 11,571
est. tokens, 25 messages) through `Loop._self_compact` against real ornith1.5_9b servers at `--ctx-size` 16,384 and
32,768 (n=8 each, 2 at temperature 0, 6 at 0.7).

With the caps scaled (windowcaps) the trigger now fires on a small window; before, the 16,384-est-token trigger never
did and the floor dropped 18 of 25 coder turns silently. Once it fires, the fail-closed lenses reject most
briefings, and **that is not caused by the scaling**: the old caps with the same trigger pinned explicitly reject
the same way.

- 16K, scaled: 3/8 accepted; rejected: retrospective lens `PLAN` 4/8, fidelity `UNFAITHFUL` 1/8.
- 16K, old caps, trigger pinned to 5,461: 0/8 accepted; `PLAN` 3/8, `UNFAITHFUL` 3/8, scope `NARROWS` 1/8.
- 32K, scaled: 0/8 accepted, `PLAN` 8/8. 32K, old caps, trigger pinned to 10,922: 1/8 accepted; `PLAN` 4/8, `UNFAITHFUL` 3/8.
- Distillation (`handoffdistill`) fired in 1 of 8 scaled 16K runs (first call only), not on every compaction: it is
  not the cause of the `PLAN` verdicts. At 49,152 the same history is rejected by the fidelity lens in both arms
  (identical wire bytes before/after), as in the original capture 0065.

**Investigated 2026-10-30 (R2) — it is not a window effect.**

- *The earlier replay was not the production path.* It replayed the captured OUTBOUND body of call 0061, which already
  carries cria's `⟦ctx:rollup⟧` user message; `selfcompact.root_text` counts that message as part of the root task, so
  the writer's "ORIGINAL TASK" block held the previous briefing (real call 0062's did not). And it ran the reasoner's
  retrospective lens, while the live service answers that lens with the system1 classifier. Rebuilt from the real
  INBOUND history (session 01a162ad `inbound-c668c47b`, cut at the same boundary a pinned trigger would use, real
  root task, writer + validators as `Loop._self_compact` runs them), n=8 per arm (2 at temperature 0, 6 at 0.7):
  16K system1 OFF 3/8 accepted (`PLAN` 4/8, scope `NARROWS` 1/8), 32K system1 OFF 1/8 (`PLAN` 5/8, `UNWRITTEN` 2/8) — the
  reported numbers reproduce — but with system1 ON (production) 16K 8/8 and 32K 7/8. Four other real sessions' views at
  the 0.33 share, n=4 each, system1 ON: 16K 14/16, 32K 10/16, and the SAME 32K views at 49,152 (:18084) 9/16 — no
  window effect. Of the sixteen system1-ON rejections (16K, 32K and 49K together): `PLAN` 6, scope `NARROWS` 5, `UNWRITTEN` 4, `UNFAITHFUL` 1; the typed lenses are the ones that carry signal (one `UNWRITTEN package.json` is a
  briefing stating the file as built that the transcript never wrote).
- *Floor reduction (a):* not at these fire points. One cold-process 16K writer body was floor-trimmed (8,007 → 5,523
  est., 21 turns, `safety` 1.8 because no summary request has been measured yet although the coder's density is
  1.17); the predicate (73570ade) now fires early enough that evidence fits whole at the floor's own density.
  Distillation fired at 16K on the cold first call; its extraction was refused 4 of 8 times for object-shaped list entries
  (`valid_extraction`, deliberate), a wasted ~800-token call and a kept-verbatim piece, not a cause of a verdict.
- *Reply cap (b):* writer replies 575–1,380 tokens, `finish_reason` stop in every sample: not cut.
- *What the reasoner's retrospective lens calls `PLAN` (c):* judged sentence by sentence, the flagged lines are the
  task's own requirements restated as commands ("Fix the threading bug and re-enable parallel workers", "Make the
  importer at least 4× faster", "Decide and implement how…"), not the extracted `latest_plan`. The scope lens demands the
  task survive; this lens refuses any imperative. A VOICE rule in the writer prompt (state the task as what was asked,
  never as orders) lifted system1-OFF acceptance on session 01a162ad (16K 3/8 → 6/8, 32K 1/8 → 4/8) but is REVERTED:
  system1 is the production arrangement, and re-measured with it ON (same real inputs, paired BEFORE = 73570ade prompt
  vs AFTER = the VOICE rule, one writer sample per cell, temp 0 and 0.7) it did not help where production runs. Paired
  accepted, all inputs (27 pairs; BEFORE 24, AFTER 23): 16K 8/8 vs 8/8, 32K 7/8 vs 6/8, 49K (:18084) 9/11 vs 9/11. Session 01a162ad alone 15/15 AFTER vs 13/15
  BEFORE (BEFORE 32K `PLAN` ×1, 49K `UNFAITHFUL` ×1; AFTER none), but the four other real sessions
  went 11/12 BEFORE → 8/12 AFTER (`UNWRITTEN` ×2, scope `NARROWS` ×2 — 32K and 49K on the same shipping-module input,
  where the AFTER briefing dropped the `GB → domestic / EU → eu / others → international` mapping that BEFORE kept
  verbatim), and the writer once leaked the rule ("The task, restated as what was asked (not as commands)"). No
  evidence the rule helps with system1 ON; one instance of it losing a task constraint; it rewrote the 49K writer.
  Open: the system1 retrospective classifier's own false `PLAN` rate on a numbered task list, measured directly on the
  briefings above, is the upstream place to look.
- *Next:* (1) the remaining `PLAN` lines are still the numbered task list — a writer that cites the task by deliverable
  instead of quoting it, tried ONLY if measured with system1 ON on all five inputs at all three windows; (2) the scope
  lens is strict on briefings that say a deliverable is "done" (session 3's three `NARROWS`); (3) `valid_extraction`
  refusing object-shaped entries wastes the cold-process extraction call at 16K — a stricter example in
  `compaction_extract` is the upstream change to try, with a fabricated-entry control.
