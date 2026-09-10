# Ornith-1.5 feed-pipeline-java full walk — 2026-09-09

## Run and outcome

- Run: `feed-pipeline-java_ornith15_codex_poff_1788984830`
- Capture: `20260909T131401-01a087ce-54c2-7940-8284-95520d92fd12`
- Terminal state: `milestone-stalled-45min`
- Final usefulness: **35%**
- Corpus: 102 calls, 89 full-prompt chunks, 136,256 lines, 7,586,604 bytes

The workspace had useful partial work: the OpenCSV dependency, malformed-value handling, counters,
and removal of the original quadratic SKU scan. It did not compile, its `RecursiveTask`s were invoked
sequentially, `worker()` erased accumulated totals, and `REVIEW.md` was absent.

## Walk method

`docs/walk-prompt.md` was followed with `suite/walk.py --full-prompts`; common prompt prefixes were
not removed. Eighteen initially delegated Claude walkers failed before reading because that provider
was already at its weekly limit. The final two launches, Codex 5.6-Sol/max, read chunks 01–45 and
46–89 sequentially through EOF and maintained page ledgers:

- `/tmp/feedwalk-1788984830/progress-19.txt`
- `/tmp/feedwalk-1788984830/progress-20.txt`
- `/tmp/feedwalk-1788984830/findings-19.md`
- `/tmp/feedwalk-1788984830/findings-20.md`

The reported causal chains were then checked against the original per-call prompt, reasoning, and
response files rather than accepted from the generated chunks.

## Confirmed causal findings

### 1. A historical-removal notice became a current reread order

This was the one confirmed cria-authored harmful A → B → C chain.

**A — contradictory tail.** In coder calls 0094, 0096, and 0102, the complete current
`Importer.java` bytes were already in the prompt. An adjacent read ledger said it existed so the
coder would not rediscover it. `focustrim._drop_superseded_writes()` nevertheless appended its own
notice after both the ledger and workspace inventory:

> The newest version ... is still here in full ... To be sure, read the file

The notice was intended only to explain why older, superseded whole-file writes had disappeared.
Its disk-current claim was stronger than the transform could prove after arbitrary later shell/edit
operations, and its imperative contradicted the newer read record.

**B — the coder used that concern.** CALL 0094 reasoning says it must establish the on-disk state,
read the whole file in ranges, and cites the removed writes. CALL 0096 says it has been going in
circles and must read the file properly. CALL 0102 acknowledges the earlier reads and rereads anyway.

**C — repeated action.** Those calls request `Importer.java` ranges already present in the prompt,
instead of repairing the four exact Maven failures.

**Experimental upstream correction, rejected.** Commit `3ebcc6a` changed the notice to state only
historical transform facts and placed it before an already-trailing user fact/action block. This
preserved the whole-call removal safeguard from `d387b64` and improved the narrow exact-call replay,
but the required live full-cell replay regressed from 35% to 30%. Under the replay rule, the change
was invalidated and reverted; the causal observation remains open rather than being promoted into a
shipping mechanism.

### 2. Maven/source grounding was accurate; the coder inverted it

The change in `8c679c0` behaved as designed. Maven supplied exact paths, Maven coordinates, and the
flagged source lines for four failures: absent `CSVRecord`, a non-`AutoCloseable`
`CSVReaderBuilder`, absent source symbol `CSVParser`, and absent `buildWithParser(...)`.

The coder's next reasoning first acknowledged that the API was wrong, then called an API containing
`CSVRecord`, `readHeader`, and `List<CSVRecord>` “correct.” Its only edit added a `CSVReader` import;
the broken import and loader remained. Later exact diagnostics repeated unchanged.

The source-line annotation was therefore factual and tool-voiced. This run does not support
reverting it or adding more compiler prose. It demonstrates a 9B evidence-inversion limit.

### 3. Inspecting the resolved artifact worked; integrating the result did not

A bounded reasoner action told the coder to inspect the already-resolved OpenCSV 5.9 JAR rather than
keep guessing. The dependency refusal state correctly said there was no current refusal. Maven found
`~/.m2/repository/com/opencsv/opencsv/5.9/opencsv-5.9.jar`; JAR listing and `javap` established:

