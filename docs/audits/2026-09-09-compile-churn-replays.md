# Compile-churn history and replays — 2026-09-09

## Incident

`feed-pipeline-java_ornith15_codex_poff_1788969546`, call `0161-coder-s1`, received a fresh Maven compile gate with three errors at `Importer.java:[154,43]`, `[202,62]`, and `[211,34]`. The next action inspected an unrelated baseline; the following action re-read lines 140–235 before attempting repairs. The complete rendered prompt, reply, and reasoning were read before assigning behavior to the call.

The compiler output itself was not the problem. A diagnostic-line dedup experiment reduced immediate fix attempts from 5/6 to 2/6 and increased reinspection from 1/6 to 4/6; it was reverted. Maven's repeated records may provide useful salience.

## History search

Four candidate assists were checked against git history before implementation.

### A. Run a fresh compile probe

Already implemented. `proberun.py` discovers and runs compile/build checks in the periodic and completion gates. Commit `1a87c55` already deduplicates repeated diagnostics by whole record rather than by line. Call 0161 itself carried a fresh `mvn -q compile` result.

### B. Co-locate a diagnostic with its current source line

Already intended by the flagged-line grounder introduced in `988f1d9` and made lossless in `9b10d08`. It did not reach Maven:

1. `probegate._FLAGGED_LINE_RE` independently recognized only `file:line[:col]:`, while the canonical `probeparse.split_diag()` had recognized Maven `file:[line,col]` since `1474a16` / `cc84738`.
2. After converging on `split_diag`, the broad runtime guard still classified javac's `unreported exception com...CsvValidationException` as a runtime raise site merely because an exception class appeared anywhere in the sentence. The guard from `a80631e` is load-bearing for actual runtime findings, whose message begins with the exception class.

The fix uses `split_diag()` as the single location owner and narrows the runtime shape to an exception class at the head of a located finding's message. Runtime `path:line: java.lang.NullPointerException` remains unannotated; javac's checked-exception diagnostic gains the current line without paraphrasing the compiler or proposing a fix.

### C. Prefer a targeted edit over a whole-file write

The coder system prompt already says this explicitly. A broader repetition/action steer was removed in `2803786` after the arm where it fired averaged 48% across 55 runs, versus 51% in BASE runs containing three or more identical calls. No second tool-choice steer was added.

### D. Fix one compiler error, rerun, repeat

No exact prior implementation or removal was found. It remained eligible for replay, but was treated as footgun-prone process prescription in light of `2803786`.

## Replay method

Source capture: `~/.cria/calls/20260909T085916-01a086e5-1b82-7753-969b-0cd35d556a64/0161-coder-s1.json`.

The original run workspace still existed. Its 245-line `Importer.java` exactly matched the three compiler coordinates. Replays used the exact captured 0161 request before the model's baseline command/read. Eight samples per arm were used.

- **Raw:** byte-identical captured request.
- **Grounded lines:** compiler text unchanged; after the first occurrence of each diagnostic, append only the existing mechanism's intended factual sentence: `the flagged line on disk — line N: <exact bytes>`.
- **One-error cadence:** raw request plus one process directive to resolve only the first current diagnostic and rerun the same check.

A response counted as a targeted fix only when its first tool call was an edit engaging the diagnosed construct. Every counted edit was then applied to a disposable copy of the real workspace and compiled offline.

## Results

| arm | immediate targeted fix | reinspect first | average reasoning chars |
|---|---:|---:|---:|
| raw | 0/8 | 8/8 | 7,161 |
| one-error cadence | 1/8 | 7/8 | 3,260 |
| grounded source lines | 2/8 | 6/8 | 4,702 |

Both grounded-line edits matched once and removed the checked-exception error; compilation moved from three unique errors to the two lambda-capture errors. The cadence arm's sole edit did the same.

This is modest evidence, not a claim that source quotes eliminate compile churn. The full prompt already contained older source ranges, and the model's original reasoning correctly identified all three errors; fresh co-location improved salience and sometimes saved a read turn. The factual intervention outperformed the process directive, so the directive was not combined or shipped.

## Decision

Ship only the reach correction for the existing flagged-line grounder. Do not deduplicate Maven's raw output, add another compile probe, steer tool choice, or impose one-error cadence.
