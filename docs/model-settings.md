# Recommended settings per model

**cria's source of truth** for the CURRENT local model fleet on `127.0.0.1:18084`. (Ported from codex-local and now maintained here.) Keep it updated when settings change or a model is added/verified. Retired, replaced, and rejected models — and why — live in [`model-history.md`](model-history.md), not here.

Settings live in **two files**, split by whether they need a model reload:

| Layer | File | Holds | Changing it needs |
|---|---|---|---|
| **Server launch** | `~/.config/llama-fleet/models.toml` (read by `llama-fleet`) | model source, quant, **ctx**, KV, GPU layers, chat template | a **model-server restart** (`systemctl restart llama-<model>`) — rare |
| **Client / per-role** | `~/.cria/cria.toml` `[roles.<role>]` | **sampling** (temperature/top_p/top_k/repeat_penalty/min_p/max_tokens) + **reasoning** | a **cria restart** (seconds) — no model reload |

cria attaches the **role's** sampling + reasoning to **every request** it makes for that role (`temperature`, `repeat_penalty`, … and reasoning as `chat_template_kwargs.enable_thinking`). The launcher's sampling is only a fallback — so tune in `cria.toml`, not `models.toml`.

> **One model at a time** (`-np 1`). Swap with `systemctl` (the `llama-fleet` launcher reads `models.toml`); see §Server launch.
> Every model but one runs on the 3080 alone. **`qwen38` is the exception** — 14.3 GiB of weights cannot fit in 10 GiB, so it spans the 3080 **and** the GTX 1080. Its unit `Conflicts=` the whole 18084 family, so starting it stops whatever else holds either card.

---

## Per-model recommended settings

Sampling is **client-side** (`cria.toml`); set the role you're driving to these. Server launch (`models.toml`) is uniform except model + template (see §Server launch).

