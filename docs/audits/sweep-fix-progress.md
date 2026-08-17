# Sweep fixes — running ledger

Working through [`application-sweep.md`](application-sweep.md). Each entry: what was wrong, what the evidence said, what landed. Every fix ships with tests proven to fail on the old code, and the full suite green before commit.

Newest last.

## Landed

### 1. The compaction retry was grounded worse than the pass it replaces
`_harden_compaction_reply` re-asks for the briefing when the first reply came back empty, truncated, or as a hallucinated tool call — and composed that retry with no workspace inventory, while the first pass passes one. It also derived the session key twice. **Fixed**: both grounding facts threaded, key derived once.

The gate plan was threaded into `compaction_request` at the same time (it was the one caller of four that dropped it), and **recorded as inert**: a raw gate blob does not reach that call, because `___CRIA_GATE_` is an anchor marker and both callers strip anchors from the summarizer input. 0 of 70 real self-compact prompts carry one.

### 2. The harness-compaction detector had never fired — not rarely, never
`loop.history_rewritten`: **0 events, ever**. `route.compaction`: **139** in the same window. 256 persisted shapes, all `sid:`-keyed, **0** pending. Four mechanisms hang off that boolean, so a gate result destroyed by a compaction was simply gone.

The premise was wrong. "Compaction REPLACES the conversation root" is one way to rewrite a history and it is not Codex's: Codex keeps every user message, the original task among them, and drops the assistant/tool items behind them. What changes is the LENGTH — and `observe_shape` was already being handed `n_messages` and storing it without ever comparing it.

Measured across 141 real sessions: inbound length dropped **108 times, all 108 after a compaction**, no false positives. 56 of the 60 compacting sessions show it; the drops are 144→4, 172→4, 169→4. **Fixed**: both signals kept. The continuation planner was corrected to match — it was handed the root as "the harness's summary", which under Codex's shape is the original task.

### 3. A gate cria READ was thrown away when the turn returned through a different door
`guard_probe_steer` reads the same probe result the completion gate reads — same call id, same plan — and recorded none of it, then returned the steer. So a gate that went green→red on a redirect or wheel-spin turn left `last_gate_red` False and `gate_fresh` True, and the completion backstop, the satisfaction judge, the rollup override and the steer author were all answered with the PREVIOUS gate. Failing open toward "done" is the one direction #13 forbids.

Three readers of one fact, two writing it inline and the third writing none — **fixed by extraction**: `record_gate_state` is the only place a reading becomes state. A fourth reader turned up while wiring it (`guard_periodic_result`, omitting `last_gate_ran`) and was folded in, keeping its one real difference: a periodic check-in must not set `gate_fresh`.

A follow-up commit deleted a private redness function this fix had itself introduced — `gate_error_text` already existed and is better.

### 4. The window is a measurement, not a constant
When `/props` cannot be read, cria commits to `_FALLBACK_WINDOW = 8192`. **52 floor runs happened against it: over-budget on 52 of 52, 934 protected messages destroyed** across 6 sessions — while the real window was 49,152, and the server was answering every one of those calls and reporting the real token counts back in `usage`.

