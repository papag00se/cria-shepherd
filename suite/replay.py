#!/usr/bin/env python3
"""Replay CAPTURED calls against a settings matrix, and score what actually broke runs.

A full suite run costs 30 minutes and yields ONE noisy number. cria already stores the exact body
of every call it has ever made (~/.cria/calls/<session>/NNNN-<phase>.json), so the same question —
"do these sampling settings make the model behave better?" — can be asked against thousands of real
prompts in minutes, with deterministic scoring and no model in the judge's seat.

The three metrics are the three failures walks have actually turned up, not invented proxies:

  tool_ok     the coder's reply is a WELL-FORMED tool call. A malformed one is dropped
              unexecuted; runs have been lost to it.
  verdict_ok  a judge's reply carries the JSON verdict its prompt demands. g20 ended at 12 of its
              30 minutes because this came back unreadable and the brake confirmed on nothing.
  echo_ok     every 60+ character literal quoted in the PROMPT that also appears in the reply is
              reproduced byte-for-byte. suite/sampling_probe.py measured this in isolation; here it
              is measured in the middle of a real 40K-token agent prompt, which is where it matters.

Replays talk to the model server DIRECTLY, so nothing here depends on cria's routing. It is a
read-only experiment: no workspace is touched and no result is fed back into a run.

    python3 suite/replay.py --phase coder-s1 --n 40
    python3 suite/replay.py --phase satisfaction-confirm --n 25 --settings gemma-default,cria-today
"""
import argparse
import json
import os
import random
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import cria when run from anywhere

CALLS = Path.home() / ".cria" / "calls"
BASE = "http://127.0.0.1:18084/v1/chat/completions"
REQUEST_TIMEOUT_S = 300

# What cria sends today came from a DIFFERENT model family — cria.toml records it in the comment:
# "ternary-bonsai (Qwen3.6 base): Qwen thinking rec". gemma4's own GGUF ships 1.0 / 64 / 1.0.
SETTINGS = {
    "cria-today": {"temperature": 0.2, "top_p": 0.95, "top_k": 20, "repeat_penalty": 1.1},
    "gemma-default": {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "repeat_penalty": 1.0},
    "greedy": {"temperature": 0.0, "repeat_penalty": 1.0},
    "cria-no-penalty": {"temperature": 0.2, "top_p": 0.95, "top_k": 20, "repeat_penalty": 1.0},
}

# A judge prompt demands a JSON object carrying one of these decision keys.
VERDICT_KEYS = ("consistent", "satisfied", "done")
LONG_LITERAL = re.compile(r"[A-Za-z0-9_]{60,}")
# Sampling knobs cria set on the captured body; stripped so the matrix is what varies.
_SAMPLING = ("temperature", "top_p", "top_k", "min_p", "repeat_penalty", "presence_penalty",
             "frequency_penalty", "seed")


def captured(phase: str, limit: int, seed: int = 3, forced_only: bool = False) -> list[dict]:
    """`limit` captured request bodies for `phase`, sampled across ALL sessions — one run's quirks
    must not become the finding.

    ``forced_only`` keeps ONLY the rounds where an answer is actually due: the judge holds read-only
    tools and is EXPECTED to inspect first, so scoring "did it emit a verdict" against round 1 scores
    correct behaviour as failure. It measured 1/12 before this filter and every one of those replies
    was a perfectly good read_file."""
    bodies = []
    for d in sorted(CALLS.glob("2*")):
        for f in sorted(d.glob(f"*-{phase}*.json")):
            if f.name.endswith(".response.json"):
                continue
            try:
                j = json.loads(f.read_text())
            except (ValueError, OSError):
                continue
            b = j.get("body") or {}
            if j.get("phase") == phase and b.get("messages"):
                bodies.append(b)
    if forced_only:
        from cria import verifytools
        tail = verifytools.ANSWER_NOW[:40]
        bodies = [b for b in bodies
                  if not b.get("tools") or tail in json.dumps(b.get("messages", []))]
    random.Random(seed).shuffle(bodies)
    return bodies[:limit]


