# Application sweep — twenty lenses over what cria actually does

Second run of this sweep (the first was 2026-08-16). Twenty agents, one orthogonal question each, over **38,824 lines, 174 prompt files, 314 test files, 253 captured sessions and 12 days of logs (440,198 records)**. Each worked from a generated inventory of every emit site, guard, prompt and constant — including the 118 emit sites that had not fired in three days of real traffic — and each was held to one standard: **read the source, quote it, and say whether it can actually happen.**

Every lens also carried the previous sweep's findings in its area, so it reports *still live / fixed / now fires into nothing* rather than rediscovering. Findings that turned out to be deliberate are recorded as such. Several lenses came back partly empty and said so.

**Nine root fixes landed while the sweep ran** — verified by running the code, not by reading it. They are marked ✅ below and listed in full at the end.

---

## The lenses

| | lens | the question it asked |
|---|---|---|
| 1 | Dead coverage | what cannot fire, or fires into a field nobody reads |
| 2 | False statements | what does cria assert that it never observed |
| 3 | The coder's work | where does cria choose what belongs to the task |
| 4 | Truncation | where is what the model reads shorter than what cria had |
| 5 | Matchers | where is a rule keyed to one tool's wording and inert elsewhere |
| 6 | Suppressed guards | where does the failure disable its own detector |
| 7 | Divergent copies | where is one owned fact stated twice and drifting |
| 8 | Measurable waste | which tokens and calls return nothing |
| 9 | Ordering | what is written after it is read |
| 10 | Cross-harness | what silently dies outside Codex |
| 11 | Cross-language | what silently dies outside Python and Ruby |
| 12 | Tests | which tests cannot fail for a real reason |
| 13 | Prompt collisions | what does cria inject that contradicts itself in one prompt |
| 14 | Unknown as false | where does "could not see" become "is not there" |
| 15 | Refusals | is every refusal true, and does it name a route the reader has |
| 16 | Seats | what does each reasoner see versus what it rules on |
| 17 | Compaction | what silently does not survive |
| 18 | Config | which defaults surprise and which numbers nobody can justify |
| 19 | Session state | what leaks between sessions and what a restart destroys |
| 20 | Doctrine | rule by rule, where does the code disagree with the principle |

---

## The three patterns that organise everything below

### 1. The fixture is not the production shape, so the test cannot see the bug

The sharpest finding of the sweep, and it recurred in four independent lenses.

`ProbeResult.summary` is the constant `"no problems reported"` on any green run — the raw runner text is dropped at parse time. Three callers asked `is_no_tests_collected(r.exit_code, r.command, r.summary)`, so the one phrase anyone had written down (`[no test files]`) **was invisible in production for six weeks** while the regression test passed, because that test hand-built its `ProbeResult` with `summary=<raw output>`. The file records the identical trap being fixed one function down, for `tally` and `skipped`. The fix was applied to those two and not to this one. ✅

Same shape elsewhere: `tests/conftest.py` binds a `DirectView` globally, so every workspace-view test reads cria's own disk — which production never touches. `test_empty_workspace_inverts_the_reframe` passes green against a branch that **cannot fire live**, because `reframe_compaction` runs before `wsview.bind`. And `test_the_gate_output_fits_the_bound_that_judges_it` composes against an empty `TemporaryDirectory`, whose survey is 201 bytes — the test named "the whole gate fits" passes because its fixture is empty.

### 2. A mechanism keyed to state only the dead path writes

`sess.web_session` — the key every per-session web gate uses — was assigned inside `_work`, the multi-item driver. `_plan_off_session` has returned `synthetic=True` unconditionally since 2026-08-19, so the dispatch reaches `_drive_single_item` first and **every real run left it `""`**. Four mechanisms degraded with no trace, including the "that fetch was not yours" correction, which appears in **0 of 253 sessions** while the wording that blames the coder for cria's own 404 appears in 377. ✅

