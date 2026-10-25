# Optional local decision classifier

The operator authorized an optional CPU-only, in-process GLiClass provider on 2026-10-25. This replaces the provider for two existing judgments; it does not add a planner, code author or completion authority. [Training tools and methodology](training/methodology.md) explains how the artifact was made. [Expanded v2 results](training/gliclass-expanded-v2.md) disclose evaluation exposure and limitations.

## Dependency boundary

Ordinary installations retain their existing dependencies and behavior. The optional serving environment uses `onnxruntime==1.31.0` and `tokenizers==0.23.3`, with their ordinary transitive dependencies. Serving does **not** load PyTorch, Transformers, the training SDK, pretrained floating weights or a CUDA provider. The operator's approval is specific to this optional production inference feature, not a general removal of the stdlib-first policy.

An immutable model/tokenizer can be shared by requests in one service; guard decisions and session state cannot be cached globally. Inference is serialized to bound simultaneous CPU attention allocations. The ONNX Runtime CPU arena has a **16 GiB allocation ceiling**, shared by these sessions in one process; unused activation chunks are released after each run. This is an activation allocator bound, not a claim that total process RSS is at most 16 GiB. Model and tokenizer stay on the cria host; no workspace or network access is needed to classify a string already in memory.

## Two seats, not every reasoner call

1. **Compaction retrospection:** classify the complete candidate briefing as RETROSPECTIVE or PLAN. Only RETROSPECTIVE permits the **existing independent task-scope and evidence-fidelity checks** to proceed. Those checks remain reasoner judgments and can still reject a briefing.
2. **Directive dictation:** classify the complete public directive as DESCRIBES or DICTATES, including prose that did not trigger the old code-shape prefilter. Only DESCRIBES clears this particular guard; grounding and the other directive checks still apply. Neither zero detected code spans nor an exact match to previously observed code can overrule DICTATES: presence does not establish quotation rather than operative instruction. DICTATES enters the existing prose-rewrite path, or withholds the directive when no rewrite is available. A rewritten directive is judged again with its actual complete text.

When the feature is disabled, the existing reasoner and shape-trigger path is unchanged. When enabled, a classifier error, nonfinite result, invalid result or input that exceeds the native window must not approve a briefing or optional directive. No clipped-input classification, chunk vote, lexical answer or silent reasoner substitution is permitted. The frozen tokenizer window remains 16,384 tokens, but fitting that window does **not** guarantee sufficient CPU memory: large complete inputs can be declined by the allocation ceiling. A resource probe of a full-window input found one temporary buffer requesting 32 GiB by itself. The bound prevents that allocation rather than shortening the input or pretending to classify it. A bad enabled bundle or unavailable dependency is a startup error, not a successful start with the feature silently disabled.

The original root task, completion gate, workspace survey, harness sandbox, sampling roles and planning policy are independent. Planning remains OFF unless the operator separately enables it.

## Configuration

Install the optional extra in the interpreter used by the service:

```sh
python -m pip install '.[system1]'
```

The production bundle is local and self-contained, not a pointer to an experiment's mutable environment. It includes the actual graph/external weights, native tokenizer and frozen policy/configuration metadata. Its manifest binds the exact bytes; admission must reject changes, missing shards and invalid mappings before serving.

```toml
[system1]
enabled = true
bundle_dir = "/absolute/path/to/the/admitted/bundle"
threads = 6
```

Omit the section or set `enabled = false` to retain existing behavior. Supplying a bundle path alone does not enable the classifier. `threads` must be a positive integer. Unknown keys and wrong types are errors.

## Admission and observability

Admission compares the production tokenizer's exact complete token IDs and prepared native inputs with saved native SDK packets, then compares actual CPU logits and decisions with the frozen saved INT4 calls. This checks serving fidelity, **not a new semantic evaluation**. Existing TRAIN exposure remains exposure. Resource measurements distinguish cold load, warm inference, process RSS, one/two concurrent callers and complete long inputs; the sub-250 MB weight artifact is not a promise of a sub-250 MB process.

Actual classifier calls must retain their complete public input, frozen policy/labels, logits and decision through the existing call-capture facility when capture is enabled. Native classifier captures live under `<session>/system1/`, in their own restart-safe sequence, with real native request/response fields—not fabricated chat requests or `choices` responses. They emit no `upstream.dump`, do not shift upstream sequence numbers, and cannot invalidate the suite's generated-LLM capture evidence. Existing suite upstream-call and generation-throughput metrics describe the LLM requests; native CPU classifier calls and timing are recorded separately through `system1.judgment`/`system1.error` and their capture pointers. Structured decision/error events establish which provider actually ran and why an optional directive or briefing was withheld. Runtime evidence must never be reconstructed by counting words in prose.

### Expanded v2 serving admission (2026-10-25)

The admitted standalone bundle is `expanded-v2-live`, manifest SHA-256 `854cb99b7ca61ac618f6065b13c9d768790336dc75968ff9176dd097be6e301a`. Its graph plus external weights occupy **239,829,455 bytes**. Final-source qualification found:

- **194/194** saved INT4 calls reproduced their complete native inputs, token IDs and decisions, with logits checked at `rtol=atol=0.0002`; **836** canonical TRAIN packets matched native rendering/tokenization. This is fidelity, not fresh accuracy; the calls comprise 64 reserved synthetic examples and 130 TRAIN-exposed real examples.
- On a host also running regression checks: cold load plus startup self-tests **8.22 s**; warm mean **1.11 s**, median **0.93 s**, p95 **2.45 s**; ordinary qualification peak RSS **1.19 GB** (decimal). Two callers serialized. These are observations, not a controlled latency comparison.
- An exact **16,384-token** constructed resource vector was declined by the bounded allocator in **7.08 s**: one buffer requested **34,359,738,368 bytes**. Peak RSS was **13.09 GB**, and a subsequent short call succeeded, with RSS then **433 MB**. The safety probe also imposed a process-local 32 GiB address-space limit; serving does not impose that process-wide limit. The actual refusal came from the 16 GiB ORT arena, not clipping or a changed window.
- The optional Python 3.13 environment passed **194** runtime, package, capture, configuration, wiring, annotation and installed-wheel tests, including the real engines. The separate complete-repository release gate passed **11,238 tests**, with **241 skips** and **4,491 subtests**; its before/after source hashes were unchanged.

Complete final qualification calls are retained at `~/.cria/calls/system1-serving-v2-20261025/qualification-003.jsonl`, SHA-256 `e446e4af829aad7fa9c5d2992789db84c372587384c76f31b54353f0c20d1e65`. Training remains as described in [methodology](training/methodology.md); serving uses neither training dependencies nor GPU inference.

A fresh `ornith1.5_9b / Java` cell must run through the existing sandboxed suite launcher, with planner OFF, call capture enabled and the newly deployed source/configuration identified. Its independent archived-workspace usefulness judgment is separate from all the classifier scores. Do not alter assists or prompts during that cell, or publish a checkpoint as its final result.
