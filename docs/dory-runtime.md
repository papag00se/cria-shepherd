# NVIDIA Dory 1.0 4B: deployment and optimization options

Investigated 2026-10-20. This is an operational installation, not a change to cria's assists or planning policy.

## Installed identity and intended profile

- Fleet identity: `dory1.0_4b`; select with `llama-fleet switch dory1.0_4b` after obtaining the shared GPU/service window.
- Source: `~/src/llama.cpp-dory`, NVIDIA contributor's `dory-support` branch pinned to `9e2f3be3947a7339ac8b93f9b9a8dabb8eeaf144`.
- Runtime: `~/.local/share/cria/fleet/runtimes/dory-9e2f3be/bin/llama-server`.
- Artifact: `~/models/cria/dory1.0_4b/NVIDIA-Nemotron-Labs-Dory1.0-4B-Q5_K_M.gguf`, 3,673,288,864 bytes, publisher SHA256 `96080be49ffd67b916018b7bdef8c484762576fb52780e10ab98ac4978a660e0`, repository revision `0963c8000791e77b2b1b49aa387d92a6da9988d6`. Both download-stream and independent disk checks passed.
- Operator-requested **three loops**, separate per-loop caches, 49,152-token configured context, one slot, Q8 K/V cache, Flash Attention, full RTX3080 offload, no context shifting. This is a configured capacity, not a statement that long-context coding quality has been evaluated.
- Temperature 1.0, top-p 0.95, top-k 0, min-p 0, repetition penalty 1.0. Reasoning and Jinja tool calling enabled. No speculative strategy selected by default.
- No automatic service enablement or live-model replacement. `llama-fleet plan dory1.0_4b` prints the exact launch.

## Validation completed

The CUDA build completed successfully; its installed runtime resolves GGML/llama libraries and CUDA user-space dependencies from the fleet paths. All 16 local fleet-tool tests pass, including the new profile tests demonstrated failing before Dory registration and passing afterward.

A three-loop **CPU-only**, 4,096-context, F16-cache API smoke passed: model identity/context, plain chat, unconstrained `get_weather` city arguments, a tool-result continuation and streamed output. Exact requests and full responses are retained in [cpu-smoke-calls.json](/home/jesse/.local/share/cria/fleet/runtimes/dory-9e2f3be/cpu-smoke-calls.json). The tool call had empty assistant content despite `force_nonempty_content=true`, consistent with that variable being absent from the actual embedded template.

The RTX3080 was serving an active campaign. No live service, model, GPU allocation or campaign was stopped or restarted; the RTX3090 was also left untouched. Consequently, this does **not** establish that the configured 49,152-context/Q8/Flash-Attention GPU profile fits, is faster, or preserves long-context coding quality. Service installation is complete but activation and GPU qualification remain pending a free shared-GPU window. No speculative strategy is represented as Dory-benchmarked.

## Options, including what is NOT ready

### 1. Full GPU placement: important correctness/performance prerequisite

Use `--gpu-layers 999 --fit off --split-mode none --device CUDA0`. The selected revision fixes CPU placement of the BF16 normalization/gating/scale vectors. The older model-card pin predates that fix. Merely saying 'all transformer layers offloaded' was not enough to establish that these small tensors were on the GPU.

The upstream discussion still identifies incorrect partial-offload accounting for physical versus recurrent virtual layers, and an unresolved tensor-split crash. Do not choose a partial-offload or tensor-parallel profile as a supposed optimization. A CPU-only validation does not qualify GPU placement or GPU memory fit.

### 2. Flash Attention

This is the fused attention implementation, reducing attention memory traffic and temporary allocations. The model-card example disables it, but the current branch's CUDA discussion explicitly exercises it enabled. Our CUDA build includes the kernels; it is selected in the intended GPU profile. Test on/off at equal context, prompt, loop count and cache precision before attributing a speedup. Q8 V cache requires an appropriate Flash Attention path; turning Flash Attention off is not an independent toggle for every quantized-cache combination.

### 3. KV-cache precision

`--cache-type-k` and `--cache-type-v` choose the precision of the stored attention history independently of the GGUF weight precision. F16 is the conservative numerical baseline; Q8_0 reduces storage to roughly half F16 plus block metadata, and Q4 formats reduce it further at a larger numerical-risk tradeoff. Savings apply to the cache, not the whole process. Q8 is configured for the normal fleet context, but neither an API smoke test nor a matching short answer establishes long-context equivalence. Q4 should remain an experiment until tool use, retrieval beyond the sliding window and long coding sessions are checked.

