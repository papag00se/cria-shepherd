#!/usr/bin/env python3
"""Prepare and record an independent usefulness judgment for a finished cell.

The judge reads the task and delivered workspace with read-only tools and infers the percentage of
usefulness actually delivered. `--emit` writes the packet; `--record` stores the judgment. The
percentage is holistic: no task-specific executable grades or aggregate mechanical measures
participate in this path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import workspace_evidence


SUITE = Path(__file__).resolve().parent
ROOT = SUITE.parent
RESULTS = SUITE / "results" / "results.jsonl"
try:  # the one locked reader/writer of results.jsonl
    from . import results_store as _rs
except ImportError:
    import results_store as _rs


SYSTEM = SUITE / "prompts" / "usefulness_judge.txt"
# The stop-looking line, in THIS judge's schema. See the call site.
ANSWER_NOW = ('You have inspected enough. Answer NOW with ONLY the JSON object: '
              '{"usefulness_percent": <integer from 0 through 100>, '
              '"reason": "<two evidence-based sentences>", '
              '"evidence": ["<specific inspected fact>"]}')


def evidence(row: dict) -> str:
    """Everything the judge is allowed to see: the task, the delivered workspace tree and how the session ended."""
    task_dir = SUITE / "tasks" / row["task"]
    ws = Path(row.get("archive") or "") / "workspace"
    prompt = (task_dir / "prompt.txt").read_text(errors="replace").strip()
    lines = [f"THE TASK THE CODER WAS GIVEN:\n{prompt}", "",
             f"WORKSPACE ARCHIVE (inspect it with read-only tools):\n{ws}", "",
             "COMPLETE WORKSPACE TREE (all entries; symlinks are not followed):\n"
             f"{workspace_evidence.tree(ws)}"]
    lines += ["", f"HOW THE SESSION ENDED: {row.get('terminal')} after {row.get('calls')} model "
                  f"calls and {round((row.get('wall_seconds') or 0) / 60, 1)} minutes."]
    return "\n".join(lines)


def parse(text: str) -> dict | None:
    """The judge's JSON, however it wrapped it. None when there is no usable verdict."""
    t = (text or "").strip()
    if "```" in t:
        t = t.split("```")[1].lstrip("json").strip() if len(t.split("```")) > 1 else t
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        d = json.loads(t[i:j + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    usefulness = d.get("usefulness_percent")
    reason = d.get("reason")
    evidence = d.get("evidence")
    if not isinstance(usefulness, int) or isinstance(usefulness, bool) or not 0 <= usefulness <= 100:
        return None
    if not isinstance(reason, str) or not reason.strip() or not isinstance(evidence, list) or not evidence:
        return None
    if not all(isinstance(item, str) and item.strip() for item in evidence):
        return None
    return {"usefulness_percent": usefulness, "reason": reason.strip(), "evidence": evidence}


VERDICTS = Path.home() / ".cria" / "test-runs" / "outputs" / "usefulness"


def verdict_path(run_id: str) -> Path:
    return VERDICTS / f"{run_id}.json"


def pending(rows: list[dict]) -> list[dict]:
    """Rows whose archived workspace still exists and that have no verdict, computed from disk every time."""
    return [r for r in rows
            if not r.get("superseded")
            and (Path(r.get("archive") or "") / "workspace").is_dir()
            and not verdict_path(r["run_id"]).exists()]


def record(run_id: str, verdict: dict) -> dict:
    """Store an inferred usefulness percentage and attach its provenance to the row."""
    normalized = parse(json.dumps(verdict))
    if normalized is None:
        raise ValueError("final judgment requires usefulness_percent, reason, and evidence")
    v = {**normalized, "judged_by": verdict.get("judged_by", "campaign agent, full toolset")}
    with _rs.rewrite(RESULTS) as rows:   # one locked read-modify-write: no torn read, no lost concurrent append
        row = next((r for r in rows if r.get("run_id") == run_id), None)
        if row is None:
            raise SystemExit(f"no row for {run_id}")
        VERDICTS.mkdir(parents=True, exist_ok=True)
        verdict_path(run_id).write_text(json.dumps(v, indent=1))
        for i, r in enumerate(rows):
            if r.get("run_id") == run_id:
                r = dict(r)
                r.pop("usefulness_judgment", None)
                r.update({"usefulness_percent": v["usefulness_percent"],
                          "usefulness_reason": v.get("reason", ""),
                          "usefulness_model": v["judged_by"]})
                rows[i] = r
    try:
        import battery_status
        battery_status.write_report(battery_status.rows(all_rows=True))
    except Exception as exc:  # noqa: BLE001 — the verdict is already recorded; the report is refreshed again by the next one
        print(f"report not refreshed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return v


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("pending", help="cells with an archive and no verdict — the worklist")
    q.add_argument("--since", type=float, default=0.0)
    q.add_argument("--arm")

    e = sub.add_parser("emit", help="print the evidence packet for one cell, then judge it yourself")
    e.add_argument("run_id")

    r = sub.add_parser("record", help="store a verdict (JSON on stdin) and write it onto the row")
    r.add_argument("run_id")

    s_ = sub.add_parser("show", help="show recorded usefulness judgments")
    s_.add_argument("--since", type=float, default=0.0)

    args = ap.parse_args()
    rows = _rs.read_rows(RESULTS)

    if args.cmd == "pending":
        want = [r for r in pending(rows)
                if r.get("started", 0) >= args.since
                and (not args.arm or f" {args.arm} " in f" {r.get('note', '')} ")]
        for r in want:
            print(f"{r['run_id']}\t{r['task']}\t{r['model']}\t"
                  f"{r.get('terminal') or ''}")
        if not want:
            print("(nothing pending)")
        return 0

    if args.cmd == "emit":
        row = next((x for x in rows if x.get("run_id") == args.run_id), None)
        if row is None:
            raise SystemExit(f"no row for {args.run_id}")
        print("=" * 78)
        print(SYSTEM.read_text().strip())
        print("=" * 78)
        print(evidence(row))
        return 0

    if args.cmd == "record":
        verdict = parse(sys.stdin.read())
        if verdict is None:
            raise SystemExit("expected usefulness_percent, reason, and evidence")
        v = record(args.run_id, verdict)
        print(f"{args.run_id}: {v['usefulness_percent']}% useful")
        return 0

    want = [r for r in rows
            if r.get("started", 0) >= args.since and "usefulness_percent" in r]
    print(f"{'task':22} {'model':17} usefulness")
    for r in want:
        print(f"{r['task']:22} {r['model']:17} {r['usefulness_percent']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