Erring large is recoverable (`_overflow_refit` re-preps once against the server's own count, 47 of them in the same window). Erring small is silent and permanent. **Fixed**: `_calibrate` raises the window to what the server demonstrably fit, and `_overflow_refit` adopts the `n_ctx` the 400 states — which it was logging and discarding.

The runaway-abort guard was gated on `_window_final`, which answers "stop probing", not "is this number real", so it was off before the first probe and forever after a fallback. **Fixed**: gated on `_window_guessed`.

Its test module asserted the rule and never drove the path — eight tests, all `inspect.getsource`, constant values and arithmetic on literals, all green while the guard had never once fired and 4 of the 14 runaway calls (43,873 / 42,673 / 40,720 / 38,025 completion tokens, every one totalling exactly 49,152) happened AFTER it shipped. Rewritten to stream real SSE frames.

### 5. `_failed_edit_ids` guarded a function that has never existed
`hasattr(editrecovery, "is_edit_failure")` with a substring fallback — the attribute has always been missing, so the fallback WAS the rule (#4). **Fixed**: keyed on `EDIT_MARK`, which every edit-failure directive carries. Costs nothing today (the two rules agree on all 9,248 captured matches) but `old_string` is an ordinary token and reading any file that documents the edit tool would have collapsed the coder's own payloads. The test hand-typed a fixture the production path cannot emit; it now builds them with `editrecovery.compose`.

### 6. The name rode into a command the coder reads
`_COMPILEALL_SKIP_RE` listed `.cria` among its skip directories, and the coder reads the gate's command line — **2,050 captured coder prompts** carry it. It was also dead: cria never writes into the workspace (#7). `_named_gap` composed "What cria's own checks currently report" as an inline f-string (#17 and #22 in one line); latent, 0 captured prompts.

Rule 17 was tested over the prompt FILES only, which is why both survived. **Fixed**: the test now drives `probediscovery.discover` and `syntax_floor_candidates` over a fixture project and asserts over every composed argv element.

### 7. `loop.spin_probe_result` recorded a literal
`spoke=True` was hardcoded, so the log said "spoke" on **121 of 121** occasions and could not have said anything else (#12). **Fixed**: records who authored the steer and whether it carries ground truth. Swept the other 41 literal booleans in emitted events; the rest are one branch of a two-branch fact.

### 8. One copy of a repeated payload in the coder's view
Rule 5's first exception is de-duplication, and cria had the machinery pointed at exactly one thing: the fetch ledger. Replaying every captured coder prompt (6,614) through the new fold: **882 of them (13%) carry a byte-identical payload twice or more; 2,088,194 bytes, roughly 522K tokens.** Largest groups: cria's own refusal re-earned verbatim (352), a source file read twice (216), a spec file read twice (130), cria's own edit directive (126), one fetched page delivered twice (150).

Newest copy wins; n pointers plus one full copy, so the repeat count survives. Never an assistant turn, never a system message, never an anchor.

### 9. A judge's proposed fix cleared a lower bar than a steer
`proposed_fix` is authored text the coder acts on and faced one guard — the invented-route check — while an authored steer goes through all of `_grounded_steer_or_none`. **134 proposed fixes reached the coder across 41 sessions**; replayed through the steer guards, 10 are dropped for naming a URL, among them `https://github.com/guyp/decimal`, a repository that does not exist. **Fixed**: the evidence the judge itself saw is threaded to all four call sites, so a URL it legitimately read still goes through. No model call added.

### 10. dirguard judged tokens before establishing they were a command
Replayed over every captured refusal, each with its real workspace root: **51 distinct / 1,225 occurrences refused before, 31 / 733 after — 20 distinct / 492 occurrences (40%) that never should have been.**

- A **parameter value is not an access**: a weak model wrote a tool signature as a shell command (`exec_command cmd="go mod tidy", …, shell="/bin/bash"`) and cria refused it for the interpreter in the last parameter. Nothing there is changeable — the string was never a shell command (#5b). 9 distinct, 229 occurrences.
- A **suffix on an unresolved expansion is not a path**: `ls $(go env GOPATH)/pkg/…` contains no path the coder wrote, so whether it lands inside the workspace is unknowable (#11b). 11 distinct, 263 occurrences.

Everything the guard is for still holds.

### 11. One owner for "is this a test file"
`execcheck` kept a private regex in which `Test`/`Tests` had to END the stem, so JUnit's prefix convention `TestImporter.java`, `ImporterTestCase.java` and jest's `__tests__/` all read as ordinary source — while `TEST_CONVENTIONS` listed all three by name. In execcheck that decides whether a workspace has a program at all. **Fixed**: the classifier moved beside the table it reads; both callers defer. `conftest.py` is now correctly not a test.

### 12. The steer author's private-thinking section was never filled
`author_steer` took a `reasoning_window=` and rendered five prompt lines plus an authority-list entry around it. No production caller ever passed one — its only producer was `_record_reasoning`, deleted with the flail detector. Every real steer carried the header, the instructions for reading it, and "(not captured for this trigger)". **Removed**, completing that decision rather than reversing it.

### 13. `Upstream(context_window=)` promised a TOML key that did not exist
Its docstring says the configured value is authoritative — "`context_window` in the toml" — and there was no key, so the path was reachable only from tests. On a box where /props cannot be read cria had no way to be *told* the answer; it committed the 8,192 fallback instead. **Wired** on `[defaults]`, documented in `cria.example.toml`, `0` = discover.

### 14. The shell tool was matched by a list of six names it happened to have met
Gemini CLI's `run_shell_command` and Cline's `execute_command` are in no such list. On either, `find_shell_tool` returns None (the plan loop declines every turn), the writeproxy has no lowering target, and **`focus_tools` DELETES the tool** — anything in none of its three sets is dropped. cria would take the coder's shell away for having an unfamiliar name. **Fixed**: matched by name shape (#18), checked against all twelve tool names in the captures.

### 15. `go test` never printed a count, so the deleted-test signal was mute on Go
`passing_test_regression` is the one signal that catches a coder destroying working code, and it reads the runner's own tally. `go test` without `-v` prints one line per PACKAGE and nothing per test, so the tally was empty and the detector correctly stayed silent — forever. probeparse's own table already said "go test -v · one `--- PASS:` per test": the parser expected the flag, the composer never sent it. **Fixed**; `-count=1` untouched.

### 16. A green gate that composed no test command said nothing
`undiscoverable_tests` reports test files a runner will NOT see. A `package.json` with no `scripts.test` and no jest config yields zero test probes while `lookup.test.js` sits there with a perfectly good name — so it stayed quiet, and the gate reported "no error-class problems" with no qualifier. **Fixed** by disclosing the other half of the same question. No runner is invented: `node --test` stays out of the floor table for the reason already recorded there, and a test pins that.

### 17. The completion note claimed verification when nothing had verified anything
`guard_gate_verdict` returns None for a green gate AND for one that could not run. The note read that None one way in both cases, and shipped the same claim on the no-shell path where no gate is composed at all. **Fixed**: composed at release from `last_gate_ran`, both wordings in prompts/.

### 18. dirguard judged tokens before establishing they were a command
See #10. Replayed over every captured refusal: **492 of 1,225 occurrences (40%)** were a parameter value or the tail of an unresolved `$(...)`.

### 19. 37 test modules could silently skip their own last classes
A class defined after `unittest.main()` does not run when the file is executed directly; `test_writeproxy.py` had two guards. Under pytest everything was collected, so the suite was honest — but a check that silently does not run is indistinguishable from one that passes, which is this whole sweep's theme. **Fixed** in all 37, with a meta-test so it cannot drift back.

### 20. A coverage test hid a rename behind a `hasattr` fallback
`test_the_living_replan_passes_the_sessions_ledger_through` widened its scan to the whole `Loop` class when the method could not be found, so it would have passed on some other call site's line. **Fixed**, plus the link it could not see (`_replan_tail` → `reassess_remaining` → the judge).

### 21. The post-compaction orienter was handed the original TASK and asked what had been built
From the cycle-4 walk, and it is the same root cause as #2 wearing different clothes. When the harness compacts the coder's history away, `_reasoned_reanchor` asks a reasoner to say what already exists and what remains. The summary it passed was `_history_root(messages)[0]` — the first user message that is not env context, which under a harness that keeps its user messages is the **task**. So the reasoner got a list of requirements under a prompt saying *"the working history was just compacted into the summary you are given… state what has already been built"*, and answered the only way that question can be answered from a task: by reading requirements back as accomplishments.

Fired three times on `feed-pipeline-java × qwen35`. The reasoner said so in its own reasoning — *"Since the summary is not provided… I am in a bind"*, *"If I output a message claiming I know what was built, I am hallucinating"* — and guessed anyway. cria injected the guess as a four-item "Remains to Fix" list whose every item was already written and passing; call 0365 answered with *"Let me redesign the solution"*, deleted `incrementSkip(parsed.reason)` and broke `messy_feed_handled`. The cell was 5/5 at the fifteen-minute floor and finished 4/5.

**Fixed**: the summary is the turn carrying `CONTINUATION_MARKER`, which `reframe_compaction` stamps in whichever shape the harness rewrites — replaced root or appended turn — so it is found in both and found *nowhere* when no compaction reached this turn. That last case is the one that must not be asked (#11b), and it now takes the canned reanchor, which claims no knowledge of what was built. The prompt additionally forbids filling a gap **inside** a real summary, since a summary that omits what remains puts the reasoner in the same bind on a smaller scale.

### 22. The manifest was only ever looked for at the workspace root
From the cycle-4 walk. `manifest_commands` read `root` and nothing below it, so a model that starts a Rust project the normal way — `cargo new toml-cli` — put its manifest one directory down and cria concluded the project declares nothing.

Cell 6, `rust-toml-cli × gemma4`: a complete, correct, working CLI judged **95% useful**, and cria's live-execution marker published *"no manifest in this workspace declares cargo run"* with `toml-cli/Cargo.toml` sitting right there. False (#5b), and it reaches the coder — the previous member of this class cost a run outright, the coder answering *"The context says cargo run is not an entry point. Let me check the actual state of the workspace"* after having run it successfully.

**Fixed** by reading `probediscovery.inventory`, which already owns "where are this workspace's projects" (bounded depth, vendor trees skipped) and is what the gate composes its probes from — so the two halves of cria stop disagreeing about where the project is (#23). Not a Rust special case: Maven, Gradle, Go with a `cmd/` dir and every monorepo nest the manifest as a matter of course. What cria will EXECUTE is untouched — still `_runnable` plus `_SHELL_META`.

### 23. cria told a coder, four times, to paste a version number it had made up
From the cycle-4 walk, cell 20 (`cart-billing-go × nemotron-elastic`, 1/5 strict, 15% useful) — and it is the single most expensive false fact found so far, because it cost the whole cell.

The checks said, verbatim: `cart.go:8: missing go.sum entry for module providing package github.com/shopspring/decimal (imported by cartsvc); to add:` / `go get cartsvc`. The steer author answered with a Go pseudo-version it invented — **`v0.0.0-20240817123456-001`**, whose timestamp is the day the run happened — and made it the instruction: *"replace it with the exact line `require github.com/shopspring/decimal v0.0.0-20240817123456-001` … Do this now with the edit_file tool."* It then diagnosed its own defect and committed it again in the same directive: *"Stop editing go.mod with invalid version strings … run `go get github.com/shopspring/decimal@v0.0.0-20240817123456`"*.

The coder obeyed, wrote pseudo-version after pseudo-version, and reached the wall with nothing that compiles. The real fix was one grounded word — `go get github.com/shopspring/decimal` — sitting in the error message cria had already read.

**Fixed**: `_invented_version` joins the grounding family (`ungrounded_urls`, phantom path / field / symbol, false line citation) inside the one gate every steer path funnels through. A version is not a judgement the author is entitled to make — it is a fact about a registry it cannot see — so a version-shaped token that appears **nowhere in the evidence cria gathered** refuses the steer whole. Matched by shape, not ecosystem: three-or-more dotted numbers, a `v`-prefixed number, or a version after `@`, which is semver, Go pseudo-versions, gem, wheel and Maven alike.

**Blast radius, measured**: of the **71 distinct steers cria delivered across cycle 4's 24 runs, 2 contain a version-shaped token at all**. What it blocks is the FIRST fabrication; once the coder pastes it, the version is genuinely on disk and a later steer quoting it passes, correctly. Cell 20's cascade was four steers and needed only the first stopped.

### 24. The model wrote a 4-of-5 answer, then repeated one block 22 times, and cria threw all of it away
The most expensive single finding of the campaign. Cycle 4 cell 4, `feed-pipeline-java × gemma4`, shipped **0/5**.

Inside the first 8% of one generation the model composed a complete, correct commons-csv rewrite. The walk extracted it from the capture and ran the task's own verifier against it: **4 of 5** — 34.3× speedup, 4 worker threads, 8 runs giving 1 distinct result, clean `mvn compile`, only `REVIEW.md` missing. It then emitted the same 6,664-character `old_string` block twenty-two more times.

`degenerate_tail` reads a 2,048-character window and needs three whole repeats inside it, so the largest unit it can see is **682 characters**. This stream is not periodic inside any 2,048-character window, so the check correctly returned False for all 40,389 frames and the only guard left was window exhaustion — which fired **721 seconds later, 74% of the cell's wall clock**, and discarded the entire generation.

**Fixed** with a strided wide check. Two things make it work where simply widening the window would not: it is **anchored at the end** (the last 512 characters are a probe, its previous occurrence gives the candidate period, which is then verified across three whole repeats — `_smallest_period` asks whether the WHOLE string is periodic, and the real answer still sitting in the window is exactly what makes that say no), and it is **strided** (KMP over 32 KB on each of 40,000 frames is not affordable; once per 2,048 new characters is ~76 evaluations). The cheap per-chunk check is untouched. It fires at ~33 KB of stream instead of 157 KB — about two minutes instead of twelve. Same three-whole-repeats rule; the module's docstring records the last time this bound was raised, from 8 characters to 682.

**And the notice stopped guessing.** `rumination_guard_window.txt` said *"That almost always means one write was too big for a single turn"* — false here: the aborted call was `edit_file`, its payload an ordinary 6.3 KB, and it had already finished. The model's next ten calls switched from one whole-file write to six piecemeal edits rebuilt from memory, and that is where the fabricated `setSkipInitialNewline` / `getHeader()` / `newNode()` came from. A notice that cannot know which call overran must not say (#5b) — the same rule as `anchor_noline` beside it.

### 25. The repeat-fold told the coder its writes could not have changed anything
Cycle 4 cell 14, `cart-billing-go × ternary-bonsai` — and it rewrites that cell's story. `focustrim` folds repeated identical calls under a note saying the call *"has told you everything it can — repeating it will return that same result"*, which is true of a reader and false of a writer. It landed on a repeated `write_file` and then on a `sed -i`, and the coder drew the only conclusion the note supports:

> *"the write_file tool seems to be caching the old content. Let me try a different approach"* / *"the sed command is not working because the file content seems to be cached or something"*

From that turn on it wrote its Go source through `python3 <<'PYEOF'` heredocs — the writes cria's syntax floor never sees. A `\t` swallowed inside the Python string turned `taxed` into `axed`, and bash backtick substitution ate the struct tags. **The cell's famous typo is an artifact of a write cria drove it to**, not something the model typed.

**Fixed**: `shelltool.writes_something` is the one owner of "could this call have changed the workspace" — by shape, not by a list of coreutils — and `focustrim` exempts anything it says yes to, the same way it already exempts cria's own gate probes. Generous on purpose: saying "this might have changed something" costs one un-folded pair of messages; saying it about a writer cost the cell.

### 26. The identical-edit message named the wrong argument
Same cell. `⟦ctx:edit⟧` said *"old_string and new_string are identical — this edit changes nothing, and you cannot pin the exact current text. Read the file, then make one targeted edit."* The second half is false: `old_string` matched the file exactly, and only `new_string` failed to differ. The coder obeyed the wrong half four times over — read the file, resubmit the identical pair, read, resubmit — and its own `grep -n` came back with the exact bytes it had been pinning all along. **Fixed** in `editfail_reports.txt`: say that `old_string` matched and `new_string` is what has to change.

### 27. The periodic critic was told no checks had run while cria held four red ones
Cycle 4 cell 18, `rust-toml-cli × ternary-bonsai`. `_periodic_step_check` composes no gate of its own and said so by handing the critic `probe_digest_none` — two lines asserting *"SYNTAX FLOOR: did not run"* and *"PROBES: none ran"*. Two calls earlier cria had handed a reasoner four red cargo failures under *"GROUND TRUTH FROM THE REPO'S CHECKS"* (`src/main.rs:31: type annotations needed`, from clippy, check and test alike). Two judges, two calls apart, opposite ground truth — whichever is wrong, cria said it (#5b). **Fixed**: composing no gate is not the same fact as no gate having run, so when the session holds a reading it is passed through the `probe_red` slot and the "none ran" digest is omitted.

### 28. "a line you remember that is not shown here is not in the file" — inferred from a six-line window
Cycle 4 cell 4. The `anchor` edit-failure message ended with a claim about the WHOLE file drawn from six lines of context, and it is false whenever `old_string` is longer than that window. The coder's copy was ~110 lines; its first forty matched the file exactly — which is what *"first differs at LINE 41"* means — and its opening line sat at line 21 of the file: remembered, not shown, and present. Told the opposite, it re-sent the byte-identical edit and the run ended. **Fixed**: say what the divergence index actually proves — everything before line N matched, from line N on it does not — which is both true and more useful, because it tells the coder which part of its copy to keep.

### 29. The self-quote exemption was inert for every page that is not an API spec
Cycle 4 cell 18. `_injected_fence_texts` read one slot — `fetched_pages[url][2]`, the parsed response SHAPES — filled by a REST-spec reader. The coder fetched `docs.rs/toml`, 7,925 characters of the crate's real API, and cria's own `⟦ctx:facts⟧` recorded *"HTTP 200 (this page answered, but no endpoint definitions were found in it)"*: routes empty, shapes empty. Its next turn summarised what it had learned, quoting fifteen lines of `pub enum Value { … }`, and cria answered *"your last message contained the file's contents as text, but no write tool call was made, so nothing reached the disk"* — false on both halves, since cria's own tool results two calls earlier said `Wrote .../Cargo.toml` and `Wrote .../src/main.rs`.

That was the run's **only** tool-call-less coder turn — its one chance to be judged and advanced — and it was spent on `read_file` to check cria's claim. **Fixed**: the haystack is now every tool result in the conversation (pages fetched, files read, command output). If a fenced block already appears verbatim in what the coder was handed, it is a quote whatever kind of page it came from (#20). The comparison is unchanged; it was being handed an empty haystack.

## Checked and NOT a defect

- **The spill ledger's empty-path arm.** `already_spilled` returns True when no absolute path was recorded, and that reads like a #5b violation. It is not: the writeproxy records "" only when it has no `workspace_root`, so cria issued the spill and cannot resolve where the harness's cwd put it — the message names `./tmp/read-only/<name>`, which is true from the coder's side. Returning False re-arms the 19-refetch incident (run 0727-104845) for every session with no workspace root. Change written, tests failed, change reverted; the arm is documented now instead.
- **Three tests with "no assertions".** All three are "must not raise" smoke tests, where an exception IS the failure.
- **`test_research_check_wiring.py` certifying a retired rule.** It does not. `_research_check` still never calls `_advance`, and the test is the regression guard pinning that. What was stale was a COMMENT in `loop.py` calling the reading-fact-to-critic wiring "the next change" — it landed some time ago. Corrected.
- **The "checks passed" wording with no gate.** Already fixed by `_check_state_words` before this sweep ran; the finding predates it.
- **The periodic check-in restating check output 140 bytes above it (claimed 37/78).** Does not reproduce. Of 131 captured coder prompts carrying the periodic-gate steer, **0** have its findings anywhere above it — checked twice, once on the first `file:line` in the block and once on the block's first 120 characters.
- **Superseded-write stamps and the mis-worded truncation refusal.** Both fixed earlier the same day; replay confirms it. Seven double-stamped prompts exist in the captures and every one predates `fd00f35`; no prompt carries the mis-worded refusal. The truncation guard now records which wording it sent, so the next measurement reads one field instead of re-deriving it from captures.
- **The steer author's unchanged-findings guard.** Already fixed by routing `checks_now` through `last_gate_flag`; the finding predates it.

## Still open

From the sweep, not yet addressed:

- superseded-write stamps: six stamps for one file at four different byte counts (believed fixed by `_last_write_index_by_path`; needs a replay against the captures to confirm)
- `guard_truncation` "partway through writing the file" on turns marked not-a-write (believed fixed by the `truncated_call` arm; same)
- the periodic check-in restating check output 140 bytes above it
- **`failover.run` and `Router.route_chain` have no production callers.** Deleting them removes the multi-backend failover chain the TOML documents — a product decision, so it is recorded here rather than taken. `upstream.chat` uses the module's POLICY with the loop written out, and its docstring now says so.