This is ordinary llama.cpp quantized KV, not evidence that an unrelated TurboQuant, Prism, KIVI or other custom cache fork supports Dory. Those integrations require their own architecture and numerical validation.

### 4. Per-loop versus last-loop cache sharing

Default:

```text
--override-kv dory.num_loops=int:3,dory.recurrent_kv_cache_mode=str:per_loop
```

Optional experiment:

```text
--override-kv dory.num_loops=int:3,dory.recurrent_kv_cache_mode=str:last_loop
```

`last_loop` keeps one recurrent-layer cache instead of one per loop. It does NOT reduce all process memory by three, because input/output caches, model weights, scratch and other overhead remain. More importantly, it changes the computation: earlier loops read historical final-loop keys/values. Prefill chunk size can change results as well. This is not a transparent lossless compression switch. Upstream vLLM discussions also flag sliding-window boundary issues; those are not automatically proven to affect llama.cpp identically, but reinforce the need for boundary/long-context tests. Keep `per_loop` as the default requested three-loop deployment.

### 5. Sliding-window allocation, context and prefix reuse

Dory mixes local 1,024-token sliding attention with full attention. llama.cpp's default compact SWA allocation (`swa_full=false`) is already selected; `--swa-full` allocates more history and is not a free speedup. It may be useful for particular reuse/rollback experiments at a memory cost.

Context size and `--parallel` multiply important allocations. Use one slot for a single coding agent. Increasing concurrency is a throughput tradeoff, not generally a single-user latency optimization. Do not advertise the training maximum of 262,144 tokens as this 10GB GPU's validated runtime capacity.

Ordinary identical-prefix prompt caching avoids reprocessing stable conversation prefixes; benchmark cold prompts separately from reused prompts. RAM prompt caches, context checkpoints and slot persistence can help repeated conversations but cost host memory. This build's default RAM cache budget is 8 GiB, so account for that on this already busy workstation. Non-prefix cache shifting/reuse is a different feature: Dory explicitly rejects context shifting. Keep `--no-context-shift`; do not casually enable shifting-based reuse or promise an unlimited conversation.

### 6. N-gram speculation: available generic candidate, no extra neural model

The runtime contains `ngram-simple`, map-based variants, `ngram-mod` and `ngram-cache`. They propose repeated token sequences from history and let the target verify them. This can help repeated code, boilerplate and copy-heavy tasks; fresh reasoning may provide little to reuse, and proposal/verification overhead can make it slower. No second model or MTP head is required. This does not skip the three-loop target verification.

Candidate experiment: `--spec-type ngram-mod`, varying its min/max draft length on representative coding sessions. Record actual proposed/accepted counters and both cold and reused latency; do not infer improvement from the flag being accepted. Currently OFF by default: not Dory-qualified on the occupied GPU.

### 7. Native MTP: not present in this Dory integration

Multi-token prediction (MTP) uses specially trained prediction heads, not merely a generic runtime switch. The published Dory architecture and this branch's Dory tensor loader/graph have no MTP head or MTP-specific graph. Other fleet models' `draft-mtp` settings are not transferable. Do not enable `--spec-type draft-mtp` for this artifact.

### 8. Separate neural draft models and trained draft adapters

Generic `draft-simple` exists in this runtime, but a useful draft must have compatible tokenization and sufficiently high agreement to repay its own computation. No verified, published Dory-specific small drafter or EAGLE3/DFlash/DSpark adapter was identified in this investigation. That is a bounded search result, not proof that none can exist.

A one-loop copy of Dory drafting for the three-loop target is interesting, but ordinary separate-model loading duplicates runtime state/weights and does not automatically share intermediate loop activations or early caches. This branch does not expose a ready-made shared-weight, different-loop self-drafting implementation. Do not describe loading the same GGUF twice as the optimized research implementation. It needs integration work and measured acceptance/memory/latency.

### 9. Loop-based self-speculation and wavefront decoding: real experimental work elsewhere

The NVIDIA vLLM PR author describes an initial one-loop-draft/four-loop-verify implementation with shared weights and reuse of early caches/activations. A separate public experimental repository implements wavefront decoding: several tokens progress concurrently at different loop depths. Its fused NVFP4 matrix-vector kernels, fused attention/MLP/residual operations and INT8 output head are additional optimizations.

These are **not flags in our installed llama.cpp server**. The experiment targets RTX4090 and non-GGUF checkpoints, with vLLM patches and custom kernels. Our RTX3080/3090 are Ampere, so neither published 4090 timings nor its tuned kernels establish support or speed here. Native NVFP4 acceleration is a newer-hardware feature; format support through dequantization/emulation is not native FP4 arithmetic. Keep this as a separate backend experiment, not an untested fleet replacement.