| Model | Quant | Recommended sampling | Source | Notes |
|-------|-------|----------------------|--------|-------|
| **ternary-bonsai-2** (27B) *(was ternary-bonsai; Bonsai 1 retired + deleted 2026-09-18, sampling carried over unchanged)* | PQ2_0 (custom ternary g128) | **per-role, CANONICAL (m15-verified — see block below)**: coder `0.2/0.95/20`, reasoner `0.6/0.90/40`, classifier+compactor `temp 0`; `repeat_penalty 1.1` all | PrismML (Qwen3.6-derived) | needs Q2_0_g128 kernels (§Server launch — TurboQuant merged fork); ~8.0 GB on the 3080; `n_ctx_train` **262144** (comfortable @ 48K) |
| **gemma4** (12B) — **RETIRED + DELETED 2026-09-18**, replaced by `gemma4-qat`; row kept because the ladder scores below were measured on it and nothing on the box now reproduces them | Q4_K_M | `temp 1.0, top_p 0.95, top_k 64, repeat_penalty 1.1` — ALL roles | Gemma 4 defaults (same pair the finetune's card pinned; kept identical so the 2026-08-05 ablation isolated weights) | replaced the yuxinlu1 finetune 2026-08-05 after repeated runs showed stock completing substantially more of the same lane |
| **ornith15** (Ornith 1.5, 9B) | Q6_K | coder `temp 0.6, top_p 0.95, top_k 20, min_p 0, presence_penalty 0, repeat_penalty 1`; reasoner `temp 1.0, top_p 0.95, top_k 20, min_p 0, presence_penalty 1.5, repeat_penalty 1` | [ornith-ai card](https://huggingface.co/ornith-ai/Ornith-1.5-9B-GGUF) | **Current Ornith as of 2026-09-05.** Reasoning + XML tool calls are native in the embedded template; 262144-token training context. Previous testing was Ornith **1.0**, not 1.5. Stock b9893 cannot load the MTP block; dedicated upstream 74a7c897 does. Service and native tool/reasoning-toggle smoke verified at ~82 tok/s. |
| **qwythos** (9B) | Q6_K | `temp 0.6, top_p 0.95, top_k 20` | empero-ai (Qwen3.5 thinking) | **V2 swapped in 2026-07-12** (`/home/jesse/models/Qwythos-9B-v2-Q6_K.gguf`, alias `qwythos_9b_v2_q6`). The UNVERIFIED flag this row carried until 2026-08-08 is retired: V2 has run the ladder repeatedly at these values, and its newest capture (20260804T155422) shows `reasoning_content` on 20/20 sampled coder replies. **Re-confirmed 2026-09-18 from both ends:** file sha256 `dd39e148…` matches the `empero-ai/Qwythos-9B-v2-GGUF` LFS oid (it is the published Q6_K, not a stale/partial copy), and a direct toggle probe on the embedded template gave `enable_thinking` on = 322 chars `reasoning_content` / 137 tok, off = 0 / 4 tok, both answering correctly — so `models.toml`'s lingering "template UNVERIFIED" note was stale and is now removed |
| **qwopus** (9B, Qwen3.5) | Q6_K | `temp 0.6, top_p 0.95, top_k 20` *(inferred — Qwen3.5)* | ⚠ not stated on card | verify before trusting |
| **gemma4-qat** (12B) | UD-Q4_K_XL (QAT) | `temp 1.0, top_p 0.95, top_k 64, repeat_penalty 1.1` — same as gemma4 | Gemma 4 defaults, deliberately identical to the gemma4 row | **added 2026-09-18** (`unsloth/gemma-4-12B-it-qat-GGUF`, 6.72 GB). Google's quantization-AWARE-trained 4-bit release: the low-bit weights are what the model was trained to be, not a post-hoc rounding, so the usual Q4 tax should be largely absent. Loads at 49152 ctx / 7842 MiB; `llama-bench` (prism b10685 build, q8_0 KV) pp2048 2779 · tg128 75.3 · **pp@8K 2399 · tg@8K 70.5** — SWA keeps its KV tiny (408 MiB non-SWA + 255 MiB SWA at 48K), so it barely slows with depth. Added ALONGSIDE `gemma4`, not over it, so no recorded score changes weights underneath it. **Caveat for the ladder: this is UD-Q4_K_XL vs gemma4's Q4_K_M — two variables (training method + quant recipe). The non-QAT repo also ships UD-Q4_K_XL (7.37 GB); run that arm before crediting any delta to QAT itself.** |
| **qwen3.5** (9B) | Q6_K | `temp 0.6, top_p 0.95, top_k 20` | Qwen's own thinking-mode card | the BASE the fleet's two 9B finetunes come from (qwythos = empero-ai's, qwopus = Jackrong's) — same size, quant, build and sampling as both, so a repeated usefulness gap is attributable to the weights. Added 2026-08-08; `unsloth/Qwen3.5-9B-GGUF:Q6_K`, 7.46 GB. Reasoning toggle **verified on load** (0 chars off / 649 on). Stock CUDA build, default q8_0 KV — TurboQuant was considered and dropped so a runtime change would not land in the same step as a model change |
| **defiant-fable** (9B, Qwen3.5 finetune) | Q5_K_S **MTP** | `temp 0.6, top_p 0.95, top_k 20` (identical to qwen35) | [DavidAU card](https://huggingface.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF): thinking/coding `0.6/0.95/20, min_p 0, presence 0, repeat 1.0` | **added 2026-09-25**. DavidAU + Nightmedia multi-stage heretic/abliterated merge of Qwen3.5-9B finetunes. File `Qwen3.5-9B-The-Defiant-Fable-Uncnr-Heretic-NEO-MAX-MTP-Q5_K_S.gguf` (note **`Uncnr`**, not the repo's `Uncensored` — the obvious name 404s), 7.14 GiB, sha256 `bf2e8ade…` = HF LFS oid. Set up like qwen35 (single 3080, `-ngl 99`, q8_0 KV, 48K, embedded template) with two MEASURED differences: **(1) binary** — the stock build rejects the MTP block (`missing tensor 'blk.32.ssm_conv1d.weight'`, the ornith15 failure), so it runs on the ornith15 build (upstream 74a7c897); **(2) `--spec-type draft-mtp --spec-draft-n-max 2`** — A/B on the 3080, same file and prompts: code decode **81.9 → 126.0 t/s (+54%, acceptance 0.95)**, prose **81.9 → 106.1 (+29%, 0.71)**, prefill ~19% slower. Sampling is held equal to qwen35 so a score gap is the weights. The card says to keep `repeat_penalty` at 1, because a higher value hurts MTP acceptance; do not carry over the 1.1 that the Bonsai rows use. The card's `reasoning_effort` / `{REASON:…}` modes belong to the separate Q6/Q8 **plusIQ** files; this file's template has only `enable_thinking` |
| **qwen38-distill** (9B, Qwen3.8 distill) | Q6_K | `temp 0.6, top_p 0.95, top_k 20` | [empero-ai card](https://huggingface.co/empero-ai/Qwen3.8-9B-Distill-GGUF) | **added 2026-09-27.** `qwen35` hybrid with an inline **MTP head** (33 blocks). Upstream `7ac59a6` build. Measured on the 3080, decode on a code prompt / a whole-file-edit prompt: no spec 80/80 → `draft-mtp` n3 139/165 → **`draft-mtp,ngram-mod` n3 143/874 (LIVE)**. ub 2048 (+2% prefill), `-cms 2048` (real-traffic replay: −2% re-prefill; multi-slot and unlimited RAM cache measured no better). q8_0 KV, 48K, 8.9 GB. Tool calls + results verified; live cria/Codex run passed |
| **ling3-tiny** (7.9B-A1.3B MoE) | Q6_K | `temp 1.0, top_p 0.95, top_k 20` | [bloomer010 card](https://huggingface.co/bloomer010/Ling-3.0-tiny-GGUF) quoting inclusionAI | **added 2026-09-27.** `bailingmoe3` (18 KDA + 6 MLA layers, no MTP) — needs upstream ≥ 2026-09-20 (Ling tool parser + PEG UTF-8 fix). **f16 KV** (MLA KV is tiny; tg@32K 200 vs 181 at q8_0), ub 2048 (prefill +10–35%), `ngram-mod` n-min 16: decode 216 code / **1361 edit**. 48K, 7.1 GB. Occasional mid-think termination is documented by the quantizer as inherent to the weights |
| **phi4** (14.7B dense) | Q4_K_S | `temp 0` all roles | [microsoft/phi-4 card](https://huggingface.co/microsoft/phi-4) (`inference.parameters.temperature: 0`) | **added 2026-09-27.** **Made to fit the 3080** at its full TRAINED 16K: q8_0/q8_0 OOMs; **K q8_0 + V q4_0** fits at 9.5 GB, ~70 t/s — a mixed KV pair is only fast on a `GGML_CUDA_FA_ALL_QUANTS` build (tg@8K 54.8 vs 46.7 on the plain build). **Needs `templates/phi4-tools.jinja`**: the embedded template shows no tools and DROPS `tool` messages, so a tool result never reached the model; the replacement keeps phi-4's turn tokens and adds Hermes `<tool_call>` JSON (verified end to end). `ngram-mod` n-min 16 (default 48 cost 9% on fresh code). Known gap: through cria's planner it sometimes emits a fenced ```` ```json {"name":…}``` ```` call that the planner does not recover |
| **k2-horizon** (7B dense) | Q6_K | `temp 1.0, top_p 0.95` (reasoning_effort high = template default) | [IFM/K2-Horizon-7B card](https://huggingface.co/IFM/K2-Horizon-7B) | **added 2026-09-27.** Arch `k2-horizon` is NOT upstream: **MBZUAI-IFM fork `model/K2Horizon` (42adf01)**, built with FA_ALL_QUANTS. 36 layers × 8 KV heads, 250K vocab. **40K ctx at K q8_0 / V q4_0 = 9.08 GB** (48K = 9.58 GB, <300 MB free — rejected; q8_0/q8_0 caps near 32K). Decode decays with depth (84 → 57 @16K → 46 @28K) identically across KV pairs. `ngram-mod` n-min 16: 81 code / **1044 edit**. Template accepts both `enable_thinking` and `reasoning_effort`; XML tool calls parsed by the fork; live cria/Codex run passed |
| **qwen38** (27B, Qwen3.8) — **NOT part of cria testing (2026-09-27): the operator's separate model on the 3090; still installed** | UD-Q4_K_S | `temp 0.7, top_p 0.80, top_k 20` (instruct mode; thinking mode `1.0/0.95/20`) | Qwen's own card | **the only DUAL-GPU model** (3080 + 1080). Arch reports as `qwen35` — hybrid Gated-DeltaNet with a full-attention layer every 4th, so only 16 of 65 blocks hold a growing KV: ~34.8 KB/token at q8_0, roughly a quarter of a same-size dense model. `ctx_train` **262144**. Needs the `~/src/llama.cpp-qwen38` build (§Server launch) — the stock b9893 tree has a `qwen35` builder but predates the NextN/MTP handling these GGUFs carry and will not load the file. KV **`q8_0` — do NOT use `iq4_nl`/4-bit here**, it cost 2.3× decode and 11× prefill in the field (§The field regression). Runs `--spec-type draft-mtp`; the draft block is **inline** in the GGUF (blk.64), so speculation costs one block, not a second model — but acceptance is only 47–76% on reasoning prose, so it is close to a wash on cria traffic. See §VRAM accounting on WSL for the `--fit-target` requirement — without it this model quietly runs a quarter of itself on the CPU |
| **maple-preview** (20B-A1B MoE) | **tq2_0** (ternary, GGML type 35) | `temp 1.0, top_p 0.95, top_k 64, repeat_penalty 1.0` | ⚠ no publisher card — NEUTRAL start | DeepGrove; 256 experts / 8 active. Needs the **stamsam/llama.cpp fork @ prism 9ee03ee** (its commit IS the tq2_0 CUDA kernel work — mainline cannot load the arch). Embedded template, no toggle template earned yet; emits `reasoning_content` on every coder reply (25/25 sampled, run 1786228135). `repeat_penalty 1.0` is deliberate: the penalty is a per-model finding, never a default |

> ⚠ **`qwopus` is unverified** — the values are inferred. Confirm from the model card or empirically before treating them as recommended.

> **Dense vs MoE, read from GGUF headers** — `general.architecture` plus
> `<arch>.expert_count` / `expert_used_count`, never a card or a name. The current run matrix is:
>
> | dense | architecture | MoE | experts (active) |
> |---|---|---|---|
> | ternary-bonsai-2 27B | `qwen35` | | |
> | gemma4-qat 12B | `gemma4` | | |
> | defiant-fable 9B | `qwen35` (33 blocks = 32 + 1 MTP) | | |
> | ornith15 9B | `qwen35` | | |
> | qwen38-distill 9B | `qwen35` (33 blocks = 32 + 1 MTP) | | |
> | phi4 14.7B | `phi3` | | |
> | k2-horizon 7B | `k2-horizon` | | |
> | | | ling3-tiny 7.9B | `bailingmoe3` 128 (8) + 1 shared |
>
> `lfm25` has a systemd unit but **no entry in `models.toml`**, so it cannot launch — fix that before putting it in any run order.

> **ternary-bonsai speculative decoding (verified 2026-07-28):** the Q2_0_g128 GGUF does **NOT** contain MTP layers (`--spec-type draft-mtp` is a FATAL load error — the service crash-loops, no graceful fallback). `--spec-type ngram-cache` works and **doubled decode: 8.3 → 17.1 tok/s** (48% draft acceptance on code; n_draft=8). Set per-model in llama-fleet models.toml extra_flags. KV: `-ctk q8_0 -ctv q4_0` (asymmetric; K drives logits, V tolerates 4-bit).

> **draft-dspark — measured dead end on this box (2026-07-28):** the companion 3.6B drafter (`Ternary-Bonsai-27B-dspark-Q4_1.gguf`, 6 blocks, drafts 4-token blocks conditioned on target hidden-state taps at layers 1/16/31/46/61) *loads and runs* on the spare GTX 1080 (`cuda_device` widened to both GPUs, `--spec-draft-device CUDA1 --spec-draft-ngl all --spec-draft-n-max 4` — n-max MUST equal the drafter's `block_size=4`). Three structural costs sank it: (1) its staging forward covers the **full target context** (~216 KiB compute buffer per position on the draft device → 49K ctx needs 10.4 GiB, so ctx had to drop to 24K just to fit); (2) target-side tap capture cut **prefill ~3× (360 → ~112 tok/s)** and **disables prompt-cache reuse** — every agentic call would re-prefill its whole history; (3) each draft round is a full-context drafter forward on Pascal → **decode 4.2–4.8 tok/s**, *below the 8.3 no-spec baseline* and falling with depth. Acceptance itself was good (62%, ~3.5 tok/target-forward ≈ 29 tok/s if drafting were free) — the drafter wants a fast co-resident device, not a spare Pascal. Re-try only with a second fast GPU; until then ngram-cache stays.

> **draft models are off the table for this target entirely (measured 2026-07-28):** a vocab-exact Qwen3.5-0.8B Q6 drafter co-resident on the 3080 (same `qwen35` family, 248320 vocab, fits in the spare ~2 GB at 49K — no dspark-style staging buffer) still measured **2.4 tok/s vs ngram's 7.1** on an identical deep-context (6.9K) benchmark, despite 51% acceptance and drafting costing only 2.8s of the 105s total. Root cause: the 27B is a **hybrid-SSM** (`qwen35` arch, recurrent layers) — its state cannot rewind, so every speculative round pays ~2s of checkpoint save/restore machinery (`-cms 8` changed nothing: it's the state copies, not re-prefill distance). Only opportunistic near-free drafting (ngram-cache) survives on a hybrid target; per-round draft speculation loses on ANY GPU. The 0.8B GGUF stays at `/home/jesse/models/Qwen3.5-0.8B/` for a future attention-only target.

> **TurboQuant KV = THE win — live since 2026-07-28.** The "no fork has both" assumption died on
> a search: **`jarkevithwlad/turboquant-prismml-cuda` v1.0.1** merges PrismML's Q2_0_g128 kernels with amesianx TurboQuant; the sm86 (RTX3090Ti) Linux release runs on the 3080 (needs `libnccl.so.2` — copied into the build dir from the `nvidia-nccl-cu12` pip wheel; KV type names are `tbq3/tbq4/tbqp3/tbqp4`, NOT the atomic fork's `turbo2/3/4`). Same-build A/B, ternary-27B on the 3080, `-fa on`: **tg128@d8192 11.3 → 48.7 t/s (4.3×)**, pp2048 168 → 845, pp@8K 22 → 189, shallow tg ~par (51.9 → 49.3). Decode becomes ~depth-independent. **CORRECTED MECHANISM (operator-prompted, f16 control 2026-07-28): the wall was the QUANTIZED-KV CODE PATH, not KV bandwidth.** Same build, tg64@d8192: q8_0/q4_0 = 11.3, tbq3 = 48.7, **f16 = 61.1** — plain f16 beats turbo. TurboQuant's real win is the COMBINATION: its cache code avoids the pathological quantized path AND fits 49K ctx (~5.6 GB f16 KV + 6.7 GB weights exceeds the 3080; f16 caps ctx at ~20K). Untested knob: tbq4 (more quality margin, still fits). Live serving verified 53 t/s with correct output; no `--spec-type` (build lacks the prism spec framework; pointless at 50 t/s anyway). Rollback = prism b9596 + ngram (in models.toml comments). **Quality at real agentic depth (20K+, long sessions) not yet proven — the next goal runs referee it.** *(Update, same day: run m15 completed the goal fully unaided on this config with zero incoherence — first quality referee PASSED.)* Earlier fun-sized data point: the AtomicBot fork (`~/src/llama.cpp-turboquant/`, types `turbo2/3/4`) also works, even on the Pascal 1080 (Qwythos-9B: +5% at 8K depth, −14% prefill) — but it lacks the prism kernels.

> **Bonsai 2 27B replaces Bonsai 1 — and needs NO TurboQuant (measured 2026-09-18).** `prism-ml/Ternary-Bonsai-2-27B-gguf`, same `qwen35` hybrid arch, two new packings (`PTQ1_0` 5.95 GB dense trits, `PQ2_0` 7.21 GB 2-bit slots) that **only the official PrismML fork can load** — the live TurboQuant build has no `ptq1_0`/`pq2_0` symbols and no Hadamard activation runtime, and TurboQuant is now **discontinued** (archive notice, `amesianx/turboquant`), so tbq3 is a dead end for Bonsai 2 forever. Binary = `prism-b10685-7dffb15` at `~/src/llama.cpp-prism2/` (what `PrismML-Eng/Bonsai-demo` pins; the newer `b10687` tag ships Windows assets only). **The KV trap bit again:** carrying Bonsai 1's rollback-recipe `-ctv q4_0` over to Bonsai 2 reproduced the pathological quantized-KV path exactly as documented above — pp2048@d8192 **17.5 t/s with q8_0/q4_0 vs 1090 t/s with q8_0/q8_0** (tg128@d8192 8.0 → 58.8). A Bonsai 1 control on its own TurboQuant build at q8_0/q4_0 measured 17.5/8.8 — i.e. **the collapse was 100% the V-cache type, not the new model or the new binary.** Final A/B at q8_0/q8_0, same box, same bench: PQ2_0 **pp@8K 1090 / tg@8K 58.8** vs PTQ1_0 602 / 49.1 — PQ2_0 wins both phases for 1.26 GB more, and beats the LIVE Bonsai 1 + tbq3 baseline (188 / 43.3) by **5.8× prefill and 1.36× decode**. Live at `-c 49152`, 8728/10240 MiB VRAM. **So the fleet-wide `-ctk q8_0 -ctv q8_0` default is now truly fleet-wide — ternary-bonsai's override is gone with Bonsai 1.** Behavioral note: the card's default `xhigh` reasoning effort is real — cria's `reasoning = "on"` already maps to `medium` (auto-detected `openai` style), yet coder steps still ruminated 3.8–4.1K reasoning tokens and `rumination.abort` fired twice in a 3-turn live run (~200s each). Plan→coder→tool pipeline otherwise ran clean end-to-end. **No rollback as of 2026-09-18** — operator call to treat new models as replacements: `[models.ternary-bonsai]`, its unit, its GGUFs (8.5 GB) and both Bonsai-1-only binaries (`llama.cpp-tq-prism` TurboQuant, `llama.cpp-prism` b9596) are deleted. Reverting means re-downloading `prism-ml/Ternary-Bonsai-27B-gguf` — and the tbq3 config is **not** reconstructible as-is, since that build is gone from the box and TurboQuant upstream is discontinued. The TurboQuant paragraphs below are kept as the measurement record, not as a live option.

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
> a foreign distribution, the "acceptance halved" finding above does not apply to it — which is why it
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
> (measured 2026-09-18).** Bonsai 1's numbers are the row above: dspark **62%**, generic Qwen3.5-0.8B
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

> **Fleet-wide TurboQuant sweep (2026-07-28): NO win for any other model — q8_0 stays the fleet default.** All 7 fleet models benched on the 3080 (AtomicBot build, q8_0 vs turbo3, shallow + 8K depth, r=3, zero errors): tg@8K deltas par to −13% (lfm25 277→249, mellum2/ornith par, qwythos/gemma4 noisy-worse, qwopus within its control's noise band). The ternary-27B is the ONLY winner because its 2-bit weights make KV reads the dominant decode term at depth — the 8–12B fleet models already decode 65–277 t/s deep (weight-bound, several MoE/hybrid with small KV), so 3-bit KV just adds quantization work. TurboQuant = ternary-only. **32K-depth follow-up (operator: "these weren't deep runs"): the loss GROWS with depth** — tg64@d32768 q8_0→turbo3: lfm25 230→163, ornith 68→49, qwopus 67→50, gemma4 60→44, qwythos 67→64. The hybrids' KV stays small at depth, so turbo3's per-read dequant overhead scales while the savings never arrive. ONE inconclusive cell: mellum2's q8_0 control went unstable at 32K (93±58) while turbo3 held 140±0.6 — repeat before trusting either number if mellum2 ever goes live again.

> **Context-vs-speed tradeoff, qwythos (measured 2026-07-28; tg64, tok/s):**
>
> | depth | 8K | 32K | 65K | 131K | 196K | max fit |
> |---|---|---|---|---|---|---|
> | q8_0   | 80 | 68 | 51 | 38 | — | **~143K** |
> | turbo3 | 76 | 59 | 49 | 33 | 26 | **~375K** |
>
> Per-token KV (from the GGUF header: 8 attn layers × 4 kv-heads × 256+256): q8_0 ≈ 17 KiB, turbo3 ≈ 6.5 KiB. Rule: **q8_0 up to ~131K; turbo3 only past q8_0's ~143K ceiling** (3–12% slower at every shared depth — its gift is reach, not speed). qwythos trains to 1M so VRAM is the only limit; note the fleet's 49K default is conservative for this model — 131K on plain q8_0 fits TODAY. **the retired Ornith 1.0 and qwopus are KV-identical** (same 32 blocks / every-4th attention / 4 heads / 256+256, verified from headers) so these numbers transfer — but they train to 262K, which becomes their useful cap. WSL caveat (measured, correcting an earlier bogus-probe claim): a beyond-VRAM ctx neither loads nor fails fast — the load HANGS (>5 min timeout at 262K q8_0 on qwythos; WSL UVM). Derive ceilings by arithmetic (per-token KV × ctx + weights vs 10 GB), never by load-probing.
>
> **gemma4 (measured 2026-07-28; tg64, tok/s):** q8_0 = 62 / 57 / 49 / 40 at 8K / 32K / 65K / 131K; turbo3 = 58 / 52 / 46 / 36 — **q8_0 wins every depth (~7–9%), and gemma4's SWA (1024-token window on most of its 48 layers) keeps KV small at any context, so turbo has no reach advantage either. TurboQuant: nothing to offer gemma4.** 131K verified on q8_0; the 262K training cap likely fits too.

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

## `merge_consecutive_turns` — strict role alternation

Meta's Llama chat-template lineage enforces alternation literally:

```jinja
{%- if (message['role'] in ['user','tool']) != (loop.index0 % 2 == 0) -%}
  {{- raise_exception('Conversation roles must alternate between user/tool and assistant') -}}
```

Every even position must be user-or-tool, every odd one assistant. **cria's whole anchor mechanism is consecutive user turns** — ⟦ctx:checks⟧, ⟦ctx:steer⟧, ⟦ctx:facts⟧ each arrive as their own message — so a Llama-lineage model rejects cria outright. Measured on nemotron-nano: the FIRST coder call, system plus three user turns, returned 400 twice and the run died in 24 seconds having made two calls.

`[roles.<name>] merge_consecutive_turns = true` collapses each run of consecutive same-SIDE messages into one. Side, not role: the template renders a `tool` result as a user turn, so `{user, tool}` is one side and `{assistant}` the other — merging by role alone would miss the common tool-result-then- anchor pair. Nothing is dropped or reordered; cria's anchors are self-delimiting blocks so concatenation reads exactly as separate turns did. A merged run keeps its first message's role, so a leading tool result keeps its `<TOOL_RESPONSE>` framing, and an assistant turn carrying `tool_calls` is never folded into or out of.

**Who needs it.** Only Llama-lineage templates. Checked in the GGUFs: Qwen3.5, Qwythos and Nemotron-H carry zero alternation guards. Note the two Nemotrons are unrelated — `nemotron-elastic` is NVIDIA's own mamba-hybrid architecture with its own permissive template; `nemotron-nano` is a Llama-3.1 derivative and inherits Meta's convention.

Every shape was verified against the live server, 400 before and 200 after: three stacked anchors, a tool result followed by an anchor, and two consecutive assistant turns.

---

## `collapse_system_prompt` — where the instruction goes

cria writes every instruction it gives into a **system** message: the coder frame, every judge, the steer author, the compactor, the classifier. Right for most chat templates, wrong for some, and until 2026-08-08 nothing in cria knew the difference — 12 construction sites, no owner.

`[roles.<name>] collapse_system_prompt = true` folds every leading system message into the front of the first user turn. One place (`Role.apply`, the same hook that translates sampling and reasoning), so it covers every request that role makes. Off by default; `suite/sampling.py` writes it per model on each swap, exactly like sampling, so a stale value cannot survive a model change.

**When to set it.** Read the model's chat template, not its card alone. The question is whether the template has somewhere to PUT a system message:

- **r1-llama** — the case that prompted the knob, but currently **OFF**. The template captures the message and emits it as `{{bos_token}}{{ns.system_prompt}}` — bare, after BOS, before the first `<｜User｜>` marker. The text reaches the model but lands outside the conversation structure it was trained on, and cria's system prompts run to thousands of characters. Its loop also keeps only the LAST system message, so a second one is discarded silently; the fold joins them in order instead.

  **Why it is off anyway (researched 2026-08-08).** The card says no system prompt, but real-world reports are split. One of the model's own developers measured a system prompt at temp 0.7 as *"close to the 'no system prompt'"* result, and another user reports the QwQ system prompt working fine; against that, one credible report of the model *"hung up repeatedly second guessing itself in a loop"* inside the recommended temperature range, and cline filed a real degradation for exactly this. DeepSeek's own issue asking the question was closed as stale with no maintainer answer. So: a named failure mode to watch for, not a settled fact. cria also never sends more than one system message — measured, 527 of 527 captured bodies across six sessions — so the multi-message discard is hypothetical here. Turning the fold on for the first run would confound the question this model is on the ladder to answer. Flip it and re-run if the loop symptom appears.

  Sources: HF discussions on the Qwen-32B and Qwen-7B distills, DeepSeek-R1 issue #33, cline #5477.
- **Everything else on the ladder** — does not. Qwen-, Gemma-, Nemotron- and ternary-derived templates all have a real system slot.

The fold preserves order, never drops text, and creates a user turn when a body has none (a judge asked system-only would otherwise lose its whole question).

---

## Reasoning ON / OFF — the mechanism and per-model reality (verified 2026-07-08)

**How it works.** Reasoning is toggled entirely by the **server-side chat template**, driven by one per-request boolean. cria (like codex-local's `ollama.rs`) sends **only** `chat_template_kwargs.enable_thinking = <bool>` on the wire — nothing else. The magic is in each model's `*-toggle.jinja`: when `enable_thinking=false` it **prefills an empty, closed think block** into the generation prompt — `<think>\n\n</think>\n\n` (Qwen family) or an empty `<|channel>thought` (Gemma). It is a **prefill, not a directive** (grepping all six templates for "do not think / answer directly" returns zero hits). The empty block is a *trained control signal*: "reasoning already done, answer now."

**So OFF works only on models trained to honor that signal.** The toggle files prefill **byte-identical bytes** for the models that work and the ones that don't — the divergence is the model, not the template.

| Model | ON | OFF (`enable_thinking=false`) | Why |
|-------|----|--------------------------------|-----|
| **qwopus / ornith15 / qwythos** | ✅ | ✅ clean direct answer | **Qwen3-derived** — honor the empty `<think></think>` control block |
| **ternary-bonsai** | ✅ | ✅ clean direct answer | **Qwen3.6-derived** — embedded ChatML honors `enable_thinking` (verified on/off at load) |
| **gemma4-finetune** (retired) | ✅ | ✅ clean direct answer | honors the empty `<|channel>thought` — finetune-era record; gemma4 NOT yet verified for the OFF recipe |
| **qwen3.5** | ✅ | ✅ clean direct answer | Qwen3.5 base — **verified at load 2026-08-08**: `enable_thinking=false` → 0 chars of `reasoning_content`, `true` → 649, both answered correctly |
| **defiant-fable** | ✅ | ✅ clean direct answer | Qwen3.5 finetune, embedded template gates on `enable_thinking` (no `reasoning_effort`, so cria's default `chat_template` style is correct). **Verified at load 2026-09-25** through the systemd unit, MTP on: `false` → 0 chars, `true` → 659, both correct |
| **maple-preview** | ✅ | ⚠ UNVERIFIED | embedded template, no `*-toggle.jinja` earned yet. ON is certain — 25/25 sampled coder replies carried `reasoning_content`. OFF has never been exercised |
| **nemotron-nano** | ✅ `detailed thinking on` | ✅ `detailed thinking off` | **cria's THIRD reasoning convention** — the switch is a sentence in the system prompt, not a body parameter. `reasoning.system_directive()` renders it; `config._set_reasoning_directive` prepends it to the leading system message (the mutation lives with the messages, same as the chat_template OFF prefill). Reasoning-unset leaves the model's own default alone |

**Known native-OFF models** include qwopus, ornith15, and qwythos (verified on the retired gemma4-finetune — re-verify gemma4 before relying on OFF). Some template families (LFM2-style) empty `reasoning_content` under `enable_thinking=false` yet still deliberate in prose in `content`, which cria's parsers can't strip (no `<think>` tags) — a model limitation to check when adding a model, not a missing manipulation.

**The per-model "manipulation" you built** was exactly these `*-toggle.jinja` files (and, for a whole-instance off, `.reason-off` launch scripts that bake the `-nothink` template via `--chat-template-file`, plus `--reasoning-format deepseek` for ornith). qwopus's *stock* template hardcoded `<think>` with no gate — which is precisely why the toggle had to be hand-built.

**What cria does on `reasoning = "off"` (SHIPPED — `LocalRole.apply` / `clean_content` in `config.py`).** Per request cria applies THREE things so OFF works on any loaded model without per-model config:
1. `chat_template_kwargs.enable_thinking = false` — suppresses thinking on the native-off models.
2. appends a **mild no-think directive** to the system message ("Do not think out loud or narrate your reasoning. Respond directly.") — makes prose-deliberating template families answer directly.
3. **strips any leaked reasoning** ahead of a `</think>` marker from the model's `content`.

**Honest result (verified end-to-end 2026-07-08):**
- **Native-off models** (qwopus, ornith15, qwythos; verified on the retired gemma4-finetune — re-verify gemma4 before relying on OFF) → OFF is **clean**.
- On a prose-deliberating template family, OFF engages and is clean on direct tasks, but reasoning-heavy prompts stay verbose (no `</think>` marker for the strip to catch). It never breaks cria — just chatty. A *harder* directive makes such models terser but **wrong** (a reasoning-trained model loses accuracy when starved of reasoning), so the directive is deliberately mild.

**Guidance:**
- Flip any role `reasoning = "on"` / `"off"` in `~/.cria/cria.toml` and restart cria — it takes effect per request, no model reload, no per-model wiring needed.
- `cria.toml` ships every role `reasoning = "on"` (clean fleet-wide; also what coding wants).
- If a role needs **terse** OFF output, point it at a **native-off model** (a Qwen-derived one).

---

## Server launch (`models.toml`) — uniform except model + template

All models share: `-c 49152` (48K) · `-b 2048 -ub 512` · `-np 1` · `--device CUDA0 -ngl auto -sm none -mg 0` · `-ctk q8_0 -ctv q8_0` **(now every model, incl. ternary-bonsai-2; only the retired Bonsai 1 entry overrode it with `tbq3`)** · `-fa on --no-host --no-mmproj --no-warmup --jinja` · `--reasoning auto` (the *parsing* mode — distinct from per-request `enable_thinking`) · `--host 127.0.0.1 --port 18084`. **Sampling is NOT set here** (cria sends it per request).

Most models differ only by source + chat template (all in `~/shepherd-eval/templates/`). **Five override `binary` + `lib_dir`**, because their weight format or model layout needs support the stock build does not carry. In every case `lib_dir` must LEAD with the fork's own dir, then `cuda-12.8-local/lib64` and `/usr/lib/wsl/lib`.

| Model | Fork | Why |
|-------|------|-----|
| ternary-bonsai-2 **(live)** | `~/src/llama.cpp-prism2/b10685/llama-prism-b10685-7dffb15/` | `PQ2_0`/`PTQ1_0` ternary kernels + Hadamard activation runtime. Stock KV (`q8_0` both) — **never `-ctv q4_0`, it costs ~60× prefill at depth** |
| maple-preview | `~/src/llama.cpp-maple-prism/build-cuda/bin/` | `tq2_0` ternary kernels (stamsam fork @ prism 9ee03ee); mainline cannot load the arch |
| defiant-fable | `~/src/llama.cpp-ornith15/build-cuda/bin/` (shared with ornith15) | Same failure, same fix: the stock build (upstream 2026-04-21 plus local CCCL patches) rejects the Qwen3.5 MTP block with `missing tensor 'blk.32.ssm_conv1d.weight'`. **Any qwen35 GGUF with `nextn_predict_layers=1` needs this build or a newer one** — check the header before assuming the stock build will do |
| ornith15 | `~/src/llama.cpp-ornith15/build-cuda/bin/` | upstream 74a7c897. Stock b9893 rejects Ornith 1.5's final MTP block with missing `blk.32.ssm_conv1d.weight`; the dedicated current build loads it. |
| qwen38 | `~/src/llama.cpp-qwen38/build-cuda/bin/` | upstream b10497 (9731ad3f2). NOT a fork — the stock tree is simply too old (b9893, Apr 22) and lacks the NextN/MTP layer handling. Built for `CMAKE_CUDA_ARCHITECTURES=61;86` so it drives the Pascal 1080 as well as the 3080; NCCL vendored at `vendor-nccl/`. ⚠ Rebuilds MUST run with `LD_LIBRARY_PATH` including `cuda-12.8-local/lib64`, or the executable link fails resolving `libcudart.so.12` |

| Model | Source | Template |
|-------|--------|----------|
| ternary-bonsai | `-m …/Ternary-Bonsai-27B/Ternary-Bonsai-27B-Q2_0.gguf` **(PrismML fork binary + lib_dir)** | *(embedded ChatML)* |
| gemma4 | `-m …/gemma4-v2-Q4_K_M.gguf` | `gemma-toggle.jinja` |
| ornith15 | `-hf ornith-ai/Ornith-1.5-9B-GGUF --hf-file Ornith-1.5-9B-Q6_K.gguf` **(dedicated upstream 74a7c897 binary + lib_dir)** | *(embedded Qwen3 XML tools + `enable_thinking`)* |
| qwopus | `-hf Jackrong/Qwopus3.5-9B-v3-GGUF:Q6_K` | `qwopus-toggle.jinja` |
| qwythos | `-m …/Qwythos-9B-v2-Q6_K.gguf` | *(embedded)* |
| qwen3.5 | `-m …/Qwen3.5-9B-Q6_K.gguf` | *(embedded)* |
| defiant-fable | `-m …/Defiant-Fable-9B/Qwen3.5-9B-The-Defiant-Fable-Uncnr-Heretic-NEO-MAX-MTP-Q5_K_S.gguf` **(ornith15 binary + lib_dir; `--spec-type draft-mtp --spec-draft-n-max 2`)** | *(embedded Qwen3.5 w/ `enable_thinking`)* |
| maple-preview | `-m …/maple/maple-tq2_0.gguf` **(stamsam fork binary + lib_dir)** | *(embedded)* |
| qwen38 | `-m …/Qwen3.8-27B/Qwen3.8-27B-UD-Q4_K_S.gguf` **(b10497 binary + lib_dir; `--device CUDA0,CUDA1 -sm layer`)** | *(embedded ChatML w/ `enable_thinking`)* |

- **`-ub 512` is required** — a larger prefill micro-batch overflows the 10 GB 3080.
- **All fit the single 3080** (9Bs ~7.3 GB Q6_K; the 12B MoEs ~7–8 GB) — **except `qwen38`**, 14.3 GiB of weights across both cards.
- **Filename trap when pulling a quant:** unsloth model cards list K-quants WITHOUT the `UD-` prefix that the repo files actually carry. `Qwen3.8-27B-Q4_K_S.gguf` 404s to a 15-byte *Entry not found*. Always enumerate with `curl -s https://huggingface.co/api/models/<repo>?blobs=true` instead of trusting the card.
- The `*-toggle.jinja` templates gate on `enable_thinking` so the per-request flag works. Keep `--reasoning-budget` at default — launching with `--reasoning-budget 0` pins the whole instance no-think and defeats per-request control.

---

## VRAM accounting on WSL — the hidden CPU offload (found and cleared 2026-08-19)

**Symptom.** `qwen38` loaded, served, and looked fine — but generated at 10.2 t/s and read prompts at 50.9 t/s. `nvidia-smi` showed the two cards holding ~13.5 GiB between them, *less than the 14.3 GiB of weights*, which was written off as WSL misreporting. It was not. `-ngl auto` had silently parked **15 of 66 layers (4.3 GB) in system RAM**, which a `triad` benchmark measures at **44 GB/s** — seven times slower than even the GTX 1080's 320 GB/s. llama.cpp does not mention this at default verbosity; it only appears as `load_tensors: layer N assigned to device CPU` under `-lv 5`.

**Root cause — CUDA under-reports free VRAM inside the WSL guest.** Proven three ways, on an otherwise idle machine (monitor is on the iGPU; no display or compute process on either card):

| State | CUDA (`cudaMemGetInfo`) | NVIDIA driver (`nvidia-smi`) | Windows host (`vmwp.exe`) |
|---|---|---|---|
| idle, nothing running | — | 3080 **0 MiB**, 1080 32 MiB | **0 MiB** dedicated, both cards |
| **one bare CUDA context**, zero allocations | 3080 **1166 MiB**, 1080 **1005 MiB** | 3080 **214 MiB**, 1080 **136 MiB** | 3080 **213.3 MiB**, 1080 **104.6 MiB** |

The host and the driver agree to within a MiB. **CUDA is the sole outlier, overstating by ~1.85 GB.** Nothing is reserved, retained, or cached — `vmwp.exe` (the Hyper-V worker that owns the VM's GPU memory) holds nothing between runs. The gap is a *reporting artifact*, and llama.cpp's auto-fit believes it.

A direct ceiling test (`cudaMalloc` descending 256→0.25 MiB chunks until free hits 0) shows what is really reachable:

| Card | `cudaMemGetInfo` free | actually allocatable | unreachable |
|---|---|---|---|
| RTX 3080 | 9073 MiB | **9538.0 MiB** (+465) | 701.5 MiB |
| GTX 1080 | 7187 MiB | **7544.0 MiB** (+357) | 648.0 MiB |

Of the unreachable remainder, 187/133 MiB is the driver's own declared `FB Reserved` and 214/105 MiB is the context itself; ~300/~410 MiB stays unexplained by any queryable source. **Do not assert a cause for it** — an earlier claim that it was "a WSL reservation" was disproved by the host-side reading above.

**The fix — `--fit-target` (`-fitt`), and it accepts NEGATIVE values.** It sets the headroom the fitter holds back *per device* (default **1024 MiB each**, i.e. >2 GB withheld). Negative values tell the fitter to spend past the reported-free figure — which is not overcommitting, it is **correcting a bad reading**.

| `-fitt` | layers on CPU | weights on GPU |
|---|---|---|
| `1024` (default) | **15** | 11316 MiB |
| `384` | 8 | 12573 MiB |
| `192` | 6 | 12961 MiB |
| **`-600,-550`** ← set | **1** (the embedding only) | **13950 MiB** |
| `-750,-650` | 0 — but `cudaMalloc` then FAILS on the 394 MiB compute buffer. **The wall.** |

**Never use `-ngl` or `-ts` to chase this.** Setting either by hand makes the fitter abort outright (`tensor_split already set by user, abort` / `n_gpu_layers already set by user`), and nothing then reserves room for compute buffers — CUDA1 OOMs on a 394 MiB allocation and the unit restart-loops. `-fitt` *guides* the fitter; `-ngl`/`-ts` *disable* it. Shrinking `-b/-ub` also frees a little (`-b 512 -ub 128` reaches 4 CPU layers) but starves prefill, which is already the bottleneck — not taken.

**What remains on CPU at `-fitt -600,-550`** — placement `CPU 0-0, CUDA0 1-41, CUDA1 42-65`. That is 66 entries for 65 blocks, so index 0 is the **input embedding**, not a transformer block: **all 65 blocks, and the MTP drafter, are on GPU.** CPU holds `token_embd.weight` (686 MiB ≈ 248320×5120 at ~4.5 bpw), 12.5 MiB of recurrent state, and **zero KV**. Leave it: an embedding is a row *lookup*, ~2.5 KB per token — a 4865-token prefill gathers ~12 MB from host RAM, ~0.3 ms of an 80 s prefill. Moving it costs 686 MiB of VRAM that does not exist.

**Result** (ctx 49152, `--spec-type draft-mtp`, tg t/s; synthetic short-prompt probes — see the next subsection for why these overstate the field):

| task | start | `-fitt 192` | `-fitt -600,-550` |
|---|---|---|---|
| code — merge sorted lists | 10.24 | 21.12 | **28.38** |
| code — LRU cache class | — | 16.49 | **22.05** |
| short prose | 9.49 | 13.58 | **18.57** |
| long prose | 9.26 | — | **16.16** |
| prefill, 4865 tok | 50.9 | 56.1 | **60.5** (95.6 s → 80.4 s) |

**2.8× on code generation from hardware that did not change.** Draft acceptance tracks how predictable the output is — 93% on code, ~46% on prose — which is why speculation is worth keeping for cria's traffic and would not be for an essay workload.

**Probe tools** — kept in [`scripts/vram-probes/`](../scripts/vram-probes/) with their own README:
- `ctxprobe.cu` — cost of a bare CUDA context, CUDA's view vs the driver's.
- `allocmax.cu` — real allocation ceiling, descending chunk sizes.
- `probe_fit.sh` — boot the fleet config once with extra flags, print the **final** layer placement, kill it. Note the load log contains several *trial* fits; only the last `layer 0 assigned` block is the real one.

> **Do not size a config on this box from `nvidia-smi` or from `cudaMemGetInfo`.** Measure the ceiling, then set `-fitt` against it.


### The field regression: 4-bit KV cost 2.3× decode and 11× prefill (2026-08-20)

The offload fix above was measured with **40-token prompts, greedy sampling, thinking OFF, code output** — the single most favourable configuration. In real cria traffic the same server delivered **4.9 t/s weighted**. The synthetic 28.4 was not a lie, it was unrepresentative in four ways at once, and the gap is a lesson about benchmark design as much as about settings.

**Replay from captures, not synthetic probes.** `~/.cria/calls/<session>/NNNN-<phase>.json` stores the exact request body. Replay it verbatim — real tools, real message history, real sampling, `enable_thinking: true` — with only `stream:false` and a `max_tokens` cap added, so the *rate* is measured at real depth without waiting out an 8000-token generation. This reproduced the field number on the first try; no synthetic prompt did.

**Config matrix, real captured bodies** (`temp 0.2 / top_p 0.95 / top_k 20 / repeat_penalty 1.1`, thinking ON; shallow = 3.7K prompt, deep = 7.5K):

| KV | spec | `-fitt` | shallow tg | **deep tg** | pp |
|---|---|---|---|---|---|
| **`iq4_nl`** | on | `-600,-550` | 14.3 | **5.6** | **22–39** |
| **`q8_0`** | on | `-600,-550` | 15.0–20.2 | **11.9–13.9** | **249–275** |
| `q8_0` | on | `-350,-300` | 12.5 | 10.4 | 208 |
| `q8_0` | **off** | `-350,-300` | 12.2 | 11.9 | 367–390 |
| `q8_0` | **off** | `-500`/`-560` | 12.1 | 11.6 | 348–378 |

**`iq4_nl` KV was the whole regression.** 4-bit KV has no fast attention kernel for this model's `head_dim 256` on this hardware and falls back to something pathological — it does not merely cost bandwidth, it costs **11× the prefill**. Switching to `q8_0` costs ~750 MiB and buys 2.3× decode at depth. **This was already a documented fleet finding** (see the TurboQuant sweep above: *"the wall was the QUANTIZED-KV CODE PATH, not KV bandwidth"*, f16 beating turbo3 on the same build, and *"q8_0 stays the fleet default"*). It was set anyway, for headroom, and not re-tested under real load. **`q8_0` is the default for a reason — deviate only with a measurement at real depth.**

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
json.dump(b, open('/tmp/replay.json','w')); print('from', f)
EOF
curl -s 127.0.0.1:18084/v1/chat/completions -H 'Content-Type: application/json' -d @/tmp/replay.json \
 | python3 -c 'import sys,json;t=json.load(sys.stdin)["timings"];d=t.get("draft_n",0);print(f"pp={t[\"prompt_per_second\"]:.0f} tg={t[\"predicted_per_second\"]:.2f} accept={100*t.get(\"draft_n_accepted\",0)/d if d else 0:.0f}%")'

# WHERE THE LAYERS ACTUALLY WENT (the default log hides this — needs -lv 5).
# Stop the unit first; this boots a second instance. Only the LAST block is the real fit.
systemctl stop llama-qwen38 && llama-fleet qwen38 -lv 5 2>&1 | tee /tmp/fit.log | grep -m1 'listening on'
awk '/layer +0 assigned/{d=""} /assigned to device/{split($0,a,"device ");split(a[2],b,",");c[b[1]]++} END{for(k in c)print k,c[k]}' /tmp/fit.log
```