def ask(body: dict, params: dict) -> dict:
    out = {k: v for k, v in body.items() if k not in _SAMPLING}
    out.update(params)
    out["stream"] = False
    req = urllib.request.Request(BASE, data=json.dumps(out).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as r:
        payload = json.load(r)
    return (payload.get("choices") or [{}])[0].get("message") or {}


def _json_objects(text: str):
    """Every balanced {...} span in `text` that parses — a verdict may arrive fenced, prefixed by
    prose, or trailed by a stray tool call, and all three still count as answering."""
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        depth = 0
        for j in range(i, len(text)):
            depth += (text[j] == "{") - (text[j] == "}")
            if depth == 0:
                try:
                    yield json.loads(text[i:j + 1])
                except ValueError:
                    pass
                break


class _Silent:
    def emit(self, *a, **k):
        pass


def cria_reads_verdict(text: str) -> bool:
    """Would CRIA accept this reply as a verdict? Asked of cria's OWN parsers, never a lookalike.

    A scorer that merely looks for the literal key is not measuring cria. Measured the hard way:
    qwythos returns valid JSON with a sound reason and simply omits `done`, and cria's
    `_fill_missing_verdict_flag` infers the flag from the schema's own `proposed_fix` contract —
    empty means done, filled means not. A key-spotting scorer called that 1/4; cria accepts 4/4,
    and I reported a live defect that did not exist. Import the real thing or measure nothing."""
    from cria.loop import _consistent_word, _fill_missing_verdict_flag
    if _consistent_word(text) is not None:
        return True
    for obj in _json_objects(text):
        for flag in ("done", "satisfied", "consistent"):
            filled = _fill_missing_verdict_flag(obj, flag, _Silent(), "replay")
            if filled is not None and isinstance(filled.get(flag), bool):
                return True
    return False


def score(body: dict, msg: dict, phase: str) -> dict:
    content = (msg.get("content") or "")
    calls = msg.get("tool_calls") or []
    res = {}
    if phase.startswith("coder"):
        # Well-formed = every call names a tool AND its arguments parse as a JSON object.
        ok = bool(calls)
        for tc in calls:
            fn = tc.get("function") or {}
            if not fn.get("name"):
                ok = False
                break
            try:
                if not isinstance(json.loads(fn.get("arguments") or "{}"), dict):
                    ok = False
            except ValueError:
                ok = False
        # A turn that legitimately ANSWERS in prose (no tool call) is not a malformed call; only
        # count turns where the model tried to act.
        res["tool_ok"] = ok if calls else None
    if any(k in json.dumps(body.get("messages", []))[:20000] for k in VERDICT_KEYS):
        res["verdict_ok"] = cria_reads_verdict(content + json.dumps(calls))
    prompt_text = json.dumps(body.get("messages", []))
    reply_text = content + json.dumps(calls)
    literals = {m for m in LONG_LITERAL.findall(prompt_text)}
    echoed = [lit for lit in literals if lit[:40] in reply_text]
    if echoed:
        res["echo_ok"] = all(lit in reply_text for lit in echoed)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="coder-s1")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--settings", default=",".join(SETTINGS))
    ap.add_argument("--forced-only", action="store_true",
                    help="only rounds where a verdict is DUE (tools withdrawn / answer-now)")
    args = ap.parse_args()

    bodies = captured(args.phase, args.n, forced_only=args.forced_only)
    if not bodies:
        raise SystemExit(f"no captured calls for phase {args.phase!r}")
    names = [s for s in args.settings.split(",") if s in SETTINGS]
    print(f"phase={args.phase}  prompts={len(bodies)}  settings={names}\n")
    print(f"{'setting':16s}" + "".join(f"{m:>14s}" for m in ("tool_ok", "verdict_ok", "echo_ok"))
          + f"{'errors':>9s}")
    print("-" * 67)
    for name in names:
        tally = {m: [0, 0] for m in ("tool_ok", "verdict_ok", "echo_ok")}
        errors = 0
        for b in bodies:
            try:
                msg = ask(b, SETTINGS[name])
            except Exception:  # noqa: BLE001 — an upstream failure is data
                errors += 1
                continue
            for m, v in score(b, msg, args.phase).items():
                if v is None:
                    continue
                tally[m][1] += 1
                tally[m][0] += int(v)
        row = f"{name:16s}"
        for m in ("tool_ok", "verdict_ok", "echo_ok"):
            hit, tot = tally[m]
            row += f"{(f'{hit}/{tot}' if tot else '—'):>14s}"
        print(row + f"{errors:>9d}")


if __name__ == "__main__":
    main()
