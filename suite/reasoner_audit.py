#!/usr/bin/env python3
"""What did the REASONER see when it got it wrong?

THE METHOD THIS ENFORCES. Nearly every "cria said something false" finding in this project is
really three steps: cria composed a prompt, a small model answered it badly, and cria delivered
that answer in its own voice. Blaming the answer stops one step short of the thing cria owns. The
prompt is cria's; the answer is a function of it.

Walked 2026-08-09 on mellum2 run 1786302864, which is why this file exists. cria injected a steer
containing FABRICATED shell output — a `Chunk ID`, a wall time, an exit code and an invented
`addr1q…` address — telling the coder its resolver worked when it had never once returned an
address. Read as "the steer author lied", that is a model failure and there is nothing to fix.
Read as "what did it see", it is cria's:

    call 0060-reasoner   system 2,769 chars — "you must never claim to have performed any action"
                         user  80,503 chars — containing 12 `exec_command(` blocks and 8
                                              `Chunk ID: … Process exited …` output blocks
                         ask: one sentence, at the very end

The prompt's dominant demonstrated pattern is *tool call followed by its output*, 20 times over,
and the prohibition is one line 80KB earlier. The model produced the most probable continuation of
what it was shown. cria's own source already records this lesson for the compaction path —
"passed 89 STRUCTURED turns — 42 of them its own tool calls — a weak model continues the pattern
and answers with a tool call, whatever the system prompt says" (cria/server.py) — and the fix there
was to flatten the history. This path flattens it and STILL demonstrates the syntax, so flattening
was necessary and not sufficient.

WHAT IT REPORTS, per non-coder call: how big the composed prompt was, what shapes it demonstrated,
where the actual question sits, and whether the answer conformed. A model asked for one word at the
end of 80KB of transcript is being set up, and that is visible here before anyone reads a line.

Usage:  python3 suite/reasoner_audit.py <capture>            # every reasoner-family call
        python3 suite/reasoner_audit.py <capture> --bad      # only the non-conforming answers
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from walk import list_calls, resolve_capture  # noqa: E402  (shared capture resolution)

# Phases where cria ASKS a model something and then acts on the answer. The coder is excluded: its
# prompt is the work, not a question, and it is what every other walk already reads.
ASKED_PHASES = ("reasoner", "critic", "satisfaction", "verify", "steer", "exec-intent",
                "research", "classifier", "self-compact", "confirm", "judge", "recover")

# Shapes a composed prompt can DEMONSTRATE to the model reading it. Each is a pattern the answer
# may then imitate — which is the failure this tool exists to make visible.
DEMONSTRATED = {
    "tool call syntax": re.compile(r"\b\w+\(\{|\bexec_command\(|\bedit_file\(|\bwrite_file\("),
    "tool OUTPUT block": re.compile(r"Chunk ID:|Process exited with code|Wall time:"),
    "json verdict": re.compile(r'\{\s*"(?:done|satisfied|consistent|verdict)"'),
    "⟦ctx:⟧ marker": re.compile(r"⟦ctx:"),
    "⟦cria⟧ marker": re.compile(r"⟦cria⟧"),
}

# What the answer was supposed to look like, inferred from the ask rather than hardcoded per phase.
# Must be an instruction to PRODUCE json. An earlier form matched "…never JSON, never a verdict"
# and reported a false problem on two conforming answers — a checker that cries wolf is the thing
# this whole tool exists to catch, so it does not get to do it itself.
WANTS_JSON = re.compile(r"(?i)output only (?:this )?json|reply with only the json|"
                        r"respond with (?:a |the )?json|answer with (?:a |the )?json")
WANTS_SENTINEL = re.compile(r"EXACTLY the one word `?([A-Z_]{4,})`?")
WANTS_SHORT = re.compile(r"(?i)under (\d+) words|short (?:imperative )?directive")


def _conformance(ask: str, answer: str) -> list[str]:
    """Ways the answer failed the shape the prompt asked for — [] when it conformed."""
    bad = []
    a = answer.strip()
    if not a:
        return ["EMPTY answer"]
    for label, pat in DEMONSTRATED.items():
        if label in ("tool call syntax", "tool OUTPUT block") and pat.search(a):
            bad.append(f"answer IMITATES the prompt's {label}")
    if WANTS_JSON.search(ask) and "never JSON" not in ask \
            and not a.lstrip().startswith(("{", "```")):
        bad.append("asked for JSON, answered prose")
    m = WANTS_SHORT.search(ask)
    if m and m.group(1) and len(a.split()) > int(m.group(1)) * 1.5:
        bad.append(f"asked for <{m.group(1)} words, answered {len(a.split())}")
    return bad


def _lost_it(thinking: str, answer: str) -> list[str]:
    """Did the thinking REACH a usable answer that the output then threw away?

    The distinction this draws is the one that changes the fix. "It never worked it out" is a
    prompt-evidence problem — the model was not shown what it needed. "It worked it out and then
    lost it" is an output-shape problem — the answer channel, the length budget, or the requested
    format destroyed a conclusion the model had already reached. The operator's standing rule is to
    read the reasoning FIRST for exactly this reason; the two look identical from the verdict alone
    and have nothing in common as bugs."""
    if not thinking:
        return []
    out = []
    if thinking.strip() and not answer.strip():
        out.append("THOUGHT but answered NOTHING — the conclusion died in the output channel")
    # A verdict the thinking CONCLUDED on and the answer then dropped. Only the tail counts:
    # weighing a sentinel and deciding against it is correct behaviour, and an earlier draft that
    # matched anywhere in the thinking flagged exactly that — call 0054 reasoned about ON_TRACK,
    # rightly rejected it, and wrote a real directive. Judge the conclusion, not the deliberation.
    tail = thinking[-220:]
    for tok in ("ON_TRACK", "NOT_DONE", "UNCLEAR", "DONE"):
        if re.search(rf"\b{tok}\b", tail) and answer.strip() and tok not in answer:
            out.append(f"thinking CONCLUDED `{tok}`; the answer does not carry it")
            break
    return out


def audit(cap: Path, only_bad: bool = False) -> int:
    rows = 0
    for num, phase, stem in list_calls(cap):
        if not any(p in phase for p in ASKED_PHASES):
            continue
        body_f, resp_f = stem.parent / f"{num}-{phase}.json", stem.parent / f"{num}-{phase}.response.json"
        if not body_f.exists():
            continue
        try:
            body = json.load(body_f.open()).get("body", {})
            msgs = body.get("messages") or []
        except (ValueError, OSError):
            continue
        system = next((m.get("content") or "" for m in msgs if m.get("role") == "system"), "")
        user = "\n".join(m.get("content") or "" for m in msgs if m.get("role") != "system")
        answer = thinking = ""
        if resp_f.exists():
            try:
                msg = json.load(resp_f.open())["choices"][0].get("message") or {}
                answer = msg.get("content") or ""
                thinking = msg.get("reasoning_content") or ""
                # Inline <think> is the same channel wearing a different hat on some templates.
                m = re.search(r"(?s)<think>(.*?)</think>", answer)
                if m:
                    thinking = thinking or m.group(1)
                    answer = (answer[:m.start()] + answer[m.end():]).strip()
            except (ValueError, OSError, KeyError, IndexError):
                pass
        ask = user[-600:]                      # the question almost always sits at the very end
        problems = _conformance(ask, answer or thinking)
        problems += _lost_it(thinking, answer)
        if only_bad and not problems:
            continue
        rows += 1
        shown = {k: len(p.findall(user)) for k, p in DEMONSTRATED.items()}
        shown = {k: v for k, v in shown.items() if v}
        print(f"\nCALL {num} [{phase}]   system {len(system):,} · prompt {len(user):,} chars")
        if shown:
            print("   DEMONSTRATED to it: " + ", ".join(f"{k} ×{v}" for k, v in shown.items()))
        print(f"   THE ASK (tail): …{' '.join(ask[-200:].split())}")
        if thinking:
            print(f"   IT THOUGHT ({len(thinking):,}): {' '.join(thinking.split())[:260]}")
            if len(thinking) > 260:
                print(f"      …ending: …{' '.join(thinking[-180:].split())}")
        print(f"   ANSWERED ({len(answer):,}): {' '.join(answer.split())[:200] or '(nothing)'}")
        for p in problems:
            print(f"   ⚠ {p}")
    return rows


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        return 2
    cap = resolve_capture(args[0])
    n = audit(cap, only_bad="--bad" in sys.argv)
    print(f"\n{n} asked-model call(s) reported from {cap.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
