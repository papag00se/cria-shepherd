#!/usr/bin/env python3
"""Emit a captured run for a FULL line walk — every call, every line, zero truncation.

Why this exists: a walk done through an ad-hoc digest script silently cut reasoning at a few
hundred characters and tool arguments shorter still, and two real defects (a file the run DID
create, and the harness's "unsupported call" replies) were invisible in the cut. The walk doctrine
(docs/regression-goal.md) says "read EVERY call in order — no grep, no sampling"; this tool is the
one permitted way to materialize a capture for that reading, and it NEVER truncates content.

For each call NNNN-<phase> in the capture directory it prints:

  CALL NNNN [phase]
  --- PROMPT ---            the full prompt the FIRST time each phase appears; after that, only
                            the suffix beyond the byte-identical common prefix with the previous
                            prompt of the SAME phase (nothing is lost: the omitted bytes were
                            already printed verbatim). When a prompt is recomposed — shorter than
                            or diverging from its predecessor — that is flagged with the char
                            count and, by default, the divergent remainder is printed IN FULL.
                            --full-prompts disables prefix-dedup entirely.
  --- THINK ---             the model's complete reasoning_content, unabridged.
  --- SAY ---               the complete assistant text, unabridged.
  --- TOOL CALL <name> ---  the complete raw argument string of every tool call, unabridged.
  [finish: <reason>]

Output goes to stdout, or to numbered chunk files with --out (default ~64 KB per chunk so a
reader can take the run in order without any single file being unloadable).

    python3 suite/walk.py ~/.cria/calls/<session>            # whole run to stdout
    python3 suite/walk.py <session-name> --out /tmp/lw       # chunked into /tmp/lw/chunkNN.txt
    python3 suite/walk.py <session-name> --full-prompts      # no prefix-dedup at all

There is deliberately NO flag to shorten, sample, or filter content. If a walk needs less than
this, it is not a walk.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

CALLS_ROOT = Path.home() / ".cria" / "calls"
CHUNK_BYTES_DEFAULT = 64_000
_CALL_RE = re.compile(r"^(\d{4})-(.+)\.json$")


def resolve_capture(arg: str) -> Path:
    p = Path(os.path.expanduser(arg))
    if p.is_dir():
        return p
    cand = CALLS_ROOT / arg
    if cand.is_dir():
        return cand
    matches = sorted(d for d in CALLS_ROOT.iterdir() if d.is_dir() and arg in d.name)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        sys.exit(f"no capture directory matches {arg!r} under {CALLS_ROOT}")
    sys.exit(f"{arg!r} is ambiguous under {CALLS_ROOT}: " + ", ".join(d.name for d in matches))


def list_calls(cap: Path):
    """(number, phase, stem) for every captured call, in call order."""
    out = []
    for f in sorted(cap.iterdir()):
        m = _CALL_RE.match(f.name)
        if m and not f.name.endswith((".response.json",)):
            out.append((m.group(1), m.group(2), f.with_suffix("")))
    return out


def emit_call(num: str, phase: str, stem: Path, prev_prompts: dict, full_prompts: bool):
    """Render one call as text. prev_prompts maps phase -> previous full prompt text."""
    lines = []
    lines.append("=" * 90)
    lines.append(f"CALL {num} [{phase}]")
    lines.append("=" * 90)

    prompt_file = stem.parent / f"{num}-{phase}.prompt.txt"
    prompt = prompt_file.read_text(errors="replace") if prompt_file.exists() else ""
    prev = prev_prompts.get(phase)
    if full_prompts or prev is None:
        tag = "" if full_prompts else f" (FULL, first {phase})"
        lines.append(f"--- PROMPT{tag} ---")
        lines.append(prompt.rstrip("\n"))
    else:
        i = 0
        limit = min(len(prev), len(prompt))
        while i < limit and prev[i] == prompt[i]:
            i += 1
        if len(prompt) < len(prev):
            lines.append(f"--- PROMPT Δ [prompt SHRANK by {len(prev) - len(prompt)} chars — recomposed] ---")
        else:
            lines.append("--- PROMPT Δ ---")
        lines.append(prompt[i:].rstrip("\n"))
    prev_prompts[phase] = prompt

    resp_file = stem.parent / f"{num}-{phase}.response.json"
    if resp_file.exists():
        resp = json.loads(resp_file.read_text(errors="replace"))
        for choice in resp.get("choices", []):
            msg = choice.get("message", {})
            think = (msg.get("reasoning_content") or "").rstrip("\n")
            if think:
                lines.append("--- THINK (full) ---")
                lines.append(think)
            say = (msg.get("content") or "").rstrip("\n")
            if say:
                lines.append("--- SAY (full) ---")
                lines.append(say)
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function", {})
                lines.append(f"--- TOOL CALL {fn.get('name', '?')} (full args) ---")
                lines.append(fn.get("arguments", ""))
            lines.append(f"[finish: {choice.get('finish_reason')}]")
    else:
        lines.append("[no response captured]")
    lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("capture", help="capture dir path, session name, or unique fragment of one")
    ap.add_argument("--out", help="write numbered chunk files into this directory instead of stdout")
    ap.add_argument("--chunk-bytes", type=int, default=CHUNK_BYTES_DEFAULT,
                    help=f"target size per chunk file with --out (default {CHUNK_BYTES_DEFAULT})")
    ap.add_argument("--full-prompts", action="store_true",
                    help="print every prompt whole; no common-prefix dedup")
    args = ap.parse_args()

    cap = resolve_capture(args.capture)
    calls = list_calls(cap)
    if not calls:
        sys.exit(f"no captured calls in {cap}")

    prev_prompts = {}
    blocks = [emit_call(num, phase, stem, prev_prompts, args.full_prompts)
              for num, phase, stem in calls]

    if not args.out:
        sys.stdout.write("".join(blocks))
        return

    outdir = Path(os.path.expanduser(args.out))
    outdir.mkdir(parents=True, exist_ok=True)
    chunks, cur, size = [], [], 0
    for b in blocks:
        # A call never splits across chunks — every chunk is a whole number of calls.
        if cur and size + len(b) > args.chunk_bytes:
            chunks.append("".join(cur))
            cur, size = [], 0
        cur.append(b)
        size += len(b)
    if cur:
        chunks.append("".join(cur))
    width = max(2, len(str(len(chunks))))
    for i, text in enumerate(chunks, 1):
        (outdir / f"chunk{i:0{width}d}.txt").write_text(text)
    total = sum(len(c) for c in chunks)
    print(f"{len(calls)} calls → {len(chunks)} chunks, {total:,} bytes, in {outdir}")


if __name__ == "__main__":
    main()
