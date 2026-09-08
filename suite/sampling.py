#!/usr/bin/env python3
"""Canonical per-model sampling, applied automatically when the suite swaps models.

`docs/model-settings.md` is the human source of truth for these numbers and every entry below cites
it. This module is the machine-readable form, because the manual step it replaces has already been
missed at scale: **26 consecutive gemma4 runs were sent ternary-bonsai's sampling** (coder
0.2/0.95/20, reasoner 0.6/0.90/40) because `run.py` swapped the model and the planner but never the
`[roles.*]` blocks, and cria.toml still held the previous model's numbers. Every one of those runs
measured a model nobody was testing.

A procedure that must be remembered before each run is a footgun. The runner now applies these on
every swap, so a cell cannot silently inherit the last model's settings.

    python3 suite/sampling.py --model gemma4          # show what would be written
    python3 suite/sampling.py --model gemma4 --apply  # write it into ~/.cria/cria.toml

Roles: cria drives `coder` (writes the code), `reasoner` (planner + step/task critic), `classifier`
(routing) and `compactor` (summarising). Where a card gives one set of numbers, the coding value
goes to the coder and the general value to the reasoner; deterministic roles stay at temp 0.
"""
import argparse
import json
import urllib.request
import struct
import math
import re
import sys
from pathlib import Path

CRIA_TOML = Path.home() / ".cria" / "cria.toml"

