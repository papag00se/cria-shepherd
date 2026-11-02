# Recommended settings per model

**Naming policy:** use the [official project names](model-names.md), owned by `suite/model_names.py`. `gemma4_12b` is one logical model across its historical and QAT quantizations. Service names, paths and old run IDs below are retained as executable aliases/provenance, not extra model identities.

**cria's source of truth** for the CURRENT local model fleet on `127.0.0.1:18084`. (Ported from codex-local and now maintained here.) Keep it updated when settings change or a model is added/verified. Retired, replaced, and rejected models — and why — live in [`model-history.md`](model-history.md), not here.

Settings live in **two files**, split by whether they need a model reload:

| Layer | File | Holds | Changing it needs |
|---|---|---|---|
| **Server launch** | `~/.config/llama-fleet/models.toml` (read by `llama-fleet`) | model source, quant, **ctx**, KV, GPU layers, chat template | a **model-server restart** (`systemctl restart llama-<model>`) — rare |
| **Client / per-role** | `~/.cria/cria.toml` `[roles.<role>]` | **sampling** (temperature/top_p/top_k/repeat_penalty/min_p/max_tokens) + **reasoning** | a **cria restart** (seconds) — no model reload |

cria attaches the **role's** sampling + reasoning to **every request** it makes for that role (`temperature`, `repeat_penalty`, … and reasoning as `chat_template_kwargs.enable_thinking`). The launcher's sampling is only a fallback — so tune in `cria.toml`, not `models.toml`.

> **One model at a time** (`-np 1`). Swap with `systemctl` (the `llama-fleet` launcher reads `models.toml`); see §Server launch.
> **The canonical cria fleet is pinned to the RTX 3080 at UUID `GPU-393d4998-707c-0ef0-a514-761015477256`.** The RTX 3090 belongs to the operator: when they release it, a second interchangeable `ornith1.5_9b` slot is served from it on `:18184` (and `:18284` forwards to `:18084`); any other use is the operator's call; parallel battery lanes serve the 3090 through `suite/lanes.py` ([Parallel lanes](../suite/README.md#parallel-lanes-one-cell-per-slot-both-gpus)). The GTX 1080 is not a cria device. Historical experiments described later in this file used other cards and are not current launch guidance.
>
> **What boots, and how to check.** The systemd unit enabled at boot for `:18084` is `llama-defiant-fable.service`, whose drop-in runs `llama-fleet serve qwen3.8_9b_distill` (the logical model `qwen3.8_9b_distill`; "defiant-fable" is only the historical service name). After a reboot the 3080 therefore comes up serving `qwen3.8_9b_distill`, **not** the model a campaign or live deployment may expect (`ornith1.5_9b` is started by `llama-ornith-q6.service`, which is not enabled). Always confirm the id before trusting a measurement: `curl -s localhost:18084/v1/models` (the `model` field), and swap with `llama-fleet switch <model>` / `scripts/swap_and_test.sh`, never by editing a unit.

---

## Per-model recommended settings

Sampling is **client-side** (`cria.toml`); set the role you're driving to these. Server launch (`models.toml`) has model-specific runtime, context, cache and batching settings (see §Server launch); inspect `llama-fleet plan MODEL` for the current executable profile.