`GateOutcome.unran` — the one field that knows a gate section went missing — has exactly one reader, inside `_verify_after_probe`, the plan-ON gate. `loop.gate` events carrying `probes_run` per day: 2, 5, 4, 6, 3, 1, **0, 0, 0, 0, 0, 0**. Zero on every day since the survey was added to the gate. A cut gate is therefore recorded GREEN.

`GuardState.gate_git` is computed by a `sha1sum` on **every** gate round trip (~1,500 in 12 days), parsed, stored, and read by nothing — untouched since the original port six weeks ago.

### 3. The generalising fix that half-landed

Repeatedly, a rule was generalised at its trigger and left keyed to one tool at the point that decides what happens next.

- `_CODE_SHAPED` grew `::` and `[?!]` for Rust and Ruby; `_invented_code_spans` — the counter that decides whether the steer ships verbatim — did not. Ran it: `serde_json::to_string(&value)` and `ZONE_BASE.key?(zone)` both trigger and both count **0**, so the steer ships as written.
- `_tally_says_zero` was written as "the kernel-level reading" of the empty-suite question and its docstring claimed twelve runners. Ran all of them: maven, phpunit, gradle and dotnet print prose and **no count at all**, so it is structurally silent for exactly the four the docstring named. ✅
- `_SKIPPED_RE` was `(\d+) skipped` — pytest's and jest's spelling and nobody else's. Ran all six battery languages with one genuinely skipped test: minitest, node, phpunit, surefire and go each reported **0**. ✅
- `_positional_only`'s file:line pattern is line-anchored, while `proberun` renders every finding as `$ <cmd> — <path>:<line>: <msg>`. So nothing is ever classified positional, and the `prescribes` gate is asked whether a directive is prescribing `bonsai_codex_poff_1787480733` — a fragment of cria's own run directory. **7 of 11 post-fix fires are on a non-symbol**, and a PRESCRIBES answer refuses the whole steer.

---

## HIGH — live, measured, not yet fixed

### The gate result is over budget on a third of real workspaces

`plan_gate` appends the workspace survey to the gate script, so both ride home in **one** tool result. The budget that decides whether that result survives (`MARKER_OVERHEAD_BYTES = 1100`) enumerates the section echoes, the litter listing, the git digest and the offline leg — and not the survey. Its comment last changed 2026-08-14; the survey was added on 2026-08-20.

The arithmetic leaves **zero headroom**: for every plan size, `n*cap + reserve + overhead` lands exactly on the 9,000-byte bound. Run against all 87 archived run workspaces:

| task | n | median survey | max | over the bound |
|---|---|---|---|---|
| rust-toml-cli | 10 | 40,179 B | 50,362 B | **10 / 10** |
| shipping-rates-rb | 35 | 48,626 B | 50,296 B | **22 / 35** |
| handles-cli-node | 9 | 614 B | 15,333 B | 1 / 9 |
| feed-pipeline-java | 15 | 1,216 B | 1,715 B | 0 / 15 |
| cart-billing-go | 12 | 589 B | 784 B | 0 / 12 |

The two families over the bound are the two that have been running. The root is `wsview.TREE_MAX_BYTES = 48_000`, 5.3× the result cap, under a comment claiming the bounds "keep the whole survey comfortably inside a normal cap". The measured harness retention, from 401 real truncated results, is **10,212 bytes median**. It is not a static condition either: the survey starts tiny and crosses the bound mid-run, when `bundle install` or `cargo build` creates `vendor/` or `target/` — i.e. at the moment the workspace becomes interesting.

Compounding it, both `apply_survey` call sites **discard its boolean**, and `wsview` has no emit sites at all — so a survey rejected for arriving cut is invisible by construction, and the view silently degrades to never-surveyed. That is the state `_confirm_completion` fails **open** on.

### Ruby and PHP dependency trees flood the gate; JS and Python do not

`ignore.generated` proves JS install dirs and Python venvs. Nothing proves a bundler or composer `vendor/`. The per-file floors then emit one probe per gem file, and `MAX_FLOOR_FILES_PER_LANG = 100_000` is not a bound.

