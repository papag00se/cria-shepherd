# Recommended settings per model

> **Copied from the `codex-local` research vehicle, which remains the source of
> truth.** Re-sync when settings change there. Launcher paths/systemd units are
> specific to the reference rig; the per-model sampling + reasoning-control
> mechanisms are what port. Spec index: [../../codex-local/docs/spec/index.md](../../codex-local/docs/spec/index.md).

Living reference for the 4 models under test on `127.0.0.1:18084`. Companion to
[local-model-services.md](../../codex-local/docs/spec/local-model-services.md) (how to launch/switch them). Three layers, in
**precedence order** (later overrides earlier for a given request):

1. **Server-side** — llama-server launcher flags (`~/bin/llama-<model>-*-server`).
   The model's baseline: quant, context, KV, GPU, and *default* sampling.
2. **Client config** — `.codex-multi/config.toml` `[models.<role>]`. Sampling here
   is sent **per request and overrides the launcher's `--temp/--top-p/--top-k`**.
   Keyed by ROLE (classifier / light_coder / light_reasoner / compactor), not by
   model — the same loaded model serves every role with different sampling.
3. **Per-request** — what the harness puts on the wire. Mostly the role's config
   values; a few things (reasoning toggles) do NOT work here and must be set
   server-side. See "Reasoning control".

> **Quant caveat:** the three 9Bs are **Q6_K**; Gemma is **Q4_K_M** (4-bit). Some of
> Gemma's weaker eval showing may be the lower quant, not the model.

---

## 1. Server-side (launcher flags)

Shared by all three 9Bs: `--device CUDA0 -ngl auto -sm none -mg 0 -ctk q8_0 -ctv q8_0
-fa on --jinja --host 127.0.0.1 --port 18084`. Differences that matter:

| Model | Quant | `-c` (ctx) | temp | top-p | top-k | repeat-pen | reasoning flags | GPU |
|-------|-------|-----------|------|-------|-------|-----------|-----------------|-----|
| **Qwopus 3.5 9B** | Q6_K | 32768¹ | 1.0 | 0.95 | 20 | — | `--reasoning auto` | 3080 only |
| **Ornith 1.0 9B** | Q6_K | 49602 | **0.6** | 0.95 | 20 | — | `--reasoning auto --reasoning-format deepseek` | 3080 only |
| **Qwythos 9B** | Q6_K | 49664 | 1.0² | 0.95 | 20 | — | `--reasoning auto` | 3080 only |
| **Gemma 4 12B** | Q4_K_M | 32768 | 1.0 | 0.95 | **64** | **1.1** | `--reasoning auto` | **3080+1080 split** (`-sm layer -ts 10,8`) |

¹ Qwopus known-good uses 32768; a 9B Q6 fits **~49664** on the 10 GB 3080 (as Ornith/
Qwythos show). Raise `-c` to 49664 if you want fewer compactions. The eval ran Qwopus at 49664.
² Qwythos temp is **inherited from Qwopus (1.0)**. Qwythos is Qwen3.5-based; Qwen3
reasoning models often recommend **temp ~0.6, top-p 0.95, top-k 20, min-p 0**. Worth
A/B-ing — 1.0 may be hot for a reasoner. *(unverified against the model card)*

Notes:
- **Launcher sampling is a FALLBACK** for the coding path — the config's `light_coder`
  temp (0.1) overrides it per request (see below). It still applies to any request that
  doesn't set sampling, and defines the model's baseline for ad-hoc `curl` tests.
- **Gemma port**: launcher defaults to 18085; the systemd unit pins `GEMMA4_AGENTIC_PORT=18084`.
- **KV cache** is q8_0 for all (halves KV VRAM vs f16, negligible quality cost).

---

## 2. Client config — `.codex-multi/config.toml` (per ROLE, overrides launcher sampling)

