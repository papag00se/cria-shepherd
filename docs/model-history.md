# Model history — tried, replaced, and abandoned

The models cria's fleet has **run, evaluated, or rejected**, and why. This is the graveyard and the paper trail; [`model-settings.md`](model-settings.md) holds only the CURRENT fleet's settings. When a model leaves the active fleet, its record moves here.

**Where the live evidence lives** (never trust this prose over the ledger):
- `suite/results/results.jsonl` — the authoritative run ledger; enumerate distinct models there, do not trust a doc's roster.
- `suite/historical_ladder.json` — FROZEN inference-usefulness rows for replaced models that still render in the engagement-ladder report (`gemma4`, `qwen35`).

---

## Retired / replaced / paused

- **nemotron-elastic** (NVIDIA Nemotron-Labs-3-Elastic 12B-A2B) — restored to the active fleet 2026-09-30. Exact source: `mradermacher/NVIDIA-Nemotron-Labs-3-Elastic-12B-A2B-GGUF` Q4_K_M, derived from DavidAU's Elastic model; original local path and launch settings recovered from `~/.config/llama-fleet/models.toml.pre-retire-20260918`. Exact L0–L4 row IDs, task scores, and `(minutes,calls)` are frozen in `suite/historical_ladder.json` from `acd9017f^:suite/results/results.jsonl` plus `acd9017f^:suite/historical_ladder.json`. Historical L5 is deliberately not restored as a fresh row. Verified model file is installed at the recovered path and its SHA-256 matches the HF LFS OID. Historical systemd journal confirms the same service successfully ran on the pinned 3080 for 3d 13h; service is restored but disabled/inactive pending the campaign operator's planned swap.
- **ornith 1.0** (9B) — the version tested before 2026-09-05 (`deepreinforce-ai/Ornith-1.0-9B-GGUF:Q6_K`). Replaced by `ornith15`; historical result rows remain `ornith` so releases are never conflated.
- **gemma4-finetune** (yuxinlu1, 12B) — replaced by stock `gemma4` on 2026-08-05 after repeated runs showed stock completing substantially more of the same lane. 46 result rows; kept for its history.

---

## Tried and failed — purged 2026-09-27

Seven models in this table were tried and purged. On the operator's order, their units, weights, launch entries, result rows, captures, walks and working directories were deleted. "No score" means a model ran before inferred-usefulness judging existed, so no percentage was ever recorded.

| model | what it was | result |
|---|---|---|
| gigachat31 | GigaChat 3.1 10B-A1.8B MoE | usefulness **mean 0.5%, best 2%** (6 L5 cells) |
| mellum2 | Mellum2 12B-A2.5B MoE | no score (48 runs, 27 reached a clean exit) |
| maple-preview | DeepGrove Maple-Preview 20B-A1B ternary MoE | no score (18 runs, 10 reached a clean exit) |
| fabliq-reasoning | Fabliq 8B Agent Reasoning | no score (13 runs, none completed) |
| zaya1 | ZAYA1 8B-A760M MoE | no score (7 runs, 6 stalled at the 15-min milestone) |
| nemotron-nano | Llama-3.1-Nemotron-Nano 8B | no score (llama.cpp could not serve its tool calls) |
| lfm25 | LFM2.5 8B-A1B MoE | never run in the suite |

---

## Considered and REJECTED for the Llama-family slot (2026-08-08, closed 2026-08-09)

cria's coder path is ~100% tool calls and its assists assume a thinking channel, so a Llama-family model needs BOTH. **The slot is CLOSED — all three candidates failed, the third on grounds no model choice can fix.** Three were tried:

- **Dolphin 3.0 (Llama-3.1-8B)** — trained for function calling (`hermes-function-calling-v1`) but instruct-only, no thinking channel. Would have changed the family AND removed reasoning in one step, confounding the question the slot exists to answer. (Evaluated on paper; no run rows.)
- **DeepSeek-R1-Distill-Llama-8B** (`r1-llama`) — reasoning, but tool use was never a training objective. MEASURED on this box: **0/4, 30 calls, ZERO assistant turns ever entered the conversation.** It emitted an invented `<tool name="web_fetch" call="begin">` in prose; llama.cpp parsed no tool call, the harness recorded no action, and every turn restarted from the task. Pinning llama.cpp's `llama-cpp-deepseek-r1.jinja` (the embedded template has NO tools branch at all) was necessary and not sufficient — the template can express a call the model cannot produce. DeepSeek's own distill discussion: tool use "is not one of the main goals for the model"; Fireworks lists R1 tool calling as "Not supported"; R1-0528 added it, but its 8B distill is Qwen3-based and would have been our fifth Qwen.
- **Llama-3.1-Nemotron-Nano-8B** (`nemotron-nano`) — tried and failed; see *Tried and failed* above.

---

## Considered and DROPPED: **Moonlight-16B-A3B-Instruct** (2026-08-01)

Raised by the operator, investigated, and dropped the same day. Recorded here so it is not raised again without new information.

