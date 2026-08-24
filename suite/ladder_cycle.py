#!/usr/bin/env python3
"""Run the engagement ladder: 6 levels x 4 models x 6 tasks, skipping what is already done.

RESUMABLE BY CONSTRUCTION. The worklist is derived from `suite/results/results.jsonl` on every pass,
so a kill, a crash, a reboot or an operator's Ctrl-C costs the cell in flight and nothing else. There
is no progress file to get out of step with reality, and no "start at cell N" flag to get wrong.

Grouped model-major because the GPU swap is per MODEL: all 36 of a model's cells run while it is
loaded, then the next model comes up. Within a model, level-major so a whole rung lands together and
the first comparison is available before the run finishes.

    python3 suite/ladder_cycle.py                 # run everything outstanding
    python3 suite/ladder_cycle.py --dry-run       # print the worklist and stop
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"

LEVELS = (0, 1, 2, 3, 4, 5)
MODELS = ("gemma4", "qwen35", "ternary-bonsai", "nemotron-elastic")
TASKS = ("shipping-rates-rb", "cart-billing-go", "orders-api-py",
         "feed-pipeline-java", "handles-cli-node", "rust-toml-cli")


def done() -> set[tuple[int, str, str]]:
    """(level, model, task) already on disk. A cell that produced a row COUNTS, whatever it scored —
    a level-0 cell that died in nine seconds on a template 400 is the measurement, not a failure to
    retry until it looks better."""
    out: set[tuple[int, str, str]] = set()
    if not RESULTS.exists():
        return out
    for line in RESULTS.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("level") is None:
            continue
        try:
            out.add((int(r["level"]), r.get("model", ""), r.get("task", "")))
        except (TypeError, ValueError):
            continue
    return out


def worklist() -> list[tuple[int, str, str]]:
    have = done()
    return [(lvl, m, t) for m in MODELS for lvl in LEVELS for t in TASKS
            if (lvl, m, t) not in have]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    todo = worklist()
    total = len(LEVELS) * len(MODELS) * len(TASKS)
    print(f"[ladder] {total - len(todo)}/{total} already done; {len(todo)} to run", flush=True)
    if args.dry_run:
        for lvl, m, t in todo:
            print(f"  L{lvl}  {m:18s} {t}")
        return 0

    for i, (lvl, model, task) in enumerate(todo, 1):
        stamp = time.strftime("%H:%M:%S")
        print(f"[{stamp}] ({i}/{len(todo)}) L{lvl} {task} x {model} — start", flush=True)
        rc = subprocess.run([sys.executable, str(SUITE / "battery_run.py"),
                             "--level", str(lvl), "--model", model, "--task", task]).returncode
        print(f"[{time.strftime('%H:%M:%S')}] ({i}/{len(todo)}) L{lvl} {task} x {model} — exit {rc}",
              flush=True)
        # The worklist is re-derived next pass, so a failed cell simply stays outstanding. Nothing
        # here decides to retry: a cell that keeps failing is a finding for the operator to read,
        # not a loop to spin in.
    print(f"[ladder] pass complete at {time.strftime('%H:%M:%S')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
