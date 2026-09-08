#!/usr/bin/env python3
"""Drive one CYCLE of the 100% campaign: every model against every task, one cell at a time.

`battery_status.py` hands out ONE cell and stops, which is right for a campaign that has never run
before. This campaign runs the same matrix over and over — run, walk, rank, fix, run again — so the
thing that has to survive is the LOOP, and it has to survive a dead terminal, a lost session and a
killed cell. That is all this file is: the loop, in the repo, importing the matrix from the one
place that defines it.

    python3 suite/cycle_run.py                 # the whole 24-cell CRIA arm, from the top
    python3 suite/cycle_run.py --start 9       # resume at cell 9 after a kill
    python3 suite/cycle_run.py --models ornith15 qwen35  # selected complete model rows
    python3 suite/cycle_run.py --dry-run       # print the cell order and exit

NO TIMEOUT OF ITS OWN. The suite already owns the wall clock — 15 minutes per budget interval, read
from each task's `meta.toml` — and a second one layered on top does not bound anything, it only
kills the long cells. A `timeout 3000` here once killed `orders-api-py` at 52 minutes of its own
60-minute wall: no archive, no row, no evidence, and the rerun finished in 21 minutes. The only
reason to stop a cell early is the operator killing it.

Nothing here refreshes a report. `suite/run.py` already rewrites both grids as its last act, and a
second refresh from out here is a copy of a fact with its own way of going stale.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

SUITE = Path(__file__).resolve().parent
sys.path.insert(0, str(SUITE))
from battery_status import MODELS, TASKS  # noqa: E402  — one definition of the matrix, imported

LOG = SUITE.parent / "docs" / "audits" / "cycle-run.log"


def cells(models=MODELS) -> list[tuple[str, str]]:
    """MODEL-major, task-minor: one model is loaded, then taken through every language.

    This was task-major until 2026-08-16, on the reasoning that a whole language finishing meant a
    half cycle still said something complete about the languages it reached. Operator's call, and
    the grid is the argument: it is model-ROWS by language-COLUMNS, and the operator reads it by
    model. Task-major fills columns, so eight cells in you have two complete languages and four
    models each a third measured — no row you can read. Model-major fills a row at a time, which is
    the unit the report is actually read in.

    The swap cost, timed directly rather than inferred: two real `swap_model` calls on this box took
    10.6 s (into gemma4's 12B) and 70.2 s (into ternary-bonsai's 27B), mean 40.4 s. Twenty-four loads
    is ~16 minutes a cycle; four is under three. It is not the headline — 13 minutes off eleven hours
    — but it is free.

    AND IT DOES NOT COME OUT OF A CELL'S CLOCK, which is worth writing down because it is the first
    thing to suspect: `run.py` calls `swap_model` at line 336 and sets `t0` well after it, past
    `configure_cria` and the workspace seed, and `swap_model` blocks on `wait_health`. So a 70-second
    model load is charged to the driver, never to the model's fifteen-minute milestone floor.

    The part that is not measured in minutes: every swap is a window where cria's endpoint is down or
    still loading, and a leftover harness session from the previous cell POSTs into it. Every 503 and
    every `connection refused` in the campaign's logs sits in one of those windows (cycle 2's walk,
    the 12x503 entry). Four of those windows instead of twenty-four is worth having on its own."""
    return [(t, m) for m in models for t in TASKS]


def note(line: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"[{stamp}] {line}\n")
    print(f"[{stamp}] {line}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="CRIA", choices=("BASE", "CRIA"))
    ap.add_argument("--start", type=int, default=1, help="1-based cell number to resume at")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--models", nargs="+", choices=MODELS,
                    help="run complete rows for only these models, in the supplied order")
    args = ap.parse_args()

    order = cells(args.models or MODELS)
    if args.dry_run:
        for i, (t, m) in enumerate(order, 1):
            print(f"{i:>3}  {t:<20}{m}")
        return 0

    for i, (task, model) in enumerate(order, 1):
        if i < args.start:
            continue
        note(f"({i}/{len(order)}) {task} x {model} — start")
        rc = subprocess.run([sys.executable, str(SUITE / "battery_run.py"),
                             "--arm", args.arm, "--model", model, "--task", task]).returncode
        note(f"({i}/{len(order)}) {task} x {model} — exit {rc}")
    note(f"CYCLE COMPLETE — {len(order)} cells, arm {args.arm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
