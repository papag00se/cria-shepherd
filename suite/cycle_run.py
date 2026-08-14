#!/usr/bin/env python3
"""Drive one CYCLE of the 100% campaign: every model against every task, one cell at a time.

`battery_status.py` hands out ONE cell and stops, which is right for a campaign that has never run
before. This campaign runs the same matrix over and over — run, walk, rank, fix, run again — so the
thing that has to survive is the LOOP, and it has to survive a dead terminal, a lost session and a
killed cell. That is all this file is: the loop, in the repo, importing the matrix from the one
place that defines it.

    python3 suite/cycle_run.py                 # the whole 24-cell CRIA arm, from the top
    python3 suite/cycle_run.py --start 9       # resume at cell 9 after a kill
    python3 suite/cycle_run.py --dry-run       # print the cell order and exit

NO TIMEOUT OF ITS OWN. The suite already owns the wall clock — 15 minutes per deliverable, read
from each task's `meta.toml` — and a second one layered on top does not bound anything, it only
kills the long cells. A `timeout 3000` here once killed `orders-api-py` at 52 minutes of its own
60-minute wall while it sat at 3 of 4 deliverables: no archive, no row, no evidence, and the rerun
finished in 21 minutes at 4 of 4. The only reason to stop a cell early is the operator killing it.

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


def cells() -> list[tuple[str, str]]:
    """Task-major, model-minor. A whole language finishes before the next one starts, so a cycle
    interrupted halfway still says something complete about the languages it reached."""
    return [(t, m) for t in TASKS for m in MODELS]


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
    args = ap.parse_args()

    order = cells()
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