Measured: **26 of 35 `shipping-rates-rb` workspaces produce a gate whose sections cannot fit the result budget.** Worst case: 370 `.rb` files collected, **363 under `vendor/`**, 372 probes, a **551,045-byte** gate script, per-section budget 700 bytes against a 9,000-byte cap. Every other language: 0 workspaces over budget. The same shape reproduces for composer (426 probes, 645,956 bytes). cria owns this fact twice already — `groundtruth.INSTALL_PREFIXES` and `execcheck.entrypoints` both know `vendor/bundle` — and neither owner is the floor's.

### `mvn test` over a project with no tests reports "tests executed"

✅ **Fixed.** Recorded here because of its blast radius: all 15 archived `feed-pipeline-java` workspaces ship exactly one `.java` file and zero tests, select `mvn test`, and were telling the satisfaction judge that tests had run.

### The offline-test claim is defeated by every runner whose total counts skipped tests

`_offline_fact` compares the tally online vs offline; unequal → silence, equal → *"The same tests pass with the network switched off — nothing in them reaches a service on the internet."* That works for pytest. It cannot work for minitest, phpunit, surefire or gradle, whose totals **include** the skipped test. Reproduced with real Ruby:

```
online  : 2 runs, 2 assertions, 0 failures, 0 errors, 0 skips  -> 0f/2p
offline : 2 runs, 1 assertions, 0 failures, 0 errors, 1 skips  -> 0f/2p   EQUAL
```

The sentence appears in **5,120 captured prompts**. Separately, `0f/0p` shipped the strong sentence **170 times** — zero tests establishing that nothing reaches the network. (The skip-count half of this is now fixable: `skipped_count` reads all eight runners as of this sweep.)

### The install refusal ships with no alternative for the first nine firings of a session

`_local_install_advice` picks a route only when `toolpath.resolved(t)` names one, and `View.program` *queues* the question and returns `None` the first time. So the refusal is a full stop: *"an install must land inside the project directory … and this one would not."*

Verified in session `20260823T032555`: the first **nine** install refusals in coder prompt 0084 are routeless; the tenth onward carries a route. **580 of 3,704 renderings (16%) carry no route.** Downstream in that same session: 14 consecutive refused installs, then the escalation reasoner authored *"Stop trying to install the countries gem — it cannot be installed in this sandbox … Replace the require with a hardcoded set of EU two-letter codes."* `countries (8.1.0)` is installed on this box, and `gem install --install-dir vendor/bundle countries` passes cria's own guard.

### The install guard tests flag spelling, not destination

Any one of eight flag spellings, appended to any manager, disables the guard:

```
pip install -i https://pypi.org/simple flask     ALLOWED   (-i is --index-url)
apt-get install -y vim --root x                  ALLOWED
pip install -t ./libs requests                   REFUSED   (pip's own --target short form)
cargo install --path .                           ALLOWED   (--path is the SOURCE)
```

And the mirror image, live at call 0040 of the session above: the coder named the project directory verbatim (`gem install countries --user-dir <the workspace>`) and was told *"an install must land inside the project directory (<the same path>), and this one would not."* Bypass prevalence in 4,303 captured commands: **0**. The false refusal is what has actually cost runs.

### A rejected write's payload is replaced by cria's English, and the coder writes it to disk

`_collapse_rejected_payload` stubs any `content`/`old_string` over 400 characters with `[985 characters — this edit was REJECTED, nothing was written to <path>]`. `focustrim` records the operator's ruling on this exact shape after a corruption incident — *"There is not supposed to be any elision. It's all or nothing"* — and was fixed by **removing the call**. This site still stubs, and so does its second owner in `selfcompact`.

Live in the coder's own prompt today (858 prompt files, 1,770 occurrences, 85 coder prompts on 08-22/23), and the model reads it as content:

