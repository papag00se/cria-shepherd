# progress_fresh — fresh author-labelled DONE / PARTIAL / NOT_STARTED set

A permanent, never-trained-on test set for the System 1 `progress` family. 244 rows from 34 small coding tasks in 25 languages (Python, TypeScript, JavaScript, Go, Rust, Java, Ruby, C#, C++, PHP, then Kotlin, Swift, Scala, Elixir, Haskell, Lua, Bash, Dart, Perl, C, Julia, OCaml, Zig, Clojure, SQL) that are unrelated to the six battery tasks the training rows come from. 102 DONE, 102 PARTIAL, 40 NOT_STARTED.

The original 10 tasks (90 rows, balanced 30/30/30) are unchanged. The 24 **extension** tasks (marked `extension=True` in `defs/`, helper `dsl.py`) were added to weight the set toward the DONE/PARTIAL boundary: each requirement has a DONE row and a PARTIAL near-miss of the SAME requirement, and only 10 requirements also get a NOT_STARTED control (`ns=True`). PARTIALs are realistic "looks finished but isn't": code without its test, tests that miss the edge case, implemented but not wired into main/CLI, wired but wrong in one case (e.g. case-sensitive where case-insensitive was asked, trailing-only trim), docs promised but missing. Many PARTIALs carry their own happy-path tests so evidence size alone does not give the label away (median PARTIAL/DONE evidence-length ratio is 0.75 on the extension rows, 0.46 on the original ones).

## How rows were built
- `defs/<task>.py` holds a seed project (a few files) and 3 concrete requirements (fix a bug, add a flag/endpoint/method, add tests, README/config). For every requirement the author wrote three snapshots: `NOT_STARTED` (the seed, or an unrelated edit only), `PARTIAL` (clearly incomplete: code without its test, half the cases, written but not wired), `DONE` (what a careful reviewer would accept).
- `python -m suite.progress_fresh.build` writes the snapshots under `tasks/<task>/{seed,<req>/{not_started,partial,done}}` and the rows. Each row is `{requirement, evidence}` where `evidence` is the unified diff seed -> snapshot produced by `suite.progress_dataset.seed_diff`, the same renderer as the training rows (`render_state` makes the model input).
- **Labels are author-known by construction, not judged by any model.** Each requirement is scored on its own changes only (the snapshot has no other requirement's work).

## Split (by task, not row)
- `dev.jsonl` (51 rows): `recipes-rb`, `weather-js`, plus the extension tasks `wordtrim-lua`, `backup-sh`, `logparse-pl`, `interval-clj`, `ratelimit-py` — for exploratory probing.
- `test.jsonl` (193 rows, 81 DONE / 81 PARTIAL / 31 NOT_STARTED): the other 27 tasks (8 original + 19 extension, ~80% of the new tasks).
- **Rule: `test.jsonl` is never used to tune anything (thresholds, prompts, hyper-parameters, checkpoint choice). Never add any of these rows to a training set.**

## Scoring
`CUDA_VISIBLE_DEVICES=<RTX 3080 uuid> python -m suite.progress_fresh.score --split test --model <reference dir>` (3080 only). `baseline-final-test.json` is the progress-v1 `final` model on the extended test split (193 rows): accuracy 0.539, macro-F1 0.496, recall DONE 0.00 / PARTIAL 0.99 / NOT_STARTED 0.77; it calls 80 of 81 DONE rows PARTIAL (1 NOT_STARTED, 0 DONE). On the original 72-row test it was accuracy 0.639, macro-F1 0.531 (recall DONE 0.00 / PARTIAL 1.00 / NOT_STARTED 0.92); those 72 rows are still inside the new test.

See `manifest.json` for counts and sha256.
