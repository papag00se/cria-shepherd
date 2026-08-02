#!/usr/bin/env python3
"""Ground truth for the phase-1 matrix: what is DONE, what is RUNNING, what is LEFT.

This exists because a goal whose progress is judged from the assistant's own narration inherits
whatever the assistant says. Mid-run I reported "Cell 5 running next" without having started it,
and nothing contradicted me for hours — the supervisor's only evidence was the sentence that was
wrong. The suite already refuses to score a task on the model's claim; a goal deserves the same
treatment.

Everything here is read from disk and the process table. Nothing is read from a conversation.

    python3 suite/phase1_status.py          # human-readable
    python3 suite/phase1_status.py --json   # machine-readable; exit 0 only when phase 1 is COMPLETE

Exit codes: 0 = complete, 1 = work remains, 2 = a run is currently in flight.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"
WALK = SUITE.parent / "docs" / "audits" / "phase1-walk.md"

TASKS = ["ada-handles", "handles-go", "handles-rust", "handles-node",
         "handles-ruby", "handles-php", "handles-java"]


def rows():
    if not RESULTS.exists():
        return []
    out = []
    for line in RESULTS.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if str(r.get("note", "")).startswith("P1-"):
            out.append(r)
    return out


def in_flight():
    """A suite run actually executing right now — the process table, not a claim about it."""
    try:
        ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        return None
    for line in ps.splitlines():
        parts = line.split()
        # argv[1] must BE the runner. Matching "suite/run.py" anywhere in the line matches the
        # shell that is asking the question — any command whose text merely mentions the runner,
        # including this file being edited — and the oracle then reports a phantom run forever and
        # blocks every action. Same self-match that makes `pkill -f` kill its own caller.
        if len(parts) >= 4 and parts[1].endswith("suite/run.py") and "--task" in parts:
            return parts[parts.index("--task") + 1]
    return None


def walked():
    """Cells whose walk has been WRITTEN DOWN. A walk that exists only in a chat message is not a
    walk anyone can check later."""
    if not WALK.exists():
        return set()
    text = WALK.read_text()
    return {t for t in TASKS if f"## {t}" in text}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    done = {}
    for r in rows():
        done[r["task"]] = r          # last row per task wins
    walk = walked()
    running = in_flight()

    state = []
    for t in TASKS:
        r = done.get(t)
        state.append({
            "task": t,
            "scored": r is not None,
            "score": (r or {}).get("score"),
            "max": (r or {}).get("max_score"),
            "walked": t in walk,
            "running": running == t,
            "complete": r is not None and t in walk,
        })
    # The two kinds of "not done" need DIFFERENT actions, and conflating them told me to spend 30
    # minutes re-running a cell that was already scored and merely needed writing up.
    to_walk = [s["task"] for s in state if s["scored"] and not s["walked"]]
    to_run = [s["task"] for s in state if not s["scored"]]
    remaining = to_walk + to_run
    complete = not remaining

    if args.json:
        print(json.dumps({"complete": complete, "running": running,
                          "next_action": ("wait" if running else "walk" if to_walk
                                          else "run" if to_run else "none"),
                          "to_walk": to_walk, "to_run": to_run, "cells": state}, indent=1))
    else:
        print(f"{'task':16s} {'scored':>7s} {'score':>7s} {'walked':>7s}  state")
        print("-" * 58)
        for s in state:
            sc = f"{s['score']:.0f}/{s['max']:.0f}" if s["scored"] else "—"
            mark = ("RUNNING" if s["running"] else
                    "complete" if s["complete"] else
                    "needs walk" if s["scored"] else "not started")
            print(f"{s['task']:16s} {'yes' if s['scored'] else 'no':>7s} {sc:>7s} "
                  f"{'yes' if s['walked'] else 'no':>7s}  {mark}")
        print()
        if running:
            print(f"IN FLIGHT: {running} — do not start another run, and do not edit code")
        elif complete:
            print("PHASE 1 COMPLETE")
        elif to_walk:
            # WALKING COMES FIRST: a scored cell already holds its evidence, and walking costs no
            # GPU. Starting another run instead buries the capture under a newer one.
            t = to_walk[0]
            cap = (done[t] or {}).get("capture_dir", "(see results.jsonl)")
            print(f"WORK REMAINS — walk {len(to_walk)}, run {len(to_run)}")
            print(f"NEXT: WALK {t} — read {cap} EVERY call start to finish (a walk is reading, "
                  f"not grepping/sampling/counting), then write "
                  f"'## {t}' into docs/audits/phase1-walk.md")
        else:
            t = to_run[0]
            print(f"WORK REMAINS — walk 0, run {len(to_run)}")
            print(f"NEXT: RUN python3 suite/run.py --task {t} --model ternary-bonsai "
                  f"--harness codex --planner off --note \"P1 {t} $(git rev-parse --short HEAD)\"")

    sys.exit(2 if running else (0 if complete else 1))


if __name__ == "__main__":
    main()
