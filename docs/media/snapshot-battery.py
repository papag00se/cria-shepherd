"""Export the L0 and L5 tables of docs/battery-report.md as display data; never grade model output.

Run with --source-root when the campaign data lives in another checkout.
Only the reporting functions are called: no suite runs, services, or model calls.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import re
import sys

MEDIA = Path(__file__).resolve().parent
TASK_LABELS = ["ruby", "go", "python", "java", "node", "rust"]


def parse_report(report: str) -> dict:
    """Read displayed cells, including preserved history, without rebuilding selection logic."""
    levels = {}
    for level in (0, 5):
        match = re.search(rf"^## L{level} — (.+) — (\d+)%\n(.*?)(?=^## |\Z)", report, re.MULTILINE | re.DOTALL)
        if not match:
            raise ValueError(f"Missing reported level {level}")
        label, overall, section = match.groups()
        rows = []
        header = next([part.strip() for part in line.split("|")[1:-1]]
                      for line in section.splitlines() if line.startswith("| model |"))
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
    date = re.search(r"^Updated: (.+)$", report, re.M)
    data["report_date"] = date[1] if date else None
    (MEDIA / "battery-data.json").write_text(json.dumps(data, indent=2) + "\n")
    (MEDIA / "battery-report-snapshot.md").write_text(report)
    print("Saved the report and the L0/L5 display data.")


if __name__ == "__main__":
    main()
