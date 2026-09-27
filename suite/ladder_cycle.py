#!/usr/bin/env python3
"""Run the engagement ladder: 6 levels x 5 models x 6 tasks, skipping what is already done.

RESUMABLE BY CONSTRUCTION. The worklist is derived from `suite/results/results.jsonl` on every pass,
so a kill, a crash, a reboot or an operator's Ctrl-C costs the cell in flight and nothing else. There
is no progress file to get out of step with reality, and no "start at cell N" flag to get wrong.

Grouped model-major because the GPU swap is per MODEL: all 36 of a model's cells run while it is
loaded, then the next model comes up. Within a model, level-major so a whole rung lands together and
the first comparison is available before the run finishes.

    python3 suite/ladder_cycle.py                 # run everything outstanding
    python3 suite/ladder_cycle.py --dry-run       # print the worklist and stop
    python3 suite/ladder_cycle.py --levels 0,5 --models phi4,ling3-tiny   # a sub-grid only
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

try:  # importable as suite.ladder_cycle and executable as suite/ladder_cycle.py
    from .run import RUNS_DIR
except ImportError:
    from run import RUNS_DIR

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"

LEVELS = (0, 1, 2, 3, 4, 5)
# 2026-09-27: nemotron-elastic, qwen35 and qwen38 left the battery (operator decision); K2-Horizon-7B,
# phi-4, Ling-3.0-tiny and Qwen3.8-9B-Distill joined, and defiant-fable entered. The report renders
# only this roster (plus gemma4's frozen row, the only gemma history); retired models are NAMED in
# the report and keep every row in results.jsonl / historical_ladder.json.
# Keys renamed 2026-09-27 (operator): ternary-bonsai-2 -> bonsai2, ornith15 -> ornith1.5,
# qwen38-distill -> qwen3.8_9b_distill, k2-horizon -> k2_horizon_7b. results.jsonl `model`
# fields were migrated with them; run_ids, archives and systemd units keep their names.
MODELS = ("gemma4-qat", "bonsai2", "defiant-fable", "ornith1.5",
          "k2_horizon_7b", "phi4", "ling3-tiny", "qwen3.8_9b_distill")
# CURRENT matrix only — a model here must be swappable and have canonical sampling.
# gemma4 (stock Q4_K_M) and ternary-bonsai (Bonsai 1) left on 2026-09-18 when their weights
# and units were deleted; like nemotron-elastic before them they stay VISIBLE in the reports
# through suite/historical_ladder.json, which is where their scores live. Retiring a model
# means dropping it from here, never deleting its history.
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


def worklist(levels=LEVELS, models=MODELS) -> list[tuple[int, str, str]]:
    have = done()
    return [(lvl, m, t) for m in models for lvl in levels for t in TASKS
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
    runs = RUNS_DIR.resolve()
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


def orphaned_harnesses() -> list[tuple[int, str, str]]:
    """Harness processes standing in a suite workspace whose parent is gone — (pid, cwd, cmdline).

    `run.py` launches codex with `start_new_session=True`, so a run that dies without reaching its
    own `stop_run()` leaves the harness ALIVE and detached. Walked on the ladder of 2026-08-25: cell
    75 was SIGKILLed at 06:04 and its codex was still running 28 minutes later, in the workspace of a
    cell that no longer existed, making calls to a single-slot model server while the NEXT cell was
    being measured on it. Nothing was listening, so the leaked-listener reaper could not see it.

    Scoped the same way and for the same reason: cwd inside `runs/` is what makes a process this
    run's to stop. A harness working in the CURRENT cell has a live parent and is left alone.
    """
    out = []
    runs = RUNS_DIR.resolve()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            if "codex" not in cmd:
                continue
            cwd = (entry / "cwd").resolve()
            if runs not in cwd.parents:
                continue
            ppid = 0
            for line in (entry / "status").read_text().splitlines():
                if line.startswith("PPid:"):
                    ppid = int(line.split()[1])
                    break
        except (OSError, ValueError):
            continue
        # A live run's harness has run.py as an ancestor; an orphan's parent has been reaped to init
        # or to the session leader. Only the parentless are ours to stop.
        if ppid <= 1 or not Path(f"/proc/{ppid}").exists():
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
    for pid, cwd, cmd in leaked_listeners() + orphaned_harnesses():
        print(f"[ladder] reaping pid={pid} cwd={cwd} :: {cmd[:90]}", flush=True)
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
    ap.add_argument("--levels", default=",".join(map(str, LEVELS)),
                    help="comma-separated rungs to run (default: all)")
    ap.add_argument("--models", default=",".join(MODELS),
                    help="comma-separated roster models to run (default: the whole roster)")
    args = ap.parse_args()
    levels = tuple(int(x) for x in args.levels.split(",") if x.strip())
    models = tuple(x.strip() for x in args.models.split(",") if x.strip())
    bad = [lvl for lvl in levels if lvl not in LEVELS] + [m for m in models if m not in MODELS]
    if bad:
        ap.error(f"not on the ladder: {bad}")

    total = len(levels) * len(models) * len(TASKS)
    if args.dry_run:
        todo = worklist(levels, models)
        print(f"[ladder] {total - len(todo)}/{total} already done; {len(todo)} to run", flush=True)
        for lvl, m, t in todo:
            print(f"  L{lvl}  {m:18s} {t}")
        return 0

    # RE-DERIVED EVERY ROUND, not once at startup. A cell can become outstanding again WHILE this
    # process runs: four level-4 cells were superseded mid-run on 2026-08-25 when a level-5 mechanism
    # was found leaking into them, and a list computed at launch could never have offered them again.
    # The gap was invisible from inside — the counter said 33 cells and the grid had eight holes.
    #
    # The round ends when the worklist stops shrinking, so a cell that keeps failing is reported and
    # left alone rather than retried forever: it is a finding for the operator to read, not a loop.
    seen_outstanding = None
    while True:
        todo = worklist(levels, models)
        if not todo:
            print(f"[ladder] {total}/{total} done at {time.strftime('%H:%M:%S')}", flush=True)
            return 0
        if seen_outstanding is not None and set(todo) == seen_outstanding:
            print(f"[ladder] {len(todo)} cell(s) still outstanding after a full round and none of "
                  f"them moved — stopping rather than retrying. Outstanding:", flush=True)
            for lvl, m, t in todo:
                print(f"  L{lvl}  {m:18s} {t}", flush=True)
            return 1
        seen_outstanding = set(todo)
        print(f"[ladder] {total - len(todo)}/{total} already done; {len(todo)} to run", flush=True)
        for i, (lvl, model, task) in enumerate(todo, 1):
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] ({i}/{len(todo)}) L{lvl} {task} x {model} — start", flush=True)
            rc = subprocess.run([sys.executable, str(SUITE / "battery_run.py"),
                                 "--level", str(lvl), "--model", model, "--task", task]).returncode
            print(f"[{time.strftime('%H:%M:%S')}] ({i}/{len(todo)}) L{lvl} {task} x {model} "
                  f"— exit {rc}", flush=True)
            reap_leaked_listeners()


if __name__ == "__main__":
    raise SystemExit(main())
