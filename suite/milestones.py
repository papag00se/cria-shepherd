#!/usr/bin/env python3
"""Create, inspect, and answer inference checkpoints for live suite runs.

The runner freezes the workspace and waits at each interval. The campaign agent inspects that
snapshot with read-only tools and records an inferred usefulness percentage together with
`complete`, `continue`, or `stalled`:

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
from pathlib import Path

try:
    from . import workspace_evidence
except ImportError:
    import workspace_evidence


SUITE = Path(__file__).resolve().parent
ROOT = Path.home() / ".cria" / "suite" / "_milestones"
SYSTEM = SUITE / "prompts" / "milestone_judge.txt"
DECISIONS = {"complete", "continue", "stalled"}


def checkpoint_name(run_id: str, minute: int) -> str:
    return f"{run_id}.{minute:03d}min"


def create(run_id: str, minute: int, ws: Path, task_dir: Path,
           previous: list[dict] | None = None) -> Path:
    """Freeze one live workspace and return its checkpoint directory."""
    out = ROOT / checkpoint_name(run_id, minute)
    snapshot = out / "workspace"
    out.mkdir(parents=True, exist_ok=True)
    if snapshot.exists():
        shutil.rmtree(snapshot)
    shutil.copytree(ws, snapshot, symlinks=True)
    prompt = (task_dir / "prompt.txt").read_text(errors="replace").strip()
    seed = task_dir / "seed"
    baseline = workspace_evidence.tree(seed) if seed.is_dir() else "(empty baseline)"
    prior = "\n".join(
        f"{v['at_active_minutes']} min judgment: {v['usefulness_percent']}%, "
        f"{v['decision']}: {v['reason']}\nMaterial changes: {v.get('material_changes', 'not recorded')}\n"
        f"Prior frozen snapshot (inspect read-only): "
        f"{v['checkpoint']}/workspace" for v in (previous or [])) or "No earlier milestone judgment."
    packet = "\n".join([
        SYSTEM.read_text().strip(),
        "", "=" * 78, "",
        f"CHECKPOINT: {run_id} at {minute} active minutes", "",
        f"THE TASK THE CODER WAS GIVEN:\n{prompt}", "",
        f"BASELINE SEED DIRECTORY (inspect read-only):\n{seed}", "",
        f"BASELINE SEED TREE (before coder started):\n{baseline}", "",
        f"PRIOR MILESTONE JUDGMENTS (context, not score targets):\n{prior}", "",
        f"FROZEN WORKSPACE SNAPSHOT (inspect with read-only tools):\n{snapshot}", "",
        "COMPLETE FROZEN WORKSPACE TREE (all entries; symlinks are not followed):\n"
        f"{workspace_evidence.tree(snapshot)}", "",
    ])
    (out / "policy.json").write_text(json.dumps({"pacing_policy": "requirement-pace-15m-protected-30m-v2"}) + "\n")
    (out / "packet.txt").write_text(packet)
    return out


def parse(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("decision") not in DECISIONS:
        return None
    usefulness = value.get("usefulness_percent")
    reason = value.get("reason")
    evidence = value.get("evidence")
    changes = value.get("material_changes")
    if not isinstance(changes, str) or not changes.strip():
        return None
    if not isinstance(usefulness, int) or isinstance(usefulness, bool) or not 0 <= usefulness <= 100:
        return None
    if not isinstance(reason, str) or not reason.strip() or not isinstance(evidence, list) or not evidence:
        return None
    if not all(isinstance(item, str) and item.strip() for item in evidence):
        return None
    return {"usefulness_percent": usefulness, "decision": value["decision"],
            "reason": reason.strip(), "evidence": evidence, "material_changes": changes.strip()}


def parse_for_checkpoint(checkpoint: Path, text: str) -> dict | None:
    """New reviews require semantic requirement/pace evidence; old evidence stays readable.

    Code validates evidence shape, never counts task bullets or decides pace from percentages.
    """
    verdict = parse(text)
    if verdict is None or not (checkpoint / "policy.json").exists():
        return verdict
    value = json.loads(text)
    requirements = value.get("requirements")
    pace = value.get("pace_reason")
    if not isinstance(pace, str) or not pace.strip() or not isinstance(requirements, list) or not requirements:
        return None
    for item in requirements:
        if not isinstance(item, dict) or item.get("status") not in {"completed", "partial", "not_started"}:
            return None
        if any(not isinstance(item.get(key), str) or not item[key].strip()
               for key in ("requirement", "evidence")):
            return None
    verdict.update(requirements=requirements, pace_reason=pace.strip())
    return verdict


def verdict_path(checkpoint: Path) -> Path:
    return checkpoint / "verdict.json"


def wait(checkpoint: Path, poll_seconds: float = 2.0) -> dict:
    """Wait until the campaign agent records a valid inference judgment."""
    path = verdict_path(checkpoint)
    while True:
        if path.is_file():
            verdict = parse_for_checkpoint(checkpoint, path.read_text(errors="replace"))
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

    verdict = parse_for_checkpoint(checkpoint, sys.stdin.read())
    if verdict is None:
        raise SystemExit("expected usefulness_percent, decision complete|continue|stalled, reason, evidence, material_changes; new checkpoints also require requirements and pace_reason")
    verdict_path(checkpoint).write_text(json.dumps(verdict, indent=1) + "\n")
    print(f"{checkpoint.name}: {verdict['usefulness_percent']}% useful; {verdict['decision']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
