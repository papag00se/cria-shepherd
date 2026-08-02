# Recommended settings per model

**cria's source of truth** for the local model fleet on `127.0.0.1:18084`. (Ported from
codex-local and now maintained here.) Keep it updated when settings change or a model is
added/verified.

Settings live in **two files**, split by whether they need a model reload:

| Layer | File | Holds | Changing it needs |
|---|---|---|---|
| **Server launch** | `~/.config/llama-fleet/models.toml` (read by `llama-fleet`) | model source, quant, **ctx**, KV, GPU layers, chat template | a **model-server restart** (`systemctl restart llama-<model>`) — rare |
| **Client / per-role** | `~/.cria/cria.toml` `[roles.<role>]` | **sampling** (temperature/top_p/top_k/repeat_penalty/min_p/max_tokens) + **reasoning** | a **cria restart** (seconds) — no model reload |

cria attaches the **role's** sampling + reasoning to **every request** it makes for that
role (`temperature`, `repeat_penalty`, … and reasoning as `chat_template_kwargs.enable_thinking`).
The launcher's sampling is only a fallback — so tune in `cria.toml`, not `models.toml`.

> **One 3080, one model at a time** (`-np 1`). Swap with `systemctl` (the `llama-fleet`
> launcher reads `models.toml`); see §Server launch.

---

## Per-model recommended settings

Sampling is **client-side** (`cria.toml`); set the role you're driving to these. Server
launch (`models.toml`) is uniform except model + template (see §Server launch).

