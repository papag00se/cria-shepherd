# Local decision classifier: technical reference

System 1 is the default CPU-only, in-process GLiClass provider for two existing judgments; it does not add a planner, code author or completion authority. For the concise visual introduction, see [System 1 guide](system1-guide.md). [Training tools and methodology](training/methodology.md) explains how the artifact was made; [expanded v2 results](training/gliclass-expanded-v2.md) disclose evaluation exposure and limitations.

## Dependency boundary

The standard installation uses `onnxruntime==1.31.0` and `tokenizers==0.23.3`, with their ordinary transitive dependencies. Serving does **not** load PyTorch, Transformers, the training SDK, pretrained floating weights or a CUDA provider. The CPU runtime is part of the standard installation; training dependencies remain separate.

An immutable model/tokenizer can be shared by requests in one service; guard decisions and session state cannot be cached globally. Inference is serialized to bound simultaneous CPU attention allocations. The ONNX Runtime CPU arena has a **16 GiB allocation ceiling**, shared by these sessions in one process; unused activation chunks are released after each run. This is an activation allocator bound, not a claim that total process RSS is at most 16 GiB. Model and tokenizer stay on the cria host; no workspace or network access is needed to classify a string already in memory.

## Two seats, not every reasoner call

1. **Compaction retrospection:** classify the complete candidate briefing as RETROSPECTIVE or PLAN. Only RETROSPECTIVE permits the **existing independent checks** to proceed: the reasoner's task-scope judgment, the typed file/change/size/build lenses, and figure grounding (`briefinggrounding`: every number-with-unit, version or URL host the briefing states must occur in the transcript, survey, check facts or task). The former one-word whole-briefing fidelity verdict no longer exists (replayed on real briefings it was blind on two of three); the lenses and the lookup replaced its signal. Those checks can still reject a briefing, and the classifier never overrides them.
2. **Directive dictation:** classify the complete public directive as DESCRIBES or DICTATES, including prose that did not trigger the old code-shape prefilter. Only DESCRIBES clears this particular guard; grounding and the other directive checks still apply. Neither zero detected code spans nor an exact match to previously observed code can overrule DICTATES: presence does not establish quotation rather than operative instruction. DICTATES withholds the directive (`refused_by='dictated_code'`, event `loop.steer_dictated_code`); no rewrite is requested, so nothing composed after the ruling reaches the coder, and the caller's own floor applies (refusal redirect, wheel-spin note, periodic check truth). Native DESCRIBES clears this guard whatever the legacy invented-span count says: a prose paragraph naming a check is not invented code to paste. Other grounding checks remain independent. Removing the former blind restatement does not establish classifier accuracy or coding usefulness.

When the feature is disabled, the existing reasoner and shape-trigger path is unchanged. When enabled, a classifier error, nonfinite result, invalid result or input that exceeds the native window is handed to the reasoner for the same complete-input judgment. An unreadable reasoner answer cannot approve the briefing or directive. No clipped-input classification or chunk vote is permitted. The frozen tokenizer window remains 16,384 tokens, but fitting that window does **not** guarantee sufficient CPU memory: large complete inputs can be declined by the allocation ceiling. A resource probe of a full-window input found one temporary buffer requesting 32 GiB by itself. Measured (2026-11-01, see the decision-log): peak activations are about `2.93 x 128 x n^2 + 0.22 GB` for `n` rendered tokens, so the 16 GiB arena holds at most about 6,725 tokens (about 6,600 of briefing after the policy), not the window. Every input over that ceiling is now refused BEFORE the model runs (`system1.token_ceiling`, derived from the configured arena by the measured formula less a 0.2% margin, 6,711 tokens at 16 GiB; `System1OverCeiling`, a `System1RuntimeError`, so the guard declines exactly as it does for an allocator failure): a 7,000-token input is declined by System 1 in 11 ms with no change in process memory instead of spending ~7 s of CPU and a ~13 GB spike before the allocator refuses it. The verdict of every input under the ceiling is unchanged (a 5,000-token real briefing: identical logits before and after). Reading less is not a way around it: chunked and structurally cut judgments disagreed with the full-text verdict on 25% and 20% of real inputs. The bound prevents that allocation rather than shortening the input or pretending to classify it. A bad enabled bundle or unavailable dependency is a startup error, not a successful start with the feature silently disabled.

The original root task, completion gate, workspace survey, harness sandbox, sampling roles and planning policy are independent. Planning remains OFF unless the operator separately enables it.

## Configuration

Install cria normally (`python -m pip install -e .`); the CPU runtime dependencies and System 1 bundle are included. Clones must fetch Git LFS objects before installation. The bundle is installed inside the `cria` Python package; startup fails if it is missing or invalid. A compatible replacement can be configured explicitly.

