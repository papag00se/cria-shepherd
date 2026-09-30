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
