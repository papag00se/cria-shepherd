#!/usr/bin/env python3
"""The battery campaign's ONE source of truth — what has run, and what runs next.

Reads `suite/results/results.jsonl` and nothing else. Not a conversation, not a memory, not a
report someone typed. Whatever it prints under `NEXT:` is the next action; when a chat message and
this tool disagree, this tool is right. `docs/battery-goal.md` is the campaign it drives.

THE QUESTION: for four models across six tasks, what does the same model score with cria DRIVING
versus with cria only PLUMBING? Nothing in this project has ever measured what the assists are
worth, because there has never been a control.

ORDER IS PART OF THE DESIGN. The whole BASE arm completes before the first CRIA run is offered. A
phase then runs on one code state end to end; pair-by-pair invites a fix landing between the halves
of a pair, which voids the only comparison the campaign exists to make.

Exit codes: 0 campaign complete · 1 work remains · 2 a run is in flight.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"
WALK = SUITE.parent / "docs" / "audits" / "battery-walk.md"
NOTE_PREFIX = "BATTERY1"

MODELS = ("gemma4", "qwen35", "ternary-bonsai", "nemotron-elastic")
# Deliberately NOT ada-handles (already mined) and not the seven handles-* ports (one problem in
# seven languages — a portability question, not a variety one). See docs/task-battery.md.
TASKS = ("shipping-rates-py", "orders-api-py", "feed-pipeline-py",
         "missing-tests-py", "sqlite-inventory", "rust-toml-cli")
ARMS = ("BASE", "CRIA")          # order matters: the whole BASE arm first


def rows() -> list[dict]:
    if not RESULTS.exists():
        return []
    out = []
    for line in RESULTS.read_text().splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if str(r.get("note", "")).startswith(NOTE_PREFIX):
            out.append(r)
    return out


def cell(rs: list[dict], arm: str, model: str, task: str) -> dict | None:
    """The STANDING row for one matrix cell — superseded rows are evidence, not results."""
    for r in reversed(rs):
        if r.get("superseded"):
            continue
        note = str(r.get("note", ""))
        if r.get("model") == model and r.get("task") == task and f" {arm} " in f" {note} ":
            return r
    return None


def in_flight() -> str | None:
    """A live `suite/run.py`, found by reading /proc rather than pgrep — a pattern that matches this
    tool's own command line reports itself as the run it is looking for, which has happened."""
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            argv = [a for a in Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0") if a]
        except OSError:
            continue
        if argv and argv[0].endswith("python3") and any(a.endswith("suite/run.py") for a in argv):
            return " ".join(argv)
    return None


def walked(run_id: str) -> bool:
    return WALK.exists() and f"## {run_id}" in WALK.read_text()


def sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, cwd=SUITE.parent).stdout.strip() or "?"
    except OSError:
        return "?"


def score_of(r: dict | None) -> str:
    if not r:
        return "  — "
    return f"{int(r.get('score') or 0)}/{int(r.get('max_score') or 4)}"


def main() -> int:
    rs = rows()
    print(f"BATTERY CAMPAIGN — {len(MODELS)} models × {len(TASKS)} tasks × 2 arms "
          f"= {len(MODELS)*len(TASKS)*2} runs   (note prefix {NOTE_PREFIX})\n")
    print(f"{'task':<20}{'model':<19}{'BASE':>6}{'CRIA':>7}{'Δ':>5}")
    print("-" * 57)
    todo: list[tuple[str, str, str]] = []
    filled = 0
    for task in TASKS:
        for model in MODELS:
            b, c = cell(rs, "BASE", model, task), cell(rs, "CRIA", model, task)
            delta = ""
            if b and c:
                d = int(c.get("score") or 0) - int(b.get("score") or 0)
                delta = f"{d:+d}"
            print(f"{task:<20}{model:<19}{score_of(b):>6}{score_of(c):>7}{delta:>5}")
            filled += bool(b) + bool(c)
            # ONE entry per cell-pair: the next thing to run for this pair. Counting cells off
            # `todo` would report an empty campaign as half finished (24 of 48), which is why the
            # filled tally is counted directly instead of inferred.
            if not b:
                todo.append(("BASE", model, task))
            elif not c:
                todo.append(("CRIA", model, task))
    total = len(MODELS) * len(TASKS) * 2
    base_done = sum(1 for t in TASKS for m in MODELS if cell(rs, "BASE", m, t))
    print(f"\n{filled} of {total} cells filled   "
          f"(BASE arm {base_done}/{len(MODELS)*len(TASKS)})")

    live = in_flight()
    if live:
        print(f"\nIN FLIGHT: {live[:120]}")
        print("NEXT: WAIT — one run at a time, and do not edit cria/ or cria/prompts/ while it runs.")
        return 2

    # A CRIA run that LOST to its BASE twin is the campaign's whole point; walk it before running more.
    for task in TASKS:
        for model in MODELS:
            b, c = cell(rs, "BASE", model, task), cell(rs, "CRIA", model, task)
            if b and c and int(c.get("score") or 0) < int(b.get("score") or 0) \
                    and not walked(str(c.get("run_id"))):
                print(f"\nNEXT: WALK {c.get('run_id')}   "
                      f"(CRIA {score_of(c)} lost to BASE {score_of(b)} — cria made it worse)")
                print(f"      python3 suite/walk.py {str(c.get('capture_dir','')).split('/')[-1]} "
                      f"--out /tmp/walk-{model}-{task}")
                print(f"      python3 suite/reasoner_audit.py "
                      f"{str(c.get('capture_dir','')).split('/')[-1]} --bad")
                return 1

    if not todo:
        print("\nNEXT: NOTHING — campaign complete. Write the closing summary per docs/battery-goal.md.")
        return 0

    # BASE arm first, entirely. `todo` is built task-major, so sort by arm to enforce the phase.
    arm, model, task = sorted(todo, key=lambda t: ARMS.index(t[0]))[0]
    drive = "false" if arm == "BASE" else "true"
    remaining = sum(1 for t in todo if t[0] == arm)
    print(f"\nNEXT: RUN {arm} {model} {task}   ({remaining} left in the {arm} arm)")
    print(f"      python3 suite/battery_run.py --arm {arm} --model {model} --task {task}")
    print(f"      (sets [engagement] drive = {drive}, restarts cria, then runs — "
          f"note \"{NOTE_PREFIX} {arm} {model} {sha()}\")")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
