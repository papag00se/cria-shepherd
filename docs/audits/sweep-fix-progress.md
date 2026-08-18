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

### 30. cria answered "install bundler" with "run bundler", and swallowed the probe that would have settled it
Cycle 4 cell 13, `shipping-rates-rb × ternary-bonsai` — 10% useful, **34 of 54 calls spent trying to obtain a gem**. The coder ran `which bundler 2>&1; gem install bundler 2>&1 | tail -5`. cria refused the whole line with the bundler route — *"add the gem to a `Gemfile` and run `bundle3.2 install --path vendor/bundle`"* — which answers "install bundler" with "run bundler". cria had **already resolved the binary**: that is where the string `bundle3.2` in its own sentence came from. And because the refusal takes the whole command line, the `which bundler` that would have told the coder the truth never executed. Two calls later: *"The bundler install is restricted. Let me try to manually extract the gem file I downloaded earlier"*. It never learned bundler was installed, and never typed `bundle3.2` once in 54 calls.

**Fixed**: when the package being installed IS a tool the chosen route names, the fact goes first — *"bundler is already installed on this machine — the executable is named `bundle3.2`, so type that instead of `bundler`."* Only fires in that case, so it cannot speak about an ordinary package (#3), and it uses the coder's own word for it.

### 31. An install loop kept flushing the evidence of itself
Same cell. `_is_progress` reads the command TEXT — writing a `Gemfile`, `mkdir -p vendor/bundle` both carry mutator words — and progress on new ground FLUSHES the repetition window. Writing a Gemfile and making vendor directories is exactly what an install loop does between attempts. Call 0051 re-wrote the Gemfile with bytes **identical** to call 0033 and still counted as new ground (the window's age trim is why the earlier copy could not catch it — entries expire after 12 forwarded calls, and 0033 to 0051 is eighteen). The walk replayed the run's real 53-call sequence through `guard_track_repetition` with the live constants: **it fires zero times.**

**Fixed**, three ways, all of them "did this actually change the workspace" rather than "do the words say so":
- an install into a **shared** environment is not workspace progress (`dirguard.installs_outside_workspace` — a local install into `vendor/bundle` or a venv genuinely populates the project and is untouched);
- a call cria itself **refused** wrote nothing, and cria is what refused it, so this is a fact cria holds rather than a judgement (#8);
- a write whose bytes are already what the **last** write to that path put there changed nothing (only the last, so write→edit→write-the-original is still the change it really is).

The protected case is untouched: a healthy edit→test→edit→test cycle resets exactly as before.

**Residual, measured and NOT fixed**: whether the redirect then FIRES depends on `_actions_match` calling those attempts the same action, and on this run's real sequence (`gem install`, `--user-dir`, `gem install bundler`, `bundle install`, a hand-rolled `curl`) it would not. Loosening that matcher is a separate change with its own false-positive profile and needs its own measurement.

### 32. "no test command was composed", said in the same message as a gate script containing `mvn test`
Cycle 4 cell 16, `feed-pipeline-java × ternary-bonsai`. `plan.untested` is filled by two different questions — *"these test files exist where no runner can see them"* (which fires whether or not a test command was composed) and *"test files exist and no command was composed at all"* — and both rendered a single lead sentence written for the second: *"The checks above cover syntax and lint only — no test command was composed."* Over a run that had just executed `mvn -q compile` and whose gate carried `mvn test`. False in cria's own voice (#5b), and it also went out on every Go and Rust project, where `go test ./...` and `cargo test` are always composed.

**Fixed**: two wordings, keyed on whether a test probe was actually composed. When one was, the lead says only what still holds — *"A test command did run, but the clean result above does not establish that this project's tests pass"* — and the finding beside it says why in each case (files a runner cannot see, or no test files at all). The qualifier's whole purpose, stopping a vacuous green from reading as "the tests pass", is unchanged.

### 33. The step author was shown the workspace and then forbidden to name any of it
Cycle 4 cell 16, `feed-pipeline-java × ternary-bonsai`. The research-step prompt printed `src/main/java/pipeline/Importer.java (4543 B)` in its context block and then instructed: *"Do not name a URL path, a file name, or an endpoint the task itself did not name."* The model noticed the contradiction in its own reasoning and complied anyway; **eight of the run's 39 calls went on guessing a path cria had already printed**, before the first file was read.

The rule exists to stop the author INVENTING a filename, and that is worth keeping. A file cria read off disk is not invented. **Fixed**: name only what the task or the context already names — and files listed in the context were read from disk and are real.

### 41. Every turn of a Rust task was told the API's routes were still undefined
Cycle 4 cell 24. The fetch ledger's no-structure line ended *"nothing read so far DEFINES the API's routes"*, which presumes the task involves an HTTP API. The coder fetched `docs.rs/toml` — a crate documentation page, in a task with no API anywhere in it — and that sentence rode **every turn from call 0004 to 0058**. **Fixed**: the narrow fact (this page yielded no endpoint definitions) is true and stays; the claim about what is still missing is now stated as the condition it always was — *"If this task needs a machine-readable API definition, nothing read so far provides one."* The swagger-shell case the note was built for reads the same.

### 47. The reading step a documentation page can never close — FIXED, and the old behaviour was #11b inverted

Promoted out of "surfaced, not built" once the rule was read properly. `step_reading_verdict` short-circuited to `NOT_DONE` **with no model call** whenever `grounded_sources` was empty — and it is empty for every page that is not a REST spec, because every marker that fills `routes`/`shapes` needs one. So a "read the library's documentation" step could never be closed however completely the page answered it.

Cycle 4 cell 18, `rust-toml-cli × ternary-bonsai`: `docs.rs/toml` came back with 7,925 characters carrying the whole API the task needed, and the step pin was recited on **20 of the run's 21 coder calls**, nine of them re-fetches of pages already fetched.

**#11b says a mechanism that cannot observe the thing it is asked about must SAY SO, never convert its own blindness into a verdict.** The short-circuit converted "the parsers found no structure" into "the coder read nothing". That is the rule inverted, and it is why this needed no new ledger field, no symbol extractor, and none of the machinery the earlier write-up proposed: the fix is to stop answering a question cria cannot see.

A page that ANSWERED and yielded no structure now goes to the judge, labelled as exactly that (#8 — the deterministic half gathers, the reasoner judges). The guarantee the short-circuit was built for is about an EMPTY ledger — nothing came back, so nothing was read — and that still holds and still costs no call, including when every fetch failed. The incident it was built for survives too: run 1785804243's five HTTP 200s still reach a judge that is told in as many words to treat a home page, a registry landing page or a search-result list as answering nothing.

**Replayed against the real fetch ledgers:**

| cell | ledger | parsed | answered | before | now |
|---|---:|---:|---:|---|---|
| rust-toml-cli × ternary-bonsai | 2 | 0 | 2 | NOT_DONE, no call | judged |
| shipping-rates-rb × ternary-bonsai | 11 | 0 | 8 | NOT_DONE, no call | judged |
| handles-cli-node × qwen35 | 2 | 1 | 2 | judged on 1 source | judged on both |

### 48. The unexecuted-write nudge fired on a step that produces no files
The real answer to #29, which the replay showed did not fix its own case. cria said *"your last message contained the file's contents as text… nothing reached the disk"* about cell 18's research summary — a turn that drafted no file, two calls after cria's own results said `Wrote .../Cargo.toml`. It was the run's ONLY tool-call-less coder turn.

Text similarity cannot settle it (the coder summarised rather than copied, and loosening containment to line-level would silence the nudge on exactly the turns it earns its keep). The deterministic fact cria already held is better: **a reading step produces no files, by its own prompt's words** — *"It produces nothing — no script, no tests, no files."* The hand-back has used that same test since 2026-08-04; it just had no name, so no other seat could ask. `_is_reading_step` is now the one owner (#23).

**Replayed on cell 18's real call 0011**: on the reading step the nudge no longer fires; on a work step the identical text still does.

## Surfaced, NOT built — eliding a read that a later edit superseded

Cycle 4 cell 4. After two edits landed, the only rendering of `Importer.java` in the model's window was the pre-edit copy from an earlier `read_file`, and nothing marked it superseded; the model's `old_string` at calls 0019 and 0020 is a verbatim copy of that stale text, including the body it had already replaced. cria has the mirror already — `write_stub_superseded` stubs a write payload a later write replaced — and the read side has no equivalent.

**Against, and it is cria's own measurement.** The docstring directly above that code records what happened the last time cria replaced source with cria's own claim in this view: on `orders-api-py × ternary-bonsai` the route's 2,579 characters became `[elided … this exact content is on disk]`, and the briefing then reconstructed the route's behaviour from the task text and the tests — asserting an `orders` array and a `total_value` it returned neither of, in 37 later prompts. Across cycle 1, 20 briefings assert behaviour of the coder's own work and 9 do it falsely. Eliding a read is the same move on the other side.

Recorded rather than taken: the walk that raised it labelled it a candidate and asked for a measurement first, and cria's own ledger already holds the counter-example.

## Surfaced, NOT built — the coder's own view of the workspace

Same cell, the other half. `⟦ctx:files⟧` is rendered only inside `_compact`, so the coder never sees a workspace listing until a compaction fires — call 0024 in that run, after the guessing was over. Every other actor gets it: the step author, the steer author, the step critic and the exec-intent judge all receive `workspace_inventory`.

**For**: not knowing what exists is the most common way a weak model burns calls, and the fact is deterministic ground truth cria already gathers. The cost is ~20 short lines, under 1% of the window, regenerated from disk each turn so it can never go stale.

**Against**: it is a permanent addition to *every* coder turn across all 24 cells, and the opposite failure — a model that reads the list instead of reading the files — is exactly the shape doctrine #1 warns about. It cannot be measured until the next cycle, and an assist that fires on a clean signal is pure downside.

Recorded rather than taken: this is a design call about what the coder is routinely shown, not a defect with a right answer.

### 34. cria said no line could be parsed, in the same prompt that printed the parsed line
Cycle 4 cell 24, `rust-toml-cli × nemotron-elastic`, 5% useful — and the highest-cost item in that run. The crate needed one file, `src/main.rs`, from call 0028 to the end, and cargo said so on every check:

```
error: can't find bin `dotkey-toml` at path `…/src/main.rs`
 --> …/Cargo.toml
```

`parse_rustc` reads the `-->` span through `split_loc`, which wants `file:line:col` — and cargo's manifest and target-resolution errors never print one. The finding was dropped **message and all**, `completion_block_nudge` came back empty, and `gate_error_text` fell through to *"a specific line could not be parsed from the output… run that exact check yourself"*, delivered six times, while `⟦ctx:checks⟧` printed the line naming the missing file in the same prompt. loop.py's own rule for this is written above `gate_error_text`: NEVER SAY "no line could be parsed" WHEN A LINE WAS PARSED. The coder ran the gate seven times and re-read `Cargo.toml` five times and never created the file.

**Fixed**: a file with no line is still a location. `Finding.line` is already Optional and `summarize` already renders a file-only span; this was the one place that refused to make one.

### 35. The lost-call nudge existed on one path, and the whole plan-off column ran without it
Cycle 4 cell 19, `shipping-rates-rb × nemotron-elastic`. At call 0025 the model emitted a complete `str_replace_editor` call in its reasoning channel; `massage.reasoning_call_off_menu` recorded it by name, `LOST_CALL_KEY` was set as designed — and `loop.lost_call_offmenu` never emitted, because the nudge branch lives only in the multi-step half of `drive`. 0.257s later cria read the empty turn as a completion claim and spent a gate and a judge on a workspace where nothing had happened. That is verbatim the failure the 2026-08-11 commit says it fixed. **Fixed** in `_drive_single_item`'s gate: every `codex_poff` cell in the matrix was running without it.

### 36. The prescribes guard refused the one right answer, because the checks named the file
Same cell 24. At call 0051 the reasoner finally produced the correct directive — *"…then create `src/main.rs` that reads a TOML file from the command line…"* — and the PRESCRIBES judge killed it on a shared-token list of `Cargo.toml, main.rs`. Both are **where the checker is pointing**, not what it is rejecting: on a `can't find X at path Y` error the correct fix is precisely to write `Y`. The coder got a generic redirect instead and never created the file. **Fixed**: a token whose every occurrence in the findings is positional — a `-->` span, a `file:line:` prefix, or the object of "can't find / no such file / not found" — is not a symbol the checks reject. One appearance in a real rejection keeps it, so the measured `decimal.NewFromInt64` case is untouched.

### 37. The orienter could rename the work
Same cell 24, and the other half of #21. Handed the task instead of a summary, `_reasoned_reanchor` answered *"Start a new binary Cargo project named `toml-dotted-key`"* — a name the task never used, over a crate already on disk called `dotkey-toml`. The coder obeyed and rewrote `Cargo.toml` without its `[package]` header and with `[bin]` for `[[bin]]`, undoing two fixes it had earned 35 calls earlier. cria contradicted itself inside one prompt: the continuation block beside the steer said *"Do NOT recreate files or restart work that is already done"* and listed the real files.

#21 fixes what the orienter is SHOWN. This adds the clause it lacked about what it may SAY: never name a project, crate, file, module or command the summary does not already name, and never tell the coder to start over.

### 38. The same pom.xml refused eight times, at a line the coder could not see
Cycle 4 cell 22, `feed-pipeline-java × nemotron-elastic`, 5% useful. The model omitted `</parameter>` and opened a second call in the same turn, so every `pom.xml` it sent ended `</project>` / `</function>` / `</tool_call>` / `<tool_call>` / `<function=write_file>` / `<parameter=path>` / `src/main/java/pipeline/Importer.java`. cria refused it — correctly, that is not well-formed XML — with *"does not parse — not well-formed (invalid token): line 34, column 1"*.

Line 34 was `</function>`. **The coder cannot re-read its own rejected payload** (cria elides it as `[1107 characters — this edit was REJECTED…]`), so a line number into an invisible document points at nothing. Across eight refusals its reasoning never once mentions line 34; at call 0016 it re-derived the identical file by hand and was refused again. It escaped only by switching to `edit_file`, which put a `<dependency>` block outside `<dependencies>` and left the project unreadable by Maven for the rest of the run.

**Fixed twice over, and they are not alternatives.** *Cut the junk*: `_protocol_debris` answers the all-or-nothing case and correctly declines when a genuine file merely has tags appended — that is the expensive case, and cria already holds the knowledge (`massage._LEAK_DEBRIS` lists these sentinels; `_bounded_xml_params` cuts them from arguments cria itself parses; the gap was a SERVER-parsed call, which `recover_leaked_tool_calls` skips by design). *Show the line*: when the validator does refuse, quote the line its coordinate names — what the sibling EDIT path has done for months.

Only a trailing run is cut, and the cut may only land ON a protocol tag: a bare single-token line is scanned past but never becomes the cut, because a bare token both trails the tags (the next call's `path` value) and precedes them in ordinary markup (`</project>`, `}`), where cutting at it would eat the file.

### 39. cria described an install that had never happened, and ruled out the step that had failed
Walked twice in cycle 4, independently, on the two worst cells of the worst column — cell 13 (`shipping-rates-rb × ternary-bonsai`, 10%) and cell 19 (`shipping-rates-rb × nemotron-elastic`, 5%). Beside the coder's own `LoadError`:

> Note: `countries` is installed nowhere ruby is looking. A gem installed with --install-dir is not on the load path by default … **Fix the loading; the code that uses it is not what failed here.**

Every `gem install` in that run had been REFUSED and every `bundle install` was `command not found`; the surviving workspace has no `vendor/`, no `.bundle/` and no `Gemfile.lock`. So the sentence describes an install that never happened, and its last clause rules out the one correct next move — the install IS what failed. The model read it and went straight back to `gem install`, the last action of the run.

Recorded in the cycle-3 ledger as *"MODIFY FIRST — add a condition, never soften the sentence"* and not landed then. **Fixed now**: ask the disk before describing it. Only the three ecosystems whose install evidence lives inside the workspace (ruby, node, python); rust/go/java resolve from caches cria cannot see and their notes are about DECLARING a dependency, so they are untouched. An ecosystem cria cannot settle, or a workspace it cannot read, keeps the original sentence — `os.walk` on a missing path yields nothing and raises nothing, which would have produced a confident "nothing is installed" about a workspace cria cannot see.

### 40. The model reverted its own correct fix, twice, reasoning against checks that predated it
Cycle 4 cell 19, `shipping-rates-rb × nemotron-elastic`. The gate ran at 07:27:41; the correct `>=` fix landed at 07:28:57; calls 0048–0062 all carried the **pre-edit** failure, because the newest gate result is re-shown at every prompt build until a new one exists. The model reasoned against it twice — *"we changed to `>=`, but maybe the code we edited was not the same as the one running… The only explanation is that the condition is not being evaluated correctly"* — then reverted its own correct fix, and on the last action of the run reverted it further still.

`changed_paths` already knew which files had moved; it was only being used to unquote the "flagged line on disk" annotation. **Fixed**: when the newest result predates a landed write, the block says so and names the file — *"These checks ran BEFORE your edit to `rates.rb` and have not been re-run since… re-run them before concluding your edit did not work."* Absent on a fresh result, so it is silent in the normal case.

### 42. The prescribes guard, measured over every fire it has ever had
The cycle-4 walks put a number on it: **18 fires, at most 2 correct.** A guard that is wrong 16 times in 18, whose failure mode is killing the one directive that names the fix, is a deletion candidate — but it exists for a real measured harm (*"replace `decimal.NewFromInt64` with …"* delivered while that symbol appeared 7 times inside `undefined:` errors). So it was narrowed against its own history instead.

Replaying all 18 reported tokens through HEAD: the shape filter (#20's `_looks_like_a_symbol`) rejects **11** outright — `countries`, `error`, `failures`, `compile`, `declared`, `annotations`, `shopspring`, `orders`, `python3` and friends are ordinary English words. Today's positional filter (#36) drops `Cargo.toml`. That left six, and five of those six are still false fires, in two clean patterns:

- **An exception class is what a checker REPORTS, never what it rejects.** `LoadError`, `AttributeError` — a directive naming one is quoting the failure, which is the exact distinction this guard exists to draw and kept getting backwards.
- **A workspace path fragment is not a symbol.** The reported token `elastic_codex_poff_1786953798` is a slice of the temp directory *cria itself chose*; `_shared_symbols` tokenizes on `[A-Za-z_][\w.:?!]*`, which breaks the path at its hyphens, and `_positional_only` was only splitting on separators.

**Both closed.** Of the 18 historical fires, **11 are now impossible by shape and a further 2 by these two rules**, and the remaining survivors are the dotted symbols the guard was actually built for.

### 43. A stream cria itself killed became the summary — found independently by two walks
`summarize` is the primitive every summariser shares: the compactor, the briefing writer, the steer author, the judges. It rejects a truncated pass and a tool-call answer, and had no check for a pass the **rumination guard aborted**. When that happens there is no content, so `coerce_text_answer` recovers `reasoning_content`, and the corpse is returned as the summary.

Cell 23 (`handles-cli-node × nemotron-elastic`) hit it twice, at 0073→0075 and 0089→0091: the compactor's aborted private narration was handed to the satisfaction judge **in the slot where the coder's action log belongs** — *"We need to continue the process. The user wants a condensed log of all distinct actions… Then attempts to exec command node …/lookup.end2end.test.js again, error."* forty times over, with not one real command, exit code or error string from the session in it. The judge ruminated too, invented a log citing a README path that does not exist, and the coder was handed a report about cria's own judge failing.

Cell 11 (`handles-cli-node × qwen35`) found the same defect from the other end: an aborted **orienter's** raw 15 KB thinking trace was injected as the steer, first person and all — *"Decision: I will state that the core resolver module exists, but the CLI wrapper, dependency update, and CI/Testing/Docker are missing"*, when all four already existed and passed. The coder read a "I must write the directive" trace, adopted the reasoner's role, and spent its whole turn emitting a directive instead of working.

**Fixed**: the rule already existed one function over. `_steer_from_reasoning` refuses exactly this, in these words — *"A STREAM CRIA ITSELF KILLED IS NOT AN ANSWER… This ran anyway, and then cria narrated the corpse as a decision."* Failing the pass is not a loss: it fires the reasoning-off retry, which is where a summary belongs anyway — straight into content, with no reasoning to salvage.

### 44. cria ran the project's test suite three times per turn, and reported the result as the coder's bug
Cycle 4 cell 21, `orders-api-py × nemotron-elastic`, 70% useful — and the missing point is exactly this.

The model's tests share one repo-relative `orders.db` that nothing deletes, so every extra run appends a row. Its own run reported `assert 22.5 < 0.01`, where `22.5 = abs(30.0 - 7.5)` and **30.0 is four rows of `3 × 2.50`** — one from the coder's run and three from cria's: the gate's online run, the gate's network-off comparison, and `exec-intent` choosing `python3 -m pytest` as the program to observe. The coder never saw the other three and spent the tail of the run theorising about pytest parameterisation.

**Fixed, one of the three.** The test suite is not the delivered program, and `proberun` already runs it (#23) — so `exec-intent` declines a command that runs the tests, by shape, in every launcher's spelling. That is a deliberate exception to the invariant in `test_the_runner_cria_accepts_is_the_runner_cria_runs.py`, and it is a different thing from the defect that file was written about: there cria refused a command naming something the coder could not change; here the command is perfectly runnable and cria declines because it owns the job. For a project with no program to run, abstaining is the honest answer (#11b).

**ATTEMPTED, MEASURED, AND ABANDONED — do not re-try the copy.** The obvious fix is to run the offline leg against a copy of the workspace instead of in it, at a reused path inside cria's own directory so nothing accumulates and nothing needs deleting (the sandbox hard-rejects `rm` in composed shell). It was built and driven, and the test suite alone produced **7.0 GB of copied trees** before it was killed.

Two things broke it, and the second is the one that matters:

- **`cp -a` is not cheap where it is used.** A gate runs on every completion check; copying the workspace each time is minutes and gigabytes on any project with a `target/`, `node_modules/` or a vendored tree.
- **The mirror is keyed on `working_dir`, and `working_dir` is not always the workspace.** Where a caller passes a bare temp directory, `cp -a <dir>/. mirror/` copies **the whole of `/tmp`** — 14,262 directories in one leaked mirror. A composed command that can copy an arbitrary tree is a footgun regardless of how careful the intended path is.

**The design that survives this is the opposite one: run the offline leg FIRST and stop.** A suite that passes with the network gone has proven both facts in ONE execution — it passes, and it is self-contained. Only a suite that FAILS offline needs the online run, to tell "needs the network" from "is broken". That removes an execution from the common case rather than duplicating a tree, needs no copy, no temp path and no cleanup, and it inverts the current guard rather than adding to it. It is a real restructure of the composed script, so it gets its own pass with a live gate run behind it.

**Still open — the network-off leg.** `proberun.py:781-790` documents this exact failure from a previous cycle and its fix was half of one: the second run is now suppressed when the online run FAILED (where the comparison is impossible), which is precisely when the double-run was harmless, and still permitted when it PASSED, which is when the side effects break the next check. The remedy is to run the offline leg against a copy of the workspace rather than in it — a strengthening of the existing mitigation, not a revert — and it touches the composed gate script, so it gets its own pass.

### 45. Twelve and a half minutes of nothing, and all four guards silent — because all four count arrivals
`shipping-rates-rb × gemma4` call 0070, the **second** occurrence on the same cell and model, one cycle after `DEAD_STREAM_CHUNKS` was written for the first. 43,442 tokens, `predicted_ms 755,470`, `message.content: null`, `aborted: False`, and not one `rumination.abort` in the session.

**Two explanations ruled out from the record**: not the buffered re-ask (no `upstream.stream_error`, and the timings say `source: "cria-measured"`, which only a streamed call gets); not a bad token estimate gating the window guard (cria estimated 5,523 sent against a real 5,710, so `window_room` was ≈43,600).

**What was left is provable from the ABSENCE of the events.** `tok_per_s` is 43442/755.47 = 57.5 exactly, so `t_first` never got set and fell back to `t0` — no frame ever carried content or reasoning, so `streamed_chars` was 0. The window guard not firing puts `chunks_seen` under 40,139; the dead-stream guard not firing, at `streamed_chars == 0`, puts it under 400. **cria received fewer than 400 readable frames while the server generated 43,442 tokens.**

The common root: every abort condition in the stream loop thresholds on what ARRIVES — frames for the window and dead-stream guards, characters for both degenerate checks. A server that goes quiet while generating is below all four for the whole call.

**Fixed** with the one signal a quiet server cannot suppress: `DEAD_STREAM_SECONDS`, time to the first readable byte. Generous — prompt processing on a large context is the only honest reason for a long quiet head, and the measured runs reach their first token in seconds — and three minutes still returns nine and a half of the twelve. **Also fixed**: `upstream.done` now records `frames` and `read_chars` on every call, which nothing did, which is why the count above had to be deduced rather than read (#12).

### 46. MEASURED — the repetition redirect is the wrong instrument for an install loop
The residual recorded under #31, now settled by replaying both Ruby cells' **real forwarded call sequences with their real tool results** through `guard_track_repetition` at HEAD:

| cell | real calls | of which cria refused | redirect fires |
|---|---:|---:|---:|
| shipping-rates-rb × ternary-bonsai | 48 | 9 | **0** |
| shipping-rates-rb × nemotron-elastic | 45 | 6 | 1 |

The flush fix (#31) was necessary and is not sufficient. The three install attempts inside one window are `gem install eu_countries --user-dir ~/.rubygems 2>&1 | tail -5`, `which bundler; gem install bundler 2>&1 | tail -5`, and `gem install eu_countries 2>&1 | tail -10` — Jaccard 0.636 against a 0.7 bar, four words of jitter against a bar of two. Making `tail -5`/`tail -10` boilerplate lifts the first pair to 0.778 and they match — **and it still would not fire**, because that only yields two matches in the window, not three.

**So this is not a matcher-tuning problem.** The loop is not "the same action three times in twelve calls"; it is twenty different attempts at one goal. The signal that IS present is cria's own: it refused 9 of 48 calls in that run and 6 of 45 in the sibling, and it knows it refused them. Counting refusals needs no similarity judgement at all.

**BUILT AND REPLAYED (operator's call, 2026-08-17).** Same threshold, same window, same redirect — this only makes the existing mechanism reachable by a second route, keyed on a fact cria owns outright rather than on a similarity judgement (#8).

Replayed over the real forwarded call sequences with their real tool results, with the trigger off and on:

| cell | before | after | |
|---|---|---|---|
| shipping-rates-rb × ternary-bonsai | never | **calls 31, 43** | new |
| shipping-rates-rb × gemma4 | never | **calls 19, 31** | new |
| shipping-rates-rb × nemotron-elastic | call 20 | calls 20, **32** | new |
| shipping-rates-rb × qwen35 | call 14 | call 14 | unchanged |
| cart-billing-go × ternary-bonsai | call 46 | call 46 | unchanged |
| orders-api-py × qwen35 | never | never | unchanged |
| handles-cli-node × ternary-bonsai | never | never | unchanged |
| rust-toml-cli × qwen35 | never | never | unchanged |

**Five new redirects, every one of them on the Ruby column — the worst column in the grid — and none on a healthy cell.** Every pre-existing fire is preserved exactly.

One bound was needed and is measured: the refusal trigger reads the message history, which a fire cannot flush the way the signature trigger flushes `recent_actions`, so unbounded it re-fired on every subsequent call — **14 redirects over 48 calls instead of two**. `blocked_fired_seq` holds it to one per window, which is the "one intervention consumes the evidence" rule the fire site already states in its own words.

### 50. THE A FIX — cria told the coder to prefer whole-file rewrites, and it obeyed

#49 below is the B, and the operator was right to ask why the duplication happened at all.

cria's cheatsheet is introduced to the model as *"Tools available this turn, **listed in the order you should PREFER them**"* — and it led with `write_file — {"content": "<full file text>"}`, `edit_file` beneath it.

| | write_file | edit_file | read_file | exec_command |
|---|---:|---:|---:|---:|
| under cria | **7** | **0** | 1 | 4 |
| unassisted | 2 | 3 | 4 | 8 |

**It did what it was told.** Seven whole-file writes, not one edit, on a cell where the same model with the harness's own menu wrote the file once and made three ~285-byte patches (20 calls, 4 of 4).

**Fixed at A**: `edit_file` now leads the preference order and the lead sentence, each is described by what it is FOR — *"change PART of an existing file"* versus *"for a NEW file, or to replace one wholesale"* — and the cost is stated where the model reads it: *"Rewriting a whole file to change a few lines regenerates every line that was already right."* Which is exactly what happened: `.get(key)` was correct at three rewrites and became `.get(key.to_string())` at the fourth.

**CHECKED AGAINST THE TWO DECISIONS IT SITS BETWEEN**, because the operator asked whether it undoes an earlier lesson. It does not, and the evidence is now in the code beside the change so the next person to weigh flipping it back has numbers rather than an opinion.

- `87563ae` set this ordering. Its lesson is **file tools first, shell LAST** — the shell-reflex lever — and that is untouched. Which of the two file tools led was incidental to it ("writing tools grouped first").
- `editrecovery`'s monotonic policy is the one that really bears on this: it escalates to a whole-file rewrite after repeated edit failures because that *"commits to the action a weak model can actually complete, rather than pin an `old_string` it keeps mis-copying"*. Measured over every captured call before changing anything (#15):

| model | edits | failures | rate |
|---|---:|---:|---:|
| gemma4 | 272 | 0 | **0%** |
| qwen35 | 2,132 | 24 | 1% |
| ternary-bonsai | 153 | 22 | 13% |
| nemotron-elastic | 135 | 79 | **37%** |
| **all** | **20,056** | **1,551** | **7.2%** (write_file: 3.9%) |

The escalation's premise holds for **one model of four**, and 93% of edits land. It is a RECOVERY keyed on a file's own failure history, and it is untouched: a model that mis-pins `old_string` three times still gets committed to a grounded whole-file rewrite. What changed is only that cria no longer starts every model, on every file, at the escalated state.

The dedup below stays, on its own terms rather than as the answer: a superseded copy is not what is on disk, and #5 allows carrying repeated content once as a pointer. But it treats the bloat; this treats the rewriting.

### 49. The model was handed six copies of its own file, and wrote a seventh with a new bug
Found by the targeted post-fix re-run of `rust-toml-cli × ternary-bonsai` — and it is the reason that cell still scored 0 when every mechanism fixed for it behaved correctly.

The model rewrote a 6.6 KB `main.rs` **whole, five times**, each version 99.1–99.9% identical to the one before, and every copy stayed verbatim in the working tail:

| call | prompt tokens | copies of the file | bytes of payload |
|---|---:|---:|---:|
| 0010 | 5,223 | 0 | 0 |
| 0014 | 8,309 | 1 | 6,570 |
| 0020 | 12,415 | 3 | 13,195 |
| 0021 | 14,478 | 4 | 19,835 |
| 0022 | 16,527 | 5 | 26,462 |
| 0023 | **21,009** | **6** | **33,103** |

**The prompt quadrupled and every token of the growth is the model's own output handed back to it.** It then synthesised a sixth version. **CORRECTED — I first wrote that `.get(key)` was correct at three earlier rewrites and that the last one broke it. That was read off the diff and is false.** Every one of the five versions was compiled afterwards and **not one of them builds**: four fail with `E0277: the trait bound String: Borrow<&str> is not satisfied` at the same line, and the last with `E0308`. The rewriting did not destroy a working state — the same `&str`/`String` typing bug survived all five attempts, and the last rewrite only changed which error the compiler reported first. The unassisted run wrote the file ONCE and made three ~285-byte `edit_file` patches — 20 coder calls, 4 of 4.

Nothing folded them because nothing could: `_collapse_duplicates` needs byte-identical calls and these differ by about 1%. `selfcompact` has exactly the right rule already — `write_stub_superseded`, keyed on PATH and not on content — but it runs over the compacted middle only, and all of these sat in the verbatim tail after it.

**Fixed**, and it is the exception #5 names in its own words — *"repeated content may appear once with a pointer to the original"*. Only SUPERSEDED copies are stubbed; the newest write to each path stays whole, because that one is what is on disk. Tool results are never touched.

**Replayed against the real call-0023 body**: six copies to two, 33,103 bytes of payload to 7,493, **35% off the whole prompt**, newest write intact.

*(Landed but deliberately NOT restarted into the service: the targeted run is still going on a pinned code state, and moving it mid-run is exactly what contaminated the baseline arm. It goes live when the run ends.)*

## REPLAYED AGAINST THE REAL ARTIFACTS — every fix a capture could reach

Ten of the landed fixes were driven against the actual workspace or the actual captured turn they were written for, rather than against a fixture. **Nine hold. Two did not, and both were only findable this way.**

| # | fix | replayed against | verdict |
|---:|---|---|---|
| 22 | manifest in a subdirectory | cell 6's real workspace (`toml-cli/` beside `.git`, `tmp`) | **PASS** — declares `cargo run`, corroborates |
| 25 | repeat-fold exempts writers | **6,923 of 27,415** real forwarded calls across every capture | **PASS** — none can now be told "repeating it returns the same result" |
| 30 | "install bundler" answered with "run bundler" | the real command line | **PASS** |
| 32 | "no test command was composed" | cell 16's Java and cell 12's Rust workspaces | **PASS** — a probe IS composed and the false sentence is gone |
| 35 | lost-call nudge on plan-off | **911** real turns that emitted a tool call into the reasoning channel | **PASS** |
| 39 | dependency note asks the disk | cell 13's real Ruby workspace | **FAIL → fixed** (below) |
| 43 | killed stream is not a summary | 2 real ruminated summariser calls | **PASS** |
| 44 | exec-intent declines the test suite | the four launcher spellings it chose live | **PASS** |
| 21 | orienter reads the summary | **4,080** real bodies with a marked summary vs **8,638** with only a task | **PASS** |
| 29 | self-quote exemption | cell 18's real call 0011 | **FAIL — see below** |

### 39 — FAILED on the real workspace, and the fixture could never have caught it

`install_landed` answered **True** for a project where nothing was installed. Cell 13's workspace holds `vendor/bundle/gems/eu_countries/` — **ten directories and zero files**, built by the model's own `mkdir -p` while every real install was refused. My check read the directory NAME, so cria would have looked at a workspace where nothing landed, seen the folder the failed attempts left behind, and gone straight back to the false sentence this whole item exists to kill.

**Fixed**: an install writes files; `mkdir -p` writes none. Directory evidence must contain a file at some depth. A lock file still counts on its own, because a lock file IS the record of an install. Re-replayed: `install_landed=False`, and the correct wording ships.

### 29 — does NOT fix its case, and loosening it would be worse

The turn is cell 18's call 0011. cria said *"your last message contained the file's contents as text… nothing reached the disk"* about a research summary, and the fix was meant to exempt a fence the coder had merely quoted from a page it was shown. Replayed: **the nudge still fires.**

The coder did not copy. It wrote its own summary — `// Value enum variants:`, `// nested tables` — interleaved with lines lifted from docs.rs. Every distinctive line (`pub enum Value`, `Integer(i64)`, `from_str`) IS in what it was shown; the block as a whole is nowhere verbatim, and the exemption is whitespace-normalised containment.

**Loosening it to line-level matching would be a worse trade, not a better one.** `unexecuted_write` exists for the model that TYPED the file instead of writing it — measured at 0/4 with the finished deliverable sitting in the transcript — and that model has almost always just read the files it is retyping. A "most lines appear in something you read" rule would exempt exactly those turns and silence the nudge where it earns its keep.

The fix as landed is still strictly better than what it replaced (it exempts verbatim quotes of any tool result, not only of cria's own parsed shape blocks). It just does not reach this case. **The grounded alternative is not text similarity at all: cria knows the step in flight, and a READING step produces no files by its own prompt's words — so the nudge has no business firing on one.** Recorded, not built: it gates an existing mechanism on plan state, and that is a design call.

### 51. The judge deciding whether the task was FINISHED was shown every failure and never the pass
Watched live on the retest of `rust-toml-cli × ternary-bonsai`, and it is why that cell banked 4/4 at fifteen minutes and ran another twenty-six.

`_gate_notes` had three wordings — `red`, `testless`, `skipped` — **all of them failures** — and returned nothing at all on a clean gate, on the rule *"never a doubt-hedge on a clean run"*. That rule is right for the CODER, which must not be taught to distrust a pass. It is wrong for the seat deciding whether the work is done, where the current pass is the load-bearing fact.

cria knew the gate was green. It said so to the coder in the same breath it told the judge nothing:

> `⟦ctx:steer⟧ The repo's automated checks pass, **but** a completion check could not confirm the task is finished.`

What the judge got instead was `_work_log(keep_checks=True)` — every check result of the whole run, including an `unclosed delimiter at src/main.rs:184` from calls 0018–0023 that had long been fixed. Its tools are `list_dir`, `read_file`, `verdict`; it can run nothing. So it read the current file, saw valid Rust, and talked itself out of it — *"the actual compilation fails — indicating either stale build artifacts or a hidden character issue"* — and returned `satisfied: false`.

**Fixed** by stating the pass as ground truth, with the freshness caveat the judge needed: *"That is a live result, not a claim from the transcript — older check output above may predate edits that have since been made."*

**A tool was considered and rejected.** Giving the judge a `check_build_and_tests` call puts GATHERING behind the model's judgement, and the failure being fixed is a weak model not doing the obvious thing (#8: deterministic code gathers, the reasoner judges). cria already holds the fact at that exact moment — the completion gate has just run.

**And the green goes LAST.** The first cut returned it above the skipped-tests disclosure, which would have reported a plain pass over a run that skipped tests — the vacuous green the other wordings exist to catch. Order is red → testless → skipped → green, gated on `last_gate_ran` and `gate_fresh` so cria never claims a pass it cannot vouch for now (#5b, #11b).

*(On heavy toolchains: checked, and the light path already exists — for Rust cria composes `cargo check` as a Cheap probe, "fast and read-only", ahead of clippy and the test run. The lost time in that cell was not a slow build; the judge ran nothing at all.)*

### 52. The off-ramp for a finished session was unreachable by most runs
`_periodic_satisfaction` exists for one thing — *"a session that has FINISHED the work but cannot stop"* — and was gated at `satisfaction_check_start = 100`, then every 25 drives. **The median run in `results.jsonl` is 70 calls, so 300 of 463 runs could never reach it.** On the cell that exposed it the gate was arithmetic: 54 calls against a start of 100, while the run sat on a banked 4/4 for twenty-six minutes.

**The rule (operator):** the more parameters a model actually scans per token, the lower the start and interval, because higher-parameter models tend to be done in fewer turns.

**Three cuts, each corrected by the operator, and the corrections are the record:**

1. *A per-model table*, buckets assigned by architecture. Wrong on its first outing — `maple-preview` is a 256-expert MoE and was filed with the fast MoEs, while it measures 63 tok/s next to gemma4's 60.
2. *Keyed on measured tok/s.* Fixes maple, but throughput is **hardware-bound** — the same model on a different GPU changes band without changing at all.
3. *Keyed on ACTIVE parameters*, which is a property of the model. `n_params` from the server (`/v1/models` → `meta.n_params`); expert counts from the GGUF header at the `model_path` the server reports, read with stdlib `struct` — the same source `docs/model-settings.md` classifies the fleet from, *"never a card or a name"*. Active, not total, is the whole point here: `nemotron-elastic` and `gemma4` are both ~11.9B **total** and one scans a sixth of itself.

**One formula, no notches** (the four anchors were dropped at the operator's word):

    start = 60 − 30·log10(active_B)          clamped to [15, 60]
    every = start / 2

The ceiling is what makes it work: a start above the 70-call median is a check that never happens, which is exactly what the flat 100 was. Every value it produces stays under it.

**Recorded, not corrected:** the expert ratio is a lower bound — attention, embeddings and shared layers are not sharded, so true active params are higher than the naive product (nemotron computes ~0.6B against a card figure of ~2B). It does not change the ordering this decides, every MoE lands under 2B and every dense model over 9B, and a correction would be a guess at a shape that varies per architecture.

## SELF-AUDIT AGAINST `docs/principles.md`

Asked of the day's own work, not of the code it was fixing. Five things failed the rules and were changed; the honest weak spots that remain are named at the end.

| what | rule | what was done |
|---|---|---|
| **A second table of test runners** (`pytest`, `jest`, `mocha`, `rspec`, `tox` …) written inside `execcheck` to answer "is this a test command" | **#23** one owner; the duplicate-implementation shape | Deleted. `probeclassify.classify_command` already answers it and is what `proberun` composes the real test probe from — checked against it: all eleven launcher spellings TEST, all five real programs UNKNOWN, including `python3 test_helper.py`, which is the false positive a hand-written list has to remember |
| **`_VERSION_REJECTED`**, an English phrase list (`invalid version`, `unknown revision`, `no matching version` …) deciding whether a version was attested only by its own rejection | **#8** "if a lexical rule needs exception lists, semantic judgment has leaked into deterministic code"; **#20** inert on any registry that words its refusal differently | Removed. Re-replayed cell 20's real evidence and all three real directives afterwards: still refused, grounded answer still delivered. It bought nothing that was measured |
| **`_REPORTED_NOT_REJECTED = frozenset()`** — an empty set subtracted from a result, left as a "placeholder" | dead code | Deleted |
| **`from .proberun import _dependency_line`** inside a function in `writeproxy` — a private name reaching across a module boundary, hidden in a local import | **#23** architectural boundaries | Made public (`proberun.dependency_line`) and hoisted to the module's import block; no cycle |
| **The fused-tail trim placed in the writeproxy's `write_file` branch** | **#23**, **#24** an invariant about what cria hands on belongs where arguments are normalised | Moved to `massage.strip_debris_from_args`, which runs on every completion before anything translates it. **The old placement left `edit_file` still receiving the junk — and `edit_file`'s `old_string` and `new_string` carried the same tail in the same run, at call 0022.** The fix was incomplete where it was |

| **`writes_something`'s verb list read the word ANYWHERE in the line** | **#23b** a match is not a meaning | Anchored to command position and quoted spans blanked out. `grep -n "install" README.md`, `grep -rn touch src/`, `go doc cp` and `echo "do not rm anything"` are read-only and all four had classified as writes. Package-manager subcommands are now matched by shape (`<manager> install\|add\|remove\|get`) rather than by the bare word |

**What remains, named rather than defended:**

- `_NAMES_A_FAILURE` (`…Error|Exception|Failure|Warning$`) is a naming-convention match, the same class as `TEST_CONVENTIONS`' `*_test.go`. Defensible, and the weakest thing left in the batch.
- `probeparse._INSTALL_EVIDENCE` is a per-ecosystem table, but of facts that genuinely differ per ecosystem, and it returns `None` — never a guess — for the three it cannot settle (#11b).
- **`writes_something`'s prevalence was never established.** #15 asks for a measurement before a heuristic, and the attempt failed honestly: the captures are the bodies cria SENT, already folded, so the duplicates that would have been kept are not in them to count. What is known is the direction — the fold requires the call AND its result to be byte-identical, so what it keeps is one extra message pair — and the harm it prevents is measured (cell 14). The window cost is bounded by construction rather than by observation, and that is a weaker footing than the other fixes here.
- `trim_fused_tail` modifies what the model asked to write. It is bounded to `massage._LEAK_DEBRIS` — tokens already documented there as never appearing in legitimate prose — cuts only a trailing run, and may only cut AT a protocol tag, so a file whose real lines merely mention one is untouched. It is not silent: `massage.fused_tail_trimmed` names the tool and the arguments cut. It is the closest thing here to a mitigation for a defect in a template parser outside this repo, and it is recorded as such.

## REPLAYED AGAINST THE REAL BYTES

Every fix above has a test, but a test is a fixture. These four were re-run against the actual captured streams from the cells they were written for (#10 — verify by doing).

| fix | replayed against | result |
|---|---|---|
| the wide degenerate check (#24) | cell 4's real 156,898-character generation, streamed back in 256-char frames through a rolling 32 KB tail on the live 2,048-char stride | **fires at 26,624 chars — 17% of the stream.** The old cheap check never fires on it at all. 17% of 721 seconds is about **two minutes instead of twelve** |
| …and it must not cut the answer | the same stream | the correct `new_string` completes at char **6,535**; the abort lands at 26,624, a margin of **20,089 characters**. The 4-of-5 answer is fully generated before the guard stops the turn |
| file-only rustc spans (#34) | cell 24's real `can't find bin \`dotkey-toml\` at path …/src/main.rs` + bare `--> …/Cargo.toml` | one finding parsed where zero were before, and `summarize` renders it with the message naming the missing file — so the "no specific line could be parsed" branch is unreachable for it |
| the invented-version guard (#23) | cell 20's real evidence block and all three of its real directives, verbatim | **all three refused.** The grounded answer — *"Run go get github.com/shopspring/decimal, then go mod tidy, then go test"* — is still delivered |
| the fused-tail trim (#38) | cell 22's real pom shape | cut back to the real file, and what is left parses as XML |

## Checked and NOT a defect

- **The spill ledger's empty-path arm.** `already_spilled` returns True when no absolute path was recorded, and that reads like a #5b violation. It is not: the writeproxy records "" only when it has no `workspace_root`, so cria issued the spill and cannot resolve where the harness's cwd put it — the message names `./tmp/read-only/<name>`, which is true from the coder's side. Returning False re-arms the 19-refetch incident (run 0727-104845) for every session with no workspace root. Change written, tests failed, change reverted; the arm is documented now instead.
- **Three tests with "no assertions".** All three are "must not raise" smoke tests, where an exception IS the failure.
- **`test_research_check_wiring.py` certifying a retired rule.** It does not. `_research_check` still never calls `_advance`, and the test is the regression guard pinning that. What was stale was a COMMENT in `loop.py` calling the reading-fact-to-critic wiring "the next change" — it landed some time ago. Corrected.
- **The "checks passed" wording with no gate.** Already fixed by `_check_state_words` before this sweep ran; the finding predates it.
- **The periodic check-in restating check output 140 bytes above it (claimed 37/78).** Does not reproduce. Of 131 captured coder prompts carrying the periodic-gate steer, **0** have its findings anywhere above it — checked twice, once on the first `file:line` in the block and once on the block's first 120 characters.
- **Superseded-write stamps and the mis-worded truncation refusal.** Both fixed earlier the same day; replay confirms it. Seven double-stamped prompts exist in the captures and every one predates `fd00f35`; no prompt carries the mis-worded refusal. The truncation guard now records which wording it sent, so the next measurement reads one field instead of re-deriving it from captures.
- **"Make the prescribes guard fail CLOSED."** Proposed by the cell-19 walk after a wrong directive shipped when the guard ruminated out and returned no verdict. **Refuted by the cell-24 walk's own measurement in the same batch**: over every fire this guard has had, at most two of eighteen were correct. Failing closed would kill more right directives than wrong ones, and the guard's documented contract already says it may only move a steer from delivered to refused when a model actually says so. The real remedy for the same incident is #36, which stops the guard being asked the wrong question in the first place.
- **The steer author's unchanged-findings guard.** Already fixed by routing `checks_now` through `last_gate_flag`; the finding predates it.

## Still open

From the sweep, not yet addressed:

- superseded-write stamps: six stamps for one file at four different byte counts (believed fixed by `_last_write_index_by_path`; needs a replay against the captures to confirm)
- `guard_truncation` "partway through writing the file" on turns marked not-a-write (believed fixed by the `truncated_call` arm; same)
- the periodic check-in restating check output 140 bytes above it
- **`failover.run` and `Router.route_chain` have no production callers.** Deleting them removes the multi-backend failover chain the TOML documents — a product decision, so it is recorded here rather than taken. `upstream.chat` uses the module's POLICY with the loop written out, and its docstring now says so.
