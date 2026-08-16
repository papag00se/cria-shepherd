# Language bias in cria's assists — the six-language battery

47 findings from reading cria's own source against 24 assisted runs in Ruby, Go, Python, Java, JavaScript and Rust. Every location was verified by reading it. Severity is what the walks actually showed.

| severity | count |
|---|---:|
| costing-points-now | 30 |
| inert-but-latent | 10 |
| cosmetic | 7 |

## costing-points-now (30)

### install refusal text (⟦ctx:denied⟧ on a global install)
`cria/prompts/external_install_refusal.txt:1 (fired from cria/dirguard.py:119)`

**Assumes.** That the only package manager whose install can be refused is pip, and the only project-local escape hatch is a venv. The whole remediation is pip/venv/pytest: "`pip install -e .` installs YOUR OWN project… `python3 -m venv .venv && ./.venv/bin/pip install <pkg>`, then run with `./.venv/bin/python`".

**Seen.** The trigger regex at cria/dirguard.py:87 explicitly matches `(?:gem|cargo|go)\s+install`, apt/dnf/brew and npm -g — five ecosystems whose refusal is answered in Python. Walk: ruby BASE arm calls 0014 and 0017; with no ruby-viable route shown the model tried two more installs, hit `bundle: command not found`, and hand-rolled the EU country list — the one thing the task forbade.

**Kernel fix.** A refusal must answer in the same ecosystem it refused. The guard already knows which manager it matched; the remediation must be selected from that match, not from one fixed language. One refusal text per manager is still a per-language list — the kernel is "name the project-local destination this manager supports, or say plainly that there is none".

### exec-intent user prompt — the run-command constraint
`cria/prompts/exec_intent_user.txt:9`

**Assumes.** That a program is a FILE you name on a command line. "the command must name a file from the list, spelled exactly as it appears there, and never a file that is not on it." In cargo, maven, npm, rake and go the run command names a TARGET (`cargo run`, `mvn test`, `npm test`, `rake test`, `go test ./...`), and the file it executes is either compiled or never named.

**Seen.** cria/execcheck.py:456 (_NOT_A_PROGRAM) strips .toml/.json/.md/.lock/.xml from the list before the prompt sees it, so a cargo/maven/npm project's only legitimate run target is deleted and then forbidden. Walk: rust 0016, node 0026/0030, ruby 0083 — cria executed no rust, node or ruby program in any of the three runs, and on rust the reasoner concluded "No `config.toml` is listed".

**Kernel fix.** An entry point is whatever the project's build system says runs, not a path that exists on disk. Resolve the run target through the manifest that is present, and never assert a command must name a listed file.

### workspace-inventory completeness clause, reused over a filtered listing
`cria/prompts/workspace_inventory.txt:10 (`complete = This list is complete — a file not listed here does not exist in the workspace.`)`

**Assumes.** That the listing the clause is attached to is unfiltered. It is true for the critic's inventory and false for the exec-intent one: cria/execcheck.py:445 copies non-entry lines (including this footer) verbatim while dropping every data/manifest extension, so an absolute "does not exist" claim ships over a list that was deliberately pruned.

**Seen.** cria/execcheck.py:445-455 — the footer is preserved by `out.append(line)` for lines that do not match _INVENTORY_ENTRY, while entries ending in _NOT_A_PROGRAM are skipped. Walk: rust 0015/0047 — the model reasoned "Looking at the list, I don't see a `config.toml` file listed" and the live-execution check died there; same drop hid pom.xml/README.md on java and discounts.json on go, each time stamped complete.

**Kernel fix.** A completeness claim belongs to the code that produced the list, not to a shared fragment. Any transform that removes entries must also strip or restate the claim — a filtered list may never say "complete".

### gate ground-truth banner handed to the satisfaction judge
`cria/prompts/gate_notes.txt:13 (`testless = [GROUND TRUTH] The checks passed but NO tests were actually executed (0 collected / no test probe ran)`)`

**Assumes.** That a test runner reports "collected". "0 collected" is pytest's collection vocabulary; minitest says "9 runs, 9 assertions", node's runner says "# pass 13", go prints per-test PASS lines, JUnit prints "Tests run:".

**Seen.** Injected into the judge's highest-authority slot at cria/loop.py:2241/3483/3728. Walk: qwen35 node 0113/0139/0163/0166/0172/0178 carried six separate "# pass 13 / # fail 0" results directly above this banner; gemma4 ruby 0114 and ternary-bonsai ruby 0062 stamped it over three passing minitest runs. The judge answered satisfied anyway, so the banner bought nothing and asserted a falsehood.

**Kernel fix.** Say what cria actually knows — "cria's own gate ran no test command" — never what the runner reported, because cria did not run one. Vocabulary borrowed from one runner turns a statement about cria's coverage into a false statement about the repo.

### self-compaction briefing rubric
`cria/prompts/selfcompact_summary.txt:14-18 ("Do NOT restate the API's endpoints, routes, or response fields… they are durable facts that travel separately and are re-stated in full, from the real fetch, in every turn")`

**Assumes.** That there is always a fetch and always a separate durable channel carrying it. On a task with no external source the clause forbids the briefing from carrying information that no other channel supplies, and it tells the model an "API" is in play when none is.

**Seen.** Static prompt text, no conditional — it renders on every self-compaction. Walk: ternary-bonsai python task with no external source at all; three plain local Python files were rendered as documents with parsed "response fields" and the briefing was fenced off from route information that nothing else provided.

**Kernel fix.** A do-not-repeat rule must name the channel that actually holds the fact, and must be conditional on that channel existing. "Do not restate what the durable ledger already carries" is the kernel; "the API's endpoints" is one instance of it.

### research read-ledger — schema and judge
`cria/prompts/researched_facts.txt:6-8; cria/prompts/research_done.txt:18; cria/prompts/research_done_user.txt:7`

**Assumes.** That everything read is an API spec. The ledger's only two fields are `routes = Endpoints read:` and `shapes = Response fields read:`; the judge is told "The routes and fields it needed are in the list" and the user turn is headed "parsed from the documents themselves". A local source file, a Cargo.toml, a Rakefile or a CSV has no routes and no response fields, so a real read is either unrepresentable or misrepresented.

**Seen.** cria/groundtruth.py:275 loads exactly these three labels; cria/research.py:170 gates the whole judgement on this ledger and returns NOT_DONE when it is empty. Walk: ternary-bonsai node — a read that 404'd was recorded as a real document ("response fields it defines: 253 chars read from disk", the length of two "No such file" lines) and step 1 was closed DONE at 0007 on that phantom entry; same model on python spent three calls judging a plain file-reading step against a spec-fetch rubric.