The experiment also distinguishes per-loop wavefront behavior from approximate shared-cache behavior. A shared-cache wavefront can change the distribution further; 'speculative' alone does not guarantee equivalence to ordinary sequential per-loop inference in every implementation.

### 10. Weight formats

Use the official Q5_K_M artifact initially. The PR author states that it includes quantization-aware distillation; converting and quantizing the BF16 checkpoint yourself does not reproduce those trained weights. BF16 costs more memory; alternative Q4/Q8 formats need quality and throughput measurement. Reducing byte size is not sufficient evidence of a faster kernel or a better coding model. MXFP8/NVFP4 releases belong to a different serving-format path, not automatic drop-in improvements for this GGUF runtime.

### 11. CUDA graphs, kernel selection and prompt batch sizes

This build targets compute capability 8.6 (both local Ampere GPUs), with CUDA graphs and Flash Attention enabled at build time. Graphs reduce repeated kernel-launch overhead; do not disable them as routine tuning. Large recurrent graphs should still be profiled for actual graph capture/replay rather than assuming all operations are fused.

The initial prompt batch and microbatch are both 512, matching the reference. Increasing `--batch-size`/`--ubatch-size` can improve prefill throughput but increases scratch and may alter `last_loop` semantics. Compare 256/512/1024 at a fixed prompt/history/cache mode, separating prompt processing from token generation. MMQ versus cuBLAS forcing is a separate build experiment; the default chooses suitable paths, and forcing one globally can improve one phase while hurting another. Flash Attention kernel variants, CUDA-graph options and a fused Dory-specific residual/normalization kernel are profiling/development candidates, not established gains on this machine.

### 12. Deliberate quality/compute choices

Loop count 1-4 is supported. Three is retained exactly as requested; the downloaded GGUF's own metadata defaults to FOUR, so the explicit three-loop override is essential. Reducing loop count is not an invisible optimization of the same computation. Similarly, disabling reasoning (`chat_template_kwargs.enable_thinking=false`), using the embedded template's `medium_effort=true` efficiency hint, changing sampling, or shortening generated answers changes behavior rather than making an equivalent three-loop server faster. The setup does not impose a short coding-output cap for latency.

The actual GGUF template was inspected in full. It recognizes `enable_thinking`, `medium_effort` and `truncate_history_thinking`; it does NOT reference the model card's suggested `force_nonempty_content` variable. Sending that variable therefore does not establish that the published template will honor it. The CPU smoke sends it as documented but separately verifies actual tool-call parsing and continuation; it does not claim that the option was implemented. No local replacement template or model-facing assist was added.

## What to measure before selecting further defaults

Use equal prompts, fixed loop count, matched prefill chunks, one excluded warmup and multiple measured repeats. Capture exact requests and complete responses, server placement and native timings, process GPU memory, time to first useful output, prompt throughput, decode throughput, and speculative proposed/accepted counters. Separate cold prompt processing from prefix reuse. Include unconstrained tool arguments, a real tool-result continuation, streaming, code/reasoning tasks, and retrieval on both sides of the SWA boundary. Do not execute generated code outside the project's existing sandbox policy. Smoke success is not a usefulness score or long-context quality qualification.

## Sources checked

- Official GGUF model card: https://huggingface.co/nvidia/NVIDIA-Nemotron-Labs-Dory1.0-4B-GGUF
- Official BF16 architecture config: https://huggingface.co/nvidia/NVIDIA-Nemotron-Labs-Dory1.0-4B-BF16/blob/main/config.json
- llama.cpp Dory support and GPU-placement/partial-offload discussion: https://github.com/ggml-org/llama.cpp/pull/30306
- Pinned implementation: `src/models/dory.cpp`, `src/llama-model.cpp`, `src/llama-context.cpp`, `src/llama-kv-cache.cpp`, `common/speculative.cpp`, `common/arg.cpp`, `common/common.h`, `ggml/src/ggml-cuda/` in the installed source tree.
- vLLM Dory PR and self-speculation discussion: https://github.com/vllm-project/vllm/pull/60149
- Experimental fused kernels/wavefront implementation and limits: https://github.com/chrisbennight/dory-vllm-experiments

Read this guide together with the [local validation status](/home/jesse/.local/share/cria/fleet/runtimes/dory-9e2f3be/validation.json). Configuration, successful CPU requests and actual GPU qualification are distinct facts.
