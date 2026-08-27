# Level 5, the cells under 40% — walked

Two passes. The first walked the five cells scoring under 40, fixed five things and re-ran them; the second walked the three that were still red afterwards.

Five agents, one cell each, each with the full toolset: the call captures, the shipped tree, and a copy of the workspace to run things in. Every finding below was reproduced before it was written down. The walks that follow the earlier sub-60 pass ([`l5-sub60-walk.md`](l5-sub60-walk.md)).

| cell | score | what actually happened | cria's part |
|---|---:|---|---|
| ternary-bonsai × java | 12 | The compiler asked for one import. | cria wrote the correct fix and then refused its own steer. |
| nemotron × go | 27 → **15** | `go.mod` pins `v1.2.3`. | cria's steer quoted go's own usage line and the coder wrote the placeholder. |
| nemotron × ruby | 9 | The coder went hunting a deleted test. | cria told it seven passing tests had vanished. Nothing had. |
| nemotron × node | 33 | Eleven calls spent re-making an edit that was already made. | A redirect ordered a change whose before and after were the same. |
| nemotron × java | 16 | It swapped CSV libraries rather than read the error. | cria authored the real fix and dropped it on a bad count. |

The go cell was **re-judged from 27 to 15** during this pass. The earlier verdict said `discounts.json` is genuinely read; `loadDiscounts()` is defined and has no call site anywhere in the tree, and there is no `init()`, so `Discounts` is the empty map it was declared as. Go does not reject an unused function, so nothing in the build says so.

## What was fixed

**A name the checks cannot find is a name they are asking for.** ternary-bonsai × java: cria's supervisor produced the run's one correct directive at call 0024 — add the `AtomicInteger` import, rename the local that shadows the static field. Both names went to the prescribes-judge inside a single "Answer with ONE word", the answer came back `PRESCRIBES`, and cria refused itself. Two changes, both on the judge's side: one name per call, so the refusal names the symbol the judge actually answered about; and the prompt now spells out that supplying a missing name — importing, declaring, defining, creating the file, adding the dependency — is `QUOTES`. A findings-side pattern was tried first and reverted: `cannot find symbol: class AtomicInteger` and `undefined: decimal.NewFromFloat64` are the same sentence, and silencing one silences the incident the guard exists for.

**A tool's own synopsis is not evidence about this repo.** nemotron × go: `go.mod:4:5: usage: require module/path v1.2.3`. `v1.2.3` stands in for a version exactly as `module/path` stands in for the module. `_invented_version` passed the steer because the token was present in the evidence, which was true and beside the point. Grounding stays the same rule; a line where a tool prints its own argument syntax stops counting as an observation.

**The passing-test high-water mark is per command.** nemotron × ruby: two test probes tallied seven passing each, the counter summed them to fourteen, a later gate ran one of them, and cria reported that seven passing tests were no longer being run. The count is now kept per test command, so every comparison is between two runs of the same command, and a command that did not run this time is not compared — its mark is kept, because silence is not zero.

**A method name and an escaping slip are not invented code.** nemotron × java: the reasoner wrote the correct fix — delete the five `builder.set…` calls that do not exist on the CSV builder — `_invented_code_spans` counted 2, and the directive was refused. The two were `Importer.load()`, empty parens, which hands the coder nothing to paste; and a `setEscapeCharacter` call one character of escaping away from the line that is on disk. Applied by hand to a copy of the shipped tree, all five `cannot find symbol` errors disappear.

**The read ledger says when it only saw a window.** Same cell: `read_file` takes `start_line`/`end_line`, and a 16-line window on a 237-line file was recorded as `Importer.java (751 bytes, 16 lines)` under a header saying these are the files you have read. The coder acted on it at call 0070. An entry from a ranged read now names the window, and a window read never replaces a whole-file reading.

## What was not built, and why

**The byte-identical redirect.** nemotron × node: a redirect at call 0058 ordered an edit the reasoner had just read, costing eleven calls and the Dockerfile. The proposed fix was to drop a directive whose before and after are the same. Measured first, over every steer in the captures: **2,352 steer blocks, zero real instances** of a directive that orders a change from A to A — the three the pattern flagged are all cases where the two operands genuinely differ. The other shape, "the directive dictates a span that is already on disk", cannot be told apart from the legitimate and common case of a steer quoting the current code as context before saying what to change elsewhere. Building it would refuse good steers to catch one bad one. Left unbuilt, recorded here.


## The re-run, after the fixes

The five cells ran again at level 5 on 2026-08-27 and were judged the same way.

| cell | before | after | what moved |
|---|---:|---:|---|
| ternary-bonsai × java | 12 | **100** | Every check met. 40× faster with identical totals, four workers, one distinct result over eight runs, seven located findings in REVIEW.md. This is the cell whose walk found cria refusing its own import directive. |
| nemotron × node | 33 | **70** | The CLI, the `request` removal and the Dockerfile all pass. The test file cannot pass an assertion — it reads `stdout`/`exitCode` off `execSync`'s Buffer. |
| nemotron × go | 15 | **32** | `go.mod` now pins a real version, so the usage-placeholder failure is gone. Nine compile errors remain, six of them `decimal.NewFromFloat64`. |
| nemotron × java | 16 | **28** | Seven named skip reasons, workers, per-SKU locks. Still imports Apache Commons CSV class names from `com.opencsv`, so 32 compile errors. |
| nemotron × ruby | 9 | **27** | The threshold bug is fixed and the repo tests are green and untouched. Nothing else was attempted. |

The nemotron row moved from 39% to 53%, and level 5 from 74% to 81%.