| capture | what the model did |
|---|---|
| `20260819T063347/0046`, `/0047` | emitted `write_file {"content":"[2254 characters — this edit was REJECTED…]"}` **twice** |
| `20260817T020431/0012` | *"The current pom.xml is: ```[1107 characters — this edit was REJECTED…]```"* |
| `20260822T001226/0078` | attributed the sentence to a **read_file** result |
| `20260819T144108/0095` | wrote `[elided 8031 chars — an EARLIER version of Importer.java]` into the file |

The em dash in the stub is `—`; the documented downstream symptom is `Importer.java:[1,20] illegal character: '—'`.

### `LoopStore._sessions` never evicts, and it is the one durable store

`_shapes` is capped on write and on load. `_sessions` has no cap anywhere and exactly one eviction site — the plan-ON `loop.done` path, which fired **0 times in 12 days**. On disk: **494 sessions, all `in_progress`, 1,015,017 bytes**, accumulating since 2026-07-27. `persist()` runs every turn and re-serialises all 494 under the lock — measured **4.08 ms to dump + 3.43 ms to write, per turn**, ≈17 GB written over 12 days for state that is 100% stale. `mark_done` is unreachable from the live path, so `shape_done()` has returned False 256 times out of 256, and the post-compaction continuation has never had that half of its evidence.

### A restart silently overwrites call captures

The capture folder name is deliberately restart-stable; the sequence counter inside it is memory-only. Counted exactly from `upstream.dump` events: **25,823 distinct capture paths written, 189 written more than once, 274 captures destroyed** across 22 session folders, one path written 11 times. This is the evidence store the project's own doctrine says to diagnose from, and every lens in this sweep was reading it.

---

## MEDIUM

