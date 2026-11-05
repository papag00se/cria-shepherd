# progress_fresh — fresh author-labelled DONE / PARTIAL / NOT_STARTED set

A permanent, never-trained-on test set for the System 1 `progress` family. 90 rows from 10 small coding tasks (Python, TypeScript, JavaScript, Go, Rust, Java, Ruby, C#, C++, PHP) that are unrelated to the six battery tasks the training rows come from.

## How rows were built
- `defs/<task>.py` holds a seed project (a few files) and 3 concrete requirements (fix a bug, add a flag/endpoint/method, add tests, README/config). For every requirement the author wrote three snapshots: `NOT_STARTED` (the seed, or an unrelated edit only), `PARTIAL` (clearly incomplete: code without its test, half the cases, written but not wired), `DONE` (what a careful reviewer would accept).
- `python -m suite.progress_fresh.build` writes the snapshots under `tasks/<task>/{seed,<req>/{not_started,partial,done}}` and the rows. Each row is `{requirement, evidence}` where `evidence` is the unified diff seed -> snapshot produced by `suite.progress_dataset.seed_diff`, the same renderer as the training rows (`render_state` makes the model input).
- **Labels are author-known by construction, not judged by any model.** Each requirement is scored on its own changes only (the snapshot has no other requirement's work).

## Split (by task, not row)
- `dev.jsonl` (18 rows): `recipes-rb`, `weather-js` — for exploratory probing.
- `test.jsonl` (72 rows): the other 8 tasks.
- **Rule: `test.jsonl` is never used to tune anything (thresholds, prompts, hyper-parameters, checkpoint choice). Never add any of these rows to a training set.**

## Scoring
`CUDA_VISIBLE_DEVICES=<RTX 3080 uuid> python -m suite.progress_fresh.score --split test --model <reference dir>` (3080 only). `baseline-final-test.json` is the progress-v1 `final` model on test: accuracy 0.639, macro-F1 0.531, recall DONE 0.00 / PARTIAL 1.00 / NOT_STARTED 0.92 (it calls every DONE row PARTIAL).

See `manifest.json` for counts and sha256.