**Kernel fix.** The ledger's unit is "a source was read and here is what it yielded". Routes and field names are ONE yield shape; the record must be able to hold a file's content, a schema, a manifest or a `--help` without pretending they are endpoints — and an error body is not a document.

### persistent fetch record, no-structure note
`cria/prompts/fetched_facts_sections.txt:55 (`no_structure`)`

**Assumes.** That every page fetched was fetched in order to learn an API's routes, and that whatever it returned is still in the transcript. "no endpoint definitions were found in it — that status is a fact about the REQUEST, not about what the API returns; whatever the page returned is in the transcript".

**Seen.** Walk: gemma4 ruby 0090, 0092, 0101, 0105, 0107, 0114 — repeated on every injection for the whole range, against the EU's list of member states on a Ruby shipping-rates task with no API, no routes and no endpoints. The second half is also false there: the page was spilled to a file by cria's own web_fetch path, so it is NOT in the transcript.

**Kernel fix.** An entry in a fetch ledger should say what the page WAS and where its content now lives, not what kind of definition it failed to be. And a note may never claim content is in the transcript when cria's own spill path moved it to disk.

### authored research step, known-source variant
`cria/prompts/research_step_known.txt:1 (wired at cria/research.py:231)`

**Assumes.** That naming an external source is enough for the coder to reach it. The prompt says "read the external source (named below)" and the source handed in is a bare hostname (cria/research.py:225: `A SOURCE THE TASK NAMES: {domain}`) — no scheme, no retrieval verb. "Read X" in a workspace means open the file X.

**Seen.** cria/research.py:231 selects this prompt whenever `first_domain_in(task)` matched. Walk: ternary-bonsai node 0002 → 0003 — the step emitted was "Read api.handle.me and identify the task-specific names, structures, and requirements needed before coding"; the coder took it as a workspace path and burned three calls on `No such file or directory`.

**Kernel fix.** A step that sends the coder to a source must carry the source's KIND, so the retrieval verb is unambiguous — a URL is fetched, a path is read, a tool is asked for `--help`. cria knows which one it detected; withholding it makes the step ambiguous exactly where a weak model guesses.

### no-tests-found line appended to ⟦ctx:checks⟧
`cria/prompts/no_tests_found.txt:1 (rendered at cria/probegate.py:493; {{FINDINGS}} comes from cria/probediscovery.py:1005-1007)`

**Assumes.** That a negative result from cria's own framework-keyed discovery is a fact about the repository's tests. The prompt converts "my matcher found nothing" into a verdict spoken to the coder: "If the task calls for tests, that is not done yet." The matcher it trusts is keyed to `*_spec.rb`/RSpec and `*.test.js`/jest-vitest (TestConvention rows at probediscovery.py:1005-1007).

**Seen.** Walk: gemma4 ruby 0092 through 0114 and qwen35 ruby (49 injections) emitted this over a minitest suite the coder had run green (9 runs / 0 failures, later 24 runs / 0 failures). nemotron-elastic ruby: the coder believed it verbatim — "rspec expects *_spec.rb. That's why they didn't run" — and spent roughly ten calls (0161-0183) doubting whether its own tests could execute. On node the coder COMPLIED, renamed to `*.test.js`, and the probe still never ran it.

**Kernel fix.** Discovery must key on the repo's declared test entry point (the Rakefile task, the package.json script, the build file's test target), not on one framework's filename convention. And a discovery MISS must be reported as a gap in cria's coverage, never as a statement about whether the work is done.

### live-execution corroboration — README requirement
`cria/execcheck.py:206-210 (`if not in_readme: return False, f"the README documents no command that runs {tok}"`); rendered through cria/prompts/exec_markers.txt:12`

**Assumes.** That the task asked for a README documenting how to run the program — cria/execcheck.py:157's own docstring says so outright: "The task asked for a README explaining how to RUN it". That is the ada-handles deliverable list, pinned into a general check: a project with no README can never corroborate a run.

**Seen.** corroborate() requires the command to appear in README text, on disk, AND be file-shaped — all three. Walk: nemotron-elastic node 0034 produced "because the README documents no command that runs tests/handle-lookup.test.js" in a workspace that had no README at all and a package.json test script; ruby/go produced the sibling "no entry point by its language's convention". Every completion judgement in those three languages was made blind to whether anything ran.

**Kernel fix.** Corroboration should draw on whatever run declarations the project actually has — a manifest script, a build target, a documented command — and the absence of one source should weaken confidence, not veto the run. A named deliverable of one task must never become a precondition of a general mechanism.

### live-execution entry-point extraction
`cria/execcheck.py:180-192 (`program_token`)`

**Assumes.** That the program in a command is the first argument containing a dot or a slash — the `python script.py arg` shape. The comment at line 191 ("`cargo run`, `go run .`, `npm start` — the project itself is the target") shows the build-tool case was known, but its fallback sits AFTER the loop, so it is unreachable whenever any argument carries a dot or slash.

**Seen.** Read the function: for `cargo run --quiet -- config.toml server.port`, `--` is skipped as a flag and `config.toml` matches `"." in basename` → returned as the program. Walk: rust 0016 — "the delivered program was not run, because config.toml is not an entry point on disk", while cria's own inventory one call earlier listed `target/debug/toml-cli (16078000 B)`. Same mechanism read `node lookup.js <handle>` as a shell pipeline on node.

**Kernel fix.** Resolve the run target head-first: if the leading token is a build/task runner, the target is the project and the remaining tokens are its arguments. Scanning arguments for a filename cannot distinguish an input datum from an executable.

### Ruby test discovery — the whole language's test story is keyed to rspec
`cria/probediscovery.py:1006 (TEST_CONVENTIONS ruby row) and cria/probediscovery.py:759-765 (build_ruby)`

**Assumes.** That a Ruby repo's tests are rspec: files named *_spec.rb, run by `bundle exec rspec`. Minitest (test/test_*.rb driven by a Rakefile) is not in either table, so it cannot be searched for and cannot be composed.

**Seen.** Ran select_completion_probes on a real minitest tree (Rakefile with FileList["test/**/test_*.rb"], lib/rates.rb, test/test_rates.rb): the ONLY candidates are `ruby -c lib/rates.rb` and `ruby -c test/test_rates.rb`, and undiscoverable_tests returns ['No rspec tests were found — to be run they must be named *_spec.rb.'] — byte-identical to what all four walkers quoted. With a Gemfile added, the single test candidate becomes `bundle exec rspec`; `rake test`, `rake`, `ruby -Itest test/test_rates.rb` are never composed by anything.

