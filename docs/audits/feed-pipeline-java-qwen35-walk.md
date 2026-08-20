# Walk — `feed-pipeline-java × qwen35`, run `1787249436`

**Score 0/5. 171 calls, 30.8 minutes, ended on the wall clock.** Captures: `~/.cria/calls/20260820T111058-01a0205e-7e44-7151-916d-a13fe0a97089`. Code state at run time: `05f7525` — before today's four fixes.

Walked to answer one question: **did it fail to the same causes as [`feed-pipeline-java × nemotron-elastic`](feed-pipeline-java-nemotron-walk.md)?** Four agents plus direct verification. Agent claims that did not survive checking are recorded as refuted.

## Answer: one shared root cause, in the opposite direction, plus one shared plumbing bug. Everything else is different.

## What this run got right

Almost everything the sibling got wrong.

- **The library choice was correct.** `org.apache.commons:commons-csv:1.11.0`, declared at call 0016 and never touched again. It fetched the real Apache javadoc first (0022, 0023, 0048). No invented class, no invented version.
- **The build was green for 21 of the 31 minutes.** `mvn compile` exited 0 at calls 0025, 0030, 0041, 0046, 0102, 0108, 0115, 0132 — and again at **0159, two minutes from the wall**.
- **It found the real threading bug unaided** at 0068: *"the row counts are inconsistent across runs (36996, 38461, 37706) when they should be deterministic"*.
- **Genuinely wasted calls: 3 of 171 (1.8%).** Two off-menu tool names, one ruminated reasoner.

## The shared root cause: the briefing writes build state from its own reading, not from the check that ran

This run compacted three times. **Two of the three briefings state a false fact about the build, in opposite directions.**

### Briefing #1 (call 0057, minute 8) — invented a failure that was already fixed

> `Running the importer on the main feed … still fails with a ConcurrentModificationException in HashMap.merge() at Importer.java:96`

The last `HashMap` was changed to `ConcurrentHashMap` at call 0051, **99 seconds earlier**, and nothing re-ran it. The exception did not exist.

Cost: eight calls disproving it. The coder said so out loud —

> 0066: *"the summary says there's a ConcurrentModificationException at line 96. Let me check — the line numbers might have shifted."*
> 0067: *"The code works with parallel workers but the summary says it fails with ConcurrentModificationException — **but my test shows it works.**"*

The same briefing also reported the messy-feed run as *"4 valid rows covering 4 SKUs … matching the expected behavior"*. The tool result it was summarising says `imported 5 rows covering 8 SKUs`. It read the four printed SKU lines and overwrote the count line directly above them — erasing the 5/8 mismatch, which is the header row being counted as a SKU.

### Briefing #3 (call 0148, minute 26) — denied a failure sitting in its own input

> `- The build compiles successfully.`

Its prompt contains `cannot find symbol` **eight times** and `exited with code 1` twice, including:

```
[ERROR] .../Importer.java:[235,51] cannot find symbol
  symbol:   class Action
```

**And cria's own deterministic work-log had it right.** The compactor role at 0140 wrote, correctly:

```
$ exec_command {"cmd": "mvn compile -q"} -> FAILED compilation: "cannot find symbol class Action"
```

The briefing step at 0148 discarded that and asserted the opposite. **cria held the ground truth at compaction time and did not use it to constrain the briefing.** That is the same defect the sibling run died of, and it is what `8f7bc32` fixes: `_last_checks_note` re-attaches the last gate verdict verbatim to the briefing, and it had never fired on any session because the store lookup used a key nothing writes. **Zero `LATEST CHECK RESULTS` blocks in this run's 171 prompts**; the workspace inventory, which needs no store lookup, appears in five.

### Why the damage was bounded here and fatal there

cria then contradicted itself inside a single prompt. Call 0155 carries `The build compiles successfully` **once** and `class Action` **three times**, the latter in a proper `⟦ctx:checks⟧` block.

**Here the truth won.** 0155 opens *"Let me read the current Importer.java file in sections … and fix the compilation errors"*, and the build was green four calls later at 0159.

In the sibling run there was no competing truth — the post-compaction prompts carried **zero** copies of the compile error — and the fiction ran unopposed for twenty calls. Same bug, different blast radius, decided entirely by whether a checks block happened to be in the same prompt.

## The other shared cause: one file under two names — worse here

`Importer.java` was written **21 times: 10 by absolute path, 11 by relative path**. A near-even split, so neither run of writes ever superseded the other and the history carried copies that should have folded. `pom.xml` was written **once**, and cria's note still told the coder *"3 earlier writes … removed: pom.xml, Importer.java"* — a false fact about a file nothing had touched since call 0016.

Both halves fixed in `d99f82e` (path spellings fold by component-suffix) and `cc84738` (the note names what it dropped).