The production bundle is local and self-contained, not a pointer to an experiment's mutable environment. It includes the actual graph/external weights, native tokenizer and policy/configuration metadata, which cria loads directly from the bundle directory.

```toml
[system1]
enabled = true
bundle_dir = "/absolute/path/to/the/bundle"
threads = 6
```

System 1 is enabled by default and uses the bundle in `cria/system1_bundle` unless `bundle_dir` selects a compatible replacement. An explicit `enabled = false` changes these judgments to the legacy reasoner path; disable it only if you understand that consequence. `threads` must be a positive integer. Unknown keys and wrong types are errors.

## Serving fidelity and observability

Serving was checked by comparing the production tokenizer's exact complete token IDs and prepared native inputs with saved native SDK packets, then comparing actual CPU logits and decisions with the saved INT4 calls. This checks serving fidelity, **not a new semantic evaluation**. Existing TRAIN exposure remains exposure. Resource measurements distinguish cold load, warm inference, process RSS, one/two concurrent callers and complete long inputs; the sub-250 MB weight artifact is not a promise of a sub-250 MB process.

HTTP receive records (`*.json.receive.json`, written by `cria.receivecapture`) are transport companions, not additional upstream requests; they are not counted as model calls or phases.

Actual classifier calls must retain their complete public input, policy/labels, logits and decision through the existing call-capture facility when capture is enabled. Native classifier captures live under `<session>/system1/`, in their own restart-safe sequence, with real native request/response fields—not fabricated chat requests or `choices` responses. They emit no `upstream.dump`, do not shift upstream sequence numbers, and cannot invalidate the suite's generated-LLM capture evidence. Existing suite upstream-call and generation-throughput metrics describe the LLM requests; native CPU classifier calls and timing are recorded separately through `system1.judgment`/`system1.error` and their capture pointers. Structured decision/error events establish which provider actually ran and why an optional directive or briefing was withheld. Runtime evidence must never be reconstructed by counting words in prose.

### Expanded v2 serving (2026-10-25)

The standalone bundle is `expanded-v2-live`. Its graph plus external weights occupy **239,829,455 bytes**. Final-source qualification found:

- **194/194** saved INT4 calls reproduced their complete native inputs, token IDs and decisions, with logits checked at `rtol=atol=0.0002`; **836** canonical TRAIN packets matched native rendering/tokenization. This is fidelity, not fresh accuracy; the calls comprise 64 reserved synthetic examples and 130 TRAIN-exposed real examples.
- On a host also running regression checks: cold load plus startup self-tests **8.22 s**; warm mean **1.11 s**, median **0.93 s**, p95 **2.45 s**; ordinary qualification peak RSS **1.19 GB** (decimal). Two callers serialized. These are observations, not a controlled latency comparison.
- An exact **16,384-token** constructed resource vector was declined by the bounded allocator in **7.08 s**: one buffer requested **34,359,738,368 bytes**. Peak RSS was **13.09 GB**, and a subsequent short call succeeded, with RSS then **433 MB**. The safety probe also imposed a process-local 32 GiB address-space limit; serving does not impose that process-wide limit. The actual refusal came from the 16 GiB ORT arena, not clipping or a changed window.
- The Python 3.13 serving environment passed **194** runtime, package, capture, configuration, wiring, annotation and installed-wheel tests, including the real engines. The separate complete-repository release gate passed **11,238 tests**, with **241 skips** and **4,491 subtests**.

Complete final qualification calls are retained at `~/.cria/calls/system1-serving-v2-20261025/qualification-003.jsonl`. Training remains as described in [methodology](training/methodology.md); serving uses neither training dependencies nor GPU inference.

The two coding cells run with this classifier active (`ornith1.5_9b / Java`, planner OFF; independent terminal judgments 2% and 15% usefulness) are not classifier evidence: neither was an ablation, and the retained run records and call captures live under `~/.cria/suite/_campaigns/system1-v2-ornith-java-20261025` and `~/.cria/calls/`. What they taught is in [the decision log](decision-log.md) ("System1 deployment cells"). Those were the initial deployment cells, not the entirety of runtime use: the [November 6 runtime inspection](system1-runtime-evidence.md) finds recorded System 1 judgments in at least 191 distinct stored coding runs, traces actual policy enforcement and a real miss, and distinguishes firing from demonstrated coding benefit.

## Development runs on the GPU

Production System 1 is CPU-only. In development, judge on the GPU with `~/.local/share/cria/envs/system1-dev-gpu/bin/python scripts/system1_gpu_judge.py FAMILY IN.json OUT.json` (same `cria.system1` code and live bundle, CUDA provider; GPU and CPU verdicts matched 62 of 62 on real briefings, 2026-11-01). Use the CPU only when measuring timings.