Every cria-side defect the walk named stayed fixed. What is left in the four nemotron cells is one shape: **the model writes calls against an API it has not read** — `decimal.NewFromFloat64` and `decimal.RoundHalfUp` in go, `CSVFormat` and `QuotePolicy` from the wrong CSV library in java, `execSync` returning an object in node. None of those is something the rungs touch.

---

# The three red cells, walked

Three agents, one cell each, every call read in order — 89, 103 and 132 coder calls, plus cria's own reasoner turns between them. Every claim below was reproduced by running something.

| cell | score | calls | what 30 minutes bought |
|---|---:|---:|---|
| nemotron × ruby | 27 | 89 | One character. `>` became `>=` at call 0034; nothing changed after it. |
| nemotron × go | 32 | 103 | A tree with nine undefined symbols, all written in a single rewrite at call 0056. |
| nemotron × java | 28 | 132 | An importer mixing two CSV libraries, and a REVIEW.md whose one located finding is a defect cria invented. |

**The three fixes from the morning held.** No summed test-count regression in the ruby run. `go.mod` pins a real version and the `usage: require` steer appears in none of the 412 captures. The java read ledger recorded only whole-file reads at their real sizes, and no steer was refused for invented code.

## The shape all three share

**cria held the answer and hid it.** Not once — six separate times across three runs, by four different mechanisms.

- **ruby, call 0012, ninety seconds in.** The model's first search returned the whole task as its first result's description: `European Union Membership · c.in_eu? #=> false`. cria wrote it to disk, showed twenty titles, and closed with "you do not have to open it". Zero of the run's 89 calls touched the spill directory. Four of the nine saved search files contain `in_eu?`.
- **go, every prompt for 103 calls.** The fetch ledger carried `https://github.com/shopspring/decimal → HTTP 200 (this page answered, but no endpoint definitions were found in it … nothing read so far provides one)`. That page has `NewFromFloat` and a worked cart-with-tax example. cria had it on disk.
- **go, call 0049.** The post-compaction workspace listing skipped `tmp` wholesale, and `tmp/reference` is where cria saves what it fetches. The re-orientation author was shown four files, and its own prompt forbids naming a file the listing does not name. It stayed quiet.
- **java, calls 0055 and 0069.** A Cloudflare 403 on opencsv's apidocs and a 404 on a source file were both reported as "the URL, the path, or the version segment in it was wrong". The 403 page holds the class list the run spent 78 more calls guessing at.
- **java, nine times.** cria pasted `com.opencsv.CSVParser cannot be converted to java.lang.AutoCloseable` into its own ground-truth block. Those words mean the jar is present and the class named is not. cria never said so.
- **java, the whole run.** The opencsv jar was in `~/.m2` from call 0050. One `unzip -l` ends the run. The coder wrote "we can't inspect the jar" and nothing corrected it.

## What was fixed

**The compaction listing keeps cria's own saved reference.** `_workspace_listing` skipped `tmp` because a package manager's tree is not the coder's work — and took `tmp/reference` with it. The rule was already written down twice elsewhere in the codebase: spill entries are labelled, never removed. This was the one place that removed.

**A stale check no longer claims to outrank the transcript.** The java run's decisive turn. At call 0091 the transcript ended with a fresh, complete `mvn clean compile`; above it cria pinned a gate result four calls older, under "if this section and the transcript disagree, this section is right". The writer obeyed, deleted ten real errors, and briefed "the code compiles and runs" over a build that never once compiled. The last 29 calls ran inside that frame. The output side of the same fact already stamped its age — the input framing was the half still asserting precedence unconditionally.

**A search description that names something callable is shown.** Dropping descriptions was written against a real poisoning by a wrong package name, and titles carry package names. They do not carry method names. A description is now re-attached when it names something callable — a backticked span, a namespaced name, a leading-hash method, a receiver call. Measured over the ruby run's nine saved files: 3,054 characters on the search that mattered, 250–1,750 on the rest.

**A refused fetch is not a wrong address.** 401, 403, 407, 429 and 451 get their own wording, which says what the server did and names no cause. 400 and 404 keep the old sentence, because for those it is true.

## What was not fixed, and is written down

- **The `no_structure` label** tells a coder a page "answered, but no endpoint definitions were found in it" — accurate, and for a library README it reads as *this page is empty*. cria has the page on disk when it says this. The honest version points at the file rather than characterising it.
- **The duplicate-search judge inverted its own rule 4 times out of 4** in the ruby run. Its prompt says a synonym swap is the same hunt; it ruled `europe` versus `eu` a new direction. That is a prompt problem with a clean measurement behind it.
- **`judge_query` cannot see the workspace.** In the ruby run it recommended searching for a gem that was already installed in `vendor/bundle` two calls earlier. cria builds a file listing for its satisfaction critic and does not give it to the search supervisor.
- **A spilled markdown document gets no outline.** `spill_outline` handles JSON and YAML. The `countries` README has `### European Union Membership` at line 202; the model was told to grep a file it had no map of.

## What no harness change fixes

All three models failed the same way, and it is not a harness failure.

- **go**: 42 consecutive calls holding `undefined: decimal.NewFromFloat64`, and it never treated the compiler as authoritative — it argued Go's import rules must differ from what it remembered, and edited the import block twice instead of the symbol. It never once ran `go doc`.
- **java**: it reached the right answer twice from its own memory — "But that's for Apache Commons CSV, not OpenCSV" at call 0054, and the correct import list at 0058 — and argued itself out of it both times. The second one lived only in its private reasoning and was gone by the next turn.
- **ruby**: nine searches, six of them a synonym swap of each other, versus zero attempts to look inside the gem it had installed.

The go cell also would not have passed on symbol names alone. Repairing only the four invented names, and leaving the model's logic untouched, builds — and reports 64.50 where the task asks for 48.58, because the discount line subtracts 0.25 as an amount rather than applying 25 percent.
