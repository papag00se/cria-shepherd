# Synthetic progress continuation from the repaired checkpoint

Operator-authorized launch: 2026-11-06 UTC. This is gradient training, separately authorized after the earlier gradient-free repair. No deployment, publication, new TEST inspection or TEST scoring is authorized by this run.

## Exact source and data

- Start from `~/.cria/training/progress-v1/weight-study-20261104/int4-repair/checkpoint/`, the saved native repaired checkpoint—not the pretrained base or unedited progress checkpoint. The loaded scoring row is checked against that checkpoint before any update. The source remains unchanged.
- Use all 3,000 examples in `~/.cria/training/progress-correctness-v2/train-3000-candidate.jsonl` each epoch, alongside all 836 existing dictation/retrospective TRAIN examples from `gliclass-v4-edge-expanded-v2/train-001/train-cases.json`.
- DEV: all 600 examples in `dev-600-candidate.jsonl`, baseline and after each epoch. A deterministic 64-example old-family TRAIN panel provides preservation diagnostics; it is neither a held-out test nor a replacement for later qualification.
- Inputs are fully rendered with native policies. No clipping or dropping. The initial length census found a maximum of 2,005 tokens across TRAIN/replay/DEV.

## Configuration

One session on RTX 3090 UUID `GPU-907a7f7a-b541-8208-2bce-e1361e3110d6`; two epochs, full-active-graph FP32 master weights and AdamW states, BF16 autocast, FP32 calibrated logits and the established CE+Brier objective. Peak learning rate `5e-6`, 5% warmup/cosine schedule, zero weight decay, microbatch one, gradient accumulation eight, seed 17, TF32 off. Reuses non-reentrant gradient checkpointing and the established DeBERTa monotone-gather backward. Task/family/label weighting and label-order permutations reuse existing training helpers.

There are 3,836 examples per epoch and 480 optimizer updates per epoch, 960 total. No extra hyperparameter search or prolonged benchmark precedes this run. Save each epoch's native checkpoint, tokenizer and optimizer/RNG state separately. Select highest DEV macro-F1 among the fixed run's epochs; this does not establish TEST generalization, old-family preservation or INT4 fidelity.

## Launch and artifacts

Runner: `suite/progress_correctness/train.py`, reusing `gliclass_train`, `progress_loto`, `training_updates` and `onejev_train` primitives. Source, datasets and live bundle are not overwritten.

```bash
CUDA_VISIBLE_DEVICES=GPU-907a7f7a-b541-8208-2bce-e1361e3110d6 \
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=4 \
"$HOME/.cria/training/onejev16-trained-v1/venv/bin/python" \
  -m suite.progress_correctness.train \
  --out "$HOME/.cria/training/progress-correctness-v2/continuation-NEW-RUN"
```

The actual initial launch is detached, PID 1779643, output `~/.cria/training/progress-correctness-v2/continuation-20261106T001652Z/`; stdout/stderr are in the adjacent `.log`. `run.json` records settings, `events.jsonl` records loading/updates/epochs, and baseline/epoch DEV and old-TRAIN-panel predictions remain separate. `epoch-N/` holds weights; `epoch-N-optimizer.pt` holds optimizer and RNG state. `selected.json` identifies the DEV-selected checkpoint without moving or deleting other epochs. PID is historical provenance, not proof a process remains running. Consult actual events for outcome; loading or baseline evaluation alone is not a completed training update.

Existing focused progress tests: 10 passed, 2 skipped. Runner compiled successfully. No new automated runner tests were added; the real run is the integration exercise, and recovery/selection behavior does not yet have dedicated automated coverage. An inherited Transformers configuration warning was emitted during loading; the requested repaired scoring row was verified exactly before work proceeded.