These are what the coder/reasoner **actually run at** (sent on every request). The same
loaded model serves all roles; only the sampling + role differ. All roles point at
`endpoint = "http://127.0.0.1:18084/v1"`, `provider = "openai-compat"`, `model =
"ornith_1_9b_q6"` (a label — llama-server serves whatever GGUF is loaded, ignores it).

| Role | temp | top_p | top_k | repeat_penalty | max_tokens | reasoning | timeout |
|------|------|-------|-------|----------------|-----------|-----------|---------|
| `classifier` | 0.0 | 1.0 | 1 | — | — | off | 30s |
| **`light_coder`** (main coding) | **0.1** | 0.95 | 20 | 1.1 | 4096 | auto | 7200s |
| `light_reasoner` | 0.4 | 0.95 | 40 | — | 4096 | auto | 7200s |
| `compactor` | 0.0 | 1.0 | 1 | — | — | auto | 7200s |

- **Coding runs near-greedy (temp 0.1)** for determinism — this OVERRIDES the launcher's
  higher temp. If you want to change how the coder samples, edit `light_coder` here, not
  the launcher.
- **Classifier/compactor are fully greedy (temp 0.0, top_k 1)** — structured snap outputs.
- `model_context_window` is **not set** — the harness auto-detects real `n_ctx` from
  `/props` at startup and drives native compaction off it. Don't hardcode it.
- `[routing] local_only = true` blocks the cloud tiers so everything routes to the local
  roles.

---

## 3. Per-request settings — and what does NOT work

The harness sends the role's `temperature / top_p / top_k / repeat_penalty / max_tokens`
per request (overriding the launcher). **Reasoning is the exception** — request-level
toggles do NOT reliably control it and must be set server-side:

- `reasoning_budget`, `enable_thinking`, `/no_think` **in the request body → ignored.**
  The harness doesn't send `chat_template_kwargs`, and Qwopus's template hardwires
  `<think>` regardless. Verified in the eval.
- The config's `reasoning = "auto"/"off"` maps to a `think` flag on the request, but for
  these local (openai-compat) models it does **not** turn thinking off — reasoning stayed
  ON in the eval with `reasoning = "auto"`. Treat the config `reasoning` field as intent
  only for local models; it's authoritative for cloud tiers.

---

## Reasoning control (ON/OFF) — SERVER-SIDE, verify with a probe

Toggle reasoning at launch, then verify: POST to `/v1/chat/completions` (`stream:false`)
and check `reasoning_content` length (0 = off, >0 = on).

| Model | OFF mechanism | Notes |
|-------|---------------|-------|
| **Ornith / Gemma / Qwythos** | **`--reasoning-budget 0`** launch flag | Their templates respect `enable_thinking`; the flag sets it false. Clean, no edit. |
| **Qwopus** | **chat-template swap** (`--chat-template-file`) | Hardwires `<think>` and ignores the flag. Use an empty-closed `<think>\n\n</think>\n\n` gen-prompt block. Template at `~/shepherd-eval/templates/qwopus-nothink.jinja`. |

ON = default launcher (no flag). Each model's think token differs (Qwen `<think>`, Ornith
deepseek, Gemma channel-based `<|channel>thought`).

**Eval verdict on reasoning (F17):** it's base-model-dependent. Strong base (Qwythos)
tolerates OFF (faster, decisive); weaker bases (Ornith, Gemma) collapse OFF (loop, drop
constraints). Qwopus does better OFF but that's a *fabricated* off-mode (no native
off-branch). **Default to ON** unless you've verified a given model is fine OFF.

---

## Quick reference — verify what's actually live
```bash
# which model + context
curl -s 127.0.0.1:18084/props | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["model_path"].split("/")[-1], "n_ctx=", d.get("default_generation_settings",{}).get("n_ctx"))'
# reasoning on/off
curl -s 127.0.0.1:18084/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"local","messages":[{"role":"user","content":"2+2? think first"}],"stream":false,"max_tokens":200}' \
  | python3 -c 'import sys,json;print("reasoning_len:", len(json.load(sys.stdin)["choices"][0]["message"].get("reasoning_content") or ""))'
```
