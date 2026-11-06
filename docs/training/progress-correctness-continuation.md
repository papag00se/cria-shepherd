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

## Completed outcome

The run completed all **960 updates / two epochs** in **1,921.85 seconds (32.0 minutes)**. No TEST was opened or scored. The process exited and the RTX 3090 returned to idle. Peak Torch reserved memory was 11,429,478,400 bytes (10.64 GiB); this is the Torch allocator measurement, not total process/system RAM.

| Native FP32 DEV metric (600 rows) | Starting repaired checkpoint | Epoch 1 — selected | Epoch 2 |
|---|---:|---:|---:|
| Accuracy | 302/600 = 50.33% | 398/600 = 66.33% | 396/600 = 66.00% |
| Macro-F1 | 0.50846 | **0.66258** | 0.56730 |
| DONE recall | 133/200 = 66.5% | 118/200 = 59.0% | 6/200 = 3.0% |
| PARTIAL recall | 65/200 = 32.5% | 84/200 = 42.0% | 194/200 = 97.0% |
| NOT_STARTED recall | 104/200 = 52.0% | 196/200 = 98.0% | 196/200 = 98.0% |
| PARTIAL incorrectly called DONE | 121/200 = 60.5% | 116/200 = 58.0% | 6/200 = 3.0% |

**Selected new checkpoint:** `~/.cria/training/progress-correctness-v2/continuation-20261106T001652Z/epoch-1/`, under the declared highest-DEV-macro-F1 rule. It contains full native safetensors, config and tokenizer. Epoch 2 and both optimizer/RNG files remain alongside it. This is the actual continued checkpoint, not another application of the old 74-value repair. Do not reapply the old repair to these trained weights. The original source checkpoint remains separate and unchanged.

The aggregate improvement is largely NOT_STARTED separation: of 96 additional correct DEV answers in epoch 1, the class-wise changes are **−15 DONE, +19 PARTIAL, +92 NOT_STARTED**. Restricting attention to the 400 DONE/PARTIAL examples, correctness moves only 198/400 to 202/400. False-DONE remains high, and epoch 2 largely collapses DONE back into PARTIAL. Thus this run improves aggregate DEV metrics but does **not** establish improved requirement-correctness discrimination. No causal explanation for the remaining confusion was established by this run.

Both trained epochs score 32/32 on each old-family TRAIN diagnostic subset (64/64 combined), versus 30/32 dictation and 32/32 retrospective initially. This is exposed TRAIN replay, not a full old-family qualification or independent generalization result. New checkpoint INT4 conversion/fidelity, full old-family validation, and untouched TEST evaluation have not been performed. Nothing is deployed or published.

Authoritative results: `baseline.json`, `epoch-{1,2}-report.json`, `selected.json`, and the completed event in `events.jsonl`. `opened-dev-example.json` includes one complete rendered DEV input, all three recorded responses and `reasoning: null`: the incident-record diff deletes both private contact fields correctly; epoch 1 still chooses DONE narrowly, while epoch 2 switches to PARTIAL. It illustrates a real lost completion, not a claim that every such change is wrong.

Existing focused progress tests: 10 passed, 2 skipped. Runner compiled successfully. No new automated runner tests were added; the real run is the integration exercise, and recovery/selection behavior does not yet have dedicated automated coverage. An inherited Transformers configuration warning was emitted during loading; the requested repaired scoring row was verified exactly before work proceeded.
