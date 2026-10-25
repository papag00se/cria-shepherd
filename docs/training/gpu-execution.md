# Authorized provisional GPU experiment

The operator explicitly authorized both training and clearing the RTX 3090: “Whatever is on the 3090 can be cleared. Use it.” This supersedes the earlier permission-pending state for this offline experiment only. It does not authorize deployment, changing the frozen examples or labels, touching the RTX 3080 workload, restoring retired assists, or enabling planning.

The 3090's `qwen38-27b-rtx3090-single-1` container was stopped cleanly; its idle-start timer/service was stopped so training can retain the device. The 3080's separate inference process was left alone. GPU selection is by exact UUID, not an assumed ordinal. No container was deleted or model-server configuration rewritten.

The isolated environment uses Python 3.13.15, Torch 2.8.0+cu128, Transformers 5.20.2 and Tokenizers 0.23.3. The pinned pretrained checkpoint was downloaded and its full SHA-256 verified against the frozen recipe; BF16 support was checked on the actual 3090. These experiment dependencies are not production dependencies.

`suite/training_run.py` verifies the frozen contract/data hashes and explicit device/recipe-bound authorization before fitting. It visits complete native inputs without truncation, excludes the calibration task from both heads/shared encoder, preserves final short accumulation batches, implements training-only task/family weighting and runs all 24 prespecified fits sequentially. Each seed/arm has three whole-task exclusion fits and one final fit. No development or diagnostic-evaluation input enters fitting. Quarantined examples remain excluded. Output directories are exclusively allocated; failed attempts are not overwritten or silently resumed.

The first attempt stopped before any optimizer step because Transformers 5 returns sets in native loading diagnostics. The receipt serializer now preserves those facts as sorted JSON arrays, with a fails-before/passes-after regression. The next attempt reached an actual optimizer step; its native event reported 1,459,637,248 allocated and 1,472,200,704 reserved GPU bytes. This is a first-update observation, not a whole-experiment peak or serving measurement.

Operative local execution state, authorization, logs and outputs are under `~/.cria/training/decision-qualified-v1/execution/`. The frozen recipe and qualification documents retain their original before-training permission state; execution authorization is recorded separately rather than retrospectively rewriting those receipts.

Training progress and loss do not establish classifier quality. Calibration, archived diagnostics, CPU parity/RSS/latency, the whole required serving-weight budget and fresh representative evaluation remain separate gates. Fresh evaluation still has zero cases; provisional assistant agreement is not human gold. No classifier was deployed and no production runtime dependency was added.
