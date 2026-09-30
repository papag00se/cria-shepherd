#!/usr/bin/env python3
"""Resumable, planner-off fresh L5 campaign manifest (never edits historical rows)."""
from __future__ import annotations
import argparse, json
from pathlib import Path

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"
MANIFEST = SUITE / "results" / "fresh-l5-manifest.json"
MODELS = ("gemma4-qat", "bonsai2", "defiant-fable", "ornith1.5", "k2_horizon_7b", "phi4", "ling3-tiny", "qwen3.8_9b_distill", "nemotron-elastic")
TASKS = ("shipping-rates-rb", "cart-billing-go", "orders-api-py", "feed-pipeline-java", "handles-cli-node", "rust-toml-cli")
LEVEL = 5


def rows():
    if not RESULTS.exists():
        return []
    out = []
    for line in RESULTS.read_text(errors="replace").splitlines():
        try: out.append(json.loads(line))
        except ValueError: continue
    return out


def worklist(revision: str, result_rows=None):
    """Fresh, revision-pinned cells; only current non-superseded L5 rows satisfy a cell."""
    if not revision or any(c.isspace() for c in revision):
        raise ValueError("a fixed git revision is required")
    done = set()
    for row in result_rows if result_rows is not None else rows():
        phases = row.get("phases")
        if (row.get("level") is None or row.get("superseded") or row.get("planner") != "off"
                or row.get("planner_enabled") is not False or row.get("planner_phase_count") != 0
                or not isinstance(phases, dict) or phases.get("planner", 0) != 0):
            continue
        if (str(row.get("note", "")).startswith("FRESH-L5 ")
                and row.get("revision") == revision):
            done.add((row.get("model"), row.get("task")))
    return [{"model": m, "task": t, "level": LEVEL, "revision": revision, "planner": "off"}
            for m in MODELS for t in TASKS if (m, t) not in done]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--revision", required=True, help="immutable cria git revision for every cell")
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    args = ap.parse_args()
    cells = worklist(args.revision)
    payload = {"schema": 1, "level": LEVEL, "revision": args.revision, "planner": "off",
               "expected_cells": len(MODELS) * len(TASKS), "remaining": cells}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(payload, indent=2) + "\n")
    for cell in cells:
        print(f"{cell['model']}\t{cell['task']}\tL5\t{cell['revision']}\tplanner=off")
    print(f"manifest={args.manifest} remaining={len(cells)}")

if __name__ == "__main__": main()
