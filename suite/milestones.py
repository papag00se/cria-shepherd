#!/usr/bin/env python3
"""Create, inspect, and answer inference checkpoints for live suite runs.

The runner freezes the workspace and waits at each interval. The campaign agent inspects that
snapshot with read-only tools and records `complete`, `continue`, or `stalled`:

    python3 suite/milestones.py pending
    python3 suite/milestones.py emit <checkpoint>
    printf '%s' '<JSON>' | python3 suite/milestones.py record <checkpoint>
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import tomllib
from pathlib import Path

import workspace_evidence


SUITE = Path(__file__).resolve().parent
ROOT = Path.home() / ".cria" / "suite" / "_milestones"
SYSTEM = SUITE / "prompts" / "milestone_judge.txt"
TASK_STATES = {"complete", "partial", "missing"}


def checkpoint_name(run_id: str, minute: int) -> str:
    return f"{run_id}.{minute:03d}min"


def create(run_id: str, minute: int, ws: Path, task_dir: Path) -> Path:
    """Freeze one live workspace and return its checkpoint directory."""
    out = ROOT / checkpoint_name(run_id, minute)
    snapshot = out / "workspace"
    out.mkdir(parents=True, exist_ok=True)
    if snapshot.exists():
        shutil.rmtree(snapshot)
    shutil.copytree(ws, snapshot, symlinks=True)
    prompt = (task_dir / "prompt.txt").read_text(errors="replace").strip()
    meta = tomllib.loads((task_dir / "meta.toml").read_text())
    task_count = meta.get("budget_intervals")
    if not isinstance(task_count, int) or isinstance(task_count, bool) or task_count < 2:
        raise RuntimeError("milestone pacing requires at least two task slots")
    (out / "task-count.txt").write_text(f"{task_count}\n")
    packet = "\n".join([
        SYSTEM.read_text().strip(),
        "", "=" * 78, "",
        f"CHECKPOINT: {run_id} at {minute} active minutes", "",
        f"TASK SLOTS: {task_count}. Infer exactly {task_count} substantive task items from the task text; metadata supplies only this pacing count, never their content.", "",
        f"THE TASK THE CODER WAS GIVEN:\n{prompt}", "",
        f"FROZEN WORKSPACE SNAPSHOT (inspect with read-only tools):\n{snapshot}", "",
        "COMPLETE FROZEN WORKSPACE TREE (all entries; symlinks are not followed):\n"
        f"{workspace_evidence.tree(snapshot)}", "",
    ])
    (out / "packet.txt").write_text(packet)
    return out


def parse(text: str, *, expected_tasks: int) -> dict | None:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    reason = value.get("reason")
    tasks = value.get("tasks")
    if not isinstance(reason, str) or not reason.strip() or not isinstance(tasks, list):
        return None
    if len(tasks) != expected_tasks:
        return None
    for task in tasks:
        if not isinstance(task, dict) or task.get("state") not in TASK_STATES:
            return None
        if not all(isinstance(task.get(key), str) and task[key].strip()
                   for key in ("name", "evidence")):
            return None
    return {"reason": reason.strip(), "tasks": tasks}


def verdict_path(checkpoint: Path) -> Path:
    return checkpoint / "verdict.json"


def _expected_tasks(checkpoint: Path) -> int:
    return int((checkpoint / "task-count.txt").read_text().strip())


def wait(checkpoint: Path, poll_seconds: float = 2.0) -> dict:
    """Wait until the campaign agent records a valid inference judgment."""
    path = verdict_path(checkpoint)
    expected_tasks = _expected_tasks(checkpoint)
    while True:
        if path.is_file():
            verdict = parse(path.read_text(errors="replace"), expected_tasks=expected_tasks)
            if verdict is not None:
                return verdict
        time.sleep(poll_seconds)


def pending() -> list[Path]:
    if not ROOT.is_dir():
        return []
    return sorted((p for p in ROOT.iterdir()
                   if p.is_dir() and (p / "packet.txt").is_file()
                   and not verdict_path(p).is_file()), key=lambda p: p.stat().st_mtime)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pending")
    emit = sub.add_parser("emit")
    emit.add_argument("checkpoint")
    record = sub.add_parser("record")
    record.add_argument("checkpoint")
    args = ap.parse_args()

    if args.cmd == "pending":
        questions = pending()
        for path in questions:
            print(path.name)
        if not questions:
            print("(nothing pending)")
        return 0

    checkpoint = ROOT / args.checkpoint
    if not checkpoint.is_dir():
        raise SystemExit(f"no such checkpoint: {checkpoint}")
    if args.cmd == "emit":
        print((checkpoint / "packet.txt").read_text())
        return 0

    verdict = parse(sys.stdin.read(), expected_tasks=_expected_tasks(checkpoint))
    if verdict is None:
        raise SystemExit("expected reason and exactly the configured number of typed task judgments")
    verdict_path(checkpoint).write_text(json.dumps(verdict, indent=1) + "\n")
    complete = sum(task["state"] == "complete" for task in verdict["tasks"])
    print(f"{checkpoint.name}: {complete}/{len(verdict['tasks'])} tasks complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