- **Node is the only ecosystem whose own declared test command is thrown away.** `build_js` drops `scripts.test` when the classifier does not recognise the runner; `node cli.test.js`, `node test/lookup.test.js` are all UNKNOWN. **7 of 9 node workspaces declare `scripts.test`; 0 reach the gate; 8 of 9 get zero test probes** — the only such workspaces in the archive. Half-fixed: the warning now exists and shipped in 2,305 prompts across 42 sessions.
- **JS's undefined-name rung has never run.** `eslint` does not resolve on this box, so `program_is_installed` drops it: 35 syntax probes, 1 test, **zero lint** across 9 node workspaces. Reproduced the defect it exists for — a broken `rates.js` using an undefined name produced *"no problems reported"* from every probe cria ran.
- **Only JUnit's tally row reads the ERROR count.** A pytest run with `1 passed, 1 error` parses to `0f/1p` and reads as green; `_checks_superseded_by_coder_run` then drops cria's real cached findings. The `0 failures, N errors` shape occurs **1,749 times across 9 sessions**.
- **A green PHPUnit run has no tally at all** (`OK (2 tests, 2 assertions)` matches no row), so the passing-test-regression detector is structurally silent for PHP.
- **A failing `node --test` run yields zero findings and a YAML key as its summary** — `exited 1: name: 'AssertionError'` — while the real message and `location:` are both in the output. Java stack frames are likewise unparsed.
- **The compaction reframe cannot see an empty workspace.** `reframe_compaction` reads the view before `wsview.bind` runs, on both POST paths, so `compaction_reframe_empty` — the template whose docstring calls the alternative *"the drift ROOT"* — has fired **0 of 8,226 times**.
- **The disk-denial override runs on one compaction path.** `_briefing_disk_truth` corrects a briefing that denies a file cria can see; the harness path never calls it. Landed yesterday: a briefing said *"REVIEW.md has not yet been created"* over a listing naming `REVIEW.md (4746 B)`, and the coder adopted it.
- **cria's own ground truth is delivered inside cria's own "this is unverified" wrapper** — 1,189 prompts across 62 sessions carry a `[GROUND TRUTH …]` block pre-discounted by the compaction reframe's *"it is NOT verified ground truth, in EITHER direction."*
- **`pending_done_parts` is cleared on one exit of three**, so a satisfaction reason from an earlier turn can replace the coder's own closing text. Walked end to end on session `01a00ade`: the delivered final message was *"All tests pass, build and vet succeed"* — from a verdict whose very next gate was red, 3.5 minutes and ~35 model calls earlier.
- **`cria.tail` drops `reason=` from every non-decision record** — two copies of one field list, diverged since the first commit. 597 records affected, including every `loop.step_incomplete`.
- **The steer author is the one code-reasoning seat given no file contents and no complete listing.** 788 of 860 invocations (92%) see a touched-files-only list with no completeness clause; it calls a tool on 16%. **27 blind directives assert an absence**, the clearest being *"Create a Gemfile … as no such file currently exists in your list of files"* over a list that held 3 of the workspace's 4 files.
- **The re-orientation seat is given the compaction summary and nothing else** while being asked to state what has been built. 22 of 136 answers name a path absent from their input; replaying both current guards, **36 of 126 (29%) would be discarded** — a full model call spent and thrown away, on the one seat withheld the fact it invents.
- **`_invented_names` refuses on a sentence period and on English slashes.** `lib/shipping/rates.rb.` reads as invented when the path is right there; so do `I/O` and `trim/normalise`. **13 of the 32 invented-name refusals (41%)** are solely one of those two artifacts.
- **`listdir`/`scandir`/`walk`/`files()` ignore `_complete`** while `isfile`/`isdir` honour it. On a 420-file folded root both model-facing `list_dir` tools answer *"empty directory"* and `_workspace_is_empty` answers True.
- **`_basename_matches` checks `complete` but not `folded`**, where its sibling in `groundtruth` checks both and says why. Run against a real 1,169-file workspace with 7 folded directories: `_basename_matches('PT.yaml') -> []`, the "genuinely absent" answer, for a file that is on disk.
- **The env-preamble recognizer is two Codex tags**, and it decides which message is the task. On a Cline-shaped preamble `contextfloor` protects the banner and leaves the task droppable, and `loop.session_key` collides every conversation in one workspace onto one plan session.
- **`edit_file` is lowered to `apply_patch` on harnesses that never advertised it.** The guard asks whether the harness runs `edit_file`, never whether it has `apply_patch`. `massage.edit_to_patch` fired **0 times in 440,198 events** — on Codex the branch is unreachable, so the path exists only where it is broken.
- **The external-dir safety guard is a no-op when no `<cwd>` arrives**, and cria learns the workspace root from its own survey and throws it away: `wsview.survey_root` has one caller, inside `apply_survey`, and never reaches the session. **51 call sites** across 8 modules abstain on a missing root while the View beside them knows it.

---

## LOW / deliberate / cleared

