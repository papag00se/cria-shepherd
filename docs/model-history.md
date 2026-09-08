# Model history — tried, replaced, and abandoned

The models cria's fleet has **run, evaluated, or rejected**, and why. This is the graveyard and the paper trail; [`model-settings.md`](model-settings.md) holds only the CURRENT fleet's settings. When a model leaves the active fleet, its record moves here.

**Where the live evidence lives** (never trust this prose over the ledger):
- `suite/results/results.jsonl` — the authoritative run ledger; enumerate distinct models there, do not trust a doc's roster.
- `suite/historical_ladder.json` — FROZEN inference-usefulness rows for replaced models that still render in the engagement-ladder report (`gemma4`, `qwen35`, `ternary-bonsai`, `nemotron-elastic`).

---

## Retired / replaced / paused

- **mellum2** (JetBrains Mellum2 12B-A2.5B MoE) — retired 2026-09-08. Ran 48 times (old `ada-*`/`handles-*` tasks, 2026-07-29..08-09), **never the current 6-task battery, never on the inference ladder**; no usefulness scores survive (it predates inference judging and its workspaces were cleaned). Behaviourally it completed 27/48 runs (56% `exited`) — maple-tier, better than zaya/fabliq, but documented as a struggling MoE that was "out of scope" (`docs/goals/compaction-live-loop.md`) and never promoted. Removed from `sampling.py` and `run.py` SERVICES; the launch entry (`-hf yuxinlu1/Mellum2-12B-A2.5B-…-GGUF --hf-file mellum2-claude-Q4_K_M.gguf`, embedded template) is kept below for reproducibility.
- **nemotron-elastic** (NVIDIA, 12B-A2B mamba-hybrid) — paused 2026-09-05. 184 result rows; its recovered inference ladder is FROZEN in `historical_ladder.json` so it stays visible in the report. Its service and reproducible launch entry remain installed. Historical runs and incident references retain the old model name. Weakest of the laddered models; extensively walked in `docs/audits/battery-pair-walk.md`.
- **GigaChat 3.1** (10B-A1.8B, ai-sage) — TRIALED 2026-09-05 as a fleet candidate and EXCLUDED after the L5 battery. It scored ~0% inferred usefulness across all six tasks (2/1/0/0/0/0) and its tokenizer/template leaked Cyrillic into generated code — e.g. it wrote the Rust manifest name as `Cargo.томл` (Cyrillic т-о-м-л instead of `toml`), which no harness-side fix can correct. Not in the suite or on the ladder.
- **ornith 1.0** (9B) — the version tested before 2026-09-05 (`deepreinforce-ai/Ornith-1.0-9B-GGUF:Q6_K`). Replaced by `ornith15`; historical result rows remain `ornith` so releases are never conflated.
- **fabliq-reasoning** (8B) — `mradermacher/Fabliq-8B-Agent-Reasoning-i1-GGUF`, `fabliq-toggle.jinja`. Retired from the suite; its unit is `disabled` and `inactive`, and it is in no sampling or SERVICES table. 13 result rows, 0 completed (9/13 stalled at the 15-min milestone). The entry stays so the launch config is reproducible. It auto-started on :18084 once after a WSL restart and had to be stopped by hand — if you see an unexpected model serving, check this one.
- **zaya1** (8B) — draft-PR arch, launchable but never laddered (7 result rows, 6/7 stalled at 15 min). Needs the `zaya` draft-PR build (`~/src/llama.cpp-zaya/build/bin/`) — the arch exists in no llama.cpp release.
- **gemma4-finetune** (yuxinlu1, 12B) — replaced by stock `gemma4` on 2026-08-05 after repeated runs showed stock completing substantially more of the same lane. 46 result rows; kept for its history.

---

## Considered and REJECTED for the Llama-family slot (2026-08-08, closed 2026-08-09)

cria's coder path is ~100% tool calls and its assists assume a thinking channel, so a Llama-family model needs BOTH. **The slot is CLOSED — all three candidates failed, the third on grounds no model choice can fix.** Three were tried:

- **Dolphin 3.0 (Llama-3.1-8B)** — trained for function calling (`hermes-function-calling-v1`) but instruct-only, no thinking channel. Would have changed the family AND removed reasoning in one step, confounding the question the slot exists to answer. (Evaluated on paper; no run rows.)
- **DeepSeek-R1-Distill-Llama-8B** (`r1-llama`) — reasoning, but tool use was never a training objective. MEASURED on this box: **0/4, 30 calls, ZERO assistant turns ever entered the conversation.** It emitted an invented `<tool name="web_fetch" call="begin">` in prose; llama.cpp parsed no tool call, the harness recorded no action, and every turn restarted from the task. Pinning llama.cpp's `llama-cpp-deepseek-r1.jinja` (the embedded template has NO tools branch at all) was necessary and not sufficient — the template can express a call the model cannot produce. DeepSeek's own distill discussion: tool use "is not one of the main goals for the model"; Fireworks lists R1 tool calling as "Not supported"; R1-0528 added it, but its 8B distill is Qwen3-based and would have been our fifth Qwen.
- **NVIDIA Llama-3.1-Nemotron-Nano-8B-v1** (`nemotron-nano`) — the only 8B Llama derivative with BOTH halves (post trained for reasoning AND tool calling; BFCL v2 Live 63.9/63.6). cria's side worked: the alternation merge, the `detailed thinking on` system directive and real `tool_calls` arrays all reached the wire. **RETIRED 2026-08-09 anyway, because the RUNTIME cannot serve it.** When the model answers without calling a tool it emits `<TOOLCALL>[]`, and llama.cpp 500s with `Unexpected empty grammar stack after accepting piece: >[] (71510)` — 56 crashes in one 8-minute run, ~34 of 81 calls dead. Two combining root causes: the single token `>[]` both completes the auto-derived `<TOOLCALL>` trigger and carries text past it, and llama.cpp's generated tool-call grammar has no production for an empty array. MEASURED: 3/3 reproduction on "answer without a tool"; a build **1,275 commits newer crashes identically**; `--jinja` off does not help; `detailed thinking off` does not help. Upstream #14413 open since 2025-06-27, fix PR #19503 rejected as "too invasive", no native `<TOOLCALL>` parser (PR #15083 closed unmerged), no flag to disable the lazy tool-call grammar. The public runs this family's tool calling on **vLLM with an NVIDIA out-of-tree plugin**, never on llama.cpp — and the 8B-v1 repo does not even ship that plugin. Re-open only behind a vLLM backend or a merged llama.cpp fix. (This is also why cria carries `merge_consecutive_turns` — see `model-settings.md`.)

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

## Reproducible launch entries for retired models

Kept so a retired model can be brought back exactly. These are NOT on the ladder and have no sampling/SERVICES entry.

| Model | Source | Template |
|-------|--------|----------|
| mellum2 | `-hf yuxinlu1/Mellum2-12B-A2.5B-…-GGUF --hf-file mellum2-claude-Q4_K_M.gguf` | *(embedded)* |
| nemotron-nano | `-m …/Llama-3.1-Nemotron-Nano-8B-v1-Q6_K.gguf` | *(embedded — has a real tools branch and system slot)* |
| nemotron-elastic | `-m …/Nemotron-Elastic-12B/…gguf` | *(embedded)* |
| zaya1 | `-m …/ZAYA1-8B/ZAYA1-8B-Q6_K.gguf` **(`~/src/llama.cpp-zaya/build/bin/` draft-PR binary + lib_dir)** | *(embedded)* |