| Model | Quant | Recommended sampling | Source | Notes |
|-------|-------|----------------------|--------|-------|
| **bonsai2** (27B; key was `ternary-bonsai-2` until 2026-09-27) *(was ternary-bonsai; Bonsai 1 retired + deleted 2026-09-18, sampling carried over unchanged)* | PQ2_0 (custom ternary g128) | **per-role, CANONICAL (m15-verified — see block below)**: coder `0.2/0.95/20`, reasoner `0.6/0.90/40`, classifier+compactor `temp 0`; `repeat_penalty 1.1` all | PrismML (Qwen3.6-derived) | needs Q2_0_g128 kernels (§Server launch — TurboQuant merged fork); ~8.0 GB on the 3080; `n_ctx_train` **262144** (comfortable @ 48K) |
| **dory1.0_4b** (NVIDIA Nemotron-Labs-Dory1.0-4B, **three recurrent loops**) | Q5_K_M | coder/reasoner `temp 1.0, top_p 0.95, top_k 0, min_p 0, repeat_penalty 1`; classifier/compactor `temp 0`, no top-k/min-p restriction, repeat penalty 1 | [NVIDIA GGUF](https://huggingface.co/nvidia/NVIDIA-Nemotron-Labs-Dory1.0-4B-GGUF) | **Added 2026-10-20; registered, not activated.** Dedicated Dory runtime `9e2f3be`; 49,152 context, per-loop Q8/Q8 cache, Flash Attention, batch/microbatch 2048/1024, no context shifting or RAM prompt snapshots. No drafting by default; optional ngram-simple 12/32 for copying, no native MTP. RTX3090 measurements: ~56 tok/s on the short-context throughput workload; 39.2 tok/s at 46,039 input tokens, but that answer was only seven tokens—not a sustained decode benchmark. Copy-only drafting reached ~278 tok/s, not general coding speed. RTX3080 qualification and coding-usefulness evaluation remain pending. See [runtime, evidence and optimization guide](dory-runtime.md). |
| **nemotron-elastic** (NVIDIA Nemotron-Labs-3-Elastic 12B-A2B) | Q4_K_M | coder/reasoner `temp 0.6, top_p 0.95`; classifier/compactor `temp 0` | [mradermacher GGUF](https://huggingface.co/mradermacher/NVIDIA-Nemotron-Labs-3-Elastic-12B-A2B-GGUF) (derived from DavidAU Elastic; exact historical stanza recovered from `models.toml.pre-retire-20260918`) | Historical path `/home/jesse/models/Nemotron-Elastic-12B/NVIDIA-Nemotron-Labs-3-Elastic-12B-A2B.Q4_K_M.gguf`; embedded template. Exact old per-model GPU-layer setting was inherited `auto`; current config preserves it explicitly. Q4_K_M is 9,641,803,360 bytes; downloaded from the verified repo and SHA-256 `7d6f134f14bde4b23dd3af537c510cb483b5119460b061b50a12a8747f0a22ce` matches its HF LFS OID. The same service ran successfully for 3d 13h (journal 2026-09-25); historical unit recorded 19.3G system memory peak / 9.1G swap peak, so observe host memory on reload. Historical 2026-09-27 ladder is L0–L4 only; old L5 is not a fresh result. |
| **ornith1.5_9b** (Ornith 1.5, 9B; executable alias `ornith1.5`, older alias `ornith15`) | Q6_K | coder `temp 0.6, top_p 0.95, top_k 20, min_p 0, presence_penalty 0, repeat_penalty 1`; reasoner `temp 1.0, top_p 0.95, top_k 20, min_p 0, presence_penalty 1.5, repeat_penalty 1` | [ornith-ai card](https://huggingface.co/ornith-ai/Ornith-1.5-9B-GGUF) | **Current Ornith as of 2026-09-05.** Reasoning + XML tool calls are native in the embedded template; 262144-token training context. Previous testing was Ornith **1.0**, not 1.5. Stock b9893 cannot load the MTP block; dedicated upstream 74a7c897 does. Service and native tool/reasoning-toggle smoke verified at ~82 tok/s. |
| **gemma4_12b** — current QAT quantization (executable alias `gemma4-qat`) | UD-Q4_K_XL (QAT) | `temp 1.0, top_p 0.95, top_k 64, repeat_penalty 1.1` — same as gemma4 | Gemma 4 defaults, deliberately identical to the gemma4 row | **added 2026-09-18** (`unsloth/gemma-4-12B-it-qat-GGUF`, 6.72 GB). Google's quantization-AWARE-trained 4-bit release: the low-bit weights are what the model was trained to be, not a post-hoc rounding, so the usual Q4 tax should be largely absent. Loads at 49152 ctx / 7842 MiB; `llama-bench` (prism b10685 build, q8_0 KV) pp2048 2779 · tg128 75.3 · **pp@8K 2399 · tg@8K 70.5** — SWA keeps its KV tiny (408 MiB non-SWA + 255 MiB SWA at 48K), so it barely slows with depth. Added ALONGSIDE `gemma4`, not over it, so no recorded score changes weights underneath it. **Caveat for the ladder: this is UD-Q4_K_XL vs gemma4's Q4_K_M — two variables (training method + quant recipe). The non-QAT repo also ships UD-Q4_K_XL (7.37 GB); run that arm before crediting any delta to QAT itself.** |
| **qwen3.8_9b_distill** (9B, Qwen3.8 distill) | Q6_K | `temp 0.6, top_p 0.95, top_k 20` | [empero-ai card](https://huggingface.co/empero-ai/Qwen3.8-9B-Distill-GGUF) | **added 2026-09-27.** `qwen35` hybrid with an inline **MTP head** (33 blocks). Upstream `7ac59a6` build. Measured on the 3080, decode on a code prompt / a whole-file-edit prompt: no spec 80/80 → `draft-mtp` n3 139/165 → **`draft-mtp,ngram-mod` n3 143/874 (LIVE)**. ub 2048 (+2% prefill), `-cms 2048` (real-traffic replay: −2% re-prefill; multi-slot and unlimited RAM cache measured no better). q8_0 KV, 48K, 8.9 GB. Tool calls + results verified; live cria/Codex run passed |
| **ling3.0_tiny** (7.9B-A1.3B MoE; executable alias `ling3-tiny`) | Q6_K | `temp 1.0, top_p 0.95, top_k 20` | [bloomer010 card](https://huggingface.co/bloomer010/Ling-3.0-tiny-GGUF) quoting inclusionAI | **added 2026-09-27.** `bailingmoe3` (18 KDA + 6 MLA layers, no MTP) — needs upstream ≥ 2026-09-20 (Ling tool parser + PEG UTF-8 fix). **f16 KV** (MLA KV is tiny; tg@32K 200 vs 181 at q8_0), ub 2048 (prefill +10–35%), `ngram-mod` n-min 16: decode 216 code / **1361 edit**. 48K, 7.1 GB. Occasional mid-think termination is documented by the quantizer as inherent to the weights |
| **phi4** (14B dense; LocalAI function-call fine-tune replaces the original weights) | i1-Q4_K_S | `temp 0` all roles; unchanged | [LocalAI-io fine-tune](https://huggingface.co/LocalAI-io/LocalAI-functioncall-phi-4-v0.3), [imatrix GGUF](https://huggingface.co/mradermacher/LocalAI-functioncall-phi-4-v0.3-i1-GGUF) | **Operator replacement, 2026-10-11**, not another battery row. Full 16K context, K q8_0 / V q4_0 and ngram settings retained. Tool integration is still under validation; not yet ready for a coding attempt. See [replacement protocol and verification](#phi4-function-call-replacement). Original scores/captures retain their original-weight provenance; historical speed measurements do not establish this replacement's performance. |
| **k2_horizon_7b** (7B dense) | Q6_K | `temp 1.0, top_p 0.95` (reasoning_effort high = template default) | [IFM/K2-Horizon-7B card](https://huggingface.co/IFM/K2-Horizon-7B) | **added 2026-09-27.** Arch `k2-horizon` is NOT upstream: **MBZUAI-IFM fork `model/K2Horizon` (42adf01)**, built with FA_ALL_QUANTS. 36 layers × 8 KV heads, 250K vocab. **40K ctx at K q8_0 / V q4_0 = 9.08 GB** (48K = 9.58 GB, <300 MB free — rejected; q8_0/q8_0 caps near 32K). Decode decays with depth (84 → 57 @16K → 46 @28K) identically across KV pairs. `ngram-mod` n-min 16: 81 code / **1044 edit**. Template accepts both `enable_thinking` and `reasoning_effort`; XML tool calls parsed by the fork; live cria/Codex run passed |


> **Dense vs MoE, read from GGUF headers** — `general.architecture` plus
> `<arch>.expert_count` / `expert_used_count`, never a card or a name. The current run matrix is:
>
> | dense | architecture | MoE | experts (active) |
> |---|---|---|---|
> | bonsai2 27B | `qwen35` | | |
> | gemma4-qat 12B | `gemma4` | | |
> | ornith1.5 9B | `qwen35` | | |
> | qwen3.8_9b_distill 9B | `qwen35` (33 blocks = 32 + 1 MTP) | | |
> | dory1.0_4b 4B (three recurrent loops) | `dory` | | |
> | phi4 14.7B | `phi3` | | |
> | k2_horizon_7b 7B | `k2-horizon` | | |
> | | | ling3-tiny 7.9B | `bailingmoe3` 128 (8) + 1 shared |
>
> **Bonsai 2 27B replaces Bonsai 1 — and needs NO TurboQuant (measured 2026-09-18).** `prism-ml/Ternary-Bonsai-2-27B-gguf`, same `qwen35` hybrid arch, two new packings (`PTQ1_0` 5.95 GB dense trits, `PQ2_0` 7.21 GB 2-bit slots) that **only the official PrismML fork can load** — the live TurboQuant build has no `ptq1_0`/`pq2_0` symbols and no Hadamard activation runtime, and TurboQuant is now **discontinued** (archive notice, `amesianx/turboquant`), so tbq3 is a dead end for Bonsai 2 forever. Binary = `prism-b10685-7dffb15` at `~/src/llama.cpp-prism2/` (what `PrismML-Eng/Bonsai-demo` pins; the newer `b10687` tag ships Windows assets only). **The KV trap bit again:** carrying Bonsai 1's rollback-recipe `-ctv q4_0` over to Bonsai 2 reproduced the pathological quantized-KV path documented in [model-history](model-history.md) — pp2048@d8192 **17.5 t/s with q8_0/q4_0 vs 1090 t/s with q8_0/q8_0** (tg128@d8192 8.0 → 58.8). A Bonsai 1 control on its own TurboQuant build at q8_0/q4_0 measured 17.5/8.8 — i.e. **the collapse was 100% the V-cache type, not the new model or the new binary.** Final A/B at q8_0/q8_0, same box, same bench: PQ2_0 **pp@8K 1090 / tg@8K 58.8** vs PTQ1_0 602 / 49.1 — PQ2_0 wins both phases for 1.26 GB more, and beats the LIVE Bonsai 1 + tbq3 baseline (188 / 43.3) by **5.8× prefill and 1.36× decode**. Live at `-c 49152`, 8728/10240 MiB VRAM. **So the fleet-wide `-ctk q8_0 -ctv q8_0` default is now truly fleet-wide — ternary-bonsai's override is gone with Bonsai 1.** Behavioral note: the card's default `xhigh` reasoning effort is real — cria's `reasoning = "on"` already maps to `medium` (auto-detected `openai` style), yet coder steps still ruminated 3.8–4.1K reasoning tokens and `rumination.abort` fired twice in a 3-turn live run (~200s each). Plan→coder→tool pipeline otherwise ran clean end-to-end. **No rollback as of 2026-09-18** — operator call to treat new models as replacements: `[models.ternary-bonsai]`, its unit, its GGUFs (8.5 GB) and both Bonsai-1-only binaries (`llama.cpp-tq-prism` TurboQuant, `llama.cpp-prism` b9596) are deleted. Reverting means re-downloading `prism-ml/Ternary-Bonsai-27B-gguf` — and the tbq3 config is **not** reconstructible as-is, since that build is gone from the box and TurboQuant upstream is discontinued. The Bonsai 1 TurboQuant and drafter measurements are in [model-history](model-history.md#retired-model-settings-and-lab-notes-moved-from-model-settingsmd), not a live option.

> **The KV rule is MATCH K TO V, not "avoid q4_0" (measured 2026-09-18, Bonsai 2 PQ2_0, 3080).** The
> morning's note here blamed a `q4_0` V cache specifically. That was wrong, and the corrected sweep is
> why the wording matters: ANY mismatched pair falls off the fast attention kernel, including two
> types that are individually fine. `llama-bench`, pp2048 / tg64 @ d8192:
>
> | K | V | pp | tg | |
> |---|---|---|---|---|
> | f16 | f16 | **1111** | **62.3** | fastest, OOMs at 48K ctx (fits 32K, 9.2 GB) |
> | q8_0 | q8_0 | 1077 | 58.2 | **LIVE** — 7% slower, fits 48K in 6.8 GB |
> | q8_0 | f16 | 22.9 | 7.6 | |
> | f16 | q8_0 | 16.8 | 6.1 | two good types, the worst result of all |
> | q4_0 | q8_0 | 39.3 | 11.4 | |
> | q4_0 | f16 | 33.1 | 8.9 | |
>
> f16/f16 buys 7% for a third of the context window; agentic runs reach 33K tokens, so q8_0/q8_0 stays.

> **MTP GRAFT: the only spec-decode arm that beats baseline on Bonsai 2 — +11.5%, NOT the claimed
> +44% (measured 2026-09-19, 3080/sm_86).** `decent-jawfish/bonsai-2-27b-mtp` is not a drafter: it is
> the Qwen3.8-27B multi-token-prediction head (15 `blk.64.*` tensors) grafted verbatim into the PQ2_0
> GGUF, `block_count=65`, `nextn_predict_layers=1`, driving `--spec-type draft-mtp`. Nothing trained.
> Because the head is the target's OWN next-token predictor rather than an external model guessing at
> a foreign distribution, the "acceptance halved" finding below does not apply to it — which is why it
> was worth testing against that prior.
>
> | arm | tok/s | acceptance | vram |
> |---|---|---|---|
> | vanilla, base model | 63.0 | — | 8328 MiB |
> | vanilla, grafted model | 62.8 | — | 8328 MiB |
> | MTP `n-max 1` | 69.0 | **0.543** | 9086 MiB |
> | **MTP `n-max 2`** | **70.2** | 0.391 | 9236 MiB |
> | MTP `n-max 3` | 61.4 | 0.306 | 9388 MiB |
> | MTP `n-max 4` | 60.0 | 0.253 | 9538 MiB |
>
> The graft is INERT without spec decode (62.8 vs 63.0) — the appended tensors cost nothing unused,
> which is the control that says the win comes from drafting and not from the file.
>
> **CORRECTION — the acceptance column above is wrong and the gain is bigger than first reported.**
> Those acceptance figures came from `grep 'draft acceptance' | tail -1`, i.e. ONE prompt's counter
> presented as the arm's mean. Re-measured per prompt across eight workloads at the live setting
> (n-max 2): **mean 76.3 tok/s, mean acceptance 0.601** — which matches the publisher's 0.60 exactly.
> The real gain over the 62.8 baseline is **+21%**, not +11.5%.
>
> **It is strongly workload-dependent, and the first prompt set was favourable** (5 of 5 code/math,
> the best-drafting categories):
>
> | workload | tok/s | acceptance |
> |---|---|---|
> | python + tests | 88.9 | 0.781 |
> | reasoning (word problem) | 81.3 | 0.681 |
> | math steps | 81.2 | 0.671 |
> | structured list | 80.1 | 0.657 |
> | code fix | 75.4 | 0.589 |
> | prose chat | 68.6 | 0.488 |
> | ruby method | 68.6 | 0.481 |
> | open prose | 66.5 | 0.463 |
>
> 1.34x spread between best and worst prompt. Predictable text drafts well; open prose does not.
> Agentic work is mostly code and tool output so the mix leans favourable, but a prose-heavy run
> lands nearer 67 than 89. Caveat: each workload was not re-baselined with MTP off, so the per-row
> RATIO is inferred from the single 62.8 baseline; the acceptance column is directly measured.
>
> **LOSSLESSNESS VERIFIED, not assumed.** The author did not re-benchmark quality; the claim rested
> on an argument. Greedy (temp 0, top_k 1, fixed seed), same prompt, all three arms produced the
> byte-identical hash `57ce584e386702c034fe781412b44d95`:
>   * base model, MTP off
>   * grafted model, MTP off   -> the graft does not perturb the main path despite block_count 64->65
>   * grafted model, MTP ON    -> verified drafts reproduce the target exactly
> The middle arm is the one that mattered: if block 64 were being executed as a normal layer rather
> than skipped, that hash would differ. It does not.
>
> **Why block_count changes.** Stock Qwen3.8 ships the MTP head INSIDE the GGUF; PrismML drops it
> when producing Bonsai 2 (an FP16-trained head is not something you ternary-quantize, and without
> runtime support it is dead weight). Parameter totals confirm it: unsloth Qwen3.8 27,320,697,856 vs
> prism Bonsai 2 26,895,998,464, a delta of 424,699,392 against ~380M per block for a 24.35B/64-block
> backbone. The graft copies those 15 `blk.64.*` tensors back and sets `nextn_predict_layers=1`,
> llama.cpp's marker for "the last N blocks are MTP, not main-path". Not an anomaly and not novel —
> the recipe is credited to `sudoingX/qwen38-mtp`, found on stock Qwen3.8 first.
>
> **LIVE as of 2026-09-19** at ctx 40960 (48K OOMs; the draft context costs ~900 MiB), patched sm_86
> binary, `--spec-draft-n-max 2`. 9572 MiB of 10240 — headroom is thin, watch for OOM on restart.
>
> **Why our ratio is a third of theirs.** Their baseline was 41.9 tok/s on a quarter-GPU MIG slice;
> ours is 62.8 on a full 3080. Speculation trades spare compute for skipped memory round-trips, so a
> bandwidth-starved baseline has more to win. Their +44% and our +11.5% are not in conflict — but the
> ratio is the part they called durable, and it did not transfer. Acceptance is the other half:
> **0.391 at n-max 2 against their 0.60**, same graft, same mechanism.
>
> Acceptance FALLS with draft depth (0.54 -> 0.39 -> 0.31 -> 0.25) since each extra token compounds
> divergence, while throughput peaks at n-max 2: n-max 1 accepts more often but saves less per
> acceptance. Still far above every external drafter (0.21-0.28 for Qwen3.5-0.8B).
>
> **NOT ADOPTED.** The author states quality was never re-benchmarked — the lossless claim rests on
> spec decode being verified-lossless and the base tensors being bit-identical, not on a measurement.
> +11.5% is a much weaker case for an unverified graft than +44% would have been. A usefulness-scored
> cell must run before this replaces anything live.
>
> Reproduction: the published `0001-qwen35-mtp-hadamard-inverse.patch` has MALFORMED HUNK HEADERS
> (`@@ -1,5 +1,6 @@` describing 5 lines while supplying 3) and `patch` rejects it; the two changes
> were applied by hand and are correct as described. Patched build at
> `~/src/llama.cpp-prism2-mtp/src/build/bin` (sm_86, `-DCMAKE_CUDA_ARCHITECTURES=86`), kept SEPARATE
> from the live unpatched binary. The documented failure was confirmed on the unpatched binary FIRST
> (`latent lookup 'mtp_tok_embd-64' consumed by op=RMS_NORM`) rather than patching toward an expected
> error. Needs matched `-ctk q8_0 -ctv q8_0`: at default f16 KV the MTP draft context OOMs on 10 GB.

> **`n_gpu_layers` is 99 fleet-wide and must NEVER be `auto` (measured 2026-09-18).** The fleet is
> pinned to the 3080 100% of the time, so there is no device-fitting decision to make — and `auto`
> gets it wrong on a hybrid. On Bonsai 2 it left layer 0 on the CPU while the fused Gated Delta Net
> op stayed on CUDA0, splitting the graph every token. Same server, same KV, same card, trivial
> prompt (so not context depth): **`auto` 20.5 tok/s in 8858 MiB; `99` 60.8 tok/s in 6766 MiB** — it
> used MORE vram to run 3x slower. Every Bonsai 2 cell run before this fix, including the L5 12% and
> the L0 5% baseline, was measured on a server running at a third speed. A model too big to fit is
> better off failing to load than silently running a third as fast. `gemma4-qat` was checked and
> offloads 49/49 correctly under `auto`, so this is a hybrid-architecture failure, not a universal one.

> **Speculative decoding on Bonsai 2: acceptance HALVED versus Bonsai 1, and no paired drafter exists
> (measured 2026-09-18).** Bonsai 1's numbers (in [model-history](model-history.md#retired-model-settings-and-lab-notes-moved-from-model-settingsmd)): dspark **62%**, generic Qwen3.5-0.8B
> **51%**, ngram-cache **48%** on code. Bonsai 2, same box, same generic drafter: **21-28%**. The
> third-party `ProCreations/…-DFlash2` head reports **35%** and a +0.54% throughput gain over its own
> predecessor. Acceptance roughly halved across BOTH drafter kinds with the drafter held constant,
> which makes it a property of the target rather than of the drafters.
>
> Measured arms on the 3080, all at `-ngl 99`: baseline (no spec) **60.4 tok/s**; `ngram-cache`
> **49.8** (−18%, the inverse of Bonsai 1 where ngram nearly doubled decode — at 60 tok/s the
> verification overhead costs more than the guess saves); `draft-simple` + Qwen3.5-0.8B **OOM at 48K**,
> and **22.2 tok/s (−63%) at 24K** where it fits.
>
> `prism-ml` ships **no dspark drafter for Bonsai 2** — the demo's own downloader says so in a comment
> (`the projector ships in the same repo; Bonsai 2 has no dspark drafter`). Every `dspark-*` file on
> the hub is paired to Bonsai 1 or the 1-bit Bonsai, and drafters are target-specific. Bonsai 2 was
> two days old at the time of measuring, so this is likely "not yet" rather than "not coming".

> **gemma4 (measured 2026-07-28; tg64, tok/s):** q8_0 = 62 / 57 / 49 / 40 at 8K / 32K / 65K / 131K; turbo3 = 58 / 52 / 46 / 36 — **q8_0 wins every depth (~7–9%), and gemma4's SWA (1024-token window on most of its 48 layers) keeps KV small at any context, so turbo has no reach advantage either. TurboQuant: nothing to offer gemma4.** 131K verified on q8_0; the 262K training cap likely fits too.

> **KV and speculation across the fleet.** `q8_0`/`q8_0` is the fleet default and every model measured keeps it: the 2026-07-28 sweep found TurboQuant (turbo3) a win only for the retired Bonsai 1 (2-bit weights made KV reads the dominant decode term) and a loss for every other model, growing with depth. Bonsai 1's TurboQuant/drafter notes, the retired models' per-model rows and the fleet-wide sweep are in [model-history](model-history.md#retired-model-settings-and-lab-notes-moved-from-model-settingsmd).

> **ternary-bonsai canonical cria.toml roles (operator-saved 2026-07-28, the exact settings that produced run m15 — the first fully unaided goal success):**
>
> ```toml [roles.classifier] backend = "local" reasoning = "on" temperature = 0.0 repeat_penalty = 1.1
>
> [roles.reasoner]                      # the planner + the step/task critic backend = "local" reasoning = "on" temperature = 0.6 top_p = 0.90 top_k = 40 repeat_penalty = 1.1
>
> [roles.coder] backend = "local" reasoning = "on" temperature = 0.2 top_p = 0.95 top_k = 20 repeat_penalty = 1.1 output_reserve = 16384                # input-side reserve; keeps a big write_file uncut
>
> [roles.compactor] backend = "local" reasoning = "off" temperature = 0.0 repeat_penalty = 1.1 ```

---

## phi4 function-call replacement

The operator selected `LocalAI-functioncall-phi-4-v0.3` as the replacement for **phi4**, not a new model identity or battery row. The prior Microsoft Phi-4 artifact and reconstructed Hermes template remain available for historical provenance. Existing judgments are not reattributed to the new weights, and completed campaigns are not restarted.

- Artifact: `LocalAI-functioncall-phi-4-v0.3.i1-Q4_K_S.gguf`, publisher revision `9e5c376d93218426530a14a141b9f7824dd3f4b0`, SHA-256 `4736e0b0d37167a38e42c9526f0543622c4b3b205ec50c3603b3c62abb4b4693`.
- Source template: [`cria/prompts/localai_functioncall_chat.jinja.txt`](../cria/prompts/localai_functioncall_chat.jinja.txt). Install its exact bytes as `~/.local/share/cria/fleet/templates/phi4-localai-functioncall.jinja`; the existing `llama-phi4.service` keeps alias `phi4`.
- LocalAI's [published integration](https://github.com/mudler/LocalAI/blob/master/gallery/phi-4-chat-fcall.yaml) supplies the system tool introduction, extracts `<Thought>…</Thought>`, and parses JSON within `<Output>…</Output>`. Its published tokenizer template alone handles only ordinary chat messages. The adapter retains Phi's turn tokens, all caller instructions, and the tool menu; renders historical calls in the Output envelope and tool results as user turns, as in the listed Glaive training dataset. It retains explicit envelope guidance and has no fabricated examples or results. The private native option below supplies LocalAI's backend-owned no-action protocol; it never becomes an executable harness tool.
- Native llama.cpp automatically derives the tool and reasoning parser from the adapted template. Set `--reasoning-format deepseek` to return emitted Thought text in `reasoning_content`; this is extraction, not proof of a trained reasoning on/off switch. The measured adapter bytes and ordinary-text guidance remain unchanged; no second template variable is introduced. No extra LocalAI server or cria response-repair implementation is needed.
- Private native patches: [`8345-serial-tool-call.patch`](../scripts/backend-patches/8345-serial-tool-call.patch) then the independent [`8345-named-tool-choice.patch`](../scripts/backend-patches/8345-named-tool-choice.patch), followed by [`8345-no-action-tool.patch`](../scripts/backend-patches/8345-no-action-tool.patch), against llama.cpp `8345f333951c661d166b00e6f9362e553768f292`. The serial patch restores one real call when parallel calls are disabled. The named contract normalizes actual Chat/Responses/Anthropic inputs and enforces the selected caller function; the no-action patch adds generic `--no-action-tool FILE`, disabled by default. Only phi4 is intended to opt in, using [`localai_functioncall_answer_tool.txt`](../cria/prompts/localai_functioncall_answer_tool.txt), with LocalAI's exact source descriptions and required string message. One native owner appends the definition for automatic choice with real tools and no response schema, uses that effective menu for rendering/grammar/parsing, and converts a complete canonical answer to exact assistant content before any stream diff. It creates no tool event, ID, execution or fabricated result. Active caller-name collisions, reserved tools-template overrides and mixed answer/action batches are errors. Null is automatic. Trusted activation and its generated parser travel together in a typed native result into all chat inference tasks; public JSON controls and custom untrusted tags cannot enable the channel. Required/none/no-tools/schema paths preserve caller ownership, while named choice intentionally gains independent native enforcement. Named selection plus a standalone response schema is unsupported by this serving path and gives 400 before generation.
- CPU validation uses the matching V3 private server/common/server implementation, including every byte prefix through native diffs and actual partial/final response formatting. Incomplete analyzed reasoning blocks cannot fall through to final content, including length termination, whitespace/preamble and partial closing markers. Framing whitespace before reasoning is consumed as upstream framing, while literal preambles and exact decoded message whitespace remain content. Both generation-prefill variants are covered; disabled mapper exception classes/messages remain unchanged, while active protocol and untrusted private-tag errors retain full raw bytes. Definitions and payloads admit exactly one required plain string message; unsupported schema facets are rejected. The opt-in supports only the tested flat name/arguments per-call analyzer shape with complete markers, and fails closed for markerless/array/nested/name-key/ID forms. Tests cover exact Unicode, JSON text, newlines, quotes, backslashes and literal closing-marker bytes; incomplete answers cannot succeed through brace completion. Golden fixtures compare disabled rendering/grammar/parser bytes and the captured manual answer-menu prompt. Ordinary bare text remains content. Raw wrapped prose/result JSON is preserved as a characterization; the accepted wrapped final protocol promises canonical `answer.message`, not generic spontaneous wrapped content. Reproduction, test commands and limitations: [`backend-patches/README.md`](../scripts/backend-patches/README.md).
- **ABI/build boundary:** deploy a newly built matching `llama-server`, `libllama-server-impl.so` and common library together. Added C++ fields make the old server incompatible with the new common library. Parent deployment must preserve the original same-revision CUDA core libraries/backends/kernels in a separate phi4 runtime and validate the assembled dependencies. The CPU build is not a substitute for that validation; never replace libraries underneath a running process. The earlier serial-only and V1 runtime/source/build are frozen historical evidence. Parent's final assembly must exclude old ABI helper executables and implementations; V1/V2 builds and parent runtime candidates remain frozen; the V3 server-only assembly is parent-owned.
- **Error boundary:** native clipped protocol output is a 500/error event, never partial completion. Existing watched streaming discards partial calls and re-asks once buffered; a buffered 500 exhausts the one-endpoint policy and propagates. Protocol-specific fake-upstream tests document this without new retry logic or a claim of automatic continued work. Parent is separately reviewing authoritative native length-stop events versus malformed completed replies before any recovery decision; V3 changes neither stop handling nor retries.
- **Separate V4 stop/error boundary:** [`8345-generation-stop.patch`](../scripts/backend-patches/8345-generation-stop.patch) applies after the unchanged V3 artifacts. Its native final owner preserves actual stop causes, returns incomplete length for valid LIMIT prefixes, withholds all buffered calls, freezes published streaming state, and reports malformed output as a typed error with complete raw evidence. The matching server/common/server implementation must be rebuilt together. Cria quarantines action deltas until terminal status at all harness boundaries; incomplete turns cannot become completed Chat/Responses calls. Typed driver faults use the existing bounded refusal/renudge path with factual prompt-file notices, while proxies propagate them. After existing guards, incomplete driver results bypass every completion judge/probe and return with full evidence and task pending. Unrecorded stream EOF is an ordinary structured transport error, distinct from an actual local abort and a native protocol error. No reserve/refit, retry-loop, output cap, semantic exact-content assist or live/config change is included. V1–V3 sources/builds/candidates and live V3 remain frozen; the false equality/newline incident and Java campaign remain outside this unit. [Boundary and reproduction](../scripts/backend-patches/generation-stop.md).
- **Replacement status: NOT_READY pending parent live verification.** No live paths, configuration, service, weights or campaign were changed in this implementation. The constrained turn-3 grammar previously offered only real actions, while the preserved raw control completed inside Output. A single manually supplied, source-grounded answer definition selected `answer` but leaked it as a tool call and incorrectly claimed a terminal newline. The new native protocol resolves that transport contract in CPU tests; it establishes no generation efficacy, exact-file success or truthful completion. Parent still must verify real calls/results, complete final delivery, exact file bytes and truthful checks. No coding attempt or campaign resume is implied.
- Full source, matching build, reproducible patch checks, before/after regression, native auto-parser/template/PEG results and Python-suite comparison receipts are in `~/.cria/validation/localai-phi4-install/no-action-native-v3/`. V1/V2 receipts, private sources/builds and parent candidates remain untouched. The existing installation state, captures, raw-form controls and rejected prototype remain preserved in the parent directory. Historical judgments retain original-weight provenance; official identity, sampling, planner OFF, context and GPU restriction remain unchanged.

## `merge_consecutive_turns` — strict role alternation

Meta's Llama chat-template lineage enforces alternation literally:

```jinja
{%- if (message['role'] in ['user','tool']) != (loop.index0 % 2 == 0) -%}
  {{- raise_exception('Conversation roles must alternate between user/tool and assistant') -}}
```

Every even position must be user-or-tool, every odd one assistant. **cria's whole anchor mechanism is consecutive user turns** — ⟦ctx:checks⟧, ⟦ctx:steer⟧, ⟦ctx:facts⟧ each arrive as their own message — so a Llama-lineage model rejects cria outright. Measured on a Llama-3.1 derivative (a failed trial): the FIRST coder call, system plus three user turns, returned 400 twice and the run died in 24 seconds having made two calls.

`[roles.<name>] merge_consecutive_turns = true` collapses each run of consecutive same-SIDE messages into one. Side, not role: the template renders a `tool` result as a user turn, so `{user, tool}` is one side and `{assistant}` the other — merging by role alone would miss the common tool-result-then- anchor pair. Nothing is dropped or reordered; cria's anchors are self-delimiting blocks so concatenation reads exactly as separate turns did. A merged run keeps its first message's role, so a leading tool result keeps its `<TOOL_RESPONSE>` framing, and an assistant turn carrying `tool_calls` is never folded into or out of.

**Who needs it.** Only Llama-lineage templates. Checked in the GGUFs: Qwen3.5 and Qwythos carry zero alternation guards.

Every shape was verified against the live server, 400 before and 200 after: three stacked anchors, a tool result followed by an anchor, and two consecutive assistant turns.

---

## `collapse_system_prompt` — where the instruction goes

cria writes every instruction it gives into a **system** message: the coder frame, every judge, the steer author, the compactor, the classifier. Right for most chat templates, wrong for some, and until 2026-08-08 nothing in cria knew the difference — 12 construction sites, no owner.

`[roles.<name>] collapse_system_prompt = true` folds every leading system message into the front of the first user turn. One place (`Role.apply`, the same hook that translates sampling and reasoning), so it covers every request that role makes. Off by default; `suite/sampling.py` writes it per model on each swap, exactly like sampling, so a stale value cannot survive a model change.

**When to set it.** Read the model's chat template, not its card alone. The question is whether the template has somewhere to PUT a system message:

- **r1-llama** — the case that prompted the knob (a rejected Llama-family candidate, currently **OFF**); its template analysis and the evidence for leaving it off are in [model-history](model-history.md#retired-model-settings-and-lab-notes-moved-from-model-settingsmd).
- **Everything else on the ladder** — does not. Qwen-, Gemma- and ternary-derived templates all have a real system slot.

The fold preserves order, never drops text, and creates a user turn when a body has none (a judge asked system-only would otherwise lose its whole question).

---

## Reasoning ON / OFF — the mechanism and per-model reality (verified 2026-07-08)

**How it works.** Reasoning is toggled entirely by the **server-side chat template**, driven by one per-request boolean. cria (like codex-local's `ollama.rs`) sends **only** `chat_template_kwargs.enable_thinking = <bool>` on the wire — nothing else. The magic is in each model's `*-toggle.jinja`: when `enable_thinking=false` it **prefills an empty, closed think block** into the generation prompt — `<think>\n\n</think>\n\n` (Qwen family) or an empty `<|channel>thought` (Gemma). It is a **prefill, not a directive** (grepping all six templates for "do not think / answer directly" returns zero hits). The empty block is a *trained control signal*: "reasoning already done, answer now."

**So OFF works only on models trained to honor that signal.** The toggle files prefill **byte-identical bytes** for the models that work and the ones that don't — the divergence is the model, not the template.

| Model | ON | OFF (`enable_thinking=false`) | Why |
|-------|----|--------------------------------|-----|
| **ornith15** (the retired qwopus and qwythos behaved identically) | ✅ | ✅ clean direct answer | **Qwen3-derived** — honor the empty `<think></think>` control block |
| **ternary-bonsai** | ✅ | ✅ clean direct answer | **Qwen3.6-derived** — embedded ChatML honors `enable_thinking` (verified on/off at load) |
| *system-line convention* | ✅ `detailed thinking on` | ✅ `detailed thinking off` | **cria's THIRD reasoning convention** (Llama-3.1 derivatives) — the switch is a sentence in the system prompt, not a body parameter. `reasoning.system_directive()` renders it; `config._set_reasoning_directive` prepends it to the leading system message (the mutation lives with the messages, same as the chat_template OFF prefill). Reasoning-unset leaves the model's own default alone |

**Known native-OFF models** include ornith15 (and the retired qwopus and qwythos; verified on the retired gemma4-finetune — re-verify gemma4 before relying on OFF). The retired qwen3.5 and defiant-fable rows of this table are in [model-history](model-history.md#retired-model-settings-and-lab-notes-moved-from-model-settingsmd). Some template families empty `reasoning_content` under `enable_thinking=false` yet still deliberate in prose in `content`, which cria's parsers can't strip (no `<think>` tags) — a model limitation to check when adding a model, not a missing manipulation.

**The per-model "manipulation" you built** was exactly these `*-toggle.jinja` files (and, for a whole-instance off, `.reason-off` launch scripts that bake the `-nothink` template via `--chat-template-file`, plus `--reasoning-format deepseek` for ornith). qwopus's *stock* template hardcoded `<think>` with no gate — which is precisely why the toggle had to be hand-built.

**What cria does on `reasoning = "off"` (SHIPPED — `LocalRole.apply` / `clean_content` in `config.py`).** Per request cria applies THREE things so OFF works on any loaded model without per-model config:
1. `chat_template_kwargs.enable_thinking = false` — suppresses thinking on the native-off models.
2. appends a **mild no-think directive** to the system message ("Do not think out loud or narrate your reasoning. Respond directly.") — makes prose-deliberating template families answer directly.
3. **strips any leaked reasoning** ahead of a `</think>` marker from the model's `content`.

**Honest result (verified end-to-end 2026-07-08):**
- **Native-off models** (ornith15; qwopus and qwythos when they ran; verified on the retired gemma4-finetune — re-verify gemma4 before relying on OFF) → OFF is **clean**.
- On a prose-deliberating template family, OFF engages and is clean on direct tasks, but reasoning-heavy prompts stay verbose (no `</think>` marker for the strip to catch). It never breaks cria — just chatty. A *harder* directive makes such models terser but **wrong** (a reasoning-trained model loses accuracy when starved of reasoning), so the directive is deliberately mild.

**Guidance:**
- Flip any role `reasoning = "on"` / `"off"` in `~/.cria/cria.toml` and restart cria — it takes effect per request, no model reload, no per-model wiring needed.
- `cria.toml` ships every role `reasoning = "on"` (clean fleet-wide; also what coding wants).
- If a role needs **terse** OFF output, point it at a **native-off model** (a Qwen-derived one).

---

## Server launch (`models.toml`)

**Current Dory exception:** `dory1.0_4b` uses its dedicated installed runtime and libraries, `-c 49152 -b 2048 -ub 1024 -np 1`, Q8/Q8 KV, Flash Attention, `--gpu-layers 999 --fit off --split-mode none --device CUDA0`, `--no-context-shift --cache-ram 0 --jinja`, and `--override-kv dory.num_loops=int:3,dory.recurrent_kv_cache_mode=str:per_loop`. The GGUF defaults to four loops, so do not omit the override. Its normal service selects no speculation; optional optimized mode adds ngram-simple lookup/draft lengths 12/32. `llama-fleet plan dory1.0_4b` and `llama-fleet plan dory1.0_4b --mode optimized` show both exact profiles. The service is installed but disabled; switch only in an authorized free RTX3080 window. RTX3090 tuning was an explicitly authorized temporary exception to the usual device restriction, not a permanent fleet reassignment. Dory is not automatically added to the frozen eight-model campaign roster or given battery scores.

The older shared-launch description below is historical guidance, not a substitute for the current per-model fleet plan. In particular, its universal microbatch and GPU-fit claims do not qualify Dory on the RTX3080.

Historical common settings: `-c 49152` (48K) · `-b 2048 -ub 512` · `-np 1` · `--device CUDA0 -ngl auto -sm none -mg 0` · `-ctk q8_0 -ctv q8_0` **(now every model, incl. ternary-bonsai-2; only the retired Bonsai 1 entry overrode it with `tbq3`)** · `-fa on --no-host --no-mmproj --no-warmup --jinja` · `--reasoning auto` (the *parsing* mode — distinct from per-request `enable_thinking`) · `--host 127.0.0.1 --port 18084`. **Sampling is NOT set here** (cria sends it per request).

The historical entries below used source/template overrides (including templates in `~/shepherd-eval/templates/`) and dedicated binaries for unsupported weight formats or layouts. Their CUDA-12.8/WSL library paths are provenance, not Dory instructions: Dory uses its own installed runtime directory followed by fleet `libs/cuda13`, as shown in its current plan.

| Model | Fork | Why |
|-------|------|-----|
| dory1.0_4b | `~/.local/share/cria/fleet/runtimes/dory-9e2f3be/bin/` (libraries there plus fleet `libs/cuda13`) | Dory architecture support and GPU scale/normalization placement fix, pinned `9e2f3be3947a7339ac8b93f9b9a8dabb8eeaf144`; source `~/src/llama.cpp-dory`. Do not substitute a stock binary without qualifying its Dory support. |
| ternary-bonsai-2 **(live)** | `~/src/llama.cpp-prism2/b10685/llama-prism-b10685-7dffb15/` | `PQ2_0`/`PTQ1_0` ternary kernels + Hadamard activation runtime. Stock KV (`q8_0` both) — **never `-ctv q4_0`, it costs ~60× prefill at depth** |
| ornith15 | `~/src/llama.cpp-ornith15/build-cuda/bin/` | upstream 74a7c897. Stock b9893 rejects Ornith 1.5's final MTP block with missing `blk.32.ssm_conv1d.weight`; the dedicated current build loads it. |

| Model | Source | Template |
|-------|--------|----------|
| dory1.0_4b | `-m ~/models/cria/dory1.0_4b/NVIDIA-Nemotron-Labs-Dory1.0-4B-Q5_K_M.gguf` (dedicated Dory runtime; explicit three-loop override above) | Embedded template; `enable_thinking`, native tool calls, Jinja. `force_nonempty_content` is not implemented by this template. |
| ornith15 | `-hf ornith-ai/Ornith-1.5-9B-GGUF --hf-file Ornith-1.5-9B-Q6_K.gguf` **(dedicated upstream 74a7c897 binary + lib_dir)** | *(embedded Qwen3 XML tools + `enable_thinking`)* |

- **`-ub 512` is required** — a larger prefill micro-batch overflows the 10 GB 3080.
- **All fit the single 3080** (9Bs ~7.3 GB Q6_K; gemma4-qat 12B ~7 GB).
- **Filename trap when pulling a quant:** unsloth model cards list K-quants WITHOUT the `UD-` prefix that the repo files actually carry. `Qwen3.8-27B-Q4_K_S.gguf` 404s to a 15-byte *Entry not found*. Always enumerate with `curl -s https://huggingface.co/api/models/<repo>?blobs=true` instead of trusting the card.
- The `*-toggle.jinja` templates gate on `enable_thinking` so the per-request flag works. Keep `--reasoning-budget` at default — launching with `--reasoning-budget 0` pins the whole instance no-think and defeats per-request control.

---

### The field regression: 4-bit KV cost 2.3× decode and 11× prefill (2026-08-20)

The `-fitt` offload fix (the retired `qwen38` run, in [model-history](model-history.md#retired-model-settings-and-lab-notes-moved-from-model-settingsmd)) was measured with **40-token prompts, greedy sampling, thinking OFF, code output** — the single most favourable configuration. In real cria traffic the same server delivered **4.9 t/s weighted**. The synthetic 28.4 was not a lie, it was unrepresentative in four ways at once, and the gap is a lesson about benchmark design as much as about settings.

**Replay from captures, not synthetic probes.** `~/.cria/calls/<session>/NNNN-<phase>.json` stores the exact request body. Replay it verbatim — real tools, real message history, real sampling, `enable_thinking: true` — with only `stream:false` and a `max_tokens` cap added, so the *rate* is measured at real depth without waiting out an 8000-token generation. This reproduced the field number on the first try; no synthetic prompt did.

**Config matrix, real captured bodies** (`temp 0.2 / top_p 0.95 / top_k 20 / repeat_penalty 1.1`, thinking ON; shallow = 3.7K prompt, deep = 7.5K):

| KV | spec | `-fitt` | shallow tg | **deep tg** | pp |
|---|---|---|---|---|---|
| **`iq4_nl`** | on | `-600,-550` | 14.3 | **5.6** | **22–39** |
| **`q8_0`** | on | `-600,-550` | 15.0–20.2 | **11.9–13.9** | **249–275** |
| `q8_0` | on | `-350,-300` | 12.5 | 10.4 | 208 |
| `q8_0` | **off** | `-350,-300` | 12.2 | 11.9 | 367–390 |
| `q8_0` | **off** | `-500`/`-560` | 12.1 | 11.6 | 348–378 |

**`iq4_nl` KV was the whole regression.** 4-bit KV has no fast attention kernel for this model's `head_dim 256` on this hardware and falls back to something pathological — it does not merely cost bandwidth, it costs **11× the prefill**. Switching to `q8_0` costs ~750 MiB and buys 2.3× decode at depth. **This was already a documented fleet finding** (see the TurboQuant sweep in [model-history](model-history.md#retired-model-settings-and-lab-notes-moved-from-model-settingsmd): *"the wall was the QUANTIZED-KV CODE PATH, not KV bandwidth"*, f16 beating turbo3 on the same build, and *"q8_0 stays the fleet default"*). It was set anyway, for headroom, and not re-tested under real load. **`q8_0` is the default for a reason — deviate only with a measurement at real depth.**

**Speculation is near-worthless for reasoning traffic.** Draft acceptance is 93% on clean code but **47–76% on reasoning prose**, and every cria coder call is reasoning-dominated — one captured call emitted 34,047 chars of reasoning for a 232-char answer. With `q8_0` it is roughly a wash on decode and **substantially slows prefill** (250 vs 375 t/s). Kept ON only because it edges ahead on decode, which dominates when a call emits thousands of tokens. Turn it off if prefill ever matters more.

**The negative `--fit-target` is calibrated to one memory profile.** Turning speculation OFF frees the draft context's ~340 MiB, the fitter packs more layers in, and `-600,-550` then overshoots into an OOM **restart loop** (58 restarts before it was caught). Any change touching memory — KV type, ctx, batch, spec — invalidates the margin. Re-probe with `scripts/vram-probes/probe_fit.sh` after changing any of them.

**Aborting a run does not free the GPU.** After a killed session, `/slots` still reported `is_processing: true` six minutes later — llama.cpp kept generating for a client that was gone. Check `curl -s :18084/slots` before trusting any measurement, and restart the unit to clear it.

> **Never benchmark this fleet on synthetic prompts.** Replay a captured body. Greedy short-prompt code generation flatters every setting that real agentic traffic punishes.


---

## Quick reference — verify what's actually live

```bash
# which model + context on 18084
curl -s 127.0.0.1:18084/props | python3 -c 'import sys,json;d=json.load(sys.stdin);g=d.get("default_generation_settings",{});print(d["model_path"].split("/")[-1],"n_ctx=",g.get("n_ctx"),"temp=",g.get("temperature"),"rep=",g.get("repeat_penalty"))'

# reasoning per-request toggle (true → reasoning_content>0; false: 0 = suppressed, but check content isn't a prose leak)
for t in true false; do printf 'enable_thinking=%s -> ' "$t"
  curl -s 127.0.0.1:18084/v1/chat/completions -H 'Content-Type: application/json' \
    -d "{\"messages\":[{\"role\":\"user\",\"content\":\"Is 51 prime? think first\"}],\"stream\":false,\"max_tokens\":220,\"chat_template_kwargs\":{\"enable_thinking\":$t}}" \
    | python3 -c 'import sys,json;m=json.load(sys.stdin)["choices"][0]["message"];print("reasoning_len:",len(m.get("reasoning_content") or ""),"| content:",(m.get("content") or "")[:60].replace(chr(10)," "))'
done

# see the exact launch command a model would run (no side effects)
llama-fleet gemma4 --dry-run

# is the slot actually free? (a killed run leaves llama.cpp generating)
curl -s 127.0.0.1:18084/slots | python3 -c 'import sys,json;print([("BUSY" if s.get("is_processing") else "idle") for s in json.load(sys.stdin)])'

# replay a REAL captured request (real tools/history/sampling) instead of a synthetic prompt
python3 - <<'EOF'
import json,glob,sys
f=sorted(glob.glob('/home/jesse/.cria/calls/*/[0-9]*-coder-s1.json'))[-1]
b=json.load(open(f))['body']; b['stream']=False; b['max_tokens']=400
json.dump(b, open('/var/tmp/replay.json','w')); print('from', f)
EOF
curl -s 127.0.0.1:18084/v1/chat/completions -H 'Content-Type: application/json' -d @/var/tmp/replay.json \
 | python3 -c 'import sys,json;t=json.load(sys.stdin)["timings"];d=t.get("draft_n",0);print(f"pp={t[\"prompt_per_second\"]:.0f} tg={t[\"predicted_per_second\"]:.2f} accept={100*t.get(\"draft_n_accepted\",0)/d if d else 0:.0f}%")'

```
