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

## Surfaced, NOT built — the reading step a documentation page can never close

Cycle 4 cell 18, `rust-toml-cli × ternary-bonsai`, 5% useful. `research.grounded_sources` counts a fetch as a source only when the ledger holds parsed ROUTES or response FIELDS, and every marker that fills those needs a doc that parsed as a spec-shaped object. Library documentation does not — docs.rs, rubydoc, godoc, javadoc and pkg.go.dev are HTML prose — so on any "read the library's documentation" step the ledger stays empty and `step_reading_verdict` short-circuits to `NOT_DONE` **with no model call**. The step cannot be closed however completely the page answers the task.

The coder fetched `docs.rs/toml` at call 0007 and got 7,925 characters carrying the whole API it needed — `pub enum Value`, `Table`, `from_str`, `to_string`. cria recorded it as *"HTTP 200 (this page answered, but no endpoint definitions were found in it)"*, and the step pin — *"Do ONLY this step (1 of 2): Visit crates.io to identify a suitable TOML parser crate"* — was then recited on **20 of the run's 21 coder calls**. Nine were re-fetches of pages already fetched. Zero bytes reached the workspace after call 0010.

**The design, written down and not landed.** The discriminator is a DECLARATION, the same shape the routes marker uses one kind of page over: a landing page declares no symbols, a documentation page declares many — so the guarantee `grounded_sources` exists for (run 1785804243's five HTTP 200s that defined nothing) is preserved. An extractor was written and it works on Rust and Python doc pages while staying silent on landing pages and prose. It was **removed rather than left unwired**: making it count requires a fifth ledger slot threaded through `groundtruth.fetch_facts`, `_merge_fetches`, `grounded_sources` and `_sources_block`, and a new block in every fetch result — a change to what every coder is routinely shown, which needs its own measured pass rather than a tail-end landing.

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
