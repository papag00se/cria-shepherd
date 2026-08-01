#!/usr/bin/env python3
"""Which ASK SHAPE do small models actually answer — a JSON object, or a single word?

cria's judges (the step critic, the satisfaction check, the approve-path confirm) end their
inspection loop by withdrawing the read-only tools and demanding a JSON verdict. Measured on real
captured prompts, gemma4 answers that demand 0 times in 14: with no tools advertised it emits its
tool-call TEMPLATE as literal text — `<|tool_call>call:Bash{command:"cd /home/user1/Mythos/..."}` —
inventing a path from pretraining. Asked instead for ONE WORD, the same prompts, model and sampling
answer 14 out of 14.

That is one model. This script runs the same A/B across the whole fleet, because a shape that fixes
gemma and breaks qwythos is not a fix. It swaps models through systemd exactly as suite/run.py does
(one model at a time on the 3080) and replays REAL captured judge prompts, changing nothing but the
final instruction.

    python3 suite/ask_shape.py --models gemma4,ternary-bonsai,qwythos --n 8
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from suite.replay import SETTINGS, ask, captured, _json_objects  # noqa: E402
from suite.run import SERVICES, wait_health  # noqa: E402

JSON_ASK = None  # leave the captured prompt exactly as cria sends it today

# Per phase: the word pair that phase's verdict uses, and how to recognise it.
PHASES = {
    "satisfaction-confirm": (
        "You have inspected enough. Reply with EXACTLY ONE WORD on the first line — CONSISTENT if the "
        "completion claim holds up against what you read, INCONSISTENT if it does not — then, on a "
        "second line, one short sentence saying why.",
        ("CONSISTENT", "INCONSISTENT")),
    "critic": (
        "You have inspected enough. Reply with EXACTLY ONE WORD on the first line — DONE if the step is "
        "complete, NOT_DONE if it is not — then, on a second line, one short sentence saying why.",
        ("DONE", "NOT_DONE")),
}

VERDICT_KEYS = ("consistent", "satisfied", "done")


def answered_json(text: str) -> bool:
    return any(any(k in o for k in VERDICT_KEYS) for o in _json_objects(text))


def answered_word(text: str, words) -> bool:
    return text.strip().lstrip("*#`\"' ").upper().startswith(words)


def swap(model: str) -> None:
    target = SERVICES[model]
    for svc in SERVICES.values():
        if svc != target:
            subprocess.run(["sudo", "-n", "systemctl", "stop", f"{svc}.service"],
                           capture_output=True, timeout=120)
    subprocess.run(["sudo", "-n", "systemctl", "start", f"{target}.service"],
                   capture_output=True, timeout=120)
    if not wait_health("http://127.0.0.1:18084/health"):
        raise RuntimeError(f"{model} never became healthy")
    time.sleep(2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gemma4,ternary-bonsai,qwythos")
    ap.add_argument("--phase", default="satisfaction-confirm")
    ap.add_argument("--n", type=int, default=8)
    args = ap.parse_args()

    phases = [p for p in args.phase.split(",") if p in PHASES]
    sets = {p: captured(p, args.n, forced_only=True) for p in phases}
    print("prompts per phase: " + ", ".join(f"{p}={len(sets[p])}" for p in phases) + "\n")
    head = f"{'model':18s}"
    for p in phases:
        head += f"{p[:14] + ' JSON':>22s}{p[:14] + ' word':>22s}"
    print(head)
    print("-" * len(head))
    for model in [m.strip() for m in args.models.split(",") if m.strip() in SERVICES]:
        try:
            swap(model)
        except Exception as e:  # noqa: BLE001 — an unavailable model is data, not a crash
            print(f"{model:18s}{'(swap failed: ' + str(e)[:24] + ')':>34s}")
            continue
        row = f"{model:18s}"
        for p in phases:
            word_ask, words = PHASES[p]
            j = w = 0
            for b in sets[p]:
                try:
                    m = ask(b, SETTINGS["greedy"])
                    j += int(answered_json((m.get("content") or "") + json.dumps(m.get("tool_calls") or [])))
                except Exception:  # noqa: BLE001
                    pass
                body = json.loads(json.dumps(b))
                for msg in reversed(body["messages"]):
                    if msg.get("role") == "user":
                        msg["content"] = word_ask
                        break
                try:
                    w += int(answered_word(ask(body, SETTINGS["greedy"]).get("content") or "", words))
                except Exception:  # noqa: BLE001
                    pass
            n = len(sets[p])
            row += f"{f'{j}/{n}':>22s}{f'{w}/{n}':>22s}"
        print(row, flush=True)


if __name__ == "__main__":
    main()
