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
| **fabliq-reasoning** | Q6_K | **greedy** `temp 0` + `repeat_penalty 1.05` | LLM-OS-Models (`do_sample=False`) | trained @ **8K ctx** — beyond ~8K unverified; no temp/penalty ⇒ looping |
| **ternary-bonsai** (27B) | Q2_0 (custom **Q2_0_g128** ternary) | `temp 0.6, top_p 0.95, top_k 20, repeat_penalty 1.1` *(Qwen3-family defaults)* | PrismML (Qwen3.6-derived) | needs the **PrismML llama.cpp fork** (§Server launch); ~8.0 GB on the 3080; `n_ctx_train` **262144** (comfortable @ 48K) |
| **mellum2** (12B A2.5B MoE) | Q4_K_M | `temp 0.6, top_p 0.95, top_k 20` | JetBrains (Thinking model) | reasoning-OFF clean (see §Reasoning) |
| **gemma4** (12B) | Q4_K_M | `temp 1.0, top_p 0.95, top_k 64, repeat_penalty 1.1` (coding: `temp 0`) | yuxinlu1 card | needs a rep-penalty or it leaks `<|tool_call>`/`<|channel>` tokens |
| **ornith** (9B) | Q6_K | `temp 1.0, top_p 0.95` (agentic: `temp 0.6`) | deepreinforce evals | reasoning model; `--reasoning-format deepseek` |
| **qwythos** (9B) | Q6_K | `temp 0.6, top_p 0.95, top_k 20` | empero-ai (Qwen3.5 thinking) | **V2 swapped in 2026-07-12** (`/home/jesse/models/Qwythos-9B-v2-Q6_K.gguf`, alias `qwythos_9b_v2_q6`); V2 sampling + reasoning-toggle UNVERIFIED — check on first launch |
| **qwopus** (9B, Qwen3.5) | Q6_K | `temp 0.6, top_p 0.95, top_k 20` *(inferred — Qwen3.5)* | ⚠ not stated on card | verify before trusting |

> ⚠ **`qwopus` is unverified** — the values are inferred. Confirm from the model card or
> empirically before treating them as recommended.

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
