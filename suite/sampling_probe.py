#!/usr/bin/env python3
"""Does cria's sampling recipe stop the model reproducing a literal verbatim?

Copying a string EXACTLY is not a creative act — it is most of what a coding model does all day
(an old_string for an edit, an expected value in a test, a long address in an assertion). A
repetition penalty makes a token that just appeared LESS likely, which is precisely the wrong
pressure for `addr1e0000000000000000000000000000000000002`.

cria currently sends gemma4 `temperature 0.2, top_k 20, repeat_penalty 1.1`, whose config comment
records where they came from: "ternary-bonsai (Qwen3.6 base): Qwen thinking rec". gemma4's own
GGUF defaults are `temperature 1.0, top_k 64, repeat_penalty 1.0`.

Scoring is exact string equality — no judgment, no model in the loop. Talks to the model server
DIRECTLY, bypassing cria, so nothing here depends on cria's routing being right.

    python3 suite/sampling_probe.py [--trials 5]
"""
import argparse
import json
import statistics
import urllib.request

BASE = "http://127.0.0.1:18084/v1/chat/completions"

# Literals a coding model has to copy byte-for-byte. The first two are verbatim from the g22
# transcript — the run where ten steers argued about a zero count for sixty calls.
LITERALS = {
    "ada-addr-zeros(g22)": "addr1e0000000000000000000000000000000000002",
    "ada-addr-zeros-2(g22)": "addr1e0000000000000000000000000000000000001",
    "real-ada-addr": ("addr1qxsfzsmy6y2seduagp6fx9pht4yz9nspxvzyldtv36p2uz0"
                      "gzxzwvk47qvndp09kkvcr6wu73g3mlv6987xf087cyc7qfskjcn"),
    "real-stake-addr": "stake1u85prp8xt2lqxfkshjmtxvpa8w0g5galkdznlryhnlvzv0qk9z7h9",
    "repeated-line": "x = 1\nx = 1\nx = 1\nx = 1\nx = 1\nx = 1\nx = 1\nx = 1",
}

# What cria sends today vs what the model publisher ships, plus the one-variable isolations.
SETTINGS = {
    "cria-today (qwen recipe)": {"temperature": 0.2, "top_p": 0.95, "top_k": 20, "repeat_penalty": 1.1},
    "cria-today, penalty off":  {"temperature": 0.2, "top_p": 0.95, "top_k": 20, "repeat_penalty": 1.0},
    "gemma default":            {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "repeat_penalty": 1.0},
    "greedy":                   {"temperature": 0.0, "repeat_penalty": 1.0},
    "greedy + penalty 1.1":     {"temperature": 0.0, "repeat_penalty": 1.1},
}

PROMPT = ("Repeat the following value back to me EXACTLY, with no quotes, no explanation and no "
          "extra text — output only the value itself:\n\n{value}")


def ask(text: str, params: dict, timeout: int = 120) -> str:
    body = {"messages": [{"role": "user", "content": text}], "stream": False,
            "max_tokens": 400, **params}
    req = urllib.request.Request(BASE, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.load(r)
    msg = (payload.get("choices") or [{}])[0].get("message") or {}
    return (msg.get("content") or "").strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=5)
    args = ap.parse_args()

    print(f"exact-reproduction rate, {args.trials} trials per cell\n")
    header = f"{'setting':26s}" + "".join(f"{k[:19]:>21s}" for k in LITERALS) + f"{'ALL':>7s}"
    print(header)
    print("-" * len(header))
    for name, params in SETTINGS.items():
        rates, row = [], f"{name:26s}"
        for value in LITERALS.values():
            hits = 0
            for _ in range(args.trials):
                try:
                    out = ask(PROMPT.format(value=value), params)
                except Exception as e:  # noqa: BLE001 — a probe failure is data, not a crash
                    out = f"<error {e}>"
                hits += int(out.strip().strip('`"\'') == value)
            rate = hits / args.trials
            rates.append(rate)
            row += f"{hits}/{args.trials:<19d}".rjust(21)
        print(row + f"{statistics.mean(rates):6.0%}")


if __name__ == "__main__":
    main()