- The advisory filter is a 20-phrase English exception list with a per-language discriminator that only reads Python syntax. Documented as deliberate; runs on every gate.
- Nine steer scrubbers have never fired in 12 days. `_steer_auth_refuted` is the expensive one — its trigger spends a reasoner call before the verdict, and the verdict has never been REFUTED.
- Four authored steer texts in `planner_steers.txt` have no reader; three dataclass fields (`research_evidence`, `exec_intent_key`, `exec_intent_reply`) have neither reader nor writer; `GatePlan.notes` is written and read only by tests; `VERIFY_MAX_CHARS` is a retired constant still cited as another constant's derivation.
- `SPILL_DIR = "./tmp/reference"` writes into the coder's workspace — 60 of 91 run workspaces contain one — against doctrine #7's flat *"cria writes only inside its own directory."* Unavoidable after #23c (cria cannot hand the model a path on its own filesystem), so the **rule** is the stale half and needs the carve-out written down.
- The literal token `cria` in model-facing text is down to **one** live site (`loop.py:6220`'s refusal-count sentence, 47 post-fix occurrences into the reasoner seat) plus the run directory that the suite harness — not cria — puts in every path.
- ~40 model-facing strings are still composed inline rather than in `prompts/*.txt`; the two largest reach 15,996 and 13,080 prompts, and the check family is also a one-owner split (the failing text is in a prompt file, the four clean/timed-out/no-signal wordings are literals).
- Every `if len(store) > N: store.clear()` bound in the codebase is dead code: max observed sessions per process lifetime is **4**, against caps of 256 and 512, because cria restarts ~53×/day.
- `[defaults] timeout_seconds` governs 8% of calls (the buffered ones); the other 92% run on a code constant. Deliberate at the wire, wrong in the docs.
- Six keys `config.py` reads are absent from `cria.example.toml`, including `[engagement] drive` — *"False = cria never drives"* — and `merge_consecutive_turns`, without which a Llama-lineage template rejects cria outright.
- `responses._REASONING_CAP = 8000` slices 11% of captured reasoning traces with no marker and no count. Display-only, but it cuts the artefact the operator's own rule says to read first.

---

## The nine fixes that landed during the sweep

| commit | what it closed |
|---|---|
| `3ff2b35` | A runner that says "no tests" in words is heard. Three callers asked the vacuous-green question of a field that is a fixed string on green runs, so go's marker was invisible for six weeks; four more runners print prose and no count, so the tally arm was silent for them too; the skip count read one runner's spelling. One owner (`says_nothing_ran`), a shape rule, and the fixture now builds its result the way production does. |
| `1a87c55` | The recovered diagnostics band dedups **records**, not lines. The one-day-old `awk '!seen[$0]++'` deleted javac's `symbol:`/`location:` from 78 of 210 errors in the only session that had run since — under a header promising the opposite. The unconditional `sed '$d'` that ate the band's last line is now conditional on there being something to cut. |
| `ab57963` | cria stops replacing a search with a fetch of an invented name. `url_is_grounded` was the module's one unbounded matcher; `sess.web_session` was written only by the driver that no longer runs, silently disabling four web mechanisms. |
| `8a4c071` | A refusal is not a file's contents — a refused whole read was being ingested as the file's bytes, including into judge prompts headed *"this is what is actually there"*, and it made non-existent files answer `isfile → True`. Plus: 23 emit sites passed a level the table does not know (or a config value), demoting **828 records** including every rumination abort; an unknown level is now the loudest, and an AST test refuses the next one. |
| `34de0b7` | The forced-answer closer asks for the key the judge declares. The satisfaction judge was asked for `{"done": …}` while declaring `satisfied` — 78 prompts, 7 replies keyed wrong, each rescued only by an inference that would have inverted a `proposed_fix: ""` into satisfied. A fail-open on completion. |
| `7c34b4c` | A listing may not outlive the look that made it. *"This list is complete — a file not listed here does not exist"* shipped **674 times** and its honest counterpart 0 times, gated on the survey's bound and on nothing about when it ran. A separate `stale` clause now also withdraws the header's "right now". |
| `97f6b8c` | Two measurable wastes: a refit that cannot shrink the body is no longer re-sent (59 refits, 59 400s, 3.2M prompt tokens), and the evidence summariser runs under the compactor's role instead of the reasoner's (85 of 85 captured bodies had reasoning on against a config that says off). |

---

## What each lens read and found correct

Recorded so the next sweep does not re-walk them: `cria/denial.py` in full; `cria/wsview.py`'s survey ingestion, truncation guard and three-valued predicates; `cria/urlgrounding.py` apart from the one hole; `probegate._strip_gate_plumbing` + `clean_gate_results` (verified 0 sentinel leaks in 167 MB of post-fix prompts); `probeparse.is_advisory` and the `_TALLY_SHAPED` family; `upstream._resolve_window` / `_prep` / the four stream backstops; `verifytools`' path containment and forced-answer ladder; `groundtruth.files_for_a_judge`; `toolmenu.focus_tools` (19,803 real events, no shell or file tool ever dropped); `shelltool`'s schema-driven argument handling; `cria/turnstats.py`; the `LoopStore` locking and the per-session lock (0 concurrent same-session turns in 19,811); the seeded-test rule's one-owner closure; `cria/toolargs.py`; `cria/searchloop.py`; `focustrim`'s payload exemptions; `editrecovery`'s escalation clock; `classify`'s cache.
