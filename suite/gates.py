#!/usr/bin/env python3
"""The mid-run gate's worklist: which questions are open, and block until one is.

THE GATE IS ONLY AS GOOD AS THE JUDGE BEING THERE. On 2026-08-27 six gates fired, none were answered,
both finished cells ran their full budget ungated, and nothing said so until the batch was over. The
run side now records that and stops the batch; this is the other half — one command that makes
answering a gate part of a turn instead of something to remember.

    python3 suite/gates.py            # what is open right now
    python3 suite/gates.py --wait     # block until a question appears, then print it
    python3 suite/gates.py --answer <name> <verdict.json>

A question is `<run_id>.<NNN>min.md`; it is answered by `<run_id>.<NNN>min.verdict` holding the same
inferred-usefulness JSON used for final campaign judgment. Each fixed deliverable is scored 0–100 on
its own merits and the average is compared with the elapsed share of the task.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import usefulness

GATE_DIR = Path(__file__).resolve().parent / "results" / "gates"


def open_questions() -> list[Path]:
    """Every asked question with no verdict beside it, oldest first."""
    if not GATE_DIR.is_dir():
        return []
    return sorted((q for q in GATE_DIR.glob("*min.md")
                   if not q.with_suffix(".verdict").is_file()),
                  key=lambda p: p.stat().st_mtime)


def unanswered() -> list[str]:
    """Gates that timed out — runs that went ahead UNGATED. The batch stops on these."""
    f = GATE_DIR / "UNANSWERED"
    return [ln.strip() for ln in f.read_text().splitlines() if ln.strip()] if f.is_file() else []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wait", type=int, nargs="?", const=3600, default=0,
                    help="block up to N seconds for a question to appear (default 3600)")
    ap.add_argument("--answer", nargs=2, metavar=("QUESTION", "VERDICT_JSON"))
    ap.add_argument("--print", action="store_true", help="print the oldest open question in full")
    args = ap.parse_args(argv)

    if args.answer:
        name, source = args.answer
        candidate = Path(source)
        raw = candidate.read_text() if candidate.is_file() else source
        verdict = usefulness.parse(raw)
        if verdict is None:
            print("the verdict must be the inferred-usefulness JSON required by the gate rubric",
                  file=sys.stderr)
            return 2
        q = GATE_DIR / (name if name.endswith(".md") else f"{name}.md")
        if not q.is_file():
            print(f"no such question: {q}", file=sys.stderr)
            return 2
        q.with_suffix(".verdict").write_text(raw.rstrip() + "\n")
        print(f"answered {q.name}: usefulness {verdict['usefulness']:g}%")
        return 0

    deadline = time.time() + args.wait
    while True:
        qs = open_questions()
        if qs or time.time() >= deadline:
            break
        time.sleep(5)

    stale = unanswered()
    if stale:
        print(f"UNGATED RUNS — {len(stale)} gate(s) timed out and their runs continued unjudged:")
        for n in stale:
            print(f"  {n}")
        print()
    if not qs:
        print("(no open questions)")
        return 0
    print(f"{len(qs)} open:")
    for q in qs:
        print(f"  {q.name}")
    if args.print or args.wait:
        print("\n" + "=" * 78 + f"\n{qs[0].name}\n" + "=" * 78)
        print(qs[0].read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
