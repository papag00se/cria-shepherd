#!/usr/bin/env python3
"""Fresh, independent 10-active-minute usefulness reports; these never control run duration."""
from __future__ import annotations
import json, shutil, sys, time
from pathlib import Path
try:
    from . import workspace_evidence
except ImportError:
    import workspace_evidence

SUITE = Path(__file__).resolve().parent
ROOT = Path.home() / ".cria" / "suite" / "_progress"
SYSTEM = SUITE / "prompts" / "progress_judge.txt"


def create(run_id: str, minute: int, ws: Path, task_dir: Path, prior: list[dict]) -> Path:
    out = ROOT / f"{run_id}.{minute:03d}min"
    out.mkdir(parents=True, exist_ok=True)
    snap = out / "workspace"
    if snap.exists(): shutil.rmtree(snap)
    shutil.copytree(ws, snap, symlinks=True)
    baseline = task_dir / "seed"
    baseline_tree = workspace_evidence.tree(baseline) if baseline.is_dir() else "(empty baseline)"
    prompt = (task_dir / "prompt.txt").read_text(errors="replace").strip()
    prev = "\n\n".join(f"{r['minute']} min judgment: {r['verdict']}\n"
                        f"Prior frozen snapshot (inspect read-only): {r['checkpoint']}/workspace"
                        for r in prior) or "No earlier report."
    packet = "\n".join([SYSTEM.read_text().strip(), f"REPORT: {run_id} at {minute} active minutes",
        f"TASK:\n{prompt}", f"BASELINE DIRECTORY (inspect read-only): {baseline}",
        f"BASELINE TREE (before coder started):\n{baseline_tree}",
        f"PRIOR INDEPENDENT REPORT JUDGMENTS:\n{prev}",
        f"CURRENT FROZEN SNAPSHOT: {snap}",
        f"COMPLETE CURRENT TREE:\n{workspace_evidence.tree(snap)}"])
    (out / "packet.txt").write_text(packet)
    return out


def parse(text: str) -> dict | None:
    try: v = json.loads(text)
    except (TypeError, json.JSONDecodeError): return None
    if not isinstance(v, dict): return None
    score, reason, evidence = v.get("usefulness_percent"), v.get("reason"), v.get("evidence")
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100: return None
    if not isinstance(reason, str) or not reason.strip() or not isinstance(evidence, list) or not evidence: return None
    if not all(isinstance(x, str) and x.strip() for x in evidence): return None
    return {"usefulness_percent": score, "reason": reason.strip(), "evidence": evidence}


def wait(path: Path, poll_seconds: float = 2.0) -> dict:
    verdict_file = path / "verdict.json"
    while True:
        if verdict_file.is_file():
            verdict = parse(verdict_file.read_text(errors="replace"))
            if verdict is not None: return verdict
        time.sleep(poll_seconds)


def pending() -> list[Path]:
    if not ROOT.is_dir(): return []
    return sorted(p for p in ROOT.iterdir() if p.is_dir() and (p / "packet.txt").is_file()
                  and not (p / "verdict.json").is_file())


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pending")
    emit = sub.add_parser("emit"); emit.add_argument("checkpoint")
    record = sub.add_parser("record"); record.add_argument("checkpoint")
    args = ap.parse_args()
    if args.cmd == "pending":
        paths = pending()
        for p in paths: print(p.name)
        if not paths: print("(nothing pending)")
        return 0
    path = ROOT / args.checkpoint
    if not path.is_dir(): raise SystemExit(f"no such report: {path}")
    if args.cmd == "emit": print((path / "packet.txt").read_text()); return 0
    verdict = parse(sys.stdin.read())
    if verdict is None: raise SystemExit("expected usefulness_percent, reason, evidence")
    (path / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    print(f"{path.name}: {verdict['usefulness_percent']}% useful")
    return 0

if __name__ == "__main__": raise SystemExit(main())