**Why it was dropped: no evidence it does tool calling.** cria drives a tool-use loop; a model that cannot emit a tool call cannot be a coder or a planner here. Checked [Moonshot's card](https://huggingface.co/moonshotai/Moonlight-16B-A3B-Instruct), all three GGUF conversions, the [OpenRouter listing](https://openrouter.ai/moonshotai/moonlight-16b-a3b-instruct) and vLLM's tool-parser list — **not one mentions function or tool calling**. The model is a research artifact: the demonstration model for Moonshot's Muon-optimizer paper, whose point was that Muon scales, not that the model is an agent. `mmnga`'s conversion removed its chat template outright, calling it "custom" — a custom non-tool template.

**Two other facts that would have hurt anyway:**

- **8K context.** The fleet runs at 48K. An agentic coding run compacts constantly at 8K.
- **It does not fit comfortably.** The 3080 has 10,240 MiB; the smallest sane quant (`gabriellarson` Q3_K_M) is 8.29 GB, `mmnga` IQ4_XS 8.74 GB, `noctrex` MXFP4_MOE 9.3 GB. That was the TurboQuant condition the operator attached — and `deepseek2` being a mainline llama.cpp arch meant it probably *would* have loaded. The tool-calling gap is what settles it, not the VRAM.

**What would change the decision:** an instruct/agent release from Moonshot at this scale that documents tool calling — the operator's own read ("maybe an agent version will come out later"). Kimi-family agent models are the line to watch. A community fine-tune that merely adds a tool template is NOT sufficient; the capability has to be trained in.

**Note for whoever revisits this:** the base `moonshotai/Moonlight-16B-A3B` is a raw completion model with no instruction tuning — never a candidate. There is no coder-specific variant. Everything else on the Hub is a re-quant or fine-tune of Instruct.

---

---

## Retired-model settings and lab notes (moved from model-settings.md)

Moved out of [`model-settings.md`](model-settings.md) (doc defrag, 2026-11-02) so that file holds only the current fleet. Verbatim except where a pointer was needed; what the notes cite as "above/below" refers to this section. Sampling rows are the values each model ran with; none is current guidance.

### Retired settings rows

Columns as in the settings table: model | quant | sampling | source | notes. `qwen38` was a separate operator model, never a cria fleet member; `defiant-fable` is only the historical service name of a Qwen3.5 finetune (the logical model run under that service is now `qwen3.8_9b_distill`); the non-QAT `gemma4` quantization is one logical model with the current `gemma4_12b`.

| Model | Quant | Sampling | Source | Notes |
|---|---|---|---|---|
| **gemma4_12b** — historical non-QAT quantization (`gemma4` alias), **RETIRED + DELETED 2026-09-18**; historical settings kept for provenance, not a separate battery row | Q4_K_M | `temp 1.0, top_p 0.95, top_k 64, repeat_penalty 1.1` — ALL roles | Gemma 4 defaults (same pair the finetune's card pinned; kept identical so the 2026-08-05 ablation isolated weights) | replaced the yuxinlu1 finetune 2026-08-05 after repeated runs showed stock completing substantially more of the same lane |
| **qwythos** (9B) | Q6_K | `temp 0.6, top_p 0.95, top_k 20` | empero-ai (Qwen3.5 thinking) | **V2 swapped in 2026-07-12** (`/home/jesse/models/Qwythos-9B-v2-Q6_K.gguf`, alias `qwythos_9b_v2_q6`). The UNVERIFIED flag this row carried until 2026-08-08 is retired: V2 has run the ladder repeatedly at these values, and its newest capture (20260804T155422) shows `reasoning_content` on 20/20 sampled coder replies. **Re-confirmed 2026-09-18 from both ends:** file sha256 `dd39e148…` matches the `empero-ai/Qwythos-9B-v2-GGUF` LFS oid (it is the published Q6_K, not a stale/partial copy), and a direct toggle probe on the embedded template gave `enable_thinking` on = 322 chars `reasoning_content` / 137 tok, off = 0 / 4 tok, both answering correctly — so `models.toml`'s lingering "template UNVERIFIED" note was stale and is now removed |
| **qwopus** (9B, Qwen3.5) | Q6_K | `temp 0.6, top_p 0.95, top_k 20` *(inferred — Qwen3.5)* | ⚠ not stated on card | verify before trusting |
| **qwen3.5** (9B) | Q6_K | `temp 0.6, top_p 0.95, top_k 20` | Qwen's own thinking-mode card | the BASE the fleet's two 9B finetunes come from (qwythos = empero-ai's, qwopus = Jackrong's) — same size, quant, build and sampling as both, so a repeated usefulness gap is attributable to the weights. Added 2026-08-08; `unsloth/Qwen3.5-9B-GGUF:Q6_K`, 7.46 GB. Reasoning toggle **verified on load** (0 chars off / 649 on). Stock CUDA build, default q8_0 KV — TurboQuant was considered and dropped so a runtime change would not land in the same step as a model change |
| **defiant-fable** — the historical service/GGUF name of the Qwen3.5 finetune now run as the logical model `qwen3.8_9b_distill` (see [official names](model-names.md); not a separate battery row; the next row is the current Qwen3.8 distill) (9B, Qwen3.5 finetune) | Q5_K_S **MTP** | `temp 0.6, top_p 0.95, top_k 20` (identical to qwen35) | [DavidAU card](https://huggingface.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF): thinking/coding `0.6/0.95/20, min_p 0, presence 0, repeat 1.0` | **added 2026-09-25**. DavidAU + Nightmedia multi-stage heretic/abliterated merge of Qwen3.5-9B finetunes. File `Qwen3.5-9B-The-Defiant-Fable-Uncnr-Heretic-NEO-MAX-MTP-Q5_K_S.gguf` (note **`Uncnr`**, not the repo's `Uncensored` — the obvious name 404s), 7.14 GiB, sha256 `bf2e8ade…` = HF LFS oid. Set up like qwen35 (single 3080, `-ngl 99`, q8_0 KV, 48K, embedded template) with two MEASURED differences: **(1) binary** — the stock build rejects the MTP block (`missing tensor 'blk.32.ssm_conv1d.weight'`, the ornith15 failure), so it runs on the ornith15 build (upstream 74a7c897); **(2) `--spec-type draft-mtp --spec-draft-n-max 2`** — A/B on the 3080, same file and prompts: code decode **81.9 → 126.0 t/s (+54%, acceptance 0.95)**, prose **81.9 → 106.1 (+29%, 0.71)**, prefill ~19% slower. Sampling is held equal to qwen35 so a score gap is the weights. The card says to keep `repeat_penalty` at 1, because a higher value hurts MTP acceptance; do not carry over the 1.1 that the Bonsai rows use. The card's `reasoning_effort` / `{REASON:…}` modes belong to the separate Q6/Q8 **plusIQ** files; this file's template has only `enable_thinking` |
| **qwen38** (27B, Qwen3.8) — **NOT part of cria testing (2026-09-27): separate operator model, not a cria fleet member** | UD-Q4_K_S | `temp 0.7, top_p 0.80, top_k 20` (instruct mode; thinking mode `1.0/0.95/20`) | Qwen's own card | Historical dual-GPU bench details below are not current cria guidance. Arch reports as `qwen35` — hybrid Gated-DeltaNet with a full-attention layer every 4th, so only 16 of 65 blocks hold a growing KV: ~34.8 KB/token at q8_0, roughly a quarter of a same-size dense model. `ctx_train` **262144**. Needs the `~/src/llama.cpp-qwen38` build (§Server launch) — the stock b9893 tree has a `qwen35` builder but predates the NextN/MTP handling these GGUFs carry and will not load the file. KV **`q8_0` — do NOT use `iq4_nl`/4-bit here**, it cost 2.3× decode and 11× prefill in the field (§The field regression). Runs `--spec-type draft-mtp`; the draft block is **inline** in the GGUF (blk.64), so speculation costs one block, not a second model — but acceptance is only 47–76% on reasoning prose, so it is close to a wash on cria traffic. See §VRAM accounting on WSL for the `--fit-target` requirement — without it this model quietly runs a quarter of itself on the CPU |

> ⚠ **`qwopus` is unverified** — the values are inferred. Confirm from the model card or empirically before treating them as recommended.

### Retired Bonsai 1 (`ternary-bonsai`): speculative decoding, drafters and TurboQuant KV

Bonsai 1 was retired and deleted 2026-09-18; Bonsai 2 (`bonsai2`) needs none of this and keeps `q8_0`/`q8_0` KV. Measurement record only.

> **ternary-bonsai speculative decoding (verified 2026-07-28):** the Q2_0_g128 GGUF does **NOT** contain MTP layers (`--spec-type draft-mtp` is a FATAL load error — the service crash-loops, no graceful fallback). `--spec-type ngram-cache` works and **doubled decode: 8.3 → 17.1 tok/s** (48% draft acceptance on code; n_draft=8). Set per-model in llama-fleet models.toml extra_flags. KV: `-ctk q8_0 -ctv q4_0` (asymmetric; K drives logits, V tolerates 4-bit).

> **draft-dspark — measured dead end on this box (2026-07-28):** the companion 3.6B drafter (`Ternary-Bonsai-27B-dspark-Q4_1.gguf`, 6 blocks, drafts 4-token blocks conditioned on target hidden-state taps at layers 1/16/31/46/61) *loads and runs* on the spare GTX 1080 (`cuda_device` widened to both GPUs, `--spec-draft-device CUDA1 --spec-draft-ngl all --spec-draft-n-max 4` — n-max MUST equal the drafter's `block_size=4`). Three structural costs sank it: (1) its staging forward covers the **full target context** (~216 KiB compute buffer per position on the draft device → 49K ctx needs 10.4 GiB, so ctx had to drop to 24K just to fit); (2) target-side tap capture cut **prefill ~3× (360 → ~112 tok/s)** and **disables prompt-cache reuse** — every agentic call would re-prefill its whole history; (3) each draft round is a full-context drafter forward on Pascal → **decode 4.2–4.8 tok/s**, *below the 8.3 no-spec baseline* and falling with depth. Acceptance itself was good (62%, ~3.5 tok/target-forward ≈ 29 tok/s if drafting were free) — the drafter wants a fast co-resident device, not a spare Pascal. Re-try only with a second fast GPU; until then ngram-cache stays.

> **draft models are off the table for this target entirely (measured 2026-07-28):** a vocab-exact Qwen3.5-0.8B Q6 drafter co-resident on the 3080 (same `qwen35` family, 248320 vocab, fits in the spare ~2 GB at 49K — no dspark-style staging buffer) still measured **2.4 tok/s vs ngram's 7.1** on an identical deep-context (6.9K) benchmark, despite 51% acceptance and drafting costing only 2.8s of the 105s total. Root cause: the 27B is a **hybrid-SSM** (`qwen35` arch, recurrent layers) — its state cannot rewind, so every speculative round pays ~2s of checkpoint save/restore machinery (`-cms 8` changed nothing: it's the state copies, not re-prefill distance). Only opportunistic near-free drafting (ngram-cache) survives on a hybrid target; per-round draft speculation loses on ANY GPU. The 0.8B GGUF stays at `/home/jesse/models/Qwen3.5-0.8B/` for a future attention-only target.

> **TurboQuant KV = THE win — live since 2026-07-28.** The "no fork has both" assumption died on
> a search: **`jarkevithwlad/turboquant-prismml-cuda` v1.0.1** merges PrismML's Q2_0_g128 kernels with amesianx TurboQuant; the sm86 (RTX3090Ti) Linux release runs on the 3080 (needs `libnccl.so.2` — copied into the build dir from the `nvidia-nccl-cu12` pip wheel; KV type names are `tbq3/tbq4/tbqp3/tbqp4`, NOT the atomic fork's `turbo2/3/4`). Same-build A/B, ternary-27B on the 3080, `-fa on`: **tg128@d8192 11.3 → 48.7 t/s (4.3×)**, pp2048 168 → 845, pp@8K 22 → 189, shallow tg ~par (51.9 → 49.3). Decode becomes ~depth-independent. **CORRECTED MECHANISM (operator-prompted, f16 control 2026-07-28): the wall was the QUANTIZED-KV CODE PATH, not KV bandwidth.** Same build, tg64@d8192: q8_0/q4_0 = 11.3, tbq3 = 48.7, **f16 = 61.1** — plain f16 beats turbo. TurboQuant's real win is the COMBINATION: its cache code avoids the pathological quantized path AND fits 49K ctx (~5.6 GB f16 KV + 6.7 GB weights exceeds the 3080; f16 caps ctx at ~20K). Untested knob: tbq4 (more quality margin, still fits). Live serving verified 53 t/s with correct output; no `--spec-type` (build lacks the prism spec framework; pointless at 50 t/s anyway). Rollback = prism b9596 + ngram (in models.toml comments). **Quality at real agentic depth (20K+, long sessions) not yet proven — the next goal runs referee it.** *(Update, same day: run m15 completed the goal fully unaided on this config with zero incoherence — first quality referee PASSED.)* Earlier fun-sized data point: the AtomicBot fork (`~/src/llama.cpp-turboquant/`, types `turbo2/3/4`) also works, even on the Pascal 1080 (Qwythos-9B: +5% at 8K depth, −14% prefill) — but it lacks the prism kernels.

### Fleet-wide TurboQuant sweep and context-vs-speed (2026-07-28)

Conclusion that still stands: `q8_0` is the fleet default and TurboQuant is for the retired Bonsai 1 only. The gemma4 paragraph that followed these notes stayed in model-settings (gemma4_12b is current).

> **Fleet-wide TurboQuant sweep (2026-07-28): NO win for any other model — q8_0 stays the fleet default.** All 7 fleet models benched on the 3080 (AtomicBot build, q8_0 vs turbo3, shallow + 8K depth, r=3, zero errors): tg@8K deltas par to −13% (ornith par, qwythos/gemma4 noisy-worse, qwopus within its control's noise band). The ternary-27B is the ONLY winner because its 2-bit weights make KV reads the dominant decode term at depth — the 8–12B fleet models already decode 65–277 t/s deep (weight-bound, several MoE/hybrid with small KV), so 3-bit KV just adds quantization work. TurboQuant = ternary-only. **32K-depth follow-up (operator: "these weren't deep runs"): the loss GROWS with depth** — tg64@d32768 q8_0→turbo3: ornith 68→49, qwopus 67→50, gemma4 60→44, qwythos 67→64. The hybrids' KV stays small at depth, so turbo3's per-read dequant overhead scales while the savings never arrive.

> **Context-vs-speed tradeoff, qwythos (measured 2026-07-28; tg64, tok/s):**
>
> | depth | 8K | 32K | 65K | 131K | 196K | max fit |
> |---|---|---|---|---|---|---|
> | q8_0   | 80 | 68 | 51 | 38 | — | **~143K** |
> | turbo3 | 76 | 59 | 49 | 33 | 26 | **~375K** |
>
> Per-token KV (from the GGUF header: 8 attn layers × 4 kv-heads × 256+256): q8_0 ≈ 17 KiB, turbo3 ≈ 6.5 KiB. Rule: **q8_0 up to ~131K; turbo3 only past q8_0's ~143K ceiling** (3–12% slower at every shared depth — its gift is reach, not speed). qwythos trains to 1M so VRAM is the only limit; note the fleet's 49K default is conservative for this model — 131K on plain q8_0 fits TODAY. **the retired Ornith 1.0 and qwopus are KV-identical** (same 32 blocks / every-4th attention / 4 heads / 256+256, verified from headers) so these numbers transfer — but they train to 262K, which becomes their useful cap. WSL caveat (measured, correcting an earlier bogus-probe claim): a beyond-VRAM ctx neither loads nor fails fast — the load HANGS (>5 min timeout at 262K q8_0 on qwythos; WSL UVM). Derive ceilings by arithmetic (per-token KV × ctx + weights vs 10 GB), never by load-probing.
>

### Retired reasoning-toggle rows

Rows from the model-settings reasoning ON/OFF table for models no longer in the fleet.

| Model | ON | OFF (`enable_thinking=false`) | Why |
|---|---|---|---|
| **gemma4-finetune** (retired) | ✅ | ✅ clean direct answer | honors the empty `<|channel>thought` — finetune-era record; gemma4 NOT yet verified for the OFF recipe |
| **qwen3.5** | ✅ | ✅ clean direct answer | Qwen3.5 base — **verified at load 2026-08-08**: `enable_thinking=false` → 0 chars of `reasoning_content`, `true` → 649, both answered correctly |
| **defiant-fable** | ✅ | ✅ clean direct answer | Qwen3.5 finetune, embedded template gates on `enable_thinking` (no `reasoning_effort`, so cria's default `chat_template` style is correct). **Verified at load 2026-09-25** through the systemd unit, MTP on: `false` → 0 chars, `true` → 659, both correct |

### Retired launch rows

Binary table:

| Model | Fork | Why |
|---|---|---|
| defiant-fable | `~/src/llama.cpp-ornith15/build-cuda/bin/` (shared with ornith15) | Same failure, same fix: the stock build (upstream 2026-04-21 plus local CCCL patches) rejects the Qwen3.5 MTP block with `missing tensor 'blk.32.ssm_conv1d.weight'`. **Any qwen35 GGUF with `nextn_predict_layers=1` needs this build or a newer one** — check the header before assuming the stock build will do |
| qwen38 | `~/src/llama.cpp-qwen38/build-cuda/bin/` | upstream b10497 (9731ad3f2). NOT a fork — the stock tree is simply too old (b9893, Apr 22) and lacks the NextN/MTP layer handling. Built for `CMAKE_CUDA_ARCHITECTURES=61;86` so it drives the Pascal 1080 as well as the 3080; NCCL vendored at `vendor-nccl/`. ⚠ Rebuilds MUST run with `LD_LIBRARY_PATH` including `cuda-12.8-local/lib64`, or the executable link fails resolving `libcudart.so.12` |

Source table:

| Model | Source | Template |
|---|---|---|
| ternary-bonsai | `-m …/Ternary-Bonsai-27B/Ternary-Bonsai-27B-Q2_0.gguf` **(PrismML fork binary + lib_dir)** | *(embedded ChatML)* |
| gemma4 | `-m …/gemma4-v2-Q4_K_M.gguf` | `gemma-toggle.jinja` |
| qwopus | `-hf Jackrong/Qwopus3.5-9B-v3-GGUF:Q6_K` | `qwopus-toggle.jinja` |
| qwythos | `-m …/Qwythos-9B-v2-Q6_K.gguf` | *(embedded)* |
| qwen3.5 | `-m …/Qwen3.5-9B-Q6_K.gguf` | *(embedded)* |
| defiant-fable | `-m …/Defiant-Fable-9B/Qwen3.5-9B-The-Defiant-Fable-Uncnr-Heretic-NEO-MAX-MTP-Q5_K_S.gguf` **(ornith15 binary + lib_dir; `--spec-type draft-mtp --spec-draft-n-max 2`)** | *(embedded Qwen3.5 w/ `enable_thinking`)* |
| qwen38 | `-m …/Qwen3.8-27B/Qwen3.8-27B-UD-Q4_K_S.gguf` **(b10497 binary + lib_dir; `--device CUDA0,CUDA1 -sm layer`)** | *(embedded ChatML w/ `enable_thinking`)* |

### r1-llama and `collapse_system_prompt`

- **r1-llama** — the case that prompted the knob, but currently **OFF**. The template captures the message and emits it as `{{bos_token}}{{ns.system_prompt}}` — bare, after BOS, before the first `<｜User｜>` marker. The text reaches the model but lands outside the conversation structure it was trained on, and cria's system prompts run to thousands of characters. Its loop also keeps only the LAST system message, so a second one is discarded silently; the fold joins them in order instead.

  **Why it is off anyway (researched 2026-08-08).** The card says no system prompt, but real-world reports are split. One of the model's own developers measured a system prompt at temp 0.7 as *"close to the 'no system prompt'"* result, and another user reports the QwQ system prompt working fine; against that, one credible report of the model *"hung up repeatedly second guessing itself in a loop"* inside the recommended temperature range, and cline filed a real degradation for exactly this. DeepSeek's own issue asking the question was closed as stale with no maintainer answer. So: a named failure mode to watch for, not a settled fact. cria also never sends more than one system message — measured, 527 of 527 captured bodies across six sessions — so the multi-message discard is hypothetical here. Turning the fold on for the first run would confound the question this model is on the ladder to answer. Flip it and re-run if the loop symptom appears.

  Sources: HF discussions on the Qwen-32B and Qwen-7B distills, DeepSeek-R1 issue #33, cline #5477.

### VRAM accounting on WSL (retired `qwen38`; full write-up below)

The WSL guest this was measured in is the old machine setup; the `-fitt` lesson (measure the allocatable ceiling, do not trust `nvidia-smi`/`cudaMemGetInfo` for sizing) is what survives. The `qwen38` fit command that used to close the quick-reference block was:

```bash
# WHERE THE LAYERS ACTUALLY WENT (the default log hides this — needs -lv 5).
# Stop the unit first; this boots a second instance. Only the LAST block is the real fit.
systemctl stop llama-qwen38 && llama-fleet qwen38 -lv 5 2>&1 | tee /var/tmp/fit.log | grep -m1 'listening on'
awk '/layer +0 assigned/{d=""} /assigned to device/{split($0,a,"device ");split(a[2],b,",");c[b[1]]++} END{for(k in c)print k,c[k]}' /var/tmp/fit.log
```

#### VRAM accounting on WSL — the hidden CPU offload (found and cleared 2026-08-19)

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