| Model | Quant | Recommended sampling | Source | Notes |
|-------|-------|----------------------|--------|-------|
| **fabliq-reasoning** (8B-A1B **MoE**) | Q6_K | **greedy** `temp 0` + `repeat_penalty 1.05` | LLM-OS-Models (`do_sample=False`) | arch `lfm2moe`, **32 experts / 4 active** (LFM2.5-8B-A1B base) — read from the GGUF header, not the card; trained @ **8K ctx** — beyond ~8K unverified; no temp/penalty ⇒ looping |
| **ternary-bonsai** (27B) | Q2_0 (custom **Q2_0_g128** ternary) | **per-role, CANONICAL (m15-verified — see block below)**: coder `0.2/0.95/20`, reasoner `0.6/0.90/40`, classifier+compactor `temp 0`; `repeat_penalty 1.1` all | PrismML (Qwen3.6-derived) | needs Q2_0_g128 kernels (§Server launch — TurboQuant merged fork); ~8.0 GB on the 3080; `n_ctx_train` **262144** (comfortable @ 48K) |
| **mellum2** (12B A2.5B MoE) | Q4_K_M | `temp 0.6, top_p 0.95, top_k 20` | JetBrains (Thinking model) | reasoning-OFF clean (see §Reasoning) |
| **gemma4** (12B) | Q4_K_M | `temp 1.0, top_p 0.95, top_k 64, repeat_penalty 1.1` (coding: `temp 0`) | yuxinlu1 card | needs a rep-penalty or it leaks `<|tool_call>`/`<|channel>` tokens |
| **ornith** (9B) | Q6_K | `temp 1.0, top_p 0.95` (agentic: `temp 0.6`) | deepreinforce evals | reasoning model; `--reasoning-format deepseek` |
| **qwythos** (9B) | Q6_K | `temp 0.6, top_p 0.95, top_k 20` | empero-ai (Qwen3.5 thinking) | **V2 swapped in 2026-07-12** (`/home/jesse/models/Qwythos-9B-v2-Q6_K.gguf`, alias `qwythos_9b_v2_q6`); V2 sampling + reasoning-toggle UNVERIFIED — check on first launch |
| **qwopus** (9B, Qwen3.5) | Q6_K | `temp 0.6, top_p 0.95, top_k 20` *(inferred — Qwen3.5)* | ⚠ not stated on card | verify before trusting |
| **nemotron-elastic** (12B-A2B) | Q4_K_M | `temp 0.6, top_p 0.95` (tool-calling; general chat `1.0/1.0`) | NVIDIA (Nemotron 3 guide) | `nemotron_h_moe` mamba-hybrid MoE (128 experts/6 active, elastic-pruned from Nano-30B-A3B); ctx_train **1M**; 9.64 GB file auto-fits the 3080; **service-verified 86 t/s** on stock b9893. No plain Q4_0 exists anywhere — Q4_K_M substituted. Reasoning = automatic `<think>` in template, toggle UNVERIFIED |
| **zaya1** (8.4B-A760M MoE) | Q6_K | `temp 0.6, top_p 0.95, top_k off` (agent/code; general `1.0`) — Zyphra | Zyphra card | ⚠ **EXPERIMENTAL — runs on a local DRAFT-PR build** (llama.cpp PR #23112 branch, built from source 2026-07-29 at `~/src/llama.cpp-zaya`; no release supports arch `zaya`). Service-verified: coherent output, prefill 377 / decode **59 t/s** direct, 46 t/s served; ctx_train 131K. Re-point at a release build when the PR merges |

### Candidate — NOT in the fleet yet: **Moonlight-16B-A3B-Instruct** (added 2026-08-01)

Requested by the operator, **conditional on TurboQuant working with it** — without a shrunk KV
cache it does not fit, and that condition is the whole reason it is not already queued.

| | |
|---|---|
| GGUF | [`mmnga/Moonlight-16B-A3B-Instruct-gguf`](https://huggingface.co/mmnga/Moonlight-16B-A3B-Instruct-gguf), **IQ4_XS = 8.74 GB** |
| Base | [`moonshotai/Moonlight-16B-A3B-Instruct`](https://huggingface.co/moonshotai/Moonlight-16B-A3B-Instruct) — 16B total / **3B active** MoE, Muon-trained on 5.7T tokens |
| Architecture | **DeepSeek-V3 shape** (llama.cpp arch `deepseek2`) — Moonshot's own card says so |
| Context | **8K native.** The fleet default is 48K; this model must override `ctx` down or it is being run past its training |
| Reasoning | **None.** No thinking mode on the card ⇒ all roles `reasoning = "off"` |

**The blocker, in numbers.** The 3080 has **10,240 MiB**. IQ4_XS weights are **8,740 MiB**, leaving
~1.4 GB for KV cache *and* compute buffers. At the fleet's 48K that is impossible; even at its native
8K it is marginal. TurboQuant `tbq3` KV — already the live `cache_type_k/v` for ternary-bonsai, and
measured at ~3× smaller than q8 — is what would make the difference.

**The open question, and it is a real one.** The TurboQuant build is a fork
(`/home/jesse/src/llama.cpp-tq-prism/llama-v0.0.0/llama-server`,
jarkevithwlad/turboquant-prismml-cuda v1.0.1). `models.toml` already records that stock, prism and
turboquant binaries *reject* one arch outright. **Nobody has checked whether that fork loads
`deepseek2`.** Check that FIRST — it is a one-command answer and it decides whether the rest matters:

```bash
/home/jesse/src/llama.cpp-tq-prism/llama-v0.0.0/llama-server   -m <the IQ4_XS file> --ctx-size 8192   --cache-type-k tbq3 --cache-type-v tbq3 --n-gpu-layers auto --no-warmup
```

**Sampling: no official values exist.** Neither Moonshot's card nor the GGUF repo states a
temperature or top_p, and a search turned up none. Do **not** invent numbers into this table — that
is the mistake this file exists to prevent, and 26 consecutive runs were once sent the wrong model's
sampling. Start from the DeepSeek-V3-family convention and *measure*, recording what was verified:

| role | starting point | why |
|---|---|---|
| coder | `temp 0.2–0.3, top_p 0.95` | DeepSeek-family coding convention; tighten if it drifts |
| reasoner | `temp 0.6, top_p 0.95` | matches every other MoE in this table |
| classifier / compactor | `temp 0` | greedy, as for the whole fleet |
| all roles | `reasoning = "off"` | the model has no thinking mode to enable |

**Second known issue:** the GGUF repo states *"chat-template is custom therefore removed"*, and the
repo calls itself experimental. A missing template means `--jinja` has nothing to apply — a template
must be supplied at launch or the wire format will be wrong. Settle this before a ladder run, not
during one.

> ⚠ **`qwopus` is unverified** — the values are inferred. Confirm from the model card or
> empirically before treating them as recommended.

> **Dense vs MoE, read from the GGUF headers (2026-08-01)** — `general.architecture` plus
> `<arch>.expert_count` / `expert_used_count`, never a card or a name. The fleet is **five dense,
> four MoE**:
>
> | dense | | MoE | experts (active) |
> |---|---|---|---|
> | ternary-bonsai 27B | `qwen35` | mellum2 12B/A2.5B | `mellum` 64 (8) |
> | gemma4 12B | `gemma4` | nemotron-elastic 12B/A2B | `nemotron_h_moe` 128 (6) |
> | qwythos 9B | `qwen35` | zaya1 8.4B/A760M | `zaya` 16 (1) |
> | qwopus 9B | `qwen35` | fabliq 8B/A1B | `lfm2moe` 32 (4) |
> | ornith 9B | `qwen35` | | |
>
> **fabliq is an MoE**, which this table implied it was not by labelling the other three and
> leaving it bare. `lfm25` has a systemd unit but **no entry in `models.toml`**, so it cannot
> launch — fix that before putting it in any run order.

> **ternary-bonsai speculative decoding (verified 2026-07-28):** the Q2_0_g128 GGUF does **NOT**
> contain MTP layers (`--spec-type draft-mtp` is a FATAL load error — the service crash-loops, no
> graceful fallback). `--spec-type ngram-cache` works and **doubled decode: 8.3 → 17.1 tok/s**
> (48% draft acceptance on code; n_draft=8). Set per-model in llama-fleet models.toml extra_flags.
> KV: `-ctk q8_0 -ctv q4_0` (asymmetric; K drives logits, V tolerates 4-bit).

> **draft-dspark — measured dead end on this box (2026-07-28):** the companion 3.6B drafter
> (`Ternary-Bonsai-27B-dspark-Q4_1.gguf`, 6 blocks, drafts 4-token blocks conditioned on target
> hidden-state taps at layers 1/16/31/46/61) *loads and runs* on the spare GTX 1080
> (`cuda_device` widened to both GPUs, `--spec-draft-device CUDA1 --spec-draft-ngl all
> --spec-draft-n-max 4` — n-max MUST equal the drafter's `block_size=4`). Three structural costs
> sank it: (1) its staging forward covers the **full target context** (~216 KiB compute buffer per
> position on the draft device → 49K ctx needs 10.4 GiB, so ctx had to drop to 24K just to fit);
> (2) target-side tap capture cut **prefill ~3× (360 → ~112 tok/s)** and **disables prompt-cache
> reuse** — every agentic call would re-prefill its whole history; (3) each draft round is a
> full-context drafter forward on Pascal → **decode 4.2–4.8 tok/s**, *below the 8.3 no-spec
> baseline* and falling with depth. Acceptance itself was good (62%, ~3.5 tok/target-forward ≈
> 29 tok/s if drafting were free) — the drafter wants a fast co-resident device, not a spare
> Pascal. Re-try only with a second fast GPU; until then ngram-cache stays.

> **draft models are off the table for this target entirely (measured 2026-07-28):** a
> vocab-exact Qwen3.5-0.8B Q6 drafter co-resident on the 3080 (same `qwen35` family, 248320
> vocab, fits in the spare ~2 GB at 49K — no dspark-style staging buffer) still measured
> **2.4 tok/s vs ngram's 7.1** on an identical deep-context (6.9K) benchmark, despite 51%
> acceptance and drafting costing only 2.8s of the 105s total. Root cause: the 27B is a
> **hybrid-SSM** (`qwen35` arch, recurrent layers) — its state cannot rewind, so every
> speculative round pays ~2s of checkpoint save/restore machinery (`-cms 8` changed nothing:
> it's the state copies, not re-prefill distance). Only opportunistic near-free drafting
> (ngram-cache) survives on a hybrid target; per-round draft speculation loses on ANY GPU.
> The 0.8B GGUF stays at `/home/jesse/models/Qwen3.5-0.8B/` for a future attention-only target.

> **TurboQuant KV = THE win — live since 2026-07-28.** The "no fork has both" assumption died on
> a search: **`jarkevithwlad/turboquant-prismml-cuda` v1.0.1** merges PrismML's Q2_0_g128 kernels
> with amesianx TurboQuant; the sm86 (RTX3090Ti) Linux release runs on the 3080 (needs
> `libnccl.so.2` — copied into the build dir from the `nvidia-nccl-cu12` pip wheel; KV type names
> are `tbq3/tbq4/tbqp3/tbqp4`, NOT the atomic fork's `turbo2/3/4`). Same-build A/B, ternary-27B
> on the 3080, `-fa on`: **tg128@d8192 11.3 → 48.7 t/s (4.3×)**, pp2048 168 → 845, pp@8K 22 → 189,
> shallow tg ~par (51.9 → 49.3). Decode becomes ~depth-independent.
> **CORRECTED MECHANISM (operator-prompted, f16 control 2026-07-28): the wall was the QUANTIZED-KV
> CODE PATH, not KV bandwidth.** Same build, tg64@d8192: q8_0/q4_0 = 11.3, tbq3 = 48.7,
> **f16 = 61.1** — plain f16 beats turbo. TurboQuant's real win is the COMBINATION: its cache
> code avoids the pathological quantized path AND fits 49K ctx (~5.6 GB f16 KV + 6.7 GB weights
> exceeds the 3080; f16 caps ctx at ~20K). Untested knob: tbq4 (more quality margin, still fits). Live serving verified 53 t/s with correct output; no `--spec-type`
> (build lacks the prism spec framework; pointless at 50 t/s anyway). Rollback = prism b9596 +
> ngram (in models.toml comments). **Quality at real agentic depth (20K+, long sessions) not yet
> proven — the next goal runs referee it.** *(Update, same day: run m15 completed the goal fully
> unaided on this config with zero incoherence — first quality referee PASSED.)* Earlier
> fun-sized data point: the AtomicBot fork (`~/src/llama.cpp-turboquant/`, types `turbo2/3/4`)
> also works, even on the Pascal 1080 (Qwythos-9B: +5% at 8K depth, −14% prefill) — but it lacks
> the prism kernels.

> **Fleet-wide TurboQuant sweep (2026-07-28): NO win for any other model — q8_0 stays the fleet
> default.** All 7 fleet models benched on the 3080 (AtomicBot build, q8_0 vs turbo3, shallow +
> 8K depth, r=3, zero errors): tg@8K deltas par to −13% (fabliq 277→241, lfm25 277→249,
> mellum2/ornith par, qwythos/gemma4 noisy-worse, qwopus within its control's noise band). The
> ternary-27B is the ONLY winner because its 2-bit weights make KV reads the dominant decode
> term at depth — the 8–12B fleet models already decode 65–277 t/s deep (weight-bound, several
> MoE/hybrid with small KV), so 3-bit KV just adds quantization work. TurboQuant = ternary-only.
> **32K-depth follow-up (operator: "these weren't deep runs"): the loss GROWS with depth** —
> tg64@d32768 q8_0→turbo3: fabliq 239→177 (−26%), lfm25 230→163, ornith 68→49, qwopus 67→50,
> gemma4 60→44, qwythos 67→64. The hybrids' KV stays small at depth, so turbo3's per-read
> dequant overhead scales while the savings never arrive. ONE inconclusive cell: mellum2's q8_0
> control went unstable at 32K (93±58) while turbo3 held 140±0.6 — repeat before trusting either
> number if mellum2 ever goes live again.

> **Context-vs-speed tradeoff, qwythos (measured 2026-07-28; tg64, tok/s):**
>
> | depth | 8K | 32K | 65K | 131K | 196K | max fit |
> |---|---|---|---|---|---|---|
> | q8_0   | 80 | 68 | 51 | 38 | — | **~143K** |
> | turbo3 | 76 | 59 | 49 | 33 | 26 | **~375K** |
>
> Per-token KV (from the GGUF header: 8 attn layers × 4 kv-heads × 256+256): q8_0 ≈ 17 KiB,
> turbo3 ≈ 6.5 KiB. Rule: **q8_0 up to ~131K; turbo3 only past q8_0's ~143K ceiling** (3–12%
> slower at every shared depth — its gift is reach, not speed). qwythos trains to 1M so VRAM is
> the only limit; note the fleet's 49K default is conservative for this model — 131K on plain
> q8_0 fits TODAY. **ornith and qwopus are KV-identical** (same 32 blocks / every-4th attention /
> 4 heads / 256+256, verified from headers) so these numbers transfer — but they train to 262K,
> which becomes their useful cap. WSL caveat (measured, correcting an earlier bogus-probe claim):
> a beyond-VRAM ctx neither loads nor fails fast — the load HANGS (>5 min timeout at 262K q8_0
> on qwythos; WSL UVM). Derive ceilings by arithmetic (per-token KV × ctx + weights vs 10 GB),
> never by load-probing.
>
> **gemma4 (measured 2026-07-28; tg64, tok/s):** q8_0 = 62 / 57 / 49 / 40 at 8K / 32K / 65K /
> 131K; turbo3 = 58 / 52 / 46 / 36 — **q8_0 wins every depth (~7–9%), and gemma4's SWA
> (1024-token window on most of its 48 layers) keeps KV small at any context, so turbo has no
> reach advantage either. TurboQuant: nothing to offer gemma4.** 131K verified on q8_0; the 262K
> training cap likely fits too.

> **ternary-bonsai canonical cria.toml roles (operator-saved 2026-07-28, the exact settings that
> produced run m15 — the first fully unaided goal success):**
>
> ```toml
> [roles.classifier]
> backend = "local"
> reasoning = "on"
> temperature = 0.0
> repeat_penalty = 1.1
>
> [roles.reasoner]                      # the planner + the step/task critic
> backend = "local"
> reasoning = "on"
> temperature = 0.6
> top_p = 0.90
> top_k = 40
> repeat_penalty = 1.1
>
> [roles.coder]
> backend = "local"
> reasoning = "on"
> temperature = 0.2
> top_p = 0.95
> top_k = 20
> repeat_penalty = 1.1
> output_reserve = 16384                # input-side reserve; keeps a big write_file uncut
>
> [roles.compactor]
> backend = "local"
> reasoning = "off"
> temperature = 0.0
> repeat_penalty = 1.1
> ```

> **fabliq is the *Agent-Reasoning* fine-tune of its base MoE family** — the base instruct model
> was tried live 2026-07-21 and dropped (not agentic: in the harness it monologues the plan in
> `content` and never emits a tool call), which is why the fine-tune is the live model.

---

## Reasoning ON / OFF — the mechanism and per-model reality (verified 2026-07-08)

**How it works.** Reasoning is toggled entirely by the **server-side chat template**, driven by
one per-request boolean. cria (like codex-local's `ollama.rs`) sends **only**
`chat_template_kwargs.enable_thinking = <bool>` on the wire — nothing else. The magic is in each
model's `*-toggle.jinja`: when `enable_thinking=false` it **prefills an empty, closed think block**
into the generation prompt — `<think>\n\n</think>\n\n` (Qwen family) or an empty `<|channel>thought`
(Gemma). It is a **prefill, not a directive** (grepping all six templates for "do not think / answer
directly" returns zero hits). The empty block is a *trained control signal*: "reasoning already done,
answer now."

**So OFF works only on models trained to honor that signal.** The toggle files prefill **byte-identical
bytes** for the models that work and the ones that don't — the divergence is the model, not the template.

| Model | ON | OFF (`enable_thinking=false`) | Why |
|-------|----|--------------------------------|-----|
| **mellum2** | ✅ | ✅ clean direct answer | trained for it (embedded template) |
| **qwopus / ornith / qwythos** | ✅ | ✅ clean direct answer | **Qwen3-derived** — honor the empty `<think></think>` control block |
| **ternary-bonsai** | ✅ | ✅ clean direct answer | **Qwen3.6-derived** — embedded ChatML honors `enable_thinking` (verified on/off at load) |
| **gemma4** | ✅ | ✅ clean direct answer | honors the empty `<|channel>thought` |
| **fabliq-reasoning** | ✅ | ⚠ deliberation leaks into `content` (~1400 chars) | **LFM2 family** — never trained on the empty-think convention; the prefill is inert |

So **5 of 7 do OFF cleanly** (mellum2, qwopus, ornith, qwythos, gemma4). On the LFM2-family model
fabliq-reasoning, `enable_thinking=false` empties `reasoning_content` but the model
still deliberates in prose in `content` — which cria's parsers can't strip (no `<think>` tags). This
is a **model limitation**, not a missing manipulation.

**The per-model "manipulation" you built** was exactly these `*-toggle.jinja` files (and, for a
whole-instance off, `.reason-off` launch scripts that bake the `-nothink` template via
`--chat-template-file`, plus `--reasoning-format deepseek` for ornith). qwopus's *stock* template
hardcoded `<think>` with no gate — which is precisely why the toggle had to be hand-built.

**What cria does on `reasoning = "off"` (SHIPPED — `LocalRole.apply` / `clean_content` in `config.py`).**
Per request cria applies THREE things so OFF works on any loaded model without per-model config:
1. `chat_template_kwargs.enable_thinking = false` — suppresses thinking on the native-off models.
2. appends a **mild no-think directive** to the system message ("Do not think out loud or narrate your
   reasoning. Respond directly.") — makes the LFM2 models answer directly instead of deliberating.
3. **strips any leaked reasoning** ahead of a `</think>` marker from the model's `content`.

**Honest result (verified end-to-end on fabliq, 2026-07-08):**
- **Native-off models** (mellum2, qwopus, ornith, qwythos, gemma4) → OFF is **clean**.
- **fabliq** → OFF *engages* (thinking block suppressed, directive applied) and is **clean on
  direct tasks** (a code one-liner came back tidy), but on **reasoning-heavy prompts they stay verbose**:
  the model explains at length with *no* `</think>` marker, so the strip can't catch it (~700–900 chars
  remained). It's **correct and never breaks cria** (parsers/`parse_steps`/`extract_json_object` still
  pull the structured output; tool-calls are untouched) — just chatty. A *harder* directive makes them
  terser but **wrong** (a reasoning-trained model loses accuracy when starved of reasoning), so the
  directive is deliberately mild.

**Guidance:**
- Flip any role `reasoning = "on"` / `"off"` in `~/.cria/cria.toml` and restart cria — it takes effect
  per request, no model reload, no per-model wiring needed.
- `cria.toml` ships every role `reasoning = "on"` (clean fleet-wide; also what coding wants).
- If a role needs **terse** OFF output, point it at a **native-off model** (mellum2 or a Qwen-derived
  one). OFF on fabliq works but stays verbose on reasoning-heavy turns — a model trait, not a bug.

---

## Server launch (`models.toml`) — uniform except model + template

All models share: `-c 49152` (48K) · `-b 2048 -ub 512` · `-np 1` · `--device CUDA0 -ngl auto
-sm none -mg 0` · `-ctk q8_0 -ctv q8_0` · `-fa on --no-host --no-mmproj --no-warmup --jinja` ·
`--reasoning auto` (the *parsing* mode — distinct from per-request `enable_thinking`) ·
`--host 127.0.0.1 --port 18084`. **Sampling is NOT set here** (cria sends it per request).

Per-model differ only by source + chat template (all templates in `~/shepherd-eval/templates/`) —
**except `ternary-bonsai`**, which also overrides `binary` + `lib_dir` to the **PrismML llama.cpp fork**
(its `libggml-cuda.so` carries the `Q2_0_g128` kernels the stock CUDA build lacks; `lib_dir` must LEAD
with the prism dir, then `cuda-12.8-local/lib64` + `/usr/lib/wsl/lib`). Fork binary:
`/home/jesse/src/llama.cpp-prism/llama-prism-b9596-9fcaed7/llama-server`.

| Model | Source | Template |
|-------|--------|----------|
| fabliq-reasoning | `-hf mradermacher/Fabliq-8B-Agent-Reasoning-i1-GGUF --hf-file …Q6_K.gguf` | `fabliq-toggle.jinja` |
| ternary-bonsai | `-m …/Ternary-Bonsai-27B/Ternary-Bonsai-27B-Q2_0.gguf` **(PrismML fork binary + lib_dir)** | *(embedded ChatML)* |
| mellum2 | `-hf yuxinlu1/Mellum2-12B-A2.5B-…-GGUF --hf-file mellum2-claude-Q4_K_M.gguf` | *(embedded)* |
| gemma4 | `-m …/gemma4-v2-Q4_K_M.gguf` | `gemma-toggle.jinja` |
| ornith | `-hf deepreinforce-ai/Ornith-1.0-9B-GGUF:Q6_K` | `ornith-toggle.jinja` |
| qwopus | `-hf Jackrong/Qwopus3.5-9B-v3-GGUF:Q6_K` | `qwopus-toggle.jinja` |
| qwythos | `-m …/Qwythos-…-Q6_K.gguf` | *(embedded)* |

- **`-ub 512` is required** — a larger prefill micro-batch overflows the 10 GB 3080.
- **All fit the single 3080** (9Bs ~7.3 GB Q6_K; the 12B MoEs ~7–8 GB).
- The `*-toggle.jinja` templates gate on `enable_thinking` so the per-request flag works. Keep
  `--reasoning-budget` at default — launching with `--reasoning-budget 0` pins the whole instance
  no-think and defeats per-request control.

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
llama-fleet fabliq-reasoning --dry-run
```