**Kernel fix.** A language's test convention table holds ONE framework per language, and the same row is used for three different jobs (what to search for, what to run, what to tell the coder). Any language with two mainstream conventions (ruby: rspec + minitest; python: pytest + unittest; java: junit + testng) silently loses the one that isn't listed. The kernel fix is one row PER CONVENTION, not per language, with the sentence naming the convention that actually matched nothing.

### Ruby ecosystem detection — Rakefile is inventoried and then consumed by nobody
`cria/probediscovery.py:341-342 (detect_ecosystems), :66-70 (PRIMARY_MANIFESTS), :105 (RELEVANT_EXACT), :83-86 (the comment that admits it)`

**Assumes.** That a Gemfile is what makes a directory a Ruby project. Rakefile, Makefile, Justfile and Taskfile are recorded as evidence and then dropped — the module comment says so outright: 'recorded as evidence but no builder consumes them — do not invent make/just/task probes'.

**Seen.** On the Rakefile-only minitest tree, project_types() == [] — no ecosystem at all, so no lint and no test candidate is even attempted; the gate is `ruby -c` and nothing else. This is the file:line answer to 'why did no ruby test ever run': not a wrong command, no command. probeclassify ALREADY recognises the right one — classify_command('rake test') returns TEST/task-alias/85 via TASK_RUNNERS at probeclassify.py:78-84 — so the knowledge exists on the recognition side and is unreachable from the composition side.

**Kernel fix.** A declared task runner IS a manifest: any file that names build/test targets (Rakefile, Makefile, Justfile, Taskfile, package.json scripts) should make the directory a project and should be able to supply a probe, because the repo's own declared entry point beats any framework guess. Today only one ecosystem (JS) can turn a declared script into a probe; the other four task-runner formats are inert data.

### Maven compile probe — the one ecosystem with no tier≤1 check
`cria/probediscovery.py:714-722 (build_jvm pom branch) vs :708-713 (the gradle branch immediately above it)`

**Assumes.** That `mvn test` plus `mvn checkstyle:check` is enough. The gradle branch gets a BuildCheck (`gradle check`), rust gets `cargo check`, go gets `go build ./...`, .NET gets `dotnet build`, TS gets `tsc --noEmit` — the pom branch gets neither a BuildCheck nor a Typecheck.

**Seen.** select_completion_probes on a pom.xml workspace returns exactly two candidates: `mvn checkstyle:check` (tier 2) and `mvn test` (tier 4). Step 2 of select_completion_probes (proberun.py:212-214) admits every ranked candidate at tier ≤ 1 — for Maven there are none, so the compile category is empty. This matches all four walkers ('mvn checkstyle:check, mvn test, netns mvn test' and nothing else). The module's own equivalence table at probediscovery.py:810-814 promises 'JVM -> mvn/gradle compile'; only the gradle half exists. probeclassify has the same hole: match_seed's mvn arm (probeclassify.py:752-758) knows test/verify/checkstyle but not compile, so even the coder typing `mvn -q compile` is classified UNKNOWN.

**Kernel fix.** Every build-system ecosystem must fill the cheap compile/typecheck slot, and the slot must be filled by a CHEAP command, not folded into the expensive test command. Where a language's parse errors are only reachable through the compiler, an absent compile probe is an absent syntax floor.

### Tier-0 syntax floor — no entry for Java, and no floor for XML manifests
`cria/probediscovery.py:881-910 (syntax_floor_candidates) and :856 (_STRICT_JSON_NAMES)`

**Assumes.** That every language either has an interpreter parse flag (python3 -m compileall, node --check, php -l, ruby -c) or a manifest-driven compiler that discovery will supply. Java has neither here: no javac entry in the floor, no JVM entry in lint_floor_candidates (:913-939, which covers only python/rust/go), and no compile candidate (previous finding). The strict-JSON floor covers package.json and composer.json; pom.xml is XML and nothing parses it.

**Seen.** On the Maven workspace no SyntaxCheck candidate is produced at all — which is why every walker read 'SYNTAX FLOOR: did not run' on java. Two of them report cria's own write path corrupting pom.xml with nothing detecting it; a stdlib XML well-formedness parse is the exact peer of the tomllib and json.load legs already present at :832-868.

**Kernel fix.** The floor's contract is 'every configuration and source file the coder can break has SOME parser that reads it'. It is currently enumerated by language-with-a-parse-flag; enumerating by file format instead (TOML/JSON/XML/YAML for config, per-language parse flag or compiler for source) closes Java and every future JVM/XML ecosystem in one place.

### Node test probe — the built-in runner is not in the classifier's seed tables, so package.json's own test script is discarded
`cria/probeclassify.py:604-663 (_SIMPLE_SEEDS/_SUB_TEST_SEEDS: jest, mocha, ava, tap, uvu, vitest, deno — no `node`) consumed at cria/probediscovery.py:658-660 (build_js: UNKNOWN → continue)`

**Assumes.** That a JS test script is a third-party runner. build_js vets the script BODY and drops the script entirely when the classifier does not recognise it, so `"test": "node --test tests/*.js"` and `"test": "node tests/handle-lookup.test.js"` are both thrown away.

