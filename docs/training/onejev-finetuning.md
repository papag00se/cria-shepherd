# OneJev fine-tuning and authorized GLiClass follow-up

## Operator direction

The operator explicitly requested training OneJev after its untrained Q4 replay. The RTX 3090 is already approved for clearing and training; do not ask again. Do not touch the RTX 3080 or deploy either candidate.

The follow-up is also authorized: **if trained OneJev remains insufficient, quantize GLiClass v4 Edge to four bits and test it; if that initial quantized result is not strong, train GLiClass and test the trained four-bit export**. This is not permission to rerun the rejected 68M matrix. The original production weight budget and in-process/runtime requirements remain separate gates; the OneJev size exception is experimental only.

The earlier [OneJev result](onejev-q4-experiment.md) was **untrained**. It does not establish what this fine-tune can achieve.

## Frozen single-fit recipe

Private root: `/home/jesse/.cria/training/onejev16-trained-v1/`; active qualified attempt: `run-002/`.

- Official source checkpoint `OmniJev/OneJev1.6-0.8B`, revision `c89933c277629b707895bff752c61d2b0664c85e`.
- Full language-model fine-tuning, not an inference-only test or a new randomly initialized classifier. Every language-model parameter belongs to the optimizer exactly once. Vision is not part of these text-only questions.
- The same **514 admitted real TRAIN examples**; no synthetic rows, quarantine releases, rewritten labels or changed source partitions.
- Native typed-choice prompts, full original `complete_input`, original frozen semantic policies. The shared request builder is used by training and the native Q4 evaluator. No cropping, input splitting, chunk voting or generated-reasoning targets.
- One seed (17), one full fit, **12 fixed epochs**, peak learning rate `5e-6`, 5% linear warmup and cosine decay. The first scheduled step has learning rate zero, explicitly logged.
- Microbatch one complete example; accumulation to 16 examples, using the actual batch length for the final short batch. Every TRAIN row appears once per epoch.
- FP32 master weights and native answer-slot readout; BF16 decoder autocast. Eager attention and the PyTorch reference gated-delta implementation are fixed. Gradient checkpointing is non-reentrant. No TF32 or automatic precision/batch/input substitutions.
- AdamW, zero weight decay, `foreach=False`, gradient clipping norm 1. The declared GPU allocation bound is 22 GiB.
- Cross-entropy plus Brier loss over the native A/B answer slots, with weight 1 on Brier. This follows the official trainer's restricted-slot objective, not full-vocabulary text generation.
- Explicit new balancing: each observed task/head/label stratum has equal total weight, `N/(K*n_stratum)`. This is **label balancing**, unlike the old smaller-encoder task/head weighting. It is a new recipe, not a retrospective change or proof that the old weighting caused the earlier weakness.
- Native option order alternates by epoch and sorted source-row index; targets follow the SDK's returned label order. Both orientations are fully rendered before training. No other prompt/state augmentation is used. Inference keeps the original option order.
- No best seed, intermediate-epoch selection, fitted threshold, or full matrix.

The public settings are recorded in [onejev-finetuning-recipe.json](onejev-finetuning-recipe.json). The immutable private `contract.json` binds actual source files, policies, admitted exports, native checkpoint/tokenizer files, recipe and training source. Native encoded inputs, optimizer-step events, used learning rates, row IDs/orders, RNG states and rolling recovery checkpoints are recorded outside the workspace. The final FP32 HF reference is retained before supported `--no-mtp` conversion and standard Q4_K_M quantization.

## Mechanical check before the real fit

An eight-example native learning check runs before the full fit, then the real fit reloads the original checkpoint so the check cannot initialize training. It uses admitted examples covering both labels of both questions in two TRAIN tasks, 128 declared updates and the same optimizer/readout/update path.

The active attempt passed: exact optimizer membership; finite nonzero native gradients; changed first/last decoder witnesses and **both** answer-slot rows; **8/8 tiny targets learned**. That is a learning-mechanics check, not generalization. Full-dataset training has started.

The first attempt stopped **before any optimizer update** while serializing native Transformers loading facts containing sets. The repair reuses `suite.training_run.loading_receipt`, rather than creating another serializer. A regression fails before and passes after the repair. That failed attempt remains distinct from `run-002`; no failed result was overwritten or counted as training.

## Implementation validation

The source-bound full `python -m pytest` run passed **11,016 tests, 229 skipped**. The isolated training environment passed all **18 focused tests**, including actual accumulated parameter-update comparisons for one-, three- and sixteen-example batches, the independently calculated CE+Brier gradient, option-order/target mapping, probability ownership and the native loading-facts serialization regression. The real GPU learning check is separate from those unit tests and has also passed. None of this is a held-task quality score.

## Final testing

A detached finalizer waits for actual training completion, then converts/quantizes and runs the official native decision interface on the same **37 DEV plus 93 archive diagnostic examples** for both the original and trained Q4 model. Only the fixed final checkpoint is tested. Full state, policies, tokenization and native probability responses are captured. An exact frozen case count is an integrity check, not a row limit.

These are whole-task-held historical diagnostics, **not fresh evaluation or human gold**. No result from them changes training, selects an epoch, releases a held label or establishes production readiness. The trained model's actual disagreement packets must be inspected before judging whether it is sufficient and invoking the GLiClass follow-up.

## Conditional GLiClass candidate

Verified identity: [`knowledgator/gliclass-v4-edge`](https://huggingface.co/knowledgator/gliclass-v4-edge), revision `885af1af8a07edf4ed34df83ca0d995ed8201283`, Apache-2.0. The publisher describes an instruction-following 0.4B encoder with native per-label probabilities and no generated text. This is a distinct pretrained decision model, not the earlier raw-encoder proposal. Published benchmark claims are not local findings.

The official API accepts the state as text, the decision policy as `prompt` and the candidate descriptions as labels. Its own documented lossless path prepares the complete input with a deliberately non-truncating pipeline and **refuses** an excessive token count afterward. The usual pipeline's 2,048-token example must not silently clip our native contexts.

The [ONNX Runtime four-bit interface](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html#quantize-to-int4uint4) supports both constant-weight MatMul and Gather operators. Quantization must account for embeddings as well as linear weights, all required scoring/calibration parameters and the actual complete serialized bundle. No estimated size, published 8-bit file, linear-only quantization or model-card benchmark substitutes for measuring and testing our four-bit artifact. Native-versus-export fidelity must be checked before attributing a result to the candidate. A training follow-up uses original trainable weights and then re-exports/re-quantizes for the actual four-bit test; an unquantized training score is not the requested result.
