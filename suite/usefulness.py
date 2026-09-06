#!/usr/bin/env python3
"""Prepare and record an independent usefulness judgment for a finished cell.

The judge reads the task and delivered workspace with read-only tools and infers the percentage of
usefulness actually delivered. `--emit` writes the packet; `--record` stores the judgment. The
percentage is holistic: no task-specific executable grades or aggregate mechanical measures
participate in this path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import workspace_evidence


SUITE = Path(__file__).resolve().parent
ROOT = SUITE.parent
RESULTS = SUITE / "results" / "results.jsonl"


SYSTEM = SUITE / "prompts" / "usefulness_judge.txt"
PACKET_VERSION = "SUITE EVIDENCE PACKET: 2"

# The stop-looking line, in THIS judge's schema. See the call site.
ANSWER_NOW = ('You have inspected enough. Answer NOW with ONLY the JSON object: '
              '{"usefulness_percent": <integer from 0 through 100>, '
              '"reason": "<two evidence-based sentences>", '
              '"evidence": ["<specific inspected fact>"]}')


def _current_contract(text: str) -> str:
    """Remove retired task metadata from legacy frozen packets.

    New packets never contain it. Old packets can outlive their archive, though, and replaying a
    hand-authored deliverables list would quietly restore the second judgment contract this module
    removed. A legacy capped inventory is labelled partial because its missing paths cannot be
    recovered after the archive is gone.
    """
    if text.startswith(PACKET_VERSION + "\n"):
        return text
    before, marker, after = text.rpartition("\n\nTASK METADATA:\n")
    if marker:
        _metadata, workspace_marker, workspace = after.partition("\n\nWORKSPACE ARCHIVE ")
        if workspace_marker:
            text = before + workspace_marker + workspace
    if "… listing stopped at " in text:
        text = text.replace("EVERY VISIBLE FILE DELIVERED (on disk, with sizes):",
                            "PARTIAL LEGACY WORKSPACE TREE (the archived inventory was capped):")
    return text


def packet_path(run_id: str) -> Path:
    return PACKETS / f"{run_id}.txt"


def save_packet(row: dict) -> Path | None:
    """Freeze this row's evidence packet to disk while the workspace still exists — or None.

    The workspace is perishable, so its task, archive location, and complete visible file inventory
    are frozen while it is warm. Best-effort: packet failure must never fail a finished run."""
    try:
        text, _digest = evidence(row, _saved=False)
    except Exception:                                   # noqa: BLE001 — never fail a finished run
        return None
    PACKETS.mkdir(parents=True, exist_ok=True)
    out = packet_path(row["run_id"])
    out.write_text(text)
    return out


def evidence(row: dict, _saved: bool = True) -> tuple[str, str]:
    """`(evidence_text, digest)` — everything the judge is allowed to see, and its fingerprint.

    Prefers the packet frozen at run time (`save_packet`) when the archived workspace is gone, so a
    reaped workspace costs the run its judgeability only if nothing was saved. The digest is always
    recomputed against the CURRENT rubric, so a reworded rubric still invalidates old verdicts."""
    saved = packet_path(row.get("run_id", ""))
    ws_gone = not (Path(row.get("archive") or "") / "workspace").is_dir()
    if _saved and ws_gone and saved.is_file():
        text = _current_contract(saved.read_text(errors="replace"))
        stamp = text + "\n\n---RUBRIC---\n" + SYSTEM.read_text()
        return text, hashlib.sha1(stamp.encode("utf-8", "replace")).hexdigest()[:16]
    task_dir = SUITE / "tasks" / row["task"]
    ws = Path(row.get("archive") or "") / "workspace"
    prompt = (task_dir / "prompt.txt").read_text(errors="replace").strip()
    lines = [PACKET_VERSION, "", f"THE TASK THE CODER WAS GIVEN:\n{prompt}", "",
             f"WORKSPACE ARCHIVE (inspect it with read-only tools):\n{ws}", "",
             "COMPLETE WORKSPACE TREE (all entries; symlinks are not followed):\n"
             f"{workspace_evidence.tree(ws)}"]

    lines += ["", f"HOW THE SESSION ENDED: {row.get('terminal')} after {row.get('calls')} model "
                  f"calls and {round((row.get('wall_seconds') or 0) / 60, 1)} minutes."]
    text = "\n".join(lines)
    # The digest covers the RUBRIC as well as the evidence. Keying on evidence alone meant a reworded
    # prompt silently reused every verdict written under the old one — a cache that hides the change
    # it was supposed to make.
    stamp = text + "\n\n---RUBRIC---\n" + SYSTEM.read_text()
    return text, hashlib.sha1(stamp.encode("utf-8", "replace")).hexdigest()[:16]






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


VERDICTS = Path.home() / ".cria" / "suite" / "_usefulness"
# The evidence packet, saved AT RUN TIME. See save_packet.
PACKETS = Path.home() / ".cria" / "suite" / "_usefulness_evidence"


def verdict_path(run_id: str) -> Path:
    return VERDICTS / f"{run_id}.json"


def _needs_judging(row: dict) -> bool:
    """True when this row has no verdict, or has one written against DIFFERENT evidence or a
    DIFFERENT rubric.

    THE DIGEST EXISTED AND NOTHING READ IT. `record` stamps every verdict with a hash of the evidence
    AND the rubric text, and its own comment says why: "Keying on evidence alone meant a reworded
    prompt silently reused every verdict written under the old one — a cache that hides the change it
    was supposed to make." But the worklist asked only whether a verdict FILE exists, so a rewritten
    rubric changed nothing — every stale verdict stayed on its row, and the grid went on reporting
    numbers earned under a scale that no longer exists (#11b: a mechanism must reach what it judges).

    Found when the operator changed the judgment rubric, which invalidates every verdict written
    against the old rubric. A verdict with no stored digest is treated as stale: it
    predates the stamp, so nothing can vouch for what it was written against."""
    p = verdict_path(row["run_id"])
    if not p.exists():
        return True
    try:
        stored = json.loads(p.read_text()).get("evidence_digest")
    except (OSError, ValueError):
        return True
    return stored != evidence(row)[1]


def pending(rows: list[dict]) -> list[dict]:
    """Cells with an archive and no verdict — the worklist, computed from disk every time.

    THIS IS THE MEMORY. Not a note in a message and not something to hold in mind across 24 cells
    and a compaction: a cell is judged when its verdict file exists, and unjudged otherwise. A run
    that is interrupted, resumed, or picked up by a different session recomputes the same list."""
    return [r for r in rows
            # A SUPERSEDED row measured a rung that was not the one running; the cell re-runs and the
            # replacement is what gets judged. Judging the old one would spend the effort and then
            # attach a verdict to a measurement the grid already ignores.
            if not r.get("superseded")
            and (r.get("archive") or packet_path(r.get("run_id", "")).is_file())
            and _needs_judging(r)
            # …and only when the evidence can still be built: an archive on disk, or a packet frozen
            # at run time. A row with neither is unjudgeable for good and must not sit in the
            # worklist forever pretending otherwise (#5b).
            and ((Path(r.get("archive") or "") / "workspace").is_dir()
                 or packet_path(r.get("run_id", "")).is_file())]


def record(run_id: str, verdict: dict) -> dict:
    """Store an inferred usefulness percentage and attach its provenance to the row."""
    normalized = parse(json.dumps(verdict))
    if normalized is None:
        raise ValueError("final judgment requires usefulness_percent, reason, and evidence")
    v = {**normalized, "judged_by": verdict.get("judged_by", "campaign agent, full toolset")}
    rows = [json.loads(l) for l in RESULTS.read_text().splitlines() if l.strip()]
    row = next((r for r in rows if r.get("run_id") == run_id), None)
    if row is None:
        raise SystemExit(f"no row for {run_id}")
    v["evidence_digest"] = evidence(row)[1]
    VERDICTS.mkdir(parents=True, exist_ok=True)
    verdict_path(run_id).write_text(json.dumps(v, indent=1))
    out = []
    for r in rows:
        if r.get("run_id") == run_id:
            r = dict(r)
            r.pop("usefulness_judgment", None)
            r.update({"usefulness_percent": v["usefulness_percent"],
                      "usefulness_reason": v.get("reason", ""),
                      "usefulness_model": v["judged_by"]})
        out.append(json.dumps(r))
    RESULTS.write_text("\n".join(out) + "\n")
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
    rows = [json.loads(l) for l in RESULTS.read_text().splitlines() if l.strip()]

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
        print(evidence(row)[0])
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
