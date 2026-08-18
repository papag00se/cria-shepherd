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
    # ⚠ INFERRED from Qwen3.5, not stated on the card — docs/model-settings.md flags it unverified.
    "qwopus": {
        "coder":      {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
        "reasoner":   {"temperature": 0.6, "top_p": 0.95, "top_k": 20},
        "classifier": {"temperature": 0.0},
        "compactor":  {"temperature": 0.0},
    },
    # deepreinforce evals: temp 1.0 / top_p 0.95 general, temp 0.6 agentic. Coding is agentic here.
    "ornith": {
        "coder":      {"temperature": 0.6, "top_p": 0.95},
        "reasoner":   {"temperature": 1.0, "top_p": 0.95},
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
KNOBS = ("temperature", "top_p", "top_k", "min_p", "repeat_penalty",
         "collapse_system_prompt", "think_protocol", "merge_consecutive_turns")


# ---------------------------------------------------------------------------
# Per-model SATISFACTION CADENCE (operator-set, 2026-08-17).
#
# `_periodic_satisfaction` is the off-ramp for "a session that has FINISHED the work but cannot
# stop". It was gated at `satisfaction_check_start = 100`, then every 25 drives — a cadence tuned for
# long sessions, and **the median run in results.jsonl is 70 calls**, so 300 of 463 runs could never
# reach it. On the cell that exposed this it was arithmetically unreachable: 54 calls against a start
# of 100.
#
# Families, not names (#19/#20). The buckets are the operator's; the assignment is read from the
# repo's own GGUF-header classification in docs/model-settings.md ("`general.architecture` plus
# `<arch>.expert_count` / `expert_used_count`, never a card or a name"), so a new model joins by what
# it IS rather than by what it is called.
SATISFACTION_CADENCE = {
    # ternary — the operator gives this quant its own bucket, apart from the qwen family it derives
    # from. ternary-bonsai is Q2_0_g128 ternary, dense, `qwen35` arch.
    "ternary-bonsai":   (20, 10),
    # gemma
    "gemma4":           (24, 12),
    # qwen derivatives — dense, `general.architecture = qwen35`: the 9B base and the three finetunes
    # of it (qwythos = empero-ai's, qwopus = Jackrong's, ornith).
    "qwen35":           (30, 15),
    "qwythos":          (30, 15),
    "qwopus":           (30, 15),
    "ornith":           (30, 15),
    # MoEs — expert_count > 1 in the headers. mellum2 `mellum` 64(8), nemotron-elastic
    # `nemotron_h_moe` 128(6), maple-preview 256(8).
    #
    # maple-preview is the one genuine ambiguity in the mapping: its quant is tq2_0 TERNARY and its
    # architecture is MoE, so it could read as either bucket. Filed by ARCHITECTURE, because that is
    # what the repo's own classification keys on and what the cadence is about (how many drives a
    # session takes to converge), not by quant. Flagged rather than silently decided.
    "mellum2":          (54, 18),
    "nemotron-elastic": (54, 18),
    "maple-preview":    (54, 18),
}


def cadence(model: str) -> tuple[int, int] | None:
    """(start, every) for this model's satisfaction off-ramp, or None to leave the config alone."""
    return SATISFACTION_CADENCE.get(model)


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
