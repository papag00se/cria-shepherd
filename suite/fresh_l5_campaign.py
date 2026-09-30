#!/usr/bin/env python3
"""Resumable, planner-off fresh L5 campaign manifest (never edits historical rows)."""
from __future__ import annotations
import argparse, json
from pathlib import Path
try:
    from .run import collect_capture
except ImportError:
    from run import collect_capture

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


def _valid_capture_evidence(row: dict) -> bool:
    """Require preserved request/response pairs whose phase inventory matches the row."""
    dirs = row.get("capture_dirs")
    if not isinstance(dirs, list) or not dirs:
        one = row.get("capture_dir")
        dirs = [one] if isinstance(one, str) and one else []
    if not all(isinstance(d, str) and d for d in dirs):
        return False
    responses = [p for d in dirs for p in Path(d).glob("*.response.json")]
    if not responses or row.get("calls") != len(responses):
        return False
    for response in responses:
        name = response.name
        request = response.with_name(name.removesuffix(".response.json") + ".json")
        try:
            req = json.loads(request.read_text())
            res = json.loads(response.read_text())
        except (OSError, ValueError):
            return False
        choices = res.get("choices") if isinstance(res, dict) else None
        filename_phase = name.split("-", 1)[1].removesuffix(".response.json") if "-" in name else ""
        body = req.get("body") if isinstance(req, dict) else None
        if (not isinstance(req, dict) or not filename_phase
                or req.get("phase") != filename_phase
                or not isinstance(body, dict) or not isinstance(body.get("messages"), list)
                or not isinstance(choices, list) or not choices
                or not isinstance(choices[0], dict)
                or not isinstance(choices[0].get("message"), dict)):
            return False
    captured = collect_capture([Path(d) for d in dirs])
    return captured.get("calls") == row.get("calls") and captured.get("phases") == row.get("phases")


def _eligible(row: dict, revision: str) -> bool:
    archive = Path(row.get("archive") or "")
    return (
        type(row.get("level")) is int and row["level"] == LEVEL
        and type(row.get("live_engagement_level")) is int and row["live_engagement_level"] == LEVEL
        and not row.get("superseded") and not row.get("aborted")
        and row.get("terminal") not in (None, "crashed-early")
        and row.get("workspace_lost") is False
        and (archive / "workspace").is_dir()
        and row.get("planner") == "off" and row.get("planner_enabled") is False
        and row.get("planner_phase_count") == 0
        and isinstance(row.get("phases"), dict) and row["phases"].get("planner", 0) == 0
        and str(row.get("note", "")).startswith("FRESH-L5 ")
        and row.get("revision") == revision
        and _valid_capture_evidence(row)
    )


def worklist(revision: str, result_rows=None):
    """Fresh cells only; requested settings never substitute for captured run evidence."""
    if not revision or any(c.isspace() for c in revision):
        raise ValueError("a fixed git revision is required")
    done = set()
    for row in result_rows if result_rows is not None else rows():
        if _eligible(row, revision):
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