# model -> role -> knobs. Cite the source in the comment; an uncited number here is a guess, and a
# guess in this file becomes a silent confound in every run of that model.
MODEL_SAMPLING = {
    # CANONICAL, m15-verified (the first fully unaided goal success). docs/model-settings.md.
    "ternary-bonsai": {
        "coder":      {"temperature": 0.2, "top_p": 0.95, "top_k": 20, "repeat_penalty": 1.1},
        "reasoner":   {"temperature": 0.6, "top_p": 0.90, "top_k": 40, "repeat_penalty": 1.1},
        "classifier": {"temperature": 0.0, "repeat_penalty": 1.1},
        "compactor":  {"temperature": 0.0, "repeat_penalty": 1.1},
    },
    # yuxinlu1 card: temp 1.0 / top_p 0.95 / top_k 64 / repeat_penalty 1.1, coding temp 0.
    # The rep-penalty is load-bearing — without it gemma4 leaks <|tool_call|>/<|channel|> tokens.
    # Card (yuxinlu1 pinned discussion): temp 1.0 + rep_pen 1.1 — the pairing is the point.
    # We ran the coder at temp 0.0 for the whole ladder+campaign era; the card never says temp 0
    # anywhere (audited 2026-08-04, operator-directed). Greedy + rep-penalty is an identifier
    # MUTATION engine: every reused name is logit-penalized /1.1, and at temp 0 any near-neighbor
    # within ~10% flips the argmax — handler/handle, papagoose->papagoase, Pytest/pytest,
    # __cria->__cira, 8ibs->8Ibs are all this, and every campaign walk's edit-spiral began with
    # one. At temp 1.0 (the tuning point) the penalty shifts odds without deterministic flips.
    # STOCK Gemma 4 12B it — identical sampling to the finetune so the
    # ablation isolates the WEIGHTS (operator ask 2026-08-05).
    "gemma4": {
        "coder":      {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "repeat_penalty": 1.1},
        "reasoner":   {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "repeat_penalty": 1.1},
        "classifier": {"temperature": 0.0, "repeat_penalty": 1.1},
        "compactor":  {"temperature": 0.0, "repeat_penalty": 1.1},
    },
    # DeepGrove Maple-Preview — NO publisher card yet (preview + community port). Neutral
    # start: temp 1.0 nucleus, NO repeat penalty (the penalty is a per-model finding, never a
    # default — greedy+penalty was the gemma mutation engine). Tune only from replay/run evidence.
    "maple-preview": {
        "coder":      {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "repeat_penalty": 1.0},
        "reasoner":   {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "repeat_penalty": 1.0},
        "classifier": {"temperature": 0.0, "repeat_penalty": 1.0},
        "compactor":  {"temperature": 0.0, "repeat_penalty": 1.0},
    },
    # empero-ai (Qwen3.5 thinking): temp 0.6 / top_p 0.95 / top_k 20.
    "qwythos": {
        "coder":      {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
        "reasoner":   {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
        "classifier": {"temperature": 0.0},
        "compactor":  {"temperature": 0.0},
    },
    # DeepSeek-R1's card is explicit and unusually strict: temperature 0.5-0.7 (0.6 recommended),
    # top_p 0.95, and NO system prompt — everything in the user turn. 0.6 is the midpoint it names.
    # top_k is left off because the card does not publish one.
    # NVIDIA's card gives sampling PER REASONING MODE: reasoning ON -> temp 0.6 / top_p 0.95,
    # reasoning OFF -> greedy. cria drives coder and reasoner with thinking on and the classifier
    # and compactor with it off, so the card maps straight onto the four roles.
    # `think_protocol` rides here too: the switch is a system-prompt SENTENCE on this model, and the
    # convention is the MODEL's rather than the endpoint's — the same llama.cpp server on :18084
    # serves parameter-toggled models the rest of the week. Listed in KNOBS so it is dropped on swap.
    "qwen35": {
        "coder":      {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
        "reasoner":   {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
        "classifier": {"temperature": 0.0},
        "compactor":  {"temperature": 0.0},
    },
    # Qwen3.8-27B (W4A16 + MTP) on the vLLM/3090 endpoint, not the llama.cpp fleet. Qwen's card:
    # thinking mode temp 0.6 / top_p 0.95 / top_k 20; cria drives coder+reasoner with thinking on and
    # the deterministic roles with it off, so the thinking numbers map onto the four roles here too.
    "qwen38": {
        "coder":      {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
        "reasoner":   {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
        "classifier": {"temperature": 0.0},
        "compactor":  {"temperature": 0.0},
    },
    # ⚠ INFERRED from Qwen3.5, not stated on the card — docs/model-settings.md flags it unverified.
    "qwopus": {
        "coder":      {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
        "reasoner":   {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
        "classifier": {"temperature": 0.0},
        "compactor":  {"temperature": 0.0},
    },
    # Ornith 1.5 publisher card: precise coding 0.6/.95/k20/min-p0/presence0/repetition1;
    # general 1.0/.95/k20/min-p0/presence1.5/repetition1. Coding maps to coder; general maps
    # to the reasoner. Deterministic roles retain temp 0 and neutral penalties.
    "ornith15": {
        "coder":      {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0,
                       "presence_penalty": 0.0, "repeat_penalty": 1.0},
        "reasoner":   {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0,
                       "presence_penalty": 1.5, "repeat_penalty": 1.0},
        "classifier": {"temperature": 0.0, "presence_penalty": 0.0, "repeat_penalty": 1.0},
        "compactor":  {"temperature": 0.0, "presence_penalty": 0.0, "repeat_penalty": 1.0},
    },
    # ai-sage's llama.cpp chat and function-call examples both use temperature 0. No broader
    # sampling recommendation is published, so parity starts from that exact demonstrated value.
    "gigachat31": {
        "coder":      {"temperature": 0.0},
        "reasoner":   {"temperature": 0.0},
        "classifier": {"temperature": 0.0},
        "compactor":  {"temperature": 0.0},
    },
    # JetBrains (Thinking model): temp 0.6 / top_p 0.95 / top_k 20.
    "mellum2": {
        "coder":      {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
        "reasoner":   {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
        "classifier": {"temperature": 0.0},
        "compactor":  {"temperature": 0.0},
    },
    # NVIDIA Nemotron 3 guide: temp 0.6 / top_p 0.95 for tool-calling, 1.0/1.0 general chat.
    "nemotron-elastic": {
        "coder":      {"temperature": 0.6, "top_p": 0.95},
        "reasoner":   {"temperature": 0.6, "top_p": 0.95},
        "classifier": {"temperature": 0.0},
        "compactor":  {"temperature": 0.0},
    },
}

# `collapse_system_prompt` is not sampling, but it is the same KIND of thing: a per-model, per-role
# value cria.toml carries and run.py rewrites on every swap. Listed here so a stale one from the
# previous model is dropped, exactly like a stale temperature.
KNOBS = ("temperature", "top_p", "top_k", "min_p", "repeat_penalty", "presence_penalty",
         "collapse_system_prompt", "think_protocol", "merge_consecutive_turns")


# ---------------------------------------------------------------------------
# SATISFACTION CADENCE, a sliding scale on ACTIVE PARAMETERS (operator rule, 2026-08-17).
#
# `_periodic_satisfaction` is the off-ramp for "a session that has FINISHED the work but cannot
# stop". It was gated at `satisfaction_check_start = 100`, then every 25 drives — and the median run
# in results.jsonl is 70 calls, so **300 of 463 runs could never reach it**.
#
# THE RULE: the more parameters a model actually scans per token, the LOWER the start and interval,
# because the higher-parameter models tend to be DONE in fewer turns. A model that converges in
# fifty drives must be asked before drive fifty.
#
# PINNED TO PARAMETERS, NOT tok/s. Throughput was the first cut and it is hardware-bound — the same
# model on a different GPU moves bands without changing at all. Active parameters are a property of
# the model.
#
# ACTIVE, not total, and the difference is the whole point for this fleet: `nemotron-elastic` and
# `gemma4` are both ~11.9B TOTAL, and one scans a sixth of itself. Total params would file them
# together; the rule is about what is scanned.
#
#     active ~= n_params * (expert_used_count / expert_count)     MoE
#             = n_params                                          dense (no expert keys)
#
# `n_params` comes from the server (`/v1/models` -> `meta.n_params`); the expert counts come from the
# GGUF header at the `model_path` the server reports — the same source docs/model-settings.md used to
# classify the fleet, "never a card or a name". Both machine-read, stdlib only, no table to maintain.
#
# THE RATIO IS A LOWER BOUND. Attention, embeddings and shared layers are not sharded across experts,
# so true active params are somewhat higher than the naive product (nemotron computes ~0.6B this way
# against a card figure of ~2B). That is fine for what this decides: every MoE in the fleet lands
# under 2B either way and every dense model over 9B, so the ordering the scale needs is unaffected.
# It is recorded rather than corrected because a correction would be a guess at a shape that varies
# per architecture.
#
# A SLIDING SCALE, one line: every tenfold increase in scanned parameters drops the start by 30.
#
#     start = CADENCE_AT_1B - CADENCE_PER_DECADE * log10(active_B)
#
# The ceiling is what makes it work at all: the median run in results.jsonl is 70 calls, so a start
# above that is a check that never happens — which is exactly what the flat 100 was. Everything this
# produces stays under it. The floor keeps a very large model from being asked on almost every drive.
CADENCE_AT_1B = 60           # a 1B-active model: long runs, ask late
CADENCE_PER_DECADE = 30      # 10x the scanned parameters -> 30 fewer drives before asking
CADENCE_MIN_START, CADENCE_MAX_START = 15, 60
CADENCE_INTERVAL_DIVISOR = 2  # re-ask twice as often as the wait to the first ask

# A model whose parameters cannot be read takes the LOW end. Unknown is not "small": checking too
# early costs one reasoner call, checking too late costs a finished session that never stops (#13's
# safe direction — fail toward continuing to look).
CADENCE_UNKNOWN = (20, 10)

_GGUF_T = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}


def gguf_experts(path: str) -> tuple[int, int] | None:
    """(expert_count, expert_used_count) from a GGUF header, or None for a dense model.

    Reads only the KV block at the head of the file — no tensors, no third-party library."""
    want_all, want_used = None, None
    try:
        with open(path, "rb") as fh:
            magic, _ver, _nt, nkv = struct.unpack("<4sIQQ", fh.read(24))
            if magic != b"GGUF":
                return None

            def _s():
                (n,) = struct.unpack("<Q", fh.read(8))
                return fh.read(n).decode("utf-8", "replace")

            def _v(t):
                if t == 8:
                    return _s()
                if t == 9:
                    (et,) = struct.unpack("<I", fh.read(4))
                    (n,) = struct.unpack("<Q", fh.read(8))
                    return [_v(et) for _ in range(n)]
                f = _GGUF_T.get(t)
                if f is None:
                    raise ValueError(t)
                return struct.unpack("<" + f, fh.read(struct.calcsize("<" + f)))[0]

            for _ in range(nkv):
                k = _s()
                (t,) = struct.unpack("<I", fh.read(4))
                v = _v(t)
                if k.endswith(".expert_count"):
                    want_all = int(v)
                elif k.endswith(".expert_used_count"):
                    want_used = int(v)
    except (OSError, ValueError, struct.error):
        return None
    if not want_all or not want_used:
        return None
    return want_all, want_used


def active_params_b(server: str = "http://127.0.0.1:18084") -> float | None:
    """Billions of parameters the LOADED model scans per token, or None when it cannot be read."""
    try:
        with urllib.request.urlopen(f"{server}/v1/models", timeout=5) as r:
            meta = (json.load(r).get("data") or [{}])[0].get("meta") or {}
        with urllib.request.urlopen(f"{server}/props", timeout=5) as r:
            path = json.load(r).get("model_path") or ""
    except (OSError, ValueError, KeyError):
        return None
    total = meta.get("n_params")
    if not total:
        return None
    experts = gguf_experts(path) if path else None
    ratio = (experts[1] / experts[0]) if experts else 1.0
    return (float(total) * ratio) / 1e9


def cadence_for_active(active_b: float | None) -> tuple[int, int]:
    """(start, every) for a model that scans `active_b` billion parameters per token."""
    if not active_b or active_b <= 0:
        return CADENCE_UNKNOWN
    start = CADENCE_AT_1B - CADENCE_PER_DECADE * math.log10(active_b)
    start = int(round(max(CADENCE_MIN_START, min(CADENCE_MAX_START, start))))
    return start, max(5, round(start / CADENCE_INTERVAL_DIVISOR))


def cadence(model: str = "", server: str = "http://127.0.0.1:18084") -> tuple[int, int]:
    """(start, every) for the model the server currently has loaded."""
    return cadence_for_active(active_params_b(server))


def render(model: str) -> dict:
    if model not in MODEL_SAMPLING:
        raise KeyError(f"no canonical sampling recorded for {model!r}. Add it to "
                       f"suite/sampling.py with its source, or the run measures whatever the "
                       f"previous model left in cria.toml.")
    return MODEL_SAMPLING[model]


def apply(model: str, toml_path: Path = CRIA_TOML) -> dict:
    """Rewrite each `[roles.<role>]` block's sampling knobs in place.

    Only the knobs this model declares are written; a knob it does not declare is REMOVED rather
    than left behind, because a stale `top_k = 20` from the previous model is exactly the silent
    confound this module exists to stop. Non-sampling keys in the block (backend, reasoning,
    output_reserve) are untouched.
    """
    spec = render(model)
    text = toml_path.read_text()
    for role, knobs in spec.items():
        header = f"[roles.{role}]"
        i = text.find(header)
        if i < 0:
            raise RuntimeError(f"{toml_path} has no {header} to configure")
        j = text.find("\n[", i + 1)
        j = len(text) if j < 0 else j
        block = text[i:j]
        kept = []
        for line in block.splitlines():
            key = line.split("=", 1)[0].strip()
            if key in KNOBS and not line.lstrip().startswith("#"):
                continue                       # drop every sampling line; re-add this model's below
            kept.append(line)
        # TOML booleans are lowercase; Python's repr of True is not valid TOML and cria's loader
        # would fail to parse the file it was handed.
        def _lit(v):
            if v is True or v is False:
                return "true" if v else "false"
            return f'"{v}"' if isinstance(v, str) else v
        added = [f"{k} = {_lit(v)}" for k, v in knobs.items()]
        # keep the header first, then the surviving keys, then this model's sampling
        text = text[:i] + "\n".join([kept[0]] + kept[1:] + added).rstrip() + "\n" + text[j:]
    text = _write_cadence(model, text)
    toml_path.write_text(text)
    return spec


def _write_cadence(model: str, text: str) -> str:
    """Put this model's satisfaction cadence into `[context]`, the same way the roles get sampling.

    Same reason as the sampling this module exists for: a per-model number that must be set by hand
    before a run is a number that will be left at the previous model's value. A model with no entry
    leaves the config untouched rather than inheriting a default that was tuned for something else."""
    pair = cadence(model)
    if pair is None:
        return text
    start, every = pair
    i = text.find("[context]")
    if i < 0:                                    # no [context] block — append one
        return text.rstrip() + (f"\n\n[context]\nsatisfaction_check_start = {start}\n"
                                f"satisfaction_check_every = {every}\n")
    j = text.find("\n[", i + 1)
    j = len(text) if j < 0 else j
    kept = [ln for ln in text[i:j].splitlines()
            if ln.split("=", 1)[0].strip() not in ("satisfaction_check_start",
                                                   "satisfaction_check_every")]
    block = "\n".join(kept).rstrip() + (f"\nsatisfaction_check_start = {start}\n"
                                        f"satisfaction_check_every = {every}\n")
    return text[:i] + block + text[j:]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=sorted(MODEL_SAMPLING))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    spec = apply(args.model) if args.apply else render(args.model)
    for role, knobs in spec.items():
        print(f"[roles.{role}]  " + "  ".join(f"{k}={v}" for k, v in knobs.items()))
    print(("APPLIED to " + str(CRIA_TOML)) if args.apply else "(dry run — pass --apply to write)")


if __name__ == "__main__":
    main()