**Seen.** classify_command('node --test tests/*.js') → kind=UNKNOWN, intent=0. select_completion_probes on a workspace with that exact package.json returns node --check per file plus the python3 JSON floor and NO Test candidate — reproducing qwen35's 'never npm test though package.json declares node --test tests/*.js' and nemotron's 'the coder COMPLIED and the probe still never ran'. Separately, the advice the coder complied with comes from a different table (TEST_CONVENTIONS node row, probediscovery.py:998-1005, runner 'jest/vitest') whose `configs` list cannot be satisfied by a package.json test script — so naming files correctly can never silence it or cause a run.

**Kernel fix.** Two failures of one shape: (1) a runner allowlist that omits the language's own bundled test runner treats the most conservative possible choice as unrecognised; (2) the table that ADVISES about test naming and the table that COMPOSES the test command are separate and can disagree, so cria can issue an instruction its own gate will not honour. A repo's declared test entry point should be the highest-confidence probe in any ecosystem, and the advice must be generated from whatever the composer would actually run.

### Runner tally table — no row for minitest or for node's TAP output
`cria/probegate.py:523-545 (_TALLIES) and :548-556 (go/unittest special cases)`

**Assumes.** That the runners worth counting are pytest, cargo, jest, junit, gradle, rspec, exunit, phpunit, dotnet, mocha, go -v and unittest. Minitest's `9 runs, 9 assertions, 0 failures, 0 errors, 0 skips` and node's `# pass 13 / # fail 0` match nothing — even though unittest's near-identical `Ran N tests` IS covered.

**Seen.** runner_tally() returns '' for both those real outputs (verified) and correct values for pytest/cargo/surefire. Two consequences, both observed by walkers: _offline_fact (probegate.py:658-663) drops to the weaker 'this runner does not print a per-test count' sentence, and _checks_superseded_by_coder_run (loop.py:5227-5262) can never see a coder's own green minitest or node run, so cria keeps restating stale failures. The table's own header says 'A ROW IS DATA, NOT CODE' — the rows are just missing.

**Kernel fix.** Coverage claims are gated on being able to read a runner's tally; a runner with no row is a runner whose green is permanently unverifiable and whose own successful runs are invisible. This is data completeness in an existing, correctly-shaped table, not a per-language branch.

### Test-floor guarantee exists for exactly one language
`cria/probediscovery.py:984-989 (only the python row carries a `floor`), :1137-1152 (test_floor_candidates skips every row without one)`

**Assumes.** Stated in the comment at :942-952: every other language's tests arrive with a manifest that triggers ecosystem discovery, which supplies the real test command. That reasoning holds for Go and Rust and fails for Ruby and Node — Ruby because a Rakefile is not a manifest here (finding 2) and Node because the manifest's declared script is discarded (finding 5).

**Seen.** The two languages where walkers report zero tests ever executed by the gate are precisely Ruby and Node; Go and Rust, whose manifests do supply a test command, ran real suites in every model's walk. The premise is documented and load-bearing, and the two counter-examples are visible in the same battery.

**Kernel fix.** A guarantee justified by an assumption about other layers must be re-checked when those layers change. The floor's real condition is 'this language's test files exist AND no test probe was composed for them' — computable from the selection itself, for every language, instead of from a per-language belief about manifests.

### validate-before-lower (the syntax check inside every lowered write_file / edit_file heredoc)
`cria/writeproxy.py:293-316 (_VALIDATE_FN); consumed at cria/writeproxy.py:325 (write) and cria/writeproxy.py:390 + :393-395 (edit `_before` / would_break)`

**Assumes.** 'A file cria can parse' == Python, JSON or TOML. `_v` dispatches on `.py/.pyi` -> compile(), `.json` -> json.loads, `.toml` -> tomllib, and every other extension falls off the end and `return None` — which the callers read as 'this content is fine'.

**Seen.** writeproxy.py:325 `if _after is not None and p.exists() and _v(...) is None:` — for a .rb/.rs/.go/.java/.js file `_after` is always None, so the refusal branch is unreachable. writeproxy.py:390 `_before=_v(str(p),s)` is always None on those files, so `_w`'s would_break guard at :393-395 never runs. Matches the gemma4 ruby walk: a corrupting edit landed a real SyntaxError on rates.rb:41/:55 and only the coder's later `ruby -c` found it — the exact class of write the Python path refuses before it reaches disk.

**Kernel fix.** cria already owns a per-extension syntax-command table (cria/probediscovery.py:881-910: node --check, php -l, ruby -c). The write path owns a second, smaller, in-process table that silently no-ops outside it. ONE ext->validator owner, with the heredoc shelling out to the language's own parser for the extensions the stdlib cannot read; the in-process compile()/json/tomllib legs stay as the fast path.

### live-execution runner — resolving which file a stated command actually runs
`cria/execcheck.py:180-194 (program_token), consumed by corroborate at cria/execcheck.py:197-213`

**Assumes.** `<interpreter> <program-file> <args...>` — the FIRST argument after the command word that contains a '.' or a '/' is the program. That is the `python script.py arg` / `node lookup.js arg` shape and nothing else.

**Seen.** Ran it directly: `cargo run --quiet -- config.toml server.port` -> 'config.toml'; `java -cp target/classes App in.csv` -> 'target/classes'; `go run . goose` -> '.'. corroborate then reports `config.toml is not an entry point on disk` (execcheck.py:212) or `no file in the workspace is an entry point by its language's convention` (execcheck.py:208). Walkers: cria executed no rust, node or ruby program in any of the three runs where this fired.

**Kernel fix.** The token that names the program is not positional — it is decided by the runner's own grammar (a build-tool subcommand names the project, `--` ends the runner's own flags, `-cp` takes a value). ENTRY_CONVENTIONS (execcheck.py:62-77) already encodes per-language runnability; program_token should resolve against that set (does this command name a known entry point, a manifest target, or the project itself?) rather than scanning argv for a dot.

### workspace inventory handed to judges, planner, coder and the exec-intent probe, stamped 'This list is complete'
`cria/groundtruth.py:193-195 (_INVENTORY_EXCLUDE) and cria/groundtruth.py:211-234; the footer at cria/prompts/workspace_inventory.txt:10`

**Assumes.** The directories worth pruning are Python's and Node's: `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `venv`, `.venv`, `site-packages`, `.tox`, `.eggs`, `node_modules`. No compiled-language build tree is in the set.

**Seen.** cria/execcheck.py:79-80 defines a SECOND skip set for the same job that DOES contain `target`, `dist`, `build` — the two disagree, and the one that feeds the 'complete' listing is the one without them. Result on rust: ~450 lines of target/debug/**.o/.rmeta/.rlib/.d/.timestamp drown src/main.rs, and the reasoner concluded 'I don't see a config.toml file listed'.

**Kernel fix.** One owner for 'what is a build artifact', shared by every walker (inventory, entrypoints, host-scan). The kernel is the same in every ecosystem — a directory the toolchain generates — and cria already has .gitignore templates it uses for the lint collector (probediscovery._language_files -> linterprobe.collect_files). Use that, not two hand-kept literal sets.

### runnable_listing — the file list the exec-intent probe is told to name a program from
`cria/execcheck.py:423-425 (_NOT_A_PROGRAM) and cria/execcheck.py:428-456`

**Assumes.** A project is source files plus documents; deleting the documents (.json .yaml .toml .ini .cfg .md .txt .csv .lock .log .xml .html .rst) leaves the programs. That is a flat-script notion of a project.

**Seen.** It is a blocklist of DATA extensions with no counterpart for build output, so on rust every `.d/.o/.rmeta/.rlib/.timestamp` and extensionless fingerprint file survives while Cargo.toml, README.md and Cargo.lock are removed; on java pom.xml/README.md go; on go discounts.json goes. The probe is then told the list is complete. The rust reasoner reasoned from the hole: 'No `config.toml` is listed.'

**Kernel fix.** Inverted polarity. 'Is this a program?' is answerable positively — ENTRY_CONVENTIONS (execcheck.py:62-77) already says what a program looks like per language — so build the listing from the allowlist and stop maintaining a blocklist of everything a project might otherwise contain. Input data and manifests are context the probe needs, not noise.

### stale-check supersede — dropping cria's cached test failures when the coder's own run has since gone green
`cria/loop.py:5224 (_TEST_FINDING) gating cria/loop.py:5244; called from cria/loop.py:5970`

**Assumes.** A cached finding is a TEST finding if its filename starts with 'test' before the extension, or the text contains pytest's `N failed` / `FAILED`.

**Seen.** Ran the regex over real finding lines: `tests/test_db.py:12:` True, `test/test_rates.rb:41:` True, `tests/handle-lookup.test.js:8:` True — but `cart_test.go:22:` False, `src/test/java/OrderTest.java:31:` False, `tests/cli.rs:22:` False, `--- FAIL: TestCart` False, `Tests run: 12, Failures: 1` False. So on go/java/rust the function returns '' at line 5245 and cria keeps restating a superseded failure under the word GROUND TRUTH — the exact defect the function's own docstring (loop.py:5231-5239) exists to prevent.

**Kernel fix.** Notice the asymmetry: the CONSUMER of this trigger, probegate.runner_tally (cria/probegate.py:523-609), is properly generalised — pytest, cargo, jest, junit, gradle, rspec, exunit, phpunit, dotnet, mocha, go -v, unittest. The trigger in front of it is not. Key 'is this finding about a test' off the same runner/convention tables (probegate._TALLIES, probediscovery.TEST_CONVENTIONS), or off which PROBE produced the finding (cria knows its own probe kind: ProbeKind.Test), never off the filename's spelling.

### coder-capability roster injected into every reasoner / steer-author / satisfaction-judge prompt
`cria/loop.py:5936 (in _coder_tools_summary, cria/loop.py:5922-5938); intent described at cria/loop.py:5926`

**Assumes.** 'a shell' is best illustrated by python and pytest. The appended clause is a fixed string: `— runs ANY shell command (grep, cat, sed, ls, find, python, pytest …)`.

**Seen.** Every one of the four walkers found this verbatim in go, java, node, rust and ruby prompts. Not inert on ruby: the nemotron judge at 0145 reached straight for it — 'Use exec_command to run pytest or rake test' — and burned an inspection round.

**Kernel fix.** The exemplars should come from the workspace, not from a literal. cria already detects the ecosystem for its gate (probediscovery.inventory / TEST_CONVENTIONS.runner); name THAT runner in the clause, or name none at all. A hardcoded exemplar list is a per-language special case that happens to be spelled as a general sentence.

### install guard — the refusal text and the project-local escape hatch
`remedy: cria/prompts/external_install_refusal.txt:1; escape: cria/dirguard.py:95-99 (_LOCAL_INSTALL_SCOPE); trigger: cria/dirguard.py:83-90 (_GLOBAL_INSTALL); rendered at cria/dirguard.py:119`

**Assumes.** The way to install into a project is a Python virtualenv. The whole remedy is `pip install -e .`, `python3 -m venv .venv && ./.venv/bin/pip install <pkg>`, `python3 -m pytest`, and _LOCAL_INSTALL_SCOPE recognises only venv/env/virtualenv bin paths plus --target/--prefix/--root.

**Seen.** The TRIGGER is correctly generalised (dirguard.py:87 matches `gem|cargo|go install`, :89 apt/brew, :86 npm -g), so a ruby `gem install countries` is refused — and answered with pip/venv prose. Ruby's own project-local form (`gem install --install-dir vendor`, `-i`) matches nothing in _LOCAL_INSTALL_SCOPE, so there is no route cria would accept. Walked: the model tried two more installs, hit 'bundle: command not found', and hand-rolled the EU country list — the one thing the task forbade.

**Kernel fix.** A guard that refuses in N ecosystems must remediate in N ecosystems. Both halves belong to the same per-ecosystem table: (global form, project-local form, the sentence that names it). Today the table exists only on the refuse side.

### test discovery / TEST FLOOR — 'no tests were found' and the config-free test probe
`cria/probediscovery.py:984-1011 (TEST_CONVENTIONS): ruby at :1006-1007, node at :998-1005, python floor at :985-989; the floor field is documented python-only at :969 and :980-983`

**Assumes.** Each language has ONE canonical test-file convention, and for ruby that is rspec (`*_spec.rb`, `RSpec.describe`, `.rspec`). Minitest — test/test_*.rb driven by a Rakefile — has no entry, so a minitest repo reads as 'no tests'.

**Seen.** Three of the four walkers hit it: gemma4 (49 injections of 'No rspec tests were found … that is not done yet' over a suite running 9 runs / 0 failures), qwen35 (49 injections, coder's own suite at 24 runs / 0 failures), ternary-bonsai ('no error-class problems' reported four times over a red suite). Node's twin fired after a green suite and caused a rename that broke package.json's test script for six calls.

**Kernel fix.** Discovery is keyed to a FRAMEWORK's filename rule when the answerable question is the repo's own test entry point: a Rakefile default task, a package.json `test` script, a Makefile `test` target, `[[test]]` in Cargo.toml. Read the repo's declared entry point first and fall back to the convention table — the manifest is ground truth, the naming glob is a guess. The floor comment at :946-952 already argues 'the manifest names the runner'; ruby's Rakefile and node's package.json script are exactly that and are not consulted.

### syntax floor / lint floor composition
`cria/probediscovery.py:881-910 (syntax_floor_candidates) and cria/probediscovery.py:913-939 (lint_floor_candidates)`

**Assumes.** The set of languages with a cheap parse check is {python, js, php, ruby, toml, json}. There is no java branch in either function, and the lint floor's docstring (:917) lists JVM among languages with 'no entry'.

**Seen.** 'SYNTAX FLOOR: did not run' on the java task in the ternary-bonsai walk; nemotron and gemma4 report gate_commands_seen EMPTY for java across all assists-ON ranges. Every java defect that landed (invalid pom.xml, missing java.util.HashMap import, three nonexistent Commons CSV methods) is one `mvn -q compile` away. The TOML leg at :902-905 and the JSON leg at :906-909 also shell out to python3, and the TOML one exits 0 when neither tomllib nor tomli imports — it fails OPEN and prints clean.

**Kernel fix.** The floor's contract is 'the language's own cheapest parse check, guaranteed'. A language present in ENTRY_CONVENTIONS and TEST_CONVENTIONS but absent here is a hole in a table, not a design decision; and a floor leg that can exit 0 without having checked anything violates the same fail-closed rule the rest of the gate holds.

### pyflakes lint leg — file selection
`cria/probediscovery.py:923-928 (`py = linterprobe.collect_files(...)` then `*py[:MAX_FLOOR_FILES_PER_LANG]`)`

**Assumes.** The set of source files is fixed for the session, so a path list captured when the gate is composed is still the file set when it runs.

**Seen.** The sibling compileall leg at :890-892 walks `.` with an exclude regex, so the two legs of the same floor disagree by construction. qwen35's python run: 'pyflakes is pinned to four absolute paths captured at session start while compileall walks .' — on a task that explicitly asks for NEW test files, so anything created later is never name-checked.

**Kernel fix.** Not cross-language, but the same class as the rest: a snapshot standing in for the world. Either both legs walk the tree at run time, or both take the same snapshot; a floor whose two halves see different file sets cannot state what it covered.

### live-test scoring — what counts as a dedicated live-test file
`suite/tasks/_liveprobe.py:76 (`for ext in ("*.py", "*.sh")`), runner choice at :82; docstring claim at :7-9; called from suite/tasks/_handles_verify.py:170`

**Assumes.** The docstring says these are 'the two wrapper shapes any language's workspace can carry'. In practice a live test only earns the point if it is a Python file or a bash script; `live_test.rb`, `live_test.js`, `live_test.go`, `live-test.rs` are not even collected, and :82 would hand anything non-.sh to sys.executable anyway.

**Seen.** _handles_verify.py:168 repeats the claim to the reader — '*.py/*.sh wrapper — legitimate in ANY language's workspace' — while this is the FIRST and most-specific branch of live_test (_handles_verify.py:170-172), so a natively-named live test in the task's own language falls through to the slower branches or scores nothing. The exclusion filter is also `__pycache__` only, so a stray .py under .venv/node_modules/target can be picked up as 'the live test'.

**Kernel fix.** The name is the signal ('live' in the filename); the extension should select the RUNNER, not gate collection. One ext->runner map (py->python3, sh->bash, rb->ruby, js->node, go->go run, rs->cargo run, java->java) makes the docstring's claim true instead of aspirational.

### session_live_evidence — the operator's 2026-08-05 fairness credit for in-session live execution
`suite/tasks/_liveprobe.py:244 (`if not name_re.search(cmd) and "pytest" not in cmd: continue`), label at :263`

**Assumes.** A command qualifies as 'the coder ran its own test suite' if it is a pytest invocation. pytest is the only test runner named anywhere in the rule.

**Seen.** The sibling allowlist one block up (_liveprobe.py:220-221) IS generalised — python3/pytest/node/ruby/php/java/go run/cargo run/bash/./ — which shows the author knew the shape. The suite gate at :244 then narrows it back to pytest, so `rake test`, `go test ./...`, `cargo test`, `npm test` and `mvn test` only qualify if the shell string happens to contain the task handle. Line 263 hard-codes the same word into the detail text: `'pytest' if 'pytest' in cmd else 'handle-named command'`.

**Kernel fix.** Two rules for the same question in one function, one shape-generalised and one tool-named. Reuse runner_re (or probegate's tally table) for 'is this a test-suite invocation' and delete the pytest literal.

## inert-but-latent (10)

### offline test re-run note, uncounted variant
`cria/prompts/tests_pass_offline_uncounted.txt:1`

**Assumes.** That the absence of a parseable count is a property of the RUNNER. "This runner does not print a per-test count that could be read" — but cria composes `go test -count=1 ./...` at cria/probediscovery.py:490 with no `-v`, and its own reader (cria/probegate.py:603, _GO_PASS) needs the per-test `-v` lines. cria withheld the flag and then blamed go.

**Seen.** cria/probediscovery.py:490 composes the command; cria/probegate.py:658-663 falls through to this prompt whenever runner_tally returns "". Walk: gemma4 go 0042 and qwen35 go "0033 onward, every gate run" — repeated verbatim on eight gate runs, attaching a doubt-hedge to a clean Go check whose -v output would have contained the four per-test lines.

**Kernel fix.** Never state a limitation of a tool that is really a limitation of the invocation cria chose. Either ask the runner for the count it can give, or say "cria's command did not request a count".

### offline test re-run note, counted variant
`cria/prompts/tests_pass_offline.txt:1`

**Assumes.** That the deliverable talks to a network service. "nothing in them reaches the real service — they exercise the code against their own fixtures" presupposes a "real service" exists to be reached.

**Seen.** cria/probegate.py:662 renders it unconditionally whenever the online and offline tallies match. Walk: gemma4 rust 0016 on a local TOML file reader with no network in it — counts correct, sentence presupposing a service that does not exist. The judge never cited it.

**Kernel fix.** State only the observation ("the same N tests pass with the network off") and let the judge decide what it means. Naming a service asserts a fact about the task that the probe never established.

### coder-tool roster shown to every reasoner and completion judge
`cria/loop.py:5936 (appended to the {{TOOLS}} block that cria/prompts/reasoner_coder_tools.txt:1-2 renders)`

**Assumes.** That python and pytest are the neutral exemplars of "any shell command". The line reads "runs ANY shell command (grep, cat, sed, ls, find, python, pytest …)" and is appended for any tool whose name is in _SHELL_TOOLNAMES, in every language.

**Seen.** Static string, no language condition, in the seat that authors steers and satisfaction verdicts. Walk: all four models flagged it in all six languages; not inert on ruby — nemotron-elastic's 0145 judge reached straight for it ("Use exec_command to run pytest or rake test") and burned an inspection round.

**Kernel fix.** Either name no exemplar (the tool's own schema already says it runs shell commands) or draw the exemplars from what the workspace actually contains. A fixed exemplar list is a hint, and a weak model orders from the menu it is shown.

### plan setup-step criterion (drafting rule and noise judge)
`cria/prompts/plan.txt:10 and cria/prompts/plan_noise_steps.txt:11`

**Assumes.** Two of them. First, that adding a dependency is always noise — "the interpreter and test runner are already available, and dependency installation may well be blocked here", true of a Python stdlib script, false where dependency resolution IS the build (Maven, Bundler, Cargo). Second, that the managers worth naming are pip/npm/apt: the enumerated forms are "virtualenv/venv", "pip/npm/apt install", "a `requirements` entry" — no gem/bundle, no cargo, no mvn, no go mod.

**Seen.** Both are static, unconditional prompt text. The shipping-rates ruby task scored a criterion specifically for using a third-party gem, and the run hand-rolled the country list instead; the java run needed Maven to resolve opencsv and cria's dirguard closed ~/.m2 (qwen35 java 0079-0080). No walk line pins the deletion to the noise judge, so this is the latent half of the same assumption the install guard already misfired on.

**Kernel fix.** Judge a step by whether it produces something the request asked for, not by whether it mentions a package manager. Where a dependency is a stated requirement of the task, adding it is a deliverable — and any enumeration of manager names is a per-language list that goes inert on the next ecosystem.

### go test probe composed without -v, so the tally row that exists for Go can never match
`cria/probediscovery.py:490 (`go test -count=1 ./...`) against cria/probegate.py:548-554 (_GO_PASS counts `--- PASS:` lines)`

**Assumes.** That the default `go test` output is what the parser will see. Plain go test prints one `ok <pkg>` per package and no per-test line; the code deliberately (and correctly) refuses to count packages as tests, so the tally is always empty.

**Seen.** runner_tally('ok\texample.com/x\t0.002s') == '' but runner_tally of the same run with -v == '0f/1p' (verified). Result: the 'This runner does not print a per-test count that could be read' hedge is emitted on every single Go gate — qwen35's walker counted eight verbatim repeats, gemma4's reported the same, and gemma4's -v run shows the four per-test lines the bound claimed were unreadable.

**Kernel fix.** When a runner can be ASKED for the per-test output the tally reader already understands, asking is the fix; the parser and the probe composer must agree on the output shape. General rule: compose the verbosity the parser needs, per runner, rather than parsing whatever the default happens to be. (Caveat: -v output is bigger, and a head+tail elision at the 16KB cap could undercount — the online/offline comparison then goes silent rather than wrong.)

### "No tests ran — the checks above cover syntax and lint only" appended without checking whether a test probe ran
`cria/probegate.py:491-493 (clean branch) with the wording in cria/prompts/no_tests_found.txt`

**Assumes.** That an untested LANGUAGE means an untested REPO. `untested` is a per-language list from undiscoverable_tests; the sentence it prefixes is an absolute claim about the whole gate.

**Seen.** Fed a clean gate whose only probe printed '7 passed in 0.1s' plus one untested-language entry: cria emits 'the repo's own checks that ran reported no error-class problems. No tests ran — the checks above cover syntax and lint only. No rspec tests were found …'. True in the single-language suite runs; a straight false fact the moment one repo holds two languages (a python+ruby repo where pytest went green).

**Kernel fix.** A per-language finding must not be rendered in whole-repo words. The claim cria can always support is 'no test ran for <language>'; 'no tests ran' requires checking that no Test-kind probe executed, a fact proberun.gate_ran_tests already computes.

### Non-Python manifests validated by a Python interpreter, and the TOML leg fails open
`cria/probediscovery.py:832-850 (_TOML_CHECK, sys.exit(0) at :841), :857-868 (_JSON_CHECK), used at :902-909`

**Assumes.** That python3 is present in every workspace, and that a missing TOML parser should abstain silently. In a Cargo workspace the manifest floor is a Python heredoc; in a Node workspace package.json is validated by python3 while node itself is being invoked two lines away.

**Seen.** Reproduced on the synthetic rust and node trees — the composed floor commands are exactly the `python3 -c 'import tomllib …'` and `python3 -c 'import sys, json …'` blobs all four walkers quoted. The TOML leg exits 0 when neither tomllib nor tomli imports, i.e. reports a clean manifest it never parsed. Compounding it: any launch failure sets could_not_run (probegate.py:322-324) and, with no findings, the whole gate collapses to 'no usable result — no signal either way' (probegate.py:470-473) — verified with one clean node --check plus one python3-not-found section. So on a box without python3, a fully green node gate reports nothing.

**Kernel fix.** Two shapes. (1) A format-level probe should prefer a parser the workspace's own ecosystem already guarantees, falling back to a shared one — the interpreter used to validate a manifest is a dependency the ecosystem may not have. (2) A gate verdict must be per-check, not all-or-nothing: one unavailable tool should mark its own check unknown, never erase the results of the checks that did run.

### README live-probe prompt
`suite/tasks/_liveprobe.py:40 ('Use python3, never bare python.') and the rewrite at :184`

**Assumes.** The command the probe proposes will be a Python command, so the one interpreter caveat worth spending prompt words on is python3-vs-python.

**Seen.** The prompt is sent unchanged for the go, rust, java, node and ruby handles tasks (_handles_verify.py:183). The listing it is shown (_liveprobe.py:150-153) correctly spans go/rs/js/rb/php/java, so the prompt and its own evidence block disagree about what language this is. The :184 substitution is harmless elsewhere, but it is the only normalisation offered — no `ruby`/`node`/`cargo run` equivalent.

**Kernel fix.** Environment caveats belong to the box, not to one language. Either state the box's real constraint set per interpreter or state none; a single-language caveat reads as a hint about what answer is wanted.

### write_file content repair (double-escaped newlines)
`cria/writeproxy.py:1197-1200 (_repair_double_escaped), table at cria/writeproxy.py:1194 (_ESCAPES), applied at cria/writeproxy.py:922`

**Assumes.** A file body with no real newline but a literal `\n` is always a mis-encoded multi-line file, and every backslash escape in it is a mis-encoded control character. It rewrites `\n \t \r \" \' \\ \0` unconditionally.

**Seen.** Unconditional on extension — it runs on .go/.rs/.java/.js/.json content as readily as .py. A genuinely single-line file whose string literals contain `\n` (a minified JSON, a one-line Go/JS source, a generated fixture) is silently rewritten before it reaches the atomic-write heredoc, and validate-before-lower cannot catch it because for most of those extensions (see finding 1) it validates nothing.

**Kernel fix.** The trigger is a heuristic about ENCODING applied without asking what the file is. Gate it on the same ext->validator owner proposed in finding 1: repair, validate, and keep the repair only if it did not turn a parsing file into a broken one — which is exactly the write path's existing regression-only contract, currently unavailable to it.

### lossy prose stripper used by the context floor on oversized tool results
`cria/content_reduce.py:350-363 (_FUNCTION_WORDS) and :272-286 (strip_prose_text), gated at :133 by _looks_like_code (:399-430); reached from cria/contextfloor.py:359`

**Assumes.** The gate holds: anything that is code will be detected structurally and skipped, so deleting `is/to/in/on/at/for/with/from/by/as/be/do/its/an/a` from what remains is safe.

**Seen.** The gate DOES hold for source in all six languages — I ran ruby, python and go samples through it and all three returned code=True. But the words themselves are two-letter ISO country codes: running the stripper over a ruby EU-list sample turned `EU = %w[at be bg]` into `%w[at bg]` — Belgium deleted. The protection is entirely the code sniff; any oversized NON-code tool result carrying lowercase codes or short identifiers (a fetched ccTLD list, a CSV, a YAML fixture) is inside the stripper's scope, and the ruby and node battery tasks are exactly about country-code lists.

**Kernel fix.** A deletion rule whose word list collides with real data values needs a reason to fire, not just an absence of a reason not to. The module's own digest_reduce (:73-114) already made this call for instruction text — keep it whole and disclose. The same argument applies here; the code sniff is a guard against one collision class, not against the class.

## cosmetic (7)

### coder system prompt — the closing Notes section
`cria/prompts/coder_system.txt:34`

**Assumes.** That every task involves an HTTP API. The last line every coder reads, in every language, is "A 404 HTTP status code on an API endpoint can mean two things…" — the ada-handles failure mode promoted to the most salient position in the system prompt.

**Seen.** Static, unconditional; loaded as the coder's system prompt on every turn (the prompt cria owns per docs). Across the battery it had nothing to bite on in go (cart arithmetic), rust (local TOML reader), ruby (shipping rates) or java (CSV) — four of six tasks with no HTTP in them. No walk line shows it causing an action, so it is dead weight rather than a misfire.

**Kernel fix.** Task-shaped notes belong in the task-conditional layer, not the always-on system prompt. The general rule already present at line 4 ("DON'T GUESS… Investigate first") covers the 404 case without naming HTTP.

### write-refusal template — directory target
`cria/prompts/write_isdir.txt:1`

**Assumes.** That the file the coder was trying to write is a Python file: the example path is "`<that folder>/your_file.py`".

**Seen.** Static exemplar in a refusal that fires on any language. Walk: nemotron-elastic rust 0021, replayed at 0049 and 0060, in a Cargo workspace containing only .rs and .toml. The guard itself was correct (it blocked a write to the tests directory); only the exemplar is out of place.

**Kernel fix.** An exemplar in a refusal should be extension-free ("<that folder>/<filename>") or drawn from the refused path itself. cria holds the attempted path — it can echo it rather than invent one.

### tool cheat-sheet, web_fetch entry
`cria/prompts/cheatsheet.txt:25`

**Assumes.** That the runtime whose default User-Agent gets refused is Python's: "a site this tool reads fine may still refuse a plain script (e.g. python-urllib's default UA)".

**Seen.** Static text folded into every coder system message when web_fetch is in the menu. cria/prompts/fetch_route_mismatch.txt:1 already carries the correct, balanced form of the same fact — "python-urllib, node-fetch, Go's http" — so the neutral wording exists in the repo and this line simply predates it. No walk line cites it.

**Kernel fix.** When the same fact is stated in two prompts, the more general wording is the one to keep. A single-runtime exemplar makes the sentence read as advice about Python rather than about default User-Agents.

### [GROUND TRUTH] testless line written in pytest's vocabulary
`cria/prompts/gate_notes.txt:13, selected by cria/loop.py:5298 from sess.last_gate_testless (set from proberun.gate_ran_tests, cria/proberun.py:379-393)`

**Assumes.** That 'collected' is how test runners describe finding tests. The underlying computation is language-agnostic and was CORRECT in every case the walkers cite — a Test probe genuinely never ran. Only the wording is Python's.

**Seen.** '(0 collected / no test probe ran)' reported to judges looking at minitest workspaces ('N runs, N assertions') and node TAP output ('# pass 13'). Three walkers flagged the same phrase; in the ruby and node runs the fact behind it was true and the judge answered satisfied anyway.

**Kernel fix.** A true fact stated in one ecosystem's dialect reads as a fact about a tool the workspace does not have, and a judge discounts it. Ground-truth sentences should name what cria did ('no test command ran in this gate') rather than paraphrase one runner's output.

### ground-truth line handed to the satisfaction judge when the gate ran no tests
`cria/prompts/gate_notes.txt (`testless = [GROUND TRUTH] … (0 collected / no test probe ran)`), rendered at cria/loop.py:5298-5299, flag set at cria/loop.py:2686, :5036, :5196 and declared at cria/loop.py:215`

**Assumes.** 'collected' is a neutral word for 'the runner found tests'. It is pytest's collection vocabulary, and the line goes into the judge's highest-authority slot for every language.

**Seen.** Reported by all four walkers on ruby and node. On qwen35's node run the same prompt carried six '# pass 13 / # fail 0' results directly above the banner; on gemma4's ruby run the log held three passing minitest runs ('14 runs, 16 assertions, 0 failures'). The judge answered satisfied anyway — so the cost today is a false-vocabulary fact, not a wrong verdict.

**Kernel fix.** cria knows WHICH probe did not run and what that runner calls its unit (probegate._TALLIES already carries every runner's own phrasing). State the fact in the repo's own terms, or state it without a count noun at all. A tool-specific word in a GROUND TRUTH slot is the smallest version of rule 5b.

### write-refusal template for a directory target
`cria/prompts/write_isdir.txt:1 (example filename `<that folder>/your_file.py`), emitted from cria/writeproxy.py:356`

**Assumes.** The reader is writing Python. The refusal is otherwise entirely language-neutral and correct.

**Seen.** Fired in a Cargo workspace containing only .rs and .toml (nemotron rust walk, calls 0021/0049/0060). The guard itself was a correct save — it blocked a write to the tests directory.

**Kernel fix.** An exemplar is model-facing content with a language in it. Where an example is needed, derive it from the path the model actually sent (it already has the extension) rather than shipping a literal.

### edit-recovery (cria/editrecovery.py) and the inline-size bound (content_reduce.INLINE_RESULT_MAX_BYTES)
`cria/editrecovery.py:38-185 read whole; bound at cria/content_reduce.py:39, applied at cria/writeproxy.py:466 (edit fact-report cap), :477 (READ_INLINE_MAX), :516, :561, :588, :599`

**Assumes.** None found that is language-shaped. Recorded so the negative is on the record rather than assumed.

**Seen.** editrecovery keys entirely on basename (:39, :54), on cria's own marker (:33, :76) and on the heredoc's mode field (:94-112) — no extension, no test-file rule, no per-language wording. The escalation clock's phrase match at :183 ('produce the corrected FULL file') is coupled to prompt wording, not to a language, and the phrase is present in cria/prompts/editfail_reports.txt:8-9. INLINE_RESULT_MAX_BYTES is a byte budget derived from the harness's per-result history budget; it is applied identically to reads, listings, spills and the edit fact-report, and nothing in it varies by file type.

**Kernel fix.** The correct shape, for contrast with the findings above: bound by BYTES (a property of the channel), key by the tool's own structured mode (a property of the event), never by the file's spelling.