- `CSVParser.class` exists; `CSVRecord.class` does not.
- `CSVReaderBuilder(Reader).build()` returns `CSVReader`.
- `CSVReader` is `Closeable` and `Iterable<String[]>`.
- `readAll()` returns `List<String[]>`; no header accessor was shown.

The coder repeatedly reversed those signatures into `Iterable<CSVRecord>`, `readHeader()`, or
`getHeader()`, then probed again. The artifact-access and dependency-cache fixes did not regress.
The failure happened after authoritative evidence reached the model.

### 4. Rumination recovery detected the loop but did not create durable progress

CALL 0100 contained the full file. Its reasoning correctly found a real concurrency defect—the
single mutable `SkippedCounts` shared by worker tasks—and proposed per-task counters plus an ordered
merge. It then re-derived the task for thousands of tokens and ended in the rumination guard without
an action. The focused retry records 127 second-guessing markers at about 8,251 reasoning tokens and
produces one grounded tool call, but that call only rereads baseline scratch data. The following
ordinary call relapses into state reconstruction.

The guard fired on the authoritative response and obeyed its one-call recovery contract. This walk
does not establish that its wording caused the relapse; no change was made to it.

## Contained hazards, not downstream causes

- Several reasoner/safety-classifier internals invented OpenCSV facts, but their unsafe prose was not
  present in the following coder prompt. The action-level boundary contained it.
- Four self-compaction candidates misstated dependency facts and/or carried future plans. Fidelity
  rejected two as `UNFAITHFUL`, one missing verdict failed closed, and the plan gate rejected one as
  `PLAN`. None was observed reaching the coder.
- A final compactor summary distorted JAR facts, but the capture ends before any coder consumed it.
- Satisfaction judges repeatedly tried a source read their prompt said was unavailable. Their
  verdicts nevertheless remained correctly negative, so this was wasted work rather than the failed
  deliverable cause.

No fix was built for a contained or model-only symptom.

## Exact-call replay

Replay target: CALL 0094's captured body, sent directly to the same Ornith backend. Arms were
interleaved. The measured event was the first emitted tool call, not a textual promise.

Experiments rejected before the final arm:

- Wording-only cleanup: no stable reduction in `Importer.java` rereads.
- Deleting the notice: rereads fell from 5/6 to 1/6 across three captured calls, but this discarded
  the earlier safeguard that tells the coder why its writes vanished.
- Ordering-only: rereads fell from 4/6 to 2/6, while retaining the misleading disk/reread sentence.

Final experimental arm—factual historical wording plus placement before newer tail facts:

| arm | repeated `Importer.java` read | other grounded action | invalid |
|---|---:|---:|---:|
| captured | 6/8 | 2/8 | 0 |
| corrected | 1/8 | 7/8 | 0 |

The experimental arm preserved the notice and produced no empty/no-tool response in this replay. It
did not solve the Java task: most displaced actions inspected data or dependency evidence.

Replay script: `/tmp/replay_superseded_note.py`.

## Required full-cell replay — experiment invalidated

Run `feed-pipeline-java_ornith15_codex_poff_1788996499` exercised `3ebcc6a` live at L5, planner off:

- 30 active minutes: **30% / continue**.
- 45 active minutes: **30% / stalled**.
- Terminal: `milestone-stalled-45min`, 124 model calls, 52.6 wall minutes.

The model wrote OpenCSV integration, linear SKU tracking, currency cleanup, and skipped-row
scaffolding. The final importer still did not compile, launched no parallel workers, truncated
currency values through `LongAdder.add((long) value)`, let malformed numbers escape, and omitted
`REVIEW.md`. Between the frozen 30- and 45-minute snapshots it made only one narrow constructor
change. This is worse than the 35%-useful source run and therefore invalidates the otherwise
plausible exact-call result. Commit `3ebcc6a` was reverted; its incident-specific regression test
was removed because it asserted behavior the live replay rejected.

The existing superseded-write tests remain in force: only genuinely landed whole-file replacements
supersede earlier writes, refused writes do not, path aliases converge, removed tool results do not
become orphans, and the surviving payload remains complete.
