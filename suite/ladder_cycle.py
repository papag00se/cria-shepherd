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
import os
import re
import signal
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
        # A SUPERSEDED row measured a rung that was not the one running — a level-5 mechanism
        # leaking into level 4, say. It stays in the file as evidence and does NOT count as done,
        # so the worklist offers the cell again.
        if r.get("level") is None or r.get("superseded"):
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


def leaked_listeners() -> list[tuple[int, str, str]]:
    """Processes still LISTENING whose cwd is inside a suite workspace — a server a cell started and
    never stopped. Returns (pid, cwd, cmdline).

    SCOPED BY CWD, DELIBERATELY. The obvious version of this walks the listening ports and kills
    whatever holds one the next cell might want, and that is how a measurement harness comes to
    kill an operator's own services. A process is this run's to stop only if it is standing in this
    run's workspace; everything else on the machine is somebody else's and is left alone even when
    it is inconvenient.
    """
    out = []
    try:
        pids = {int(x) for x in re.findall(rb"pid=(\d+)",
                subprocess.run(["ss", "-ltnp"], capture_output=True).stdout)}
    except Exception:
        return out
    runs = (SUITE.parent / "runs").resolve()
    for pid in pids:
        try:
            cwd = Path(f"/proc/{pid}/cwd").resolve()
            if runs not in cwd.parents and cwd != runs:
                continue
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except (OSError, ValueError):
            continue
        out.append((pid, str(cwd), cmd.strip()))
    return out


def reap_leaked_listeners() -> None:
    """Stop servers a finished cell left listening, so the next cell does not inherit its port.

    Walked on the ladder run of 2026-08-24: a cell's own test fixture pinned port 8081, found it
    occupied, and went looking for something to kill — `fuser -k 8081/tcp`, then `kill -9` on two
    PIDs by number. Below level 2 nothing stops that, because the guard that refuses it lives in the
    write proxy. Cleaning up after ourselves removes the provocation; it does not remove the hazard,
    which is recorded in docs/audits/ladder-progress.md.
    """
    for pid, cwd, cmd in leaked_listeners():
        print(f"[ladder] reaping leaked listener pid={pid} cwd={cwd} :: {cmd[:90]}", flush=True)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                break
            time.sleep(1.0)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break


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
        reap_leaked_listeners()
        # The worklist is re-derived next pass, so a failed cell simply stays outstanding. Nothing
        # here decides to retry: a cell that keeps failing is a finding for the operator to read,
        # not a loop to spin in.
    print(f"[ladder] pass complete at {time.strftime('%H:%M:%S')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
