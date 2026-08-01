#!/usr/bin/env python3
"""Ground truth for the LANGUAGE LADDER: which model is up, what it scored, what happens next.

The ladder's rule is simple and its state is entirely on disk: one language, one model at a time,
that model repeats until it scores full marks, then the next model starts. Nothing here is read from
a conversation — a goal that judges its own progress from the assistant's narration inherits whatever
the assistant says, and that has already cost a day: "Cell 5 running next" was written for a run that
was never started, and nothing contradicted it for hours.

    python3 suite/ladder_status.py           # human-readable
    python3 suite/ladder_status.py --json     # machine-readable

Exit codes: 0 = the language is complete, 1 = work remains, 2 = a run is in flight, 3 = blocked.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"
WALK = SUITE.parent / "docs" / "audits" / "ladder-walk.md"

NOTE_PREFIX = "LADDER"
MILESTONE_MINUTES = 15

# The ladder's order, and the ONE place it is defined. Dense first, largest first — a proven-capable
# model failing means cria is at fault, which is the cheaper thing to debug; a 760M-active model
# failing tells you almost nothing until the big ones pass. Flip `reverse=` in your head by editing
# this list; nothing else reads an ordering.
#
# `planner` is the OPERATOR'S HYPOTHESIS, not a measured result: dense models appear to cope with the
# planner off, MoEs appear to need it on. It is recorded here so the ladder GENERATES the evidence
# rather than assuming it — every row carries the setting it ran under.
LADDER = [
    # name,              params,        kind,    planner
    ("ternary-bonsai",   "27B",         "dense", "off"),
    ("gemma4",           "12B",         "dense", "off"),
    ("qwythos",          "9B",          "dense", "off"),
    ("qwopus",           "9B",          "dense", "off"),
    ("ornith",           "9B",          "dense", "off"),
    ("fabliq",           "8B",          "dense", "off"),
    ("mellum2",          "12B/A2.5B",   "moe",   "on"),
    ("nemotron-elastic", "12B/A2B",     "moe",   "on"),
    ("zaya1",            "8.4B/A760M",  "moe",   "on"),
]
# lfm25 is deliberately absent: the systemd unit exists but the model has no entry in
# ~/.config/llama-fleet/models.toml, so starting it cannot work. Add it back when that is fixed.

LANGUAGES = [("python", "ada-handles")]     # the ladder walks ONE language at a time, in this order

# A model walked this many times with no new cria fault found is recorded BLOCKED and the ladder
# moves on. It does NOT count as a pass and the language does not complete — the point is that a
# wedged model must not silently eat days of a long-running goal.
BLOCKED_AFTER = 5


def rows(task):
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
        if str(r.get("note", "")).startswith(NOTE_PREFIX) and r.get("task") == task:
            out.append(r)
    return out


def in_flight():
    """A suite run executing RIGHT NOW — the process table, not a claim about it."""
    try:
        ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True,
                            timeout=30).stdout
    except Exception:  # noqa: BLE001
        return None
    for line in ps.splitlines():
        parts = line.split()
        # argv[1] must BE the runner. Matching "suite/run.py" anywhere in the line also matches the
        # shell asking the question, and this file while it is being edited — the oracle then reports
        # a phantom run forever and blocks every action. Same self-match that makes `pkill -f` kill
        # its own caller.
        if len(parts) >= 4 and parts[1].endswith("suite/run.py") and "--model" in parts:
            return parts[parts.index("--model") + 1]
    return None


def walked_runs():
    """Run ids whose walk has been WRITTEN DOWN. A walk that exists only in a chat message is not a
    walk anyone can check later, and is exactly what a compaction deletes."""
    if not WALK.exists():
        return set()
    text = WALK.read_text()
    return {line.split("## ", 1)[1].strip()
            for line in text.splitlines() if line.startswith("## ")}


def state_for(task):
    walked = walked_runs()
    running = in_flight()
    by_model = {}
    for r in rows(task):
        by_model.setdefault(r["model"], []).append(r)

    out = []
    for name, params, kind, planner in LADDER:
        rs = sorted(by_model.get(name, []), key=lambda r: r.get("started") or 0)
        passed = any((r.get("score") or 0) >= (r.get("max_score") or 4) for r in rs)
        last = rs[-1] if rs else None
        unwalked = [r for r in rs if r["run_id"] not in walked
                    and (r.get("score") or 0) < (r.get("max_score") or 4)]
        out.append({
            "model": name, "params": params, "kind": kind, "planner": planner,
            "attempts": len(rs),
            "best": max([(r.get("score") or 0) for r in rs], default=None),
            "last_score": (last or {}).get("score"),
            "last_run_id": (last or {}).get("run_id"),
            "last_terminal": (last or {}).get("terminal"),
            "passed": passed,
            "needs_walk": bool(unwalked) and not passed,
            "next_walk": unwalked[0]["run_id"] if unwalked else None,
            "next_walk_capture": (unwalked[0].get("capture_dir") if unwalked else None),
            "blocked": (not passed) and len(rs) >= BLOCKED_AFTER and not unwalked,
            "running": running == name,
        })
    return out, running


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--language", default=LANGUAGES[0][0])
    args = ap.parse_args()

    task = dict(LANGUAGES)[args.language]
    cells, running = state_for(task)

    # WALK BEFORE RUN, always: a scored run already holds its evidence and walking costs no GPU,
    # while starting another run buries that capture under a newer one.
    to_walk = [c for c in cells if c["needs_walk"]]
    live = [c for c in cells if not c["passed"] and not c["blocked"]]
    complete = not live
    action, target = "none", None
    if running:
        action = "wait"
    elif to_walk:
        action, target = "walk", to_walk[0]
    elif live:
        action, target = "run", live[0]

    if args.json:
        print(json.dumps({"language": args.language, "task": task, "complete": complete,
                          "running": running, "next_action": action,
                          "target": target, "cells": cells}, indent=1))
    else:
        print(f"LANGUAGE LADDER — {args.language} ({task}), {MILESTONE_MINUTES} min per deliverable\n")
        print(f"{'model':18s} {'params':12s} {'kind':6s} {'plan':5s} {'tries':>5s} "
              f"{'best':>5s}  state")
        print("-" * 74)
        for c in cells:
            st = ("RUNNING" if c["running"] else "PASSED 4/4" if c["passed"] else
                  "BLOCKED" if c["blocked"] else "needs walk" if c["needs_walk"] else
                  "not started" if not c["attempts"] else "ready to rerun")
            best = f"{c['best']:.0f}" if c["best"] is not None else "—"
            print(f"{c['model']:18s} {c['params']:12s} {c['kind']:6s} {c['planner']:5s} "
                  f"{c['attempts']:5d} {best:>5s}  {st}")
        print()
        if running:
            print(f"IN FLIGHT: {running} — do not start another run, and do not edit cria or its "
                  f"prompts (they load lazily; an edit changes the RUNNING system)")
        elif complete:
            blocked = [c["model"] for c in cells if c["blocked"]]
            print(f"{args.language.upper()} COMPLETE" if not blocked else
                  f"{args.language.upper()} DONE EXCEPT BLOCKED: {', '.join(blocked)} — "
                  f"not a pass, and the language is NOT finished")
        elif action == "walk":
            print(f"NEXT: WALK {target['next_walk']}")
            print(f"  read {target['next_walk_capture']} call by call — pair NNNN-*.prompt.txt "
                  f"(what was sent) with NNNN-*.reasoning.txt (what it made of it)")
            print(f"  then write '## {target['next_walk']}' into docs/audits/ladder-walk.md")
            print("  RUN any code a steer contains. A diagnosis that reads correct can still ship "
                  "a fix that cannot execute — that is how C1 was cleared wrongly.")
        else:
            print(f"NEXT: RUN {target['model']} ({target['params']} {target['kind']}, "
                  f"attempt {target['attempts'] + 1})")
            print(f"  python3 suite/run.py --task {task} --model {target['model']} "
                  f"--harness codex --planner {target['planner']} "
                  f"--milestone-minutes {MILESTONE_MINUTES} "
                  f'--note "{NOTE_PREFIX} {args.language} {target["model"]} $(git rev-parse --short HEAD)"')

    sys.exit(2 if running else 0 if complete else 1)


if __name__ == "__main__":
    main()
