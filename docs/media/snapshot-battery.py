"""Freeze L0/L5 from the project's authoritative report; never grade model output.

Run with --source-root when the campaign data lives in another checkout.
Only the reporting functions are called: no suite runs, services, or model calls.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import re
import subprocess
import sys

MEDIA = Path(__file__).resolve().parent
TASK_LABELS = ["ruby", "go", "python", "java", "node", "rust"]


def parse_report(report: str) -> dict:
    """Read displayed cells, including preserved history, without rebuilding selection logic."""
    levels = {}
    for level in (0, 5):
        match = re.search(rf"^### Level {level}(?: — ([^\n]+))? — (\d+)%\n(.*?)(?=^### |\Z)",
                          report, re.MULTILINE | re.DOTALL)
        if not match:
            raise ValueError(f"Missing reported level {level}")
        label, overall, section = match.groups()
        rows = []
        header = [part.strip() for part in section.splitlines()[1].split("|")[1:-1]]
        if header[1:7] != TASK_LABELS:
            raise ValueError(f"Unexpected report columns: {header}")
        for line in section.splitlines():
            if not line.startswith("| ") or line.startswith("| model |"):
                continue
            fields = [part.strip() for part in line.split("|")[1:-1]]
            if len(fields) != len(header):
                raise ValueError(f"Unexpected report row: {line}")
            cells = []
            for field in fields[1:7]:
                if field == "·":
                    cells.append(None)
                else:
                    score = re.fullmatch(r"[^\d]+(\d+)%", field)
                    if not score or not 0 <= int(score[1]) <= 100:
                        raise ValueError(f"Invalid reported cell: {field}")
                    cells.append(int(score[1]))
            rows.append({"model": fields[0], "cells": cells})
        if not rows or len({row['model'] for row in rows}) != len(rows):
            raise ValueError("Empty or duplicate model rows")
        values = [v for row in rows for v in row["cells"] if v is not None]
        if round(sum(values) / len(values)) != int(overall):
            raise ValueError("Displayed overall average disagrees with displayed cells")
        levels[str(level)] = {"reported_label": label, "overall": int(overall), "rows": rows}
    return {"task_labels": TASK_LABELS, "levels": levels}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=MEDIA.parents[1])
    args = parser.parse_args()
    root = args.source_root.resolve()
    sys.path.insert(0, str(root))
    status = importlib.import_module("suite.battery_status")
    report = status.report(status.rows())
    data = parse_report(report)
    data["model_order"] = list(status.DISPLAY)
    date = re.search(r"\*\*Last updated ([\d-]+ [\d:]+)\*\*", report)
    if not date:
        raise ValueError("Generated report has no date")
    inputs = ["suite/battery_status.py", "suite/model_names.py",
              "suite/historical_ladder.json", "suite/results/results.jsonl",
              "docs/audits/battery-report.md"]
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in inputs}
    data["provenance"] = {
        "recorded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "report_date": date[1],
        "report_timezone": datetime.now().astimezone().tzname(),
        "source_revision": subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                                          check=True, capture_output=True, text=True).stdout.strip(),
        "inference_anchor": status.REPORT_INFERENCE_REVISION,
        "source_sha256": hashes,
        "source_inputs_dirty": bool(subprocess.run(["git", "status", "--porcelain", "--", *inputs],
            cwd=root, check=True, capture_output=True, text=True).stdout.strip()),
        "metric": "Holistically inferred usefulness, not a task pass rate",
        "limits": "Mixed dates, revisions, model variants and historical planner settings; not controlled A/B. "
                  "Some recent full captures are unavailable in this checkout; this freezes reported "
                  "judgments, not a fresh re-audit of each run.",
    }
    (MEDIA / "battery-data.json").write_text(json.dumps(data, indent=2) + "\n")
    (MEDIA / "battery-report-snapshot.md").write_text(report)
    print("Saved the authoritative report and L0/L5 display data; no benchmark was run.")


if __name__ == "__main__":
    main()