## Causes NOT shared with the sibling

| sibling cause | here |
|---|---|
| invented `com.opencsv.CSVRecord`, never checked | **no** — right library, docs fetched, correct `pom.xml` |
| Maven's `[ERROR] ` tag hid diagnostics from the parser | **barely** — only 2 prompts carried the "could not be parsed" line; the build was green most of the run |
| the steer rewriter never received the directive | **no** — zero `steer-code` calls; the path was never reached |

## What actually cost this run its points

### The free deliverable starved behind an impossible one

`REVIEW.md` was never written. **cria's whole chain worked**: the done-check ran six times (minutes 4.5, 7.3, 12.6, 16.3, 20.1, 24.5), every verdict named `REVIEW.md`, verified on disk each time; every verdict reached the coder as `⟦ctx:steer⟧` two calls later; the coder restated it in its own words all six times and mentions it in **18** reasoning files. **Zero write attempts** — every write in 171 calls went to `Importer.java` or `pom.xml`.

The shape repeats verbatim: *"Let me first benchmark the performance and then create the REVIEW.md"* (0128), *"Let me verify the performance more carefully and then create REVIEW.md"* (0088). The 4× speedup it chained the file behind was never achievable — its own benchmarks put parallel at ~1.24 s against ~1.17 s single-threaded, about 1.0× — so the precondition never cleared. A sixty-word file needing no build starved for thirty minutes behind a target that could not be met.

*(One measurement error nobody caught, not cria's: the "single-threaded baseline" was taken with `-Dpipeline.Workers_ENABLED=false`, which does nothing — `WORKERS_ENABLED` is a compile-time `static final`. Both numbers are the parallel path.)*

### Churn, then a scope error two minutes from the end

15 whole-file rewrites plus 7 patches, cycling Executor → CompletableFuture → ForkJoinPool → Executor. cria saw it (`loop.wheel_spinning {"writes": 5}`, `loop.thrash_diagnosed`) and the clock beat it.

The fatal edit is call **0162**, a whole-file rewrite that moved two declarations inside a `try (…)` block and left the `return` outside:

```java
try (BufferedReader reader = …; CSVParser parser = …) {   // line 150
    List<Object[]> rows = new ArrayList<>();              // 159 — inside
    List<String>   skus = new ArrayList<>(seenSkus);      // 177 — inside
}                                                          // 209 — both die here
return new Summary(skus.size(), rows.size(), totals);      // 211 — out of scope
```

Then, in the last four calls: it got the wrong theory (0164); got it **exactly right** at 0165 — *"defined inside the try block, so it's not accessible outside… Let me fix this properly"* — and wrote back a file **byte-identical to the broken one**; lost the thread completely at 0169, arguing the variables *"should be accessible"*; and on the **final call** had it right again and began the correct edit. The 30-minute wall expired mid-call. That edit was a half-fix anyway — it hoists `rows` and leaves `skus` inside.

**Found it, then lost it** — the same shape as the sibling, on a different bug.

## Refuted

- **"31% of turns did nothing."** False. 54 turns emitted their tool call inside the reasoning channel instead of as a structured call; cria recovered **52** and refused **2** as off-menu tool names — matching its own counters exactly. Traced two by hand: the recovered calls ran, and their results appear in the next prompt. There is no post-compaction stall in this run.
- **"cria is blind to reasoning-channel writes."** False for cria: `writeproxy.lowered` counts 14 `write_file` + 8 `edit_file` = **22**, matching all 22 landed writes. The recovery happens before lowering. The blind spot is in **post-run analysis** that reads `message.tool_calls` from the raw captures — it caught out this walk's own first write census, which missed 7 writes including the one that broke the build.
- **"cria's write path mangled the file."** False. Zero edit-recovery events; every structured write returned `Wrote …`; the 0162 content is byte-identical to disk. All 54 `⟦ctx:denied⟧` markers are read-side, not write-side.

## Open

- **Nothing constrains a briefing's build claim against the gate that just ran.** `8f7bc32` restores the deterministic appendix, which is the load-bearing half. It does not make cria refuse a briefing sentence its own gate contradicts. Both of this run's bad briefings would still be written; they would now sit beside the truth rather than replacing it.
- **A steer named two files that have never existed** — call 0091: *"Inspect … Importer.java, Summary.java, and main.java"*. `Summary` is a nested class inside `Importer.java`. The coder spent a call on it.
- **Compaction machinery cost 15.6% of the run** (288.6 s across 3 compactor + 3 proxy calls and 3 post-compaction steers), and two of the three briefings actively misdirected.
- **The read cap pushed the coder into keyhole reads of its own file.** 21 read-denials on `Importer.java`; calls 0164/0169/0170 read 10–20 lines around line 211 and could not see where the enclosing `try` opened — the one fact needed to fix it.
